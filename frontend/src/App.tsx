import { routeFor, usePath } from './design/routes';
import { useTheme } from './design/theme';
import { SummaryProvider } from './features/summary/SummaryProvider';
import { useDataKinds, useSummary } from './features/summary/useSummary';
import { OverviewPage } from './pages/OverviewPage';
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
        <OverviewPage summary={summary} />
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
