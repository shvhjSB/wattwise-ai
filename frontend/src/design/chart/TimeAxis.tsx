import { MARGIN, type Geometry } from './geometry';
import { timeTicks } from './scales';

/** The bottom axis: a baseline and ticks on round UTC boundaries. */
export function TimeAxis({ g, height }: { g: Geometry; height: number }) {
  return (
    <g fontSize="11">
      <line
        x1={MARGIN.left}
        x2={g.innerRight}
        y1={g.innerBottom}
        y2={g.innerBottom}
        className="stroke-edge"
      />
      {timeTicks(g.start, g.end, 6).map((tick) => (
        <g key={tick.time}>
          <line
            x1={g.x(tick.time)}
            x2={g.x(tick.time)}
            y1={g.innerBottom}
            y2={g.innerBottom + 4}
            className="stroke-edge"
          />
          <text x={g.x(tick.time)} y={height - 8} textAnchor="middle" className="fill-muted">
            {tick.label}
          </text>
        </g>
      ))}
    </g>
  );
}
