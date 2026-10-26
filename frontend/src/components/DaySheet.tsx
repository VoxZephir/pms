/** One day, opened from a calendar cell or a day column, without leaving
 * the page: its movements in statement order, and a step to the next. */
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { useApi } from "@/lib/api";
import { chf, frLongDay } from "@/lib/format";
import type { CategoryRow, Tx } from "@/lib/types";

import { Sheet } from "./Sheet";
import { TxRow } from "./TxList";
import { TxSheet } from "./TxSheet";
import { Button, Skeleton } from "./ui";

interface Day {
  date: string;
  rows: Tx[];
  spending: number;
  income: number;
  categories: CategoryRow[];
  prev: string | null;
  next: string | null;
}

export function DaySheet({ day, onChange }: { day: string | null; onChange: (day: string | null) => void }) {
  const { data, isFetching } = useApi<Day>(`/api/day/${day}`, undefined, !!day);
  const [open, setOpen] = useState<Tx | null>(null);
  const shown = data && data.date === day ? data : null;
  return (
    <>
      <Sheet open={!!day && !open} onOpenChange={(o) => !o && onChange(null)}
             title={day ? <span className="first-letter:uppercase">{frLongDay(day)}</span> : ""}
             description={shown ? `${chf(shown.spending)} CHF dépensés${shown.income ? ` · ${chf(shown.income)} CHF encaissés` : ""} · ${shown.rows.length} mouvement${shown.rows.length > 1 ? "s" : ""}` : " "}
             footer={
               <div className="flex items-center justify-between gap-2">
                 <Button size="sm" variant="ghost" disabled={!data?.prev || isFetching} onClick={() => data?.prev && onChange(data.prev)}>
                   <ChevronLeft size={15} /> Veille
                 </Button>
                 <Button size="sm" variant="ghost" disabled={!data?.next || isFetching} onClick={() => data?.next && onChange(data.next)}>
                   Lendemain <ChevronRight size={15} />
                 </Button>
               </div>
             }>
        {!shown ? (
          <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : shown.rows.length === 0 ? (
          <p className="py-6 text-center text-[14px] text-muted">Aucun mouvement ce jour-là.</p>
        ) : (
          <div className="divide-y divide-hairline">
            {shown.rows.map((t) => <TxRow key={t.key} tx={t} onOpen={setOpen} />)}
          </div>
        )}
      </Sheet>
      <TxSheet tx={open} onClose={() => setOpen(null)} />
    </>
  );
}
