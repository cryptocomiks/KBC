import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BellRing, FileCheck2, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ENTITY_COLORS, fmtDate } from "../lib/format";
import type { CaseTab } from "../lib/route";
import type { CaseView } from "../types";
import { VigilanceBadge } from "./KycQuestionnaire";

const STATE_STYLE: Record<string, string> = {
  to_complete: "bg-[#2e90fa]/12 text-[#1570ef] ring-[#2e90fa]/30 dark:text-[#84caff]",
  rejected: "bg-amber-500/15 text-amber-700 ring-amber-500/40 dark:text-amber-300",
  pending_validation: "bg-[#f04438]/12 text-[#d92d20] ring-[#f04438]/30 dark:text-[#fda29b]",
  validated: "bg-[#17b26a]/12 text-[#079455] ring-[#17b26a]/30 dark:text-[#75e0a7]",
};
const TABS: { id: CaseTab; label: string }[] = [
  { id: "kyc", label: "KYC file" },
  { id: "investigation", label: "Investigation" },
  { id: "history", label: "History & notes" },
];

interface Props {
  view: CaseView;
  tab: CaseTab;
  onTab: (t: CaseTab) => void;
  onBack: () => void;
}

/** Sticky case header: status at a glance (workflow, vigilance, risk, documents), actions and tabs. */
export default function CaseHeader({ view, tab, onTab, onBack }: Props) {
  const { case: c, workflow, checklist, questionnaire } = view;
  const qc = useQueryClient();
  const [last, setLast] = useState<string | null>(null);
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["case", c.id] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const update = useMutation({ mutationFn: (p: Parameters<typeof api.updateCase>[1]) => api.updateCase(c.id, p), onSuccess: invalidate });
  const refresh = useMutation({
    mutationFn: () => api.refreshCase(c.id),
    onSuccess: (r) => {
      setLast(r.changes.length ? `${r.changes.length} change(s) found — see History` : "Checked just now: nothing changed");
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: () => api.deleteCase(c.id), onSuccess: onBack });
  const docs = checklist?.documents ?? [];
  const docsDone = docs.filter((d) => d.done).length;
  const vigilance = questionnaire.assessment?.level;
  const unseen = view.changes.filter((x) => !x.seen).length;
  const badge: Partial<Record<CaseTab, number>> = {
    kyc: workflow?.state === "to_complete" || workflow?.state === "rejected" ? workflow.blockers.length : 0,
    history: unseen,
  };

  return (
    <div className="card z-20 -mx-1 overflow-hidden p-0 shadow-sm backdrop-blur-xl md:sticky md:top-14">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-3 pb-2">
        <button className="btn-ghost -ml-2 px-2 py-1 text-xs" onClick={onBack} aria-label="Back to cases">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[17px] font-semibold tracking-tight">{c.title}</h1>
          <div className="truncate text-[11px] text-slate-500">
            {c.subject_name !== c.title && `${c.subject_name} · `}Created {fmtDate(c.created_at)} · last checked{" "}
            {c.last_run_at ? fmtDate(c.last_run_at) : "never"}
            {c.demo && " · demo data"}
          </div>
        </div>
        {/* Status chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          {workflow && (
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${STATE_STYLE[workflow.state]}`}>
              {workflow.state === "rejected" ? "Sent back" : workflow.label}
            </span>
          )}
          {vigilance ? (
            <VigilanceBadge level={vigilance} small />
          ) : (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold text-slate-500 uppercase ring-1 ring-slate-300 ring-inset dark:ring-white/15">
              vigilance to assess
            </span>
          )}
          {c.risk_level && (
            <span className="rounded-full px-2 py-0.5 text-[10px] font-bold text-white uppercase" style={{ background: ENTITY_COLORS[c.risk_level] }}>
              {c.risk_level} {c.risk_score?.toFixed(0)}
            </span>
          )}
          {docs.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[11px] text-slate-500" title="Documents received">
              <FileCheck2 className="h-3.5 w-3.5" /> {docsDone}/{docs.length}
              <span className="h-1.5 w-12 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                <span className="block h-full rounded-full bg-brand-500 transition-[width] duration-500" style={{ width: `${(100 * docsDone) / docs.length}%` }} />
              </span>
            </span>
          )}
        </div>
        {/* Actions */}
        <div className="flex items-center gap-1.5">
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs" title="Re-checked every day against fresh data">
            <input type="checkbox" className="accent-brand-600" checked={c.monitor} onChange={(e) => update.mutate({ monitor: e.target.checked })} />
            <BellRing className="h-3.5 w-3.5" /> <span className="hidden lg:inline">Monitoring</span>
          </label>
          <select className="input py-1 text-xs" value={c.status} onChange={(e) => update.mutate({ status: e.target.value as "open" | "closed" })}>
            <option value="open">Open</option>
            <option value="closed">Closed</option>
          </select>
          <button className="btn-outline py-1.5 text-xs" onClick={() => refresh.mutate()} disabled={refresh.isPending} title="Re-run the checks with today's data">
            {refresh.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline">Re-check</span>
          </button>
          <button
            className="btn-ghost px-2 py-1.5 text-xs text-red-600"
            aria-label="Delete the case"
            onClick={() => window.confirm(`Delete the case “${c.title}” and its decisions?`) && remove.mutate()}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {(last || refresh.error) && (
        <p className={`px-4 pb-1 text-[11px] ${refresh.error ? "text-red-600" : "text-slate-500"}`}>
          {refresh.error ? (refresh.error as Error).message : last}
        </p>
      )}
      {/* Tabs */}
      <nav className="flex gap-1 overflow-x-auto border-t border-slate-200 px-3 dark:border-white/10" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => onTab(t.id)}
            className={`relative flex shrink-0 items-center gap-1.5 px-3 py-2.5 text-[13px] font-medium transition-colors ${
              tab === t.id ? "text-slate-900 dark:text-white" : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            }`}
          >
            {t.label}
            {!!badge[t.id] && (
              <span className={`rounded-full px-1.5 text-[10px] font-semibold text-white ${t.id === "history" ? "bg-red-600" : "bg-amber-500"}`}>
                {badge[t.id]}
              </span>
            )}
            {tab === t.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-500 shadow-[0_0_10px_rgb(94_224_42/0.6)]" />}
          </button>
        ))}
      </nav>
    </div>
  );
}
