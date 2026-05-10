/**
 * Resolves the action-router backend URL the web app dials.
 *
 * Mirrors the iOS `BackendConfig.swift` pattern (generated from .env's
 * PUBLIC_BASE_URL or the Mac LAN IP at build time). Values flow:
 *
 *   1. NEXT_PUBLIC_BACKEND_URL  (set by `make web` from .env)
 *   2. NEXT_PUBLIC_PUBLIC_BASE_URL (legacy ngrok pin, kept for compatibility)
 *   3. http://localhost:8001  (zero-config default — works when the web
 *      dev server and the action router run on the same Mac)
 *
 * `NEXT_PUBLIC_USE_MOCKS=1` disables real network calls and falls back
 * to the MSW handlers (useful for designers iterating without a backend).
 */

const trim = (s: string | undefined) => (s ?? "").trim().replace(/\/+$/, "");

const fromEnv =
  trim(process.env.NEXT_PUBLIC_BACKEND_URL) ||
  trim(process.env.NEXT_PUBLIC_PUBLIC_BASE_URL);

export const BACKEND_URL: string = fromEnv || "http://localhost:8001";

export const USE_MOCKS: boolean =
  (process.env.NEXT_PUBLIC_USE_MOCKS ?? "").toLowerCase() === "1" ||
  (process.env.NEXT_PUBLIC_USE_MOCKS ?? "").toLowerCase() === "true";

/**
 * Build a full URL against the backend, joining a path that may be
 * absolute (`http://...`) or relative (`/api/cameras`). Absolute URLs
 * pass through untouched so callers can reuse server-rendered links.
 */
export function backendUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const slash = path.startsWith("/") ? "" : "/";
  return `${BACKEND_URL}${slash}${path}`;
}
