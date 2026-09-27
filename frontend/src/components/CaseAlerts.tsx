import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, BrainCircuit, CheckCheck, ChevronDown, ExternalLink, Loader2, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { fmtDate } from "../lib/format";
import type { AlertRow, DecisionValue } from "../types";
import { TRIAGE_SEGMENTS } from "./CaseOverview";
import { BarList, ChartCard, Meter, StackedBar, Tile, TONE } from "./viz";

const TRIAGE: Record<string, { label: string; cls: string }> = {
  likely: { label: "Likely match", cls: "bg-red-500/12 text-red-700 ring-red-500/30 dark:text-red-300" },
  verify: { label: "To check", cls: "bg-amber-500/12 text-amber-700 ring-amber-500/30 dark:text-amber-300" },
  namesake: { label: "Probable namesake", cls: "bg-sky-500/12 text-sky-700 ring-sky-500/30 dark:text-sky-300" },
  dismissed: { label: "Ruled out (memory)", cls: "bg-slate-500/12 text-slate-600 ring-slate-500/25 dark:text-slate-300" },
};
const DECISION_LABEL: Record<string, string> = { confirmed: "Confirmed match", false_positive: "False positive", to_review: "To review" };

function AlertItem({ a, onDecide, busy }: { a: AlertRow; onDecide: (a: AlertRow, d: DecisionValue | "none") => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const t = TRIAGE[a.realert ? "verify" : a.triage] ?? TRIAGE.verify;
  const d = a.decision && !a.decision.stale ? a.decision : null;
  return (
    <li className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${t.cls}`}>
          {a.realert ? "Re-alert" : t.label}
        </span>
        <span className="min-w-0 flex-1 text-[13px] font-medium">
          {a.entity} <span className="text-slate-400">≈</span> {a.matched_name}
          <span className="ml-1.5 text-[11px] font-normal text-slate-500">{a.dataset}</span>
          {a.url && (
            <a href={a.url} target="_blank" rel="noreferrer" className="ml-1 inline-flex text-slate-400 hover:text-brand-600" aria-label="Open the listing">
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </span>
        <span className="flex w-24 items-center gap-1.5" title="Match confidence">
          <Meter className="flex-1" value={a.score} max={100} tone={a.score >= 90 ? "critical" : a.score >= 75 ? "warning" : "neutral"} label="Match confidence" />
          <span className="w-8 text-right font-mono text-[11px] font-semibold">{a.score.toFixed(0)}%</span>
        </span>
        <select
          className="input w-auto py-1 text-xs"
          value={d?.decision ?? "none"}
          disabled={busy}
          onChange={(e) => onDecide(a, e.target.value as DecisionValue | "none")}
          aria-label="Analyst decision"
        >
          <option value="none">— undecided</option>
          <option value="confirmed">Confirmed match</option>
          <option value="false_positive">False positive</option>
          <option value="to_review">To review</option>
        </select>
      </div>
      {a.realert && (
        <div className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] text-amber-800 dark:text-amber-200">
          <b>Came back:</b> {a.reasons[0]?.replace(/^re-alert: /, "")}
        </div>
      )}
      {!a.realert && a.reasons.length > 0 && <p className="mt-1.5 text-[12px] text-slate-500">{a.reasons.join(" · ")}</p>}
      {d && (
        <p className="mt-1.5 text-[12px] text-slate-600 dark:text-slate-400">
          <b>{DECISION_LABEL[d.decision]}</b> by {d.author || "—"} on {fmtDate(d.decided_at)}
          {d.comment && <> — “{d.comment}”</>}
        </p>
      )}
      {a.proposed && !d && (
        <button className="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-brand-700 dark:text-brand-400" onClick={() => setOpen(!open)}>
          <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} /> Proposed justification
        </button>
      )}
      {open && a.proposed && <p className="mt-1 rounded-lg bg-slate-500/5 px-3 py-2 text-[12px] leading-relaxed">{a.proposed}</p>}
    </li>
  );
}

/** Memory of rulings across every case: who ruled what out, on which evidence; revocable. */
function MemoryRegister() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const mem = useQuery({ queryKey: ["memory"], queryFn: api.memory, enabled: open });
  const forget = useMutation({
    mutationFn: (key: string) => api.forget(key),
    onSuccess: (r) => {
      qc.setQueryData(["memory"], r);
      qc.invalidateQueries({ queryKey: ["alerts"] });
    },
  });
  const items = (mem.data?.items ?? []).filter((m) => !q || `${m.item_label} ${m.author} ${m.case_title}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="card p-4">
      <button className="flex w-full items-center gap-2 text-left" onClick={() => setOpen(!open)}>
        <BrainCircuit className="h-5 w-5 text-brand-600" />
        <span className="tag">Alert memory</span>
        <span className="text-xs text-slate-500">every namesake ruled out, in every case — it stays silent until its evidence changes</span>
        <ChevronDown className={`ml-auto h-4 w-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-3">
          <label className="relative block">
            <Search className="absolute top-2.5 left-2.5 h-4 w-4 text-slate-400" />
            <input className="input pl-8 text-sm" placeholder="Filter by name, analyst or case" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          {mem.isLoading && <Loader2 className="mx-auto mt-3 h-4 w-4 animate-spin" />}
          <ul className="mt-2 divide-y divide-slate-200 dark:divide-white/10">
            {items.map((m) => (
              <li key={m.item_key} className="flex items-start gap-3 py-2 text-[12px]">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{m.item_label || m.item_key}</div>
                  <div className="text-slate-500">
                    {fmtDate(m.decided_at)} · {m.author || "—"}
                    {m.case_title && <> · case “{m.case_title}”</>}
                    {" · "}
                    {m.tracked ? (
                      <span className="text-brand-700 dark:text-brand-400">re-alerts if the list entry or our data changes</span>
                    ) : (
                      <span>older ruling (name only)</span>
                    )}
                  </div>
                  {m.comment && <div className="mt-0.5 text-slate-600 dark:text-slate-400">“{m.comment}”</div>}
                </div>
                <button
                  className="btn-ghost px-2 py-1 text-xs text-red-600"
                  disabled={forget.isPending}
                  onClick={() => window.confirm("Revoke this ruling? The alert will come back in every case.") && forget.mutate(m.item_key)}
                >
                  <Trash2 className="h-3.5 w-3.5" /> Revoke
                </button>
              </li>
            ))}
            {!mem.isLoading && !items.length && <li className="py-3 text-center text-xs text-slate-500">No ruling in memory yet.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Alerts tab: triage of every screening alert, batch ruling of namesakes, memory and re-alerts. */
export default function CaseAlerts({ caseId }: { caseId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["alerts", caseId], queryFn: () => api.alerts(caseId) });
  const [name, setName] = useState(analyst.get());
  const [showCleared, setShowCleared] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["alerts", caseId] });
    qc.invalidateQueries({ queryKey: ["case", caseId] });
    qc.invalidateQueries({ queryKey: ["memory"] });
  };
  const batch = useMutation({
    mutationFn: () => api.batchDismiss(caseId, name),
    onSuccess: (r) => {
      analyst.set(name);
      qc.setQueryData(["alerts", caseId], r);
      refresh();
    },
  });
  const decide = useMutation({
    mutationFn: ({ a, d, comment }: { a: AlertRow; d: DecisionValue | "none"; comment: string }) =>
      api.decide(caseId, { item_key: a.key, item_label: a.label, decision: d, comment, author: name }),
    onSuccess: refresh,
  });
  const groups = useMemo(() => {
    const rows = q.data?.alerts ?? [];
    const open = rows.filter((a) => a.triage !== "dismissed" && a.triage !== "namesake" && !(a.decision && !a.decision.stale));
    const namesakes = rows.filter((a) => a.triage === "namesake" && !a.decision);
    const decided = rows.filter((a) => a.decision && !a.decision.stale && a.triage !== "dismissed");
    const cleared = rows.filter((a) => a.triage === "dismissed");
    return { open, namesakes, decided, cleared };
  }, [q.data]);

  if (q.isLoading || !q.data) return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
  const v = q.data;
  const perList = new Map<string, { n: number; open: number }>();
  for (const a of v.alerts) {
    const r = perList.get(a.dataset) ?? { n: 0, open: 0 };
    r.n += 1;
    if (a.triage === "likely" || a.triage === "verify") r.open += 1;
    perList.set(a.dataset, r);
  }
  const byDataset = [...perList.entries()]
    .sort((x, y) => y[1].n - x[1].n)
    .map(([k, r]) => ({ key: k, label: k, value: r.n, sub: r.open ? `${r.open} to decide` : "no open alert", color: r.open ? TONE.warning : TONE.accent }));
  const onDecide = (a: AlertRow, d: DecisionValue | "none") => {
    if (!name.trim()) {
      window.alert("Enter your name first: every ruling is signed.");
      return;
    }
    const comment = d === "none" ? "" : window.prompt("Justification for the audit trail:", d === "false_positive" ? a.proposed ?? "" : "") ?? null;
    if (comment === null) return;
    decide.mutate({ a, d, comment });
  };

  return (
    <div className="panel-enter space-y-4">
      <div className="card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <BellRing className="h-5 w-5 text-brand-600" />
          <span className="tag">Screening alerts</span>
          <label className="ml-auto flex items-center gap-2 text-xs text-slate-500">
            Signed by
            <input className="input w-40 py-1 text-xs" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
          <Tile label="Open alerts" tone={groups.open.length ? "critical" : "good"} value={groups.open.length} sub="likely matches and hits to check" />
          <Tile label="Probable namesakes" tone={groups.namesakes.length ? "warning" : "good"} value={groups.namesakes.length} sub="contradicted by the evidence" />
          <Tile label="Silenced by memory" tone="neutral" value={v.cleared_by_memory} sub="ruled out before, evidence unchanged" />
          <Tile label="Time saved (est.)" tone="accent" value={`${v.minutes_saved} min`} sub={`~${v.minutes_per_alert} min per alert by hand`} />
        </div>
        {groups.namesakes.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl bg-brand-500/8 px-4 py-3 ring-1 ring-brand-500/25">
            <p className="min-w-0 flex-1 text-[13px]">
              <b>{groups.namesakes.length} alert(s)</b> are contradicted by the evidence. Rule them out in one go — each gets a written
              justification (shown below each alert) and is remembered for every other case.
            </p>
            <button
              className="btn-primary"
              disabled={batch.isPending || !name.trim()}
              onClick={() => window.confirm(`Rule out ${groups.namesakes.length} probable namesake(s), signed ${name}?`) && batch.mutate()}
            >
              {batch.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCheck className="h-4 w-4" />} Rule out all namesakes
            </button>
          </div>
        )}
        {batch.data?.dismissed !== undefined && <p className="mt-2 text-xs text-brand-700 dark:text-brand-400">{batch.data.dismissed} alert(s) ruled out and remembered.</p>}
        {(batch.error || decide.error) && <p className="mt-2 text-xs text-red-600">{((batch.error || decide.error) as Error).message}</p>}
        {!v.memory_enabled && <p className="mt-2 text-xs text-amber-700">The memory is off on this server (no password configured).</p>}
      </div>

      {v.alerts.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard
            title="Triage of the alerts"
            sub={`${v.alerts.length} hit(s) on the network`}
            table={{ head: ["Triage", "Alerts"], rows: TRIAGE_SEGMENTS(v.counts).map((x) => [x.label, x.value]) }}
          >
            <StackedBar segments={TRIAGE_SEGMENTS(v.counts)} height={12} />
          </ChartCard>
          <ChartCard
            title="By list"
            sub="where the hits come from"
            table={{ head: ["List", "Hits"], rows: byDataset.map((r) => [r.key, r.value]) }}
          >
            <BarList rows={byDataset.slice(0, 6)} />
          </ChartCard>
        </div>
      )}
      {[
        { title: "To decide", rows: groups.open, empty: "No open alert." },
        { title: "Probable namesakes", rows: groups.namesakes, empty: "" },
        { title: "Decided in this case", rows: groups.decided, empty: "" },
      ]
        .filter((g) => g.rows.length || g.empty)
        .map((g) => (
          <section key={g.title} className="card p-4">
            <h3 className="mb-2 text-[13px] font-semibold">
              {g.title} <span className="font-mono text-xs text-slate-400">{g.rows.length}</span>
            </h3>
            {g.rows.length ? (
              <ul className="space-y-2">
                {g.rows.map((a) => (
                  <AlertItem key={a.key} a={a} onDecide={onDecide} busy={decide.isPending} />
                ))}
              </ul>
            ) : (
              <p className="text-xs text-slate-500">{g.empty}</p>
            )}
          </section>
        ))}
      {groups.cleared.length > 0 && (
        <section className="card p-4">
          <button className="flex w-full items-center gap-2 text-left text-[13px] font-semibold" onClick={() => setShowCleared(!showCleared)}>
            Silenced by memory <span className="font-mono text-xs text-slate-400">{groups.cleared.length}</span>
            <ChevronDown className={`ml-auto h-4 w-4 text-slate-400 transition-transform ${showCleared ? "rotate-180" : ""}`} />
          </button>
          {showCleared && (
            <ul className="mt-2 space-y-2">
              {groups.cleared.map((a) => (
                <AlertItem key={a.key} a={a} onDecide={onDecide} busy={decide.isPending} />
              ))}
            </ul>
          )}
        </section>
      )}
      <MemoryRegister />
    </div>
  );
}
