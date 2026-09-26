import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, CornerUpLeft, History, Loader2, RotateCcw, Send, ShieldCheck, UserRound } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { fmtDate } from "../lib/format";
import type { WorkflowAction, WorkflowState, WorkflowView } from "../types";

const STEPS: { state: WorkflowState[]; label: string }[] = [
  { state: ["to_complete", "rejected"], label: "To complete" },
  { state: ["pending_validation"], label: "Awaiting validation" },
  { state: ["validated"], label: "Validated" },
];
const ACTION_LABEL: Record<WorkflowAction, string> = {
  submit: "Sent for validation",
  validate: "Validated",
  reject: "Sent back",
  reopen: "Reopened",
};

interface Props {
  caseId: string;
  view: WorkflowView;
}

/** Case status with the four-eyes validation: to complete → awaiting validation → validated. */
export default function CaseWorkflow({ caseId, view }: Props) {
  const qc = useQueryClient();
  const [name, setName] = useState(analyst.get());
  const [showHistory, setShowHistory] = useState(false);
  const act = useMutation({
    mutationFn: ({ action, comment }: { action: WorkflowAction; comment?: string }) =>
      api.workflowAction(caseId, action, name, comment ?? ""),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const run = (action: WorkflowAction, askComment = false) => {
    if (!name.trim()) {
      const n = window.prompt("Your name (signed in the audit trail):")?.trim();
      if (!n) return;
      setName(n);
      analyst.set(n);
    }
    let comment = "";
    if (askComment) {
      comment = window.prompt(action === "reject" ? "Why is the case sent back? (required)" : "Why reopen the case? (required)") ?? "";
      if (!comment.trim()) return;
    }
    act.mutate({ action, comment });
  };
  const current = STEPS.findIndex((s) => s.state.includes(view.state));
  const ownSubmission = !!name && name.trim().toLowerCase() === (view.submitted_by ?? "").toLowerCase();

  return (
    <div className="card space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-brand-600" />
          <span className="tag">Validation</span>
        </div>
        {/* Stepper */}
        <ol className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5 text-xs">
          {STEPS.map((s, i) => {
            const done = i < current || view.state === "validated";
            const active = i === current;
            return (
              <li key={s.label} className="flex items-center gap-1.5">
                {i > 0 && <span className={`h-px w-6 ${i <= current ? "bg-brand-500" : "bg-slate-300 dark:bg-white/15"}`} />}
                <span
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-medium ${
                    active
                      ? view.state === "rejected"
                        ? "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/40 dark:text-amber-300"
                        : "bg-brand-500/15 text-slate-900 ring-1 ring-brand-500/50 dark:text-white"
                      : done
                        ? "text-brand-700 dark:text-brand-400"
                        : "text-slate-400"
                  }`}
                >
                  {done && !active ? <Check className="h-3 w-3" /> : <span className="font-mono text-[10px]">{i + 1}</span>}
                  {active && view.state === "rejected" ? "Sent back — to complete" : s.label}
                </span>
              </li>
            );
          })}
        </ol>
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          <UserRound className="h-3.5 w-3.5" />
          <input
            className="input w-36 py-1 text-xs"
            placeholder="Your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => analyst.set(name)}
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(view.state === "to_complete" || view.state === "rejected") && (
          <button className="btn-primary" disabled={act.isPending || view.blockers.length > 0} onClick={() => run("submit")}>
            {act.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Send for validation
          </button>
        )}
        {view.state === "pending_validation" && (
          <>
            <button
              className="btn-primary"
              disabled={act.isPending || ownSubmission}
              title={ownSubmission ? "Four-eyes principle: another person must validate" : undefined}
              onClick={() => run("validate")}
            >
              {act.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Validate the case
            </button>
            <button className="btn-outline" disabled={act.isPending} onClick={() => run("reject", true)}>
              <CornerUpLeft className="h-4 w-4" /> Send back
            </button>
            <span className="text-xs text-slate-500">
              Sent by <b>{view.submitted_by}</b>
              {ownSubmission && " — another person must validate (four-eyes principle)"}
            </span>
          </>
        )}
        {view.state === "validated" && (
          <>
            <span className="inline-flex items-center gap-1.5 text-sm font-medium text-[#067647] dark:text-[#47cd89]">
              <CheckCircle2 className="h-4 w-4" /> Validated by {view.validated_by}
              {view.validated_at && ` on ${fmtDate(view.validated_at)}`}
            </span>
            <button className="btn-outline py-1 text-xs" disabled={act.isPending} onClick={() => run("reopen", true)}>
              <RotateCcw className="h-3.5 w-3.5" /> Reopen (review)
            </button>
          </>
        )}
        {view.history.length > 0 && (
          <button className="btn-ghost ml-auto py-1 text-xs" onClick={() => setShowHistory((s) => !s)}>
            <History className="h-3.5 w-3.5" /> History ({view.history.length})
          </button>
        )}
      </div>

      {(view.state === "to_complete" || view.state === "rejected") && view.blockers.length > 0 && (
        <ul className="rounded-xl bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
          <li className="mb-0.5 font-semibold">Before sending for validation:</li>
          {view.blockers.map((b) => (
            <li key={b}>• {b}</li>
          ))}
        </ul>
      )}
      {view.state === "rejected" && view.history[0]?.action === "reject" && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          Sent back by {view.history[0].by}: “{view.history[0].comment}”
        </p>
      )}
      {act.error && <p className="text-xs text-red-600">{(act.error as Error).message}</p>}
      {showHistory && (
        <ul className="space-y-1 border-t border-slate-200 pt-2 text-xs dark:border-white/10">
          {view.history.map((h, i) => (
            <li key={i} className="flex flex-wrap gap-x-2">
              <span className="font-mono text-[10px] text-slate-500">{h.at.slice(0, 16).replace("T", " ")}</span>
              <b>{ACTION_LABEL[h.action] ?? h.action}</b> by {h.by}
              {h.comment && <span className="text-slate-500">— {h.comment}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
