import React from 'react';

export default function TappingCard({ word, onSubmit }) {
  return React.createElement(
    'div',
    { className: 'flex flex-col items-center gap-4' },
    React.createElement('p', { className: 'text-xl font-semibold text-slate-800' }, word?.prompt ?? ''),
    React.createElement(
      'button',
      {
        type: 'button',
        onClick: () => onSubmit(true),
        className: 'px-4 py-2 rounded-lg bg-purple-500 text-white shadow hover:bg-purple-600',
      },
      'Continue'
    )
  );
}
