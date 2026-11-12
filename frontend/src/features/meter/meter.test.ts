import { describe, expect, it } from 'vitest';

import {
  check,
  type Check,
  intervalMinutes,
  localParts,
  parseCsv,
  parseTime,
  readRows,
  syntheticMeterCsv,
  zonedToUtc,
} from './meter';

const IST = 'Asia/Kolkata';
const MON_SAT_8_20 = { days: [0, 1, 2, 3, 4, 5], from: 8, to: 20 };

describe('reading a CSV', () => {
  it('finds the delimiter and keeps quoted fields together', () => {
    expect(parseCsv('a,b\n1,2\n').rows).toEqual([['1', '2']]);
    const semi = parseCsv('Zeit;Wert\n"2018-01-01 00:00";"12,5"\n\n');
    expect(semi.delimiter).toBe(';');
    expect(semi.rows).toEqual([['2018-01-01 00:00', '12,5']]);
    expect(parseCsv('﻿t\tv\nx\ty\n').header).toEqual(['t', 'v']);
  });

  it('reports unreadable lines with their line numbers, and reads decimal commas', () => {
    const table = parseCsv('time;kWh\n2018-01-01 00:00;1,5\nnot a time;2\n2018-01-01 00:30;x\n');
    const read = readRows(table, {
      timeColumn: 0,
      valueColumn: 1,
      order: 'ymd',
      timeZone: 'UTC',
      kind: 'kwh',
    });

    expect(read.readings).toEqual([{ t: Date.parse('2018-01-01T00:00:00Z'), value: 1.5 }]);
    expect(read.unreadable).toBe(2);
    expect(read.problems[0]).toMatch(/^Line 3: the time "not a time"/);
    expect(read.problems[1]).toMatch(/^Line 4: the value "x" is not a number/);
  });
});

describe('times', () => {
  it('reads a written offset as given, and local times in the chosen zone and order', () => {
    expect(parseTime('2018-01-01T00:00:00+05:30', 'dmy', 'UTC')).toBe(
      Date.parse('2017-12-31T18:30:00Z'),
    );
    const midnight = Date.parse('2017-12-31T18:30:00Z'); // 1 January 2018, 00:00 in India
    expect(parseTime('2018-01-01 00:00', 'ymd', IST)).toBe(midnight);
    expect(parseTime('01/01/2018 00:00', 'dmy', IST)).toBe(midnight);
    expect(parseTime('03/04/2018 10:00', 'dmy', 'UTC')).toBe(Date.parse('2018-04-03T10:00:00Z'));
    expect(parseTime('03/04/2018 10:00', 'mdy', 'UTC')).toBe(Date.parse('2018-03-04T10:00:00Z'));
  });

  it('refuses impossible dates and times', () => {
    expect(parseTime('2018-04-31 00:00', 'ymd', 'UTC')).toBeNull();
    expect(parseTime('2018-13-01 00:00', 'ymd', 'UTC')).toBeNull();
    expect(parseTime('2018-01-01 24:00', 'ymd', 'UTC')).toBeNull();
    expect(parseTime('yesterday', 'ymd', 'UTC')).toBeNull();
  });

  it('handles the clock changes: a skipped hour does not exist, a repeated one is taken first', () => {
    // Berlin skipped 02:00-03:00 on 25 March 2018 and repeated 02:00-03:00 on 28 October 2018.
    expect(zonedToUtc(2018, 3, 25, 2, 30, 0, 'Europe/Berlin')).toBeNull();
    expect(zonedToUtc(2018, 10, 28, 2, 30, 0, 'Europe/Berlin')).toBe(
      Date.parse('2018-10-28T00:30:00Z'), // the first 02:30, still summer time
    );
    expect(zonedToUtc(2018, 7, 1, 12, 0, 0, 'Europe/Berlin')).toBe(
      Date.parse('2018-07-01T10:00:00Z'),
    );
    expect(localParts(Date.parse('2017-12-31T18:30:00Z'), IST).hour).toBe(0);
  });

  it('knows the supported reading intervals', () => {
    const t0 = Date.parse('2018-01-01T00:00:00Z');
    expect(intervalMinutes([t0, t0 + 900_000, t0 + 1_800_000])).toBe(15);
    expect(intervalMinutes([t0, t0 + 420_000, t0 + 840_000])).toBeNull(); // 7 minutes
  });
});

