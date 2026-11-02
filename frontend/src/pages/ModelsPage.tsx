import {
  fetchAnalysisRuns,
  fetchDatasets,
  fetchEvaluation,
  fetchMetadata,
  fetchModelMetrics,
  type ModelMetadata,
} from '../api/models';
import { useApi } from '../api/useApi';
import { formatCount, formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { useSearch } from '../design/routes';
import { Pager, Resource } from '../design/Panel';
import { EmptyState, PageHeader } from '../design/states';
import { MetricTable } from '../features/models/MetricTable';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm disabled:opacity-50';

function Window({ start, end }: { start: string | null; end: string | null }) {
  return (
    <span>
      {start ?? 'Not recorded'} → {end ?? 'Not recorded'} (UTC, end exclusive)
    </span>
  );
}

function Metadata({ data }: { data: ModelMetadata }) {
  return (
    <>
      <p className="break-all font-mono text-sm">{data.version}</p>
      <p className="text-sm text-muted">{data.serves}</p>
      <dl className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries({
          Family: data.model.family,
          Variant: data.model.variant,
          Created: data.created_at,
          'Training rows': formatCount(data.training.training_rows),
          'Training meters': formatCount(data.training.meters),
          'Input rows': formatCount(data.training.data_rows),
          'Feature set': data.feature_set_version,
          'History horizon': `${String(data.horizon_hours)} hours`,
          Seed: String(data.model.seed),
        }).map(([label, value]) => (
          <div key={label}>
            <dt className="text-muted">{label}</dt>
            <dd className="mt-1 break-words font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="text-sm">
        Training observations: {data.training.first} → {data.training.last} (UTC, last observation
        inclusive).
      </p>
      <details className="text-sm">
        <summary className="cursor-pointer font-medium">
          Settings, features and reproducibility
        </summary>
        <div className="mt-3 space-y-3 break-words">
          <p className="break-all">
            Data fingerprint: <code>{data.training.data_fingerprint}</code>
          </p>
          <p>
            Libraries:{' '}
            {Object.entries(data.libraries)
              .map(([name, version]) => `${name} ${version}`)
              .join(', ')}
          </p>
          <pre className="overflow-x-auto rounded-lg bg-sunken p-3">
            {JSON.stringify({ settings: data.model.settings, split: data.split }, null, 2)}
          </pre>
          <p>Features: {data.feature_columns.join(', ')}</p>
        </div>
      </details>
    </>
  );
}

function offsetOf(value: string | null, size: number): number {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? Math.floor(parsed / size) * size : 0;
}

export function ModelsPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const query = params.get('building') ?? '';
  const offset = offsetOf(params.get('buildingOffset'), 25);
  const runOffset = offsetOf(params.get('runOffset'), 10);
  const metadata = useApi('model-metadata', fetchMetadata);
  const metrics = useApi('model-metrics', fetchModelMetrics);
  const evaluation = useApi(`model-evaluation:${query}:${String(offset)}`, (signal) =>
    fetchEvaluation(query, offset, signal),
  );
  const datasets = useApi('dataset-health', fetchDatasets);
  const runs = useApi(`analysis-runs:${String(runOffset)}`, (signal) =>
    fetchAnalysisRuns(runOffset, signal),
  );
  const servedVersion =
    metadata.state.status === 'success' && metadata.state.data.available
      ? metadata.state.data.version
      : null;

  return (
    <>
      <PageHeader title="Model lab" summary={summary} />
      <p className="rounded-lg bg-sunken p-4 text-sm text-muted">
        Expected consumption uses the observed weather of the target hour. These errors describe the
        recorded evaluation, not future-weather forecasts or anomaly-detection precision. Uploaded
        buildings have no measured accuracy unless separately evaluated.
      </p>
      <Resource title="Served model" resource={metadata}>
        {(data) =>
          data.available ? (
            <Metadata data={data} />
          ) : (
            <EmptyState title="Model unavailable">{data.message}</EmptyState>
          )
        }
      </Resource>
      <Resource title="Recorded metrics" resource={metrics}>
        {(data) =>
          !data.available ? (
            <EmptyState title="Metrics unavailable">{data.message}</EmptyState>
          ) : servedVersion !== null && data.version !== servedVersion ? (
            <EmptyState title="Model version changed">
              Reload this page to view consistent model metadata and metrics.
            </EmptyState>
          ) : (
            <>
              <ProvenanceBadge kind={data.data_label} />
              <p className="break-all text-sm">Model version: {data.version}</p>
              <p className="text-sm text-muted">{data.note}</p>
              <ul className="space-y-2 text-sm">
                {data.roles.map((role) => (
                  <li key={role.role}>
                    <strong className="capitalize">{role.role}</strong>:{' '}
                    <Window start={role.window_start} end={role.window_end} />
                  </li>
                ))}
              </ul>
              <MetricTable
                caption="Validation and test errors"
                rows={data.roles.map((role) => ({ label: role.role, metrics: role.metrics }))}
              />
              <details className="text-sm">
                <summary className="cursor-pointer">Metric definitions</summary>
                <dl className="mt-3 space-y-2">
                  {Object.entries(data.definitions).map(([name, definition]) => (
                    <div key={name}>
                      <dt className="font-medium uppercase">{name}</dt>
                      <dd className="text-muted">{definition}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            </>
          )
        }
      </Resource>
      <Resource title="Baseline comparison and buildings" resource={evaluation}>
        {(data) =>
          !data.available ? (
            <EmptyState title="Evaluation breakdown unavailable">{data.message}</EmptyState>
          ) : servedVersion !== null && data.version !== servedVersion ? (
            <EmptyState title="Evaluation version changed">
              Reload this page to view the served model's evaluation.
            </EmptyState>
          ) : (
            <>
              <p className="text-sm text-muted">{data.message}</p>
              <MetricTable
                caption="Recorded test comparison (available rows per forecaster)"
                rows={[
                  { label: 'Served model', metrics: data.model_metrics },
                  { label: data.baseline_name, metrics: data.baseline_metrics },
                ]}
              />
              <form
                role="search"
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = new FormData(event.currentTarget);
                  const building = form.get('building');
                  setParams({
                    building: typeof building === 'string' ? building : '',
                    buildingOffset: null,
                  });
                }}
                className="flex flex-wrap items-end gap-3"
              >
                <label className="grid gap-1 text-sm">
                  Building identifier
                  <input key={query} name="building" defaultValue={query} className={control} />
                </label>
                <button type="submit" className={control}>
                  Find building
                </button>
              </form>
              {data.buildings.length ? (
                <MetricTable
                  caption="Test errors by building"
                  rows={data.buildings.map((building) => ({
                    label: building.building_id,
                    metrics: building.metrics,
                  }))}
                />
              ) : (
                <EmptyState title="No matching building errors">
                  Try another building identifier or return to the first page.
                </EmptyState>
              )}
              <Pager
                offset={offset}
                limit={25}
                total={data.total}
                label="Building evaluation pages"
                onPage={(next) => {
                  setParams({ buildingOffset: String(next) });
                }}
              />
            </>
          )
        }
      </Resource>
      <Resource title="Dataset health" resource={datasets}>
        {(data) =>
          !data.datasets.length ? (
            <EmptyState title="No datasets loaded">
              Load a dataset to see its ingestion summary.
            </EmptyState>
          ) : (
            <>
              <p className="text-sm text-muted">
                Missing share is missing values divided by stored rows; absent hours are not
                counted. Duplicate, gap, flatline and out-of-range audit results are not retained by
                this API and are unavailable here.
              </p>
              <div className="grid gap-4 lg:grid-cols-2">
                {data.datasets.map((dataset) => (
                  <article
                    key={dataset.dataset_id}
                    className="min-w-0 space-y-2 rounded-lg border border-line p-4"
                  >
                    <h4 className="break-words font-medium">{dataset.name}</h4>
                    <ProvenanceBadge kind={dataset.kind} />
                    <p className="break-all text-xs text-muted">{dataset.dataset_id}</p>
                    <p className="text-sm">
                      {formatCount(dataset.buildings)} buildings · {formatCount(dataset.meters)}{' '}
                      meters · {formatCount(dataset.readings)} rows
                    </p>
                    <p className="text-sm">
                      Missing values: {formatCount(dataset.missing_values)} (
                      {dataset.readings
                        ? formatShare(dataset.missing_values / dataset.readings)
                        : 'Unavailable: no readings'}
                      )
                    </p>
                    <p className="break-words text-xs text-muted">
                      {dataset.first_reading ?? 'No first reading'} →{' '}
                      {dataset.last_reading ?? 'No last reading'} (UTC, last reading inclusive)
                    </p>
                  </article>
                ))}
              </div>
            </>
          )
        }
      </Resource>
      <Resource title="Recent upload analyses" resource={runs}>
        {(data) => (
          <>
            <p className="text-sm text-muted">
              Monitoring records, newest first. Uploaded readings and filenames are not retained;
              these counts do not establish accuracy. Only runs recorded while the database was
              available appear.
            </p>
            {data.items.length ? (
              <div className="space-y-3">
                {data.items.map((run) => (
                  <article
                    key={run.run_id}
                    className="space-y-2 rounded-lg border border-line p-4 text-sm"
                  >
                    <h4 className="font-medium">
                      Analysis #{run.run_id} · {run.created_at}
                    </h4>
                    <ProvenanceBadge kind="uploaded" />
                    <p className="break-all">
                      Model: {run.model_version ?? 'Unavailable: no model'} · Detector:{' '}
                      {run.detector}
                    </p>
                    <p>
                      {formatCount(run.readings)} readings · {formatCount(run.meters)} meters ·{' '}
                      {formatCount(run.missing_values)} missing · {formatCount(run.predictions)}{' '}
                      predictions · {formatCount(run.alerts)} alerts
                    </p>
                    <p className="text-xs text-muted">
                      Input: {run.input_start} → {run.input_end} (UTC, last reading inclusive)
                    </p>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState title="No recorded analyses">
                Upload analyses appear here after they run with a database available.
              </EmptyState>
            )}
            <Pager
              offset={runOffset}
              limit={10}
              total={data.total}
              label="Analysis pages"
              onPage={(next) => {
                setParams({ runOffset: String(next) });
              }}
            />
          </>
        )}
      </Resource>
    </>
  );
}
