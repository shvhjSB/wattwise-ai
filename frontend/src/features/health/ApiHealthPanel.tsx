import { ErrorState } from '../../design/states';
import { useApiHealth } from './useApiHealth';

/** Shows whether the WattWise API is reachable, with loading and error states. */
export function ApiHealthPanel() {
  const { state, retry } = useApiHealth();

  return (
    <section
      aria-labelledby="api-health-heading"
      className="rounded-xl border border-line bg-raised p-6 shadow-sm"
    >
      <h2 id="api-health-heading" className="text-base font-semibold">
        API connection
      </h2>

      <div role="status" aria-live="polite" className="mt-4">
        {state.status === 'loading' && (
          <p className="text-sm text-muted">Checking the WattWise API…</p>
        )}

        {state.status === 'success' && (
          <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted">Status</dt>
            <dd className="flex items-center gap-2 font-medium text-success">
              <span aria-hidden="true" className="size-2 rounded-full bg-success" />
              Online
            </dd>
            <dt className="text-muted">Service</dt>
            <dd className="font-mono">{state.data.service}</dd>
            <dt className="text-muted">Version</dt>
            <dd className="font-mono">{state.data.version}</dd>
            <dt className="text-muted">Environment</dt>
            <dd className="font-mono">{state.data.environment}</dd>
          </dl>
        )}
      </div>

      {state.status === 'error' && (
        <div className="mt-4">
          <ErrorState title="API unavailable" message={state.error.message} onRetry={retry} />
        </div>
      )}
    </section>
  );
}
