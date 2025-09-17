import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

function toSummary(entries, startedAt) {
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

export default function PeacockConveyorSorter({ words, timeLimitMs = 60000, onComplete }) {
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState([]);
  const [timeLeft, setTimeLeft] = useState(timeLimitMs);
  const completedRef = useRef(false);
  const startRef = useRef(Date.now());
  const resultsRef = useRef([]);

  const safeWords = useMemo(() => (Array.isArray(words) ? words : []), [words]);
  const currentWord = safeWords[index] ?? null;

  useEffect(() => {
    resultsRef.current = results;
  }, [results]);

  const finishGame = useCallback(
    entries => {
      if (completedRef.current) {
        return;
      }
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
      const remaining = Math.max(timeLimitMs - elapsed, 0);
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
    isCorrect => {
      if (!currentWord || completedRef.current) {
        return;
      }
      const entry = { word: currentWord, correct: isCorrect };
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

  const header = React.createElement(
    'div',
    { className: 'flex flex-wrap items-center justify-between gap-4 rounded-xl border border-slate-200 bg-slate-50 p-4' },
    React.createElement(
      'div',
      null,
      React.createElement('p', { className: 'text-sm font-semibold text-slate-700' }, 'Time Left'),
      React.createElement('p', { className: 'text-2xl font-bold text-slate-900' }, `${Math.max(secondsLeft, 0)}s`)
    ),
    React.createElement(
      'div',
      { className: 'flex gap-6' },
      React.createElement(
        'div',
        { className: 'text-center' },
        React.createElement('p', { className: 'text-xs uppercase tracking-wide text-slate-500' }, 'Fed'),
        React.createElement('p', { className: 'text-lg font-semibold text-emerald-600' }, correctCount)
      ),
      React.createElement(
        'div',
        { className: 'text-center' },
        React.createElement('p', { className: 'text-xs uppercase tracking-wide text-slate-500' }, 'Missed'),
        React.createElement('p', { className: 'text-lg font-semibold text-rose-500' }, wrongCount)
      )
    )
  );

  const wordContent = currentWord
    ? React.createElement(
        'div',
        { className: 'flex flex-col items-center gap-4' },
        React.createElement('p', { className: 'text-sm uppercase tracking-wide text-slate-500' }, 'Feed this word'),
        React.createElement('p', { className: 'text-2xl font-bold text-slate-900' }, currentWord.prompt ?? ''),
        currentWord.answer
          ? React.createElement(
              'p',
              { className: 'text-base text-slate-500' },
              `Target: ${currentWord.answer}`
            )
          : null,
        React.createElement(
          'div',
          { className: 'mt-4 flex w-full max-w-md flex-col gap-3 sm:flex-row' },
          React.createElement(
            'button',
            {
              type: 'button',
              onClick: () => markResult(true),
              className: 'flex-1 rounded-lg bg-emerald-500 px-4 py-2 text-white shadow hover:bg-emerald-600',
            },
            'Fed Correctly'
          ),
          React.createElement(
            'button',
            {
              type: 'button',
              onClick: () => markResult(false),
              className: 'flex-1 rounded-lg bg-rose-500 px-4 py-2 text-white shadow hover:bg-rose-600',
            },
            'Missed'
          )
        )
      )
    : React.createElement('div', { className: 'text-center text-sm text-slate-500' }, 'No words available.');

  const board = React.createElement(
    'div',
    { className: 'rounded-2xl border border-slate-200 bg-white p-6 shadow' },
    wordContent
  );

  const finishButton = React.createElement(
    'button',
    {
      type: 'button',
      onClick: () => finishGame(),
      className: 'self-center rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100',
    },
    'Finish Early'
  );

  return React.createElement('div', { className: 'flex flex-col gap-4' }, header, board, finishButton);
}
