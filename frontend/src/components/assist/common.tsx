/** Shared by every assisted block: whether a model is on, the badge, the
 * figures set in bold, the sources under a card, the box they sit in. */
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Note } from "@/components/ui";
import { useApi } from "@/lib/api";

export interface AiStatus { enabled: boolean; reason?: string; label?: string; model?: string; local?: boolean }

export function useAi(): AiStatus | undefined {
  return useApi<AiStatus>("/api/ai").data;
}

export function AiBadge({ children = "IA" }: { children?: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--s6)_12%,transparent)] px-2 py-0.5 text-[11.5px] font-semibold text-s6">
      <Sparkles size={11} aria-hidden />{children}
    </span>
  );
}

/** The model's sentence with its figures set in bold: every number in it
 * was checked against what the app computed, and they are what the eye
 * looks for. */
export function Figures({ text, className, source = "calculé par l'app, vérifié dans la réponse" }: {
  text: string; className?: string; source?: string;
}) {
  const parts = text.split(/([+−-]?\d{1,3}(?:['’]\d{3})+(?:\.\d+)?(?:\s?(?:CHF|%))?|[+−-]?\d+(?:\.\d+)?\s?(?:CHF|%))/g);
  return (
    <span className={className}>
      {parts.map((p, i) => (i % 2
        ? <b key={i} title={source} className="num cursor-help border-b border-dotted border-muted font-semibold text-ink">{p}</b>
        : p))}
    </span>
  );
}

/** Where the numbers of a card come from, as small chips under it. */
export function Sources({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-1.5">
      {items.map((x) => <span key={x} className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted">{x}</span>)}
    </div>
  );
}

/** A per-viewer convenience, never a decision: kept in this browser only. */
export function useLocalFlag(key: string): [boolean, (v: boolean) => void] {
  const read = () => { try { return localStorage.getItem(key) === "1"; } catch { return false; } };
  const [value, setValue] = useState(read);
  const set = (v: boolean) => {
    setValue(v);
    try { if (v) localStorage.setItem(key, "1"); else localStorage.removeItem(key); } catch { /* private mode */ }
  };
  return [value, set];
}

export const aiBox = "rounded-2xl border border-[color-mix(in_srgb,var(--s6)_25%,transparent)] bg-[color-mix(in_srgb,var(--s6)_6%,var(--surface))] p-3.5";

export function failed(title: string, e: unknown) {
  toast.error(title, { description: (e as Error).message });
}

/** Which model, or why none: on the Corrections page, where the assisted
 * classification lives. */
export function AiStatusNote({ status }: { status?: AiStatus }) {
  if (!status) return null;
  return (
    <Note className="px-1">
      {status.enabled
        ? <>Assistant : {status.label} ({status.model}){status.local ? ", sur ce PC" : ""}. Ce qui lui est envoyé est noté dans <code>data/ai_log.jsonl</code> ; les noms de personnes partent masqués.</>
        : <>Assistant éteint : il se choisit dans la page <Link to="/assistant" className="underline underline-offset-2">Assistant</Link>.</>}
    </Note>
  );
}
