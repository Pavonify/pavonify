import React, { useEffect, useState } from 'react';

export default function MyWordsPage({ fetchImpl = fetch }) {
  const [words, setWords] = useState([]);

  useEffect(() => {
    fetchImpl('/api/srs/my-words?filter=all', { credentials: 'include' })
      .then(r => r.json())
      .then(data => setWords(data.results || data));
  }, [fetchImpl]);

  return React.createElement(
    'div',
    null,
    words.map(w =>
      React.createElement('div', { key: w.word_id }, `${w.prompt || ''}: ${w.status} (${w.strength || 0})`)
    )
  );
}
