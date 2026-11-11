/**
 * The bill analyser's arithmetic (T062, D073). Everything comes from figures typed in from one
 * monthly electricity bill; nothing is sent or saved.
 *
 * - Rates are derived only from the bill's own figures. No tariff rule is assumed (a minimum
 *   billing demand, a power-factor threshold or a time-of-day percentage differ by utility).
 * - A bill comes from one meter for the whole site, so nothing here says which machine uses what.
 * - Savings are hypothetical; month-to-month changes are questions to ask, not anomalies.
 */

export type ChargeKind =
  | 'energy'
  | 'demand'
  | 'todSurcharge'
  | 'todRebate'
  | 'powerFactor'
  | 'fuel'
  | 'duty'
  | 'latePayment'
  | 'other';

export const CHARGE_KINDS: readonly ChargeKind[] = [
  'energy',
  'demand',
  'todSurcharge',
  'todRebate',
  'powerFactor',
  'fuel',
  'duty',
  'latePayment',
  'other',
];

export const CHARGE_LABELS: Record<ChargeKind, string> = {
  energy: 'Energy charges',
  demand: 'Fixed or demand charges',
  todSurcharge: 'Time-of-day surcharge',
  todRebate: 'Time-of-day rebate',
  powerFactor: 'Power-factor surcharge or rebate',
  fuel: 'Fuel and other surcharges',
  duty: 'Electricity duty, taxes and cess',
  latePayment: 'Late-payment surcharge',
  other: 'Other (arrears, adjustments)',
};

/** Charges for the billing period itself; late payment and arrears are not part of it. */
const PERIOD_KINDS: ReadonlySet<ChargeKind> = new Set(
  CHARGE_KINDS.filter((kind) => kind !== 'latePayment' && kind !== 'other'),
);

/** Amounts on a bill are rounded, usually to the nearest whole unit of currency. */
export const MONEY_TOLERANCE = 1;
/** A printed power factor has two or three decimals. */
export const POWER_FACTOR_TOLERANCE = 0.005;

export interface TodWindow {
  label: string;
  kwh: number | null;
  /** The surcharge (+) or rebate (−) as a percentage of the energy rate, as the bill applies it. */
  percent: number | null;
}

export interface HistoryMonth {
  /** `YYYY-MM`. */
  month: string;
  kwh: number | null;
}

export interface Bill {
  currency: string;
  periodDays: number | null;
  kwh: number | null;
  kvah: number | null;
  contractDemandKva: number | null;
  recordedDemandKva: number | null;
  billingDemandKva: number | null;
  /** Per kWh, as printed. */
  energyRate: number | null;
  statedPowerFactor: number | null;
  /** As printed: rebates and credits are negative. */
  charges: Record<ChargeKind, number | null>;
  totalPayable: number | null;
  tod: TodWindow[];
  history: HistoryMonth[];
}

export function emptyCharges(): Record<ChargeKind, number | null> {
  return Object.fromEntries(CHARGE_KINDS.map((kind) => [kind, null])) as Record<
    ChargeKind,
    number | null
  >;
}

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

export function validCurrency(code: string): boolean {
  return /^[A-Z]{3}$/.test(code);
}

/** Entries that cannot be right, each with the field it concerns. Results skip such fields. */
export function problems(bill: Bill): string[] {
  const found: string[] = [];
  const nonNegative: [string, number | null][] = [
    ['Billing period', bill.periodDays],
    ['Energy (kWh)', bill.kwh],
    ['Apparent energy (kVAh)', bill.kvah],
    ['Contract demand', bill.contractDemandKva],
    ['Recorded maximum demand', bill.recordedDemandKva],
    ['Billing demand', bill.billingDemandKva],
    ['Energy rate', bill.energyRate],
  ];
  for (const [name, value] of nonNegative) {
    if (value !== null && value < 0) found.push(`${name} cannot be negative.`);
  }
  if (!validCurrency(bill.currency)) {
    found.push('Currency must be a three-letter code, such as INR.');
  }
  if (
    bill.statedPowerFactor !== null &&
    !(bill.statedPowerFactor > 0 && bill.statedPowerFactor <= 1)
  ) {
    found.push('Power factor must be above 0 and at most 1.');
  }
  if (bill.kwh !== null && bill.kvah !== null && bill.kvah > 0 && bill.kwh > bill.kvah) {
    found.push(
      'Energy (kWh) cannot exceed apparent energy (kVAh): the power factor would be above 1.',
    );
  }
  const rebate = bill.charges.todRebate;
  if (rebate !== null && rebate > 0) {
    found.push('A time-of-day rebate reduces the bill: enter it as a negative amount, as printed.');
  }
  const surcharge = bill.charges.todSurcharge;
  if (surcharge !== null && surcharge < 0) {
    found.push('A time-of-day surcharge adds to the bill: enter it as a positive amount.');
  }
  for (const window of bill.tod) {
    const name = window.label || 'A time-of-day window';
    if (window.kwh !== null && window.kwh < 0)
      found.push(`${name}: consumption cannot be negative.`);
    if (window.percent !== null && (window.percent < -100 || window.percent > 100)) {
      found.push(`${name}: the percentage must be between −100 and 100.`);
    }
  }
  const windowKwh = sum(bill.tod.map((w) => (w.kwh !== null && w.kwh >= 0 ? w.kwh : null)));
  if (bill.kwh !== null && windowKwh !== null && windowKwh > bill.kwh + 1e-9) {
    found.push('The time-of-day windows add up to more than the energy (kWh) billed.');
  }
  const months = new Set<string>();
  for (const entry of bill.history) {
    if (entry.month === '' && entry.kwh === null) continue;
    if (!MONTH.test(entry.month)) {
      found.push(`History: "${entry.month}" is not a month written as YYYY-MM.`);
    } else if (months.has(entry.month)) {
      found.push(`History: ${entry.month} is entered twice.`);
    }
    months.add(entry.month);
    if (entry.kwh !== null && entry.kwh < 0) {
      found.push(`History: ${entry.month || 'a month'} cannot have negative consumption.`);
    }
  }
  return found;
}

