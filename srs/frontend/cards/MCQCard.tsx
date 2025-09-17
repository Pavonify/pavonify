import React from "react";
import { CardProps } from "../types";

export default function MCQCard({ word, onSubmit }: CardProps) {
  const choices = Array.isArray(word.choices) ? word.choices : [];

  return (
    <div className="grid gap-2">
      {choices.map(choice => {
        const label = String(choice);
        return (
          <button
            key={label}
            type="button"
            onClick={() => onSubmit(label === (word.answer ?? ""))}
            className="px-4 py-2 rounded-lg border border-slate-300 hover:bg-slate-100"
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
