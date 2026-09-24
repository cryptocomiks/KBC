import { AlertOctagon, AlertTriangle, ArrowRight, ChevronDown, ChevronRight, Info, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { Brief, Investigation } from "../types";

const LEVEL_BAR: Record<string, string> = {
  critical: "bg-[#ff3b30]",
  high: "bg-[#ff9500]",
  medium: "bg-[#ffcc00]",
  low: "bg-[#34c759]",
};
const LEVEL_PILL: Record<string, string> = {
  critical: "bg-[#ff3b30]/12 text-[#d70015] dark:bg-[#ff453a]/20 dark:text-[#ff6961]",
  high: "bg-[#ff9500]/15 text-[#c93400] dark:bg-[#ff9f0a]/20 dark:text-[#ffb340]",
  medium: "bg-[#ffcc00]/20 text-[#a05a00] dark:bg-[#ffd60a]/20 dark:text-[#ffd426]",
  low: "bg-[#34c759]/15 text-[#248a3d] dark:bg-[#30d158]/20 dark:text-[#30d158]",
};
const TONE: Record<string, string> = {
  critical: "text-[#d70015] dark:text-[#ff6961]",
  warning: "text-[#c93400] dark:text-[#ffb340]",
  good: "text-[#248a3d] dark:text-[#30d158]",
  neutral: "text-[#1d1d1f] dark:text-white",
};
const DOT: Record<string, string> = {
  critical: "bg-[#ff3b30]",
  warning: "bg-[#ff9500]",
  good: "bg-[#34c759]",
  neutral: "bg-slate-300 dark:bg-slate-600",
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
      <div className="flex items-start gap-4 px-5 pt-5 pb-4">
        <div className={`mt-1 h-10 w-1 shrink-0 rounded-full ${LEVEL_BAR[b.level] ?? LEVEL_BAR.low}`} />
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${LEVEL_PILL[b.level] ?? LEVEL_PILL.low}`}>
              <Verdict className="h-3 w-3" /> {level}
            </span>
            <span className="text-[11px] font-medium text-slate-500">Risk score {b.score.toFixed(0)} / 100</span>
          </div>
          <p className="text-[19px] leading-snug font-semibold tracking-[-0.015em] text-[#1d1d1f] dark:text-white">{rest.join(" — ")}</p>
        </div>
      </div>

      {/* Key figures */}
      <div className="grid grid-cols-2 gap-2 px-5 pb-5 sm:grid-cols-4 xl:grid-cols-8">
        {b.figures.map((f) => (
          <button
            key={f.key}
            onClick={() => f.tab && onOpenTab(f.tab)}
            className="rounded-xl bg-black/[0.03] px-3 py-2.5 text-left transition hover:bg-black/[0.06] active:scale-[0.98] dark:bg-white/[0.05] dark:hover:bg-white/[0.09]"
            title={f.hint ?? undefined}
          >
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
              <span className={`h-1.5 w-1.5 rounded-full ${DOT[f.tone] ?? DOT.neutral}`} />
              {f.label}
            </div>
            <div className={`mt-0.5 font-semibold leading-tight tracking-[-0.01em] ${f.value.length > 14 ? "text-[15px]" : f.value.length > 6 ? "text-[17px]" : "text-[22px]"} ${TONE[f.tone] ?? TONE.neutral}`}>
              {f.value}
            </div>
            {f.hint && <div className="truncate text-[11px] text-slate-500">{f.hint}</div>}
          </button>
        ))}
      </div>

      <div className="grid gap-4 border-t border-black/[0.06] p-5 dark:border-white/[0.08] lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
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
            <ol className="divide-y divide-black/[0.06] dark:divide-white/[0.08]">
              {flags.map((f) => {
                const Icon = SEV_ICON[f.severity];
                return (
                  <li key={f.key} className="py-2.5 first:pt-0">
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
                          <p className="mt-1 flex gap-1 text-xs text-brand-600 dark:text-brand-300">
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
      <div className="border-t border-black/[0.06] px-5 py-2.5 text-[11px] text-slate-500 dark:border-white/[0.08]">{b.coverage}</div>
    </div>
  );
}
