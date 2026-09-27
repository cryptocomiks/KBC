import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BellRing, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { fmtDate } from "../lib/format";
import type { CaseTab } from "../lib/route";
import type { CaseView } from "../types";
import { VigilanceBadge } from "./KycQuestionnaire";
import { Meter, Steps, Tile, type Tone } from "./viz";

const LEVEL_TONE: Record<string, Tone> = { none: "good", low: "good", medium: "warning", high: "serious", critical: "critical", incomplete: "neutral" };
const WF_STEPS = [
  { key: "to_complete", label: "Complete" },
  { key: "pending_validation", label: "Validate" },
  { key: "validated", label: "Validated" },
];
const WF_INDEX: Record<string, number> = { to_complete: 0, rejected: 0, pending_validation: 1, validated: 3 };
const TABS: { id: CaseTab; label: string }[] = [
  { id: "kyc", label: "KYC file" },
  { id: "alerts", label: "Alerts" },
  { id: "cdb", label: "UBO forms (CDB 20)" },
  { id: "sow", label: "Source of wealth" },
  { id: "checks", label: "Quick checks" },
  { id: "review", label: "Periodic review" },
  { id: "investigation", label: "Investigation" },
  { id: "memo", label: "Decision memo" },
  { id: "history", label: "History & notes" },
];
const DOT: Record<string, string> = { good: "bg-[var(--status-good)]", warning: "bg-[var(--status-warning)]", critical: "bg-[var(--status-critical)]" };

interface Props {
  view: CaseView;
  tab: CaseTab;
  onTab: (t: CaseTab) => void;
  onBack: () => void;
}

/** Case header: identity and actions, the file's key figures, then the (sticky) tab bar with
 *  what needs attention in each tab. */
export default function CaseHeader({ view, tab, onTab, onBack }: Props) {
  const { case: c, workflow, overview: o } = view;
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
  const unseen = view.changes.filter((x) => !x.seen).length;

  // What each tab still needs: a count, or a status dot (with its meaning in the title).
  const badge: Partial<Record<CaseTab, { n?: number; dot?: keyof typeof DOT; title: string }>> = {
    kyc: workflow && ["to_complete", "rejected"].includes(workflow.state) && workflow.blockers.length ? { n: workflow.blockers.length, title: "blockers before validation" } : undefined,
    alerts: o?.alerts.open ? { n: o.alerts.open, title: "open alerts" } : undefined,
    cdb: o ? (o.cdb.missing ? { n: o.cdb.missing, title: "fields to complete" } : { dot: "good", title: "ready to sign" }) : undefined,
    sow: o?.sow ? { dot: o.sow.verdict === "plausible" ? "good" : o.sow.verdict === "gap" ? "critical" : "warning", title: o.sow.verdict } : undefined,
    review: o && ["overdue", "due"].includes(o.review.status) ? { dot: o.review.status === "overdue" ? "critical" : "warning", title: `review ${o.review.status}` } : undefined,
    history: unseen ? { n: unseen, title: "new changes" } : undefined,
  };
  const riskTone = LEVEL_TONE[o?.risk.level ?? c.risk_level ?? "none"] ?? "neutral";
  const review = o?.review;

  return (
    <>
      <div className="glass -mx-1 overflow-hidden rounded-[var(--radius-card)] p-0">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 pt-3 pb-2">
          <button className="btn-ghost -ml-2 px-2 py-1 text-xs" onClick={onBack} aria-label="Back to cases">
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[19px] font-semibold tracking-tight">{c.title}</h1>
            <div className="truncate text-[11px] text-slate-500">
              {c.subject_name !== c.title && `${c.subject_name} · `}Created {fmtDate(c.created_at)} · last checked {c.last_run_at ? fmtDate(c.last_run_at) : "never"}
              {c.demo && " · demo data"}
            </div>
          </div>
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
          <p className={`px-4 pb-1 text-[11px] ${refresh.error ? "text-red-600" : "text-slate-500"}`}>{refresh.error ? (refresh.error as Error).message : last}</p>
        )}

        {/* Key figures */}
        <div className="grid grid-cols-2 gap-2 px-4 pb-4 sm:grid-cols-3 xl:grid-cols-6">
          <Tile
            label="Risk score"
            tone={riskTone}
            value={
              <span>
                {(o?.risk.score ?? c.risk_score ?? 0).toFixed(0)}
                <span className="ml-1 text-xs font-medium text-slate-500">/ 100 · {o?.risk.level ?? c.risk_level ?? "—"}</span>
              </span>
            }
            meter={{ value: o?.risk.score ?? c.risk_score ?? 0, max: 100, tone: riskTone }}
            onClick={() => onTab("investigation")}
          />
          <Tile
            label="Vigilance"
            value={o?.vigilance ? <VigilanceBadge level={o.vigilance} /> : <span className="text-base text-slate-400">to assess</span>}
            sub={o?.vigilance ? "from the questionnaire" : "answer the questionnaire"}
            onClick={() => onTab("kyc")}
          />
          <div className="glass-tile col-span-2 flex flex-col justify-between rounded-xl p-3">
            <span className="text-[11px] font-medium text-slate-500">
              Validation · {workflow?.state === "rejected" ? "sent back" : (workflow?.label ?? "—")}
            </span>
            <div className="mt-2 overflow-x-auto">
              <Steps steps={WF_STEPS} current={WF_INDEX[workflow?.state ?? "to_complete"] ?? 0} />
            </div>
            {o && (
              <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
                <Meter className="flex-1" value={o.ready} max={o.readiness.length} tone={o.ready === o.readiness.length ? "good" : "accent"} label="File readiness" />
                {o.ready}/{o.readiness.length} ready
              </div>
            )}
          </div>
          <Tile
            label="Open alerts"
            tone={o?.alerts.open ? "critical" : "good"}
            value={o?.alerts.open ?? "—"}
            sub={o ? `${o.alerts.total} hit(s) · ${o.alerts.triage.dismissed ?? 0} silenced` : undefined}
            onClick={() => onTab("alerts")}
          />
          <Tile
            label="Next review"
            tone={review?.status === "overdue" ? "critical" : review?.status === "due" ? "warning" : review?.status === "not_due" ? "good" : "neutral"}
            value={review?.days_left == null ? "—" : review.days_left < 0 ? `${-review.days_left}d late` : `${review.days_left}d`}
            sub={review?.next_review ? fmtDate(review.next_review) : "no date set"}
            onClick={() => onTab("review")}
          />
        </div>
      </div>

      {/* Tabs */}
      <nav className="glass-bar sticky top-14 z-20 -mx-1 flex gap-1 overflow-x-auto rounded-[var(--radius-card)] border border-slate-200/70 px-3 py-0 dark:border-white/[0.07]" role="tablist">
        {TABS.map((t) => {
          const b = badge[t.id];
          return (
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
              {b?.n ? (
                <span title={b.title} className={`rounded-full px-1.5 text-[10px] font-semibold text-white ${t.id === "history" || t.id === "alerts" ? "bg-red-600" : "bg-amber-500"}`}>
                  {b.n}
                </span>
              ) : b?.dot ? (
                <span title={b.title} className={`h-2 w-2 rounded-full ${DOT[b.dot]}`} />
              ) : null}
              {tab === t.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-brand-500" />}
            </button>
          );
        })}
      </nav>
    </>
  );
}
