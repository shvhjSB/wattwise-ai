import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { ApiError } from '../../api/client';
import { fetchSummary } from '../../api/summary';
import { SummaryContext, type SummaryState } from './summaryContext';

/**
 * Loads the dashboard summary once and shares it, so the demo banner and the overview use one
 * request (D051). Plain hooks, not a server-state library: one resource, one reader at a time.
 */
export function SummaryProvider({ children }: { children: ReactNode }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<SummaryState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    fetchSummary(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: 'success', data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError('network', 'Unexpected error while loading the summary.', {
                cause: error,
              });
        setState({ status: 'error', error: apiError });
      },
    );
    return () => {
      controller.abort();
    };
  }, [attempt]);

  const retry = useCallback(() => {
    setState({ status: 'loading' });
    setAttempt((n) => n + 1);
  }, []);

  const value = useMemo(() => ({ state, retry }), [state, retry]);
  return <SummaryContext value={value}>{children}</SummaryContext>;
}
