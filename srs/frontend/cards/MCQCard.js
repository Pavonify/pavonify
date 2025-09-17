import React from 'react';

export default function MCQCard({ word, onSubmit }) {
  const choices = Array.isArray(word?.choices) ? word.choices : [];

  return React.createElement(
    'div',
    { className: 'grid gap-2' },
    choices.map(choice => {
      const label = String(choice);
      return React.createElement(
        'button',
        {
          key: label,
          type: 'button',
          onClick: () => onSubmit(label === (word?.answer ?? '')),
          className: 'px-4 py-2 rounded-lg border border-slate-300 hover:bg-slate-100',
        },
        label
      );
    })
  );
}
