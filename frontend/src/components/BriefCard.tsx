import { AlertOctagon, AlertTriangle, ArrowRight, ChevronDown, ChevronRight, Info, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useCountUp } from "../lib/motion";
import type { Brief, Investigation } from "../types";

const LEVEL_PANEL: Record<string, string> = {
  critical: "bg-[#fef3f2] text-[#b42318] dark:bg-[#55160c]/60 dark:text-[#fda29b]",
  high: "bg-[#fffaeb] text-[#b54708] dark:bg-[#4e1d09]/60 dark:text-[#fec84b]",
  medium: "bg-[#fefbe8] text-[#a15c07] dark:bg-[#542c0d]/60 dark:text-[#fde272]",
  low: "bg-[#ecfdf3] text-[#067647] dark:bg-[#053321]/60 dark:text-[#47cd89]",
  incomplete: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200",
};
const TONE: Record<string, string> = {
  critical: "text-[#b42318] dark:text-[#fda29b]",
  warning: "text-[#b54708] dark:text-[#fec84b]",
  good: "text-[#067647] dark:text-[#47cd89]",
  neutral: "text-[#101828] dark:text-white",
};
const DOT: Record<string, string> = {
  critical: "bg-[#d92d20]",
  warning: "bg-[#dc6803]",
  good: "bg-[#079455]",
  neutral: "bg-slate-300 dark:bg-slate-600",
};
/** Whole numbers count up when they appear; anything else is shown as is. */
function Counted({ value }: { value: string }) {
  const n = /^\d+$/.test(value) ? Number(value) : null;
  const v = useCountUp(n ?? 0);
  return <>{n === null ? value : Math.round(v)}</>;
}

const SEV_ICON = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;
const SEV_COLOR = { critical: "text-red-600", warning: "text-amber-600", info: "text-slate-400" } as const;

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
  onOpenTab: (tab: string) => void;
  /** The ownership infographic shows the owners: the brief then only lists the red flags. */
  hideOwners?: boolean;
}

/** The 30-second read: verdict, key figures, ultimate owners, red flags with the next step. */
export default function BriefCard({ investigation: inv, onSelect, onOpenTab, hideOwners }: Props) {
  const b: Brief | null = inv.brief;
  const [showAll, setShowAll] = useState(false);
  if (!b) return null;
  const [level, ...rest] = b.headline.split(" — ");
  const flags = showAll ? b.flags : b.flags.slice(0, 4);
  const Verdict = b.level === "low" ? ShieldCheck : b.level === "medium" ? AlertTriangle : AlertOctagon;

  return (
    <div className="card overflow-hidden">
      {/* Risk rating, main finding, recommended action */}
      <div className="grid border-b border-slate-200 md:grid-cols-[200px_1fr] dark:border-slate-800">
        <div className={`flex flex-col justify-center gap-1 px-5 py-4 ${LEVEL_PANEL[b.level] ?? LEVEL_PANEL.low}`}>
          <div className="text-[11px] font-semibold tracking-wider uppercase opacity-80">Risk rating</div>
          <div className="flex items-center gap-2 text-[20px] font-bold tracking-wide uppercase">
            <Verdict className="h-5 w-5" /> {level}
          </div>
          <div className="text-[12px] font-medium opacity-80">Score {b.score.toFixed(0)} / 100</div>
        </div>
        <div className="px-5 py-4">
          <div className="tag">Summary</div>
          <p className="mt-0.5 text-[16px] leading-snug font-semibold text-slate-900 dark:text-white">{rest.join(" — ")}</p>
          {b.action && (
            <p className="mt-2 flex gap-2 text-[13px] text-slate-700 dark:text-slate-300">
              <span className="shrink-0 font-semibold text-slate-900 dark:text-white">Recommended action:</span>
              {b.action}
            </p>
          )}
        </div>
      </div>

      {/* Key figures */}
      <div className="stagger grid grid-cols-2 border-b border-slate-200 sm:grid-cols-4 xl:grid-cols-8 dark:border-slate-800 [&>*]:border-slate-200 [&>*]:dark:border-slate-800">
        {b.figures.map((f, i) => (
          <button
            key={f.key}
            style={{ ["--i" as string]: i }}
            onClick={() => f.tab && onOpenTab(f.tab)}
            className="border-r border-b px-4 py-3 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/60"
            title={f.hint ?? undefined}
          >
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
              <span className={`h-1.5 w-1.5 rounded-full ${DOT[f.tone] ?? DOT.neutral}`} />
              {f.label}
            </div>
            <div className={`mt-0.5 font-semibold leading-tight tabular-nums ${f.value.length > 14 ? "text-[14px]" : f.value.length > 6 ? "text-[15px]" : "text-[20px]"} ${TONE[f.tone] ?? TONE.neutral}`}>
              <Counted value={f.value} />
            </div>
            {f.hint && <div className="truncate text-[11px] text-slate-500">{f.hint}</div>}
          </button>
        ))}
      </div>

      <div
        className={`grid gap-4 border-t [&>*]:min-w-0 border-black/[0.06] p-5 dark:border-white/[0.08] ${hideOwners ? "" : "lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"}`}
      >
        {/* Owners */}
        <div className={hideOwners ? "hidden" : ""}>
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
            Findings and required action ({b.flags.length})
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
