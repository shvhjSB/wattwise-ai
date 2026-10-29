import type { DataKind } from '../api/summary';

const LABELS: Record<DataKind, { text: string; title: string; className: string }> = {
  synthetic: {
    text: 'Synthetic',
    title: 'Generated data, not measurements from real buildings.',
    className: 'bg-synthetic-soft text-synthetic',
  },
  observed: {
    text: 'Observed',
    title: 'Measured by real meters (BDG2).',
    className: 'bg-observed-soft text-observed',
  },
  uploaded: {
    text: 'Uploaded',
    title: 'Supplied by a user; not checked against any source.',
    className: 'bg-uploaded-soft text-uploaded',
  },
};

/** Where a piece of data comes from. Always text, never colour alone. */
export function ProvenanceBadge({ kind }: { kind: DataKind }) {
  const label = LABELS[kind];
  return (
    <span
      title={label.title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${label.className}`}
    >
      <span className="sr-only">Data provenance: </span>
      {label.text}
    </span>
  );
}

/**
 * Shown on every page while synthetic data is loaded, so demo numbers are never mistaken for
 * measurements.
 */
export function DemoBanner({ kinds }: { kinds: readonly DataKind[] }) {
  if (!kinds.includes('synthetic')) return null;
  const mixed = kinds.some((kind) => kind !== 'synthetic');
  return (
    <div
      role="note"
      aria-label="Demo data"
      className="border-b border-line bg-synthetic-soft px-6 py-2 text-sm text-synthetic"
    >
      <strong className="font-semibold">Demo data.</strong>{' '}
      {mixed
        ? 'Some of the data shown is synthetic; check each item’s provenance badge.'
        : 'Everything shown is synthetic: generated, not measured. Results on it are not real-world performance.'}
    </div>
  );
}
