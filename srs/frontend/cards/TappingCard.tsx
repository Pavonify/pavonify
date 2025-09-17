import React from "react";
import { CardProps } from "../types";

export default function TappingCard({ word, onSubmit }: CardProps) {
  return (
    <div className="flex flex-col items-center gap-4">
      <p className="text-xl font-semibold text-slate-800">{word.prompt ?? ""}</p>
      <button
        type="button"
        onClick={() => onSubmit(true)}
        className="px-4 py-2 rounded-lg bg-purple-500 text-white shadow hover:bg-purple-600"
      >
        Continue
      </button>
    </div>
  );
}
