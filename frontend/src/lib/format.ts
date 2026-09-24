import type { RiskLevel } from "../types";

/** Global score colours (gauge). */
export const RISK_COLORS: Record<RiskLevel, string> = {
  none: "#94a3b8",
  low: "#16a34a",
  medium: "#d97706",
  high: "#ea580c",
  critical: "#dc2626",
  incomplete: "#94a3b8",
};

/** Entity colours in the graph: any flag is at least yellow, "no flag" stays neutral. */
export const ENTITY_COLORS: Record<RiskLevel, string> = {
  none: "#94a3b8",
  low: "#eab308",
  medium: "#f59e0b",
  high: "#ea580c",
  critical: "#dc2626",
  incomplete: "#94a3b8",
};

export const ENTITY_LEVEL_LABEL: Record<RiskLevel, string> = {
  none: "no flag",
  low: "minor",
  medium: "medium",
  high: "high",
  critical: "critical",
  incomplete: "not screened",
};

export const RISK_BADGE: Record<RiskLevel, string> = {
  none: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  low: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  high: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  critical: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  incomplete: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
};

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

export function countryName(code?: string | null): string {
  if (!code) return "—";
  try {
    return regionNames.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

export function flag(code?: string | null): string {
  if (!code || code.length !== 2) return "";
  return String.fromCodePoint(...[...code.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)));
}

export function fmtDate(value?: unknown): string {
  if (!value) return "—";
  const s = String(value);
  if (s.length > 10 && s.includes("T")) {
    const d = new Date(s);
    return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
  }
  return s;
}

export function fmtPct(value?: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return `${Number(value).toLocaleString("en", { maximumFractionDigits: 2 })}%`;
}

export function scoreClass(score: number): string {
  if (score >= 85) return "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";
  if (score >= 70) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
}

export function matchScoreClass(score: number): string {
  if (score >= 90) return "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300";
  if (score >= 75) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
}
