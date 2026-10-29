import type { ExpectationPoint } from '../../api/catalog';
import { formatDateTime, linearScale, residualOf, sideOf } from './scales';

export const CHART_WIDTH = 900;
export const MARGIN = { top: 12, right: 14, bottom: 30, left: 60 };

export const timeOf = (point: ExpectationPoint): number => Date.parse(point.timestamp);

export interface Geometry {
  x: (t: number) => number;
  innerRight: number;
  innerBottom: number;
  start: number;
  end: number;
}

/** The x scale and plot area shared by the main and residual charts. */
export function geometry(
  points: readonly ExpectationPoint[],
  height: number,
  width = CHART_WIDTH,
): Geometry {
  const first = points[0];
  const last = points[points.length - 1];
  const start = first ? timeOf(first) : 0;
  const finish = last ? timeOf(last) : 1;
  const end = finish > start ? finish : start + 1;
  const innerRight = width - MARGIN.right;
  return {
    x: linearScale([start, end], [MARGIN.left, innerRight]),
    innerRight,
    innerBottom: height - MARGIN.bottom,
    start,
    end,
  };
}

/** The index of the point nearest an x position on the chart (-1 for no points). */
export function nearestIndex(points: readonly ExpectationPoint[], g: Geometry, x: number): number {
  if (points.length === 0) return -1;
  const t = g.start + ((x - MARGIN.left) / (g.innerRight - MARGIN.left)) * (g.end - g.start);
  let lo = 0;
  let hi = points.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const midPoint = points[mid];
    if (midPoint && timeOf(midPoint) < t) lo = mid + 1;
    else hi = mid;
  }
  const before = Math.max(0, lo - 1);
  const a = points[before];
  const b = points[lo];
  if (!a || !b) return lo;
  return Math.abs(timeOf(a) - t) <= Math.abs(timeOf(b) - t) ? before : lo;
}

/** The pointer's x position in chart coordinates (the SVG scales to its container). */
export function chartX(
  event: { clientX: number; currentTarget: Element },
  width = CHART_WIDTH,
): number {
  const box = event.currentTarget.getBoundingClientRect();
  return box.width === 0 ? 0 : ((event.clientX - box.left) / box.width) * width;
}

/** Text for a point: what the chart shows at that hour. */
export function describePoint(point: ExpectationPoint, unit: string): string[] {
  const number = (v: number | null) => (v === null ? 'not available' : `${v.toFixed(1)} ${unit}`);
  const residual = residualOf(point);
  const side = sideOf(point);
  const sideText = {
    above: 'Above the interval',
    below: 'Below the interval',
    inside: 'Inside the interval',
  };
  return [
    formatDateTime(timeOf(point)),
    `Observed: ${point.observed === null ? 'not measured' : number(point.observed)}`,
    `Expected: ${number(point.expected)}`,
    point.lower === null || point.upper === null
      ? 'Interval: not available'
      : `Interval: ${point.lower.toFixed(1)} to ${point.upper.toFixed(1)} ${unit}`,
    residual === null
      ? 'Difference: not available'
      : `Difference: ${residual >= 0 ? '+' : ''}${residual.toFixed(1)} ${unit}`,
    side === null ? 'Not compared with an interval' : sideText[side],
  ];
}
