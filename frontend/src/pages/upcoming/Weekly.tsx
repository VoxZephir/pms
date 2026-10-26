/** The weekly summary: the message as the phone will show it, and the
 * settings that push it there every week through ntfy (`notify.py`). */
import { BellRing, Copy, RefreshCw, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Field, Input, Select } from "@/components/Form";
import { Button, Callout, Note, Panel, cx } from "@/components/ui";
import { ApiError, send, useApi } from "@/lib/api";
import { frDate } from "@/lib/format";

interface Settings {
  enabled: boolean; server: string; topic: string; weekday: number; hour: number;
  app_url: string; last_sent: string | null; last_error: string | null;
  next: string | null; weekdays: string[];
}
interface WeeklyData { empty?: boolean; summary: { title: string; lines: string[] }; settings: Settings }

function when(iso: string | null) {
  if (!iso) return "";
  return `${frDate(iso)} à ${iso.slice(11, 16)}`;
}

export function Weekly() {
  const { data } = useApi<WeeklyData>("/api/semaine");
  if (!data || data.empty) return null;
  return (
    <Panel id="p-weekly" title="Le résumé de la semaine" hint="ce que le téléphone reçoit chaque semaine : catégories et montants, jamais un nom">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Preview title={data.summary.title} lines={data.summary.lines} />
        <SettingsForm s={data.settings} />
      </div>
    </Panel>
  );
}

function Preview({ title, lines }: { title: string; lines: string[] }) {
  return (
    <div className="min-w-0">
      <div className="eyebrow mb-2">Aperçu</div>
      <div className="rounded-[20px] border border-hairline bg-[color-mix(in_srgb,var(--surface-2)_70%,var(--surface))] p-3.5 shadow-[var(--shadow-sm)]">
        <div className="flex items-center gap-2 text-[11.5px] text-muted">
          <span className="grid size-5 place-items-center rounded-md bg-ink text-[10px] font-bold text-page">P</span>
          ntfy · PMS <span className="ml-auto">maintenant</span>
        </div>
        <div className="mt-1.5 text-[14px] font-semibold">{title}</div>
        <div className="mt-0.5 space-y-1 text-[13px] leading-snug text-ink-2">
          {lines.map((l) => <p key={l}>{l}</p>)}
        </div>
      </div>
    </div>
  );
}

function SettingsForm({ s }: { s: Settings }) {
  const [enabled, setEnabled] = useState(s.enabled);
  const [weekday, setWeekday] = useState(s.weekday);
  const [hour, setHour] = useState(s.hour);
  const [server, setServer] = useState(s.server);
  const [err, setErr] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const dirty = enabled !== s.enabled || weekday !== s.weekday || hour !== s.hour || server !== s.server;

  const run = async (body: object, ok: string) => {
    setBusy(true); setErr(undefined);
    try { await send("/api/semaine", body); toast(ok); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(s.topic); toast("Sujet copié"); }
    catch { toast("Copie impossible : sélectionne le sujet à la main"); }
  };

  return (
    <form className="min-w-0 space-y-4" onSubmit={(e) => { e.preventDefault(); run({ action: "save", enabled, weekday, hour, server }, enabled ? "Résumé programmé" : "Résumé arrêté"); }}>
      <label className="flex cursor-pointer items-center gap-3">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="size-5 accent-[var(--ink)]" />
        <span className="text-[14px] font-medium">Recevoir le résumé sur le téléphone</span>
      </label>
      <div className={cx("grid grid-cols-2 gap-3 transition-opacity", !enabled && "opacity-50")}>
        <Field label="Le">{(id) => (
          <Select id={id} value={weekday} onChange={(e) => setWeekday(Number(e.target.value))} disabled={!enabled}>
            {s.weekdays.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </Select>
        )}</Field>
        <Field label="À">{(id) => (
          <Select id={id} value={hour} onChange={(e) => setHour(Number(e.target.value))} disabled={!enabled}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")} h</option>)}
          </Select>
        )}</Field>
      </div>
      <Field label="Serveur ntfy" hint="ntfy.sh par défaut ; un serveur à toi sur le tailnet garde les messages chez toi." error={err}>
        {(id, describedBy) => <Input id={id} aria-describedby={describedBy} value={server} onChange={(e) => setServer(e.target.value)} disabled={!enabled} />}
      </Field>
      {s.topic && (
        <div className="rounded-2xl border border-hairline p-3.5 text-[13px]">
          <div className="eyebrow mb-1.5">Sur le téléphone</div>
          <ol className="list-decimal space-y-1 pl-4 text-ink-2">
            <li>Installe l'app <b>ntfy</b> (App Store, Google Play ou F-Droid).</li>
            <li>« S'abonner à un sujet », serveur <span className="num">{s.server.replace(/^https?:\/\//, "")}</span>, sujet :</li>
          </ol>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-surface-2 px-2.5 py-1.5 text-[13px]">{s.topic}</code>
            <Button type="button" size="sm" variant="ghost" onClick={copy} aria-label="Copier le sujet"><Copy size={14} /></Button>
            <Button type="button" size="sm" variant="ghost" disabled={busy} aria-label="Tirer un nouveau sujet"
                    onClick={() => run({ action: "topic" }, "Nouveau sujet : réabonne le téléphone")}><RefreshCw size={14} /></Button>
          </div>
          <p className="mt-2 text-[12px] text-muted">Le sujet est le seul secret : qui le connaît lit les résumés. Un nouveau sujet coupe l'ancien.</p>
        </div>
      )}
      {s.last_error && <Callout tone="warn" title="Le dernier envoi a échoué">{s.last_error}</Callout>}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary" disabled={!dirty || busy}><BellRing size={15} />Enregistrer</Button>
        {s.topic && <Button type="button" variant="secondary" disabled={busy} onClick={() => run({ action: "test" }, "Résumé envoyé")}><Send size={15} />Envoyer maintenant</Button>}
      </div>
      <Note className="mt-0">
        {s.enabled && s.next ? <>Prochain envoi le {when(s.next)}. </> : null}
        {s.last_sent ? <>Dernier envoi le {when(s.last_sent)}. </> : null}
        Le serveur ntfy voit passer le texte : des catégories et des montants, aucun nom ni IBAN.
      </Note>
    </form>
  );
}
