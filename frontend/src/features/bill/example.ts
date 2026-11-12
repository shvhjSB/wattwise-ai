import type { Bill } from './bill';

/**
 * A **synthetic** bill for trying the analyser: made-up figures, not any real customer's bill.
 * They are constructed to be consistent (kWh × rate = energy charges, the window percentages give
 * the time-of-day lines, the lines add up to the total), so every check passes on it.
 */
export const SYNTHETIC_BILL: Bill = {
  currency: 'INR',
  periodDays: 30,
  kwh: 48_000,
  kvah: 51_000,
  contractDemandKva: 400,
  recordedDemandKva: 210,
  billingDemandKva: 300,
  energyRate: 7,
  statedPowerFactor: 0.94,
  charges: {
    energy: 336_000,
    demand: 105_000,
    todSurcharge: 8_400,
    todRebate: -6_300,
    powerFactor: 1_680,
    fuel: 36_000,
    duty: 24_000,
    latePayment: 2_500,
    other: null,
  },
  totalPayable: 507_280,
  tod: [
    { label: '06:00–09:00', kwh: 6_000, percent: 5 },
    { label: '18:00–22:00', kwh: 9_000, percent: 10 },
    { label: '22:00–06:00', kwh: 12_000, percent: -7.5 },
  ],
  history: [
    { month: '2025-10', kwh: 46_200, demandKva: 210 },
    { month: '2025-11', kwh: 47_100, demandKva: 230 },
    { month: '2025-12', kwh: 0, demandKva: 0 },
    { month: '2026-01', kwh: 44_800, demandKva: 250 },
    { month: '2026-02', kwh: 45_900, demandKva: 290 },
    { month: '2026-03', kwh: 47_300, demandKva: 310 },
    { month: '2026-04', kwh: 46_500, demandKva: 260 },
    { month: '2026-05', kwh: 49_800, demandKva: 240 },
    { month: '2026-06', kwh: 29_400, demandKva: 220 },
    { month: '2026-07', kwh: 47_600, demandKva: 200 },
    { month: '2026-08', kwh: 48_900, demandKva: 215 },
    { month: '2026-09', kwh: 47_700, demandKva: 225 },
  ],
};
