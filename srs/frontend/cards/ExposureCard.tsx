import React from "react";
import { CardProps } from "../types";

export default function ExposureCard({ word, onSubmit }: CardProps) {
  return (
    <div className="flex flex-col items-center gap-4">
      <p className="text-xl font-semibold text-slate-800">{word.prompt ?? ""}</p>
      <button
        type="button"
        onClick={() => onSubmit(true)}
        className="px-4 py-2 rounded-lg bg-blue-500 text-white shadow hover:bg-blue-600"
      >
        Next
      </button>
    </div>
  );
}
