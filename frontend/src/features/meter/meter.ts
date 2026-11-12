/**
 * The meter check (T067, D078): a main meter's interval file, read and analysed in the browser.
 * Nothing is uploaded or stored.
 *
 * - Readings are taken as given; a gap is reported, never filled.
 * - The day/month order and the time zone are the user's choices, because "03/04" is ambiguous.
 * - Unusual days come from the default detector (`detector.ts`, the same rule as the server).
 * - It never splits the meter into machines (T065, D076).
 */

import { detectEvents, type DetectorEvent, HOUR_MS, type HourRow } from './detector';

// ---------------------------------------------------------------------------------------------
// Reading a CSV file
// ---------------------------------------------------------------------------------------------

export interface Table {
  header: string[];
  rows: string[][];
  delimiter: string;
}

function splitLine(line: string, delimiter: string): string[] {
  const out: string[] = [];
  let field = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line.charAt(i);
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') {
        field += '"';
        i += 1;
      } else if (ch === '"') {
        quoted = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === delimiter) {
      out.push(field.trim());
      field = '';
    } else {
      field += ch;
    }
  }
  out.push(field.trim());
  return out;
}

/** A CSV with a header row. The delimiter (comma, semicolon or tab) is the one the header uses
 * most. Blank lines are skipped. */
export function parseCsv(text: string): Table {
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text; // a byte-order mark
  const lines = body.split(/\r?\n/);
  const first = lines.find((l) => l.trim() !== '') ?? '';
  const delimiter = [',', ';', '\t'].reduce((best, d) =>
    first.split(d).length > first.split(best).length ? d : best,
  );
  const [header = [], ...rows] = lines
    .filter((l) => l.trim() !== '')
    .map((l) => splitLine(l, delimiter));
  return { header, rows, delimiter };
}

// ---------------------------------------------------------------------------------------------
// Times
// ---------------------------------------------------------------------------------------------

export type DateOrder = 'ymd' | 'dmy' | 'mdy';

const OFFSET_TIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/i;
const LOCAL_TIME = /^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$/;

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(timeZone: string): Intl.DateTimeFormat {
  let f = formatters.get(timeZone);
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', {
      timeZone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
    formatters.set(timeZone, f);
  }
  return f;
}

/** The wall-clock parts of a UTC instant in a time zone. */
export function localParts(t: number, timeZone: string) {
  const parts: Record<string, number> = {};
  for (const p of formatter(timeZone).formatToParts(new Date(t))) {
    if (p.type !== 'literal') parts[p.type] = Number(p.value);
  }
  return {
    year: parts.year ?? 0,
    month: parts.month ?? 0,
    day: parts.day ?? 0,
    hour: parts.hour ?? 0,
    minute: parts.minute ?? 0,
    second: parts.second ?? 0,
  };
}

export function validTimeZone(timeZone: string): boolean {
  try {
    formatter(timeZone);
    return true;
  } catch {
    return false;
  }
}

/** UTC milliseconds of a local wall-clock time in `timeZone`, or null if that time does not exist
 * there (the hour skipped when clocks go forward). In the hour that repeats when clocks go back,
 * the first occurrence is used. The zone's offset is sampled 12 hours either side, which covers
 * any clock change near the time. */
export function zonedToUtc(
  y: number,
  mo: number,
  d: number,
  h: number,
  mi: number,
  s: number,
  timeZone: string,
): number | null {
  const wall = Date.UTC(y, mo - 1, d, h, mi, s);
  const offsetAt = (t: number) => {
    const p = localParts(t, timeZone);
    return (
      Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(t / 1000) * 1000
    );
  };
  const candidates = new Set(
    [wall - 12 * HOUR_MS, wall, wall + 12 * HOUR_MS].map((probe) => wall - offsetAt(probe)),
  );
  const valid = [...candidates].filter((t) => {
    const p = localParts(t, timeZone);
    return (
      p.year === y &&
      p.month === mo &&
      p.day === d &&
      p.hour === h &&
      p.minute === mi &&
      p.second === s
    );
  });
  return valid.length ? Math.min(...valid) : null;
}

/** A timestamp's UTC milliseconds: with an offset (or Z) as written; otherwise as local time in
 * `timeZone`, with the day/month order given. Null if it cannot be read. */
export function parseTime(text: string, order: DateOrder, timeZone: string): number | null {
  const value = text.trim();
  if (OFFSET_TIME.test(value)) {
    const t = Date.parse(value.replace(' ', 'T'));
    return Number.isNaN(t) ? null : t;
  }
  const m = LOCAL_TIME.exec(value);
  if (!m) return null;
  const [a, b, c] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const [year, month, day] = order === 'ymd' ? [a, b, c] : order === 'dmy' ? [c, b, a] : [c, a, b];
  const [hour, minute, second] = [Number(m[4]), Number(m[5]), Number(m[6] ?? 0)];
  if (year < 1900 || month < 1 || month > 12 || day < 1 || day > 31) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (probe.getUTCMonth() !== month - 1) return null; // e.g. 31 April
  return zonedToUtc(year, month, day, hour, minute, second, timeZone);
}

