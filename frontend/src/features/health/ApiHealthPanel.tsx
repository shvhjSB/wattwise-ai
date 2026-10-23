import { useApiHealth } from './useApiHealth';

/** Shows whether the WattWise API is reachable, with loading and error states. */
export function ApiHealthPanel() {
  const { state, retry } = useApiHealth();

  return (
    <section
      aria-labelledby="api-health-heading"
      className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900"
    >
      <h2 id="api-health-heading" className="text-base font-semibold">
        API connection
      </h2>

      <div role="status" aria-live="polite" className="mt-4">
        {state.status === 'loading' && (
          <p className="text-sm text-slate-600 dark:text-slate-400">Checking the WattWise API…</p>
        )}

        {state.status === 'success' && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-slate-600 dark:text-slate-400">Status</dt>
            <dd className="flex items-center gap-2 font-medium text-emerald-700 dark:text-emerald-400">
              <span aria-hidden="true" className="size-2 rounded-full bg-emerald-600" />
              Online
            </dd>
            <dt className="text-slate-600 dark:text-slate-400">Service</dt>
            <dd className="font-mono">{state.data.service}</dd>
            <dt className="text-slate-600 dark:text-slate-400">Version</dt>
            <dd className="font-mono">{state.data.version}</dd>
            <dt className="text-slate-600 dark:text-slate-400">Environment</dt>
            <dd className="font-mono">{state.data.environment}</dd>
          </dl>
        )}
      </div>

      {state.status === 'error' && (
        <div
          role="alert"
          className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm dark:border-red-900 dark:bg-red-950"
        >
          <p className="font-medium text-red-800 dark:text-red-200">API unavailable</p>
          <p className="mt-1 text-red-700 dark:text-red-300">{state.error.message}</p>
          <button
            type="button"
            onClick={retry}
            className="mt-3 rounded-md bg-red-700 px-3 py-1.5 font-medium text-white hover:bg-red-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700"
          >
            Retry
          </button>
        </div>
      )}
    </section>
  );
}
