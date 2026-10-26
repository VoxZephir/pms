/** The URL is the state: a window, a grain, a few view switches.
 *
 * No store, no session -- `?from=&to=&grain=` and friends determine a view
 * entirely, so every view is a link, the back button works, and a reload
 * lands where it was. These helpers build the next URL from the current one,
 * carrying along only the keys that should ride (never page-only keys). */
import { useCallback, useMemo } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";

/** The window: carried from page to page, like `page_url` did. */
export const WINDOW_KEYS = ["from", "to", "grain", "preset"] as const;

/** Dashboard and savings view switches: carried across period changes. */
export const VIEW_KEYS = [
  "stack", "split", "scale", "focus", "perf", "rate", "stats", "bench", "shares", "smooth", "titres",
] as const;

/** The table's filters: carried only within the transactions views. */
export const TABLE_KEYS = ["q", "category", "bucket", "dir", "sort", "dir_sort", "per", "amin", "amax", "fix", "todo", "acct"] as const;

export type Patch = Record<string, string | number | null | undefined>;

/** `current` with `patch` applied, keeping only `keep`. A window given as
 * dates drops the preset, and a preset drops the dates: the two never
 * disagree in one URL. */
export function nextParams(
  current: URLSearchParams,
  patch: Patch,
  keep: readonly string[] = [...WINDOW_KEYS, ...VIEW_KEYS],
): URLSearchParams {
  const out = new URLSearchParams();
  for (const key of keep) {
    for (const value of current.getAll(key)) out.append(key, value);
  }
  if ("from" in patch || "to" in patch) out.delete("preset");
  if ("preset" in patch && patch.preset) {
    out.delete("from");
    out.delete("to");
  }
  for (const [key, value] of Object.entries(patch)) {
    out.delete(key);
    if (value !== null && value !== undefined && value !== "") out.set(key, String(value));
  }
  return out;
}

export function withQuery(path: string, params: URLSearchParams): string {
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

/** Read the current view and build links from it. */
export function useView() {
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();

  /** A link on this page with `patch` applied. */
  const href = useCallback(
    (patch: Patch, opts: { path?: string; keep?: readonly string[] } = {}) =>
      withQuery(opts.path ?? location.pathname, nextParams(params, patch, opts.keep)),
    [params, location.pathname],
  );

  /** A link to another page, the window riding along. */
  const pageHref = useCallback(
    (path: string, patch: Patch = {}) =>
      withQuery(path, nextParams(params, patch, WINDOW_KEYS)),
    [params],
  );

  const go = useCallback(
    (patch: Patch, opts: { path?: string; keep?: readonly string[]; replace?: boolean } = {}) =>
      navigate(href(patch, opts), { replace: opts.replace, preventScrollReset: true }),
    [navigate, href],
  );

  const query = useMemo(() => params.toString(), [params]);
  return { params, query, href, pageHref, go, navigate, pathname: location.pathname };
}

/** The window of a period as URL params, its grain left to the server's
 * automatic pick unless given. */
export function windowPatch(start: string, end: string, grain: string | null = "auto"): Patch {
  return { from: start, to: end, grain, preset: null };
}
