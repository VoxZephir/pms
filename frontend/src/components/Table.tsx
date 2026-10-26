/** A table that stays a table on a laptop and becomes a list of cards on a
 * phone: the first column is the card's title, the others its rows. */
import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { cx } from "./ui";

export interface Col<T> {
  key: string;
  label: ReactNode;
  render: (row: T) => ReactNode;
  /** Sort key; the column is sortable when given. */
  sort?: (row: T) => number | string;
  numeric?: boolean;
  title?: string;
  /** Hidden in the phone's card (secondary detail). */
  wide?: boolean;
  className?: string;
}

export function Table<T>({
  rows, cols, rowKey, rowClass, empty, sortable = true, dense,
}: {
  rows: T[];
  cols: Col<T>[];
  rowKey: (row: T, i: number) => string;
  rowClass?: (row: T) => string | undefined;
  empty?: ReactNode;
  sortable?: boolean;
  dense?: boolean;
}) {
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = cols.find((c) => c.key === sort.key);
    if (!col?.sort) return rows;
    const get = col.sort;
    return [...rows].sort((a, b) => {
      const x = get(a);
      const y = get(b);
      const cmp = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "fr");
      return sort.desc ? -cmp : cmp;
    });
  }, [rows, cols, sort]);

  if (!rows.length) return <p className="py-4 text-[14px] text-muted">{empty ?? "Rien à afficher."}</p>;
  const [head, ...rest] = cols;

  return (
    <>
      <div className="-mx-4 hidden overflow-x-auto sm:-mx-5 sm:block">
        <table className="w-full border-collapse text-[13.5px]">
          <thead>
            <tr className="border-b border-hairline">
              {cols.map((c, i) => {
                const active = sort?.key === c.key;
                const click = sortable && c.sort
                  ? () => setSort(active ? (sort!.desc ? { key: c.key, desc: false } : null) : { key: c.key, desc: true })
                  : undefined;
                return (
                  <th key={c.key} scope="col" title={c.title}
                      aria-sort={active ? (sort!.desc ? "descending" : "ascending") : undefined}
                      className={cx("whitespace-nowrap px-3 py-2 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-muted",
                        c.numeric ? "text-right" : "text-left", i === 0 && "pl-4 sm:pl-5", i === cols.length - 1 && "pr-4 sm:pr-5")}>
                    {click ? (
                      <button type="button" onClick={click} className={cx("inline-flex items-center gap-1 uppercase hover:text-ink", active && "text-ink")}>
                        {c.label}
                        {active && (sort!.desc ? <ArrowDown size={12} /> : <ArrowUp size={12} />)}
                      </button>
                    ) : c.label}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, ri) => (
              <tr key={rowKey(r, ri)} className={cx("border-b border-hairline last:border-0 hover:bg-surface-2/50", rowClass?.(r))}>
                {cols.map((c, i) => (
                  <td key={c.key} className={cx(dense ? "py-1.5" : "py-2.5", "px-3 align-top",
                    c.numeric && "num whitespace-nowrap text-right", i === 0 && "pl-4 sm:pl-5", i === cols.length - 1 && "pr-4 sm:pr-5", c.className)}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-2 sm:hidden">
        {sorted.map((r, ri) => (
          <li key={rowKey(r, ri)} className={cx("rounded-2xl border border-hairline bg-surface-2/40 px-3.5 py-2.5", rowClass?.(r))}>
            <div className="text-[14px] font-medium">{head.render(r)}</div>
            <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[12.5px]">
              {rest.filter((c) => !c.wide).map((c) => (
                <div key={c.key} className="contents">
                  <dt className="text-muted">{c.label}</dt>
                  <dd className={cx("text-right", c.numeric && "num")}>{c.render(r)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </>
  );
}
