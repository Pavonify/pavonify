import React, { useEffect, useState } from 'react';
import ExposureCard from './cards/ExposureCard.js';
import TappingCard from './cards/TappingCard.js';
import MCQCard from './cards/MCQCard.js';
import TypingCard from './cards/TypingCard.js';
import ListeningCard from './cards/ListeningCard.js';

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

export default function ReviewSession({ fetchImpl = fetch }) {
  const fetchFn = fetchImpl;
  const [queue, setQueue] = useState([]);
  const [current, setCurrent] = useState(null);

  useEffect(() => {
    fetchFn('/api/srs/queue?limit=30&mode=mix', { credentials: 'include' })
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
    const remaining = queue.slice(1);
    setQueue(remaining);
    setCurrent(remaining[0] || null);

    const csrftoken = getCookie('csrftoken');
    const headers = { 'Content-Type': 'application/json' };
    if (csrftoken) headers['X-CSRFToken'] = csrftoken;

    return fetchFn('/api/srs/attempt', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      credentials: 'include'
    }).then(() => {
      if (remaining.length === 0) {
        return fetchFn('/api/srs/queue?limit=30&mode=mix', { credentials: 'include' })
          .then(r => r.json())
          .then(setQueue);
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
