import { useState } from 'react';

import {
  fetchExpectation,
  fetchMeterAlerts,
  type ExpectationSeries,
  type MeterAlert,
} from '../../api/catalog';
import { useApi } from '../../api/useApi';
import { ResidualChart } from '../../design/chart/ResidualChart';
import { TimeSeriesChart } from '../../design/chart/TimeSeriesChart';
import { describePoint, timeOf } from '../../design/chart/geometry';
import { formatDateTime, intervalStats } from '../../design/chart/scales';
import { formatCount, formatShare } from '../../design/format';
import { ProvenanceBadge } from '../../design/Provenance';
import { EmptyState, ErrorState, LoadingState } from '../../design/states';
import {
  alertView,
  defaultView,
  lastDays,
  pan,
  viewDays,
  wholeSeries,
  zoomTo,
  type View,
} from './view';

const TABLE_ROWS = 500;
const ZOOMS = [3, 7, 14, 28] as const;

/** One meter: its readings against the model's expectation and interval, with the alerts on it. */
export function MeterView({ meterId }: { meterId: string }) {
  const expectation = useApi(`expectation:${meterId}`, (signal) =>
    fetchExpectation(meterId, signal),
  );
  const alerts = useApi(`meter-alerts:${meterId}`, (signal) => fetchMeterAlerts(meterId, signal));

  if (expectation.state.status === 'loading' || alerts.state.status === 'loading') {
    return <LoadingState label="Loading the meter…" />;
  }
  if (expectation.state.status === 'error') {
    return (
      <ErrorState
        title="This meter is unavailable"
        message={
          expectation.state.error.status === 404
            ? `There is no meter ${meterId}.`
            : expectation.state.error.message
        }
        onRetry={expectation.retry}
      />
    );
  }
  if (alerts.state.status === 'error') {
    return (
      <ErrorState
        title="The alerts on this meter are unavailable"
        message={alerts.state.error.message}
        onRetry={alerts.retry}
      />
    );
  }
  const series = expectation.state.data;
  if (!series.available) {
    return <EmptyState title="No expectation to show">{series.message}</EmptyState>;
  }
  // `key` restarts the view when the meter changes.
  return <Loaded key={meterId} series={series} alerts={alerts.state.data.items} />;
}

