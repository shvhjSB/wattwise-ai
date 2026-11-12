import { describe, expect, it } from 'vitest';

import {
  type Bill,
  breakdown,
  demand,
  emptyCharges,
  energyCheck,
  history,
  powerFactor,
  problems,
  shiftSaving,
  timeOfDay,
  totalCheck,
  utilisation,
} from './bill';
import { SYNTHETIC_BILL } from './example';

/** The synthetic example with some fields changed (never a real customer's bill). */
function bill(changes: Partial<Bill> = {}): Bill {
  return { ...structuredClone(SYNTHETIC_BILL), ...changes };
}

function blank(): Bill {
  return {
    currency: 'INR',
    periodDays: null,
    kwh: null,
    kvah: null,
    contractDemandKva: null,
    recordedDemandKva: null,
    billingDemandKva: null,
    energyRate: null,
    statedPowerFactor: null,
    charges: emptyCharges(),
    totalPayable: null,
    tod: [],
    history: [],
  };
}

describe('the synthetic example', () => {
  it('is consistent, so every check passes on it', () => {
    expect(problems(SYNTHETIC_BILL)).toEqual([]);
    expect(totalCheck(SYNTHETIC_BILL)).toMatchObject({ expected: 507_280, ok: true });
    expect(energyCheck(SYNTHETIC_BILL)).toMatchObject({ expected: 336_000, ok: true });
    const tod = timeOfDay(SYNTHETIC_BILL);
    expect(tod?.surchargeCheck).toMatchObject({ expected: 8_400, ok: true });
    expect(tod?.rebateCheck).toMatchObject({ expected: -6_300, ok: true });
    expect(powerFactor(SYNTHETIC_BILL).consistent).toBe(true);
  });
});

describe('checks against the bill', () => {
  it('flags lines that do not add up to the total payable', () => {
    const typo = bill({ charges: { ...SYNTHETIC_BILL.charges, fuel: 3_600 } });

    expect(totalCheck(typo)).toEqual({
      expected: 474_880,
      entered: 507_280,
      difference: 32_400,
      ok: false,
    });
  });

  it('allows the rounding of a printed total', () => {
    expect(totalCheck(bill({ totalPayable: 507_280.6 }))?.ok).toBe(true);
    expect(totalCheck(bill({ totalPayable: 507_281.5 }))?.ok).toBe(false);
  });

  it('needs a total and at least one line', () => {
    expect(totalCheck(bill({ totalPayable: null }))).toBeNull();
    expect(totalCheck({ ...blank(), totalPayable: 100 })).toBeNull();
  });

  it('compares energy charges with kWh times the printed rate', () => {
    const slab = bill({ charges: { ...SYNTHETIC_BILL.charges, energy: 330_000 } });

    expect(energyCheck(slab)).toMatchObject({ expected: 336_000, difference: -6_000, ok: false });
    expect(energyCheck(bill({ energyRate: null }))).toBeNull();
  });

  it('computes the power factor from kWh and kVAh and compares it with the printed one', () => {
    const pf = powerFactor(SYNTHETIC_BILL);
    expect(pf.computed).toBeCloseTo(48_000 / 51_000, 10);
    expect(pf.stated).toBe(0.94);
    expect(powerFactor(bill({ statedPowerFactor: 0.9 })).consistent).toBe(false);
    expect(powerFactor(bill({ kvah: null })).computed).toBeNull();
  });
});

describe('where the money goes', () => {
  it('shares every line of the total and separates late payment from the period', () => {
    const result = breakdown(SYNTHETIC_BILL);

    expect(result?.linesTotal).toBe(507_280);
    expect(result?.periodCharges).toBe(504_780); // without the late-payment surcharge
    expect(result?.periodPerKwh).toBeCloseTo(504_780 / 48_000, 10);
    expect(result?.energyRateMultiple).toBeCloseTo(504_780 / 48_000 / 7, 10);
    const demandLine = result?.lines.find((line) => line.kind === 'demand');
    expect(demandLine?.share).toBeCloseTo(105_000 / 507_280, 10);
    const rebate = result?.lines.find((line) => line.kind === 'todRebate');
    expect(rebate?.share).toBeLessThan(0);
    expect(result?.lines.some((line) => line.kind === 'other')).toBe(false); // not entered
  });

  it('is absent without any line, and has no per-kWh figures without kWh', () => {
    expect(breakdown(blank())).toBeNull();
    expect(breakdown(bill({ kwh: null }))?.periodPerKwh).toBeNull();
  });
});

describe('demand', () => {
  it('derives the rate per kVA from the bill and prices billed demand above the recorded peak', () => {
    expect(demand(SYNTHETIC_BILL)).toEqual({
      ratePerKva: 350,
      billedAboveRecordedKva: 90,
      billedAboveRecordedCost: 31_500,
      recordedShareOfContract: 210 / 400,
      billingShareOfContract: 0.75,
    });
  });

  it('prices nothing when the billing demand is at or below the recorded peak', () => {
    const result = demand(bill({ recordedDemandKva: 320 }));

    expect(result.billedAboveRecordedKva).toBe(-20);
    expect(result.billedAboveRecordedCost).toBeNull();
  });

  it('needs a billing demand for a rate', () => {
    expect(demand(bill({ billingDemandKva: null })).ratePerKva).toBeNull();
    expect(demand(bill({ billingDemandKva: 0 })).ratePerKva).toBeNull();
  });
});

