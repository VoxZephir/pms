/** One day as a page of its own: a shared link to `/jour/2026-10-14`. From
 * the app itself a day opens in a sheet over the page instead. */
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router";

import { PageHeader } from "@/components/PageState";
import { TxRow } from "@/components/TxList";
import { TxSheet } from "@/components/TxSheet";
import { ButtonLink, Callout, Card, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { chf, frLongDay, plural } from "@/lib/format";
import type { Tx } from "@/lib/types";

interface Day { date: string; rows: Tx[]; spending: number; income: number; prev: string | null; next: string | null }

export default function DayPage() {
  const { iso = "" } = useParams();
  const { data, isPending, error } = useApi<Day>(`/api/day/${iso}`);
  const [open, setOpen] = useState<Tx | null>(null);
  if (error) return <Callout tone="bad" title="Journée introuvable">{error.message}</Callout>;
  if (isPending || !data) return <Skeleton className="h-64 rounded-card" />;
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader title={<span className="first-letter:uppercase">{frLongDay(data.date)}</span>}
                  subtitle={`${chf(data.spending)} CHF dépensés${data.income ? ` · ${chf(data.income)} CHF encaissés` : ""} · ${plural(data.rows.length, "mouvement")}`}
                  actions={<>
                    {data.prev && <ButtonLink to={`/jour/${data.prev}`} size="sm"><ChevronLeft size={15} />Veille</ButtonLink>}
                    {data.next && <ButtonLink to={`/jour/${data.next}`} size="sm">Lendemain<ChevronRight size={15} /></ButtonLink>}
                  </>} />
      <Card className="divide-y divide-hairline px-3 py-1">
        {data.rows.length ? data.rows.map((t) => <TxRow key={t.key} tx={t} onOpen={setOpen} />)
          : <p className="py-8 text-center text-[14px] text-muted">Aucun mouvement ce jour-là.</p>}
      </Card>
      <TxSheet tx={open} onClose={() => setOpen(null)} />
    </div>
  );
}
