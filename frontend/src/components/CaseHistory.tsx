import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, AlertTriangle, Check, Info } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { CaseView } from "../types";

const SEV = {
  critical: { Icon: AlertOctagon, cls: "text-red-600" },
  warning: { Icon: AlertTriangle, cls: "text-amber-600" },
  info: { Icon: Info, cls: "text-slate-400" },
} as const;
const STEP: Record<string, string> = { submit: "Sent for validation", validate: "Validated", reject: "Sent back", reopen: "Reopened" };
const DECISION: Record<string, string> = { confirmed: "Confirmed", false_positive: "False positive", to_review: "To review" };
const when = (s?: string | null) => (s ?? "").slice(0, 16).replace("T", " ");

/** What changed (monitoring), analyst notes, validation steps and screening decisions: the case's audit trail. */
export default function CaseHistory({ view }: { view: CaseView }) {
  const { case: c, changes, decisions, workflow } = view;
  const qc = useQueryClient();
  const [notes, setNotes] = useState(c.notes);
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["case", c.id] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const save = useMutation({ mutationFn: () => api.updateCase(c.id, { notes }), onSuccess: invalidate });
  const seen = useMutation({ mutationFn: () => api.markSeen(c.id), onSuccess: invalidate });
  const unseen = changes.filter((x) => !x.seen).length;

  return (
    <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
      <section className="card p-4">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="tag">What changed</h2>
          {unseen > 0 && (
            <button className="btn-ghost py-0.5 text-[11px]" onClick={() => seen.mutate()}>
              <Check className="h-3 w-3" /> Mark {unseen} as seen
            </button>
          )}
        </div>
        {changes.length === 0 ? (
          <p className="text-xs text-slate-500">No change since the case was created. Checks run daily when monitoring is on.</p>
        ) : (
          <ul className="max-h-[420px] space-y-1.5 overflow-auto pr-1">
            {changes.map((x) => {
              const { Icon, cls } = SEV[x.severity] ?? SEV.info;
              return (
                <li key={x.id ?? x.description} className={`flex gap-2 text-xs ${x.seen ? "opacity-60" : ""}`}>
                  <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${cls}`} />
                  <span>
                    <span className="font-mono text-[10px] text-slate-500">{x.run_at?.slice(0, 10)}</span> {x.description}
                    {!x.seen && <span className="ml-1 rounded bg-red-600 px-1 text-[9px] font-semibold text-white">NEW</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="card p-4">
        <h2 className="tag mb-2">Analyst notes</h2>
        <textarea
          className="input h-40 w-full resize-y text-sm"
          placeholder="Context, calls with the client, decisions taken…"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => notes !== c.notes && save.mutate()}
        />
        <p className="mt-1 text-[11px] text-slate-500">{save.isPending ? "Saving…" : save.isSuccess ? "Saved." : "Saved automatically when you leave the field."}</p>
      </section>

      <section className="card p-4">
        <h2 className="tag mb-2">Validation steps</h2>
        {!workflow?.history.length ? (
          <p className="text-xs text-slate-500">Not sent for validation yet.</p>
        ) : (
          <ol className="relative space-y-3 border-l border-slate-200 pl-4 dark:border-white/10">
            {workflow.history.map((h, i) => (
              <li key={i} className="text-xs">
                <span className="absolute -left-[5px] mt-1 h-2.5 w-2.5 rounded-full bg-brand-500" />
                <div>
                  <b>{STEP[h.action] ?? h.action}</b> by {h.by} <span className="font-mono text-[10px] text-slate-500">{when(h.at)}</span>
                </div>
                {h.comment && <div className="text-slate-500">{h.comment}</div>}
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="card p-4">
        <h2 className="tag mb-2">Screening decisions</h2>
        {decisions.length === 0 ? (
          <p className="text-xs text-slate-500">No hit reviewed yet. Decide on each hit in the Investigation tab (confirmed, false positive, to review).</p>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {decisions.map((d) => (
              <li key={d.item_key}>
                <b>{DECISION[d.decision] ?? d.decision}</b> — {d.item_label || d.item_key}
                <span className="ml-1 font-mono text-[10px] text-slate-500">{when(d.decided_at)}</span>
                {d.comment && <div className="text-slate-500">{d.comment}</div>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
