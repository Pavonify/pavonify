import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ExposureCard from './cards/ExposureCard.js';
import TappingCard from './cards/TappingCard.js';
import MCQCard from './cards/MCQCard.js';
import TypingCard from './cards/TypingCard.js';
import ListeningCard from './cards/ListeningCard.js';
import { GameHubProvider } from '../../frontend/src/gamehub/GameHubContext.js';
import { useEnergyMeter } from '../../frontend/src/gamehub/useEnergyMeter.js';
import EnergyMeter from '../../frontend/src/gamehub/EnergyMeter.js';
import GameLauncherModal from '../../frontend/src/gamehub/GameLauncherModal.js';

const PRACTICE_MODE = 'practice';

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) {
    const segment = parts.pop();
    if (segment) {
      return segment.split(';').shift() ?? null;
    }
  }
  return null;
}

function ReviewSessionInner({ fetchImpl = fetch }) {
  const fetchFn = fetchImpl;
  const [queue, setQueue] = useState([]);
  const [current, setCurrent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [sessionPoints, setSessionPoints] = useState(0);
  const [streak, setStreak] = useState(0);
  const { onQuestionResult } = useEnergyMeter();

  const jsonHeaders = useCallback(() => {
    const headers = { 'Content-Type': 'application/json' };
    const csrftoken = getCookie('csrftoken');
    if (csrftoken) {
      headers['X-CSRFToken'] = csrftoken;
    }
    return headers;
  }, []);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchFn('/api/srs/queue?limit=30&mode=mix', { credentials: 'include' });
      const data = await response.json();
      const items = Array.isArray(data) ? data : [];
      setQueue(items);
      setCurrent(items[0] ?? null);
    } catch (err) {
      console.error('Failed to load SRS queue', err);
      setError('Unable to load practice queue.');
      setQueue([]);
      setCurrent(null);
    } finally {
      setLoading(false);
    }
  }, [fetchFn]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  useEffect(() => {
    if (queue.length > 0) {
      setCurrent(queue[0]);
    } else {
      setCurrent(null);
    }
  }, [queue]);

  const handleResult = useCallback(
    async (correct, extra = {}) => {
      if (!current) {
        return;
      }

      const payload = {
        word_id: current.word_id,
        activity_type: current.suggested_next_activity,
        is_correct: correct,
        ...extra,
      };

      const remaining = queue.slice(1);
      setQueue(remaining);
      setCurrent(remaining[0] ?? null);

      const nextStreakValue = correct ? streak + 1 : 0;
      setStreak(nextStreakValue);
      onQuestionResult({ correct, streak: nextStreakValue });

      if (correct) {
        setSessionPoints(prev => prev + 10);
      }

      try {
        await fetchFn('/api/srs/attempt', {
          method: 'POST',
          headers: jsonHeaders(),
          credentials: 'include',
          body: JSON.stringify(payload),
        });
      } catch (err) {
        console.error('Failed to submit attempt', err);
      } finally {
        if (remaining.length === 0) {
          await loadQueue();
        }
      }
    },
    [current, fetchFn, jsonHeaders, loadQueue, onQuestionResult, queue, streak]
  );

  const card = useMemo(() => {
    if (!current) {
      return null;
    }
    const props = { word: current, onSubmit: handleResult };
    switch (current.suggested_next_activity) {
      case 'tapping':
        return React.createElement(TappingCard, props);
      case 'mcq':
        return React.createElement(MCQCard, props);
      case 'typing':
        return React.createElement(TypingCard, props);
      case 'listening':
        return React.createElement(ListeningCard, props);
      default:
        return React.createElement(ExposureCard, props);
    }
  }, [current, handleResult]);

  const fetchWords = useCallback(
    async mode => {
      const response = await fetchFn(`/api/srs/current-words?mode=${mode}`, {
        credentials: 'include',
      });
      if (!response.ok) {
        throw new Error('Failed to load current words');
      }
      const data = await response.json();
      if (!Array.isArray(data)) {
        throw new Error('Invalid words payload');
      }
      return data;
    },
    [fetchFn]
  );

  const postResult = useCallback(
    async body => {
      const response = await fetchFn('/api/srs/game-result', {
        method: 'POST',
        headers: jsonHeaders(),
        credentials: 'include',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error('Failed to record game result');
      }
    },
    [fetchFn, jsonHeaders]
  );

  const awardSession = useCallback(
    async body => {
      const response = await fetchFn('/api/srs/session-award', {
        method: 'POST',
        headers: jsonHeaders(),
        credentials: 'include',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error('Failed to apply session awards');
      }
      setSessionPoints(prev => prev + (body.pointsDelta ?? 0));
      if (body.streakDelta) {
        setStreak(prev => Math.max(prev + body.streakDelta, 0));
      }
    },
    [fetchFn, jsonHeaders]
  );

  const header = React.createElement(
    'div',
    { className: 'flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm' },
    React.createElement(
      'div',
      null,
      React.createElement('h2', { className: 'text-lg font-semibold text-slate-900' }, 'Practice Session'),
      React.createElement('p', { className: 'text-sm text-slate-500' }, `Session Points: ${sessionPoints}`),
      React.createElement('p', { className: 'text-sm text-slate-500' }, `Current Streak: ${streak}`)
    ),
    React.createElement(EnergyMeter, { onLaunch: () => setLauncherOpen(true) })
  );

  const errorBlock = error
    ? React.createElement('div', { className: 'rounded-lg bg-red-50 p-4 text-sm text-red-600' }, error)
    : null;

  const content = loading
    ? React.createElement('div', { className: 'text-center text-sm text-slate-500' }, 'Loading…')
    : card || React.createElement('div', { className: 'text-center text-sm text-slate-500' }, 'All done for now! 🎉');

  const board = React.createElement(
    'div',
    { className: 'min-h-[200px] rounded-2xl border border-slate-200 bg-white p-6 shadow-sm' },
    content
  );

  const modal = React.createElement(GameLauncherModal, {
    open: launcherOpen,
    onClose: () => setLauncherOpen(false),
    mode: PRACTICE_MODE,
    fetchWords,
    postResult,
    awardSession,
  });

  return React.createElement('div', { className: 'flex flex-col gap-4 p-4' }, header, errorBlock, board, modal);
}

export default function ReviewSession(props) {
  return React.createElement(
    GameHubProvider,
    null,
    React.createElement(ReviewSessionInner, props)
  );
}
