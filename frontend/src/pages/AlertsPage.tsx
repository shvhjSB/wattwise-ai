import {
  ALERT_KINDS,
  fetchAlerts,
  REVIEW_STATUSES,
  SEVERITIES,
  type AlertFilters as ApiFilters,
} from '../api/alerts';
import { useApi } from '../api/useApi';
import { useSearch } from '../design/routes';
import { EmptyState, PageHeader } from '../design/states';
import { AlertDetail } from '../features/alerts/AlertDetail';
import { AlertFilters, AlertQueue, type QueueFilterValues } from '../features/alerts/AlertQueue';
import { afterDay, startOfDay } from '../features/alerts/format';

const LIMIT = 25;
const FILTER_KEYS = ['severity', 'review', 'kind', 'signature', 'building', 'meter', 'from', 'to'];

function member<T extends string>(values: readonly T[], value: string | null): T | undefined {
  return value !== null && values.includes(value as T) ? (value as T) : undefined;
}

function pageOf(value: string | null): number {
  const parsed = Number(value ?? '0');
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function alertOf(value: string | null): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

function present(value: string | null): string | undefined {
  return value === null || value === '' ? undefined : value;
}

function initialFilters(params: URLSearchParams): QueueFilterValues {
  return {
    severity: params.get('severity') ?? '',
    review: params.get('review') ?? '',
    kind: params.get('kind') ?? '',
    signature: params.get('signature') ?? '',
    building: params.get('building') ?? '',
    meter: params.get('meter') ?? '',
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
  };
}

function apiFilters(params: URLSearchParams, page: number): ApiFilters {
  return {
    severity: member(SEVERITIES, params.get('severity')),
    review_status: member(REVIEW_STATUSES, params.get('review')),
    kind: member(ALERT_KINDS, params.get('kind')),
    signature: present(params.get('signature')),
    building_id: present(params.get('building')),
    meter_id: present(params.get('meter')),
    start: startOfDay(params.get('from') ?? undefined),
    end: afterDay(params.get('to') ?? undefined),
    limit: LIMIT,
    offset: page * LIMIT,
  };
}

/** Priority-ordered investigation queue and the selected alert's evidence and review workflow. */
export function AlertsPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const page = pageOf(params.get('page'));
  const filters = apiFilters(params, page);
  const requestKey = new URLSearchParams(
    Object.entries(filters).flatMap(([key, value]) =>
      value === undefined ? [] : [[key, String(value)]],
    ),
  ).toString();
  const queue = useApi(`alerts:${requestKey}`, (signal) => fetchAlerts(filters, signal));
  const requestedAlert = alertOf(params.get('alert'));
  const firstAlert =
    queue.state.status === 'success' ? queue.state.data.items[0]?.alert_id : undefined;
  const selected = requestedAlert ?? firstAlert ?? null;
  const filterValues = initialFilters(params);

  const applyFilters = (values: QueueFilterValues) => {
    setParams({
      alert: null,
      page: null,
      severity: values.severity || null,
      review: values.review || null,
      kind: values.kind || null,
      signature: values.signature || null,
      building: values.building.trim() || null,
      meter: values.meter.trim() || null,
      from: values.from || null,
      to: values.to || null,
    });
  };
  const clearFilters = () => {
    setParams(Object.fromEntries([...FILTER_KEYS, 'page', 'alert'].map((key) => [key, null])));
  };

  return (
    <>
      <PageHeader title="Alerts" summary={summary} />
      <div className="grid items-start gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <aside
          aria-label="Investigation queue"
          className="max-h-[75vh] min-w-0 space-y-4 overflow-auto rounded-xl border border-line bg-raised p-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)]"
        >
          <div>
            <h3 className="font-semibold">Investigation queue</h3>
            <p className="mt-1 text-xs text-muted">
              Highest priority first. Filter the queue without changing the stored alerts.
            </p>
          </div>
          <AlertFilters
            key={FILTER_KEYS.map((key) => params.get(key) ?? '').join('|')}
            initial={filterValues}
            onApply={applyFilters}
            onClear={clearFilters}
          />
          <AlertQueue
            state={queue.state}
            selected={selected}
            onSelect={(id) => {
              setParams({ alert: String(id) });
            }}
            onRetry={queue.retry}
            onPrevious={() => {
              setParams({ page: page <= 1 ? null : String(page - 1), alert: null });
            }}
            onNext={() => {
              setParams({ page: String(page + 1), alert: null });
            }}
          />
        </aside>
        <div className="min-w-0">
          {selected === null ? (
            <EmptyState title="Choose an alert">
              Select an alert from the priority queue to review its evidence and record a verdict.
            </EmptyState>
          ) : (
            <AlertDetail key={selected} alertId={selected} onQueueRefresh={queue.retry} />
          )}
        </div>
      </div>
    </>
  );
}
