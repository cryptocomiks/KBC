import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, Check, Copy, FileWarning, Loader2, Mail, PlayCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { openEmail } from "../lib/email";
import { fmtDate } from "../lib/format";
import type { CaseTab } from "../lib/route";
import type { ReviewPack } from "../types";
import { ChartCard, StackedBar, Tile, TONE } from "./viz";

const STATUS: Record<ReviewPack["status"], { label: string; cls: string }> = {
  overdue: { label: "Overdue", cls: "bg-red-500/12 text-red-700 ring-red-500/30 dark:text-red-300" },
  due: { label: "Due within 30 days", cls: "bg-amber-500/12 text-amber-700 ring-amber-500/30 dark:text-amber-300" },
  not_due: { label: "Not due yet", cls: "bg-brand-500/12 text-brand-700 ring-brand-500/30 dark:text-brand-300" },
  not_set: { label: "No date set", cls: "bg-slate-500/12 text-slate-600 ring-slate-500/25 dark:text-slate-300" },
};
const DOC: Record<string, string> = {
  ok: "text-brand-700 dark:text-brand-400",
  expired: "text-red-700 dark:text-red-300",
  missing: "text-red-700 dark:text-red-300",
  expiring: "text-amber-700 dark:text-amber-300",
  stale: "text-amber-700 dark:text-amber-300",
  not_received: "text-slate-500",
};
const DOC_SEGMENTS = (docs: ReviewPack["documents"]) => {
  const n = (st: string[]) => docs.filter((d) => st.includes(d.status)).length;
  return [
    { key: "ok", label: "Valid", value: n(["ok"]), color: TONE.good },
    { key: "stale", label: "Too old / expiring", value: n(["stale", "expiring"]), color: TONE.warning },
    { key: "expired", label: "Expired or missing", value: n(["expired", "missing"]), color: TONE.critical },
    { key: "not_received", label: "Optional, not received", value: n(["not_received"]), color: TONE.neutral },
  ];
};

