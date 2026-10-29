import { useEffect, useState } from 'react';

import { fetchDataKinds, type DataKind } from '../../api/summary';

/**
 * The kinds of data stored (synthetic, observed), loaded once. `null` while loading or when the
 * summary is unavailable (for example no database): the shell then shows no banner, and the
 * pages that need data say why they have none.
 */
export function useDataKinds(): DataKind[] | null {
  const [kinds, setKinds] = useState<DataKind[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchDataKinds(controller.signal).then(
      (summary) => {
        if (!controller.signal.aborted) setKinds(summary.data_kinds);
      },
      () => {
        // Unavailable is not shown as an error here; the health panel reports the API's state.
      },
    );
    return () => {
      controller.abort();
    };
  }, []);

  return kinds;
}
