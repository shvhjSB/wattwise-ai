import { routeFor, usePath } from './design/routes';
import { PageHeader } from './design/states';
import { useTheme } from './design/theme';
import { ApiHealthPanel } from './features/health/ApiHealthPanel';
import { useDataKinds } from './features/provenance/useDataKinds';
import { NotFoundPage, PlannedPage } from './pages/PlannedPage';
import { AppShell } from './shell/AppShell';

export function App() {
  const { path, navigate } = usePath();
  const { choice, setChoice } = useTheme();
  const dataKinds = useDataKinds();
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
        <>
          <PageHeader title={route.label} summary={route.summary} />
          <p className="max-w-prose text-sm text-muted">
            The overview’s energy figures arrive with roadmap task {route.task}. Until then this
            page shows whether the API is reachable.
          </p>
          <ApiHealthPanel />
        </>
      ) : (
        <PlannedPage route={route} />
      )}
    </AppShell>
  );
}
