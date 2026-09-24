import { AlertOctagon, AlertTriangle, ArrowRight, ChevronDown, ChevronRight, Info, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { Brief, Investigation } from "../types";

const LEVEL_STYLE: Record<string, string> = {
  critical: "border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-100",
  high: "border-orange-300 bg-orange-50 text-orange-900 dark:border-orange-900 dark:bg-orange-950/50 dark:text-orange-100",
  medium: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100",
  low: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100",
};
const TONE: Record<string, string> = {
  critical: "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200",
  warning: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200",
  good: "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-200",
  neutral: "border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100",
};
const SEV_ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;
const SEV_COLOR = { critical: "text-red-600", warning: "text-amber-600", info: "text-slate-400" } as const;

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
  onOpenTab: (tab: string) => void;
}

/** The 30-second read: verdict, key figures, ultimate owners, red flags with the next step. */
export default function BriefCard({ investigation: inv, onSelect, onOpenTab }: Props) {
  const b: Brief | null = inv.brief;
  const [showAll, setShowAll] = useState(false);
  if (!b) return null;
  const [level, ...rest] = b.headline.split(" — ");
  const flags = showAll ? b.flags : b.flags.slice(0, 4);
  const Verdict = b.level === "low" ? ShieldCheck : b.level === "medium" ? AlertTriangle : AlertOctagon;

  return (
    <div className="card overflow-hidden">
      {/* Verdict */}
      <div className={`flex items-start gap-3 border-b px-4 py-3 ${LEVEL_STYLE[b.level] ?? LEVEL_STYLE.low}`}>
        <Verdict className="mt-0.5 h-6 w-6 shrink-0" />
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wider opacity-80">
            Verdict · {level} · score {b.score.toFixed(0)}/100
          </div>
          <p className="text-base font-semibold leading-snug">{rest.join(" — ")}</p>
        </div>
      </div>

      {/* Key figures */}
      <div className="grid grid-cols-2 gap-2 p-4 sm:grid-cols-4 xl:grid-cols-8">
        {b.figures.map((f) => (
          <button
            key={f.key}
            onClick={() => f.tab && onOpenTab(f.tab)}
            className={`rounded-lg border px-3 py-2 text-left transition hover:shadow-sm ${TONE[f.tone] ?? TONE.neutral}`}
            title={f.hint ?? undefined}
          >
            <div className="text-[10px] font-semibold uppercase tracking-wide opacity-70">{f.label}</div>
            <div className={`font-bold leading-tight ${f.value.length > 14 ? "text-sm" : "text-lg"}`}>{f.value}</div>
            {f.hint && <div className="truncate text-[10px] opacity-70">{f.hint}</div>}
          </button>
        ))}
      </div>

      <div className="grid gap-4 border-t border-slate-200 p-4 dark:border-slate-800 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        {/* Owners */}
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            {b.subject_type === "person" ? "What they control (effective %)" : "Who is behind it (effective %)"}
          </h3>
          {b.owners.length === 0 ? (
            <p className="text-sm text-slate-500">
              {b.subject_type === "company"
                ? "No ultimate owner identified in the sources queried — to be obtained from the client (UBO register, KYC documents)."
                : b.subject_type === "person"
                  ? "No shareholding found in the sources queried: see the mandates (officer roles) below."
                  : "Not applicable."}
            </p>
          ) : (
            <ul className="space-y-2">
              {b.owners.map((o) => (
                <li key={o.entity_id}>
                  <button onClick={() => onSelect(o.entity_id)} className="w-full text-left">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
                        <div className={`h-full ${o.flags.includes("sanctioned") ? "bg-red-500" : "bg-brand-600"}`} style={{ width: `${Math.min(100, o.pct)}%` }} />
                      </div>
                      <span className="w-12 text-right font-mono text-xs font-semibold">{o.pct.toFixed(o.pct < 1 ? 2 : 0)}%</span>
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1 text-sm">
                      <span className="font-medium">{o.name}</span>
                      {o.flags.map((t) => (
                        <span key={t} className="rounded bg-red-100 px-1.5 text-[10px] font-semibold uppercase text-red-800 dark:bg-red-900/40 dark:text-red-200">
                          {t}
                        </span>
                      ))}
                    </div>
                    {o.path.length > 2 && (
                      <div className="flex flex-wrap items-center gap-0.5 text-[11px] text-slate-500">
                        {b.subject_type === "person" ? "through" : "via"}
                        {o.path.slice(1, -1).map((p, i) => (
                          <span key={p} className="inline-flex items-center gap-0.5">
                            {i > 0 && <ArrowRight className="h-3 w-3" />}
                            {p}
                          </span>
                        ))}
                      </div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Red flags + next steps */}
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Red flags and what to do ({b.flags.length})
          </h3>
          {b.flags.length === 0 ? (
            <p className="text-sm text-emerald-700 dark:text-emerald-300">No red flag in the sources queried. Standard due diligence applies.</p>
          ) : (
            <ol className="space-y-2">
              {flags.map((f) => {
                const Icon = SEV_ICON[f.severity];
                return (
                  <li key={f.key} className="rounded-lg border border-slate-200 p-2.5 dark:border-slate-700">
                    <div className="flex items-start gap-2">
                      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${SEV_COLOR[f.severity]}`} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-sm font-semibold">{f.title}</span>
                          <span className="shrink-0 font-mono text-[11px] text-slate-500">+{f.points.toFixed(0)}</span>
                        </div>
                        <p className="truncate text-xs text-slate-600 dark:text-slate-400" title={f.evidence.join("\n")}>
                          {f.evidence[0]}
                          {f.evidence.length > 1 && ` (+${f.evidence.length - 1} more)`}
                        </p>
                        {f.next_step && (
                          <p className="mt-1 flex gap-1 text-xs text-sky-800 dark:text-sky-300">
                            <ChevronRight className="mt-0.5 h-3 w-3 shrink-0" />
                            {f.next_step}
                          </p>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
          {b.flags.length > 4 && (
            <button className="btn-ghost mt-2 text-xs" onClick={() => setShowAll((s) => !s)}>
              <ChevronDown className={`h-3.5 w-3.5 transition ${showAll ? "rotate-180" : ""}`} />
              {showAll ? "Show the main flags only" : `Show all ${b.flags.length} flags`}
            </button>
          )}
        </div>
      </div>
      <div className="border-t border-slate-200 px-4 py-2 text-[11px] text-slate-500 dark:border-slate-800">{b.coverage}</div>
    </div>
  );
}
