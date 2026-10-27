/** `/api/impots`: the return rubric by rubric (`taxes.py`). */
import type { TaxProvision } from "@/lib/types";

export interface TaxLine { date: string; label: string; amount: number; key: string | null }

export interface TaxItem {
  key: string; group: string; title: string; form: string;
  amount: number; deductible: number | null;
  certainty: "exact" | "rule" | "estimate" | "indicative";
  rule: string; rows: TaxLine[]; note: string;
  canton?: { deductible: number; rule: string; certain: boolean };
}

export interface Installments { since: string; amount: number; months: number[] }
export interface TaxSettings { canton: string; since: number | null; paid_next_year: boolean; installments: Installments | null }

export interface Taxes {
  empty?: boolean;
  year: number; years: number[]; whole: boolean; published: boolean;
  net: { value: number; estimated: boolean; pay: number };
  salaries: { label: string; amount: number; count: number }[];
  items: TaxItem[];
  deducted: number;
  pillar3a: { ceiling: number; paid: number; left: number; published: boolean };
  interest: { bank: number; dividends: number; broker: number; withheld: number; rows: TaxLine[] };
  wealth: {
    day: string; partial: boolean; taxable: number;
    rows: { name: string; kind: string; detail: string; value: number | null }[];
    pillar3a_value: number | null;
  };
  paid: { year: number; later: boolean; seen: boolean; out: number; back: number; rows: TaxLine[] };
  securities: Security[];
  holdings: Holding[];
  canton: { code: string; name: string; guide: string } | null;
  deducted_canton: number | null;
  settings: TaxSettings;
  cantons: { id: string; name: string }[];
  franchise: { franchise: number; declared: boolean };
  provision: TaxProvision | null;
}

export interface Security {
  id: string; name: string; quantity: number; unit: number; value: number; payer: string; withholding: boolean;
  dividends: { net: number; gross: number; withheld: number; rows: TaxLine[] };
}

export interface Holding {
  id: string; name: string; kind: "share" | "other"; quantity: number; payer: string; withholding: boolean;
  since: number | null; values: Record<string, number>;
}
