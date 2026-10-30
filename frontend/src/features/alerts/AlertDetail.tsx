import { useState } from 'react';

import { fetchAlert, type AlertDetail as Detail } from '../../api/alerts';
import { fetchExpectation, type ExpectationPoint } from '../../api/catalog';
import { useApi } from '../../api/useApi';
import { ResidualChart } from '../../design/chart/ResidualChart';
import { TimeSeriesChart } from '../../design/chart/TimeSeriesChart';
import { formatCount, formatEnergy, formatShare } from '../../design/format';
import { ProvenanceBadge } from '../../design/Provenance';
import { EmptyState, ErrorState, LoadingState } from '../../design/states';
import { alertView } from '../explorer/view';
import { evidenceView } from './evidence';
import { FeedbackForm } from './FeedbackForm';
import { reviewLabel, sentence, utcHour, words } from './format';

function signed(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`;
}

function EventCharts({ alert }: { alert: Detail }) {
  const request = useApi(`alert-expectation:${alert.meter_id}`, (signal) =>
    fetchExpectation(alert.meter_id, signal),
  );
  const [cursor, setCursor] = useState<number | null>(null);
  if (request.state.status === 'loading') return <LoadingState label="Loading event readings..." />;
  if (request.state.status === 'error') {
    return (
      <ErrorState
        title="The event chart is unavailable"
        message={request.state.error.message}
        onRetry={request.retry}
      />
    );
  }
  const series = request.state.data;
  if (!series.available || series.points.length === 0) {
    return (
      <EmptyState title="No event chart available">
        {series.message ?? 'No model expectation is stored for this meter.'}
      </EmptyState>
    );
  }
  const view = alertView(series.points, alert);
  const points = series.points.slice(view.from, view.to);
  const active: ExpectationPoint | undefined = cursor === null ? undefined : points[cursor];
  return (
    <section
      aria-label="Event readings and expectation"
      className="space-y-3 rounded-xl border border-line bg-raised p-4"
    >
      <div>
        <h4 className="font-semibold">Event in context</h4>
        <p className="text-xs text-muted">
          Three days of context on each side, where available. Both charts share the same hour
          cursor.
        </p>
      </div>
      <TimeSeriesChart
        points={points}
        alerts={[alert]}
        unit={series.unit}
        label={`Observed and expected energy in ${series.unit} per hour around this alert`}
        cursor={cursor}
        onCursor={setCursor}
      />
      <ResidualChart
        points={points}
        unit={series.unit}
        label={`Observed minus expected ${series.unit} around this alert`}
        cursor={cursor}
        onCursor={setCursor}
      />
      <output className="block min-h-10 rounded-md bg-sunken px-3 py-2 text-xs">
        {active ? (
          <span>
            {utcHour(active.timestamp)} / observed {active.observed?.toFixed(1) ?? 'missing'}{' '}
            {series.unit} / expected {active.expected?.toFixed(1) ?? 'unavailable'} {series.unit}
            {active.observed !== null && active.expected !== null
              ? ` / difference ${signed(active.observed - active.expected)} ${series.unit}`
              : ''}
          </span>
        ) : (
          <span className="text-muted">Move over either chart to inspect one hour.</span>
        )}
      </output>
    </section>
  );
}

function Evidence({ alert }: { alert: Detail }) {
  const evidence = evidenceView(alert.evidence);
  const energy =
    alert.potential_excess_kwh === null ? null : formatEnergy(alert.potential_excess_kwh);
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <section className="space-y-3 rounded-xl border border-line bg-raised p-4">
        <h4 className="font-semibold">Explanation</h4>
        <p className="text-sm leading-6">
          {alert.explanation ?? 'No plain-language explanation was stored for this alert.'}
        </p>
        <div className="rounded-lg bg-sunken p-3">
          <h5 className="text-sm font-semibold">Suggested check</h5>
          <p className="mt-1 text-sm">
            {evidence.check ??
              'Review the meter data, schedule, and operating context for this period.'}
          </p>
        </div>
      </section>

      <section className="space-y-3 rounded-xl border border-line bg-raised p-4">
        <h4 className="font-semibold">Evidence</h4>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="text-muted">Detector comparison</dt>
          <dd>
            {evidence.detector.observed_kwh !== null && evidence.detector.baseline_kwh !== null
              ? `${evidence.detector.observed_kwh.toFixed(1)} kWh recorded vs ${evidence.detector.baseline_kwh.toFixed(1)} kWh baseline`
              : (evidence.detector.baseline ?? alert.detector)}
          </dd>
          <dt className="text-muted">Model comparison</dt>
          <dd>
            {evidence.model.observed_kwh !== null && evidence.model.expected_kwh !== null
              ? `${evidence.model.observed_kwh.toFixed(1)} kWh recorded vs ${evidence.model.expected_kwh.toFixed(1)} kWh expected`
              : 'No model comparison stored'}
          </dd>
          <dt className="text-muted">Model agreement</dt>
          <dd>
            {evidence.model.agrees === null
              ? 'Not available'
              : evidence.model.agrees
                ? 'Agrees with the detector'
                : 'Does not agree with the detector'}
          </dd>
          <dt className="text-muted">Potential excess</dt>
          <dd>
            {energy ? `${energy.value} ${energy.unit} (estimate)` : 'Not counted for this alert'}
          </dd>
          <dt className="text-muted">Pattern</dt>
          <dd>{evidence.signature.description ?? sentence(alert.signature)}</dd>
        </dl>
      </section>

      <section className="space-y-3 rounded-xl border border-line bg-raised p-4">
        <h4 className="font-semibold">Model influences</h4>
        {evidence.influences.length > 0 ? (
          <ol className="space-y-2 text-sm">
            {evidence.influences.slice(0, 5).map((influence) => (
              <li
                key={influence.feature}
                className="flex justify-between gap-3 border-b border-line pb-2 last:border-0"
              >
                <span title={influence.description ?? undefined}>{words(influence.feature)}</span>
                <span className="whitespace-nowrap font-medium tabular-nums">
                  {signed(influence.mean_contribution_kwh)} kWh/h
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted">Influences were not computed for this alert.</p>
        )}
        <p className="text-xs text-muted">
          {evidence.influences_note ?? 'Influences are model associations, not causes.'}
        </p>
      </section>

      <section className="space-y-3 rounded-xl border border-line bg-raised p-4">
        <h4 className="font-semibold">Assumptions and limits</h4>
        <ul className="list-disc space-y-2 pl-5 text-sm">
          {evidence.detector.baseline ? (
            <li>The detector compares against {evidence.detector.baseline}.</li>
          ) : null}
          {evidence.model.interval_nominal !== null ? (
            <li>
              The model interval is nominally {formatShare(evidence.model.interval_nominal)}; it
              covered{' '}
              {evidence.model.measured_coverage === null
                ? 'an unreported share'
                : formatShare(evidence.model.measured_coverage)}{' '}
              of measured hours in this detection window.
            </li>
          ) : null}
          {alert.caveats.map((caveat) => (
            <li key={caveat}>{caveat}</li>
          ))}
          <li>
            Reviewer feedback is stored for people and evaluation; this model was not retrained from
            it.
          </li>
        </ul>
      </section>
    </div>
  );
}

function FeedbackHistory({ alert }: { alert: Detail }) {
  return (
    <section className="space-y-3 rounded-xl border border-line bg-raised p-4">
      <h4 className="font-semibold">Review history</h4>
      {alert.feedback.length === 0 ? (
        <p className="text-sm text-muted">No reviews yet.</p>
      ) : (
        <ol className="space-y-3">
          {alert.feedback.map((item) => (
            <li key={item.feedback_id} className="border-l-2 border-accent pl-3 text-sm">
              <p className="font-medium">{sentence(item.label)}</p>
              <p className="text-xs text-muted">
                {utcHour(item.created_at)}
                {item.reviewer ? ` / ${item.reviewer}` : ''}
              </p>
              {item.note ? <p className="mt-1 whitespace-pre-wrap">{item.note}</p> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function Loaded({
  alert,
  refresh,
  onQueueRefresh,
}: {
  alert: Detail;
  refresh: () => void;
  onQueueRefresh: () => void;
}) {
  return (
    <article aria-labelledby="alert-detail-title" className="space-y-5">
      <header className="rounded-xl border border-line bg-raised p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted">
              Alert #{alert.alert_id}
            </p>
            <h3 id="alert-detail-title" className="mt-1 text-lg font-semibold">
              {alert.building_id}
            </h3>
            <p className="text-sm text-muted">{alert.meter_id}</p>
          </div>
          <ProvenanceBadge kind={alert.data_kind} />
        </div>
        <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <dt className="text-xs text-muted">Priority</dt>
            <dd className="font-semibold">
              {sentence(alert.severity)} <span aria-hidden="true">&middot;</span>{' '}
              {alert.priority_score.toFixed(0)}/100
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Pattern</dt>
            <dd className="font-semibold">{sentence(alert.signature)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Review</dt>
            <dd className="font-semibold">
              {reviewLabel(alert.review_status)} / {formatCount(alert.feedback_count)} saved
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Window</dt>
            <dd className="font-semibold">
              {utcHour(alert.start)}
              <br />
              {formatCount(alert.duration_hours)} hours / {formatCount(alert.flagged_hours)} flagged
            </dd>
          </div>
        </dl>
      </header>
      <EventCharts key={alert.alert_id} alert={alert} />
      <Evidence alert={alert} />
      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-xl border border-line bg-raised p-4">
          <FeedbackForm
            alertId={alert.alert_id}
            onSaved={() => {
              refresh();
              onQueueRefresh();
            }}
          />
        </section>
        <FeedbackHistory alert={alert} />
      </div>
    </article>
  );
}

export function AlertDetail({
  alertId,
  onQueueRefresh,
}: {
  alertId: number;
  onQueueRefresh: () => void;
}) {
  const request = useApi(`alert:${String(alertId)}`, (signal) => fetchAlert(alertId, signal));
  if (request.state.status === 'loading') return <LoadingState label="Loading alert evidence..." />;
  if (request.state.status === 'error') {
    const message =
      request.state.error.status === 404
        ? `There is no alert ${String(alertId)}.`
        : request.state.error.message;
    return (
      <ErrorState title="This alert is unavailable" message={message} onRetry={request.retry} />
    );
  }
  return (
    <Loaded alert={request.state.data} refresh={request.retry} onQueueRefresh={onQueueRefresh} />
  );
}
