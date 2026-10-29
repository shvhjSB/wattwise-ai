import type { ExpectationPoint, MeterAlert } from '../../api/catalog';

/** The visible part of a meter's series: point indexes, `to` exclusive. */
export interface View {
  from: number;
  to: number;
}

const HOURS_PER_DAY = 24;
/** Hours of context shown either side of an alert. */
const ALERT_CONTEXT_HOURS = 3 * HOURS_PER_DAY;
export const DEFAULT_DAYS = 14;

/** The last `days` days of the series. */
export function lastDays(total: number, days: number): View {
  return { from: Math.max(0, total - days * HOURS_PER_DAY), to: total };
}

/** The whole series. */
export function wholeSeries(total: number): View {
  return { from: 0, to: total };
}

function indexAtOrAfter(points: readonly ExpectationPoint[], time: number): number {
  const i = points.findIndex((p) => Date.parse(p.timestamp) >= time);
  return i === -1 ? points.length : i;
}

/** The alert with three days of context either side, clipped to the series. */
export function alertView(points: readonly ExpectationPoint[], alert: MeterAlert): View {
  const from = indexAtOrAfter(points, Date.parse(alert.start));
  const to = indexAtOrAfter(points, Date.parse(alert.end));
  return {
    from: Math.max(0, from - ALERT_CONTEXT_HOURS),
    to: Math.min(points.length, Math.max(to, from + 1) + ALERT_CONTEXT_HOURS),
  };
}

/** The highest-priority alert (the alerts arrive in that order from the API), if any. */
export function topAlert(alerts: readonly MeterAlert[]): MeterAlert | undefined {
  return alerts.reduce<MeterAlert | undefined>(
    (best, a) => (best === undefined || a.priority_score > best.priority_score ? a : best),
    undefined,
  );
}

/** Where to start: around the meter's top alert if it has one, else its last fortnight. */
export function defaultView(
  points: readonly ExpectationPoint[],
  alerts: readonly MeterAlert[],
): View {
  const top = topAlert(alerts);
  return top ? alertView(points, top) : lastDays(points.length, DEFAULT_DAYS);
}

/** Move the view by half its width, keeping its width and staying inside the series. */
export function pan(view: View, direction: -1 | 1, total: number): View {
  const width = view.to - view.from;
  const step = Math.max(1, Math.floor(width / 2)) * direction;
  const from = Math.min(Math.max(0, view.from + step), Math.max(0, total - width));
  return { from, to: from + width };
}

/** The view's width in whole days (at least one). */
export function viewDays(view: View): number {
  return Math.max(1, Math.round((view.to - view.from) / HOURS_PER_DAY));
}

/** A zoomed view of the same centre, `days` wide. */
export function zoomTo(view: View, days: number, total: number): View {
  const width = Math.min(total, days * HOURS_PER_DAY);
  const centre = Math.floor((view.from + view.to) / 2);
  const from = Math.min(Math.max(0, centre - Math.floor(width / 2)), Math.max(0, total - width));
  return { from, to: from + width };
}
