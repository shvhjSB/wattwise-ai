import type { ReactNode } from 'react';

import type { ApiState } from '../api/useApi';
import { formatCount } from './format';
import { ErrorState, LoadingState } from './states';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm disabled:opacity-50';

/** A titled panel for one API resource, with its loading and error states. */
export function Resource<T>({
  title,
  resource,
  children,
}: {
  title: string;
  resource: { state: ApiState<T>; retry: () => void };
  children: (data: T) => ReactNode;
}) {
  return (
    <section
      className="min-w-0 space-y-4 rounded-xl border border-line bg-raised p-5"
      aria-label={title}
    >
      <h3 className="font-semibold">{title}</h3>
      {resource.state.status === 'loading' ? (
        <LoadingState label={`Loading ${title.toLowerCase()}...`} />
      ) : resource.state.status === 'error' ? (
        <ErrorState
          title={`${title} unavailable`}
          message={resource.state.error.message}
          onRetry={resource.retry}
        />
      ) : (
        children(resource.state.data)
      )}
    </section>
  );
}

/** Previous and next buttons for an offset-paged list. */
export function Pager({
  offset,
  limit,
  total,
  onPage,
  label,
}: {
  offset: number;
  limit: number;
  total: number;
  onPage: (offset: number) => void;
  label: string;
}) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center gap-3 text-sm">
      <button
        className={control}
        disabled={offset === 0}
        onClick={() => {
          onPage(Math.max(0, offset - limit));
        }}
      >
        Previous
      </button>
      <span>
        {total === 0 ? '0' : `${String(offset + 1)}–${String(Math.min(offset + limit, total))}`} of{' '}
        {formatCount(total)}
      </span>
      <button
        className={control}
        disabled={offset + limit >= total}
        onClick={() => {
          onPage(offset + limit);
        }}
      >
        Next
      </button>
    </nav>
  );
}