function sum(values: readonly (number | null)[]): number | null {
  const present = values.filter((v): v is number => v !== null);
  return present.length ? present.reduce((a, b) => a + b, 0) : null;
}

function positive(value: number | null): value is number {
  return value !== null && value > 0;
}

// ---------------------------------------------------------------------------------------------
// Checks against the bill's own figures
// ---------------------------------------------------------------------------------------------

export interface AmountCheck {
  expected: number;
  entered: number;
  difference: number;
  ok: boolean;
}

function check(expected: number, entered: number): AmountCheck {
  const difference = entered - expected;
  return { expected, entered, difference, ok: Math.abs(difference) <= MONEY_TOLERANCE };
}

/** The charge lines entered against the total payable printed on the bill. */
export function totalCheck(bill: Bill): AmountCheck | null {
  const lines = sum(CHARGE_KINDS.map((kind) => bill.charges[kind]));
  if (lines === null || bill.totalPayable === null) return null;
  return check(lines, bill.totalPayable);
}

/** Energy charges against kWh × the printed energy rate. A slab tariff legitimately differs. */
export function energyCheck(bill: Bill): AmountCheck | null {
  const { kwh, energyRate } = bill;
  const entered = bill.charges.energy;
  if (kwh === null || energyRate === null || entered === null || kwh < 0 || energyRate < 0) {
    return null;
  }
  return check(kwh * energyRate, entered);
}

export interface PowerFactor {
  /** kWh ÷ kVAh, when both are entered. */
  computed: number | null;
  stated: number | null;
  consistent: boolean | null;
}

export function powerFactor(bill: Bill): PowerFactor {
  const { kwh, kvah } = bill;
  const computed = kwh !== null && positive(kvah) && kwh >= 0 && kwh <= kvah ? kwh / kvah : null;
  const stated =
    bill.statedPowerFactor !== null && bill.statedPowerFactor > 0 && bill.statedPowerFactor <= 1
      ? bill.statedPowerFactor
      : null;
  const consistent =
    computed !== null && stated !== null
      ? Math.abs(computed - stated) <= POWER_FACTOR_TOLERANCE
      : null;
  return { computed, stated, consistent };
}

// ---------------------------------------------------------------------------------------------
// Where the money goes
// ---------------------------------------------------------------------------------------------

export interface BreakdownLine {
  kind: ChargeKind;
  amount: number;
  /** Share of all the lines entered (rebates give negative shares). */
  share: number | null;
  perKwh: number | null;
}

export interface Breakdown {
  lines: BreakdownLine[];
  linesTotal: number;
  /** Charges for the period: every line except late payment and arrears or adjustments. */
  periodCharges: number;
  periodPerKwh: number | null;
  /** How many times the printed energy rate the period's charges come to, per kWh. */
  energyRateMultiple: number | null;
}

