import { fetchImpact, type TariffScenario } from '../api/impact';
import { useApi } from '../api/useApi';
import { useSearch } from '../design/routes';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../design/states';
import { ImpactPanel } from '../features/impact/ImpactPanel';
import { TariffConfiguration } from '../features/impact/TariffConfiguration';

function tariffFrom(params: URLSearchParams): TariffScenario | undefined {
  const geography = params.get('tariff');
  const currency = params.get('currency');
  const rate = Number(params.get('rate'));
  if (
    geography === null ||
    currency === null ||
    !/^[A-Za-z]{3}$/.test(currency) ||
    !Number.isFinite(rate) ||
    rate <= 0
  ) {
    return undefined;
  }
  return { geography, currency: currency.toUpperCase(), rate_per_kwh: rate };
}

/** Potential energy, cost and carbon scenarios, with every configuration and source visible. */
export function ImpactPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const tariff = tariffFrom(params);
  const key = tariff
    ? `${tariff.geography}:${tariff.currency}:${String(tariff.rate_per_kwh)}`
    : 'unconfigured';
  const impact = useApi(`impact:${key}`, (signal) => fetchImpact(tariff, signal));
  const setTariff = (next: TariffScenario) => {
    setParams({
      tariff: next.geography,
      currency: next.currency,
      rate: String(next.rate_per_kwh),
    });
  };
  const clearTariff = () => {
    setParams({ tariff: null, currency: null, rate: null });
  };

  return (
    <>
      <PageHeader title="Cost impact" summary={summary} />
      {impact.state.status === 'loading' ? (
        <LoadingState label="Loading impact estimates..." />
      ) : null}
      {impact.state.status === 'error' ? (
        <ErrorState
          title="Impact estimates are unavailable"
          message={impact.state.error.message}
          onRetry={impact.retry}
        />
      ) : null}
      {impact.state.status === 'success' ? (
        impact.state.data.by_kind.length === 0 ? (
          <EmptyState title="No impact to estimate">
            Load alerts before configuring cost or carbon impact.
          </EmptyState>
        ) : (
          <div className="space-y-8">
            <TariffConfiguration
              key={key}
              summary={impact.state.data}
              onApply={setTariff}
              onClear={clearTariff}
            />
            {impact.state.data.by_kind.map((kind) => (
              <ImpactPanel key={kind.kind} impact={kind} />
            ))}
            <section className="rounded-xl border border-line bg-raised p-5">
              <h3 className="font-semibold">Assumptions and limits</h3>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-sm">
                {impact.state.data.caveats.map((caveat) => (
                  <li key={caveat}>{caveat}</li>
                ))}
                <li>Observed and synthetic data are shown separately and never added together.</li>
              </ul>
            </section>
          </div>
        )
      ) : null}
    </>
  );
}
