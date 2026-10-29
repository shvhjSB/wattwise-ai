/**
 * The chart's arithmetic, kept apart from drawing so it can be tested: scales, tick choice,
 * gap-aware segments and the residual statistics. Times are UTC milliseconds throughout.
 */

import type { ExpectationPoint } from '../../api/catalog';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** A function mapping `domain` linearly onto `range`; a zero-width domain maps to the middle. */
export function linearScale(
  domain: readonly [number, number],
  range: readonly [number, number],
): (value: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  if (d1 === d0) return () => (r0 + r1) / 2;
  return (value) => r0 + ((value - d0) / (d1 - d0)) * (r1 - r0);
}

/** Round, evenly spaced values covering [min, max], about `count` of them. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (max === min) return [min];
  const rough = (max - min) / Math.max(1, count - 1);
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  // The nice step (1, 2, 2.5, 5 or 10 times a power of ten) nearest the rough one, by ratio.
  const step = [1, 2, 2.5, 5, 10]
    .map((m) => m * magnitude)
    .reduce((best, s) =>
      Math.abs(Math.log(s / rough)) < Math.abs(Math.log(best / rough)) ? s : best,
    );
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  // Index-based so a decimal step does not accumulate floating-point error.
  for (let i = 0; first + i * step <= max + step * 1e-9; i++) {
    ticks.push(Number((first + i * step).toFixed(10)));
  }
  return ticks;
}

const STEPS = [HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY, 28 * DAY];

export interface TimeTick {
  time: number;
  label: string;
}

/** Time ticks on round UTC boundaries, at most about `count` of them. */
export function timeTicks(start: number, end: number, count = 6): TimeTick[] {
  if (!(end > start)) return [];
  const wanted = (end - start) / Math.max(1, count - 1);
  const step = STEPS.find((s) => s >= wanted) ?? 28 * DAY;
  const ticks: TimeTick[] = [];
  for (let t = Math.ceil(start / step) * step; t <= end; t += step) {
    ticks.push({ time: t, label: formatTick(t, step) });
  }
  return ticks;
}

function formatTick(time: number, step: number): string {
  const iso = new Date(time).toISOString();
  return step < DAY ? `${iso.slice(5, 10)} ${iso.slice(11, 16)}` : iso.slice(5, 10);
}

/** A UTC time for display, to the minute. */
export function formatDateTime(time: number): string {
  const iso = new Date(time).toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
}

/**
 * Split values into runs of consecutive defined ones. A missing reading ends a run, so a line
 * drawn per run shows the gap and never connects across it (not measured is not zero).
 */
export function runs<T>(items: readonly T[], isPresent: (item: T) => boolean): T[][] {
  const out: T[][] = [];
  let current: T[] = [];
  for (const item of items) {
    if (isPresent(item)) {
      current.push(item);
    } else if (current.length > 0) {
      out.push(current);
      current = [];
    }
  }
  if (current.length > 0) out.push(current);
  return out;
}

/** An SVG path through the given screen points; empty for no points. */
export function linePath(points: readonly (readonly [number, number])[]): string {
  return points
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ');
}

/** A closed SVG path for the area between an upper and a lower edge (same x positions). */
export function bandPath(
  upper: readonly (readonly [number, number])[],
  lower: readonly (readonly [number, number])[],
): string {
  if (upper.length === 0) return '';
  return `${linePath(upper)} ${linePath([...lower].reverse()).replace('M', 'L')} Z`;
}

export type Side = 'above' | 'below' | 'inside';

/** Where an observed value sits against its interval (null if either is missing). */
export function sideOf(point: ExpectationPoint): Side | null {
  if (point.observed === null || point.lower === null || point.upper === null) return null;
  if (point.observed > point.upper) return 'above';
  if (point.observed < point.lower) return 'below';
  return 'inside';
}

export interface IntervalStats {
  /** Hours with both a reading and an interval. */
  checked: number;
  above: number;
  below: number;
  /** Share of checked hours outside the interval; null when none were checked. */
  outsideShare: number | null;
}

/** How the readings sat against the interval over `points`. */
export function intervalStats(points: readonly ExpectationPoint[]): IntervalStats {
  let checked = 0;
  let above = 0;
  let below = 0;
  for (const point of points) {
    const side = sideOf(point);
    if (side === null) continue;
    checked += 1;
    if (side === 'above') above += 1;
    if (side === 'below') below += 1;
  }
  return {
    checked,
    above,
    below,
    outsideShare: checked === 0 ? null : (above + below) / checked,
  };
}

/** Observed minus expected, or null when either is missing (never computed from a gap). */
export function residualOf(point: ExpectationPoint): number | null {
  return point.observed === null || point.expected === null
    ? null
    : point.observed - point.expected;
}

/** The smallest range containing every finite value, widened a little so lines do not touch it. */
export function extent(
  values: readonly (number | null)[],
  include: readonly number[] = [],
): [number, number] {
  const finite = [
    ...values.filter((v): v is number => v !== null && Number.isFinite(v)),
    ...include,
  ];
  if (finite.length === 0) return [0, 1];
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  if (min === max) return [min - 1, max + 1];
  const pad = (max - min) * 0.05;
  return [min - pad, max + pad];
}
