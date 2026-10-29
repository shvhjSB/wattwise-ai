const INTEGER = new Intl.NumberFormat('en', { maximumFractionDigits: 0 });
const ONE_DECIMAL = new Intl.NumberFormat('en', { maximumFractionDigits: 1 });
const TWO_DECIMALS = new Intl.NumberFormat('en', { maximumFractionDigits: 2 });

export function formatCount(value: number): string {
  return INTEGER.format(value);
}

/** Energy in the largest sensible unit: kWh, MWh or GWh (decimal, 1,000 per step). */
export function formatEnergy(kwh: number): { value: string; unit: string } {
  const size = Math.abs(kwh);
  if (size >= 1e6) return { value: TWO_DECIMALS.format(kwh / 1e6), unit: 'GWh' };
  if (size >= 1e3) return { value: ONE_DECIMAL.format(kwh / 1e3), unit: 'MWh' };
  return { value: ONE_DECIMAL.format(kwh), unit: 'kWh' };
}

/** A share between 0 and 1 as a percentage, with two decimals for very small shares. */
export function formatShare(share: number): string {
  const percent = share * 100;
  return `${(percent < 1 ? TWO_DECIMALS : ONE_DECIMAL).format(percent)}%`;
}

/** A UTC timestamp as a date, e.g. `2016-01-01`. Dates are UTC, as the API's are. */
export function formatDate(iso: string): string {
  return iso.slice(0, 10);
}
