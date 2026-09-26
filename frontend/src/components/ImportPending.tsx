import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Building2, Clock, Loader2, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { countryName, flag } from "../lib/format";
import type { CaseView, ImportChoice } from "../types";

const STATE: Record<string, { label: string; cls: string }> = {
  pending: { label: "Waiting: company to find", cls: "text-slate-500" },
  resolved: { label: "Company found: analysis waiting", cls: "text-slate-500" },
  ambiguous: { label: "Several companies match", cls: "text-amber-600" },
  not_found: { label: "Company not found", cls: "text-amber-600" },
  error: { label: "Analysis failed", cls: "text-red-600" },
};

interface Props {
  view: CaseView;
  onBack: () => void;
}

/** An imported client line not analysed yet: find / pick its company, then analyse it. */
export default function ImportPending({ view, onBack }: Props) {
  const c = view.case;
  const info = c.import_info ?? {};
  const qc = useQueryClient();
  const [q, setQ] = useState(info.name || info.query || "");
  const [searched, setSearched] = useState<string | null>(null);
  const search = useQuery({
    queryKey: ["search", searched, "company"],
    queryFn: () => api.search(searched!, "company"),
    enabled: !!searched,
  });
  const run = useMutation({
    mutationFn: async (record_ids?: string[]) => {
      if (record_ids) await api.resolveCase(c.id, record_ids);
      // find the company (if still to find), then investigate it
      for (let i = 0; i < 2; i++) {
        const r = await api.importNext(c.id);
        if (!r.step || r.step.state !== "resolved") break;
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["case", c.id] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const remove = useMutation({ mutationFn: () => api.deleteCase(c.id), onSuccess: onBack });
  const state = STATE[c.import_state ?? ""] ?? STATE.pending;
  const choices: ImportChoice[] = searched
    ? (search.data?.candidates ?? [])
        .filter((x) => x.entity.type === "company")
        .map((x) => ({
          record_ids: x.entity.record_ids,
          name: x.entity.name,
          jurisdiction: x.entity.jurisdiction,
          registration_number: x.entity.registration_number,
          status: x.entity.status,
          score: x.score,
        }))
    : (info.choices ?? []);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <button className="btn-ghost text-xs" onClick={onBack}>
        <ArrowLeft className="h-3.5 w-3.5" /> Cases
      </button>
      <div className="card space-y-4 p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="tag">Imported client</div>
            <h1 className="mt-1 text-lg font-semibold">{c.title}</h1>
            <div className="mt-1 text-xs text-slate-500">
              {info.line ? `Line ${info.line}` : ""}
              {info.identifier && ` · identifier ${info.identifier}`}
              {info.country && ` · ${flag(info.country)} ${countryName(info.country)}`}
            </div>
          </div>
          <button
            className="btn-ghost py-1.5 text-xs text-red-600"
            onClick={() => window.confirm(`Delete “${c.title}” from the cases?`) && remove.mutate()}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className={`flex items-center gap-2 text-sm font-medium ${state.cls}`}>
          {c.import_state === "pending" || c.import_state === "resolved" ? <Clock className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {state.label}
          {info.note && <span className="font-normal text-slate-500">— {info.note}</span>}
        </div>
        {(c.import_state === "pending" || c.import_state === "resolved" || c.import_state === "error") && (
          <button className="btn-primary" disabled={run.isPending} onClick={() => run.mutate(undefined)}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            {c.import_state === "error" ? "Retry the analysis" : "Analyse now"}
          </button>
        )}
        {run.isPending && <p className="text-xs text-slate-500">Searching the registers and screening the network — up to a few minutes…</p>}
        {run.error && <p className="text-xs text-red-600">{(run.error as Error).message}</p>}

        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (q.trim()) setSearched(q.trim());
          }}
        >
          <input className="input min-w-0 flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company name, SIREN, LEI, UID…" />
          <button className="btn-outline" type="submit">
            <Search className="h-4 w-4" /> Search
          </button>
        </form>
        {search.isFetching && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Searching the registers…
          </div>
        )}
        {choices.length > 0 && (
          <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200 dark:divide-white/5 dark:border-white/10">
            {choices.map((x) => (
              <li key={x.record_ids.join("|")} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                <Building2 className="h-4 w-4 text-slate-400" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{x.name}</div>
                  <div className="text-[11px] text-slate-500">
                    {x.jurisdiction && `${flag(x.jurisdiction)} ${countryName(x.jurisdiction)}`}
                    {x.registration_number && ` · ${x.registration_number}`}
                    {x.status && ` · ${x.status}`} · match {Math.round(x.score)}%
                  </div>
                </div>
                <button className="btn-outline py-1 text-xs" disabled={run.isPending} onClick={() => run.mutate(x.record_ids)}>
                  This one
                </button>
              </li>
            ))}
          </ul>
        )}
        {searched && !search.isFetching && choices.length === 0 && <p className="text-xs text-slate-500">No company found for “{searched}”.</p>}
      </div>
    </div>
  );
}
