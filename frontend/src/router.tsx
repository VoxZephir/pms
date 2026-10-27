import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter } from "react-router";

import { PageError } from "./components/PageState";
import { Skeleton } from "./components/ui";
import { DashboardPage } from "./pages/Dashboard";
import { AppShell } from "./shell/AppShell";

// The dashboard is in the first download; every other page is fetched the
// first time it is opened, so the phone's first load stays small.
const TransactionsPage = lazy(() => import("./pages/Transactions"));
const DayPage = lazy(() => import("./pages/Day"));
const SavingsPage = lazy(() => import("./pages/Savings"));
const AnalysePage = lazy(() => import("./pages/Analyse"));
const PrevisionsPage = lazy(() => import("./pages/Previsions"));
const CorrectionsPage = lazy(() => import("./pages/Corrections"));
const TriagePage = lazy(() => import("./pages/Triage"));
const UploadPage = lazy(() => import("./pages/Upload"));
const AssistantPage = lazy(() => import("./pages/Assistant"));
const UpcomingPage = lazy(() => import("./pages/Upcoming"));
const TaxesPage = lazy(() => import("./pages/Taxes"));
const ProjectsPage = lazy(() => import("./pages/Projects"));
const RetroPage = lazy(() => import("./pages/Retro"));
const RedactPage = lazy(() => import("./pages/Redact"));
const HelpPage = lazy(() => import("./pages/Help"));

function Lazy({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div className="space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-64" /></div>}>
      {children}
    </Suspense>
  );
}

export const router = createBrowserRouter(
  [
    {
      element: <AppShell />,
      errorElement: <PageError />,
      children: [
        { index: true, element: <DashboardPage /> },
        { path: "transactions", element: <Lazy><TransactionsPage /></Lazy> },
        { path: "jour/:iso", element: <Lazy><DayPage /></Lazy> },
        { path: "epargne", element: <Lazy><SavingsPage /></Lazy> },
        { path: "analyse", element: <Lazy><AnalysePage /></Lazy> },
        { path: "previsions", element: <Lazy><PrevisionsPage /></Lazy> },
        { path: "corrections", element: <Lazy><CorrectionsPage /></Lazy> },
        { path: "corrections/tri", element: <Lazy><TriagePage /></Lazy> },
        { path: "importer", element: <Lazy><UploadPage /></Lazy> },
        { path: "assistant", element: <Lazy><AssistantPage /></Lazy> },
        { path: "a-venir", element: <Lazy><UpcomingPage /></Lazy> },
        { path: "impots", element: <Lazy><TaxesPage /></Lazy> },
        { path: "projets", element: <Lazy><ProjectsPage /></Lazy> },
        { path: "bilan", element: <Lazy><RetroPage /></Lazy> },
        { path: "caviarder", element: <Lazy><RedactPage /></Lazy> },
        { path: "aide", element: <Lazy><HelpPage /></Lazy> },
        { path: "*", element: <PageError notFound /> },
      ],
    },
  ],
);