// ---------------------------------------------------------------------------------------------
// From rows to readings
// ---------------------------------------------------------------------------------------------

export type ValueKind = 'kwh' | 'kw';

export interface ReadOptions {
  timeColumn: number;
  valueColumn: number;
  order: DateOrder;
  timeZone: string;
  kind: ValueKind;
}

export interface Reading {
  t: number;
  value: number;
}

export interface ReadResult {
  readings: Reading[];
  unreadable: number;
  problems: string[];
}

const MAX_PROBLEMS = 10;

function number(text: string, delimiter: string): number {
  const cleaned = text.replace(/\s/g, '');
  const decimal =
    delimiter !== ',' && /^-?\d+,\d+$/.test(cleaned) ? cleaned.replace(',', '.') : cleaned;
  return cleaned === '' ? NaN : Number(decimal);
}

export function readRows(table: Table, options: ReadOptions): ReadResult {
  const readings: Reading[] = [];
  const problems: string[] = [];
  let unreadable = 0;
  table.rows.forEach((row, index) => {
    const line = index + 2; // the header is line 1
    const t = parseTime(row[options.timeColumn] ?? '', options.order, options.timeZone);
    const value = number(row[options.valueColumn] ?? '', table.delimiter);
    if (t === null || !Number.isFinite(value)) {
      unreadable += 1;
      if (problems.length < MAX_PROBLEMS) {
        problems.push(
          t === null
            ? `Line ${String(line)}: the time "${row[options.timeColumn] ?? ''}" cannot be read with the chosen format.`
            : `Line ${String(line)}: the value "${row[options.valueColumn] ?? ''}" is not a number.`,
        );
      }
      return;
    }
    readings.push({ t, value });
  });
  return { readings, unreadable, problems };
}

// ---------------------------------------------------------------------------------------------
// The check
// ---------------------------------------------------------------------------------------------

export const SUPPORTED_MINUTES = [1, 5, 10, 15, 30, 60];

export interface OpenHours {
  days: number[]; // 0 is Monday
  from: number;
  to: number; // exclusive
}

export interface Window {
  label: string;
  from: number;
  to: number; // exclusive; wraps past midnight when to <= from
}

export interface Interval {
  t: number;
  kwh: number;
  kw: number;
}

export interface Check {
  minutes: number;
  first: number;
  last: number;
  intervals: Interval[];
  duplicates: number;
  expected: number;
  missing: number;
  longestGapHours: number;
  negatives: number;
  totalKwh: number;
  peak: Interval;
  top: Interval[];
  nearPeak: number;
  hourProfile: (number | null)[];
  closedKwh: number;
  closedShare: number | null;
  baseLoadKw: number | null;
  windows: { label: string; kwh: number; share: number | null }[];
  otherKwh: number;
  events: DetectorEvent[];
  completeHours: number;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? (sorted[middle] ?? 0)
    : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}

function quantile(values: number[], q: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * q;
  const low = Math.floor(position);
  const high = Math.ceil(position);
  const a = sorted[low] ?? 0;
  const b = sorted[high] ?? 0;
  return a + (b - a) * (position - low);
}

/** Local weekday (0 is Monday) and hour of a UTC instant. */
export function localDayHour(t: number, timeZone: string): { day: number; hour: number } {
  const p = localParts(t, timeZone);
  const weekday = new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay(); // 0 is Sunday
  return { day: (weekday + 6) % 7, hour: p.hour };
}

export function inWindow(hour: number, from: number, to: number): boolean {
  if (from === to) return false;
  return from < to ? hour >= from && hour < to : hour >= from || hour < to;
}

/** Reading interval in minutes (the median step between readings), or null if it is not one of
 * the supported intervals. */
export function intervalMinutes(sortedTimes: number[]): number | null {
  const steps: number[] = [];
  for (let i = 1; i < sortedTimes.length; i += 1) {
    const step = (sortedTimes[i] ?? 0) - (sortedTimes[i - 1] ?? 0);
    if (step > 0) steps.push(step);
  }
  if (!steps.length) return null;
  const minutes = median(steps) / 60_000;
  return SUPPORTED_MINUTES.includes(minutes) ? minutes : null;
}

