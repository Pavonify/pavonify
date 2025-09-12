import React from 'react';

export default function MCQCard({ word, onSubmit }) {
  const choices = word.choices || [];
  return React.createElement(
    'div',
    null,
    choices.map(choice =>
      React.createElement(
        'button',
        {
          key: choice,
          onClick: () => onSubmit(choice === word.answer)
        },
        choice
      )
    )
  );
}
