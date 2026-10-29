import { useId, useState, type ReactNode } from 'react';

/**
 * One headline figure with a definition and a source. The definition is a tooltip that opens on
 * hover or focus and closes on Escape or when the pointer or focus leaves (WCAG 1.4.13), and it is
 * always available to screen readers through `aria-describedby`.
 */
export function KpiCard({
  label,
  value,
  unit,
  note,
  definition,
  source,
  estimate = false,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: ReactNode;
  definition: string;
  source: string;
  /** Marks the figure as an estimate, in words next to the label. */
  estimate?: boolean;
}) {
  const tipId = useId();
  const [open, setOpen] = useState(false);

  return (
    <section
      aria-label={label}
      className="relative rounded-xl border border-line bg-raised p-5 shadow-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-muted">
          {label}
          {estimate ? (
            <span className="ml-2 rounded-full bg-uploaded-soft px-2 py-0.5 text-xs font-semibold text-uploaded">
              Estimate
            </span>
          ) : null}
        </h3>
        <button
          type="button"
          aria-label={`About ${label}`}
          aria-describedby={tipId}
          aria-expanded={open}
          onClick={() => {
            setOpen((o) => !o);
          }}
          onMouseEnter={() => {
            setOpen(true);
          }}
          onMouseLeave={() => {
            setOpen(false);
          }}
          onFocus={() => {
            setOpen(true);
          }}
          onBlur={() => {
            setOpen(false);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') setOpen(false);
          }}
          className="grid size-6 shrink-0 place-items-center rounded-full border border-edge text-xs font-semibold text-muted hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          <span aria-hidden="true">i</span>
        </button>
      </div>

      <p className="mt-3 text-3xl font-semibold tracking-tight">
        {value}
        {unit ? <span className="ml-1.5 text-base font-medium text-muted">{unit}</span> : null}
      </p>
      {note ? <p className="mt-1 text-sm text-muted">{note}</p> : null}

      <div
        id={tipId}
        role="tooltip"
        className={`absolute inset-x-3 top-12 z-10 rounded-lg border border-edge bg-raised p-3 text-xs leading-relaxed text-ink shadow-lg ${
          open ? 'block' : 'hidden'
        }`}
      >
        <p>{definition}</p>
        <p className="mt-2 text-muted">
          <span className="font-semibold">Source:</span> {source}
        </p>
      </div>
    </section>
  );
}
