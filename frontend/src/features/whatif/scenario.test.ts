import { describe, expect, it } from 'vitest';

import type { ExpectationPoint } from '../../api/catalog';
import {
  DEFAULT_SCENARIO,
  inHours,
  localHourOf,
  runScenario,
  validTariff,
  type Scenario,
} from './scenario';

/** Four hours from 00:00 UTC; the third has no interval, the fourth no reading. */
const POINTS: ExpectationPoint[] = [
  { timestamp: '2016-02-01T00:00:00Z', observed: 12, expected: 10, lower: 8, upper: 11 },
  { timestamp: '2016-02-01T01:00:00Z', observed: 9, expected: 10, lower: 8, upper: 11 },
  { timestamp: '2016-02-01T02:00:00Z', observed: 20, expected: 10, lower: null, upper: null },
  { timestamp: '2016-02-01T03:00:00Z', observed: null, expected: 10, lower: 8, upper: 11 },
];
const UTC = localHourOf('UTC');

function scenario(change: Partial<Scenario>): Scenario {
  return { ...DEFAULT_SCENARIO, ...change };
}

describe('runScenario', () => {
  it('counts potential excess above the interval only where there is one', () => {
    const result = runScenario(POINTS, DEFAULT_SCENARIO, UTC, 'kWh');

    expect(result.recorded).toBe(41);
    expect(result.comparableHours).toBe(3);
    expect(result.expectedComparable).toBe(30);
    expect(result.excess).toBe(1); // 12 - 11; hour 2 has no interval
    expect(result.excessHours).toBe(1);
    expect(result.hoursWithoutThreshold).toBe(1);
    expect(result.excessCost).toBeNull(); // no tariff, no cost
  });

  it('can use a margin over the expectation instead', () => {
    const result = runScenario(
      POINTS,
      scenario({ excessRule: 'margin', marginPct: 10 }),
      UTC,
      'kWh',
    );

    // thresholds 11, 11, 11: excess 1 + 0 + 9
    expect(result.excess).toBeCloseTo(10);
    expect(result.excessHours).toBe(2);
    expect(result.hoursWithoutThreshold).toBe(0);
  });

  it('applies a cut only in the chosen local hours, without changing the recording', () => {
    const result = runScenario(
      POINTS,
      scenario({ reductionPct: 50, fromHour: 1, toHour: 3 }),
      UTC,
      'kWh',
    );

    expect(result.reduction).toBeCloseTo(4.5 + 10); // hours 1 and 2
    expect(result.reductionHours).toBe(2);
    expect(result.scenarioTotal).toBeCloseTo(41 - 14.5);
    expect(result.points.map((p) => p.observed)).toEqual([12, 9, 20, null]);
    expect(result.points.map((p) => p.scenario)).toEqual([12, 4.5, 10, null]);
    expect(result.excessAfter).toBe(1); // hour 0 is outside the chosen hours
  });

  it('prices kWh only, with a valid tariff', () => {
    const tariff = scenario({ price: 0.2, currency: 'USD', excessRule: 'margin' });

    expect(runScenario(POINTS, tariff, UTC, 'kWh').excessCost).toBeCloseTo(2);
    expect(runScenario(POINTS, tariff, UTC, 'm3').excessCost).toBeNull();
  });
});

describe('helpers', () => {
  it('wraps hour ranges past midnight', () => {
    expect(inHours(23, 22, 6)).toBe(true);
    expect(inHours(3, 22, 6)).toBe(true);
    expect(inHours(12, 22, 6)).toBe(false);
    expect(inHours(9, 8, 17)).toBe(true);
    expect(inHours(17, 8, 17)).toBe(false);
    expect(inHours(5, 5, 5)).toBe(false);
  });

  it('reads the local hour in the building’s time zone', () => {
    expect(localHourOf('America/New_York')('2016-07-01T12:00:00Z')).toBe(8);
    expect(localHourOf('Asia/Kolkata')('2016-07-01T12:00:00Z')).toBe(17);
  });

  it('accepts only a positive price with a three-letter currency', () => {
    expect(validTariff(scenario({ price: 0.15, currency: 'EUR' }))).toBe(true);
    expect(validTariff(scenario({ price: 0, currency: 'EUR' }))).toBe(false);
    expect(validTariff(scenario({ price: 0.15, currency: 'euro' }))).toBe(false);
    expect(validTariff(scenario({ price: null, currency: 'EUR' }))).toBe(false);
  });
});
