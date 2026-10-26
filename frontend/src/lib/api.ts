/** The one way the front end talks to Flask.
 *
 * Reads go through TanStack Query, keyed by path and query string, so a view
 * visited once comes back instantly and a hovered link can be prefetched.
 * Every write goes through `send`, which drops that whole cache: a view
 * fetched before a correction must never come back with its old figures. */
import { QueryClient, keepPreviousData, useQuery } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
      placeholderData: keepPreviousData,
    },
  },
});

export class ApiError extends Error {
  constructor(public status: number, message: string, public data?: unknown) {
    super(message);
  }
}

export function apiUrl(path: string, params?: URLSearchParams | string): string {
  const query = typeof params === "string" ? params : params?.toString() ?? "";
  return query ? `${path}?${query.replace(/^\?/, "")}` : path;
}

export async function getJSON<T>(path: string, params?: URLSearchParams | string): Promise<T> {
  const response = await fetch(apiUrl(path, params), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new ApiError(response.status, await errorText(response));
  return response.json() as Promise<T>;
}

export async function send<T = unknown>(
  path: string,
  body?: unknown,
  init: { method?: string; form?: FormData } = {},
): Promise<T> {
  const response = await fetch(path, {
    method: init.method ?? "POST",
    headers: init.form
      ? { Accept: "application/json" }
      : { "Content-Type": "application/json", Accept: "application/json" },
    body: init.form ?? (body === undefined ? undefined : JSON.stringify(body)),
  });
  await queryClient.invalidateQueries();
  if (!response.ok) {
    let data: unknown;
    try { data = await response.clone().json(); } catch { /* not JSON */ }
    throw new ApiError(response.status, await errorText(response), data);
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : {}) as T;
}

/** A POST that changes nothing a view shows -- a question to the model, a
 * preview -- so the cache is kept. Anything that writes goes through `send`. */
export async function post<T = unknown>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let data: unknown;
    try { data = await response.clone().json(); } catch { /* not JSON */ }
    throw new ApiError(response.status, await errorText(response), data);
  }
  return response.json() as Promise<T>;
}

async function errorText(response: Response): Promise<string> {
  try {
    const data = await response.clone().json();
    if (data && typeof data.error === "string") return data.error;
  } catch {
    /* not JSON */
  }
  return `${response.status} ${response.statusText}`;
}

/** A page's data, keyed by its query string. The previous view stays on
 * screen while the next one loads -- no flash of skeletons between periods. */
export function useApi<T>(path: string, params?: URLSearchParams | string, enabled = true) {
  const query = typeof params === "string" ? params : params?.toString() ?? "";
  return useQuery({
    queryKey: [path, query],
    queryFn: () => getJSON<T>(path, query),
    enabled,
  });
}

export function prefetch(path: string, params?: URLSearchParams | string): void {
  const query = typeof params === "string" ? params : params?.toString() ?? "";
  void queryClient.prefetchQuery({
    queryKey: [path, query],
    queryFn: () => getJSON(path, query),
  });
}
