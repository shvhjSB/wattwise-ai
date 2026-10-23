/**
 * Minimal typed HTTP client for the WattWise API.
 *
 * Every response is checked at runtime against a type guard, so a backend/frontend contract
 * mismatch surfaces as an explicit error instead of silently rendering wrong data.
 */

export type ApiErrorKind = 'network' | 'http' | 'invalid-response';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | undefined;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number; cause?: unknown } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = 'ApiError';
    this.kind = kind;
    this.status = options.status;
  }
}

/** Build an absolute or same-origin URL for an API path such as `/api/v1/health`. */
export function apiUrl(path: string): string {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');
  return `${base}${path}`;
}

/** Checked by name, not `instanceof`, because DOMException can come from another realm. */
function isAbortError(error: unknown): boolean {
  return (
    typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError'
  );
}

/**
 * GET a JSON resource and validate its shape.
 *
 * Throws {@link ApiError} for network failures, non-2xx responses and unexpected payloads.
 * Aborted requests re-throw the original `AbortError` so callers can ignore them.
 */
export async function getJson<T>(
  path: string,
  isExpected: (value: unknown) => value is T,
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      headers: { Accept: 'application/json' },
      signal: options.signal ?? null,
    });
  } catch (cause) {
    if (isAbortError(cause)) throw cause;
    throw new ApiError('network', 'Could not reach the WattWise API.', { cause });
  }

  if (!response.ok) {
    // A proxy may answer instead of the API (e.g. 502 when the backend is down), so the
    // message names the request, not the API, as the source of the status.
    throw new ApiError(
      'http',
      `The WattWise API request failed with HTTP ${String(response.status)}.`,
      {
        status: response.status,
      },
    );
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (cause) {
    throw new ApiError(
      'invalid-response',
      'The WattWise API returned a response that is not JSON.',
      {
        status: response.status,
        cause,
      },
    );
  }

  if (!isExpected(body)) {
    throw new ApiError(
      'invalid-response',
      'The WattWise API response did not match the expected format.',
      { status: response.status },
    );
  }
  return body;
}
