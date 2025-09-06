import React from 'react';

export default function ExposureCard({ word, onSubmit }) {
  return React.createElement('div', null, [
    React.createElement('p', { key: 'prompt' }, word.prompt || ''),
    React.createElement('button', { key: 'btn', onClick: () => onSubmit(true) }, 'Next')
  ]);
}
