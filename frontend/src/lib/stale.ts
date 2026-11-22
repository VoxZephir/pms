/** A tab left open across a new build still runs the old JS, and the old JS
 * asks for page chunks by their old hashed names -- gone with the build
 * (22.11: "Failed to fetch dynamically imported module …/Taxes-DDDi6SMu.js").
 * The fix is a reload, which fetches the new `index.html` (served
 * `no-cache`) and with it the new names. Done once: if the chunk is still
 * missing after a fresh load, the error is real and stays on screen. */

const KEY = "pms:stale-reload";
const AGAIN_AFTER_MS = 10_000;

export function isStaleBuild(error: unknown): boolean {
  const text = String((error as Error)?.message ?? error ?? "");
  return /dynamically imported module|Importing a module script failed|Unable to preload CSS/i.test(text);
}

/** Reload, unless one was just done for the same reason; true when it reloads. */
export function reloadOnce(): boolean {
  let last = 0;
  try { last = Number(sessionStorage.getItem(KEY) || 0); } catch { /* storage blocked */ }
  if (Date.now() - last < AGAIN_AFTER_MS) return false;
  try { sessionStorage.setItem(KEY, String(Date.now())); } catch { /* storage blocked */ }
  window.location.reload();
  return true;
}
