import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';
import ExposureCard from '../cards/ExposureCard.js';
import TappingCard from '../cards/TappingCard.js';
import MCQCard from '../cards/MCQCard.js';
import TypingCard from '../cards/TypingCard.js';
import ListeningCard from '../cards/ListeningCard.js';

test('ExposureCard submits', () => {
  const fn = jest.fn();
  const { getByText } = render(React.createElement(ExposureCard, { word: { prompt: 'hi' }, onSubmit: fn }));
  fireEvent.click(getByText('Next'));
  expect(fn).toHaveBeenCalledWith(true);
});

test('TappingCard submits', () => {
  const fn = jest.fn();
  const { getByText } = render(React.createElement(TappingCard, { word: { prompt: 'hi' }, onSubmit: fn }));
  fireEvent.click(getByText('Continue'));
  expect(fn).toHaveBeenCalledWith(true);
});

test('MCQCard submits correct', () => {
  const fn = jest.fn();
  const { getByText } = render(React.createElement(MCQCard, { word: { answer: 'a', choices: ['a', 'b'] }, onSubmit: fn }));
  fireEvent.click(getByText('a'));
  expect(fn).toHaveBeenCalledWith(true);
});

test('TypingCard submits', () => {
  const fn = jest.fn();
  const { getByText, getByRole } = render(React.createElement(TypingCard, { word: { answer: 'cat' }, onSubmit: fn }));
  fireEvent.change(getByRole('textbox'), { target: { value: 'cat' } });
  fireEvent.click(getByText('Check'));
  expect(fn).toHaveBeenCalledWith(true, { user_answer: 'cat' });
});

test('ListeningCard submits', () => {
  const fn = jest.fn();
  const { getByText } = render(React.createElement(ListeningCard, { word: { audio: 'a.mp3' }, onSubmit: fn }));
  fireEvent.click(getByText('Heard'));
  expect(fn).toHaveBeenCalledWith(true);
});