export function check(
  readings: readonly Reading[],
  kind: ValueKind,
  timeZone: string,
  open: OpenHours,
  windows: readonly Window[],
): Check | string {
  if (readings.length < 2) return 'At least two readings are needed.';
  const sorted = [...readings].sort((a, b) => a.t - b.t);
  const unique: Reading[] = [];
  let duplicates = 0;
  for (const r of sorted) {
    if (unique.length && unique[unique.length - 1]?.t === r.t) duplicates += 1;
    else unique.push(r);
  }
  const minutes = intervalMinutes(unique.map((r) => r.t));
  if (minutes === null) {
    return `The readings are not at a supported interval (${SUPPORTED_MINUTES.join(', ')} minutes).`;
  }
  const hours = minutes / 60;
  const step = minutes * 60_000;
  const intervals: Interval[] = unique.map((r) => {
    const kwh = kind === 'kwh' ? r.value : r.value * hours;
    return { t: r.t, kwh, kw: kwh / hours };
  });
  const first = intervals[0]?.t ?? 0;
  const last = intervals[intervals.length - 1]?.t ?? 0;
  const expected = Math.round((last - first) / step) + 1;
  let longestGap = 0;
  for (let i = 1; i < intervals.length; i += 1) {
    const gap = Math.round(((intervals[i]?.t ?? 0) - (intervals[i - 1]?.t ?? 0)) / step) - 1;
    longestGap = Math.max(longestGap, gap);
  }
  const byPower = [...intervals].sort((a, b) => b.kw - a.kw || a.t - b.t);
  const peak = byPower[0] ?? { t: first, kwh: 0, kw: 0 };

  const hourSums = new Array<number>(24).fill(0);
  const hourCounts = new Array<number>(24).fill(0);
  const closedKw: number[] = [];
  let closedKwh = 0;
  const windowKwh = windows.map(() => 0);
  let otherKwh = 0;
  const openDays = new Set(open.days);
  // Hourly energy for the detector, by the meter's local hour (so a +05:30 zone's hours are not
  // split), and only for hours with every interval present: nothing is filled.
  const perHour = new Map<number, { kwh: number; n: number }>();
  for (const i of intervals) {
    const p = localParts(i.t, timeZone);
    const day = (new Date(Date.UTC(p.year, p.month - 1, p.day)).getUTCDay() + 6) % 7;
    const hour = p.hour;
    const bucket = i.t - (p.minute * 60 + p.second) * 1000 - (((i.t % 1000) + 1000) % 1000);
    const cell = perHour.get(bucket) ?? { kwh: 0, n: 0 };
    cell.kwh += i.kwh;
    cell.n += 1;
    perHour.set(bucket, cell);
    hourSums[hour] = (hourSums[hour] ?? 0) + i.kw;
    hourCounts[hour] = (hourCounts[hour] ?? 0) + 1;
    const isOpen = openDays.has(day) && hour >= open.from && hour < open.to;
    if (!isOpen) {
      closedKwh += i.kwh;
      closedKw.push(i.kw);
    }
    const w = windows.findIndex((win) => inWindow(hour, win.from, win.to));
    if (w >= 0) windowKwh[w] = (windowKwh[w] ?? 0) + i.kwh;
    else otherKwh += i.kwh;
  }
  const totalKwh = intervals.reduce((a, i) => a + i.kwh, 0);

  const needed = 60 / minutes;
  const hourRows: HourRow[] = [];
  for (const [t, cell] of perHour) {
    if (cell.n === needed) hourRows.push({ t, value: cell.kwh });
  }

  return {
    minutes,
    first,
    last,
    intervals,
    duplicates,
    expected,
    missing: expected - intervals.length,
    longestGapHours: (longestGap * minutes) / 60,
    negatives: intervals.filter((i) => i.kwh < 0).length,
    totalKwh,
    peak,
    top: byPower.slice(0, 10),
    nearPeak: intervals.filter((i) => i.kw >= 0.9 * peak.kw).length,
    hourProfile: hourSums.map((s, h) => ((hourCounts[h] ?? 0) ? s / (hourCounts[h] ?? 1) : null)),
    closedKwh,
    closedShare: totalKwh > 0 ? closedKwh / totalKwh : null,
    baseLoadKw: quantile(closedKw, 0.1),
    windows: windows.map((w, k) => ({
      label: w.label,
      kwh: windowKwh[k] ?? 0,
      share: totalKwh > 0 ? (windowKwh[k] ?? 0) / totalKwh : null,
    })),
    otherKwh,
    events: detectEvents(hourRows),
    completeHours: hourRows.length,
  };
}

// ---------------------------------------------------------------------------------------------
// A synthetic example
// ---------------------------------------------------------------------------------------------

/**
 * A **synthetic** 15-minute meter file (made up, never a real site): four weeks in Asia/Kolkata.
 * 40 kW at night and on Sundays, 120 kW from 08:00 to 20:00 Monday to Saturday, and one Sunday
 * (21 January 2018) when the load stayed at 120 kW from 00:00 to 08:00.
 */
export function syntheticMeterCsv(): string {
  const lines = ['Timestamp,kWh'];
  const start = Date.UTC(2018, 0, 1, 0, 0) - 5.5 * HOUR_MS; // 1 January 2018, 00:00 in India
  for (let k = 0; k < 28 * 96; k += 1) {
    const t = start + k * 15 * 60_000;
    const p = localParts(t, 'Asia/Kolkata');
    const { day, hour } = localDayHour(t, 'Asia/Kolkata');
    const working = day < 6 && hour >= 8 && hour < 20;
    const leftOn = p.year === 2018 && p.month === 1 && p.day === 21 && hour < 8;
    const kw = working || leftOn ? 120 : 40;
    const stamp = `${String(p.year)}-${String(p.month).padStart(2, '0')}-${String(p.day).padStart(2, '0')} ${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')}`;
    lines.push(`${stamp},${String(kw * 0.25)}`);
  }
  return lines.join('\n') + '\n';
}
