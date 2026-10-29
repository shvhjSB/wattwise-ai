import type { ExpectationPoint } from '../../api/catalog';
import { CHART_WIDTH, MARGIN, chartX, geometry, nearestIndex, timeOf } from './geometry';
import { TimeAxis } from './TimeAxis';
import { extent, linearScale, niceTicks, residualOf, sideOf } from './scales';

const TOP = 10;

/**
 * Observed minus expected for each hour, on a shared time axis. A bar rises above zero where the
 * reading was above the expectation and falls below where it was under. Bars for readings outside
 * the interval are drawn in the alert colour. An hour with no reading or no expectation has no bar:
 * a gap is not a difference of zero.
 */
export function ResidualChart({
  points,
  unit,
  label,
  cursor,
  onCursor,
  height = 140,
}: {
  points: readonly ExpectationPoint[];
  unit: string;
  label: string;
  cursor: number | null;
  onCursor: (index: number | null) => void;
  height?: number;
}) {
  const g = geometry(points, height);
  const residuals = points.map(residualOf);
  const [low, high] = extent(residuals, [0]);
  const y = linearScale([low, high], [g.innerBottom, TOP]);
  const zero = y(0);

  /** One path of vertical bars: for readings outside the interval, or for all the others. */
  const bars = (outsideInterval: boolean): string =>
    points
      .map((p, i) => {
        const r = residuals[i] ?? null;
        const side = sideOf(p);
        const isOutside = side === 'above' || side === 'below';
        if (r === null || isOutside !== outsideInterval) return '';
        return `M${g.x(timeOf(p)).toFixed(1)},${zero.toFixed(1)}V${y(r).toFixed(1)}`;
      })
      .join('');
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
        {niceTicks(low, high, 4).map((tick) => (
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
          transform={`translate(12 ${String((TOP + g.innerBottom) / 2)}) rotate(-90)`}
          textAnchor="middle"
          className="fill-muted"
        >
          {unit} difference
        </text>
      </g>
      <line x1={MARGIN.left} x2={g.innerRight} y1={zero} y2={zero} className="stroke-edge" />
      <TimeAxis g={g} height={height} />
      <path
        data-testid="residual-inside"
        d={bars(false)}
        className="fill-none stroke-accent"
        strokeWidth="1.5"
      />
      <path
        data-testid="residual-outside"
        d={bars(true)}
        className="fill-none stroke-danger"
        strokeWidth="1.5"
      />
      {active ? (
        <line
          x1={g.x(timeOf(active))}
          x2={g.x(timeOf(active))}
          y1={TOP}
          y2={g.innerBottom}
          className="stroke-ink"
          strokeWidth="1"
        />
      ) : null}
    </svg>
  );
}
