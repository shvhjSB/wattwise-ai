import { getJson } from './client';
import type { StoredKind } from './summary';

export interface TariffScenario {
  geography: string;
  currency: string;
  rate_per_kwh: number;
}

export interface MoneyEstimate {
  value: number;
  currency: string;
  events: number;
}

export interface CarbonFactor {
  geography: string;
  geography_name: string;
  requested_year: number;
  vintage_year: number;
  kg_co2e_per_kwh: number;
  scope: string;
  source_name: string;
  source_url: string;
  retrieved: string;
  licence: string;
}

export interface PriceReference {
  geography: string;
  geography_name: string;
  year: number;
  period: string;
  sector: string;
  band: string | null;
  tax_basis: string;
  rate_per_kwh: number;
  currency: string;
  source_name: string;
  source_url: string;
  retrieved: string;
  licence: string;
}

export interface GeographyImpact {
  carbon_geography: string | null;
  tariff_geography: string | null;
  sites: string[];
  years: number[];
  events: number;
  potential_excess_kwh: number;
  potential_carbon_kg: number | null;
  carbon_configured_events: number;
  carbon_unconfigured_events: number;
  cost: MoneyEstimate | null;
  carbon_factors: CarbonFactor[];
  price_references: PriceReference[];
}

export interface KindImpact {
  kind: StoredKind;
  events: number;
  events_counted: number;
  meter_problem_events: number;
  total_potential_excess_kwh: number;
  total_potential_carbon_kg: number | null;
  carbon_configured_events: number;
  carbon_unconfigured_events: number;
  total_cost: MoneyEstimate | null;
  by_geography: GeographyImpact[];
}

export interface ImpactSummary {
  status: 'potential';
  tariff: TariffScenario | null;
  by_kind: KindImpact[];
  caveats: string[];
}

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

const text = (value: unknown): value is string => typeof value === 'string';
const number = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
const nullable =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is T | null =>
    value === null || guard(value);
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const numbers = (value: unknown): value is number[] => Array.isArray(value) && value.every(number);

function isTariff(value: unknown): value is TariffScenario {
  const item = record(value);
  return item !== null && text(item.geography) && text(item.currency) && number(item.rate_per_kwh);
}

function isMoney(value: unknown): value is MoneyEstimate {
  const item = record(value);
  return item !== null && number(item.value) && text(item.currency) && number(item.events);
}

function isFactor(value: unknown): value is CarbonFactor {
  const item = record(value);
  return (
    item !== null &&
    text(item.geography) &&
    text(item.geography_name) &&
    number(item.requested_year) &&
    number(item.vintage_year) &&
    number(item.kg_co2e_per_kwh) &&
    text(item.scope) &&
    text(item.source_name) &&
    text(item.source_url) &&
    text(item.retrieved) &&
    text(item.licence)
  );
}

function isPrice(value: unknown): value is PriceReference {
  const item = record(value);
  return (
    item !== null &&
    text(item.geography) &&
    text(item.geography_name) &&
    number(item.year) &&
    text(item.period) &&
    text(item.sector) &&
    nullable(text)(item.band) &&
    text(item.tax_basis) &&
    number(item.rate_per_kwh) &&
    text(item.currency) &&
    text(item.source_name) &&
    text(item.source_url) &&
    text(item.retrieved) &&
    text(item.licence)
  );
}

function isGeography(value: unknown): value is GeographyImpact {
  const item = record(value);
  return (
    item !== null &&
    nullable(text)(item.carbon_geography) &&
    nullable(text)(item.tariff_geography) &&
    texts(item.sites) &&
    numbers(item.years) &&
    number(item.events) &&
    number(item.potential_excess_kwh) &&
    nullable(number)(item.potential_carbon_kg) &&
    number(item.carbon_configured_events) &&
    number(item.carbon_unconfigured_events) &&
    nullable(isMoney)(item.cost) &&
    Array.isArray(item.carbon_factors) &&
    item.carbon_factors.every(isFactor) &&
    Array.isArray(item.price_references) &&
    item.price_references.every(isPrice)
  );
}

function isKind(value: unknown): value is KindImpact {
  const item = record(value);
  return (
    item !== null &&
    (item.kind === 'observed' || item.kind === 'synthetic') &&
    number(item.events) &&
    number(item.events_counted) &&
    number(item.meter_problem_events) &&
    number(item.total_potential_excess_kwh) &&
    nullable(number)(item.total_potential_carbon_kg) &&
    number(item.carbon_configured_events) &&
    number(item.carbon_unconfigured_events) &&
    nullable(isMoney)(item.total_cost) &&
    Array.isArray(item.by_geography) &&
    item.by_geography.every(isGeography)
  );
}

export function isImpactSummary(value: unknown): value is ImpactSummary {
  const item = record(value);
  return (
    item !== null &&
    item.status === 'potential' &&
    nullable(isTariff)(item.tariff) &&
    Array.isArray(item.by_kind) &&
    item.by_kind.every(isKind) &&
    texts(item.caveats)
  );
}

export function fetchImpact(tariff?: TariffScenario, signal?: AbortSignal): Promise<ImpactSummary> {
  const query = new URLSearchParams();
  if (tariff) {
    query.set('tariff_geography', tariff.geography);
    query.set('currency', tariff.currency);
    query.set('rate_per_kwh', String(tariff.rate_per_kwh));
  }
  const suffix = query.size ? `?${query.toString()}` : '';
  return getJson(`/api/v1/impact/summary${suffix}`, isImpactSummary, signal ? { signal } : {});
}
