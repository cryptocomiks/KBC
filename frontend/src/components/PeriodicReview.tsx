import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CalendarClock, Check, Copy, FileWarning, Loader2, Mail, PlayCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { openEmail } from "../lib/email";
import { fmtDate } from "../lib/format";
import type { CaseTab } from "../lib/route";
import type { ReviewPack } from "../types";

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
          <div className="mt-4 grid grid-cols-3 gap-2 text-center">
            {(["critical", "warning", "info"] as const).map((k) => (
              <div key={k} className="rounded-lg border border-slate-200 py-2 dark:border-white/10">
                <div className="text-lg font-semibold">{r.changes_count[k] ?? 0}</div>
                <div className="text-[10px] text-slate-500 uppercase">{k} changes</div>
              </div>
            ))}
          </div>
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
