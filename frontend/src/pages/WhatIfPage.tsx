import { useMemo, useState } from 'react';

import {
  fetchBuilding,
  fetchExpectation,
  fetchMeter,
  fetchMeterSuggestions,
  type ExpectationPoint,
} from '../api/catalog';
import { useApi } from '../api/useApi';
import { formatCount, formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { useSearch } from '../design/routes';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../design/states';
import { ScenarioChart } from '../features/whatif/ScenarioChart';
import {
  DEFAULT_SCENARIO,
  localHourOf,
  runScenario,
  validTariff,
  type Scenario,
  type ScenarioResult,
} from '../features/whatif/scenario';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm disabled:opacity-50';
const WINDOWS = [
  { value: '7', label: 'Last 7 days' },
  { value: '14', label: 'Last 14 days' },
  { value: '28', label: 'Last 28 days' },
  { value: 'all', label: 'Whole window' },
] as const;
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const SCENARIO_NOTE =
  'Hypothetical: the recorded readings are unchanged and nothing is saved. Potential excess is ' +
  'an estimate above a threshold, not a verified saving, and a scenario is not a forecast.';

function lastDays(points: readonly ExpectationPoint[], days: string): ExpectationPoint[] {
  const last = points[points.length - 1];
  if (days === 'all' || last === undefined) return [...points];
  const from = Date.parse(last.timestamp) - (Number(days) * 24 - 1) * 3_600_000;
  return points.filter((p) => Date.parse(p.timestamp) >= from);
}

function amount(value: number, unit: string): string {
  return `${value.toLocaleString('en', { maximumFractionDigits: 1 })} ${unit}`;
}

function money(value: number | null, currency: string): string | null {
  return value === null
    ? null
    : value.toLocaleString('en', { style: 'currency', currency, maximumFractionDigits: 2 });
}

function Results({
  result,
  scenario,
  unit,
  nominal,
}: {
  result: ScenarioResult;
  scenario: Scenario;
  unit: string;
  nominal: number;
}) {
  const rule =
    scenario.excessRule === 'interval'
      ? `above the ${formatShare(nominal)} interval’s upper bound`
      : `above expected + ${String(scenario.marginPct)}%`;
  const rows: [string, string, string | null][] = [
    ['Recorded', amount(result.recorded, unit), `${formatCount(result.hours)} hours in the window`],
    [
      'Expected by the model',
      amount(result.expectedComparable, unit),
      `${formatCount(result.comparableHours)} hours with a reading and an expectation (recorded in them: ${amount(result.recordedComparable, unit)})`,
    ],
    [
      `Potential excess (${rule})`,
      amount(result.excess, unit),
      [
        `${formatCount(result.excessHours)} hours above the line`,
        money(result.excessCost, scenario.currency),
      ]
        .filter(Boolean)
        .join(' · '),
    ],
  ];
  if (scenario.reductionPct > 0) {
    rows.push(
      [
        `Hypothetical cut (${String(scenario.reductionPct)}%, ${String(scenario.fromHour).padStart(2, '0')}:00–${String(scenario.toHour).padStart(2, '0')}:00 local)`,
        amount(result.reduction, unit),
        [
          `${formatCount(result.reductionHours)} hours`,
          money(result.reductionCost, scenario.currency),
        ]
          .filter(Boolean)
          .join(' · '),
      ],
      ['Consumption under the scenario', amount(result.scenarioTotal, unit), null],
      [
        'Potential excess under the scenario',
        amount(result.excessAfter, unit),
        money(result.excessAfterCost, scenario.currency),
      ],
    );
  }
  return (
    <div className="space-y-2">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Scenario totals</caption>
        <tbody>
          {rows.map(([label, value, detail]) => (
            <tr key={label} className="border-t border-line align-top">
              <th scope="row" className="py-2 pr-4 font-medium">
                {label}
              </th>
              <td className="py-2 pr-4 text-right tabular-nums">{value}</td>
              <td className="py-2 text-muted">{detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.hoursWithoutThreshold ? (
        <p className="text-xs text-muted">
          {formatCount(result.hoursWithoutThreshold)} hours with a reading have no threshold (no
          expectation, or no interval yet) and count towards no excess.
        </p>
      ) : null}
    </div>
  );
}

function Controls({
  scenario,
  onChange,
  unit,
}: {
  scenario: Scenario;
  onChange: (next: Scenario) => void;
  unit: string;
}) {
  const set = (change: Partial<Scenario>) => {
    onChange({ ...scenario, ...change });
  };
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <fieldset className="space-y-2 text-sm">
        <legend className="font-semibold">Potential excess counts</legend>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="excess-rule"
            checked={scenario.excessRule === 'interval'}
            onChange={() => {
              set({ excessRule: 'interval' });
            }}
            className="accent-accent"
          />
          Above the interval’s upper bound
        </label>
        <label className="flex flex-wrap items-center gap-2">
          <input
            type="radio"
            name="excess-rule"
            checked={scenario.excessRule === 'margin'}
            onChange={() => {
              set({ excessRule: 'margin' });
            }}
            className="accent-accent"
          />
          Above expected +
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            aria-label="Margin above expected, percent"
            value={scenario.marginPct}
            onChange={(event) => {
              set({ excessRule: 'margin', marginPct: Math.max(0, Number(event.target.value)) });
            }}
            className={`${control} w-20`}
          />
          %
        </label>
      </fieldset>
      <fieldset className="space-y-2 text-sm">
        <legend className="font-semibold">Hypothetical cut</legend>
        <label className="flex items-center gap-2">
          Reduce recorded use by
          <input
            type="number"
            min={0}
            max={100}
            step={5}
            aria-label="Cut, percent"
            value={scenario.reductionPct}
            onChange={(event) => {
              set({ reductionPct: Math.min(100, Math.max(0, Number(event.target.value))) });
            }}
            className={`${control} w-20`}
          />
          %
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <label>
            from
            <select
              aria-label="Cut from, local hour"
              value={scenario.fromHour}
              onChange={(event) => {
                set({ fromHour: Number(event.target.value) });
              }}
              className={`${control} ml-2`}
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, '0')}:00
                </option>
              ))}
            </select>
          </label>
          <label>
            to
            <select
              aria-label="Cut to, local hour"
              value={scenario.toHour}
              onChange={(event) => {
                set({ toHour: Number(event.target.value) });
              }}
              className={`${control} ml-2`}
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, '0')}:00
                </option>
              ))}
            </select>
          </label>
          <span className="text-muted">building’s local time</span>
        </div>
      </fieldset>
      <fieldset className="space-y-2 text-sm">
        <legend className="font-semibold">Tariff (optional)</legend>
        {unit === 'kWh' ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <input
                type="number"
                min={0}
                step={0.01}
                aria-label="Price per kWh"
                placeholder="Price per kWh"
                value={scenario.price ?? ''}
                onChange={(event) => {
                  set({ price: event.target.value === '' ? null : Number(event.target.value) });
                }}
                className={`${control} w-32`}
              />
              <input
                aria-label="Currency code"
                placeholder="USD"
                maxLength={3}
                value={scenario.currency}
                onChange={(event) => {
                  set({ currency: event.target.value.toUpperCase() });
                }}
                className={`${control} w-20`}
              />
            </div>
            <p className="text-xs text-muted">
              {validTariff(scenario)
                ? 'Costs use this tariff only; no tariff is ever assumed.'
                : 'Enter a price and a three-letter currency to see costs; without one, energy only.'}
            </p>
          </>
        ) : (
          <p className="text-muted">Costs are shown for kWh meters only.</p>
        )}
      </fieldset>
    </div>
  );
}

