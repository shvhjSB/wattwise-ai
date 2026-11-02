import { fetchAnalysisRuns, fetchDatasets } from '../api/models';
import {
  fetchDatasetQuality,
  QUALITY_CHECKS,
  QUALITY_PAGE,
  type DatasetQuality,
  type MeterQuality,
  type QualityCheck,
} from '../api/quality';
import { useApi } from '../api/useApi';
import { formatCount, formatShare } from '../design/format';
import { Pager, Resource } from '../design/Panel';
import { ProvenanceBadge } from '../design/Provenance';
import { useSearch } from '../design/routes';
import { EmptyState, PageHeader } from '../design/states';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm disabled:opacity-50';

/** Plain names for the checks; the definitions come from the API. */
const CHECK_NAMES: Record<QualityCheck, string> = {
  gaps: 'Gaps',
  irregular_interval: 'Irregular intervals',
  missing_values: 'Missing values',
  low_coverage: 'Low coverage',
  negative_values: 'Negative values',
  zero_runs: 'Zero runs',
  flatlines: 'Flatlines',
  extreme_values: 'Extreme values (out of range)',
  implausible_intensity: 'Implausible intensity (out of range)',
};

function isCheck(value: string | null): value is QualityCheck {
  return value !== null && (QUALITY_CHECKS as readonly string[]).includes(value);
}

