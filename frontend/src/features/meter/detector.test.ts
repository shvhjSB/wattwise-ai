import { describe, expect, it } from 'vitest';

import { DEFAULT_CONFIG, detectEvents, HOUR_MS, type HourRow, rollingSameHour } from './detector';
import parity from './detector-parity.json';

interface ParityEvent {
  direction: string;
  start: string;
  end: string;
  duration_hours: number;
  flagged_hours: number;
  missing_hours: number;
  peak_time: string;
  peak_z: number;
  peak_residual: number;
  residual_sum: number;
  ongoing: boolean;
}

const rows: HourRow[] = (parity.rows as [string, number | null][]).map(([t, value]) => ({
  t: Date.parse(t),
  value,
}));

describe('the detector port', () => {
  it('uses the same settings as the Python default', () => {
    const python = parity.config as Record<string, unknown>;
    for (const [key, value] of Object.entries(DEFAULT_CONFIG)) {
      expect(python[key], key).toBe(value);
    }
  });

  it('finds exactly the events the Python detector finds (detector-parity.json)', () => {
    const found = detectEvents(rows);
    const expected = parity.events as ParityEvent[];

    expect(found).toHaveLength(expected.length);
    found.forEach((event, i) => {
      const python = expected[i];
      expect(python).toBeDefined();
      if (!python) return;
      expect(event.direction).toBe(python.direction);
      expect(new Date(event.start).toISOString().replace('.000', '')).toBe(python.start);
      expect(new Date(event.end).toISOString().replace('.000', '')).toBe(python.end);
      expect(new Date(event.peak_time).toISOString().replace('.000', '')).toBe(python.peak_time);
      expect(event.duration_hours).toBe(python.duration_hours);
      expect(event.flagged_hours).toBe(python.flagged_hours);
      expect(event.missing_hours).toBe(python.missing_hours);
      expect(event.ongoing).toBe(python.ongoing);
      expect(event.peak_z).toBeCloseTo(python.peak_z, 3);
      expect(event.peak_residual).toBeCloseTo(python.peak_residual, 3);
      expect(event.residual_sum).toBeCloseTo(python.residual_sum, 3);
    });
  });

  it('needs a week of history and never scores an hour without a row', () => {
    const start = Date.parse('2017-01-02T00:00:00Z');
    const flat: HourRow[] = Array.from({ length: 24 * 8 }, (_, i) => ({
      t: start + i * HOUR_MS,
      value: 10,
    }));
    const scores = rollingSameHour(flat);

    expect(Number.isNaN(scores?.z[24 * 7 - 1] ?? 0)).toBe(true); // six days of history
    expect(scores?.z[24 * 7]).toBe(0); // seven days: scored
    expect(detectEvents([])).toEqual([]);
  });
});
