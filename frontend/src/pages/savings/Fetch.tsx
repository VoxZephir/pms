/** "Rafraîchir": IBKR, the indices, the inflation and the crypto fetched
 * again (`refresh.py`), the run run.bat does once a day, on demand. The run
 * goes on in the server; this asks how it is going, then reloads the
 * figures. Each source says its outcome in the console's own words. */
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, CircleMinus, LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button, cx } from "@/components/ui";
import { getJSON, queryClient, send } from "@/lib/api";
import { frDate } from "@/lib/format";

interface Step { name: string; ok: boolean | null; said: string[]; seconds: number }
interface FetchState {
  running: boolean; started: string | null; error: string; due: boolean;
  at: string | null; last: null | { at: string; steps: Step[] };
}

const when = (iso: string | null) => (iso ? `${frDate(iso).slice(0, 5)} à ${iso.slice(11, 16)}` : "jamais");

export function FetchButton() {
  const [open, setOpen] = useState(false);
  const { data, refetch } = useQuery({
    queryKey: ["/api/fetch", ""],
    queryFn: () => getJSON<FetchState>("/api/fetch"),
    // Asked again while a run is on, not otherwise.
    refetchInterval: (q) => (q.state.data?.running ? 1500 : false),
    staleTime: 0,
  });
  const was = useRef(false);
  useEffect(() => {
    if (!data) return;
    if (was.current && !data.running) {
      // The run just ended: every view reads the new files.
      void queryClient.invalidateQueries();
      const failed = data.last?.steps.filter((s) => s.ok === false) ?? [];
      if (data.error) toast.error("Le rafraîchissement a échoué", { description: data.error });
      else if (failed.length) toast.warning(`Rafraîchi, sauf ${failed.map((s) => s.name).join(", ")}`, { description: "Le détail est sous le bouton." });
      else toast.success("Cours, IBKR et inflation à jour");
      setOpen(true);
    }
    was.current = data.running;
  }, [data]);

  const start = async () => {
    await send("/api/fetch");
    was.current = true;
    void refetch();
  };
  const running = !!data?.running;
  const steps = data?.last?.steps ?? [];
  return (
    <div className="relative">
      <div className="flex items-center gap-1.5">
        <Button size="sm" onClick={() => void start()} disabled={running}
                title="IBKR (Flex), les indices de référence et ceux du 3a, l'inflation, la crypto">
          {running ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {running ? "Rafraîchissement…" : "Rafraîchir"}
        </Button>
        {steps.length > 0 && (
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
                  className={cx("rounded-lg px-1.5 py-1 text-[12px] transition hover:bg-surface-2",
                    steps.some((s) => s.ok === false) ? "text-warn" : "text-muted")}>
            {running ? "en cours" : `le ${when(data?.last?.at ?? null)}`}
          </button>
        )}
      </div>
      {open && steps.length > 0 && (
        <div className="absolute right-0 z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-hairline bg-surface p-3 shadow-lg">
          <ul className="space-y-2.5">
            {steps.map((s) => (
              <li key={s.name} className="flex gap-2 text-[12.5px]">
                {s.ok === true ? <CheckCircle2 size={15} className="mt-px shrink-0 text-good" />
                  : s.ok === false ? <CircleAlert size={15} className="mt-px shrink-0 text-warn" />
                  : <CircleMinus size={15} className="mt-px shrink-0 text-muted" />}
                <div className="min-w-0">
                  <div className="font-medium">{s.name}{s.seconds >= 1 && <span className="font-normal text-muted"> · {Math.round(s.seconds)} s</span>}</div>
                  {s.said.map((line, i) => <div key={i} className="break-words text-muted">{line}</div>)}
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 border-t border-hairline pt-2 text-[11.5px] text-muted">
            Tout à jour pour la dernière fois le {when(data?.at ?? null)}. run.bat le refait chaque jour au lancement.
          </p>
        </div>
      )}
    </div>
  );
}
