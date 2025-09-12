import React, { useEffect, useState } from 'react';
import ExposureCard from './cards/ExposureCard.js';
import TappingCard from './cards/TappingCard.js';
import MCQCard from './cards/MCQCard.js';
import TypingCard from './cards/TypingCard.js';
import ListeningCard from './cards/ListeningCard.js';

export default function ReviewSession({ fetchImpl = fetch }) {
  const fetchFn = fetchImpl;
  const [queue, setQueue] = useState([]);
  const [current, setCurrent] = useState(null);

  useEffect(() => {
    fetchFn('/api/srs/queue?limit=30&mode=mix')
      .then(r => r.json())
      .then(setQueue);
  }, []);

  useEffect(() => {
    setCurrent(queue[0]);
  }, [queue]);

  function handleResult(is_correct, extra = {}) {
    if (!current) return Promise.resolve();
    const payload = {
      word_id: current.word_id,
      activity_type: current.suggested_next_activity,
      is_correct,
      ...extra
    };
    return fetchFn('/api/srs/attempt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).then(() => {
      const remaining = queue.slice(1);
      if (remaining.length === 0) {
        return fetchFn('/api/srs/queue?limit=30&mode=mix')
          .then(r => r.json())
          .then(setQueue);
      } else {
        setQueue(remaining);
      }
    });
  }

  if (!current) {
    return React.createElement('div', null, 'Loading');
  }

  const props = {
    word: current,
    onSubmit: (correct, extra) => handleResult(correct, extra)
  };

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
}
