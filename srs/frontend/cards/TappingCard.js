import React from 'react';

export default function TappingCard({ word, onSubmit }) {
  return React.createElement('div', null, [
    React.createElement('p', { key: 'prompt' }, word.prompt || ''),
    React.createElement(
      'button',
      { key: 'btn', type: 'button', onClick: () => onSubmit(true), className: 'btn btn-primary' },
      'Continue'
    )
  ]);
}
