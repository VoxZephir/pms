/** The savings in words, on the savings page. */
import { Sparkles } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui";
import { send, useApi } from "@/lib/api";
import { useView } from "@/lib/url";
import { useAi, AiBadge, Figures, Sources, aiBox, failed } from "./common";

/** What moved the savings over the window -- the money put in against what
 * the markets did, and which pocket carried it -- from the pocket table's
 * own figures. On the savings page, under the headline. */
export function SavingsAssist() {
  const ai = useAi();
  const { query } = useView();
  const { data } = useApi<{ answer: { text: string } | null }>("/api/ai/savings", query, !!ai?.enabled);
  const [busy, setBusy] = useState(false);
  if (!ai?.enabled || !data) return null;
  const ask = async (again = false) => {
    setBusy(true);
    try {
      await send(`/api/ai/savings?${query}`, { again });
    } catch (e) {
      failed("L'explication n'a pas pu être écrite", e);
    } finally {
      setBusy(false);
    }
  };
  if (!data.answer) {
    return (
      <Button size="sm" onClick={() => ask()} disabled={busy}>
        <Sparkles size={14} />{busy ? "Analyse…" : "Expliquer la période"}
      </Button>
    );
  }
  return (
    <div className={aiBox}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold">Ce qui a fait bouger l'épargne</h3>
        <AiBadge>explication</AiBadge>
      </div>
      <p className="text-[14.5px] leading-relaxed"><Figures text={data.answer.text} /></p>
      <Sources items={["valeurs et versements de chaque poche", "rendement TWR, versements retirés"]} />
      <div className="mt-2.5">
        <Button size="sm" onClick={() => ask(true)} disabled={busy}>{busy ? "Réécriture…" : "Réécrire"}</Button>
      </div>
    </div>
  );
}