export function breakdown(bill: Bill): Breakdown | null {
  const entered = CHARGE_KINDS.flatMap((kind) => {
    const amount = bill.charges[kind];
    return amount === null ? [] : [{ kind, amount }];
  });
  if (!entered.length) return null;
  const linesTotal = entered.reduce((a, line) => a + line.amount, 0);
  const periodCharges = entered
    .filter((line) => PERIOD_KINDS.has(line.kind))
    .reduce((a, line) => a + line.amount, 0);
  const kwh = positive(bill.kwh) ? bill.kwh : null;
  const periodPerKwh = kwh === null ? null : periodCharges / kwh;
  return {
    lines: entered.map(({ kind, amount }) => ({
      kind,
      amount,
      share: linesTotal > 0 ? amount / linesTotal : null,
      perKwh: kwh === null ? null : amount / kwh,
    })),
    linesTotal,
    periodCharges,
    periodPerKwh,
    energyRateMultiple:
      periodPerKwh !== null && positive(bill.energyRate) ? periodPerKwh / bill.energyRate : null,
  };
}

// ---------------------------------------------------------------------------------------------
// Demand and utilisation
// ---------------------------------------------------------------------------------------------

export interface Demand {
  /** Fixed or demand charges ÷ billing demand: the bill's own rate per kVA for the period. */
  ratePerKva: number | null;
  /** Billing demand minus the recorded maximum demand (negative if billed below it). */
  billedAboveRecordedKva: number | null;
  billedAboveRecordedCost: number | null;
  recordedShareOfContract: number | null;
  billingShareOfContract: number | null;
}

export function demand(bill: Bill): Demand {
  const { billingDemandKva: billing, recordedDemandKva: recorded } = bill;
  const contract = bill.contractDemandKva;
  const charge = bill.charges.demand;
  const ratePerKva = positive(billing) && charge !== null && charge >= 0 ? charge / billing : null;
  const gap =
    billing !== null && recorded !== null && billing >= 0 && recorded >= 0
      ? billing - recorded
      : null;
  return {
    ratePerKva,
    billedAboveRecordedKva: gap,
    billedAboveRecordedCost:
      gap !== null && gap > 0 && ratePerKva !== null ? gap * ratePerKva : null,
    recordedShareOfContract:
      positive(contract) && recorded !== null && recorded >= 0 ? recorded / contract : null,
    billingShareOfContract:
      positive(contract) && billing !== null && billing >= 0 ? billing / contract : null,
  };
}

export interface Utilisation {
  hours: number | null;
  averageKw: number | null;
  averageKva: number | null;
  /** kWh ÷ (contract demand × hours): one common definition of load factor. */
  contractUtilisation: number | null;
  /** Recorded maximum demand ÷ average kVA (needs kVAh). */
  peakToAverage: number | null;
}

export function utilisation(bill: Bill): Utilisation {
  const hours = positive(bill.periodDays) ? bill.periodDays * 24 : null;
  const averageKw = hours !== null && bill.kwh !== null && bill.kwh >= 0 ? bill.kwh / hours : null;
  const averageKva =
    hours !== null && bill.kvah !== null && bill.kvah >= 0 ? bill.kvah / hours : null;
  return {
    hours,
    averageKw,
    averageKva,
    contractUtilisation:
      hours !== null && bill.kwh !== null && bill.kwh >= 0 && positive(bill.contractDemandKva)
        ? bill.kwh / (bill.contractDemandKva * hours)
        : null,
    peakToAverage:
      positive(averageKva) && bill.recordedDemandKva !== null && bill.recordedDemandKva >= 0
        ? bill.recordedDemandKva / averageKva
        : null,
  };
}

// ---------------------------------------------------------------------------------------------
// Time of day
// ---------------------------------------------------------------------------------------------

export interface TodRow {
  label: string;
  kwh: number;
  share: number | null;
  percent: number | null;
  /** kWh × energy rate × percent: the surcharge (+) or rebate (−) the window implies. */
  implied: number | null;
}

export interface TimeOfDay {
  rows: TodRow[];
  /** Consumption outside the entered windows, at no surcharge or rebate. */
  otherHoursKwh: number | null;
  surchargeCheck: AmountCheck | null;
  rebateCheck: AmountCheck | null;
}

function usableWindows(bill: Bill): TodWindow[] {
  return bill.tod.filter((w) => w.kwh !== null && w.kwh >= 0);
}

