import React, { useEffect, useState } from "react";
import { useGameHub } from "./GameHubContext";
import PeacockConveyorSorter, { GameWord } from "@/games/PeacockConveyorSorter";

type Mode = "practice" | "assignment";

type AwardBody = {
  pointsDelta: number;
  streakDelta: number;
  energyDelta: number;
  tokensDelta: number;
};

type Props = {
  open: boolean;
  onClose: () => void;
  mode: Mode;
  fetchWords: (mode: Mode) => Promise<GameWord[]>;
  postResult: (body: unknown) => Promise<void>;
  awardSession: (body: AwardBody) => Promise<void>;
};

export default function GameLauncherModal({
  open,
  onClose,
  mode,
  fetchWords,
  postResult,
  awardSession,
}: Props) {
  const { consumeToken } = useGameHub();
  const [words, setWords] = useState<GameWord[] | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    if (!consumeToken()) {
      onClose();
      return;
    }
    fetchWords(mode)
      .then(setWords)
      .catch(() => setWords([]));
    setStartedAt(Date.now());
  }, [open, consumeToken, fetchWords, mode, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-3xl shadow-2xl p-4 w-full max-w-3xl">
        {!words ? (
          <div className="p-10 text-center">Loading words…</div>
        ) : (
          <PeacockConveyorSorter
            words={words}
            timeLimitMs={90000}
            onComplete={async summary => {
              const payload = {
                gameKey: "peacock-conveyor",
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
            }}
          />
        )}
      </div>
    </div>
  );
}
