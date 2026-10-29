import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ExpectationPoint } from '../../api/catalog';
import { alertAt, points as makePoints } from '../../test/expectationFixture';
import { CHART_WIDTH, describePoint, geometry, nearestIndex } from './geometry';
import { ResidualChart } from './ResidualChart';
import { TimeSeriesChart } from './TimeSeriesChart';

afterEach(() => {
  vi.restoreAllMocks();
});

function chart(
  points: ExpectationPoint[],
  extra: Partial<Parameters<typeof TimeSeriesChart>[0]> = {},
) {
  const onCursor = vi.fn();
  render(
    <TimeSeriesChart
      points={points}
      alerts={[]}
      unit="kWh"
      label="Test chart"
      cursor={null}
      onCursor={onCursor}
      {...extra}
    />,
  );
  return onCursor;
}

describe('TimeSeriesChart', () => {
  it('is a labelled image', () => {
    chart(makePoints(100));

    expect(screen.getByRole('img', { name: 'Test chart' })).toBeInTheDocument();
  });

  it('breaks the observed line at a missing reading instead of bridging or zeroing it', () => {
    chart(makePoints(100)); // hour 50 is not measured

    const lines = screen.getAllByTestId('observed-line');
    expect(lines).toHaveLength(2);
    // Each line is one run: a single move-to, no connection across the gap.
    for (const line of lines) expect(line.getAttribute('d')?.match(/M/g)).toHaveLength(1);
  });

  it('has one observed line when nothing is missing', () => {
    chart(makePoints(40).map((p) => ({ ...p, observed: 100 })));

    expect(screen.getAllByTestId('observed-line')).toHaveLength(1);
  });

  it('starts the interval band where the interval starts', () => {
    chart(makePoints(100)); // no interval for the first 24 hours

    expect(screen.getAllByTestId('interval-band')).toHaveLength(1);
    expect(screen.getAllByTestId('expected-line')).toHaveLength(1);
  });

  it('draws no band when the meter has no interval', () => {
    chart(makePoints(100).map((p) => ({ ...p, lower: null, upper: null })));

    expect(screen.queryByTestId('interval-band')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('expected-line')).toHaveLength(1);
  });

  it('draws only the readings, when there is no expectation', () => {
    chart(makePoints(100).map((p) => ({ ...p, expected: null, lower: null, upper: null })));

    expect(screen.queryByTestId('expected-line')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('observed-line').length).toBeGreaterThan(0);
  });

  it('marks exactly the readings outside the interval', () => {
    chart(makePoints(400)); // the spike at hours 300-309

    expect(screen.getAllByTestId('outside-marker')).toHaveLength(10);
  });

  it('shades only the alerts that overlap the visible range', () => {
    chart(makePoints(100), {
      alerts: [alertAt(1, 10, 20), alertAt(2, 500, 520)],
    });

    expect(screen.getAllByTestId('alert-window')).toHaveLength(1);
  });

  it('keeps a long alert inside the plot', () => {
    chart(makePoints(100), { alerts: [alertAt(1, -50, 5000)] });

    const rect = screen.getByTestId('alert-window');
    const x = Number(rect.getAttribute('x'));
    const width = Number(rect.getAttribute('width'));
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x + width).toBeLessThanOrEqual(CHART_WIDTH);
  });

  it('shows a cursor line only when a point is selected', () => {
    chart(makePoints(100), { cursor: 10 });

    expect(screen.getByTestId('cursor')).toBeInTheDocument();
  });

  it('has no cursor by default', () => {
    chart(makePoints(100));

    expect(screen.queryByTestId('cursor')).not.toBeInTheDocument();
  });

  it('reports the point under the pointer, and clears when the pointer leaves', () => {
    const onCursor = chart(makePoints(101)); // 100 hours across the plot
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      width: CHART_WIDTH,
      top: 0,
      right: CHART_WIDTH,
      bottom: 280,
      height: 280,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    const svg = screen.getByRole('img');
    const g = geometry(makePoints(101), 280);

    fireEvent.pointerMove(svg, { clientX: g.x(Date.parse(makePoints(101)[40]?.timestamp ?? '')) });
    expect(onCursor).toHaveBeenLastCalledWith(40);

    fireEvent.pointerLeave(svg);
    expect(onCursor).toHaveBeenLastCalledWith(null);
  });

  it('does not fail with no points', () => {
    chart([]);

    expect(screen.getByRole('img', { name: 'Test chart' })).toBeInTheDocument();
    expect(screen.queryByTestId('observed-line')).not.toBeInTheDocument();
  });
});

describe('ResidualChart', () => {
  function residual(points: ExpectationPoint[]) {
    render(
      <ResidualChart
        points={points}
        unit="kWh"
        label="Residuals"
        cursor={null}
        onCursor={() => undefined}
      />,
    );
  }

  it('draws a bar for each hour with a reading and an expectation, split by the interval', () => {
    residual(makePoints(400));

    const outside = screen.getByTestId('residual-outside').getAttribute('d') ?? '';
    const inside = screen.getByTestId('residual-inside').getAttribute('d') ?? '';
    expect(outside.match(/M/g)).toHaveLength(10); // the spike
    // 400 hours, minus the 10 outside, minus the hour with no reading
    expect(inside.match(/M/g)).toHaveLength(389);
  });

  it('draws no bar for an hour that was not measured', () => {
    residual(makePoints(60));

    const inside = screen.getByTestId('residual-inside').getAttribute('d') ?? '';
    expect(inside.match(/M/g)).toHaveLength(59);
  });

  it('draws no bar when there is no expectation', () => {
    residual(makePoints(60).map((p) => ({ ...p, expected: null })));

    expect(screen.getByTestId('residual-inside').getAttribute('d')).toBe('');
  });

  it('is a labelled image', () => {
    residual(makePoints(10));

    expect(screen.getByRole('img', { name: 'Residuals' })).toBeInTheDocument();
  });
});

describe('geometry helpers', () => {
  const pts = makePoints(101);
  const g = geometry(pts, 280);

  it('finds the nearest point to an x position', () => {
    const at = (i: number) => g.x(Date.parse(pts[i]?.timestamp ?? ''));

    expect(nearestIndex(pts, g, at(0))).toBe(0);
    expect(nearestIndex(pts, g, at(50))).toBe(50);
    expect(nearestIndex(pts, g, at(100))).toBe(100);
    expect(nearestIndex(pts, g, at(50) + 1)).toBe(50);
    expect(nearestIndex(pts, g, -100)).toBe(0);
    expect(nearestIndex(pts, g, 5000)).toBe(100);
  });

  it('has no index for no points', () => {
    expect(nearestIndex([], geometry([], 280), 100)).toBe(-1);
  });

  it('describes a point in words, saying what is not available', () => {
    const lines = describePoint(
      {
        timestamp: '2017-07-01T05:00:00Z',
        observed: null,
        expected: 100,
        lower: null,
        upper: null,
      },
      'kWh',
    );

    expect(lines).toContain('2017-07-01 05:00 UTC');
    expect(lines).toContain('Observed: not measured');
    expect(lines).toContain('Expected: 100.0 kWh');
    expect(lines).toContain('Interval: not available');
    expect(lines).toContain('Difference: not available');
    expect(lines).toContain('Not compared with an interval');
  });

  it('says which side of the interval a reading is on, with its difference', () => {
    const lines = describePoint(
      { timestamp: '2017-07-01T05:00:00Z', observed: 150, expected: 100, lower: 90, upper: 110 },
      'kWh',
    );

    expect(lines).toContain('Difference: +50.0 kWh');
    expect(lines).toContain('Above the interval');
  });
});
