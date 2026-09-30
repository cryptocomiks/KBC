import { BellRing, ChevronDown, Download, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { BoBoard, BoReception, ReceptionStatus } from "../../types";
import type { WorkspaceActions } from "../../lib/workspace";
import { downloadCsv } from "../../lib/csv";
import { Meter } from "../viz";

const STATUS: Record<ReceptionStatus, { label: string; cls: string }> = {
  overdue: { label: "Overdue", cls: "bg-[#d70015]/10 text-[#b42318] dark:text-[#ff453a]" },
  awaited: { label: "Awaited", cls: "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]" },
  to_request: { label: "To request", cls: "bg-brand-500/10 text-brand-600 dark:text-[#2997ff]" },
  received: { label: "Received", cls: "bg-[#248a3d]/10 text-[#1b7331] dark:text-[#30d158]" },
};
const ORDER: ReceptionStatus[] = ["overdue", "awaited", "to_request", "received"];
const d = (v?: string | null) => (v ? new Date(v.length === 10 ? `${v}T12:00:00` : v).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
const daysLeft = (v?: string | null) => (v ? Math.round((Date.parse(`${v.slice(0, 10)}T12:00:00`) - Date.now()) / 86_400_000) : null);

/** Every document of every case: what to request, what is awaited, what is late, what arrived. */
export default function Receptions({ board, actions, onRemind }: { board: BoBoard; actions: WorkspaceActions; onRemind: (caseId: string) => void }) {
  const [filter, setFilter] = useState<ReceptionStatus | "open" | "all">("open");
  const [needle, setNeedle] = useState("");
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    board.receptions.forEach((r) => (c[r.status] = (c[r.status] ?? 0) + 1));
    return c;
  }, [board.receptions]);

  const groups = useMemo(() => {
    const n = needle.trim().toLowerCase();
    const map = new Map<string, { title: string; rows: BoReception[]; all: BoReception[] }>();
    for (const r of board.receptions) {
      const g = map.get(r.case_id) ?? { title: r.case_title, rows: [], all: [] };
      g.all.push(r);
      const keep = (filter === "all" || (filter === "open" ? r.status !== "received" : r.status === filter)) && (!n || `${r.document} ${r.case_title}`.toLowerCase().includes(n));
      if (keep) g.rows.push(r);
      map.set(r.case_id, g);
    }
    return [...map.entries()]
      .filter(([, g]) => g.rows.length)
      .map(([id, g]) => ({ id, ...g, rows: g.rows.sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || Number(b.required) - Number(a.required)) }))
      .sort((a, b) => ORDER.indexOf(a.rows[0].status) - ORDER.indexOf(b.rows[0].status));
  }, [board.receptions, filter, needle]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="segmented" role="group" aria-label="Show">
          {(
            [
              ["open", `Open · ${board.receptions.length - (counts.received ?? 0)}`],
              ["overdue", `Overdue · ${counts.overdue ?? 0}`],
              ["awaited", `Awaited · ${counts.awaited ?? 0}`],
              ["to_request", `To request · ${counts.to_request ?? 0}`],
              ["received", `Received · ${counts.received ?? 0}`],
              ["all", "All"],
            ] as const
          ).map(([k, l]) => (
            <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)} className={`rounded-[8px] px-2.5 py-1 text-xs font-medium ${filter === k ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}>
              {l}
            </button>
          ))}
        </div>
        <label className="relative ml-auto">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" aria-hidden />
          <input className="input w-60 py-1 pl-8 text-xs" placeholder="Find a document or a client" aria-label="Find a document or a client" value={needle} onChange={(e) => setNeedle(e.target.value)} />
        </label>
        <button
          className="btn-outline py-1 text-xs"
          onClick={() =>
            downloadCsv(
              `receptions-${new Date().toISOString().slice(0, 10)}.csv`,
              [
                { key: "case_title", label: "Client" },
                { key: "document", label: "Document" },
                { key: "required", label: "Required" },
                { key: "status", label: "Status" },
                { key: "requested_at", label: "Requested" },
                { key: "due_at", label: "Due" },
                { key: "reminders", label: "Reminders" },
                { key: "received_at", label: "Received" },
                { key: "received_by", label: "Received by" },
              ],
              board.receptions.map((r) => ({ ...r, status: STATUS[r.status].label, required: r.required ? "yes" : "no" })),
            )
          }
        >
          <Download className="h-3.5 w-3.5" /> Export CSV
        </button>
      </div>

      {groups.length === 0 && <p className="card p-8 text-center text-sm text-slate-500">Nothing here with this filter.</p>}
      {groups.map((g) => {
        const got = g.all.filter((r) => r.status === "received").length;
        const late = g.all.filter((r) => r.status === "overdue").length;
        const open = !closed.has(g.id);
        return (
          <section key={g.id} className="card overflow-hidden" aria-labelledby={`rc-${g.id}`}>
            <div className="flex flex-wrap items-center gap-3 px-4 py-3">
              <button
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                aria-expanded={open}
                onClick={() =>
                  setClosed((s) => {
                    const n = new Set(s);
                    if (n.has(g.id)) n.delete(g.id);
                    else n.add(g.id);
                    return n;
                  })
                }
              >
                <ChevronDown className={`h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 ${open ? "" : "-rotate-90"}`} aria-hidden />
                <h3 id={`rc-${g.id}`} className="truncate text-[14px] font-semibold">
                  {g.title}
                </h3>
              </button>
              <div className="flex w-full items-center gap-2 sm:w-64">
                <Meter className="flex-1" value={got} max={g.all.length} tone={got === g.all.length ? "good" : late ? "critical" : "accent"} label={`Documents received for ${g.title}`} />
                <span className="text-[12px] whitespace-nowrap text-slate-500 tabular-nums">
                  {got}/{g.all.length}
                </span>
              </div>
              {g.all.some((r) => r.status === "overdue" || r.status === "to_request") && (
                <button className="btn-outline py-1 text-xs" onClick={() => onRemind(g.id)}>
                  <BellRing className="h-3.5 w-3.5" /> {late ? "Send a reminder" : "Send the request"}
                </button>
              )}
            </div>
            {open && (
              <ul className="divide-y divide-black/[0.05] border-t border-black/[0.06] dark:divide-white/[0.06] dark:border-white/[0.08]">
                {g.rows.map((r) => {
                  const left = daysLeft(r.due_at);
                  return (
                    <li key={r.key} className="ws-row grid items-center gap-x-3 gap-y-1 px-4 py-2.5 sm:grid-cols-[24px_minmax(0,1fr)_110px_170px]">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-brand-600"
                        checked={r.status === "received"}
                        onChange={(e) => actions.received(r, e.target.checked)}
                        aria-label={`${r.document}: received`}
                      />
                      <div className="min-w-0">
                        <div className={`text-[13.5px] ${r.status === "received" ? "text-slate-500" : ""}`}>
                          {r.document}
                          {r.required && <span className="ml-1.5 rounded bg-black/[0.05] px-1 text-[10px] font-semibold text-slate-600 uppercase dark:bg-white/[0.08] dark:text-slate-300">required</span>}
                        </div>
                        {r.reason && <div className="truncate text-[11.5px] text-slate-500">{r.reason}</div>}
                      </div>
                      <span className={`justify-self-start rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS[r.status].cls}`}>{STATUS[r.status].label}</span>
                      <div className="text-[11.5px] text-slate-500 tabular-nums">
                        {r.status === "received" ? (
                          <>
                            received {d(r.received_at)}
                            {r.received_by && ` · ${r.received_by}`}
                          </>
                        ) : r.requested_at ? (
                          <>
                            asked {d(r.requested_at)} ·{" "}
                            <span className={left != null && left < 0 ? "font-semibold text-[#b42318] dark:text-[#ff6961]" : ""}>
                              {left == null ? "" : left < 0 ? `${-left} d late` : left === 0 ? "due today" : `${left} d left`}
                            </span>
                            {r.reminders > 0 && ` · ${r.reminders} reminder${r.reminders > 1 ? "s" : ""}`}
                          </>
                        ) : (
                          "not requested yet"
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
