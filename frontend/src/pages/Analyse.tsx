/** The past, read several ways: the four figures, the ordinary month the
 * forecast is made of, what changed in a year, each category with its
 * line, the rhythm of a month and of a week. A category opens up close. */
import { Download } from "lucide-react";

import { MonthlyProfile } from "@/components/MonthlyProfile";
import { PageHeader } from "@/components/PageState";
import { Callout, Note, Panel, Segmented, Skeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { chf, frDate } from "@/lib/format";
import { useView } from "@/lib/url";
import { Categories, CategoryDetail, Changes, Headline, KEEP, Rhythm, WeekdayBars } from "./analyse/Reads";
import { MyInflation, VersusSwitzerland } from "./analyse/Swiss";
import type { Analyse } from "./analyse/types";

export default function AnalysePage() {
  const { params, href } = useView();
  const q = new URLSearchParams();
  KEEP.forEach((k) => { const v = params.get(k); if (v) q.set(k, v); });
  const { data, isPending, isPlaceholderData, error } = useApi<Analyse>("/api/analyse", q);
  if (error) return <Callout tone="bad" title="L'analyse n'a pas pu être chargée">{error.message}</Callout>;
  if (isPending || !data) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-24 rounded-card" /><Skeleton className="h-72 rounded-card" /></div>;
  if (data.empty) return <Callout title="Aucun relevé" />;
  const exportHref = (fmt: string) => `/analyse/export.${fmt}${data.year !== "median" ? `?year=${data.year}` : ""}`;
  const keep = { keep: KEEP };

  return (
    <div className={isPlaceholderData ? "opacity-70 transition-opacity" : "transition-opacity"}>
      <PageHeader
        title="Analyse"
        subtitle={<>la dépense passée, au {frDate(data.as_of)} — la matière dont les prévisions sont faites</>}
        actions={<>
          <a href={exportHref("csv")} download className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"><Download size={15} />CSV</a>
          <a href={exportHref("xlsx")} download className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[13px] font-medium text-ink-2 hover:bg-surface-2 hover:text-ink"><Download size={15} />Excel</a>
        </>}
      />
      <div className="space-y-4 sm:space-y-5">
        <Headline a={data} />
        {data.drill ? <CategoryDetail a={data} d={data.drill} /> : data.profile.length > 0 && (
          <Panel id="p-profile" title="Le mois ordinaire" hint="la médiane des mois observés ; la part claire est le pic saisonnier retiré de la base"
                 actions={<Segmented size="sm" label="Année du profil" value={data.year} options={data.years}
                                     hrefFor={(id) => href({ year: id === "median" ? null : id }, keep)} />}>
            <MonthlyProfile profile={data.profile} baseline={data.baseline} />
            <Note>Chaque barre est la médiane des mois observés de ce mois calendaire ; la part claire est ce que les factures annuelles détectées retirent. Le pointillé est la dépense de base, {chf(data.baseline, 0)} CHF.</Note>
          </Panel>
        )}
        <Changes a={data} />
        <Categories a={data} />
        <div className="grid gap-4 sm:gap-5 lg:grid-cols-[1.4fr_1fr]">
          <Rhythm a={data} />
          <WeekdayBars a={data} />
        </div>
        {!data.drill && data.inflation && <MyInflation inf={data.inflation} />}
        {!data.drill && data.households && <VersusSwitzerland h={data.households} />}
      </div>
    </div>
  );
}
