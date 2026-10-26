/** Redact a PDF before sending it: IBANs, names and addresses leave the file
 * itself (`redact.py`, `docs/caviardage.md`). The original only passes
 * through; the copy is downloaded from here. */
import { CheckCircle2, Download, EyeOff, FileUp, LoaderCircle } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { PageHeader } from "@/components/PageState";
import { Button, Callout, Card, Panel, cx } from "@/components/ui";
import { ApiError, send, useApi } from "@/lib/api";
import { frDate, plural } from "@/lib/format";

interface State {
  available: boolean;
  folder: string;
  copies: { file: string; size: number; at: string; url: string }[];
}
interface Result {
  file: string; url: string; pages: number; count: number;
  kinds: { kind: string; count: number }[]; names: string[];
}

export default function RedactPage() {
  const { data } = useApi<State>("/api/caviarder");
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [also, setAlso] = useState("");
  const [spare, setSpare] = useState("");
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<Result | null>(null);

  const pick = (f: File | null) => { setFile(f); setDone(null); setError(""); };
  const run = async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    const form = new FormData();
    form.append("pdf", file);
    form.append("also", also);
    form.append("spare", spare);
    try {
      setDone(await send<Result>("/api/caviarder", undefined, { form }));
      setFile(null);
      if (input.current) input.current.value = "";
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
    if (f) pick(f);
  };

  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title="Caviarder un PDF" subtitle="IBAN, noms et adresses retirés du fichier, pas cachés" />
      <div className="space-y-4 sm:space-y-5">
        {data && !data.available && (
          <Callout tone="bad" title="PyMuPDF n'est pas installé">
            Lancer <code>caviarder.bat</code> une fois (ou <code>uv sync --extra web --inexact</code>), puis recharger la page.
          </Callout>
        )}
        {done && (
          <Callout tone="good" icon={<CheckCircle2 size={18} className="text-good" />}
                   title={done.count ? `${plural(done.count, "passage")} retiré${done.count > 1 ? "s" : ""}` : "Rien trouvé à retirer"}>
            <span className="break-all">{done.file}</span> · {plural(done.pages, "page")}
            {done.kinds.length > 0 && <> · {done.kinds.map((k) => `${k.count} ${k.kind}`).join(", ")}</>}
            {done.names.length > 0 && (
              <span className="mt-1 block text-[12.5px] text-muted">dont {done.names.slice(0, 12).join(", ")}{done.names.length > 12 ? ` et ${done.names.length - 12} autre(s)` : ""}</span>
            )}
            <span className="mt-1 block text-[12.5px] text-muted">Relu après coup : aucun passage retiré n'est encore lisible. Parcourir le PDF avant de l'envoyer reste la dernière vérification.</span>
            <a href={done.url} download
               className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-hairline-2 bg-surface text-[14px] font-medium text-ink no-underline transition hover:bg-surface-2 sm:w-auto sm:px-4">
              <Download size={16} />Télécharger la copie caviardée
            </a>
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
            {file ? <FileUp size={28} className="text-muted" /> : <EyeOff size={28} className="text-muted" />}
            <span className="text-[15px] font-semibold break-all">{file ? file.name : "Choisir un PDF"}</span>
            <span className="text-[12.5px] text-muted">{file ? `${(file.size / 1024).toFixed(0)} Ko` : "ou le déposer ici"}</span>
            <input ref={input} type="file" accept=".pdf,application/pdf" className="sr-only" aria-invalid={!!error}
                   onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          </label>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-[12.5px] font-medium text-ink-2">Retirer aussi</span>
              <textarea value={also} onChange={(e) => setAlso(e.target.value)} rows={3} placeholder={"Un nom par ligne\nou séparés par des virgules"}
                        className="mt-1 block min-h-[5.5rem] w-full resize-y rounded-xl border border-hairline-2 bg-surface px-3 py-2 text-[16px] text-ink outline-none transition focus:border-accent sm:text-[14px]" />
            </label>
            <label className="block">
              <span className="text-[12.5px] font-medium text-ink-2">Laisser</span>
              <textarea value={spare} onChange={(e) => setSpare(e.target.value)} rows={3} placeholder={"Swissquote\nUBS"}
                        className="mt-1 block min-h-[5.5rem] w-full resize-y rounded-xl border border-hairline-2 bg-surface px-3 py-2 text-[16px] text-ink outline-none transition focus:border-accent sm:text-[14px]" />
            </label>
          </div>
          {error && <p role="alert" className="mt-3 text-[13.5px] text-critical">{error}</p>}
          <Button variant="primary" size="lg" className="mt-4 w-full" disabled={!file || busy || data?.available === false} onClick={run}>
            {busy ? <><LoaderCircle size={17} className="animate-spin" />Caviardage…</> : "Caviarder"}
          </Button>
          <p className="mt-3 text-[12.5px] text-muted">
            Retirés : les IBAN (vérifiés par leur clé) et le numéro de client ; sur un relevé que PMS lit, le titulaire et la contrepartie de chaque virement — les commerces payés par carte restent ; dans tout PDF, un prénom courant à côté d'un nom, un nom après M., Mme, Herr…, une adresse, et les noms de tes règles personnelles. Dans les deux champs, un terme par ligne, ou séparés par des virgules ou des points-virgules.
          </p>
        </Card>

        {data && data.copies.length > 0 && (
          <Panel title="Copies caviardées" hint={data.folder}>
            <ul className="divide-y divide-hairline text-[13.5px]">
              {data.copies.map((c) => (
                <li key={c.file} className="flex items-center gap-3 py-2">
                  <span className="min-w-0 flex-1 break-all">{c.file}</span>
                  <span className="num shrink-0 text-[12px] text-muted">{frDate(c.at)} · {(c.size / 1024).toFixed(0)} Ko</span>
                  <a href={c.url} download aria-label={`Télécharger ${c.file}`} className="shrink-0 rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-ink"><Download size={15} /></a>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    </div>
  );
}
