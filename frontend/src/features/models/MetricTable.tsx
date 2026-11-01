import type { Metrics } from '../../api/models';
import { formatCount, formatShare } from '../../design/format';

const labels = [
  'MAE (kWh)',
  'RMSE (kWh)',
  'Bias (kWh)',
  'WAPE',
  'Scored rows',
  'Missing predictions',
];

export function MetricTable({
  caption,
  rows,
}: {
  caption: string;
  rows: { label: string; metrics: Metrics | null }[];
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-sm">
        <caption className="p-3 text-left font-medium">{caption}</caption>
        <thead className="bg-sunken text-muted">
          <tr>
            <th scope="col" className="p-3">
              Result
            </th>
            {labels.map((label) => (
              <th scope="col" key={label} className="whitespace-nowrap p-3 text-right">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ label, metrics }) => (
            <tr key={label} className="border-t border-line">
              <th scope="row" className="p-3 font-medium">
                {label}
              </th>
              {metrics === null ? (
                <td className="p-3 text-warning" colSpan={6}>
                  Metrics not recorded
                </td>
              ) : (
                <>
                  {[metrics.mae, metrics.rmse, metrics.bias].map((value, index) => (
                    <td key={index} className="p-3 text-right tabular-nums">
                      {value === null ? 'Unavailable' : value.toFixed(3)}
                    </td>
                  ))}
                  <td className="p-3 text-right tabular-nums">
                    {metrics.wape === null ? 'Unavailable' : formatShare(metrics.wape)}
                  </td>
                  <td className="p-3 text-right tabular-nums">{formatCount(metrics.scored)}</td>
                  <td className="p-3 text-right tabular-nums">
                    {formatCount(metrics.missing_prediction)}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
