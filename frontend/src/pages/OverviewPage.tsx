import type { KindSummary } from '../api/summary';
import { KpiCard } from '../design/KpiCard';
import { formatCount, formatDate, formatEnergy, formatShare } from '../design/format';
import { ProvenanceBadge } from '../design/Provenance';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../design/states';
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

export function OverviewPage({ summary }: { summary: ReturnType<typeof useSummary> }) {
  const { state, retry } = summary;
  return (
    <>
      <PageHeader
        title="Overview"
        summary="Measured and expected energy, potential excess, open alerts and data coverage. Figures are shown per kind of data and never added across synthetic and observed."
      />

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

      <ApiHealthPanel />
    </>
  );
}
