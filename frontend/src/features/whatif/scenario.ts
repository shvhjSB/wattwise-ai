import type { ExpectationPoint } from '../../api/catalog';

/**
 * The what-if lab's arithmetic (T049). Everything is computed from stored readings and the
 * model's stored expectation and interval; nothing is saved, and the recorded readings are never
 * changed. A scenario is a hypothesis to explore, and its potential excess is not a verified saving.
 */

/** Which line consumption must exceed to count as potential excess. */
export type ExcessRule = 'interval' | 'margin';

export interface Scenario {
  /** `interval`: above the stored interval's upper bound; `margin`: above expected × (1 + margin). */
  excessRule: ExcessRule;
  marginPct: number;
  /** A hypothetical cut, in percent of the recorded reading, in the local hours [fromHour, toHour). */
  reductionPct: number;
  fromHour: number;
  toHour: number;
  /** A tariff the user enters, per kWh; no tariff means no cost is shown. */
  price: number | null;
  currency: string;
}

export const DEFAULT_SCENARIO: Scenario = {
  excessRule: 'interval',
  marginPct: 10,
  reductionPct: 0,
  fromHour: 22,
  toHour: 6,
  price: null,
  currency: '',
};

export interface ScenarioPoint {
  timestamp: string;
  observed: number | null;
  expected: number | null;
  threshold: number | null;
  scenario: number | null;
}

export interface ScenarioResult {
  hours: number;
  recorded: number;
  /** Hours with both a reading and an expectation, and their sums. */
  comparableHours: number;
  recordedComparable: number;
  expectedComparable: number;
  /** Potential excess over the threshold, in recorded consumption and after the scenario. */
  excess: number;
  excessHours: number;
  excessAfter: number;
  /** Hours with a reading but no threshold (no expectation, or no interval yet). */
  hoursWithoutThreshold: number;
  reduction: number;
  reductionHours: number;
  scenarioTotal: number;
  /** Costs only for kWh meters with a valid tariff; otherwise null. */
  excessCost: number | null;
  excessAfterCost: number | null;
  reductionCost: number | null;
  points: ScenarioPoint[];
}

/** Whether a local hour lies in [from, to), wrapping past midnight when to <= from. */
export function inHours(hour: number, from: number, to: number): boolean {
  if (from === to) return false;
  return from < to ? hour >= from && hour < to : hour >= from || hour < to;
}

/** The local clock hour of a UTC timestamp in an IANA time zone. */
export function localHourOf(timeZone: string): (timestamp: string) => number {
  const format = new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', hourCycle: 'h23' });
  return (timestamp) => Number(format.format(new Date(timestamp)));
}

export function validTariff(scenario: Scenario): boolean {
  return (
    scenario.price !== null &&
    Number.isFinite(scenario.price) &&
    scenario.price > 0 &&
    /^[A-Z]{3}$/.test(scenario.currency)
  );
}

function thresholdOf(point: ExpectationPoint, scenario: Scenario): number | null {
  if (scenario.excessRule === 'interval') return point.upper;
  return point.expected === null ? null : point.expected * (1 + scenario.marginPct / 100);
}

export function runScenario(
  points: readonly ExpectationPoint[],
  scenario: Scenario,
  hourOf: (timestamp: string) => number,
  unit: string,
): ScenarioResult {
  const cut = Math.min(Math.max(scenario.reductionPct, 0), 100) / 100;
  let recorded = 0;
  let comparableHours = 0;
  let recordedComparable = 0;
  let expectedComparable = 0;
  let excess = 0;
  let excessHours = 0;
  let excessAfter = 0;
  let hoursWithoutThreshold = 0;
  let reduction = 0;
  let reductionHours = 0;
  const out: ScenarioPoint[] = [];

  for (const point of points) {
    const threshold = thresholdOf(point, scenario);
    let scenarioValue: number | null = null;
    if (point.observed !== null) {
      recorded += point.observed;
      const reduced =
        cut > 0 && inHours(hourOf(point.timestamp), scenario.fromHour, scenario.toHour)
          ? point.observed * cut
          : 0;
      if (reduced > 0) {
        reduction += reduced;
        reductionHours += 1;
      }
      scenarioValue = point.observed - reduced;
      if (point.expected !== null) {
        comparableHours += 1;
        recordedComparable += point.observed;
        expectedComparable += point.expected;
      }
      if (threshold === null) {
        hoursWithoutThreshold += 1;
      } else {
        const over = Math.max(0, point.observed - threshold);
        if (over > 0) excessHours += 1;
        excess += over;
        excessAfter += Math.max(0, scenarioValue - threshold);
      }
    }
    out.push({
      timestamp: point.timestamp,
      observed: point.observed,
      expected: point.expected,
      threshold,
      scenario: scenarioValue,
    });
  }

  const priced = unit === 'kWh' && validTariff(scenario);
  const cost = (amount: number) =>
    priced && scenario.price !== null ? amount * scenario.price : null;
  return {
    hours: points.length,
    recorded,
    comparableHours,
    recordedComparable,
    expectedComparable,
    excess,
    excessHours,
    excessAfter,
    hoursWithoutThreshold,
    reduction,
    reductionHours,
    scenarioTotal: recorded - reduction,
    excessCost: cost(excess),
    excessAfterCost: cost(excessAfter),
    reductionCost: cost(reduction),
    points: out,
  };
}
