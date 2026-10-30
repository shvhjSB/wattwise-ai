import { useState, type SyntheticEvent } from 'react';

import { ALERT_KINDS, REVIEW_STATUSES, SEVERITIES, type AlertSummary } from '../../api/alerts';
import { formatCount, formatEnergy } from '../../design/format';
import { ProvenanceBadge } from '../../design/Provenance';
import { EmptyState, ErrorState, LoadingState } from '../../design/states';
import { reviewLabel, sentence, utcHour, words } from './format';

export interface QueueFilterValues {
  severity: string;
  review: string;
  kind: string;
  signature: string;
  building: string;
  meter: string;
  from: string;
  to: string;
}

const SIGNATURES = [
  'data_fault',
  'flatline',
  'spike',
  'overnight_excess',
  'drift',
  'sustained',
  'unclassified',
];

const control =
  'min-w-0 w-full rounded-md border border-edge bg-raised px-2 py-1.5 text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent';

export function AlertFilters({
  initial,
  onApply,
  onClear,
}: {
  initial: QueueFilterValues;
  onApply: (values: QueueFilterValues) => void;
  onClear: () => void;
}) {
  const [values, setValues] = useState(initial);
  const set = (name: keyof QueueFilterValues, value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
  };
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    onApply(values);
  };
  return (
    <form
      onSubmit={submit}
      aria-label="Alert filters"
      className="space-y-3 border-b border-line pb-4"
    >
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="min-w-0 text-xs text-muted">
          Severity
          <select
            value={values.severity}
            onChange={(e) => {
              set('severity', e.target.value);
            }}
            className={control}
          >
            <option value="">All</option>
            {SEVERITIES.map((value) => (
              <option key={value} value={value}>
                {sentence(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-0 text-xs text-muted">
          Review status
          <select
            value={values.review}
            onChange={(e) => {
              set('review', e.target.value);
            }}
            className={control}
          >
            <option value="">All</option>
            {REVIEW_STATUSES.map((value) => (
              <option key={value} value={value}>
                {reviewLabel(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-0 text-xs text-muted">
          Alert kind
          <select
            value={values.kind}
            onChange={(e) => {
              set('kind', e.target.value);
            }}
            className={control}
          >
            <option value="">All</option>
            {ALERT_KINDS.map((value) => (
              <option key={value} value={value}>
                {sentence(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-0 text-xs text-muted">
          Pattern
          <select
            value={values.signature}
            onChange={(e) => {
              set('signature', e.target.value);
            }}
            className={control}
          >
            <option value="">All</option>
            {SIGNATURES.map((value) => (
              <option key={value} value={value}>
                {sentence(value)}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-0 text-xs text-muted">
          From date (UTC)
          <input
            type="date"
            value={values.from}
            onChange={(e) => {
              set('from', e.target.value);
            }}
            className={control}
          />
        </label>
        <label className="min-w-0 text-xs text-muted">
          Through date (UTC)
          <input
            type="date"
            value={values.to}
            onChange={(e) => {
              set('to', e.target.value);
            }}
            className={control}
          />
        </label>
      </div>
      <label className="block text-xs text-muted">
        Building ID
        <input
          value={values.building}
          onChange={(e) => {
            set('building', e.target.value);
          }}
          className={control}
        />
      </label>
      <label className="block text-xs text-muted">
        Meter ID
        <input
          value={values.meter}
          onChange={(e) => {
            set('meter', e.target.value);
          }}
          className={control}
        />
      </label>
      <div className="flex gap-2">
        <button
          type="submit"
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Apply filters
        </button>
        <button
          type="button"
          onClick={onClear}
          className="rounded-md border border-edge px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent"
        >
          Clear
        </button>
      </div>
    </form>
  );
}

function AlertRow({
  alert,
  selected,
  onSelect,
}: {
  alert: AlertSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const energy =
    alert.potential_excess_kwh === null ? null : formatEnergy(alert.potential_excess_kwh);
  return (
    <li>
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={`w-full rounded-lg border p-3 text-left focus-visible:outline-2 focus-visible:outline-accent ${selected ? 'border-accent bg-accent-soft' : 'border-line bg-raised hover:border-edge'}`}
      >
        <span className="flex items-start gap-2">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{alert.building_id}</span>
            <span className="block truncate text-xs text-muted">{alert.meter_id}</span>
          </span>
          <span className="rounded-full bg-sunken px-2 py-0.5 text-xs font-semibold tabular-nums">
            {alert.priority_score.toFixed(0)}
          </span>
        </span>
        <span className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
          <span className={alert.severity === 'high' ? 'font-semibold text-danger' : 'text-muted'}>
            {sentence(alert.severity)}
          </span>
          <span aria-hidden="true">/</span>
          <span>{words(alert.signature)}</span>
          <span aria-hidden="true">/</span>
          <span>{reviewLabel(alert.review_status)}</span>
        </span>
        <span className="mt-2 flex flex-wrap items-end justify-between gap-2 text-xs text-muted">
          <span>{utcHour(alert.start)}</span>
          {energy ? (
            <span>
              {energy.value} {energy.unit} potential
            </span>
          ) : (
            <span>Meter problem</span>
          )}
        </span>
        <span className="mt-2 flex items-center justify-between gap-2">
          <ProvenanceBadge kind={alert.data_kind} />
          {alert.feedback_count > 0 ? (
            <span className="text-xs text-muted">
              {formatCount(alert.feedback_count)} review{alert.feedback_count === 1 ? '' : 's'}
            </span>
          ) : null}
        </span>
      </button>
    </li>
  );
}

export function AlertQueue({
  state,
  selected,
  onSelect,
  onRetry,
  onPrevious,
  onNext,
}: {
  state: import('../../api/useApi').ApiState<import('../../api/catalog').Page<AlertSummary>>;
  selected: number | null;
  onSelect: (id: number) => void;
  onRetry: () => void;
  onPrevious: () => void;
  onNext: () => void;
}) {
  if (state.status === 'loading') return <LoadingState label="Loading alert queue..." />;
  if (state.status === 'error')
    return (
      <ErrorState
        title="The alert queue is unavailable"
        message={state.error.message}
        onRetry={onRetry}
      />
    );
  const page = state.data;
  if (page.items.length === 0)
    return (
      <EmptyState title="No alerts match">
        Change or clear the filters to widen the queue.
      </EmptyState>
    );
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Showing {formatCount(page.offset + 1)} to {formatCount(page.offset + page.items.length)} of{' '}
        {formatCount(page.total)}. Priority orders review; it is not a probability.
      </p>
      <ol className="space-y-2" aria-label="Alerts ordered by priority">
        {page.items.map((alert) => (
          <AlertRow
            key={alert.alert_id}
            alert={alert}
            selected={alert.alert_id === selected}
            onSelect={() => {
              onSelect(alert.alert_id);
            }}
          />
        ))}
      </ol>
      <div className="flex justify-between gap-2">
        <button
          type="button"
          disabled={page.offset === 0}
          onClick={onPrevious}
          className="rounded-md border border-edge px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={page.offset + page.items.length >= page.total}
          onClick={onNext}
          className="rounded-md border border-edge px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
