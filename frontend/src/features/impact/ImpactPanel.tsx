import type { GeographyImpact, KindImpact } from '../../api/impact';
import { formatCount, formatEnergy } from '../../design/format';
import { KpiCard } from '../../design/KpiCard';
import { ProvenanceBadge } from '../../design/Provenance';
import { formatCarbon, formatMoney, formatRate } from './format';

function region(group: GeographyImpact): string {
  if (group.tariff_geography && group.carbon_geography) {
    return group.tariff_geography === group.carbon_geography
      ? group.tariff_geography
      : `${group.tariff_geography} / ${group.carbon_geography}`;
  }
  return group.tariff_geography ?? group.carbon_geography ?? 'Not configured';
}

function CarbonConfiguration({ group }: { group: GeographyImpact }) {
  return (
    <article className="rounded-xl border border-line bg-raised p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h4 className="font-semibold">{group.carbon_geography ?? 'Carbon not configured'}</h4>
          <p className="text-xs text-muted">
            Sites {group.sites.join(', ')} · event years {group.years.join(', ')}
          </p>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${group.carbon_unconfigured_events ? 'bg-uploaded-soft text-uploaded' : 'bg-accent-soft text-success'}`}
        >
          {group.carbon_factors.length === 0
            ? 'Not configured'
            : group.carbon_unconfigured_events
              ? 'Partly configured'
              : 'Sourced'}
        </span>
      </div>
      {group.carbon_factors.length === 0 ? (
        <p className="mt-3 text-sm text-muted">
          No sourced regional factor is available. Carbon remains not configured, not zero.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {group.carbon_factors.map((factor) => (
            <li
              key={`${factor.geography}-${String(factor.requested_year)}`}
              className="rounded-lg bg-sunken p-3 text-sm"
            >
              <p className="font-semibold">{formatRate(factor.kg_co2e_per_kwh)} kg CO2e/kWh</p>
              <p className="text-xs text-muted">
                {factor.geography_name} · requested {factor.requested_year}, source vintage{' '}
                {factor.vintage_year} · {factor.scope}
              </p>
              <a
                href={factor.source_url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-xs font-medium text-accent underline"
              >
                {factor.source_name}
              </a>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function ImpactPanel({ impact }: { impact: KindImpact }) {
  const energy = formatEnergy(impact.total_potential_excess_kwh);
  const carbon =
    impact.total_potential_carbon_kg === null
      ? null
      : formatCarbon(impact.total_potential_carbon_kg);
  return (
    <section aria-label={`${impact.kind} impact`} className="space-y-4">
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-semibold capitalize">{impact.kind} data</h3>
        <ProvenanceBadge kind={impact.kind} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Potential excess energy"
          estimate
          value={energy.value}
          unit={energy.unit}
          note={`${formatCount(impact.events_counted)} consumption alerts; not verified savings`}
          definition="Energy above the model interval's upper bound over stored consumption alerts. An anomaly is not confirmed waste."
          source="Stored alert evidence, using the measured value and model interval."
        />
        <KpiCard
          label="Potential carbon"
          estimate
          value={carbon?.value ?? 'Not configured'}
          {...(carbon ? { unit: carbon.unit } : {})}
          note={`${formatCount(impact.carbon_configured_events)} events sourced · ${formatCount(impact.carbon_unconfigured_events)} not configured`}
          definition="Potential excess multiplied by the sourced factor for each event's site and year. Events without a factor remain not configured."
          source="Committed carbon-factor reference table; sources are listed below."
        />
        <KpiCard
          label="Scenario cost"
          estimate
          value={impact.total_cost ? formatMoney(impact.total_cost.value) : 'Not configured'}
          {...(impact.total_cost ? { unit: impact.total_cost.currency } : {})}
          note={
            impact.total_cost
              ? `${formatCount(impact.total_cost.events)} events in the configured tariff geography`
              : 'Configure one tariff geography above'
          }
          definition="Potential excess multiplied by the explicit scenario tariff, only for its named geography. This is not a saving forecast."
          source="The tariff scenario in this page's URL; it is not persisted."
        />
        <KpiCard
          label="Excluded meter problems"
          value={formatCount(impact.meter_problem_events)}
          unit={impact.meter_problem_events === 1 ? 'event' : 'events'}
          note={`${formatCount(impact.events)} alerts in total`}
          definition="Flatlines and data faults are not treated as consumption, so they add nothing to potential energy, cost or carbon."
          source="Stored alert signatures."
        />
      </div>

      <div className="overflow-x-auto rounded-xl border border-line bg-raised">
        <table className="w-full min-w-[46rem] text-left text-sm">
          <caption className="px-4 py-3 text-left font-semibold">Regional impact breakdown</caption>
          <thead className="border-y border-line bg-sunken text-xs text-muted">
            <tr>
              <th className="px-4 py-2 font-medium">Tariff / carbon geography</th>
              <th className="px-4 py-2 text-right font-medium">Events</th>
              <th className="px-4 py-2 text-right font-medium">Potential excess</th>
              <th className="px-4 py-2 text-right font-medium">Potential carbon</th>
              <th className="px-4 py-2 text-right font-medium">Scenario cost</th>
            </tr>
          </thead>
          <tbody>
            {impact.by_geography.map((group) => {
              const groupEnergy = formatEnergy(group.potential_excess_kwh);
              const groupCarbon =
                group.potential_carbon_kg === null ? null : formatCarbon(group.potential_carbon_kg);
              return (
                <tr
                  key={`${group.tariff_geography ?? 'none'}-${group.carbon_geography ?? 'none'}`}
                  className="border-b border-line last:border-0"
                >
                  <td className="px-4 py-3">
                    <span className="font-medium">{region(group)}</span>
                    <span className="block text-xs text-muted">{group.sites.join(', ')}</span>
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatCount(group.events)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {groupEnergy.value} {groupEnergy.unit}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {groupCarbon ? `${groupCarbon.value} ${groupCarbon.unit}` : 'Not configured'}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {group.cost
                      ? `${formatMoney(group.cost.value)} ${group.cost.currency}`
                      : 'Not configured'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <section className="space-y-3" aria-label={`${impact.kind} carbon factor configuration`}>
        <div>
          <h3 className="font-semibold">Carbon factor configuration</h3>
          <p className="text-sm text-muted">
            Factors are selected by each event's site and year. A source vintage may precede the
            requested year and is labelled explicitly.
          </p>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {impact.by_geography.map((group) => (
            <CarbonConfiguration
              key={`${group.tariff_geography ?? 'none'}-${group.carbon_geography ?? 'none'}`}
              group={group}
            />
          ))}
        </div>
      </section>
    </section>
  );
}
