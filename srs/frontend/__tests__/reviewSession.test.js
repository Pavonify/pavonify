import React from 'react';
import { render, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';
import ReviewSession from '../ReviewSession.js';

test('ReviewSession posts attempt and advances queue', async () => {
  const queue = [
    { word_id: 1, prompt: 'hola', suggested_next_activity: 'mcq', choices: ['hola', 'adios'], answer: 'hola' },
    { word_id: 2, prompt: 'adios', suggested_next_activity: 'mcq', choices: ['adios', 'hola'], answer: 'adios' }
  ];
  document.cookie = 'csrftoken=testtoken';
  const fetchMock = jest
    .fn()
    .mockResolvedValueOnce({ json: () => Promise.resolve(queue) })
    .mockResolvedValueOnce({ json: () => Promise.resolve({}) });

  const { getByText } = render(React.createElement(ReviewSession, { fetchImpl: fetchMock }));

  await waitFor(() => getByText('hola'));
  fireEvent.click(getByText('hola'));
  expect(fetchMock).toHaveBeenCalledWith(
    '/api/srs/attempt',
    expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      headers: expect.objectContaining({ 'X-CSRFToken': 'testtoken' })
    })
  );
  await waitFor(() => getByText('adios'));
});
