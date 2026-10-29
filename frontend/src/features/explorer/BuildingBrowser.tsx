import { useState, type SyntheticEvent } from 'react';

import { fetchBuildings, fetchMeters, type Building } from '../../api/catalog';
import { useApi } from '../../api/useApi';
import { formatCount } from '../../design/format';
import { ProvenanceBadge } from '../../design/Provenance';
import { EmptyState, ErrorState, LoadingState } from '../../design/states';

const PAGE = 20;
const MAX_LIMIT = 200;

/** Search buildings, pick one, and pick one of its meters. */
export function BuildingBrowser({
  buildingId,
  meterId,
  onSelectBuilding,
  onSelectMeter,
}: {
  buildingId: string | null;
  meterId: string | null;
  onSelectBuilding: (id: string) => void;
  onSelectMeter: (building: string, meter: string) => void;
}) {
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE);
  const buildings = useApi(`buildings:${query}:${String(limit)}`, (signal) =>
    fetchBuildings({ q: query, limit, offset: 0 }, signal),
  );

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    setQuery(draft.trim());
    setLimit(PAGE);
  };

  return (
    <section aria-labelledby="buildings-heading" className="space-y-4">
      <h3 id="buildings-heading" className="text-base font-semibold">
        Buildings
      </h3>

      <form role="search" onSubmit={submit} className="flex gap-2">
        <label className="sr-only" htmlFor="building-search">
          Search buildings by name or use
        </label>
        <input
          id="building-search"
          type="search"
          value={draft}
          maxLength={100}
          placeholder="Search by name or use"
          onChange={(event) => {
            setDraft(event.target.value);
          }}
          className="min-w-0 flex-1 rounded-md border border-edge bg-raised px-3 py-1.5 text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent"
        />
        <button
          type="submit"
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Search
        </button>
      </form>

      {buildings.state.status === 'loading' && <LoadingState label="Loading buildings…" />}
      {buildings.state.status === 'error' && (
        <ErrorState
          title="Buildings are unavailable"
          message={
            buildings.state.error.status === 503
              ? 'The API has no database to read from.'
              : buildings.state.error.message
          }
          onRetry={buildings.retry}
        />
      )}
      {buildings.state.status === 'success' &&
        (buildings.state.data.items.length === 0 ? (
          <EmptyState title={query ? 'No building matches' : 'No buildings loaded'}>
            {query ? `Nothing matches “${query}”.` : 'Load a dataset to browse its buildings.'}
          </EmptyState>
        ) : (
          <>
            <p className="text-sm text-muted" role="status">
              Showing {formatCount(buildings.state.data.items.length)} of{' '}
              {formatCount(buildings.state.data.total)} buildings
            </p>
            <ul
              aria-label="Buildings"
              className="divide-y divide-line rounded-xl border border-line bg-raised"
            >
              {buildings.state.data.items.map((building) => (
                <BuildingItem
                  key={building.building_id}
                  building={building}
                  selected={building.building_id === buildingId}
                  meterId={meterId}
                  onSelectBuilding={onSelectBuilding}
                  onSelectMeter={onSelectMeter}
                />
              ))}
            </ul>
            {buildings.state.data.items.length < buildings.state.data.total &&
              (limit < MAX_LIMIT ? (
                <button
                  type="button"
                  onClick={() => {
                    setLimit((n) => Math.min(MAX_LIMIT, n + PAGE));
                  }}
                  className="rounded-md border border-edge px-3 py-1.5 text-sm font-medium hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  Show more
                </button>
              ) : (
                <p className="text-sm text-muted">
                  Showing the first {String(MAX_LIMIT)}. Search to narrow the list.
                </p>
              ))}
          </>
        ))}
    </section>
  );
}

function BuildingItem({
  building,
  selected,
  meterId,
  onSelectBuilding,
  onSelectMeter,
}: {
  building: Building;
  selected: boolean;
  meterId: string | null;
  onSelectBuilding: (id: string) => void;
  onSelectMeter: (building: string, meter: string) => void;
}) {
  return (
    <li className="p-3">
      <button
        type="button"
        aria-expanded={selected}
        onClick={() => {
          onSelectBuilding(building.building_id);
        }}
        className="flex w-full items-start justify-between gap-3 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span>
          <span className="block text-sm font-medium break-all">{building.building_id}</span>
          <span className="block text-xs text-muted">
            {building.primary_use ?? 'Use unknown'} · {formatCount(building.meter_count)}{' '}
            {building.meter_count === 1 ? 'meter' : 'meters'}
          </span>
        </span>
        <ProvenanceBadge kind={building.data_kind} />
      </button>
      {selected ? (
        <MeterList building={building.building_id} meterId={meterId} onSelect={onSelectMeter} />
      ) : null}
    </li>
  );
}

function MeterList({
  building,
  meterId,
  onSelect,
}: {
  building: string;
  meterId: string | null;
  onSelect: (building: string, meter: string) => void;
}) {
  const meters = useApi(`meters:${building}`, (signal) => fetchMeters(building, signal));
  if (meters.state.status === 'loading') return <LoadingState label="Loading meters…" />;
  if (meters.state.status === 'error') {
    return (
      <ErrorState
        title="Meters are unavailable"
        message={meters.state.error.message}
        onRetry={meters.retry}
      />
    );
  }
  return (
    <ul aria-label={`Meters of ${building}`} className="mt-2 space-y-1">
      {meters.state.data.items.map((meter) => (
        <li key={meter.meter_id}>
          <button
            type="button"
            aria-current={meter.meter_id === meterId ? 'true' : undefined}
            onClick={() => {
              onSelect(building, meter.meter_id);
            }}
            className={`w-full rounded-md px-3 py-1.5 text-left text-sm focus-visible:outline-2 focus-visible:outline-accent ${
              meter.meter_id === meterId
                ? 'bg-accent text-accent-ink'
                : 'bg-sunken text-ink hover:bg-line'
            }`}
          >
            {meter.meter_type} <span className="opacity-80">({meter.unit})</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
