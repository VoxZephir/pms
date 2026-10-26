import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { isRouteErrorResponse, useRouteError } from "react-router";

import { ButtonLink } from "./ui";

export function PageError({ notFound, error }: { notFound?: boolean; error?: unknown }) {
  const routeError = useRouteError();
  const err = error ?? routeError;
  const missing = notFound || (isRouteErrorResponse(err) && err.status === 404);
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      <CircleAlert className="mx-auto text-muted" size={32} />
      <h1 className="mt-4 text-xl font-semibold">{missing ? "Page introuvable" : "Quelque chose a cassé"}</h1>
      <p className="mt-2 text-[14px] text-muted">
        {missing ? "Cette adresse ne mène nulle part." : String((err as Error)?.message ?? err ?? "")}
      </p>
      <ButtonLink to="/" className="mt-6" variant="primary">Revenir au tableau de bord</ButtonLink>
    </div>
  );
}

export function PageHeader({
  title, subtitle, actions, eyebrow,
}: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end gap-x-4 gap-y-3 sm:mb-6">
      <div className="min-w-[min(100%,280px)] flex-1">
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.025em] sm:text-[30px]">{title}</h1>
        {subtitle && <p className="mt-1 text-[13.5px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