describe('utilisation', () => {
  it('compares the period’s average load with the contract and the recorded peak', () => {
    const result = utilisation(SYNTHETIC_BILL);

    expect(result.hours).toBe(720);
    expect(result.averageKw).toBeCloseTo(48_000 / 720, 10);
    expect(result.averageKva).toBeCloseTo(51_000 / 720, 10);
    expect(result.contractUtilisation).toBeCloseTo(48_000 / (400 * 720), 10);
    expect(result.peakToAverage).toBeCloseTo(210 / (51_000 / 720), 10);
  });

  it('needs the billing period', () => {
    expect(utilisation(bill({ periodDays: null }))).toEqual({
      hours: null,
      averageKw: null,
      averageKva: null,
      contractUtilisation: null,
      peakToAverage: null,
    });
  });
});

describe('time of day', () => {
  it('gives each window its share and implied surcharge or rebate, and the other hours', () => {
    const tod = timeOfDay(SYNTHETIC_BILL);

    expect(tod?.rows.map((r) => r.implied)).toEqual([2_100, 6_300, -6_300]);
    expect(tod?.rows[1]?.share).toBeCloseTo(9_000 / 48_000, 10);
    expect(tod?.otherHoursKwh).toBe(21_000);
  });

  it('flags printed time-of-day lines that the windows do not explain', () => {
    const off = bill({ charges: { ...SYNTHETIC_BILL.charges, todSurcharge: 9_000 } });

    expect(timeOfDay(off)?.surchargeCheck).toMatchObject({ difference: 600, ok: false });
  });

  it('prices moving consumption between windows at the bill’s own rate', () => {
    expect(shiftSaving(SYNTHETIC_BILL, { from: 1, to: 2, kwh: 2_000 })).toEqual({
      savingPerKwh: 1.225, // 7 × (10 % + 7.5 %)
      kwhMoved: 2_000,
      capped: false,
      saving: 2_450,
    });
    expect(shiftSaving(SYNTHETIC_BILL, { from: 1, to: 'other', kwh: 1_000 })?.saving).toBe(700);
    expect(shiftSaving(SYNTHETIC_BILL, { from: 2, to: 1, kwh: 1_000 })?.saving).toBe(-1_225);
  });

  it('never moves more than the source window recorded', () => {
    expect(shiftSaving(SYNTHETIC_BILL, { from: 1, to: 2, kwh: 10_000 })).toMatchObject({
      kwhMoved: 9_000,
      capped: true,
      saving: 9_000 * 1.225,
    });
  });

  it('has nothing to move without windows, a rate, or two different windows', () => {
    expect(timeOfDay(bill({ tod: [] }))).toBeNull();
    expect(shiftSaving(bill({ energyRate: null }), { from: 1, to: 2, kwh: 100 })).toBeNull();
    expect(shiftSaving(SYNTHETIC_BILL, { from: 1, to: 1, kwh: 100 })).toBeNull();
  });
});

describe('history', () => {
  it('sorts months, lists zero months and finds the largest changes between months with use', () => {
    const shuffled = bill({ history: [...SYNTHETIC_BILL.history].reverse() });
    const result = history(shuffled);

    expect(result?.months[0]?.month).toBe('2025-10');
    expect(result?.zeroMonths).toEqual(['2025-12']);
    expect(result?.largestDrop?.from).toBe('2026-05');
    expect(result?.largestDrop?.change).toBeCloseTo((29_400 - 49_800) / 49_800, 10);
    expect(result?.largestRise?.to).toBe('2026-07');
    expect(result?.largestRise?.change).toBeCloseTo((47_600 - 29_400) / 29_400, 10);
    expect(result?.median).toBe(47_100); // of the 11 months with use
    expect(result?.billAgainstMedian).toBeCloseTo(48_000 / 47_100, 10);
  });

  it('skips changes to or from a zero month and ignores invalid or repeated months', () => {
    const result = history(
      bill({
        history: [
          { month: '2026-01', kwh: 100 },
          { month: '2026-02', kwh: 0 },
          { month: '2026-03', kwh: 300 },
          { month: '2026-03', kwh: 999 },
          { month: 'March', kwh: 50 },
        ],
      }),
    );

    expect(result?.months.map((m) => m.month)).toEqual(['2026-01', '2026-02', '2026-03']);
    expect(result?.largestRise).toBeNull();
    expect(result?.largestDrop).toBeNull();
  });
});

describe('problems', () => {
  it('names entries that cannot be right', () => {
    const found = problems(
      bill({
        currency: 'rupees',
        kwh: 60_000, // above kVAh
        statedPowerFactor: 1.2,
        charges: { ...SYNTHETIC_BILL.charges, todRebate: 6_300 },
        tod: [{ label: 'Peak', kwh: 70_000, percent: 150 }],
        history: [
          { month: '2026-13', kwh: 10 },
          { month: '2026-01', kwh: -5 },
          { month: '2026-01', kwh: 5 },
          { month: '2026-02', kwh: 5, demandKva: -1 },
        ],
      }),
    );

    expect(found).toEqual([
      'Currency must be a three-letter code, such as INR.',
      'Power factor must be above 0 and at most 1.',
      'Energy (kWh) cannot exceed apparent energy (kVAh): the power factor would be above 1.',
      'A time-of-day rebate reduces the bill: enter it as a negative amount, as printed.',
      'Peak: the percentage must be between −100 and 100.',
      'The time-of-day windows add up to more than the energy (kWh) billed.',
      'History: "2026-13" is not a month written as YYYY-MM.',
      'History: 2026-01 cannot have negative consumption.',
      'History: 2026-01 is entered twice.',
      'History: 2026-02 cannot have a negative highest demand.',
    ]);
  });

  it('has nothing to say about an empty form', () => {
    expect(problems(blank())).toEqual([]);
  });
});
