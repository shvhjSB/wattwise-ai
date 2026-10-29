import type { ExpectationPoint, MeterAlert } from '../../api/catalog';
import { CHART_WIDTH, MARGIN, chartX, geometry, nearestIndex, timeOf } from './geometry';
import { TimeAxis } from './TimeAxis';
import { bandPath, extent, linePath, linearScale, niceTicks, runs, sideOf } from './scales';

type Xy = [number, number];

/**
 * A meter's readings against the model's expectation and its interval.
 *
 * - A missing reading is a gap in the line: the line never connects across it, and a gap is never
 *   drawn as zero. The same holds for hours without an expectation or interval.
 * - Readings outside the interval are marked, and alert windows are shaded.
 * - The chart is a labelled image; the same numbers are available as a table and through the hour
 *   slider beside it.
 */
export function TimeSeriesChart({
  points,
  alerts,
  unit,
  label,
  cursor,
  onCursor,
  height = 280,
}: {
  points: readonly ExpectationPoint[];
  alerts: readonly MeterAlert[];
  unit: string;
  label: string;
  cursor: number | null;
  onCursor: (index: number | null) => void;
  height?: number;
}) {
  const g = geometry(points, height);
  const [low, high] = extent(points.flatMap((p) => [p.observed, p.expected, p.lower, p.upper]));
  const y = linearScale([low, high], [g.innerBottom, MARGIN.top]);
  const at = (p: ExpectationPoint, value: number | null): Xy => [g.x(timeOf(p)), y(value ?? low)];

  const observedRuns = runs(points, (p) => p.observed !== null);
  const expectedRuns = runs(points, (p) => p.expected !== null);
  const bandRuns = runs(points, (p) => p.lower !== null && p.upper !== null);
  const outside = points.filter((p) => {
    const side = sideOf(p);
    return side === 'above' || side === 'below';
  });
  const shown = alerts.filter((a) => Date.parse(a.end) > g.start && Date.parse(a.start) < g.end);
  const active = cursor === null ? undefined : points[cursor];

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${String(CHART_WIDTH)} ${String(height)}`}
      className="h-auto w-full touch-none select-none"
      onPointerMove={(event) => {
        const index = nearestIndex(points, g, chartX(event));
        if (index >= 0) onCursor(index);
      }}
      onPointerLeave={() => {
        onCursor(null);
      }}
    >
      <g fontSize="11">
        {niceTicks(low, high, 5).map((tick) => (
          <g key={tick}>
            <line
              x1={MARGIN.left}
              x2={g.innerRight}
              y1={y(tick)}
              y2={y(tick)}
              className="stroke-line"
            />
            <text x={MARGIN.left - 6} y={y(tick) + 4} textAnchor="end" className="fill-muted">
              {tick.toLocaleString('en')}
            </text>
          </g>
        ))}
        <text
          transform={`translate(12 ${String((MARGIN.top + g.innerBottom) / 2)}) rotate(-90)`}
          textAnchor="middle"
          className="fill-muted"
        >
          {unit} per hour
        </text>
      </g>
      <TimeAxis g={g} height={height} />

      {shown.map((a) => {
        const from = g.x(Math.max(Date.parse(a.start), g.start));
        const to = g.x(Math.min(Date.parse(a.end), g.end));
        return (
          <rect
            key={a.alert_id}
            data-testid="alert-window"
            x={from}
            y={MARGIN.top}
            width={Math.max(2, to - from)}
            height={g.innerBottom - MARGIN.top}
            className="fill-warning opacity-15"
          />
        );
      })}

      {bandRuns.map((run) => (
        <path
          key={`band-${run[0]?.timestamp ?? ''}`}
          data-testid="interval-band"
          d={bandPath(
            run.map((p) => at(p, p.upper)),
            run.map((p) => at(p, p.lower)),
          )}
          className="fill-accent opacity-15"
        />
      ))}

      {expectedRuns.map((run) => (
        <path
          key={`expected-${run[0]?.timestamp ?? ''}`}
          data-testid="expected-line"
          d={linePath(run.map((p) => at(p, p.expected)))}
          className="fill-none stroke-muted"
          strokeWidth="1.5"
          strokeDasharray="5 3"
        />
      ))}
      {observedRuns.map((run) => {
        const only = run.length === 1 ? run[0] : undefined;
        const dot = only ? at(only, only.observed) : undefined;
        return (
          <g key={`observed-${run[0]?.timestamp ?? ''}`}>
            <path
              data-testid="observed-line"
              d={linePath(run.map((p) => at(p, p.observed)))}
              className="fill-none stroke-accent"
              strokeWidth="1.75"
            />
            {dot ? <circle cx={dot[0]} cy={dot[1]} r="2" className="fill-accent" /> : null}
          </g>
        );
      })}

      {outside.map((p) => {
        const [cx, cy] = at(p, p.observed);
        return (
          <circle
            key={p.timestamp}
            data-testid="outside-marker"
            cx={cx}
            cy={cy}
            r="2.5"
            className="fill-danger"
          />
        );
      })}

      {active ? (
        <line
          data-testid="cursor"
          x1={g.x(timeOf(active))}
          x2={g.x(timeOf(active))}
          y1={MARGIN.top}
          y2={g.innerBottom}
          className="stroke-ink"
          strokeWidth="1"
        />
      ) : null}
    </svg>
  );
}
