import React, { useEffect, useState } from 'react';

export default function MyWordsPage({ fetchImpl = fetch }) {
  const fetchFn = fetchImpl;
  const [words, setWords] = useState([]);

  useEffect(() => {
    fetchFn('/api/srs/my-words?filter=all', { credentials: 'include' })
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