function Loaded({ series, alerts }: { series: ExpectationSeries; alerts: MeterAlert[] }) {
  const { meta, points } = series;
  const [view, setView] = useState<View>(() => defaultView(points, alerts));
  const [cursor, setCursor] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  const slice = points.slice(view.from, view.to);
  const stats = intervalStats(slice);
  const hasExpectation = slice.some((p) => p.expected !== null);
  const top = alerts.reduce<MeterAlert | undefined>(
    (best, a) => (best === undefined || a.priority_score > best.priority_score ? a : best),
    undefined,
  );
  const first = slice[0];
  const last = slice[slice.length - 1];
  const range =
    first && last
      ? `${formatDateTime(timeOf(first))} to ${formatDateTime(timeOf(last))}`
      : 'no hours';
  const inView = alerts.filter(
    (a) =>
      first && last && Date.parse(a.end) > timeOf(first) && Date.parse(a.start) <= timeOf(last),
  );
  const shownPoint = cursor === null ? undefined : slice[cursor];
  const chartLabel =
    `${series.meter_id}: observed and expected energy in ${series.unit} per hour, ${range}. ` +
    `${formatCount(stats.above + stats.below)} of ${formatCount(stats.checked)} hours with an interval were outside it. ` +
    `${formatCount(inView.length)} alerts in this range.`;

  const button =
    'rounded-md border border-edge px-3 py-1.5 text-sm font-medium hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent';

  return (
    <section aria-label={`Meter ${series.meter_id}`} className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold break-all">{series.meter_id}</h3>
        <ProvenanceBadge kind={series.data_kind} />
      </header>

      {meta ? (
        <p className="text-sm text-muted">
          Model {meta.model_version}. Its expectation covers {meta.window_start.slice(0, 10)} to{' '}
          {meta.window_end.slice(0, 10)} (UTC), where it was not trained on the readings.
          {meta.first_interval
            ? ` The ${formatShare(meta.interval_nominal)} interval begins ${meta.first_interval.slice(0, 10)}.`
            : ' This meter has no interval.'}
          {meta.measured_coverage === null
            ? ''
            : ` Measured on the test window, ${formatShare(meta.measured_coverage)} of readings fell inside it.`}
        </p>
      ) : null}

      <div role="group" aria-label="Range" className="flex flex-wrap items-center gap-2">
        {top ? (
          <button
            type="button"
            className={button}
            onClick={() => {
              setView(alertView(points, top));
            }}
          >
            Top alert
          </button>
        ) : null}
        {ZOOMS.map((days) => (
          <button
            key={days}
            type="button"
            aria-pressed={viewDays(view) === days}
            className={`${button} aria-pressed:bg-accent aria-pressed:text-accent-ink`}
            onClick={() => {
              setView(zoomTo(view, days, points.length));
            }}
          >
            {String(days)} days
          </button>
        ))}
        <button
          type="button"
          className={button}
          onClick={() => {
            setView(wholeSeries(points.length));
          }}
        >
          Whole window
        </button>
        <button
          type="button"
          className={button}
          onClick={() => {
            setView(lastDays(points.length, 14));
          }}
        >
          Latest
        </button>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden="true" />
        <button
          type="button"
          className={button}
          onClick={() => {
            setView(pan(view, -1, points.length));
          }}
        >
          ◀ Earlier
        </button>
        <button
          type="button"
          className={button}
          onClick={() => {
            setView(pan(view, 1, points.length));
          }}
        >
          Later ▶
        </button>
      </div>

      <p className="text-sm" role="status" aria-label="Range summary">
        <span className="font-medium">{range}</span>
        {stats.checked > 0 && stats.outsideShare !== null ? (
          <span className="text-muted">
            {' '}
            · {formatCount(stats.above + stats.below)} of {formatCount(stats.checked)} hours with a
            reading and an interval were outside it ({formatShare(stats.outsideShare)}; above{' '}
            {formatCount(stats.above)}, below {formatCount(stats.below)})
          </span>
        ) : (
          <span className="text-muted"> · no hours here have both a reading and an interval</span>
        )}
      </p>

      {!hasExpectation ? (
        <EmptyState title="No expectation in this range">
          The model has no expectation for this meter here. The readings are shown alone.
        </EmptyState>
      ) : null}

      <figure className="space-y-2 rounded-xl border border-line bg-raised p-3">
        <TimeSeriesChart
          points={slice}
          alerts={alerts}
          unit={series.unit}
          label={chartLabel}
          cursor={cursor}
          onCursor={setCursor}
        />
        <ResidualChart
          points={slice}
          unit={series.unit}
          label={`${series.meter_id}: observed minus expected, ${series.unit} per hour, ${range}.`}
          cursor={cursor}
          onCursor={setCursor}
        />
        <figcaption className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          <span>
            <span aria-hidden="true" className="text-accent">
              ━
            </span>{' '}
            Observed
          </span>
          <span>
            <span aria-hidden="true">╍</span> Expected by the model
          </span>
          <span>
            <span aria-hidden="true" className="text-accent opacity-40">
              ▮
            </span>{' '}
            {formatShare(meta?.interval_nominal ?? 0.9)} interval
          </span>
          <span>
            <span aria-hidden="true" className="text-danger">
              ●
            </span>{' '}
            Outside the interval
          </span>
          <span>
            <span aria-hidden="true" className="text-warning">
              ▮
            </span>{' '}
            Alert window
          </span>
          <span>A gap is a missing reading, not zero.</span>
        </figcaption>
      </figure>

      <div className="space-y-2">
        <label className="flex items-center gap-3 text-sm">
          <span className="font-medium">Inspect hour</span>
          <input
            type="range"
            min={0}
            max={Math.max(0, slice.length - 1)}
            value={cursor ?? 0}
            disabled={slice.length === 0}
            onChange={(event) => {
              setCursor(Number(event.target.value));
            }}
            className="flex-1 accent-[var(--color-accent)]"
          />
        </label>
        <output
          className="block min-h-[3.5rem] rounded-lg bg-sunken p-3 text-sm"
          aria-live="polite"
        >
          {shownPoint ? (
            <ul className="grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
              {describePoint(shownPoint, series.unit).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <span className="text-muted">
              Move over the chart, or use the slider, to read a single hour.
            </span>
          )}
        </output>
      </div>

      {inView.length > 0 ? (
        <section aria-label="Alerts in this range" className="space-y-1">
          <h4 className="text-sm font-semibold">Alerts in this range</h4>
          <ul className="space-y-1 text-sm">
            {inView.slice(0, 10).map((a) => (
              <li key={a.alert_id}>
                <button
                  type="button"
                  className="text-left underline decoration-line underline-offset-4 hover:decoration-accent focus-visible:outline-2 focus-visible:outline-accent"
                  onClick={() => {
                    setView(alertView(points, a));
                  }}
                >
                  {a.start.slice(0, 16).replace('T', ' ')} UTC · {a.signature.replace('_', ' ')} ·{' '}
                  {a.severity} priority ({a.priority_score.toFixed(0)}) ·{' '}
                  {a.review_status.replace('_', ' ')}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div>
        <button
          type="button"
          aria-expanded={showTable}
          className={button}
          onClick={() => {
            setShowTable((v) => !v);
          }}
        >
          {showTable ? 'Hide data table' : 'Show data table'}
        </button>
        {showTable ? (
          <div className="mt-3 max-h-96 overflow-auto rounded-lg border border-line">
            <table className="w-full text-left text-xs">
              <caption className="sr-only">
                Hourly readings, expectation and interval in {series.unit}
              </caption>
              <thead className="sticky top-0 bg-sunken">
                <tr>
                  <th scope="col" className="p-2">
                    Hour (UTC)
                  </th>
                  <th scope="col" className="p-2">
                    Observed
                  </th>
                  <th scope="col" className="p-2">
                    Expected
                  </th>
                  <th scope="col" className="p-2">
                    Lower
                  </th>
                  <th scope="col" className="p-2">
                    Upper
                  </th>
                </tr>
              </thead>
              <tbody>
                {slice.slice(0, TABLE_ROWS).map((p) => (
                  <tr key={p.timestamp} className="border-t border-line">
                    <th scope="row" className="p-2 font-normal">
                      {p.timestamp.slice(0, 16).replace('T', ' ')}
                    </th>
                    {[p.observed, p.expected, p.lower, p.upper].map((v, i) => (
                      <td key={i} className="p-2 tabular-nums">
                        {v === null ? '—' : v.toFixed(1)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {slice.length > TABLE_ROWS ? (
              <p className="p-2 text-xs text-muted">
                The first {String(TABLE_ROWS)} of {formatCount(slice.length)} hours. Narrow the
                range to see the rest.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>

      <ul className="space-y-1 text-xs text-muted">
        {series.caveats.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </section>
  );
}
