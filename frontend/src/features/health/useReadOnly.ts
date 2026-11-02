import { useEffect, useState } from 'react';

import { fetchHealth } from '../../api/health';

/**
 * Whether the API is the read-only public demo. False until the health check answers, and false
 * if it fails: the server still refuses writes on the public demo, with a clear message.
 */
export function useReadOnly(): boolean {
  const [readOnly, setReadOnly] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal).then(
      (health) => {
        if (!controller.signal.aborted) setReadOnly(health.read_only === true);
      },
      () => undefined,
    );
    return () => {
      controller.abort();
    };
  }, []);

  return readOnly;
}
