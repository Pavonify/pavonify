import React, { useState } from 'react';

export default function TypingCard({ word, onSubmit }) {
  const [value, setValue] = useState('');

  function handleSubmit(event) {
    event.preventDefault();
    const expected = (word?.answer ?? '').toString().trim().toLowerCase();
    const guess = value.trim().toLowerCase();
    onSubmit(guess === expected, { user_answer: value });
  }

  return React.createElement(
    'form',
    { onSubmit: handleSubmit, className: 'flex flex-col items-center gap-3' },
    React.createElement('input', {
      value,
      onChange: event => setValue(event.target.value),
      className: 'w-full max-w-xs rounded border border-slate-300 px-3 py-2',
      'aria-label': 'Type your answer',
    }),
    React.createElement(
      'button',
      {
        type: 'submit',
        className: 'px-4 py-2 rounded-lg bg-emerald-500 text-white shadow hover:bg-emerald-600',
      },
      'Check'
    )
  );
}
