/** Spending per period, stacked by category or by need / want / save, the
 * income as a marker over each column. A column opens one level deeper;
 * a sideways drag selects a range. */
import { Columns, type Column } from "@/charts/Columns";
import { useAi } from "@/components/Assist";
import { Button, Dot, Panel, Segmented } from "@/components/ui";
import { bucketLabel, chf, compact } from "@/lib/format";
import type { Dashboard, SeriesRow } from "@/lib/types";
import { useView, windowPatch } from "@/lib/url";

const OTHER = "Autres";

function short(row: SeriesRow, grain: string): string {
  if (grain === "day") {
    const d = Number(row.start.slice(8, 10));
    return d === 1 ? row.label : String(d);
  }
  if (grain === "week") return row.label.split(" · ")[0];
  return row.label;
}

export function Timeline({ data, onDay }: { data: Dashboard; onDay: (iso: string) => void }) {
  const { href, go } = useView();
  const t = data.timeline;
  const grain = data.period.grain;
  const incomeMarker = grain === "month" || grain === "year";
  const byBucket = t.stack === "bucket";
  const ai = useAi();
  // E, as sketched: under the months, the dearest one and its "why".
  const dearest = grain === "month" && t.rows.length >= 2
    ? t.rows.reduce((a, r) => (r.spending > a.spending ? r : a), t.rows[0]) : null;
  const named = new Set(data.legend.filter((l) => l.name !== OTHER).map((l) => l.name));
  const slotOf = Object.fromEntries(data.legend.map((l) => [l.name, l.slot]));

  const columns: Column[] = t.rows.map((r) => {
    let segments;
    if (byBucket) {
      segments = Object.entries(r.buckets).map(([name, value]) => ({
        name: bucketLabel(name), value, color: data.bucket_fill[name] ?? "var(--unsorted)",
      }));
    } else {
      const folded: Record<string, number> = {};
      for (const [name, value] of Object.entries(r.categories)) {
        const k = named.has(name) ? name : OTHER;
        folded[k] = (folded[k] ?? 0) + value;
      }
      segments = Object.entries(folded).map(([name, value]) => ({
        name, value, color: `var(--s${slotOf[name] ?? slotOf[OTHER] ?? 7})`,
      }));
    }
    return {
      key: r.key, label: r.label, short: short(r, grain), segments,
      // Income as a marker reads against a month or a year. A day's income
      // is the salary landing once: drawn, it set the scale and flattened
      // every other day of the month to a few pixels. The tooltip keeps it.
      total: r.spending, marker: incomeMarker ? r.income : undefined, pickable: !!t.drill && r.count > 0,
    };
  });

  const legend = byBucket
    ? data.bucket_order.filter((b) => t.rows.some((r) => r.buckets[b])).map((b) => ({ name: bucketLabel(b), color: data.bucket_fill[b] }))
    : data.legend.map((l) => ({ name: l.name, color: `var(--s${l.slot})` }));

  return (
    <Panel
      title={`Dépenses par ${data.period.grains.find((g) => g.id === grain)?.label.toLowerCase() ?? grain}`}
      hint={t.hint ? `${t.hint} · glisser sélectionne une plage` : undefined}
      actions={
        <Segmented size="sm" label="Découpage des colonnes" value={t.stack}
                   options={t.stacks.map((s) => ({ id: s.id as "category" | "bucket", label: s.label }))}
                   hrefFor={(id) => href({ stack: id === "category" ? null : id })} />
      }
    >
      <Columns
        columns={columns}
        height={300}
        ariaLabel={`Dépenses par période, ${byBucket ? "par besoin, envie et épargne" : "par catégorie"}`}
        pickHint={t.drill === "detail" ? "Ouvrir la journée" : "Zoomer sur cette période"}
        tipFooter={(c) => {
          const r = t.rows.find((x) => x.key === c.key)!;
          return (
            <div className="space-y-0.5">
              <div className="flex justify-between gap-3"><span>Dépensé</span><b className="num">{chf(r.spending)} CHF</b></div>
              {r.income > 0 && <div className="flex justify-between gap-3"><span>Encaissé</span><span className="num text-good">{chf(r.income)} CHF</span></div>}
              <div className="flex justify-between gap-3 text-muted"><span>Transactions</span><span className="num">{r.count}</span></div>
            </div>
          );
        }}
        format={compact}
        onPick={(c) => {
          const r = t.rows.find((x) => x.key === c.key)!;
          if (t.drill === "detail") onDay(r.start);
          else go(windowPatch(r.start, r.end));
        }}
        onBrush={(a, b) => go(windowPatch(t.rows[a].start, t.rows[b].end))}
      />
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px] text-ink-2">
        {legend.map((l) => (
          <span key={l.name} className="inline-flex items-center gap-1.5"><Dot color={l.color} />{l.name}</span>
        ))}
        {incomeMarker && <span className="inline-flex items-center gap-1.5"><i className="h-[2.5px] w-3 rounded-full bg-good" />Encaissé (repère)</span>}
      </div>
      {ai?.enabled && dearest && dearest.spending > 0 && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-hairline pt-3 text-[13.5px]">
          <span>Le plus cher : <b className="capitalize">{dearest.label}</b> · <span className="num">{chf(dearest.spending, 0)}</span> CHF</span>
          <Button size="sm" onClick={() => go({ ...windowPatch(dearest.start, dearest.end), why: "1" })}>Pourquoi ce mois ?</Button>
        </div>
      )}
      {byBucket && (
        <p className="mt-3 text-[12.5px] text-muted">
          Ici « Épargne » ne compte que les versements sortants vers l'épargne. Le solde non dépensé en fait
          aussi partie, mais n'a pas de transaction propre : il n'apparaît que dans le bloc « Besoins, envies, épargne ».
        </p>
      )}
    </Panel>
  );
}
