import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type GameWord = {
  id?: string | number;
  prompt?: string;
  answer?: string;
  [key: string]: unknown;
};

export type MiniGameSummary = {
  score: number;
  accuracy: number;
  correct: number;
  wrong: number;
  wordsSeen: GameWord[];
  timeMs: number;
};

type MiniGameProps = {
  words: GameWord[];
  timeLimitMs?: number;
  onComplete: (summary: MiniGameSummary) => void;
};

type ResultEntry = {
  word: GameWord;
  correct: boolean;
};

function toSummary(entries: ResultEntry[], startedAt: number): MiniGameSummary {
  const correct = entries.filter(item => item.correct).length;
  const wrong = entries.length - correct;
  const total = entries.length;
  const accuracy = total > 0 ? correct / total : 0;
  const timeMs = Date.now() - startedAt;

  return {
    score: correct * 10,
    accuracy,
    correct,
    wrong,
    wordsSeen: entries.map(item => item.word),
    timeMs,
  };
}

const PeacockConveyorSorter: React.FC<MiniGameProps> = ({ words, timeLimitMs = 60000, onComplete }) => {
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState<ResultEntry[]>([]);
  const [timeLeft, setTimeLeft] = useState(timeLimitMs);
  const completedRef = useRef(false);
  const startRef = useRef(Date.now());
  const resultsRef = useRef<ResultEntry[]>([]);

  const safeWords = useMemo(() => (Array.isArray(words) ? words : []), [words]);
  const currentWord = safeWords[index] ?? null;

  useEffect(() => {
    resultsRef.current = results;
  }, [results]);

  const finishGame = useCallback(
    (entries?: ResultEntry[]) => {
      if (completedRef.current) return;
      const finalEntries = entries ?? resultsRef.current;
      completedRef.current = true;
      onComplete(toSummary(finalEntries, startRef.current));
    },
    [onComplete]
  );

  useEffect(() => {
    completedRef.current = false;
    startRef.current = Date.now();
    setResults([]);
    setIndex(0);
    setTimeLeft(timeLimitMs);
  }, [safeWords, timeLimitMs]);

  useEffect(() => {
    if (safeWords.length === 0 && !completedRef.current) {
      finishGame([]);
      return;
    }
    const update = () => {
      const elapsed = Date.now() - startRef.current;
      const remaining = Math.max((timeLimitMs ?? 60000) - elapsed, 0);
      setTimeLeft(remaining);
      if (remaining <= 0) {
        finishGame();
      }
    };
    update();
    const interval = window.setInterval(update, 250);
    return () => window.clearInterval(interval);
  }, [finishGame, safeWords.length, timeLimitMs]);

  const markResult = useCallback(
    (isCorrect: boolean) => {
      if (!currentWord || completedRef.current) return;
      const entry: ResultEntry = { word: currentWord, correct: isCorrect };
      setResults(prev => {
        const next = [...prev, entry];
        if (next.length >= safeWords.length) {
          window.setTimeout(() => finishGame(next), 0);
        }
        return next;
      });
      setIndex(prev => {
        const nextIndex = prev + 1;
        if (nextIndex >= safeWords.length) {
          return 0;
        }
        return nextIndex;
      });
    },
    [currentWord, finishGame, safeWords.length]
  );

  const correctCount = useMemo(() => results.filter(item => item.correct).length, [results]);
  const wrongCount = results.length - correctCount;
  const secondsLeft = Math.ceil(timeLeft / 1000);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <p className="text-sm font-semibold text-slate-700">Time Left</p>
          <p className="text-2xl font-bold text-slate-900">{Math.max(secondsLeft, 0)}s</p>
        </div>
        <div className="flex gap-6">
          <div className="text-center">
            <p className="text-xs uppercase tracking-wide text-slate-500">Fed</p>
            <p className="text-lg font-semibold text-emerald-600">{correctCount}</p>
          </div>
          <div className="text-center">
            <p className="text-xs uppercase tracking-wide text-slate-500">Missed</p>
            <p className="text-lg font-semibold text-rose-500">{wrongCount}</p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow">
        {currentWord ? (
          <div className="flex flex-col items-center gap-4">
            <p className="text-sm uppercase tracking-wide text-slate-500">Feed this word</p>
            <p className="text-2xl font-bold text-slate-900">{currentWord.prompt ?? ""}</p>
            {currentWord.answer ? (
              <p className="text-base text-slate-500">Target: {currentWord.answer}</p>
            ) : null}
            <div className="mt-4 flex w-full max-w-md flex-col gap-3 sm:flex-row">
              <button
                type="button"
                onClick={() => markResult(true)}
                className="flex-1 rounded-lg bg-emerald-500 px-4 py-2 text-white shadow hover:bg-emerald-600"
              >
                Fed Correctly
              </button>
              <button
                type="button"
                onClick={() => markResult(false)}
                className="flex-1 rounded-lg bg-rose-500 px-4 py-2 text-white shadow hover:bg-rose-600"
              >
                Missed
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center text-sm text-slate-500">No words available.</div>
        )}
      </div>

      <button
        type="button"
        onClick={() => finishGame()}
        className="self-center rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100"
      >
        Finish Early
      </button>
    </div>
  );
};

export default PeacockConveyorSorter;
