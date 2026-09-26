import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, FileCheck2, ListChecks, Loader2, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { fmtDate } from "../lib/format";
import type { Checklist, ChecklistItem } from "../types";

interface Props {
  caseId: string;
  data: Checklist;
}

function Row({
  item,
  onToggle,
  onRemove,
  busy,
}: {
  item: ChecklistItem;
  onToggle: () => void;
  onRemove?: () => void;
  busy: boolean;
}) {
  return (
    <li className="group flex items-start gap-3 px-3 py-2.5">
      <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-brand-600" checked={item.done} disabled={busy} onChange={onToggle} />
      <div className="min-w-0 flex-1">
        <div className={`text-[13px] leading-snug ${item.done ? "text-slate-500 line-through decoration-slate-400/60" : ""}`}>{item.label}</div>
        {item.reason && !item.done && <div className="text-[11px] text-slate-500">{item.reason}</div>}
        {item.done && (
          <div className="text-[11px] text-[#067647] dark:text-[#47cd89]">
            ✓ {item.by || "done"}
            {item.at && ` · ${fmtDate(item.at)}`}
          </div>
        )}
      </div>
      {item.required !== undefined && (
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
            item.required ? "bg-[#fef3f2] text-[#b42318] dark:bg-[#55160c]/60 dark:text-[#fda29b]" : "bg-slate-100 text-slate-600 dark:bg-white/5 dark:text-slate-300"
          }`}
        >
          {item.required ? "Required" : "Recommended"}
        </span>
      )}
      {onRemove && (
        <button
          className="shrink-0 rounded p-1 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:text-red-600 focus:opacity-100"
          onClick={onRemove}
          aria-label="Remove"
          title="Remove this diligence"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </li>
  );
}

/** Documents received and additional diligences of a case, ticked by the analyst (signed and dated). */
export default function CaseChecklist({ caseId, data }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(true);
  const [text, setText] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["case", caseId] });
  const tick = useMutation({
    mutationFn: (i: ChecklistItem) => api.tick(caseId, i.key, !i.done, analyst.get()),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: () => api.addDiligence(caseId, text),
    onSuccess: () => {
      setText("");
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (key: string) => api.removeDiligence(caseId, key), onSuccess: refresh });
  const busy = tick.isPending || add.isPending || remove.isPending;
  const docsDone = data.documents.filter((d) => d.done).length;
  const dilDone = data.diligences.filter((d) => d.done).length;
  const error = tick.error ?? add.error ?? remove.error;

  return (
    <div className="card overflow-hidden">
      <button className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        <ListChecks className="h-5 w-5 text-brand-600" />
        <div className="min-w-0 flex-1">
          <div className="tag">Case checklist</div>
          <div className="text-[12px] text-slate-500">
            Documents {docsDone}/{data.documents.length} received · diligences {dilDone}/{data.diligences.length} done
          </div>
        </div>
        {busy && <Loader2 className="h-4 w-4 animate-spin text-slate-400" />}
        {data.missing_required.length > 0 ? (
          <span className="rounded-full bg-[#fef3f2] px-2.5 py-0.5 text-[11px] font-semibold text-[#b42318] dark:bg-[#55160c]/60 dark:text-[#fda29b]">
            {data.missing_required.length} required missing
          </span>
        ) : (
          <span className="rounded-full bg-[#ecfdf3] px-2.5 py-0.5 text-[11px] font-semibold text-[#067647] dark:bg-[#053321]/60 dark:text-[#47cd89]">
            Required documents received
          </span>
        )}
      </button>
      {open && (
        <div className="grid gap-4 border-t border-slate-200 p-4 lg:grid-cols-2 dark:border-slate-800 [&>*]:min-w-0">
          <section>
            <h3 className="label mb-2 flex items-center gap-1.5">
              <FileCheck2 className="h-3.5 w-3.5" /> Documents from the client
            </h3>
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-white/5 dark:border-white/10">
              {data.documents.map((d) => (
                <Row key={d.key} item={d} busy={busy} onToggle={() => tick.mutate(d)} />
              ))}
            </ul>
            <p className="mt-1.5 text-[11px] text-slate-500">Tick a document once received and checked. Derived from the findings of the case.</p>
          </section>
          <section>
            <h3 className="label mb-2 flex items-center gap-1.5">
              <ListChecks className="h-3.5 w-3.5" /> Additional diligences
            </h3>
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-white/5 dark:border-white/10">
              {data.diligences.map((d) => (
                <Row key={d.key} item={d} busy={busy} onToggle={() => tick.mutate(d)} onRemove={() => remove.mutate(d.key)} />
              ))}
            </ul>
            <form
              className="mt-2 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (text.trim().length >= 3) add.mutate();
              }}
            >
              <input className="input min-w-0 flex-1 py-1.5 text-sm" placeholder="Add a diligence…" value={text} onChange={(e) => setText(e.target.value)} />
              <button className="btn-outline py-1.5 text-xs" disabled={busy || text.trim().length < 3}>
                <Plus className="h-3.5 w-3.5" /> Add
              </button>
            </form>
            <p className="mt-1.5 text-[11px] text-slate-500">
              Suggested from the vigilance level and the red flags. Optional: remove what does not apply, add your own.
            </p>
          </section>
          {error && <p className="text-xs text-red-600 lg:col-span-2">{(error as Error).message}</p>}
        </div>
      )}
    </div>
  );
}
