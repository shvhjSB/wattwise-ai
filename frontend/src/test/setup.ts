import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

beforeEach(() => {
  // Tests assume same-origin API calls regardless of any local .env file.
  vi.stubEnv('VITE_API_BASE_URL', '');
});

afterEach(() => {
  cleanup();
});
