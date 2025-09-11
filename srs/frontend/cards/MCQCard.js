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
          type: 'button',
          onClick: () => onSubmit(choice === word.answer),
          className: 'btn btn-primary m-1'
        },
        choice
      )
    )
  );
}