function Lab({ meterId, days }: { meterId: string; days: string }) {
  const { setParams } = useSearch();
  const [scenario, setScenario] = useState<Scenario>(DEFAULT_SCENARIO);
  const meter = useApi(`whatif-meter:${meterId}`, (signal) => fetchMeter(meterId, signal));
  const buildingId = meter.state.status === 'success' ? meter.state.data.building_id : null;
  const building = useApi(buildingId === null ? null : `whatif-building:${buildingId}`, (signal) =>
    fetchBuilding(buildingId ?? '', signal),
  );
  const series = useApi(`whatif-expectation:${meterId}`, (signal) =>
    fetchExpectation(meterId, signal),
  );
  const timezone = building.state.status === 'success' ? building.state.data.timezone : null;
  const points = useMemo(
    () => (series.state.status === 'success' ? lastDays(series.state.data.points, days) : []),
    [series.state, days],
  );
  const unit = series.state.status === 'success' ? series.state.data.unit : 'kWh';
  const result = useMemo(
    () => (timezone === null ? null : runScenario(points, scenario, localHourOf(timezone), unit)),
    [points, scenario, timezone, unit],
  );

  for (const [state, retry, title] of [
    [meter.state, meter.retry, 'This meter is unavailable'],
    [series.state, series.retry, 'The readings are unavailable'],
    [building.state, building.retry, 'The building is unavailable'],
  ] as const) {
    if (state.status === 'error') {
      return (
        <ErrorState
          title={title}
          message={
            state.error.status === 404 ? `There is no meter ${meterId}.` : state.error.message
          }
          onRetry={retry}
        />
      );
    }
  }
  if (series.state.status !== 'success' || result === null || timezone === null) {
    return <LoadingState label="Loading the meter…" />;
  }
  const data = series.state.data;
  if (!data.available || data.meta === null) {
    return (
      <EmptyState title="No expectation for this meter">
        {data.message ?? 'The model has no stored expectation here.'}
      </EmptyState>
    );
  }
  return (
    <section
      className="space-y-5 rounded-xl border border-line bg-raised p-5"
      aria-label="Scenario"
    >
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <ProvenanceBadge kind={data.data_kind} />
        <span className="break-all font-medium">{meterId}</span>
        <span className="text-muted">
          {timezone} · model <code>{data.meta.model_version}</code>
        </span>
        <label className="ml-auto">
          Window
          <select
            className={`${control} ml-2`}
            value={days}
            onChange={(event) => {
              setParams({ days: event.target.value === '14' ? null : event.target.value });
            }}
          >
            {WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>
                {w.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <Controls scenario={scenario} onChange={setScenario} unit={unit} />
      <p role="note" className="rounded-lg bg-sunken p-3 text-sm text-muted">
        {SCENARIO_NOTE}
      </p>
      <Results
        result={result}
        scenario={scenario}
        unit={unit}
        nominal={data.meta.interval_nominal}
      />
      <ScenarioChart
        points={result.points}
        unit={unit}
        showScenario={scenario.reductionPct > 0}
        label={`Recorded readings, the model's expectation, the excess threshold${scenario.reductionPct > 0 ? ' and the scenario' : ''} for ${meterId}`}
      />
      <ul className="flex flex-wrap gap-4 text-xs text-muted" aria-label="Chart legend">
        <li>
          <span className="mr-1 inline-block h-0.5 w-4 bg-accent align-middle" />
          Recorded
        </li>
        <li>
          <span className="mr-1 inline-block h-0.5 w-4 border-t-2 border-dashed border-muted align-middle" />
          Expected
        </li>
        <li>
          <span className="mr-1 inline-block h-0.5 w-4 border-t-2 border-dotted border-warning align-middle" />
          Excess threshold
        </li>
        {scenario.reductionPct > 0 ? (
          <li>
            <span className="mr-1 inline-block h-0.5 w-4 bg-ink align-middle" />
            Scenario (where it differs)
          </li>
        ) : null}
      </ul>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted">
        {data.caveats.map((caveat) => (
          <li key={caveat}>{caveat}</li>
        ))}
      </ul>
    </section>
  );
}

export function WhatIfPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const meterId = params.get('meter');
  const rawDays = params.get('days');
  const days = WINDOWS.some((w) => w.value === rawDays) && rawDays !== null ? rawDays : '14';
  const suggestions = useApi('whatif-suggestions', fetchMeterSuggestions);
  const [draft, setDraft] = useState(meterId ?? '');

  return (
    <>
      <PageHeader title="What-if lab" summary={summary} />
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const chosen = draft.trim();
          if (chosen) setParams({ meter: chosen });
        }}
      >
        <label className="text-sm">
          Meter
          <input
            list="whatif-meters"
            value={draft}
            onChange={(event) => {
              setDraft(event.target.value);
            }}
            placeholder="Meter ID"
            className={`${control} ml-2 w-72 max-w-full`}
          />
        </label>
        <datalist id="whatif-meters">
          {suggestions.state.status === 'success'
            ? suggestions.state.data.items.map((m) => (
                <option key={m.meter_id} value={m.meter_id} />
              ))
            : null}
        </datalist>
        <button
          type="submit"
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink"
        >
          Explore
        </button>
      </form>
      {meterId ? (
        <Lab key={meterId} meterId={meterId} days={days} />
      ) : (
        <EmptyState title="Choose a meter">
          Pick a meter to compare its recorded readings with the model’s expectation and try
          scenarios on them. Nothing you try here is saved.
        </EmptyState>
      )}
    </>
  );
}
