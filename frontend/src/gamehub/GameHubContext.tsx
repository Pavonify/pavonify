import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

export type HubState = {
  energy: number;
  tokens: number;
  maxTokens: number;
  gainEnergy: (base: number, streak: number) => void;
  consumeToken: () => boolean;
  resetEnergy: () => void;
  setEnergy: (n: number) => void;
};

const GameHubContext = createContext<HubState | null>(null);

export const useGameHub = () => {
  const ctx = useContext(GameHubContext);
  if (!ctx) throw new Error("GameHubContext missing");
  return ctx;
};

const KEY = "pavonify_gamehub_v1";

export function GameHubProvider({ children }: { children: React.ReactNode }) {
  const [energy, setEnergy] = useState(0);
  const [tokens, setTokens] = useState(0);
  const [maxTokens] = useState(3);

  useEffect(() => {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      try {
        const v = JSON.parse(raw) as { energy?: unknown; tokens?: unknown };
        const storedEnergy = typeof v.energy === "number" && Number.isFinite(v.energy) ? v.energy : 0;
        const storedTokens = typeof v.tokens === "number" && Number.isFinite(v.tokens) ? v.tokens : 0;
        setEnergy(storedEnergy);
        setTokens(storedTokens);
      } catch (error) {
        console.warn("Failed to restore game hub state", error);
      }
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify({ energy, tokens }));
  }, [energy, tokens]);

  function gainEnergy(base: number, streak: number) {
    const bonus = streak >= 20 ? 2 : streak >= 10 ? 1 : 0;
    let next = energy + base + bonus;
    let newTokens = tokens;

    while (next >= 100 && newTokens < maxTokens) {
      next -= 100;
      newTokens += 1;
    }

    if (newTokens >= maxTokens) next = Math.min(next, 99);
    setEnergy(Math.round(next));
    setTokens(newTokens);
  }

  function consumeToken() {
    if (tokens <= 0) return false;
    setTokens(prev => Math.max(prev - 1, 0));
    return true;
  }

  function resetEnergy() {
    setEnergy(0);
  }

  const value = useMemo(
    () => ({
      energy,
      tokens,
      maxTokens,
      gainEnergy,
      consumeToken,
      resetEnergy,
      setEnergy,
    }),
    [energy, tokens, maxTokens]
  );

  return <GameHubContext.Provider value={value}>{children}</GameHubContext.Provider>;
}
