import { useState } from 'react';

import { fetchBuildings } from '../api/catalog';
import {
  fetchMachines,
  type MachineComparison,
  type MachineQuery,
  type MeterComparison,
} from '../api/machines';
import { useApi } from '../api/useApi';
import { formatDate, formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { useSearch } from '../design/routes';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../design/states';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm';
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DEFAULT_DAYS = [0, 1, 2, 3, 4];
const DEFAULT_FROM = 6;
const DEFAULT_TO = 18;

function kwh(value: number): string {
  return `${value.toLocaleString('en', { maximumFractionDigits: 1 })} kWh`;
}

function hour(value: number): string {
  return `${String(value).padStart(2, '0')}:00`;
}

/** Opening days from the URL (`days=0,1,2`), or the default when absent or invalid. */
function daysOf(raw: string | null): number[] {
  if (raw === null) return DEFAULT_DAYS;
  const parsed = raw.split(',').map(Number);
  const valid = parsed.every((d) => Number.isInteger(d) && d >= 0 && d <= 6);
  return valid && parsed.length ? [...new Set(parsed)].sort((a, b) => a - b) : DEFAULT_DAYS;
}

function hourOf(raw: string | null, fallback: number, min: number, max: number): number {
  const value = raw === null ? NaN : Number(raw);
  return Number.isInteger(value) && value >= min && value <= max ? value : fallback;
}

function Row({
  meter,
  share,
  strong,
}: {
  meter: MeterComparison;
  share: number | null;
  strong?: boolean;
}) {
  return (
    <tr className={`border-t border-line align-top ${strong ? 'font-semibold' : ''}`}>
      <th scope="row" className="py-2 pr-4 text-left font-medium break-all">
        {meter.meter_id}
        {meter.negative_hours > 0 ? (
          <span className="block text-xs font-normal text-synthetic">
            {meter.negative_hours.toLocaleString('en')} hours below zero ({kwh(meter.negative_kwh)}
            ), included as recorded: check this meter
          </span>
        ) : null}
      </th>
      <td className="py-2 pr-4 text-right tabular-nums">{kwh(meter.energy_kwh)}</td>
      <td className="py-2 pr-4 text-right tabular-nums">
        {share === null ? '—' : formatShare(share)}
      </td>
      <td className="py-2 pr-4 text-right tabular-nums">
        {meter.running_hours.toLocaleString('en')} h
      </td>
      <td className="py-2 pr-4 text-right tabular-nums">
        {kwh(meter.closed_kwh)}
        {meter.closed_share === null ? null : (
          <span className="block text-xs text-muted">
            {formatShare(meter.closed_share)} of its use
          </span>
        )}
      </td>
      <td className="py-2 pr-4 text-right tabular-nums">{kwh(meter.peak_kwh)}</td>
      <td className="py-2 text-right tabular-nums">{meter.events.toLocaleString('en')}</td>
    </tr>
  );
}

function Comparison({
  data,
  onMain,
}: {
  data: MachineComparison;
  onMain: (meter: string) => void;
}) {
  const header = (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <ProvenanceBadge kind={data.data_kind} />
      <span className="font-medium">{data.dataset_name}</span>
      <span className="text-muted">
        {data.first_reading && data.last_reading
          ? `${formatDate(data.first_reading)} to ${formatDate(data.last_reading)} (UTC) · `
          : ''}
        local time {data.timezone}
      </span>
    </div>
  );
  if (!data.available || data.main === null) {
    return (
      <section aria-label="Machine comparison" className="space-y-4">
        {header}
        <EmptyState title="No comparison for this building">
          {data.message ?? 'This building has no meters to compare.'}
        </EmptyState>
      </section>
    );
  }
  const main = data.main;
  const meters = [main.meter_id, ...data.machines.map((m) => m.meter_id)].sort();
  // A main meter should contain the others: if one uses more, or the remainder is negative,
  // the chosen meter is probably not the site's main incomer.
  const larger = data.machines.filter((m) => m.energy_kwh > main.energy_kwh);
  const doesNotContain = larger.length > 0 || (data.unmetered_kwh ?? 0) < 0;
  return (
    <section
      aria-label="Machine comparison"
      className="min-w-0 space-y-4 rounded-xl border border-line bg-raised p-5"
    >
      {header}
      <label className="block text-sm">
        <span className="font-medium">Main meter</span>{' '}
        <span className="text-muted">({main.chosen ? 'chosen' : 'the largest, by default'})</span>
        <select
          aria-label="Main meter"
          value={main.meter_id}
          onChange={(event) => {
            onMain(event.target.value);
          }}
          className={`${control} mt-1 block max-w-full`}
        >
          {meters.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </label>
      {doesNotContain ? (
        <p role="alert" className="rounded-md border border-line bg-sunken p-3 text-sm">
          <strong>Check the main meter.</strong>{' '}
          {larger.length
            ? `${larger.map((m) => m.meter_id).join(', ')} used more than ${main.meter_id}, `
            : ''}
          so &ldquo;not metered separately&rdquo; comes out negative: {main.meter_id} probably does
          not include the other meters. Choose the site&rsquo;s main incoming meter for shares to
          mean anything.
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[44rem] text-sm">
          <caption className="sr-only">Each meter against the main meter</caption>
          <thead className="text-muted">
            <tr>
              <th scope="col" className="py-2 pr-4 text-left font-medium">
                Meter
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Energy
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Share of main
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Running hours
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Used while closed
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Highest hour
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Unusual events
              </th>
            </tr>
          </thead>
          <tbody>
            <Row meter={main} share={null} strong />
            {data.machines.map((m) => (
              <Row key={m.meter_id} meter={m} share={m.share_of_main} />
            ))}
            {data.unmetered_kwh === null ? null : (
              <tr className="border-t border-line text-muted">
                <th scope="row" className="py-2 pr-4 text-left font-medium">
                  Not metered separately (main minus the others)
                </th>
                <td className="py-2 pr-4 text-right tabular-nums">{kwh(data.unmetered_kwh)}</td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {data.unmetered_share === null ? '—' : formatShare(data.unmetered_share)}
                </td>
                <td colSpan={4} />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data.not_compared.length ? (
        <p className="text-xs text-muted">
          Not compared (not electricity in kWh): {data.not_compared.join(', ')}.
        </p>
      ) : null}
      <details className="text-sm">
        <summary className="cursor-pointer font-medium">How each figure is worked out</summary>
        <dl className="mt-2 space-y-1">
          {Object.entries(data.definitions).map(([key, definition]) => (
            <div key={key}>
              <dt className="inline font-mono text-xs">{key}</dt>{' '}
              <dd className="inline text-muted">{definition}</dd>
            </div>
          ))}
        </dl>
      </details>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted" aria-label="Caveats">
        {data.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </section>
  );
}

export function MachinesPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const building = params.get('building');
  const query: MachineQuery = {
    main: params.get('main'),
    days: daysOf(params.get('days')),
    from: hourOf(params.get('from'), DEFAULT_FROM, 0, 23),
    to: hourOf(params.get('to'), DEFAULT_TO, 1, 24),
  };
  const validHours = query.from < query.to;
  const [draft, setDraft] = useState(building ?? '');
  const suggestions = useApi('machines-buildings', (signal) =>
    fetchBuildings({ limit: 200, offset: 0 }, signal),
  );
  const key =
    building && validHours
      ? `machines:${building}:${query.main ?? ''}:${query.days.join(',')}:${String(query.from)}:${String(query.to)}`
      : null;
  const comparison = useApi(key, (signal) => fetchMachines(building ?? '', query, signal));

  const toggleDay = (day: number) => {
    const next = query.days.includes(day)
      ? query.days.filter((d) => d !== day)
      : [...query.days, day].sort((a, b) => a - b);
    if (next.length) setParams({ days: next.join(',') });
  };

  return (
    <>
      <PageHeader title="Machines" summary={summary} />
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const chosen = draft.trim();
          if (chosen) setParams({ building: chosen, main: null });
        }}
      >
        <label className="text-sm">
          Building
          <input
            list="machines-buildings"
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            placeholder="Building ID"
            className={`${control} ml-2 w-72 max-w-full`}
          />
        </label>
        <datalist id="machines-buildings">
          {suggestions.state.status === 'success'
            ? suggestions.state.data.items.map((b) => (
                <option key={b.building_id} value={b.building_id} />
              ))
            : null}
        </datalist>
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink"
        >
          Compare
        </button>
      </form>

      <fieldset className="space-y-2 text-sm">
        <legend className="font-semibold">Opening hours (local time)</legend>
        <div className="flex flex-wrap items-center gap-3">
          {DAYS.map((name, day) => (
            <label key={name} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={query.days.includes(day)}
                onChange={() => {
                  toggleDay(day);
                }}
              />
              {name}
            </label>
          ))}
          <label className="flex items-center gap-1">
            from
            <select
              aria-label="Opening hour"
              value={query.from}
              onChange={(event) => {
                setParams({ from: event.target.value });
              }}
              className={control}
            >
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {hour(h)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1">
            to
            <select
              aria-label="Closing hour"
              value={query.to}
              onChange={(event) => {
                setParams({ to: event.target.value });
              }}
              className={control}
            >
              {Array.from({ length: 24 }, (_, i) => i + 1).map((h) => (
                <option key={h} value={h}>
                  {hour(h)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="text-xs text-muted">
          {validHours
            ? '"Used while closed" counts the hours outside these days and hours. Set them to your site’s real hours: nothing here knows when it actually opened.'
            : 'The closing hour must be after the opening hour.'}
        </p>
      </fieldset>

      {!building ? (
        <EmptyState title="Choose a building">
          Compare each meter of a building with its main meter: how much each uses, when it runs,
          what it uses while the site is closed, and its unusual hours. This needs a meter on each
          machine. The method tested for splitting a single main meter into machines did not work on
          a real factory (T065).
        </EmptyState>
      ) : !validHours ? null : comparison.state.status === 'loading' ? (
        <LoadingState label="Comparing the meters…" />
      ) : comparison.state.status === 'error' ? (
        <ErrorState
          title="The comparison is unavailable"
          message={
            comparison.state.error.status === 404
              ? `No building ${building} is stored.`
              : comparison.state.error.message
          }
          onRetry={comparison.retry}
        />
      ) : (
        <Comparison
          data={comparison.state.data}
          onMain={(meter) => {
            setParams({ main: meter });
          }}
        />
      )}
    </>
  );
}
