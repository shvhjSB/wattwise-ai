import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { jsonResponse } from '../../test/http';
import { ApiHealthPanel } from './ApiHealthPanel';

const healthy = {
  status: 'ok',
  service: 'wattwise-api',
  version: '0.1.0',
  environment: 'development',
};

describe('ApiHealthPanel', () => {
  it('shows a loading state while the health check is in flight', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>(() => undefined)),
    );

    render(<ApiHealthPanel />);

    expect(screen.getByRole('status')).toHaveTextContent(/checking the wattwise api/i);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows the service details when the API is healthy', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(healthy)));

    render(<ApiHealthPanel />);

    expect(await screen.findByText('Online')).toBeInTheDocument();
    expect(screen.getByText('wattwise-api')).toBeInTheDocument();
    expect(screen.getByText('0.1.0')).toBeInTheDocument();
    expect(screen.getByText('development')).toBeInTheDocument();
  });

  it('shows an error when the API is unreachable and recovers on retry', async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(jsonResponse(healthy));
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();

    render(<ApiHealthPanel />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(/api unavailable/i);
    expect(alert).toHaveTextContent(/could not reach the wattwise api/i);

    await user.click(screen.getByRole('button', { name: 'Retry' }));

    expect(await screen.findByText('Online')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('explains an HTTP failure from the API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'x' }, 503)));

    render(<ApiHealthPanel />);

    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
  });
});
