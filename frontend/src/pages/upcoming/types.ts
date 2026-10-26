/** `/api/a-venir`: the commitments, their due dates, the deadlines to change
 * them, the health franchise replayed (`upcoming.py`, `health.py`). */

export interface PriceMove {
  before: number; before_day: string; now: number; since: string;
  delta: number; pct: number; yearly_delta: number;
}

export interface Commitment {
  label: string; category: string; subcategory: string; slot: number;
  cadence: string; interval: number; count: number;
  first: string; last: string; next: string; dues: string[];
  amount: number; variable: boolean; yearly: number; monthly: number;
  price: PriceMove | null; spark: number[];
}

export interface Due {
  day: string; label: string; amount: number; out: boolean; category: string;
  slot: number | null; cadence: string; variable: boolean; pending: boolean;
}

export interface Horizon { days: number; until: string; out: number; in: number; count: number }

export interface Deadline {
  kind: "lamal" | "insurance"; label: string; by: string; days: number;
  title: string; detail: string; monthly: number; yearly: number;
  price: PriceMove | null; certain: boolean;
}

export interface CareYear {
  year: number; paid: number; billed: number; refunds: number; share: number;
  costs: number; exact: boolean; whole: boolean; until: string;
  best?: number; saving?: number;
}

export interface Replay {
  franchise: number; premium: number; costs: number;
  rows: { franchise: number; premium: number; premiums: number; left: number; total: number }[];
  best: number; saving: number;
  axis: number[]; curves: { franchise: number; values: number[] }[]; crossing: number | null;
  years: CareYear[];
  rules: { quote_part: number; cap: number; discount: number };
}

export interface Upcoming {
  empty?: boolean;
  today: string; statement_end: string; start: string; stale: number;
  commitments: Commitment[];
  income: { label: string; amount: number; dues: string[] }[];
  summary: { count: number; yearly: number; monthly: number; rises: number; rises_yearly: number; falls: number };
  ahead: { rows: Due[]; totals: Horizon[]; pending: { count: number; out: number } };
  legend: { name: string; slot: number }[];
  deadlines: Deadline[];
  health: {
    settings: { franchise: number; declared: boolean };
    premium: { label: string; monthly: number } | null;
    years: CareYear[];
    default_costs: number;
    franchises: number[];
    replay: Replay | null;
  };
}
