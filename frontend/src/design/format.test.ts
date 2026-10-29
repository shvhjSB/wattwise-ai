import { describe, expect, it } from 'vitest';

import { formatCount, formatDate, formatEnergy, formatShare } from './format';

describe('formatEnergy', () => {
  it.each([
    [0, '0', 'kWh'],
    [999.04, '999', 'kWh'],
    [1_000, '1', 'MWh'],
    [558_721.9, '558.7', 'MWh'],
    [2_872_660_506.2, '2,872.66', 'GWh'],
    [1_000_000, '1', 'GWh'],
  ])('%s kWh -> %s %s', (kwh, value, unit) => {
    expect(formatEnergy(kwh)).toEqual({ value, unit });
  });

  it('keeps the sign of a negative figure', () => {
    expect(formatEnergy(-2_500)).toEqual({ value: '-2.5', unit: 'MWh' });
  });
});

describe('formatShare', () => {
  it.each([
    [0.0011, '0.11%'],
    [0.059, '5.9%'],
    [0, '0%'],
    [1, '100%'],
  ])('%s -> %s', (share, text) => {
    expect(formatShare(share)).toBe(text);
  });
});

describe('formatCount and formatDate', () => {
  it('groups digits', () => {
    expect(formatCount(20_137_056)).toBe('20,137,056');
  });

  it('shows the UTC date of an ISO timestamp', () => {
    expect(formatDate('2016-01-04T00:00:00Z')).toBe('2016-01-04');
  });
});
