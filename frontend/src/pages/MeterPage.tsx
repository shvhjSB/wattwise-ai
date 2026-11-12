import { type ReactNode, useMemo, useState } from 'react';

import { formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { PrintButton, PrintHeader } from '../design/PrintReport';
import { EmptyState, PageHeader } from '../design/states';
import {
  check,
  type DateOrder,
  localParts,
  parseCsv,
  parseTime,
  readRows,
  syntheticMeterCsv,
  validTimeZone,
  type ValueKind,
  type Window,
} from '../features/meter/meter';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm';
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const ZONES = ['Asia/Kolkata', 'UTC', 'Europe/Berlin', 'Europe/London', 'America/New_York'];

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function local(t: number, zone: string): string {
  const p = localParts(t, zone);
  const two = (n: number) => String(n).padStart(2, '0');
  return `${String(p.year)}-${two(p.month)}-${two(p.day)} ${two(p.hour)}:${two(p.minute)}`;
}

function num(value: number, digits = 1): string {
  return value.toLocaleString('en', { maximumFractionDigits: digits });
}

function hour(value: number): string {
  return `${String(value).padStart(2, '0')}:00`;
}

/** The time and value columns, guessed from the first row: the first column that reads as a time,
 * and the first other column that reads as a number. */
function guessColumns(header: string[], first: string[] | undefined): [number, number] {
  if (!first) return [0, Math.min(1, header.length - 1)];
  const time = first.findIndex(
    (cell) =>
      parseTime(cell, 'ymd', 'UTC') !== null ||
      parseTime(cell, 'dmy', 'UTC') !== null ||
      parseTime(cell, 'mdy', 'UTC') !== null,
  );
  const t = time >= 0 ? time : 0;
  const value = first.findIndex(
    (cell, i) => i !== t && cell !== '' && Number.isFinite(Number(cell.replace(',', '.'))),
  );
  return [t, value >= 0 ? value : t === 0 ? 1 : 0];
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      aria-label={title}
      className="min-w-0 space-y-3 rounded-xl border border-line bg-raised p-5 text-sm print:break-inside-avoid"
    >
      <h3 className="text-base font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Facts({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="tabular-nums">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function MeterPage({ summary }: { summary: string }) {
  const [text, setText] = useState<string | null>(null);
  const [source, setSource] = useState('');
  const [fromExample, setFromExample] = useState(false);
  const [columns, setColumns] = useState<[number, number]>([0, 1]);
  const [order, setOrder] = useState<DateOrder>('ymd');
  const [zone, setZone] = useState(browserZone);
  const [kind, setKind] = useState<ValueKind>('kwh');
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [from, setFrom] = useState(6);
  const [to, setTo] = useState(18);
  const [rate, setRate] = useState('');
  const [windows, setWindows] = useState<{ label: string; from: string; to: string }[]>([
    { label: '', from: '', to: '' },
    { label: '', from: '', to: '' },
  ]);

  const table = useMemo(() => (text === null ? null : parseCsv(text)), [text]);
  const zoneOk = validTimeZone(zone);
  const usedWindows: Window[] = useMemo(
    () =>
      windows.flatMap((w) => {
        const f = Number(w.from);
        const t = Number(w.to);
        return w.label.trim() !== '' &&
          w.from !== '' &&
          w.to !== '' &&
          f >= 0 &&
          f <= 23 &&
          t >= 0 &&
          t <= 24
          ? [{ label: w.label.trim(), from: f, to: t }]
          : [];
      }),
    [windows],
  );
  const read = useMemo(
    () =>
      table && zoneOk
        ? readRows(table, {
            timeColumn: columns[0],
            valueColumn: columns[1],
            order,
            timeZone: zone,
            kind,
          })
        : null,
    [table, columns, order, zone, kind, zoneOk],
  );
  const result = useMemo(
    () =>
      read && from < to ? check(read.readings, kind, zone, { days, from, to }, usedWindows) : null,
    [read, kind, zone, days, from, to, usedWindows],
  );

  const load = (content: string, name: string, example: boolean) => {
    const t = parseCsv(content);
    setText(content);
    setSource(name);
    setFromExample(example);
    setColumns(guessColumns(t.header, t.rows[0]));
  };

  const rateValue = Number(rate);
  const priced = rate.trim() !== '' && Number.isFinite(rateValue) && rateValue > 0;

  return (
    <>
      <PageHeader title="Meter check" summary={summary} />
      <PrintHeader
        title="meter"
        source={
          fromExample
            ? 'Synthetic example: made-up readings, not a real site.'
            : `Readings from ${source || 'a meter file'}, in ${zone}.`
        }
      />
      <div
        role="note"
        aria-label="How the meter check works"
        className="space-y-2 rounded-xl border border-line bg-sunken p-4 text-sm"
      >
        <p>
          <strong>Read in your browser.</strong> The file is never uploaded or saved; reloading the
          page clears it.
        </p>
        <p>
          Use your main meter&rsquo;s interval readings (every 15, 30 or 60 minutes) as a CSV file
          with a time column and an energy (kWh) or power (kW) column. Industrial meters often
          record such load-survey data; ask your utility or meter supplier how to get it, as access
          differs by utility. A logger on the main incomer also produces such files.
        </p>
        <p>
          This shows when and how the whole site uses electricity. It does not split the meter into
          machines: tested on a real factory, that did not work (T065).
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <label className="text-sm">
          <span className="mr-2 font-medium">Meter file</span>
          <input
            type="file"
            accept=".csv,.txt,text/csv,text/plain"
            aria-label="Meter file"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              void file.text().then((content) => {
                load(content, file.name, false);
              });
            }}
            className="text-sm"
          />
        </label>
        <button
          type="button"
          onClick={() => {
            load(syntheticMeterCsv(), 'synthetic example', true);
            setZone('Asia/Kolkata');
            setOrder('ymd');
            setKind('kwh');
            setDays([0, 1, 2, 3, 4, 5]);
            setFrom(8);
            setTo(20);
          }}
          className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink"
        >
          Use a synthetic example
        </button>
        {text !== null ? (
          <button
            type="button"
            onClick={() => {
              setText(null);
              setFromExample(false);
              setSource('');
            }}
            className="rounded-md border border-edge px-4 py-2 text-sm font-semibold"
          >
            Clear
          </button>
        ) : null}
        {fromExample ? (
          <span className="flex items-center gap-2 text-sm">
            <ProvenanceBadge kind="synthetic" />
            Made-up readings, not a real site.
          </span>
        ) : null}
        {result !== null && typeof result !== 'string' ? <PrintButton /> : null}
      </div>

      {table === null ? (
        <EmptyState title="Choose a meter file">
          Or try the synthetic example: four weeks of 15-minute readings with one Sunday when the
          load was left on overnight.
        </EmptyState>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2 print:hidden">
            <fieldset className="min-w-0 space-y-3 rounded-xl border border-line bg-raised p-5 text-sm">
              <legend className="px-1 font-semibold">How to read {source}</legend>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="block">
                  Time column
                  <select
                    value={columns[0]}
                    onChange={(e) => {
                      setColumns([Number(e.target.value), columns[1]]);
                    }}
                    className={`${control} mt-1 block w-full`}
                  >
                    {table.header.map((h, i) => (
                      <option key={`${String(i)}-${h}`} value={i}>
                        {h || `Column ${String(i + 1)}`}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  Value column
                  <select
                    value={columns[1]}
                    onChange={(e) => {
                      setColumns([columns[0], Number(e.target.value)]);
                    }}
                    className={`${control} mt-1 block w-full`}
                  >
                    {table.header.map((h, i) => (
                      <option key={`${String(i)}-${h}`} value={i}>
                        {h || `Column ${String(i + 1)}`}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  The values are
                  <select
                    value={kind}
                    onChange={(e) => {
                      setKind(e.target.value === 'kw' ? 'kw' : 'kwh');
                    }}
                    className={`${control} mt-1 block w-full`}
                  >
                    <option value="kwh">energy in each interval (kWh)</option>
                    <option value="kw">average power over each interval (kW)</option>
                  </select>
                </label>
                <label className="block">
                  Date order
                  <select
                    value={order}
                    onChange={(e) => {
                      const v = e.target.value;
                      setOrder(v === 'dmy' ? 'dmy' : v === 'mdy' ? 'mdy' : 'ymd');
                    }}
                    className={`${control} mt-1 block w-full`}
                  >
                    <option value="ymd">year-month-day (2018-01-31)</option>
                    <option value="dmy">day/month/year (31/01/2018)</option>
                    <option value="mdy">month/day/year (01/31/2018)</option>
                  </select>
                </label>
                <label className="block sm:col-span-2">
                  Time zone of the times (times with an offset, such as +05:30 or Z, are read as
                  written)
                  <input
                    list="meter-zones"
                    value={zone}
                    onChange={(e) => {
                      setZone(e.target.value.trim());
                    }}
                    className={`${control} mt-1 block w-full`}
                  />
                  <datalist id="meter-zones">
                    {ZONES.map((z) => (
                      <option key={z} value={z} />
                    ))}
                  </datalist>
                  {zoneOk ? null : (
                    <span className="mt-1 block text-xs text-synthetic">
                      Not a time zone. Use a name such as Asia/Kolkata.
                    </span>
                  )}
                </label>
              </div>
            </fieldset>

            <fieldset className="min-w-0 space-y-3 rounded-xl border border-line bg-raised p-5 text-sm">
              <legend className="px-1 font-semibold">Your site</legend>
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-medium">Open</span>
                {DAYS.map((name, day) => (
                  <label key={name} className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={days.includes(day)}
                      onChange={() => {
                        const next = days.includes(day)
                          ? days.filter((d) => d !== day)
                          : [...days, day].sort((a, b) => a - b);
                        if (next.length) setDays(next);
                      }}
                    />
                    {name}
                  </label>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1">
                  from
                  <select
                    aria-label="Opening hour"
                    value={from}
                    onChange={(e) => {
                      setFrom(Number(e.target.value));
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
                    value={to}
                    onChange={(e) => {
                      setTo(Number(e.target.value));
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
                <span className="text-xs text-muted">local time</span>
              </div>
              <label className="block">
                Energy rate, optional, to price use while closed
                <input
                  type="number"
                  step="any"
                  min={0}
                  aria-label="Energy rate per kWh"
                  value={rate}
                  onChange={(e) => {
                    setRate(e.target.value);
                  }}
                  className={`${control} mt-1 block w-40`}
                />
              </label>
              <p className="font-medium">Time-of-day windows, optional (local hours)</p>
              {windows.map((w, i) => (
                <div key={String(i)} className="grid grid-cols-3 gap-2">
                  {(['label', 'from', 'to'] as const).map((field) => (
                    <label key={field} className="text-xs">
                      Window {String(i + 1)} {field}
                      <input
                        type={field === 'label' ? 'text' : 'number'}
                        min={0}
                        max={24}
                        value={w[field]}
                        onChange={(e) => {
                          const value = e.target.value;
                          setWindows(
                            windows.map((x, j) => (j === i ? { ...x, [field]: value } : x)),
                          );
                        }}
                        className={`${control} mt-1 block w-full`}
                      />
                    </label>
                  ))}
                </div>
              ))}
              {from < to ? null : (
                <p className="text-xs text-synthetic">
                  The closing hour must be after the opening hour.
                </p>
              )}
            </fieldset>
          </div>

          {read === null || result === null ? null : typeof result === 'string' ? (
            <Section title="Data check">
              <p>{result}</p>
              {read.problems.length ? (
                <ul className="list-disc pl-5">
                  {read.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              ) : null}
            </Section>
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <Section title="Data check">
                <Facts
                  rows={[
                    ['Interval', `${String(result.minutes)} minutes`],
                    [
                      'Period (local)',
                      `${local(result.first, zone)} to ${local(result.last, zone)}`,
                    ],
                    ['Readings', num(result.intervals.length, 0)],
                    [
                      'Missing intervals',
                      `${num(result.missing, 0)} (${formatShare(result.missing / result.expected)}), longest gap ${num(result.longestGapHours, 2)} h`,
                    ],
                    ['Repeated times', `${num(result.duplicates, 0)} (the first is kept)`],
                    ['Below zero', num(result.negatives, 0)],
                    ['Lines not read', num(read.unreadable, 0)],
                  ]}
                />
                {read.problems.length ? (
                  <ul className="list-disc pl-5 text-xs text-muted">
                    {read.problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                ) : null}
                <p className="text-xs text-muted">
                  Missing readings are reported, never filled in.
                </p>
              </Section>

              <Section title="Energy and peak demand">
                <Facts
                  rows={[
                    ['Energy', `${num(result.totalKwh)} kWh`],
                    [
                      'Highest demand',
                      `${num(result.peak.kw)} kW at ${local(result.peak.t, zone)} (average over its ${String(result.minutes)}-minute interval)`,
                    ],
                    ['Near the peak', `${num(result.nearPeak, 0)} intervals at 90% of it or more`],
                  ]}
                />
                <table className="w-full text-left">
                  <caption className="sr-only">The highest-demand intervals</caption>
                  <thead className="text-muted">
                    <tr>
                      <th scope="col" className="py-1 pr-4 font-medium">
                        Interval start (local)
                      </th>
                      <th scope="col" className="py-1 text-right font-medium">
                        Demand
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.top.map((i) => (
                      <tr key={i.t} className="border-t border-line">
                        <td className="py-1 pr-4 tabular-nums">{local(i.t, zone)}</td>
                        <td className="py-1 text-right tabular-nums">{num(i.kw)} kW</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>

              <Section title="Use while closed">
                <Facts
                  rows={[
                    [
                      'While closed',
                      `${num(result.closedKwh)} kWh${result.closedShare === null ? '' : ` (${formatShare(result.closedShare)} of all use)`}`,
                    ],
                    [
                      'Base load while closed',
                      result.baseLoadKw === null
                        ? '—'
                        : `${num(result.baseLoadKw)} kW (10th percentile)`,
                    ],
                    ...(priced
                      ? ([
                          [
                            'At your rate',
                            `${num(result.closedKwh * rateValue, 2)} for the period (rate ${String(rateValue)} per kWh)`,
                          ],
                        ] as [string, string][])
                      : []),
                  ]}
                />
                <p className="text-xs text-muted">
                  Closed means outside the days and hours you set. Some use while closed is needed
                  (security, servers, cold storage); this shows how much there is, not how much is
                  waste.
                </p>
              </Section>

              <Section title="Hour of day">
                <table className="w-full text-left">
                  <caption className="sr-only">Average demand by local hour</caption>
                  <tbody>
                    {result.hourProfile.map((kw, h) => {
                      const top = Math.max(...result.hourProfile.map((v) => v ?? 0), 1);
                      return (
                        <tr key={h}>
                          <th scope="row" className="w-14 py-0.5 pr-2 font-normal tabular-nums">
                            {hour(h)}
                          </th>
                          <td className="w-20 py-0.5 pr-2 text-right tabular-nums">
                            {kw === null ? '—' : `${num(kw)} kW`}
                          </td>
                          <td className="py-0.5" aria-hidden="true">
                            <div
                              className="h-2 rounded bg-accent"
                              style={{ width: `${String(((kw ?? 0) / top) * 100)}%` }}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Section>

              {result.windows.length ? (
                <Section title="Time of day">
                  <table className="w-full text-left">
                    <caption className="sr-only">Energy by time-of-day window</caption>
                    <tbody>
                      {result.windows.map((w) => (
                        <tr key={w.label} className="border-t border-line">
                          <th scope="row" className="py-1 pr-4 font-normal">
                            {w.label}
                          </th>
                          <td className="py-1 pr-4 text-right tabular-nums">{num(w.kwh)} kWh</td>
                          <td className="py-1 text-right tabular-nums">
                            {w.share === null ? '—' : formatShare(w.share)}
                          </td>
                        </tr>
                      ))}
                      <tr className="border-t border-line">
                        <th scope="row" className="py-1 pr-4 font-normal">
                          Other hours
                        </th>
                        <td className="py-1 pr-4 text-right tabular-nums">
                          {num(result.otherKwh)} kWh
                        </td>
                        <td className="py-1 text-right tabular-nums">
                          {result.totalKwh > 0
                            ? formatShare(result.otherKwh / result.totalKwh)
                            : '—'}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </Section>
              ) : null}

              <Section title="Unusual periods">
                {result.events.length ? (
                  <table className="w-full text-left">
                    <caption className="sr-only">
                      Unusual periods found by the default detector
                    </caption>
                    <thead className="text-muted">
                      <tr>
                        <th scope="col" className="py-1 pr-4 font-medium">
                          From (local)
                        </th>
                        <th scope="col" className="py-1 pr-4 font-medium">
                          Hours
                        </th>
                        <th scope="col" className="py-1 pr-4 font-medium">
                          Direction
                        </th>
                        <th scope="col" className="py-1 text-right font-medium">
                          Against the usual
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.events.map((e) => (
                        <tr
                          key={`${String(e.start)}-${e.direction}`}
                          className="border-t border-line"
                        >
                          <td className="py-1 pr-4 tabular-nums">{local(e.start, zone)}</td>
                          <td className="py-1 pr-4 tabular-nums">{e.duration_hours}</td>
                          <td className="py-1 pr-4">
                            {e.direction === 'high' ? 'higher' : 'lower'}
                          </td>
                          <td className="py-1 text-right tabular-nums">
                            {e.residual_sum > 0 ? '+' : ''}
                            {num(e.residual_sum)} kWh
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p>No unusual periods were found.</p>
                )}
                <p className="text-xs text-muted">
                  Each hour is compared with the same hour on the previous 14 days (at least 7
                  needed), using {num(result.completeHours, 0)} complete hours. These are anomalies
                  to investigate, not confirmed waste: an unusual week can have a good reason.
                </p>
              </Section>
            </div>
          )}
        </>
      )}
    </>
  );
}
