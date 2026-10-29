import { createContext } from 'react';

import type { ApiError } from '../../api/client';
import type { DashboardSummary } from '../../api/summary';

export type SummaryState =
  | { status: 'loading' }
  | { status: 'success'; data: DashboardSummary }
  | { status: 'error'; error: ApiError };

export interface SummaryContextValue {
  state: SummaryState;
  retry: () => void;
}

export const SummaryContext = createContext<SummaryContextValue | null>(null);
