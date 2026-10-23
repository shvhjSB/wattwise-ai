import { ApiHealthPanel } from './features/health/ApiHealthPanel';

export function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-5xl items-baseline gap-3 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight">WattWise AI</h1>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Explainable energy-waste detection for commercial buildings
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-6 py-10">
        <p className="max-w-prose text-sm text-slate-600 dark:text-slate-400">
          This is the application foundation. Energy analytics, anomaly investigation and model
          evaluation arrive in later milestones. No energy data is shown yet.
        </p>
        <ApiHealthPanel />
      </main>
    </div>
  );
}
