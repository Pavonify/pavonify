import React, { useEffect, useState } from "react";
import { useGameHub } from "./GameHubContext.js";
import PeacockConveyorSorter from "../games/PeacockConveyorSorter.js";

export default function GameLauncherModal({
  open,
  onClose,
  mode,
  fetchWords,
  postResult,
  awardSession,
}) {
  const { consumeToken } = useGameHub();
  const [words, setWords] = useState(null);
  const [startedAt, setStartedAt] = useState(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (!consumeToken()) {
      onClose();
      return;
    }
    fetchWords(mode)
      .then(setWords)
      .catch(() => setWords([]));
    setStartedAt(Date.now());
  }, [open, consumeToken, fetchWords, mode, onClose]);

  if (!open) {
    return null;
  }

  const content = !words
    ? React.createElement('div', { className: 'p-10 text-center' }, 'Loading words…')
    : React.createElement(PeacockConveyorSorter, {
        words,
        timeLimitMs: 90000,
        onComplete: async summary => {
          const payload = {
            gameKey: 'peacock-conveyor',
            ...summary,
            startedAt,
            endedAt: Date.now(),
            mode,
          };
          try {
            await postResult(payload);
            const points = summary.score;
            const streakDelta = summary.accuracy >= 0.9 && summary.correct >= 15 ? 5 : 0;
            await awardSession({
              pointsDelta: points,
              streakDelta,
              energyDelta: 0,
              tokensDelta: 0,
            });
          } finally {
            onClose();
          }
        },
      });

  return React.createElement(
    'div',
    { className: 'fixed inset-0 bg-black/40 flex items-center justify-center z-50' },
    React.createElement('div', { className: 'bg-white rounded-3xl shadow-2xl p-4 w-full max-w-3xl' }, content)
  );
}
