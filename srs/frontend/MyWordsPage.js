import React, { useEffect, useState } from 'react';

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}

export default function MyWordsPage({ fetchImpl = fetch }) {
  const fetchFn = fetchImpl;
  const [words, setWords] = useState([]);

  useEffect(() => {
    const csrftoken = getCookie('csrftoken');
    const headers = {};
    if (csrftoken) headers['X-CSRFToken'] = csrftoken;
    fetchFn('/api/srs/my-words?filter=all', { credentials: 'include', headers })
      .then(r => r.json())
      .then(data => setWords(data.results || data));
  }, []);

  return React.createElement(
    'div',
    null,
    words.map(w =>
      React.createElement('div', { key: w.word_id }, `${w.prompt || ''}: ${w.status} (${w.strength || 0})`)
    )
  );
}
