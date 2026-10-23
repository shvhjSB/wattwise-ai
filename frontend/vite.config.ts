/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  // Non-VITE_ variables are read here only and are never embedded in the browser bundle.
  const env = loadEnv(mode, process.cwd(), '');
  // An empty value (as in .env.example) means "use the default backend address".
  const configuredTarget = env.WATTWISE_DEV_API_TARGET?.trim() ?? '';
  const devApiTarget = configuredTarget === '' ? 'http://127.0.0.1:8000' : configuredTarget;

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      strictPort: true,
      // Same-origin API calls in development; production uses a reverse proxy (see DECISIONS D009).
      proxy: { '/api': { target: devApiTarget } },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      restoreMocks: true,
      unstubGlobals: true,
      unstubEnvs: true,
    },
  };
});
