import { useState, type SyntheticEvent } from 'react';

import type { ImpactSummary, PriceReference, TariffScenario } from '../../api/impact';
import { formatRate } from './format';

function tariffGeographies(summary: ImpactSummary): string[] {
  return [
    ...new Set(
      summary.by_kind.flatMap((kind) =>
        kind.by_geography.flatMap((group) =>
          group.tariff_geography === null ? [] : [group.tariff_geography],
        ),
      ),
    ),
  ].sort();
}

function references(summary: ImpactSummary, geography: string): PriceReference[] {
  const found = summary.by_kind.flatMap((kind) =>
    kind.by_geography.flatMap((group) =>
      group.tariff_geography === geography ? group.price_references : [],
    ),
  );
  return [
    ...new Map(
      found.map((item) => [
        [item.geography, item.year, item.rate_per_kwh, item.band, item.tax_basis].join('|'),
        item,
      ]),
    ).values(),
  ];
}

const control =
  'mt-1 w-full rounded-md border border-edge bg-raised px-3 py-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent';

export function TariffConfiguration({
  summary,
  onApply,
  onClear,
}: {
  summary: ImpactSummary;
  onApply: (tariff: TariffScenario) => void;
  onClear: () => void;
}) {
  const geographies = tariffGeographies(summary);
  const initial = summary.tariff;
  const [geography, setGeography] = useState(initial?.geography ?? geographies[0] ?? '');
  const [currency, setCurrency] = useState(initial?.currency ?? '');
  const [rate, setRate] = useState(initial ? String(initial.rate_per_kwh) : '');
  const [error, setError] = useState<string | null>(null);
  const available = references(summary, geography);

  const apply = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsed = Number(rate);
    if (!geography || !/^[A-Za-z]{3}$/.test(currency) || !Number.isFinite(parsed) || parsed <= 0) {
      setError('Choose a geography, a three-letter currency, and a positive rate per kWh.');
      return;
    }
    setError(null);
    onApply({ geography, currency: currency.toUpperCase(), rate_per_kwh: parsed });
  };

  return (
    <section className="space-y-4 rounded-xl border border-line bg-raised p-5">
      <div>
        <h3 className="font-semibold">Tariff scenario</h3>
        <p className="mt-1 text-sm text-muted">
          Configure one region at a time. This what-if rate is held in the URL, is not saved, and is
          never applied to another currency or geography.
        </p>
      </div>
      <form
        onSubmit={apply}
        aria-label="Tariff configuration"
        className="grid gap-3 md:grid-cols-3"
      >
        <label className="text-sm">
          Tariff geography
          <select
            value={geography}
            disabled={geographies.length === 0}
            onChange={(event) => {
              setGeography(event.target.value);
              setError(null);
            }}
            className={control}
          >
            {geographies.length === 0 ? <option value="">Not configured</option> : null}
            {geographies.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Currency code
          <input
            value={currency}
            maxLength={3}
            placeholder="USD"
            onChange={(event) => {
              setCurrency(event.target.value.toUpperCase());
              setError(null);
            }}
            className={control}
          />
        </label>
        <label className="text-sm">
          Rate per kWh
          <input
            type="number"
            min="0"
            step="any"
            value={rate}
            placeholder="0.1048"
            onChange={(event) => {
              setRate(event.target.value);
              setError(null);
            }}
            className={control}
          />
        </label>
        <div className="flex flex-wrap items-center gap-2 md:col-span-3">
          <button
            type="submit"
            disabled={geographies.length === 0}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-ink disabled:opacity-50"
          >
            Apply scenario
          </button>
          <button
            type="button"
            onClick={onClear}
            className="rounded-md border border-edge px-4 py-2 text-sm font-semibold"
          >
            Clear tariff
          </button>
          {summary.tariff ? (
            <span className="text-sm text-muted">
              Active: {formatRate(summary.tariff.rate_per_kwh)} {summary.tariff.currency}/kWh for{' '}
              {summary.tariff.geography}
            </span>
          ) : (
            <span className="text-sm font-medium text-muted">Cost: not configured</span>
          )}
        </div>
      </form>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="border-t border-line pt-4">
        <h4 className="text-sm font-semibold">Published reference rates</h4>
        <p className="mt-1 text-xs text-muted">
          References are shown for context, never applied automatically. Choose only a rate whose
          sector, band and tax basis fit the scenario.
        </p>
        {available.length === 0 ? (
          <p className="mt-3 text-sm text-muted">No published reference is configured here.</p>
        ) : (
          <ul className="mt-3 grid gap-2 lg:grid-cols-2">
            {available.map((item) => (
              <li
                key={`${String(item.year)}-${String(item.rate_per_kwh)}-${item.band ?? 'none'}-${item.tax_basis}`}
                className="rounded-lg bg-sunken p-3 text-sm"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-semibold">
                      {formatRate(item.rate_per_kwh)} {item.currency}/kWh · {item.year}
                    </p>
                    <p className="text-xs text-muted">
                      {item.sector}
                      {item.band ? ` · ${item.band.replaceAll('_', ' ')}` : ''} ·{' '}
                      {item.tax_basis.replaceAll('_', ' ')}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      onApply({
                        geography: item.geography,
                        currency: item.currency,
                        rate_per_kwh: item.rate_per_kwh,
                      });
                    }}
                    className="rounded-md border border-edge bg-raised px-2 py-1 text-xs font-semibold"
                  >
                    Use reference
                  </button>
                </div>
                <a
                  href={item.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-block text-xs font-medium text-accent underline"
                >
                  {item.source_name}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
