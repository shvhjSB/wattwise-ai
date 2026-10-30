import type { ReviewStatus } from '../../api/alerts';

export function words(value: string): string {
  return value.replaceAll('_', ' ');
}

export function sentence(value: string): string {
  const text = words(value);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function utcHour(value: string): string {
  return `${value.slice(0, 16).replace('T', ' ')} UTC`;
}

export function reviewLabel(status: ReviewStatus): string {
  return status === 'unreviewed' ? 'Unreviewed' : sentence(status);
}

export function startOfDay(value: string | undefined): string | undefined {
  return value ? `${value}T00:00:00Z` : undefined;
}

/** The API's `end` is exclusive, while the date filter shown to people is inclusive. */
export function afterDay(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString();
}
