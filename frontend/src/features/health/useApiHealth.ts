import { useCallback, useEffect, useState } from 'react';

import { ApiError } from '../../api/client';
import { fetchHealth, type HealthResponse } from '../../api/health';

export type ApiHealthState =
  | { status: 'loading' }
  | { status: 'success'; data: HealthResponse }
  | { status: 'error'; error: ApiError };

/** Load the API liveness status once on mount, with a manual retry. */
export function useApiHealth(): { state: ApiHealthState; retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<ApiHealthState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: 'success', data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError('network', 'Unexpected error while contacting the WattWise API.', {
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

  return { state, retry };
}
