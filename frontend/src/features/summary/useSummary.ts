import { useContext } from 'react';

import type { StoredKind } from '../../api/summary';
import { SummaryContext, type SummaryContextValue } from './summaryContext';

/** The shared dashboard summary and a retry. Must be used inside `SummaryProvider`. */
export function useSummary(): SummaryContextValue {
  const value = useContext(SummaryContext);
  if (value === null) throw new Error('useSummary must be used inside SummaryProvider');
  return value;
}

/**
 * The kinds of data stored, or `null` while loading or when the summary is unavailable (for
 * example no database): the shell then shows no banner, and the pages that need data say why they
 * have none.
 */
export function useDataKinds(): StoredKind[] | null {
  const { state } = useSummary();
  return state.status === 'success' ? state.data.data_kinds : null;
}
