/** "Mise à jour disponible": the commits waiting upstream, and one button
 * that pulls them and restarts the server (views/system.py, web/updates.py).
 * When there is nothing to install, the sidebar still says so -- and when
 * it was checked, and against which branch -- with a button to look again:
 * a notice that only ever appears reads as a missing feature. */
import { ArrowDownToLine, CheckCircle2, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button, cx } from "@/components/ui";
import { ApiError, getJSON, queryClient, send, useApi } from "@/lib/api";

interface UpdateState {
  available: boolean; behind?: number; changes?: string[]; dependencies?: boolean; reason?: string;
  branch?: string; checked?: number;
}

function ago(seconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - seconds);
  if (s < 90) return "à l'instant";
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  return `il y a ${Math.round(s / 3600)} h`;
}

/** Up to date, or why it could not tell -- and a button to look again now. */
function UpdateStatus({ data }: { data?: UpdateState }) {
  const [busy, setBusy] = useState(false);
  if (!data || data.reason === "off") return null;
  const again = async () => {
    setBusy(true);
    try {
      const fresh = await getJSON<UpdateState>("/api/update", "force=1");
      queryClient.setQueryData(["/api/update", ""], fresh);
      if (!fresh.available) toast(fresh.reason ? "Vérification impossible" : "L'app est à jour", { description: fresh.reason });
    } catch (e) {
      toast.error("La vérification a échoué", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mb-2 flex items-start gap-2 px-3 text-[12px] text-muted">
      {data.reason ? <RefreshCw size={13} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-good" />}
      <span className="min-w-0 flex-1">
        {data.reason ? <>Mises à jour : {data.reason}</> : <>À jour{data.checked ? ` · vérifié ${ago(data.checked)}` : ""}</>}
        {data.branch && <span className="block truncate" title={data.branch}>{data.branch}</span>}
      </span>
      <button type="button" onClick={again} disabled={busy} className="shrink-0 font-medium text-ink-2 hover:text-ink disabled:opacity-50">
        {busy ? "…" : "Vérifier"}
      </button>
    </div>
  );
}

// Set just before the reload that loads the new code, read once after it:
// the toast that says the update went through outlives the page.
const DONE_KEY = "pms-update-done";

/** Wait for the restarted server (a new pid), then load the new code. */
async function reloadWhenBack(pid: number) {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 700));
    try {
      const h = await getJSON<{ pid: number }>("/api/health", "");
      if (h.pid !== pid) {
        try { sessionStorage.setItem(DONE_KEY, "1"); } catch { /* private window */ }
        window.location.reload();
        return;
      }
    } catch { /* still restarting */ }
  }
  toast.error("Le serveur ne revient pas", { description: "Relancer run.bat." });
}

function announceDone() {
  try {
    if (sessionStorage.getItem(DONE_KEY)) {
      sessionStorage.removeItem(DONE_KEY);
      toast.success("Mise à jour installée", { description: "L'app tourne sur la nouvelle version." });
    }
  } catch { /* storage blocked: nothing to announce */ }
}
announceDone();

export function UpdateNotice({ compact }: { compact?: boolean }) {
  const { data } = useApi<UpdateState>("/api/update");
  const [busy, setBusy] = useState(false);
  if (!data?.available) return compact ? <UpdateStatus data={data} /> : null;
  const install = async () => {
    setBusy(true);
    const id = toast.loading("Mise à jour…");
    // The pid before the pull: the pull rewrites the code, and the reloader
    // may stop the server before it answers -- a dropped connection, then a
    // new pid, is a restart, not a failure.
    let pid: number | null = null;
    try { pid = (await getJSON<{ pid: number }>("/api/health", "")).pid; } catch { /* asked again below */ }
    try {
      const r = await send<{ pulled: number; dependencies: boolean; restarting: boolean; pid: number }>("/api/update", {});
      if (r.restarting) {
        toast.loading("Redémarrage…", { id });
        await reloadWhenBack(r.pid);
      } else {
        toast.success("Code à jour", {
          id, duration: 15000,
          description: r.dependencies ? "De nouvelles dépendances : fermer la fenêtre de l'app et relancer run.bat pour finir."
            : "Relancer run.bat pour en profiter.",
        });
        setBusy(false);
      }
    } catch (e) {
      if (!(e instanceof ApiError) && pid != null) {
        toast.loading("Redémarrage…", { id });
        await reloadWhenBack(pid);
        return;
      }
      toast.error("La mise à jour n'a pas pu se faire", { id, description: (e as Error).message });
      setBusy(false);
    }
  };
  const n = data.behind ?? 0;
  return (
    <div className={cx("rounded-xl border border-[color-mix(in_srgb,var(--good)_30%,transparent)] bg-[color-mix(in_srgb,var(--good)_7%,transparent)] text-ink-2",
      compact ? "mb-2 px-3 py-2 text-[12.5px]" : "px-4 py-3 text-[13.5px]")}>
      <b className="text-ink">Mise à jour disponible</b> · {n} changement{n > 1 ? "s" : ""}
      <ul className={cx("mt-1 list-disc pl-4", compact && "line-clamp-3")}>
        {(data.changes ?? []).slice(0, compact ? 3 : 8).map((c, i) => <li key={i} className="truncate">{c}</li>)}
      </ul>
      {data.dependencies && <p className="mt-1 text-muted">Avec de nouvelles dépendances : relancer run.bat ensuite.</p>}
      <Button size="sm" className="mt-2" onClick={install} disabled={busy}>
        <ArrowDownToLine size={14} />{busy ? "Mise à jour…" : "Mettre à jour"}
      </Button>
    </div>
  );
}
