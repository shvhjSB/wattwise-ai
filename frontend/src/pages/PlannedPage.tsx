import type { RouteInfo } from '../design/routes';
import { EmptyState, PageHeader } from '../design/states';

/** A page that a later roadmap task builds: says so plainly instead of showing empty charts. */
export function PlannedPage({ route }: { route: RouteInfo }) {
  return (
    <>
      <PageHeader title={route.label} summary={route.summary} />
      <EmptyState title="Not built yet">
        This page arrives with roadmap task {route.task}. No data is shown here until then.
      </EmptyState>
    </>
  );
}

/** An address that matches no page. */
export function NotFoundPage({ onHome }: { onHome: () => void }) {
  return (
    <EmptyState
      title="Page not found"
      action={
        <button
          type="button"
          onClick={onHome}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Go to the overview
        </button>
      }
    >
      There is no page at this address.
    </EmptyState>
  );
}
