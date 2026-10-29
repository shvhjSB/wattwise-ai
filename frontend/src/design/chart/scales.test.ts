import { describe, expect, it } from 'vitest';

import type { ExpectationPoint } from '../../api/catalog';
import {
  bandPath,
  extent,
  formatDateTime,
  intervalStats,
  linePath,
  linearScale,
  niceTicks,
  residualOf,
  runs,
  sideOf,
  timeTicks,
} from './scales';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const T0 = Date.UTC(2017, 9, 1);

function point(overrides: Partial<ExpectationPoint> = {}): ExpectationPoint {
  return {
    timestamp: '2017-10-01T00:00:00Z',
    observed: 100,
    expected: 100,
    lower: 90,
    upper: 110,
    ...overrides,
  };
}

describe('linearScale', () => {
  it('maps the domain onto the range, in either direction', () => {
    const x = linearScale([0, 10], [0, 100]);
    expect(x(0)).toBe(0);
    expect(x(5)).toBe(50);
    expect(x(10)).toBe(100);
    const y = linearScale([0, 10], [100, 0]); // SVG's y axis points down
    expect(y(0)).toBe(100);
    expect(y(10)).toBe(0);
  });

  it('maps a zero-width domain to the middle instead of dividing by zero', () => {
    expect(linearScale([5, 5], [0, 100])(5)).toBe(50);
  });
});

describe('niceTicks', () => {
  it.each([
    [0, 100, [0, 25, 50, 75, 100]],
    [0, 1, [0, 0.25, 0.5, 0.75, 1]],
    [3, 97, [25, 50, 75]],
    [0, 1000, [0, 250, 500, 750, 1000]],
    [-50, 50, [-50, -25, 0, 25, 50]],
  ])('covers %s to %s on round values', (min, max, expected) => {
    expect(niceTicks(min, max, 5)).toEqual(expected);
  });

  it('has no floating-point residue for decimal steps', () => {
    expect(niceTicks(0, 0.3, 4)).toEqual([0, 0.1, 0.2, 0.3]);
  });

  it('returns the value itself for a single value, and nothing for non-finite input', () => {
    expect(niceTicks(7, 7)).toEqual([7]);
    expect(niceTicks(Number.NaN, 1)).toEqual([]);
  });
});

describe('timeTicks', () => {
  it('uses round UTC boundaries', () => {
    const ticks = timeTicks(T0, T0 + 2 * DAY, 5);
    expect(ticks.every((t) => t.time % (6 * HOUR) === 0 || t.time % DAY === 0)).toBe(true);
    expect(ticks[0]?.time).toBe(T0);
  });

  it('shows the time of day for short ranges and only the date for long ones', () => {
    expect(timeTicks(T0, T0 + DAY, 5)[0]?.label).toBe('10-01 00:00');
    const long = timeTicks(T0, T0 + 60 * DAY, 5);
    expect(long.length).toBeGreaterThan(1);
    expect(long.every((t) => /^\d\d-\d\d$/.test(t.label))).toBe(true);
  });

  it('is empty for an empty or reversed range', () => {
    expect(timeTicks(T0, T0)).toEqual([]);
    expect(timeTicks(T0 + DAY, T0)).toEqual([]);
  });

  it('does not produce many more ticks than asked for', () => {
    expect(timeTicks(T0, T0 + 180 * DAY, 6).length).toBeLessThanOrEqual(9);
  });
});

describe('runs', () => {
  it('splits at missing values so a gap is never bridged', () => {
    const values = [1, 2, null, 3, null, null, 4, 5];

    expect(runs(values, (v) => v !== null)).toEqual([[1, 2], [3], [4, 5]]);
  });

  it('keeps a series with no gaps in one run, and returns none for all-missing input', () => {
    expect(runs([1, 2, 3], () => true)).toEqual([[1, 2, 3]]);
    expect(runs<number | null>([null, null], (v) => v !== null)).toEqual([]);
  });

  it('does not treat zero as missing', () => {
    expect(runs([0, 0, null, 0], (v) => v !== null)).toEqual([[0, 0], [0]]);
  });
});

describe('paths', () => {
  it('draws a line through points, and nothing for none', () => {
    expect(
      linePath([
        [0, 10],
        [5, 20],
      ]),
    ).toBe('M0.0,10.0 L5.0,20.0');
    expect(linePath([])).toBe('');
  });

  it('closes a band between its upper and lower edges', () => {
    const path = bandPath(
      [
        [0, 10],
        [10, 10],
      ],
      [
        [0, 30],
        [10, 30],
      ],
    );

    expect(path).toBe('M0.0,10.0 L10.0,10.0 L10.0,30.0 L0.0,30.0 Z');
    expect(bandPath([], [])).toBe('');
  });
});

describe('interval statistics', () => {
  it.each([
    [{ observed: 120 }, 'above'],
    [{ observed: 80 }, 'below'],
    [{ observed: 110 }, 'inside'], // on the bound is inside
    [{ observed: 90 }, 'inside'],
    [{ observed: null }, null],
    [{ lower: null }, null],
    [{ upper: null }, null],
  ] as const)('%j is %s the interval', (overrides, side) => {
    expect(sideOf(point(overrides))).toBe(side);
  });

  it('counts only hours with both a reading and an interval', () => {
    const stats = intervalStats([
      point({ observed: 120 }),
      point({ observed: 80 }),
      point(),
      point({ observed: null }), // not measured: not checked
      point({ lower: null, upper: null }), // no interval yet: not checked
    ]);

    expect(stats).toEqual({ checked: 3, above: 1, below: 1, outsideShare: 2 / 3 });
  });

  it('has no share when nothing could be checked', () => {
    expect(intervalStats([])).toEqual({ checked: 0, above: 0, below: 0, outsideShare: null });
  });
});

describe('residualOf', () => {
  it('is observed minus expected', () => {
    expect(residualOf(point({ observed: 130, expected: 100 }))).toBe(30);
    expect(residualOf(point({ observed: 70, expected: 100 }))).toBe(-30);
  });

  it('is null, not zero or a guess, when either value is missing', () => {
    expect(residualOf(point({ observed: null }))).toBeNull();
    expect(residualOf(point({ expected: null }))).toBeNull();
  });
});

describe('extent', () => {
  it('covers the values with a little padding and ignores missing ones', () => {
    const [low, high] = extent([10, null, 20]);

    expect(low).toBeLessThan(10);
    expect(high).toBeGreaterThan(20);
  });

  it('includes extra values such as a zero baseline', () => {
    expect(extent([5, 6], [0])[0]).toBeLessThanOrEqual(0);
  });

  it('has a usable range for no values or one value', () => {
    expect(extent([])).toEqual([0, 1]);
    const [low, high] = extent([7, 7]);
    expect(high - low).toBeGreaterThan(0);
  });
});

describe('formatDateTime', () => {
  it('shows UTC to the minute', () => {
    expect(formatDateTime(Date.UTC(2017, 9, 1, 13, 5))).toBe('2017-10-01 13:05 UTC');
  });
});