function Summary({ data }: { data: DatasetQuality }) {
  const s = data.summary;
  const items: [string, string][] = [
    ['Meters', formatCount(s.meters)],
    ['Rows stored', formatCount(s.rows)],
    ['Coverage', `${s.coverage_pct.toFixed(1)}% of expected intervals`],
    ['Meters with warnings', `${formatCount(s.meters_with_warnings)} of ${formatCount(s.meters)}`],
    ['Period (UTC)', `${s.first} → ${s.last}`],
    ['Audited', `${data.assessed_at} (quality v${data.quality_version})`],
  ];
  return (
    <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {items.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-muted">{label}</dt>
          <dd className="break-words font-medium">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function Checks({
  data,
  selected,
  onSelect,
}: {
  data: DatasetQuality;
  selected: QualityCheck | null;
  onSelect: (check: QualityCheck | null) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-left text-sm">
        <caption className="sr-only">Data-quality checks and the meters each one flags</caption>
        <thead className="text-muted">
          <tr>
            <th scope="col" className="py-2 pr-4 font-medium">
              Check
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              What it finds
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Meters
            </th>
          </tr>
        </thead>
        <tbody>
          {data.checks.map((c) => (
            <tr key={c.check} className="border-t border-line align-top">
              <td className="py-2 pr-4">
                {c.meters > 0 ? (
                  <button
                    type="button"
                    className="text-left font-medium text-accent underline-offset-2 hover:underline"
                    aria-pressed={selected === c.check}
                    onClick={() => {
                      onSelect(selected === c.check ? null : c.check);
                    }}
                  >
                    {CHECK_NAMES[c.check]}
                  </button>
                ) : (
                  <span>{CHECK_NAMES[c.check]}</span>
                )}
              </td>
              <td className="py-2 pr-4 text-muted">{c.definition}</td>
              <td className="py-2 pr-4 text-right tabular-nums">{formatCount(c.meters)}</td>
            </tr>
          ))}
          <tr className="border-t border-line align-top">
            <td className="py-2 pr-4">Duplicate timestamps</td>
            <td className="py-2 pr-4 text-muted">{data.duplicates_note}</td>
            <td className="py-2 pr-4 text-right tabular-nums">0</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function MeterRow({ meter }: { meter: MeterQuality }) {
  return (
    <article className="min-w-0 space-y-2 rounded-lg border border-line p-4 text-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="break-all font-medium">{meter.meter_id}</h4>
        <span className={meter.warnings ? 'font-medium text-danger' : 'text-muted'}>
          {meter.warnings
            ? `${formatCount(meter.warnings)} warning${meter.warnings === 1 ? '' : 's'}`
            : 'No warnings'}
        </span>
      </div>
      <p className="text-muted">
        {meter.meter_type} · {meter.unit} ·{' '}
        {meter.interval_minutes === null
          ? 'interval unknown'
          : `every ${String(meter.interval_minutes)} min`}{' '}
        · coverage {meter.coverage_pct.toFixed(1)}%
      </p>
      <p>
        {formatCount(meter.present_rows)} rows of {formatCount(meter.expected_intervals)} expected ·{' '}
        {formatCount(meter.absent_intervals)} absent · {formatCount(meter.missing_values)} missing
        values · {formatCount(meter.negative_values)} negative · {formatCount(meter.zero_values)}{' '}
        zero
      </p>
      {meter.findings.length ? (
        <ul className="space-y-1">
          {meter.findings.map((f, i) => (
            <li key={`${f.check}-${String(i)}`} className="break-words">
              <span className={f.severity === 'warning' ? 'text-danger' : 'text-muted'}>
                {f.severity === 'warning' ? 'Warning' : 'Info'}
              </span>{' '}
              · {CHECK_NAMES[f.check]}: {f.message}
              {f.start ? (
                <span className="text-muted">
                  {' '}
                  (e.g. {f.start} → {f.end ?? f.start} UTC)
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">No findings.</p>
      )}
    </article>
  );
}

function Audit({
  datasetId,
  check,
  warningsOnly,
  offset,
  setParams,
}: {
  datasetId: string;
  check: QualityCheck | null;
  warningsOnly: boolean;
  offset: number;
  setParams: (updates: Record<string, string | null>) => void;
}) {
  const key = `quality:${datasetId}:${check ?? ''}:${String(warningsOnly)}:${String(offset)}`;
  const quality = useApi(key, (signal) =>
    fetchDatasetQuality(datasetId, { check, warningsOnly, offset }, signal),
  );
  return (
    <Resource title="Data-quality audit" resource={quality}>
      {(data) =>
        !data.available ? (
          <EmptyState title="Not audited yet">{data.message}</EmptyState>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <ProvenanceBadge kind={data.data_kind} />
              <span className="break-all text-xs text-muted">{data.dataset_id}</span>
            </div>
            <Summary data={data} />
            <p className="text-sm text-muted">
              Findings describe the data, not the buildings: they flag where readings may be
              unreliable. A cause in a message is a hypothesis to check.
            </p>
            <Checks
              data={data}
              selected={check}
              onSelect={(next) => {
                setParams({ check: next, offset: null });
              }}
            />
            <details className="text-sm">
              <summary className="cursor-pointer text-muted">Thresholds used</summary>
              <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                {Object.entries(data.thresholds).map(([name, value]) => (
                  <li key={name}>
                    <span className="font-mono text-xs">{name}</span>: {String(value)}
                  </li>
                ))}
              </ul>
            </details>
            <div className="flex flex-wrap items-end gap-3 border-t border-line pt-4">
              <label className="text-sm">
                Check
                <select
                  className={`${control} ml-2`}
                  value={check ?? ''}
                  onChange={(event) => {
                    setParams({ check: event.target.value || null, offset: null });
                  }}
                >
                  <option value="">All meters</option>
                  {QUALITY_CHECKS.map((c) => (
                    <option key={c} value={c}>
                      {CHECK_NAMES[c]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={warningsOnly}
                  onChange={(event) => {
                    setParams({ warnings: event.target.checked ? '1' : null, offset: null });
                  }}
                  className="accent-accent"
                />
                Warnings only
              </label>
            </div>
            {data.meters.items.length ? (
              <div className="space-y-3">
                {data.meters.items.map((meter) => (
                  <MeterRow key={meter.meter_id} meter={meter} />
                ))}
              </div>
            ) : (
              <EmptyState title="No meters match">
                Choose another check or clear the filters.
              </EmptyState>
            )}
            <Pager
              offset={offset}
              limit={QUALITY_PAGE}
              total={data.meters.total}
              label="Meter pages"
              onPage={(next) => {
                setParams({ offset: String(next) });
              }}
            />
            <p className="text-xs text-muted">{data.uploads_note}</p>
          </>
        )
      }
    </Resource>
  );
}

function RecentUploads({
  offset,
  setParams,
}: {
  offset: number;
  setParams: (updates: Record<string, string | null>) => void;
}) {
  const runs = useApi(`runs:${String(offset)}`, (signal) => fetchAnalysisRuns(offset, signal));
  return (
    <Resource title="Recent uploads" resource={runs}>
      {(data) => (
        <>
          {data.items.length ? (
            <ul className="space-y-2 text-sm">
              {data.items.map((run) => (
                <li key={run.run_id} className="rounded-lg border border-line p-3">
                  <span className="font-medium">
                    Analysis #{run.run_id} · {run.created_at}
                  </span>
                  <span className="block text-muted">
                    {formatCount(run.readings)} readings · {formatCount(run.meters)} meters ·{' '}
                    {formatCount(run.missing_values)} missing (
                    {run.readings ? formatShare(run.missing_values / run.readings) : 'no readings'})
                    · input {run.input_start} → {run.input_end} UTC
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No recorded uploads">
              Uploads analysed with a database available are recorded here. The files themselves are
              not stored.
            </EmptyState>
          )}
          <Pager
            offset={offset}
            limit={10}
            total={data.total}
            label="Upload pages"
            onPage={(next) => {
              setParams({ runOffset: String(next) });
            }}
          />
        </>
      )}
    </Resource>
  );
}

export function DataHealthPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const datasets = useApi('datasets', fetchDatasets);
  const rawCheck = params.get('check');
  const check = isCheck(rawCheck) ? rawCheck : null;
  const warningsOnly = params.get('warnings') === '1';
  const offset = Math.max(0, Number(params.get('offset') ?? 0) || 0);
  const runOffset = Math.max(0, Number(params.get('runOffset') ?? 0) || 0);

  return (
    <>
      <PageHeader title="Data health" summary={summary} />
      <Resource title="Datasets" resource={datasets}>
        {(data) => {
          if (!data.datasets.length) {
            return (
              <EmptyState title="No datasets loaded">
                Load a dataset to see its data-quality audit.
              </EmptyState>
            );
          }
          const requested = params.get('dataset');
          const chosen = data.datasets.find((d) => d.dataset_id === requested) ?? data.datasets[0];
          if (chosen === undefined) return null;
          return (
            <>
              {data.datasets.length > 1 ? (
                <label className="text-sm">
                  Dataset
                  <select
                    className={`${control} ml-2`}
                    value={chosen.dataset_id}
                    onChange={(event) => {
                      setParams({ dataset: event.target.value, check: null, offset: null });
                    }}
                  >
                    {data.datasets.map((d) => (
                      <option key={d.dataset_id} value={d.dataset_id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <p className="text-sm">{chosen.name}</p>
              )}
              <Audit
                datasetId={chosen.dataset_id}
                check={check}
                warningsOnly={warningsOnly}
                offset={offset}
                setParams={setParams}
              />
            </>
          );
        }}
      </Resource>
      <RecentUploads offset={runOffset} setParams={setParams} />
    </>
  );
}
