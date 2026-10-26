/** Which account the savings page shows, beside the period in the sticky
 * bar: it scopes every figure of the page, as the window does. Same `focus`
 * key as the "Par poche" table's links. */
import { Check, ChevronDown, Wallet } from "lucide-react";
import { Popover } from "radix-ui";
import { useState } from "react";
import { Link } from "react-router";

import { cx } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { Meta } from "@/lib/types";
import { useView } from "@/lib/url";

export function PocketPicker({ compact = false }: { compact?: boolean }) {
  const { params, href } = useView();
  const { data: meta } = useApi<Meta>("/api/meta");
  const [open, setOpen] = useState(false);
  const pockets = [
    { id: "total", label: "Tous les comptes", short: "Tout" },
    { id: "swissquote", label: "Swissquote", short: "Swissquote" },
    { id: "ibkr", label: "IBKR", short: "IBKR" },
    { id: "finpension", label: "3a finpension", short: "3a" },
    ...(meta?.crypto ? [{ id: "crypto", label: "Crypto (Revolut)", short: "Crypto" }] : []),
    ...(meta?.titres ? [{ id: "titres", label: "Titres non cotés", short: "Titres" }] : []),
  ];
  const current = pockets.find((p) => p.id === (params.get("focus") || "total")) ?? pockets[0];
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button type="button" aria-label={`Compte affiché : ${current.label}`}
                className="flex shrink-0 items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[14px] font-semibold transition hover:bg-surface-2">
          <Wallet size={16} className="text-muted" />
          {compact ? current.short : current.label}
          <ChevronDown size={15} className="text-muted" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content sideOffset={6} align="start"
                         className="z-50 w-56 rounded-2xl border border-hairline bg-surface p-1.5 shadow-pop">
          {pockets.map((p) => {
            const on = p.id === current.id;
            return (
              <Link key={p.id} to={href({ focus: p.id === "total" ? null : p.id })} preventScrollReset
                    onClick={() => setOpen(false)} aria-current={on ? "true" : undefined}
                    className={cx("flex items-center justify-between rounded-xl px-3 py-2 text-[14px] no-underline transition",
                      on ? "bg-surface-2 font-semibold text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink")}>
                {p.label}{on && <Check size={15} />}
              </Link>
            );
          })}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