/** Last validation → next review, with today on the line. */
function Timeline({ from, to, basis }: { from: string | null; to: string | null; basis: string }) {
  if (!from || !to) return <p className="text-xs text-slate-500">Set the next review date by answering the questionnaire.</p>;
  const a = new Date(from).getTime();
  const b = new Date(to).getTime();
  const now = Date.now();
  const span = Math.max(1, b - a);
  const pos = Math.max(0, Math.min(100, (100 * (now - a)) / span));
  const late = now > b;
  return (
    <div className="pt-6 pb-1">
      <div className="relative h-2.5 rounded-full" style={{ background: "var(--viz-track)" }}>
        <div className="bar-x absolute inset-y-0 left-0 rounded-full" style={{ width: `${pos}%`, background: late ? TONE.critical : pos > 90 ? TONE.warning : TONE.accent }} />
        <div className="absolute -top-6 -translate-x-1/2 text-[10.5px] font-semibold whitespace-nowrap" style={{ left: `${pos}%` }}>
          today
        </div>
        <div className="absolute -top-1.5 h-5.5 w-0.5 -translate-x-1/2 rounded bg-slate-900 dark:bg-white" style={{ left: `${pos}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-[11px] text-slate-500">
        <span>
          {basis === "validation" ? "last validation" : "file opened"} <b className="text-slate-800 dark:text-slate-200">{fmtDate(from)}</b>
        </span>
        <span>
          next review <b className="text-slate-800 dark:text-slate-200">{fmtDate(to)}</b>
        </span>
      </div>
    </div>
  );
}

const SEV: Record<string, string> = {
  critical: "border-red-500/40 bg-red-500/8",
  warning: "border-amber-500/40 bg-amber-500/8",
  info: "border-slate-300 dark:border-white/10",
};

/** Periodic review: only what changed since the last validation and only what is missing. */
export default function PeriodicReview({ caseId, onTab }: { caseId: string; onTab: (t: CaseTab) => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["review", caseId], queryFn: () => api.review(caseId) });
  const [name, setName] = useState(analyst.get());
  const [copied, setCopied] = useState(false);
  const start = useMutation({
    mutationFn: () => api.startReview(caseId, name),
    onSuccess: (r) => {
      analyst.set(name);
      qc.setQueryData(["review", caseId], r);
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["alerts", caseId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  if (q.isLoading || !q.data) return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
  const r = q.data;
  const s = STATUS[r.status];
  const ok = r.documents.filter((d) => d.status === "ok").length;

  return (
    <div className="panel-enter space-y-4">
      <div className="card p-4">
        <div className="flex flex-wrap items-center gap-3">
          <CalendarClock className="h-5 w-5 text-brand-600" />
          <span className="tag">Periodic review</span>
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${s.cls}`}>{s.label}</span>
          <span className="text-xs text-slate-500">
            Next review {r.next_review ? fmtDate(r.next_review) : "—"}
            {r.days_left != null && ` (${r.days_left < 0 ? `${-r.days_left} days late` : `in ${r.days_left} days`})`} ·{" "}
            {r.last_review_basis === "validation" ? "last validation" : "file opened"}{" "}
            {r.last_review ? fmtDate(r.last_review) : "—"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <input className="input w-36 py-1 text-xs" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-primary py-1.5 text-xs" disabled={start.isPending || !name.trim()} onClick={() => start.mutate()} title="Re-check with today's data, record the review and reopen the case">
              {start.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <PlayCircle className="h-3.5 w-3.5" />} Start the review
            </button>
          </div>
        </div>
        <p className="mt-2 text-[12px] text-slate-500">
          Starting the review re-runs every check with today's data, records the review in the file and sends a validated case back to the analyst
          (four-eyes validation at the end, as at onboarding).
        </p>
        {r.warning && <p className="mt-2 text-xs text-amber-700">{r.warning}</p>}
        {start.error && <p className="mt-2 text-xs text-red-600">{(start.error as Error).message}</p>}
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Tile
          hero
          label={r.status === "overdue" ? "Review overdue by" : "Next review in"}
          tone={r.status === "overdue" ? "critical" : r.status === "due" ? "warning" : r.status === "not_due" ? "good" : "neutral"}
          value={r.days_left == null ? "—" : `${Math.abs(r.days_left)} days`}
          sub={s.label}
        />
        <ChartCard title="Review cycle" sub={`the bar fills from the ${r.last_review_basis === "validation" ? "last validation" : "opening of the file"} to the review date`}>
          <Timeline from={r.last_review} to={r.next_review} basis={r.last_review_basis} />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Documents on file"
          sub={`${r.documents.length} document(s) checked against their validity rules`}
          table={{ head: ["Document", "Status", "Why"], rows: r.documents.map((d) => [d.label, d.status.replace("_", " "), d.why]) }}
        >
          <StackedBar segments={DOC_SEGMENTS(r.documents)} height={12} />
        </ChartCard>
        <ChartCard
          title="Changes since the last validation"
          sub="from the daily monitoring"
          table={{ head: ["Severity", "Changes"], rows: (["critical", "warning", "info"] as const).map((k) => [k, r.changes_count[k] ?? 0]) }}
        >
          <StackedBar
            height={12}
            segments={[
              { key: "critical", label: "Critical", value: r.changes_count.critical ?? 0, color: TONE.critical },
              { key: "warning", label: "Warning", value: r.changes_count.warning ?? 0, color: TONE.warning },
              { key: "info", label: "Information", value: r.changes_count.info ?? 0, color: TONE.neutral },
            ]}
          />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card p-4">
          <span className="tag">What to do</span>
          <ul className="mt-3 space-y-2">
            {r.actions.map((a) => (
              <li key={a.text} className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-[13px] ${SEV[a.severity] ?? SEV.info}`}>
                <span className="min-w-0 flex-1">{a.text}</span>
                <button className="btn-ghost shrink-0 px-2 py-1 text-xs" onClick={() => onTab(a.tab as CaseTab)}>
                  Open <ArrowRight className="h-3 w-3" />
                </button>
              </li>
            ))}
          </ul>
          {r.vigilance.saved && (
            <p className="mt-3 text-[12px] text-slate-500">
              Vigilance: {r.vigilance.saved} at the last assessment, {r.vigilance.now ?? "—"} with today's answers.
            </p>
          )}
        </div>

        <div className="card p-4">
          <div className="flex items-center gap-2">
            <FileWarning className="h-5 w-5 text-slate-400" />
            <span className="tag">Documents</span>
            <span className="ml-auto text-xs text-slate-500">
              {ok} still valid · {r.to_renew.length} to renew or obtain
            </span>
          </div>
          <ul className="mt-3 max-h-80 space-y-1 overflow-y-auto pr-1">
            {r.documents.map((d) => (
              <li key={d.label} className="flex items-start gap-2 text-[12.5px]">
                <span className={`w-24 shrink-0 text-[10px] font-semibold uppercase ${DOC[d.status]}`}>{d.status.replace("_", " ")}</span>
                <span className="min-w-0 flex-1">
                  {d.label}
                  <span className="text-slate-500"> — {d.why}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-slate-500">
            Rules: register extracts and financial statements over 12 months are renewed; identity documents on their expiry date (write it in the
            checklist note, e.g. “expires 2027-03-31”).
          </p>
        </div>
      </div>

      <div className="card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Mail className="h-5 w-5 text-brand-600" />
          <span className="tag">E-mail to the client</span>
          <span className="text-xs text-slate-500">asks only for what is missing or out of date</span>
          <div className="ml-auto flex gap-2">
            <button
              className="btn-ghost py-1 text-xs"
              onClick={() => {
                navigator.clipboard?.writeText(`${r.email.subject}\n\n${r.email.body}`);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} Copy
            </button>
            <button className="btn-primary py-1.5 text-xs" onClick={() => openEmail(r.email.subject, r.email.body)}>
              <Mail className="h-3.5 w-3.5" /> Open in my mail app
            </button>
          </div>
        </div>
        <div className="mt-3 rounded-xl bg-slate-500/5 p-3 text-[12.5px] whitespace-pre-line">
          <b>{r.email.subject}</b>
          {"\n\n"}
          {r.email.body}
        </div>
      </div>

      {(r.changes.length > 0 || r.open_alerts.length > 0) && (
        <div className="card p-4">
          <span className="tag">Since the last validation</span>
          <ul className="mt-3 space-y-1 text-[12.5px]">
            {r.open_alerts.map((a) => (
              <li key={a.label} className="text-amber-800 dark:text-amber-200">
                Open alert — {a.label} ({a.score.toFixed(0)}%)
              </li>
            ))}
            {r.changes.slice(0, 40).map((c) => (
              <li key={c.id} className="text-slate-600 dark:text-slate-400">
                <span className="font-mono text-[11px] text-slate-400">{fmtDate(c.run_at)}</span> {c.description}
              </li>
            ))}
          </ul>
        </div>
      )}

      {r.reviews.length > 0 && (
        <div className="card p-4">
          <span className="tag">Review history</span>
          <ul className="mt-2 space-y-1 text-[12px] text-slate-600 dark:text-slate-400">
            {r.reviews.map((x) => (
              <li key={x.started_at}>
                {fmtDate(x.started_at)} — started by {x.by} · {x.changes} change(s), {x.actions} action(s)
                {x.due && ` · was due ${fmtDate(x.due)}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