describe('the check, on the synthetic meter file', () => {
  function run(open = MON_SAT_8_20): Check {
    const table = parseCsv(syntheticMeterCsv());
    const read = readRows(table, {
      timeColumn: 0,
      valueColumn: 1,
      order: 'ymd',
      timeZone: IST,
      kind: 'kwh',
    });
    const result = check(read.readings, 'kwh', IST, open, [
      { label: 'Day shift', from: 8, to: 20 },
    ]);
    if (typeof result === 'string') throw new Error(result);
    return result;
  }

  it('reads every interval, with nothing missing', () => {
    const result = run();

    expect(result.minutes).toBe(15);
    expect(result.intervals).toHaveLength(28 * 96);
    expect([result.missing, result.duplicates, result.negatives]).toEqual([0, 0, 0]);
    expect(result.first).toBe(Date.parse('2017-12-31T18:30:00Z'));
  });

  it('adds up the energy and finds the peak demand', () => {
    const result = run();

    // 296 hours at 120 kW (288 working, 8 left on) and 376 hours at 40 kW.
    expect(result.totalKwh).toBeCloseTo(296 * 120 + 376 * 40, 6);
    expect(result.peak.kw).toBe(120);
    expect(result.nearPeak).toBe(296 * 4);
    expect(result.hourProfile[3]).toBeCloseTo((27 * 40 + 120) / 28, 6); // 03:00, one left-on
  });

  it('measures use while closed and the base load', () => {
    const result = run();

    expect(result.closedKwh).toBeCloseTo(376 * 40 + 8 * 120, 6);
    expect(result.closedShare).toBeCloseTo(16000 / 50560, 9);
    expect(result.baseLoadKw).toBe(40);
    expect(result.windows[0]?.kwh).toBeCloseTo(288 * 120 + 4 * 12 * 40, 6); // Sundays at 40
  });

  it('finds the Sunday the load was left on, in local hours', () => {
    const result = run();

    expect(result.events).toHaveLength(1);
    const [event] = result.events;
    expect(event?.direction).toBe('high');
    expect(event?.start).toBe(Date.parse('2018-01-20T18:30:00Z')); // 21 January, 00:00 in India
    expect(event?.duration_hours).toBe(8);
  });

  it('works from power readings, and reports gaps, duplicates and negative readings', () => {
    const t0 = Date.parse('2018-01-01T00:00:00Z');
    const q = 900_000;
    const readings = [
      { t: t0, value: 4 },
      { t: t0, value: 9 }, // a duplicate: the first is kept
      { t: t0 + q, value: 8 },
      { t: t0 + 2 * q, value: 8 },
      { t: t0 + 3 * q, value: 8 },
      { t: t0 + 8 * q, value: -2 }, // four intervals missing before it
    ];
    const result = check(readings, 'kw', 'UTC', MON_SAT_8_20, []);
    if (typeof result === 'string') throw new Error(result);

    expect(result.minutes).toBe(15);
    expect(result.duplicates).toBe(1);
    expect(result.missing).toBe(4);
    expect(result.longestGapHours).toBe(1);
    expect(result.negatives).toBe(1);
    expect(result.totalKwh).toBeCloseTo((4 + 8 + 8 + 8 - 2) * 0.25, 9); // kW for a quarter hour
    expect(check(readings.slice(0, 1), 'kw', 'UTC', MON_SAT_8_20, [])).toBe(
      'At least two readings are needed.',
    );
  });
});
