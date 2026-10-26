/** Send a statement from the phone (or this PC): it is read at once, filed in
 * inbox/, and joins the ledger -- or is turned away with the reason. */
import { CheckCircle2, FileUp, FolderDown, LoaderCircle } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { PageHeader } from "@/components/PageState";
import { Table } from "@/components/Table";
import { Button, Callout, Card, Panel, cx } from "@/components/ui";
import { ApiError, send, useApi } from "@/lib/api";
import { frDate, plural } from "@/lib/format";

interface Imports {
  imports: { file: string; account: string; ingested: string | null; until: string | null; added: number | null }[];
  kinds: { label: string; suffix: string }[];
  accept: string;
  watcher: null | { folder: string; last_scan: string | null; events: { file: string; at: string; ok: boolean; known?: boolean; added?: number; error?: string }[] };
}

export default function UploadPage() {
  const { data } = useApi<Imports>("/api/imports");
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<null | { file: string; added: number; known: boolean }>(null);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("releve", file);
    try {
      const r = await send<{ file: string; added: number; known: boolean }>("/api/import", undefined, { form });
      setDone(r);
      setFile(null);
      if (input.current) input.current.value = "";
      toast.success(r.known ? "Déjà importé" : `${plural(r.added, "mouvement")} ajouté${r.added > 1 ? "s" : ""}`, { description: r.file });
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) { setFile(f); setDone(null); setError(""); }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Importer un relevé" subtitle="depuis le téléphone comme depuis ce PC" />
      <div className="space-y-4 sm:space-y-5">
        {done && (
          <Callout tone="good" icon={<CheckCircle2 size={18} className="text-good" />}
                   title={done.known ? `${done.file} était déjà importé` : done.added ? `${plural(done.added, "mouvement")} ajouté${done.added > 1 ? "s" : ""}` : `${done.file} lu`}
                   action={<Link to="/" className="text-[13px] font-medium text-ink">Tableau de bord →</Link>}>
            {done.known ? "Rien de nouveau." : done.added ? done.file : "Tous ses mouvements étaient déjà connus."}
          </Callout>
        )}
        <Card className="p-4 sm:p-5">
          <label
            onDragOver={(e) => { e.preventDefault(); setOver(true); }}
            onDragLeave={() => setOver(false)}
            onDrop={drop}
            className={cx(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-4 py-10 text-center transition",
              over ? "border-accent bg-[color-mix(in_srgb,var(--s0)_6%,transparent)]" : "border-hairline-2 hover:bg-surface-2/50",
              error && "border-critical",
            )}>
            <FileUp size={28} className="text-muted" />
            <span className="text-[15px] font-semibold">{file ? file.name : "Choisir un relevé"}</span>
            <span className="text-[12.5px] text-muted">
              {file ? `${(file.size / 1024).toFixed(0)} Ko` : "ou le déposer ici"} · {data?.kinds.map((k) => `${k.label} (${k.suffix})`).join(", ")}
            </span>
            <input ref={input} type="file" accept={data?.accept} className="sr-only" aria-invalid={!!error}
                   onChange={(e) => { setFile(e.target.files?.[0] ?? null); setDone(null); setError(""); }} />
          </label>
          {error && <p role="alert" className="mt-3 text-[13.5px] text-critical">{error}</p>}
          <Button variant="primary" size="lg" className="mt-4 w-full" disabled={!file || busy} onClick={upload}>
            {busy ? <><LoaderCircle size={17} className="animate-spin" />Lecture…</> : "Importer"}
          </Button>
          <p className="mt-3 text-[12.5px] text-muted">Il est lu tout de suite et rangé dans <code>inbox/</code> ; un fichier déjà importé n'ajoute rien. Un relevé de deux ans se lit en une quinzaine de secondes.</p>
        </Card>

        {data?.watcher && (
          <Panel title="Téléchargements du PC" hint={`dernier passage ${data.watcher.last_scan ? data.watcher.last_scan.slice(11, 16) : "—"}`}>
            <p className="flex gap-2 text-[13.5px] text-ink-2"><FolderDown size={17} className="shrink-0 text-muted" />
              Un relevé téléchargé dans <code className="break-all">{data.watcher.folder}</code> est reconnu à son contenu, ingéré dans la minute, puis retiré du dossier.</p>
            {data.watcher.events.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-[13px]">
                {data.watcher.events.map((e, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="num shrink-0 text-muted">{frDate(e.at).slice(0, 5)} {e.at.slice(11, 16)}</span>
                    <span className="min-w-0"><b>{e.file || "Surveillance"}</b> : {e.ok
                      ? (e.known ? "déjà importé" : `${plural(e.added ?? 0, "mouvement")} ajouté${(e.added ?? 0) > 1 ? "s" : ""}`)
                      : <span className="text-critical">{e.error}</span>}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}

        {data && data.imports.length > 0 && (
          <Panel title="Derniers imports">
            <Table rows={data.imports} rowKey={(r, i) => `${r.file}-${i}`} sortable={false}
                   cols={[
                     { key: "file", label: "Fichier", render: (r) => <span className="break-all">{r.file}{r.account && <span className="text-muted"> · {r.account}</span>}</span> },
                     { key: "ingested", label: "Importé le", render: (r) => <span className="num">{frDate(r.ingested) || "—"}</span> },
                     { key: "until", label: "Jusqu'au", render: (r) => <span className="num">{frDate(r.until) || "—"}</span> },
                     { key: "added", label: "Ajoutés", numeric: true, render: (r) => r.added ?? "—" },
                   ]} />
          </Panel>
        )}
      </div>
    </div>
  );
}
