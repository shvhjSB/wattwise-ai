import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { isHealthResponse } from '../../api/health';
import { jsonResponse } from '../../test/http';
import { ApiHealthPanel } from '../health/ApiHealthPanel';
import { FeedbackForm } from './FeedbackForm';

const health = {
  status: 'ok',
  service: 'wattwise-api',
  version: '0.1.0',
  environment: 'production',
};

function stubHealth(body: object) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body)));
}

describe('FeedbackForm on the public demo', () => {
  it('replaces the form with a notice when the API is read-only', async () => {
    stubHealth({ ...health, read_only: true });

    render(<FeedbackForm alertId={1} onSaved={() => undefined} />);

    expect(await screen.findByRole('note')).toHaveTextContent(/public demo is read-only/i);
    expect(screen.queryByRole('button', { name: /save review/i })).not.toBeInTheDocument();
  });

  it('keeps the form when the API accepts reviews', async () => {
    stubHealth({ ...health, read_only: false });

    render(<FeedbackForm alertId={1} onSaved={() => undefined} />);

    expect(await screen.findByRole('button', { name: /save review/i })).toBeEnabled();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('says so in the API panel', async () => {
    stubHealth({ ...health, read_only: true });

    render(<ApiHealthPanel />);

    expect(await screen.findByText('Read-only public demo')).toBeInTheDocument();
  });
});

describe('isHealthResponse', () => {
  it('accepts an API with or without the read-only flag, and rejects a wrong type', () => {
    expect(isHealthResponse(health)).toBe(true);
    expect(isHealthResponse({ ...health, read_only: true })).toBe(true);
    expect(isHealthResponse({ ...health, read_only: 'yes' })).toBe(false);
  });
});
