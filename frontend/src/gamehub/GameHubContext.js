import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

const GameHubContext = createContext(null);

export const useGameHub = () => {
  const ctx = useContext(GameHubContext);
  if (!ctx) {
    throw new Error("GameHubContext missing");
  }
  return ctx;
};

const KEY = "pavonify_gamehub_v1";

export function GameHubProvider({ children }) {
  const [energy, setEnergy] = useState(0);
  const [tokens, setTokens] = useState(0);
  const [maxTokens] = useState(3);

  useEffect(() => {
    const raw = localStorage.getItem(KEY);
    if (!raw) {
      return;
    }
    try {
      const value = JSON.parse(raw);
      setEnergy(Number.isFinite(value?.energy) ? value.energy : 0);
      setTokens(Number.isFinite(value?.tokens) ? value.tokens : 0);
    } catch (error) {
      console.warn("Failed to parse game hub state", error);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify({ energy, tokens }));
  }, [energy, tokens]);

  function gainEnergy(base, streak) {
    const bonus = streak >= 20 ? 2 : streak >= 10 ? 1 : 0;
    let next = energy + base + bonus;
    let newTokens = tokens;

    while (next >= 100 && newTokens < maxTokens) {
      next -= 100;
      newTokens += 1;
    }

    if (newTokens >= maxTokens) {
      next = Math.min(next, 99);
    }

    setEnergy(Math.round(next));
    setTokens(newTokens);
  }

  function consumeToken() {
    if (tokens <= 0) {
      return false;
    }
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

  return React.createElement(GameHubContext.Provider, { value }, children);
}
