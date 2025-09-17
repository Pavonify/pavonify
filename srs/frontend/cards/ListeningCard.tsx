import React from "react";
import { CardProps } from "../types";

export default function ListeningCard({ word, onSubmit }: CardProps) {
  const audioSrc = word.audio ? String(word.audio) : null;

  return (
    <div className="flex flex-col items-center gap-4">
      {audioSrc ? <audio src={audioSrc} controls className="w-full" /> : null}
      <button
        type="button"
        onClick={() => onSubmit(true)}
        className="px-4 py-2 rounded-lg bg-indigo-500 text-white shadow hover:bg-indigo-600"
      >
        Heard
      </button>
    </div>
  );
}
