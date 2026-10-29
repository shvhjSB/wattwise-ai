import type { ReactNode } from 'react';

/** A region that is loading; announced politely to screen readers. */
export function LoadingState({ label }: { label: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-3 py-6 text-sm text-muted"
    >
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-line border-t-accent motion-reduce:animate-none"
      />
      {label}
    </div>
  );
}

/** Nothing to show, said plainly, with an optional next step. */
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-raised p-8 text-center">
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-2 text-sm text-muted">{children}</div> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/** A failure, with what went wrong and, when it can help, a retry. */
export function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="rounded-lg border border-danger-line bg-danger-soft p-4 text-sm">
      <p className="font-medium text-danger">{title}</p>
      <p className="mt-1 text-ink">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md bg-danger px-3 py-1.5 font-medium text-raised hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

/** A page's title and one-line purpose. */
export function PageHeader({ title, summary }: { title: string; summary: string }) {
  return (
    <header className="space-y-1">
      <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
      <p className="max-w-prose text-sm text-muted">{summary}</p>
    </header>
  );
}
