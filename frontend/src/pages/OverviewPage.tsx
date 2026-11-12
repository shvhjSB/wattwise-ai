import type { DatasetSummary, KindSummary } from '../api/summary';
import { KpiCard } from '../design/KpiCard';
import { formatCount, formatDate, formatEnergy, formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../design/states';
import { href } from '../design/routes';
import { ApiHealthPanel } from '../features/health/ApiHealthPanel';
import { useSummary } from '../features/summary/useSummary';

const ALERT_SOURCE = 'Stored alerts (detected by the rolling z-score, scored by T022).';

/** The six headline figures of one kind of data. Kinds are never added together. */
function KindOverview({ kind }: { kind: KindSummary }) {
  const measured = formatEnergy(kind.measured_kwh);
  const excess = formatEnergy(kind.alerts.potential_excess_kwh);
  const expected = formatEnergy(kind.alerts.expected_kwh_in_alerts);
  const observedInAlerts = formatEnergy(kind.alerts.observed_kwh_in_alerts);
  const consumptionAlerts =
    (kind.alerts.by_kind.above_expected ?? 0) + (kind.alerts.by_kind.below_expected ?? 0);
  const meterProblems = kind.alerts.by_kind.meter_problem ?? 0;
  const hasAlerts = kind.alerts.alerts > 0;

  return (
    <section aria-label={`${kind.kind} data`} className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-semibold capitalize">{kind.kind} data</h3>
        <ProvenanceBadge kind={kind.kind} />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <KpiCard
          label="Measured energy"
          value={measured.value}
          unit={measured.unit}
          note={
            kind.first_reading && kind.last_reading
              ? `Recorded by ${formatCount(kind.meters)} meters, ${formatDate(kind.first_reading)} to ${formatDate(kind.last_reading)}`
              : 'No readings'
          }
          definition="The sum of the recorded readings of the kWh meters over the whole period. Missing readings add nothing: they are not counted as zero."
          source="Stored readings, totalled when the dataset was loaded."
        />
        <KpiCard
          label="Model-expected energy, in alert windows"
          value={hasAlerts ? expected.value : '—'}
          {...(hasAlerts ? { unit: expected.unit } : {})}
          note={
            hasAlerts
              ? `against ${observedInAlerts.value} ${observedInAlerts.unit} recorded over the same hours (${formatCount(consumptionAlerts)} consumption alerts; above- and below-expected alerts net out)`
              : 'No alerts, so no expectation is stored'
          }
          definition="What the model expected for the hours covered by consumption alerts, next to the energy recorded in the same hours. The model's expectation is stored only for alert windows, so there is no portfolio-wide expected figure."
          source="Stored alerts' evidence (the evaluation model)."
        />
        <KpiCard
          label="Potential excess energy"
          estimate
          value={hasAlerts ? excess.value : '—'}
          {...(hasAlerts ? { unit: excess.unit } : {})}
          note={
            hasAlerts
              ? 'Above the model’s upper bound, in alert hours. Not verified savings.'
              : 'No alerts'
          }
          definition="Energy above the model's upper 90% bound over the hours of consumption alerts. It is potential, not a verified saving, and an anomaly is not confirmed waste. Meter problems are not counted."
          source={ALERT_SOURCE}
        />
        <KpiCard
          label="Open alerts"
          value={formatCount(kind.alerts.open)}
          note={`${formatCount(kind.alerts.high_severity)} high severity · ${formatCount(kind.alerts.alerts)} in total`}
          definition="Alerts not yet reviewed, or marked needs investigation, excluding alerts a later detection no longer finds. Severity is a band of the priority score (high is 60 or more); the score orders review and is not a probability."
          source={ALERT_SOURCE}
        />
        <KpiCard
          label="Data quality"
          value={kind.missing_share === null ? '—' : formatShare(kind.missing_share)}
          note={`${formatCount(kind.missing_values)} of ${formatCount(kind.readings)} readings missing · ${formatCount(meterProblems)} meter-problem alerts`}
          definition="The share of readings with no value (not measured). Meter-problem alerts are events whose signature says the meter or its data is at fault (flatline or data fault), not the building's consumption."
          source="Stored readings and alerts."
        />
        <KpiCard
          label="Coverage"
          value={formatCount(kind.buildings)}
          unit={kind.buildings === 1 ? 'building' : 'buildings'}
          note={`${formatCount(kind.meters)} meters · ${formatCount(kind.readings)} readings · ${formatCount(kind.datasets)} ${kind.datasets === 1 ? 'dataset' : 'datasets'}`}
          definition="The buildings and meters stored, and how many hourly readings they have, over the period shown under Measured energy (UTC)."
          source="Stored buildings, meters and readings."
        />
      </div>
    </section>
  );
}

/**
 * Every stored source, with its label and version (when it was loaded). Sources are never merged
 * or substituted for one another; uploads are never stored, so they are not listed here.
 */
function DataSources({ datasets }: { datasets: readonly DatasetSummary[] }) {
  return (
    <section aria-labelledby="data-sources" className="space-y-3">
      <h3 id="data-sources" className="text-lg font-semibold">
        Data sources
      </h3>
      <p className="text-sm text-muted">
        Stored datasets are historical records, not live data. Uploaded files are analysed by the
        API without being stored and are labelled Uploaded.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <caption className="sr-only">Stored datasets, their provenance and version</caption>
          <thead className="text-muted">
            <tr>
              <th scope="col" className="py-2 pr-4 font-medium">
                Dataset
              </th>
              <th scope="col" className="py-2 pr-4 font-medium">
                Provenance
              </th>
              <th scope="col" className="py-2 pr-4 font-medium">
                Period recorded (UTC)
              </th>
              <th scope="col" className="py-2 pr-4 text-right font-medium">
                Readings
              </th>
              <th scope="col" className="py-2 pr-4 font-medium">
                Version (loaded)
              </th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((d) => (
              <tr key={d.dataset_id} className="border-t border-line align-top">
                <td className="py-2 pr-4">
                  <span className="font-medium">{d.name}</span>
                  <span className="block font-mono text-xs text-muted">{d.dataset_id}</span>
                </td>
                <td className="py-2 pr-4">
                  <ProvenanceBadge kind={d.kind} />
                </td>
                <td className="py-2 pr-4">
                  {d.first_reading && d.last_reading
                    ? `${formatDate(d.first_reading)} to ${formatDate(d.last_reading)}`
                    : 'No readings'}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">{formatCount(d.readings)}</td>
                <td className="py-2 pr-4">{formatDate(d.loaded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const STEPS: { path: string; link: string; text: string }[] = [
  {
    path: '/bill',
    link: 'Check a bill',
    text: 'Type in a monthly bill: where the money goes, the demand charge, time-of-day and late fees, checked against the bill’s own total, and a contract-demand what-if.',
  },
  {
    path: '/meter',
    link: 'Check a meter file',
    text: 'Load your main meter’s 15-, 30- or 60-minute readings: peak demand, use while closed, the base load and unusual periods.',
  },
  {
    path: '/machines',
    link: 'Compare machines',
    text: 'With a meter on each machine: which one uses what, what runs while you are closed, and its unusual hours.',
  },
];

/** The check-up, first (T069): what a small factory can do here, privately and for free. */
function CheckupIntro({ navigate }: { navigate: (path: string) => void }) {
  return (
    <section
      aria-label="Electricity check-up"
      className="space-y-4 rounded-xl border border-line bg-raised p-5"
    >
      <div className="space-y-1">
        <h3 className="text-lg font-semibold">A free, private electricity check-up</h3>
        <p className="text-sm text-muted">
          For a small factory, from the data it already has. The bill and meter checks run in your
          browser: nothing you enter or load is sent anywhere or saved. Each method’s tests are
          published, including what did not work and what has not been tested on factory data.
        </p>
      </div>
      <ol className="grid gap-3 sm:grid-cols-3">
        {STEPS.map((step, i) => (
          <li key={step.path} className="space-y-1 rounded-lg border border-line p-4 text-sm">
            <a
              href={href(step.path)}
              onClick={(event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
                event.preventDefault();
                navigate(step.path);
              }}
              className="font-semibold text-accent underline-offset-2 hover:underline"
            >
              {String(i + 1)}. {step.link}
            </a>
            <p className="text-muted">{step.text}</p>
          </li>
        ))}
      </ol>
      <p className="text-xs text-muted">
        A bill cannot show which machine uses what. The method tested for splitting a single main
        meter into machines did not work on a real factory (T065), so that needs a meter on each
        machine.
      </p>
    </section>
  );
}

export function OverviewPage({
  summary,
  navigate,
}: {
  summary: ReturnType<typeof useSummary>;
  /** The router's own navigation (a second `usePath` would not move the router). */
  navigate: (path: string) => void;
}) {
  const { state, retry } = summary;
  return (
    <>
      <PageHeader
        title="Overview"
        summary="Measured and expected energy, potential excess, open alerts and data coverage. Figures are shown per kind of data and never added across synthetic and observed."
      />

      <CheckupIntro navigate={navigate} />

      {state.status === 'loading' && <LoadingState label="Loading the overview…" />}

      {state.status === 'error' && (
        <ErrorState
          title="The overview is unavailable"
          message={
            state.error.status === 503
              ? 'The API has no database to read from. Configure WATTWISE_DATABASE_URL and load a dataset.'
              : state.error.message
          }
          onRetry={retry}
        />
      )}

      {state.status === 'success' && state.data.by_kind.length === 0 && (
        <EmptyState title="No data loaded">
          Load a dataset with <code className="font-mono">python -m wattwise.db.load</code>, then
          load its alerts with <code className="font-mono">python -m wattwise.db.alerts</code>.
        </EmptyState>
      )}

      {state.status === 'success' &&
        state.data.by_kind.map((kind) => <KindOverview key={kind.kind} kind={kind} />)}

      {state.status === 'success' && state.data.datasets.length > 0 && (
        <DataSources datasets={state.data.datasets} />
      )}

      <ApiHealthPanel />
    </>
  );
}
