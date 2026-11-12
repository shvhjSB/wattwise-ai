import { routeFor, usePath } from './design/routes';
import { useTheme } from './design/theme';
import { SummaryProvider } from './features/summary/SummaryProvider';
import { useDataKinds, useSummary } from './features/summary/useSummary';
import { BillPage } from './pages/BillPage';
import { ExplorerPage } from './pages/ExplorerPage';
import { AlertsPage } from './pages/AlertsPage';
import { DataHealthPage } from './pages/DataHealthPage';
import { WhatIfPage } from './pages/WhatIfPage';
import { ImpactPage } from './pages/ImpactPage';
import { MachinesPage } from './pages/MachinesPage';
import { MeterPage } from './pages/MeterPage';
import { OverviewPage } from './pages/OverviewPage';
import { ModelsPage } from './pages/ModelsPage';
import { NotFoundPage, PlannedPage } from './pages/PlannedPage';
import { AppShell } from './shell/AppShell';

function Routes() {
  const { path, navigate } = usePath();
  const { choice, setChoice } = useTheme();
  const dataKinds = useDataKinds();
  const summary = useSummary();
  const route = routeFor(path);

  return (
    <AppShell
      path={route?.path ?? path}
      navigate={navigate}
      dataKinds={dataKinds}
      theme={choice}
      onThemeChange={setChoice}
    >
      {route === undefined ? (
        <NotFoundPage
          onHome={() => {
            navigate('/');
          }}
        />
      ) : route.path === '/' ? (
        <OverviewPage summary={summary} navigate={navigate} />
      ) : route.path === '/explorer' ? (
        <ExplorerPage summary={route.summary} />
      ) : route.path === '/machines' ? (
        <MachinesPage summary={route.summary} />
      ) : route.path === '/alerts' ? (
        <AlertsPage summary={route.summary} />
      ) : route.path === '/impact' ? (
        <ImpactPage summary={route.summary} />
      ) : route.path === '/whatif' ? (
        <WhatIfPage summary={route.summary} />
      ) : route.path === '/bill' ? (
        <BillPage summary={route.summary} />
      ) : route.path === '/meter' ? (
        <MeterPage summary={route.summary} />
      ) : route.path === '/data' ? (
        <DataHealthPage summary={route.summary} />
      ) : route.path === '/models' ? (
        <ModelsPage summary={route.summary} />
      ) : (
        <PlannedPage route={route} />
      )}
    </AppShell>
  );
}

export function App() {
  return (
    <SummaryProvider>
      <Routes />
    </SummaryProvider>
  );
}
