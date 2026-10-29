import { useCallback, useEffect, useState } from 'react';

import { ApiError } from './client';

export type ApiState<T> =
  { status: 'loading' } | { status: 'success'; data: T } | { status: 'error'; error: ApiError };

interface Settled<T> {
  key: string;
  attempt: number;
  state: Exclude<ApiState<T>, { status: 'loading' }>;
}

/**
 * Load a resource when `key` changes (and on retry), aborting the request in flight when the key
 * changes or the component unmounts. `key` is any string that identifies the request; `load` may
 * close over what it needs. A `null` key means "nothing to load" and stays in `loading`.
 *
 * The state is `loading` whenever the settled result belongs to another key or attempt, so a
 * changed key never shows the previous resource's data.
 */
export function useApi<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
): { state: ApiState<T>; retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted)
          setSettled({ key, attempt, state: { status: 'success', data } });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError('network', 'Unexpected error while contacting the WattWise API.', {
                cause: error,
              });
        setSettled({ key, attempt, state: { status: 'error', error: apiError } });
      },
    );
    return () => {
      controller.abort();
    };
    // `load` is intentionally not a dependency: `key` identifies what it loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);

  const state: ApiState<T> =
    settled !== null && settled.key === key && settled.attempt === attempt
      ? settled.state
      : { status: 'loading' };
  return { state, retry };
}
