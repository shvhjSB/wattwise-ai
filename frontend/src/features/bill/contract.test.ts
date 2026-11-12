import { describe, expect, it } from 'vitest';

import { cheapestContract, compareYear, type DemandRule, monthCharge, validRule } from './contract';

/** Synthetic: a year of recorded maximum demand, and rules typed in by a user. */
const MONTHS = [210, 230, 250, 290, 310, 260, 240, 220, 200, 215, 225, 235].map((kva, i) => ({
  month: `2026-${String(i + 1).padStart(2, '0')}`,
  demandKva: kva,
}));
const RULE: DemandRule = { minimumShare: 0.75, excessMultiplier: 1.5, ratePerKva: 350 };

describe('one month', () => {
  it('bills at least the minimum share of the contract', () => {
    expect(monthCharge(210, 400, RULE)).toEqual({ billedKva: 300, excessKva: 0, charge: 105_000 });
    expect(monthCharge(310, 400, RULE)).toEqual({ billedKva: 310, excessKva: 0, charge: 108_500 });
  });

  it('charges demand above the contract at the excess multiple', () => {
    // 280 at 350, and 30 above at 1.5 times 350.
    expect(monthCharge(310, 280, RULE)).toEqual({
      billedKva: 280,
      excessKva: 30,
      charge: 280 * 350 + 30 * 525,
    });
  });
});

describe('a year', () => {
  it('compares the current and a proposed contract month by month', () => {
    const result = compareYear(MONTHS, 400, 320, RULE);

    expect(result.currentTotal).toBe(1_263_500);
    expect(result.proposedTotal).toBe(1_060_500);
    expect(result.saving).toBe(203_000);
    expect(result.monthsOverProposed).toEqual([]);
    expect(result.highestKva).toBe(310);
  });

  it('names the months a lower contract would have exceeded', () => {
    const result = compareYear(MONTHS, 400, 280, RULE);

    expect(result.proposedTotal).toBe(1_020_250);
    expect(result.monthsOverProposed).toEqual(['2026-04', '2026-05']); // 290 and 310 kVA
    expect(result.rows[4]?.proposed.excessKva).toBe(30);
  });

  it('finds the contract that would have cost least under these rules', () => {
    expect(cheapestContract(MONTHS, RULE, 400)).toEqual({ contractKva: 280, total: 1_020_250 });
    expect(cheapestContract([], RULE, 400)).toBeNull();
  });

  it('can only be worked out with complete, sensible rules', () => {
    expect(validRule(RULE)).toBe(true);
    expect(validRule({ ...RULE, minimumShare: 1.2 })).toBe(false);
    expect(validRule({ ...RULE, excessMultiplier: 0.5 })).toBe(false);
    expect(validRule({ ...RULE, ratePerKva: 0 })).toBe(false);
    expect(validRule({ ...RULE, ratePerKva: Number.NaN })).toBe(false);
  });
});
