import React from 'react';

export default function ListeningCard({ word, onSubmit }) {
  return React.createElement('div', null, [
    word.audio ? React.createElement('audio', { key: 'audio', src: word.audio, controls: true }) : null,
    React.createElement(
      'button',
      { key: 'btn', type: 'button', onClick: () => onSubmit(true), className: 'btn btn-primary' },
      'Heard'
    )
  ]);
}
