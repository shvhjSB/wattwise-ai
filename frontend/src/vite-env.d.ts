/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the WattWise API. Empty or unset means same origin. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
