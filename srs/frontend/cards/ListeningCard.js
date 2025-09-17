import React from 'react';

export default function ListeningCard({ word, onSubmit }) {
  const audioSrc = word?.audio ? String(word.audio) : null;

  return React.createElement(
    'div',
    { className: 'flex flex-col items-center gap-4' },
    audioSrc ? React.createElement('audio', { src: audioSrc, controls: true, className: 'w-full' }) : null,
    React.createElement(
      'button',
      {
        type: 'button',
        onClick: () => onSubmit(true),
        className: 'px-4 py-2 rounded-lg bg-indigo-500 text-white shadow hover:bg-indigo-600',
      },
      'Heard'
    )
  );
}
