import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, AlertTriangle, BellRing, Check, FolderOpen, Info, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { fmtDate } from "../lib/format";
import type { CaseChange, CaseView } from "../types";

const SEV = {
  critical: { Icon: AlertOctagon, cls: "text-red-600" },
  warning: { Icon: AlertTriangle, cls: "text-amber-600" },
  info: { Icon: Info, cls: "text-slate-400" },
} as const;

interface Props {
  view: CaseView;
  onDeleted: () => void;
}

/** Case header: status, monitoring, refresh, notes and "what changed" since the previous runs. */
export default function CaseBar({ view, onDeleted }: Props) {
  const { case: c, changes } = view;
  const qc = useQueryClient();
  const [notes, setNotes] = useState(c.notes);
  const [last, setLast] = useState<CaseChange[] | null>(null);
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["case", c.id] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const update = useMutation({ mutationFn: (p: Parameters<typeof api.updateCase>[1]) => api.updateCase(c.id, p), onSuccess: invalidate });
  const refresh = useMutation({
    mutationFn: () => api.refreshCase(c.id),
    onSuccess: (r) => {
      setLast(r.changes);
      invalidate();
    },
  });
  const seen = useMutation({ mutationFn: () => api.markSeen(c.id), onSuccess: invalidate });
  const remove = useMutation({ mutationFn: () => api.deleteCase(c.id), onSuccess: onDeleted });
  const unseen = changes.filter((x) => !x.seen);

  return (
    <div className="card space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <FolderOpen className="h-5 w-5 text-brand-600" />
        <div className="min-w-[200px] flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Case</div>
          <div className="text-base font-semibold">{c.title}</div>
          <div className="text-[11px] text-slate-500">
            Created {fmtDate(c.created_at)} · last checked {c.last_run_at ? fmtDate(c.last_run_at) : "never"}
            {c.demo && " · demo data"}
          </div>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs">
          <input type="checkbox" className="accent-brand-600" checked={c.monitor} onChange={(e) => update.mutate({ monitor: e.target.checked })} />
          <BellRing className="h-3.5 w-3.5" /> Daily monitoring
        </label>
        <select className="input py-1 text-xs" value={c.status} onChange={(e) => update.mutate({ status: e.target.value as "open" | "closed" })}>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
        </select>
        <button className="btn-outline py-1.5 text-xs" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          {refresh.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Re-check now
        </button>
        <button
          className="btn-ghost py-1.5 text-xs text-red-600"
          onClick={() => window.confirm(`Delete the case “${c.title}” and its decisions?`) && remove.mutate()}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {refresh.error && <p className="text-xs text-red-600">{(refresh.error as Error).message}</p>}
      {last && (
        <p className="rounded bg-slate-50 px-3 py-2 text-xs dark:bg-slate-800">
          {last.length ? `${last.length} change(s) found by this check — listed below.` : "Checked just now: nothing changed."}
        </p>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              What changed {unseen.length > 0 && <span className="ml-1 rounded bg-red-600 px-1.5 text-[10px] text-white">{unseen.length} new</span>}
            </span>
            {unseen.length > 0 && (
              <button className="btn-ghost py-0.5 text-[11px]" onClick={() => seen.mutate()}>
                <Check className="h-3 w-3" /> Mark as seen
              </button>
            )}
          </div>
          {changes.length === 0 ? (
            <p className="text-xs text-slate-500">No change since the case was created. Checks run daily when monitoring is on.</p>
          ) : (
            <ul className="max-h-48 space-y-1 overflow-auto pr-1">
              {changes.map((x) => {
                const { Icon, cls } = SEV[x.severity] ?? SEV.info;
                return (
                  <li key={x.id ?? x.description} className={`flex gap-2 text-xs ${x.seen ? "opacity-60" : ""}`}>
                    <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${cls}`} />
                    <span>
                      <span className="font-mono text-[10px] text-slate-500">{x.run_at?.slice(0, 10)}</span> {x.description}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Analyst notes</div>
          <textarea
            className="input h-28 w-full resize-y text-sm"
            placeholder="Context, documents requested, decisions taken…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => notes !== c.notes && update.mutate({ notes })}
          />
        </div>
      </div>
    </div>
  );
}
