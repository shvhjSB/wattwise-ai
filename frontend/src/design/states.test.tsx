import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { EmptyState, ErrorState, LoadingState, PageHeader } from './states';

describe('LoadingState', () => {
  it('announces what is loading', () => {
    render(<LoadingState label="Loading alerts…" />);

    expect(screen.getByRole('status')).toHaveTextContent('Loading alerts…');
  });
});

describe('EmptyState', () => {
  it('says what is missing, why, and what to do', () => {
    render(
      <EmptyState title="No alerts" action={<button type="button">Load data</button>}>
        No alerts have been loaded.
      </EmptyState>,
    );

    expect(screen.getByText('No alerts')).toBeInTheDocument();
    expect(screen.getByText('No alerts have been loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Load data' })).toBeInTheDocument();
  });

  it('works with just a title', () => {
    render(<EmptyState title="Nothing here" />);

    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });
});

describe('ErrorState', () => {
  it('is announced as an alert with its message', () => {
    render(<ErrorState title="API unavailable" message="Could not reach the WattWise API." />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('API unavailable');
    expect(alert).toHaveTextContent('Could not reach the WattWise API.');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('offers a retry that calls back', async () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Failed" message="Try again." onRetry={onRetry} />);

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('PageHeader', () => {
  it('shows a second-level heading and the summary', () => {
    render(<PageHeader title="Alerts" summary="The investigation queue." />);

    expect(screen.getByRole('heading', { level: 2, name: 'Alerts' })).toBeInTheDocument();
    expect(screen.getByText('The investigation queue.')).toBeInTheDocument();
  });
});
