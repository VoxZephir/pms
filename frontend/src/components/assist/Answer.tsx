/** A: the answer to a question -- the view it points at, its table. */
import { Track, cx } from "@/components/ui";
import { chf } from "@/lib/format";

export interface AskAnswer {
  answer: string; supported: boolean; measure_label?: string; scope?: string;
  title?: string; sources?: string[];
  view?: Record<string, string | number | null>;
  table?: { columns: string[]; rows: (string | number)[][] } | null;
  follow_ups: string[]; focus?: string;
}

/** The view an answer points at, as an address of the app. */
export function answerHref(view: Record<string, string | number | null>): string {
  const { path, ...rest } = view;
  const q = new URLSearchParams();
  Object.entries(rest).forEach(([k, v]) => { if (v != null && v !== "") q.set(k, String(v)); });
  const s = q.toString();
  return s ? `${path}?${s}` : String(path ?? "/");
}

const BARS = new Set(["categories", "beneficiaires", "par_mois", "jours", "grosses_lignes", "abonnements"]);

/** The numbers under an answer, as the app computed them: one amount per
 * row reads as bars, anything wider as a table. */
export function AnswerTable({ table, focus }: { table: NonNullable<AskAnswer["table"]>; focus?: string }) {
  if (!table.rows.length) return null;
  const amount = table.columns.length >= 2 && table.rows.every((r) => typeof r[1] === "number") ? 1 : -1;
  const barCol = focus === "grosses_lignes" ? 2 : amount;
  if (focus && BARS.has(focus) && barCol > 0 && table.rows.every((r) => typeof r[barCol] === "number")) {
    const labelCol = focus === "grosses_lignes" ? 1 : 0;
    const max = Math.max(...table.rows.map((r) => Math.abs(r[barCol] as number)), 1);
    return (
      <div className="mt-3 space-y-1.5">
        {table.rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[minmax(0,8.5rem)_minmax(0,1fr)_5rem] items-center gap-2 text-[12.5px]">
            <span className="truncate" title={String(r[labelCol])}>{r[labelCol]}</span>
            <Track value={(Math.abs(r[barCol] as number) / max) * 100} color="var(--s1)" />
            <span className="num text-right">{chf(r[barCol] as number, 0)}</span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="mt-3 overflow-x-auto rounded-xl border border-hairline">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-[0.06em] text-muted">
            {table.columns.map((c, i) => <th key={i} className={cx("px-3 py-2 font-semibold", i > 0 && "text-right")}>{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r} className="border-t border-hairline">
              {row.map((v, i) => (
                <td key={i} className={cx("px-3 py-1.5", i > 0 ? "num text-right" : "min-w-0 max-w-[14rem] truncate")}>
                  {typeof v === "number" ? chf(v) : v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
