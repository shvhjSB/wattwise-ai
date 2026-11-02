import { DRIFT_PAGE, fetchDrift, type DriftPeriod } from '../../api/drift';
import { useApi } from '../../api/useApi';
import { formatCount, formatShare, levelChange } from '../../design/format';
import { Pager, Resource } from '../../design/Panel';
import { ProvenanceBadge } from '../../design/Provenance';
import { useSearch } from '../../design/routes';
import { EmptyState } from '../../design/states';

const control = 'rounded-md border border-edge bg-raised px-3 py-2 text-sm disabled:opacity-50';

function share(value: number | null): string {
  return value === null ? 'n/a' : formatShare(value);
}

function day(iso: string): string {
  return iso.slice(0, 10);
}

/** How meters' readings and the model's errors move over the stored evaluation window (T048). */
export function DriftPanel() {
  const { params, setParams } = useSearch();
  const datasetId = params.get('driftDataset');
  const rawPeriod = params.get('driftPeriod');
  const period: DriftPeriod | null =
    rawPeriod === 'week' || rawPeriod === 'month' ? rawPeriod : null;
  const parsed = Number(params.get('driftOffset') ?? 0);
  const offset = Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
  const drift = useApi(`drift:${datasetId ?? ''}:${period ?? ''}:${String(offset)}`, (signal) =>
    fetchDrift({ datasetId, period, offset }, signal),
  );

  return (
    <Resource title="Data drift" resource={drift}>
      {(data) =>
        !data.available ? (
          <EmptyState title="No drift to show">{data.message}</EmptyState>
        ) : (
          <>
            <p className="text-sm text-muted">{data.note}</p>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <ProvenanceBadge kind={data.data_kind} />
              <span className="break-all">
                Model <code>{data.model_version}</code> · window {day(data.window_start)} →{' '}
                {day(data.window_end)} (UTC) · training period: readings before{' '}
                {day(data.reference_end)}
              </span>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              {data.datasets.length > 1 ? (
                <label className="text-sm">
                  Dataset
                  <select
                    className={`${control} ml-2`}
                    value={data.dataset_id}
                    onChange={(event) => {
                      setParams({ driftDataset: event.target.value, driftOffset: null });
                    }}
                  >
                    {data.datasets.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="text-sm">
                Group by
                <select
                  className={`${control} ml-2`}
                  value={period ?? ''}
                  onChange={(event) => {
                    setParams({ driftPeriod: event.target.value || null, driftOffset: null });
                  }}
                >
                  <option value="">Automatic ({data.period})</option>
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                </select>
              </label>
            </div>
            {data.periods.length ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[36rem] text-left text-sm">
                  <caption className="sr-only">Drift by {data.period}</caption>
                  <thead className="text-muted">
                    <tr>
                      <th scope="col" className="py-2 pr-4 font-medium">
                        {data.period === 'week' ? 'Week from' : 'Month'}
                      </th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">
                        Readings
                      </th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">
                        Level vs training
                      </th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">
                        WAPE
                      </th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">
                        Bias
                      </th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">
                        In interval (nominal {formatShare(data.interval_nominal)})
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.periods.map((p) => (
                      <tr key={p.start} className="border-t border-line">
                        <td className="py-2 pr-4">
                          {data.period === 'week' ? day(p.start) : p.start.slice(0, 7)}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {formatCount(p.readings)}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {levelChange(p.median_level_ratio)}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">{share(p.wape)}</td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {p.bias === null ? 'n/a' : p.bias.toFixed(2)}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {p.coverage === null ? 'No interval yet' : formatShare(p.coverage)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No stored pairs">
                No reading in the window has a stored expectation.
              </EmptyState>
            )}
            {data.latest_period ? (
              <>
                <h4 className="font-medium">
                  Meters in the {data.period === 'week' ? 'week from' : 'month of'}{' '}
                  {data.period === 'week'
                    ? day(data.latest_period)
                    : data.latest_period.slice(0, 7)}
                  , largest level change first
                </h4>
                <ul className="space-y-2 text-sm">
                  {data.meters.items.map((m) => (
                    <li key={m.meter_id} className="rounded-lg border border-line p-3">
                      <span className="break-all font-medium">{m.meter_id}</span>
                      <span className="block text-muted">
                        Level vs training {levelChange(m.level_ratio)} · WAPE {share(m.wape)} · in
                        interval {m.coverage === null ? 'no interval' : formatShare(m.coverage)} ·{' '}
                        {formatCount(m.readings)} readings
                      </span>
                    </li>
                  ))}
                </ul>
                <Pager
                  offset={offset}
                  limit={DRIFT_PAGE}
                  total={data.meters.total}
                  label="Drift meter pages"
                  onPage={(next) => {
                    setParams({ driftOffset: String(next) });
                  }}
                />
              </>
            ) : null}
            <details className="text-sm">
              <summary className="cursor-pointer text-muted">Definitions</summary>
              <dl className="mt-2 space-y-1">
                {Object.entries(data.definitions).map(([name, definition]) => (
                  <div key={name}>
                    <dt className="inline font-mono text-xs">{name}</dt>:{' '}
                    <dd className="inline">{definition}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </>
        )
      }
    </Resource>
  );
}
