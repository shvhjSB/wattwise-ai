/**
 * The static demo (T050): with `VITE_SNAPSHOT=1` the app has no server. Each GET is answered
 * from answers recorded by `python -m wattwise.snapshot`, looked up in `snapshot/index.json` by
 * the same key the recorder used: the decoded path, then the query parameters sorted by name and
 * value, joined with `&`. A request that was not recorded gets a plain message, never invented
 * data, and nothing can be changed.
 */

export const SNAPSHOT = import.meta.env.VITE_SNAPSHOT === '1';

export const NOT_RECORDED =
  'This view is not part of the static demo, which holds the recorded answers for the preset ' +
  'views only (free-text searches, date filters and custom tariffs are not recorded). Run ' +
  'WattWise locally to explore everything.';
export const READ_ONLY =
  'This static demo is read-only: reviews, uploads and analyses are switched off. Run WattWise ' +
  'locally to use them.';

/** The lookup key of an API path such as `/api/v1/alerts?offset=0&limit=25`. */
export function snapshotKey(path: string): string {
  const url = new URL(path, 'http://snapshot.invalid');
  const pairs = [...url.searchParams.entries()].sort(([a, x], [b, y]) =>
    a < b ? -1 : a > b ? 1 : x < y ? -1 : x > y ? 1 : 0,
  );
  const query = pairs.map(([name, value]) => `${name}=${value}`).join('&');
  const decoded = decodeURIComponent(url.pathname);
  return query ? `${decoded}?${query}` : decoded;
}

interface Index {
  version: number;
  entries: Record<string, string>;
}

function isIndex(value: unknown): value is Index {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    v.version === 1 &&
    typeof v.entries === 'object' &&
    v.entries !== null &&
    Object.values(v.entries).every((file) => typeof file === 'string')
  );
}

let index: Promise<Index> | null = null;

function snapshotUrl(file: string): string {
  return `${import.meta.env.BASE_URL}snapshot/${file}`;
}

async function loadIndex(): Promise<Index> {
  const response = await fetch(snapshotUrl('index.json'));
  if (!response.ok) throw new Error(`snapshot index: HTTP ${String(response.status)}`);
  const body: unknown = await response.json();
  if (!isIndex(body)) throw new Error('snapshot index: unexpected format');
  return body;
}

/** Forget the cached index (tests). */
export function resetSnapshot(): void {
  index = null;
}

export type SnapshotAnswer =
  { kind: 'found'; body: unknown } | { kind: 'missing' } | { kind: 'refused' };

/** The recorded answer for a request, if there is one. Only GET is ever answered. */
export async function snapshotAnswer(
  path: string,
  method: 'GET' | 'POST',
  signal?: AbortSignal,
): Promise<SnapshotAnswer> {
  if (method !== 'GET') return { kind: 'refused' };
  index ??= loadIndex();
  let entries: Record<string, string>;
  try {
    entries = (await index).entries;
  } catch (error) {
    index = null; // retry on the next request
    throw error;
  }
  const file = entries[snapshotKey(path)];
  if (file === undefined) return { kind: 'missing' };
  const response = await fetch(snapshotUrl(file), signal ? { signal } : {});
  if (!response.ok) throw new Error(`snapshot answer: HTTP ${String(response.status)}`);
  return { kind: 'found', body: (await response.json()) as unknown };
}
