import type { ExpectationPoint } from '../../api/catalog';
import { MARGIN, geometry } from '../../design/chart/geometry';
import { TimeAxis } from '../../design/chart/TimeAxis';
import { extent, linePath, linearScale, niceTicks, runs } from '../../design/chart/scales';
import type { ScenarioPoint } from './scenario';

type Line = 'observed' | 'expected' | 'threshold' | 'scenario';

const STYLES: Record<Line, { className: string; dash?: string; width: string }> = {
  observed: { className: 'stroke-accent', width: '1.75' },
  expected: { className: 'stroke-muted', dash: '5 3', width: '1.5' },
  threshold: { className: 'stroke-warning', dash: '2 3', width: '1.5' },
  scenario: { className: 'stroke-ink', width: '1.25' },
};

/**
 * The scenario is drawn under the recorded line, so it shows only where the cut changes it.
 * Recorded readings, the model's expectation, the excess threshold and the scenario. A missing
 * value is a gap, never zero. The same totals are given in the table beside the chart.
 */
export function ScenarioChart({
  points,
  unit,
  label,
  showScenario,
  height = 280,
}: {
  points: readonly ScenarioPoint[];
  unit: string;
  label: string;
  showScenario: boolean;
  height?: number;
}) {
  const asExpectation: ExpectationPoint[] = points.map((p) => ({
    timestamp: p.timestamp,
    observed: p.observed,
    expected: p.expected,
    lower: null,
    upper: null,
  }));
  const g = geometry(asExpectation, height);
  const [low, high] = extent(points.flatMap((p) => [p.observed, p.expected, p.threshold]));
  const y = linearScale([low, high], [g.innerBottom, MARGIN.top]);
  const lines: Line[] = showScenario
    ? ['expected', 'threshold', 'scenario', 'observed']
    : ['expected', 'threshold', 'observed'];

  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 900 ${String(height)}`}
      className="h-auto w-full select-none"
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
      {lines.map((line) =>
        runs(points, (p) => p[line] !== null).map((run) => (
          <path
            key={`${line}-${run[0]?.timestamp ?? ''}`}
            data-testid={`${line}-line`}
            d={linePath(run.map((p) => [g.x(Date.parse(p.timestamp)), y(p[line] ?? low)] as const))}
            className={`fill-none ${STYLES[line].className}`}
            strokeWidth={STYLES[line].width}
            strokeDasharray={STYLES[line].dash}
          />
        )),
      )}
    </svg>
  );
}
