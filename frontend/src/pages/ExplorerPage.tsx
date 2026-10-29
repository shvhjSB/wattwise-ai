import { useSearch } from '../design/routes';
import { EmptyState, PageHeader } from '../design/states';
import { BuildingBrowser } from '../features/explorer/BuildingBrowser';
import { MeterView } from '../features/explorer/MeterView';

/** Browse buildings and meters; see a meter's readings against the model's expectation. */
export function ExplorerPage({ summary }: { summary: string }) {
  const { params, setParams } = useSearch();
  const building = params.get('building');
  const meter = params.get('meter');

  return (
    <>
      <PageHeader title="Buildings & meters" summary={summary} />
      <div className="grid gap-8 lg:grid-cols-[22rem_1fr]">
        <BuildingBrowser
          buildingId={building}
          meterId={meter}
          onSelectBuilding={(id) => {
            setParams({ building: id, meter: null });
          }}
          onSelectMeter={(b, m) => {
            setParams({ building: b, meter: m });
          }}
        />
        <div>
          {meter ? (
            <MeterView meterId={meter} />
          ) : (
            <EmptyState title="Choose a meter">
              Search for a building, open it, and choose one of its meters to see its readings
              against what the model expected.
            </EmptyState>
          )}
        </div>
      </div>
    </>
  );
}
