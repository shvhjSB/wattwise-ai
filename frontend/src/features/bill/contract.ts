/**
 * The contract-demand what-if (T068, D079): what a year of demand charges would have been with a
 * different contract demand, **under rules the user enters from their own tariff**. No rule is
 * assumed: minimum billing demands and excess-demand charges differ by utility.
 *
 * The rule, stated on the page as it is applied here, for a month with recorded maximum demand R
 * and contract demand C:
 *
 * - **R at or below C:** billed on max(R, minimum share × C) at the demand rate.
 * - **R above C:** billed on C at the demand rate, plus (R − C) at the excess multiplier times the
 *   demand rate.
 *
 * Results are hypothetical: last year's demand may not repeat, and changing a contract demand
 * follows the utility's own procedure and limits.
 */

export interface DemandRule {
  /** Minimum billing demand as a share of the contract demand, 0 to 1 (e.g. 0.75). */
  minimumShare: number;
  /** Demand above the contract is charged at this multiple of the demand rate (1 or more). */
  excessMultiplier: number;
  /** Demand rate per kVA per month (the bill's fixed charges divided by its billing demand). */
  ratePerKva: number;
}

export interface MonthDemand {
  month: string;
  demandKva: number;
}

export interface MonthCharge {
  billedKva: number;
  excessKva: number;
  charge: number;
}

export function validRule(rule: DemandRule): boolean {
  return (
    Number.isFinite(rule.minimumShare) &&
    rule.minimumShare >= 0 &&
    rule.minimumShare <= 1 &&
    Number.isFinite(rule.excessMultiplier) &&
    rule.excessMultiplier >= 1 &&
    Number.isFinite(rule.ratePerKva) &&
    rule.ratePerKva > 0
  );
}

/** One month's demand charge under the rule. */
export function monthCharge(
  recordedKva: number,
  contractKva: number,
  rule: DemandRule,
): MonthCharge {
  if (recordedKva <= contractKva) {
    const billedKva = Math.max(recordedKva, rule.minimumShare * contractKva);
    return { billedKva, excessKva: 0, charge: billedKva * rule.ratePerKva };
  }
  const excessKva = recordedKva - contractKva;
  return {
    billedKva: contractKva,
    excessKva,
    charge: contractKva * rule.ratePerKva + excessKva * rule.excessMultiplier * rule.ratePerKva,
  };
}

export interface YearRow {
  month: string;
  recordedKva: number;
  current: MonthCharge;
  proposed: MonthCharge;
}

export interface YearComparison {
  rows: YearRow[];
  currentTotal: number;
  proposedTotal: number;
  /** Positive when the proposed contract would have cost less. */
  saving: number;
  monthsOverProposed: string[];
  monthsOverCurrent: string[];
  highestKva: number;
}

export function compareYear(
  months: readonly MonthDemand[],
  currentKva: number,
  proposedKva: number,
  rule: DemandRule,
): YearComparison {
  const rows = [...months]
    .sort((a, b) => a.month.localeCompare(b.month))
    .map((m) => ({
      month: m.month,
      recordedKva: m.demandKva,
      current: monthCharge(m.demandKva, currentKva, rule),
      proposed: monthCharge(m.demandKva, proposedKva, rule),
    }));
  const currentTotal = rows.reduce((a, r) => a + r.current.charge, 0);
  const proposedTotal = rows.reduce((a, r) => a + r.proposed.charge, 0);
  return {
    rows,
    currentTotal,
    proposedTotal,
    saving: currentTotal - proposedTotal,
    monthsOverProposed: rows.filter((r) => r.proposed.excessKva > 0).map((r) => r.month),
    monthsOverCurrent: rows.filter((r) => r.current.excessKva > 0).map((r) => r.month),
    highestKva: Math.max(0, ...rows.map((r) => r.recordedKva)),
  };
}

/** The whole-kVA contract demand that would have cost least over these months under the rule,
 * searched from 1 kVA up to the larger of the current contract and the highest recorded demand.
 * Ties go to the larger contract (more headroom). */
export function cheapestContract(
  months: readonly MonthDemand[],
  rule: DemandRule,
  currentKva: number,
): { contractKva: number; total: number } | null {
  if (!months.length) return null;
  const highest = Math.max(...months.map((m) => m.demandKva));
  const top = Math.max(1, Math.ceil(Math.max(currentKva, highest)));
  let best: { contractKva: number; total: number } | null = null;
  for (let c = 1; c <= top; c += 1) {
    const total = months.reduce((a, m) => a + monthCharge(m.demandKva, c, rule).charge, 0);
    if (best === null || total < best.total - 1e-9 || Math.abs(total - best.total) <= 1e-9) {
      best = { contractKva: c, total };
    }
  }
  return best;
}