export function timeOfDay(bill: Bill): TimeOfDay | null {
  const windows = usableWindows(bill);
  if (!windows.length) return null;
  const rate = bill.energyRate !== null && bill.energyRate >= 0 ? bill.energyRate : null;
  const total = bill.kwh !== null && bill.kwh >= 0 ? bill.kwh : null;
  const rows = windows.map((w, index): TodRow => {
    const kwh = w.kwh ?? 0;
    const percent = w.percent !== null && Math.abs(w.percent) <= 100 ? w.percent : null;
    return {
      label: w.label || `Window ${String(index + 1)}`,
      kwh,
      share: positive(total) ? kwh / total : null,
      percent,
      implied: rate !== null && percent !== null ? (kwh * rate * percent) / 100 : null,
    };
  });
  const windowKwh = rows.reduce((a, r) => a + r.kwh, 0);
  const otherHoursKwh = total !== null && windowKwh <= total + 1e-9 ? total - windowKwh : null;
  const priced = rows.every((r) => r.implied !== null);
  const implied = (keep: (value: number) => boolean) =>
    rows.reduce((a, r) => (r.implied !== null && keep(r.implied) ? a + r.implied : a), 0);
  const surcharge = bill.charges.todSurcharge;
  const rebate = bill.charges.todRebate;
  return {
    rows,
    otherHoursKwh,
    surchargeCheck:
      priced && surcharge !== null
        ? check(
            implied((v) => v > 0),
            surcharge,
          )
        : null,
    rebateCheck:
      priced && rebate !== null
        ? check(
            implied((v) => v < 0),
            rebate,
          )
        : null,
  };
}

export interface Shift {
  /** Index of a window, or 'other' for the hours outside every window (0 %). */
  from: number | 'other';
  to: number | 'other';
  kwh: number;
}

export interface ShiftResult {
  /** Change in charges per kWh moved: positive is a saving. */
  savingPerKwh: number;
  /** The kWh actually counted: at most what the source window recorded. */
  kwhMoved: number;
  capped: boolean;
  saving: number;
}

/**
 * Hypothetical: moving `kwh` from one window to another at the bill's own rate and percentages.
 * It assumes the load can move, and says nothing about demand peaks or production.
 */
export function shiftSaving(bill: Bill, shift: Shift): ShiftResult | null {
  const tod = timeOfDay(bill);
  if (tod === null || bill.energyRate === null || bill.energyRate < 0) return null;
  if (!(shift.kwh >= 0) || shift.from === shift.to) return null;
  const source = (side: number | 'other') =>
    side === 'other'
      ? { kwh: tod.otherHoursKwh, percent: 0 }
      : { kwh: tod.rows[side]?.kwh ?? null, percent: tod.rows[side]?.percent ?? null };
  const from = source(shift.from);
  const to = source(shift.to);
  if (from.kwh === null || from.percent === null || to.percent === null) return null;
  const savingPerKwh = (bill.energyRate * (from.percent - to.percent)) / 100;
  const kwhMoved = Math.min(shift.kwh, from.kwh);
  return {
    savingPerKwh,
    kwhMoved,
    capped: kwhMoved < shift.kwh,
    saving: kwhMoved * savingPerKwh,
  };
}

// ---------------------------------------------------------------------------------------------
// The last months' consumption
// ---------------------------------------------------------------------------------------------

export interface MonthChange {
  from: string;
  to: string;
  /** (later − earlier) ÷ earlier. */
  change: number;
}

export interface History {
  /** Oldest first, valid entries only. */
  months: { month: string; kwh: number }[];
  zeroMonths: string[];
  largestRise: MonthChange | null;
  largestDrop: MonthChange | null;
  /** Median of the months with consumption. */
  median: number | null;
  /** This bill's kWh against that median, as a ratio. */
  billAgainstMedian: number | null;
}

function median(values: readonly number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? (sorted[middle] ?? null)
    : ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2;
}

export function history(bill: Bill): History | null {
  const seen = new Set<string>();
  const months = bill.history
    .filter((entry): entry is { month: string; kwh: number } => {
      const ok =
        MONTH.test(entry.month) && entry.kwh !== null && entry.kwh >= 0 && !seen.has(entry.month);
      if (ok) seen.add(entry.month);
      return ok;
    })
    .sort((a, b) => a.month.localeCompare(b.month));
  if (!months.length) return null;
  let largestRise: MonthChange | null = null;
  let largestDrop: MonthChange | null = null;
  for (let i = 1; i < months.length; i += 1) {
    const earlier = months[i - 1];
    const later = months[i];
    if (!earlier || !later || earlier.kwh === 0 || later.kwh === 0) continue;
    const change = (later.kwh - earlier.kwh) / earlier.kwh;
    const step = { from: earlier.month, to: later.month, change };
    if (change > 0 && (largestRise === null || change > largestRise.change)) largestRise = step;
    if (change < 0 && (largestDrop === null || change < largestDrop.change)) largestDrop = step;
  }
  const typical = median(months.filter((m) => m.kwh > 0).map((m) => m.kwh));
  return {
    months,
    zeroMonths: months.filter((m) => m.kwh === 0).map((m) => m.month),
    largestRise,
    largestDrop,
    median: typical,
    billAgainstMedian:
      typical !== null && typical > 0 && bill.kwh !== null && bill.kwh >= 0
        ? bill.kwh / typical
        : null,
  };
}
