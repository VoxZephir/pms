/** `/api/projets` (`projects.py`). */

export interface ProjectRow {
  key: string; date: string; label: string; amount: number;
  category: string; subcategory: string; slot: number | null; country: string | null;
}

export interface ProjectSummary {
  id: string; name: string; kind: string; count: number; missing: number;
  start: string | null; end: string | null; days: number;
  spent: number; back: number; net: number; per_day: number | null;
  categories: { category: string; amount: number; slot: number | null; share: number }[];
  countries: string[];
}

export interface Suggestion {
  id: string; name: string; start: string; end: string; countries: string[]; keys: string[];
  count: number; spent: number; back: number; net: number; why: string;
  rows: (ProjectRow & { reason: string })[];
}

export interface ProjectsData {
  empty?: boolean;
  projects: ProjectSummary[];
  legend: { name: string; slot: number }[];
  suggestions: Suggestion[];
  detail?: ProjectSummary & { rows: ProjectRow[]; candidates: ProjectRow[] };
}
