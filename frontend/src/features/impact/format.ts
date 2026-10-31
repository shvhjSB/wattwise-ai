const ONE = new Intl.NumberFormat('en', { maximumFractionDigits: 1 });
const FOUR = new Intl.NumberFormat('en', { maximumFractionDigits: 4 });
const MONEY = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatCarbon(kg: number): { value: string; unit: string } {
  if (Math.abs(kg) >= 1000) return { value: ONE.format(kg / 1000), unit: 't CO2e' };
  return { value: ONE.format(kg), unit: 'kg CO2e' };
}

export function formatMoney(value: number): string {
  return MONEY.format(value);
}

export function formatRate(value: number): string {
  return FOUR.format(value);
}
