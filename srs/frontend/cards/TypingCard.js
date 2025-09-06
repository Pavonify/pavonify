import React, { useState } from 'react';

export default function TypingCard({ word, onSubmit }) {
  const [value, setValue] = useState('');
  function handleSubmit(e) {
    e.preventDefault();
    onSubmit(value.trim().toLowerCase() === (word.answer || '').toLowerCase(), { user_answer: value });
  }
  return React.createElement(
    'form',
    { onSubmit: handleSubmit },
    [
      React.createElement('input', {
        key: 'input',
        value,
        onChange: e => setValue(e.target.value)
      }),
      React.createElement('button', { key: 'btn', type: 'submit' }, 'Check')
    ]
  );
}
