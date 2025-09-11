import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { jest } from '@jest/globals';
import MyWordsPage from '../MyWordsPage.js';

test('MyWordsPage fetches with credentials and CSRF header', async () => {
  document.cookie = 'csrftoken=abc';
  const fetchMock = jest.fn().mockResolvedValue({ json: () => Promise.resolve([]) });
  render(React.createElement(MyWordsPage, { fetchImpl: fetchMock }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  const opts = fetchMock.mock.calls[0][1];
  expect(opts.credentials).toBe('include');
  expect(opts.headers['X-CSRFToken']).toBe('abc');
});
