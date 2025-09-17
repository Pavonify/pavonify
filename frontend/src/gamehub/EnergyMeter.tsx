import React from "react";
import { useGameHub } from "./GameHubContext";

type Props = {
  onLaunch: () => void;
};

export default function EnergyMeter({ onLaunch }: Props) {
  const { energy, tokens, maxTokens } = useGameHub();
  const pct = Math.min(100, energy);
  const canLaunch = tokens > 0;

  return (
    <div className="flex items-center gap-3">
      <div className="relative w-36 h-5 bg-sky-100 rounded-full overflow-hidden">
        <div className="h-full bg-sky-400 transition-all" style={{ width: `${pct}%` }} />
        <div className="absolute inset-0 flex items-center justify-center text-xs font-semibold">
          {pct}% Energy
        </div>
      </div>
      <button
        aria-label="Mini-game launcher"
        className={`px-3 py-1 rounded-xl shadow ${canLaunch ? "bg-emerald-500 text-white hover:scale-105" : "bg-gray-200 text-gray-500"}`}
        disabled={!canLaunch}
        onClick={onLaunch}
      >
        🎮 x{tokens}/{maxTokens}
      </button>
    </div>
  );
}
