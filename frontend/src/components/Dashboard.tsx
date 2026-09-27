import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  AlertTriangle,
  BellRing,
  CalendarClock,
  CheckCircle2,
  FolderOpen,
  Info,
  Loader2,
  Lock,
  PencilLine,
  ShieldAlert,
  Stamp,
} from "lucide-react";
import { useState } from "react";
import { api, auth, AuthError } from "../api";
import { countryName, flag, fmtDate } from "../lib/format";
import type { CasesStatus, Queue } from "../types";
import ImportPanel from "./ImportPanel";
import { VigilanceBadge } from "./KycQuestionnaire";
import PasswordGate from "./PasswordGate";
import { BarList, ChartCard, Columns, Meter, StackedBar, Tile, TONE, type Tone } from "./viz";

const QUEUES: { key: Queue; title: string; sub: string; Icon: typeof ShieldAlert; tone: Tone }[] = [
  { key: "sensitive", title: "Sensitive", sub: "PEP / sanctions to review", Icon: ShieldAlert, tone: "critical" },
  { key: "to_validate", title: "To validate", sub: "awaiting a second person", Icon: Stamp, tone: "serious" },
  { key: "to_complete", title: "To complete", sub: "documents, questionnaire", Icon: PencilLine, tone: "warning" },
  { key: "review_due", title: "Review due", sub: "within 30 days", Icon: CalendarClock, tone: "warning" },
  { key: "validated", title: "Validated", sub: "accepted clients", Icon: CheckCircle2, tone: "good" },
];
const STATE_LABEL: Record<string, string> = {
  to_complete: "to complete",
  pending_validation: "to validate",
  validated: "validated",
  rejected: "sent back",
};
const IMPORT_LABEL: Record<string, string> = {
  pending: "in the queue",
  resolved: "analysis waiting",
  ambiguous: "pick the company",
  not_found: "not found",
  error: "failed",
};
const RISK: { key: string; label: string; tone: Tone }[] = [
  { key: "critical", label: "Critical", tone: "critical" },
  { key: "high", label: "High", tone: "serious" },
  { key: "medium", label: "Medium", tone: "warning" },
  { key: "low", label: "Low / no flag", tone: "good" },
  { key: "incomplete", label: "Not screened", tone: "neutral" },
];
const riskCount = (by: Record<string, number>, key: string) => (by[key] ?? 0) + (key === "low" ? (by.none ?? 0) : 0);
const RISK_TONE: Record<string, Tone> = { critical: "critical", high: "serious", medium: "warning", low: "good", none: "good", incomplete: "neutral" };
const VIG: { key: string; label: string; color: string }[] = [
  { key: "enhanced", label: "Enhanced", color: TONE.critical },
  { key: "standard", label: "Standard", color: TONE.warning },
  { key: "simplified", label: "Simplified", color: TONE.good },
  { key: "to_assess", label: "To assess", color: TONE.neutral },
];
const SEV = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;
const daysTo = (d: string) => Math.round((new Date(d).getTime() - Date.now()) / 86_400_000);

interface Props {
  status?: CasesStatus;
  onOpenCase: (id: string) => void;
}

/** All cases at a glance: key figures, work queues, portfolio risk, monitoring activity. */
export default function Dashboard({ status, onOpenCase }: Props) {
  const [attempt, setAttempt] = useState(0);
  const [queue, setQueue] = useState<Queue | null>(null);
  const q = useQuery({ queryKey: ["dashboard", attempt], queryFn: api.dashboard, retry: false, enabled: status?.enabled !== false });

  if (status && !status.enabled) {
    return <div className="card mx-auto max-w-xl p-6 text-sm text-amber-700 dark:text-amber-300">{status.message}</div>;
  }
  if (q.error instanceof AuthError) return <PasswordGate wrong={attempt > 0} onUnlock={() => setAttempt((a) => a + 1)} />;
  if (q.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-24 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" /> Loading cases…
      </div>
    );
  }
  if (q.error) return <div className="card p-6 text-sm text-red-600">{(q.error as Error).message}</div>;
  const d = q.data!;
  const analysed = d.cases.filter((c) => !c.import_state);
  const total = d.cases.length;
  const unseen = d.cases.reduce((n, c) => n + (c.unseen_changes ?? 0), 0);
  const monitored = d.cases.filter((c) => c.monitor && c.status === "open").length;
  const risky = (d.by_level.high ?? 0) + (d.by_level.critical ?? 0);
  const days = d.changes_by_day ?? [];
  const changes30 = days.reduce((n, x) => n + x.critical + x.warning + x.info, 0);
  const critical30 = days.reduce((n, x) => n + x.critical, 0);
  const rows = d.cases.filter((c) => !queue || c.queue === queue);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Cases</h1>
          <p className="text-xs text-slate-500">
            Your client portfolio, re-checked daily when monitoring is on. Storage: {status?.storage ?? "—"}
            {status?.message && <span className="ml-1 text-amber-600">· {status.message}</span>}
          </p>
        </div>
        <button
          className="btn-ghost text-xs"
          onClick={() => {
            auth.clear();
            setAttempt((a) => a + 1);
          }}
        >
          <Lock className="h-3.5 w-3.5" /> Lock
        </button>
      </div>

      {/* Key figures */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Tile hero label="Cases" value={total} sub={`${monitored} monitored daily`} />
        <Tile
          label="High or critical risk"
          tone={risky ? "critical" : "good"}
          value={risky}
          sub={analysed.length ? `${Math.round((100 * risky) / analysed.length)}% of the portfolio` : "—"}
          meter={{ value: risky, max: Math.max(1, analysed.length), tone: "critical" }}
        />
        <Tile label="Awaiting validation" tone={d.queues?.to_validate ? "serious" : "good"} value={d.queues?.to_validate ?? 0} sub="four-eyes step" onClick={() => setQueue("to_validate")} />
        <Tile label="Reviews due ≤ 30 days" tone={d.queues?.review_due ? "warning" : "good"} value={d.queues?.review_due ?? 0} sub="periodic reviews" onClick={() => setQueue("review_due")} />
        <Tile label="Changes, last 30 days" tone={critical30 ? "critical" : "neutral"} value={changes30} sub={`${critical30} critical · ${unseen} unread`} />
        <Tile label="Alerts in memory" tone="accent" value={d.memory ?? 0} sub="namesakes silenced across cases" />
      </div>

      {/* Work queues */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
        {QUEUES.map((qd) => {
          const n = d.queues?.[qd.key] ?? 0;
          const on = queue === qd.key;
          return (
            <button
              key={qd.key}
              onClick={() => setQueue(on ? null : qd.key)}
              className={`glass-tile glass-press flex flex-col gap-2 rounded-[var(--radius-card)] p-3 text-left ${on ? "ring-2 ring-brand-500" : ""}`}
              aria-pressed={on}
            >
              <span className="flex items-center gap-1.5 text-[11.5px] font-semibold">
                <span className="h-2 w-2 rounded-full" style={{ background: TONE[qd.tone] }} />
                <qd.Icon className="h-3.5 w-3.5 text-slate-500" /> {qd.title}
                <span className={`ml-auto text-xl font-semibold ${n ? "" : "text-slate-400"}`}>{n}</span>
              </span>
              <Meter value={n} max={Math.max(1, analysed.length)} tone={qd.tone} height={4} label={qd.title} />
              <span className="text-[11px] text-slate-500">{qd.sub}</span>
            </button>
          );
        })}
      </div>

      <ImportPanel status={d.imports} />

      {total === 0 ? (
        <div className="card p-8 text-center text-sm text-slate-500">
          <FolderOpen className="mx-auto mb-2 h-8 w-8 text-slate-300" />
          No case yet. Open an investigation and click <b>Save as case</b>, or import a client list above.
        </div>
      ) : (
        <>
          {/* Portfolio charts */}
          <div className="grid gap-4 lg:grid-cols-3">
            <ChartCard
              title="Monitoring activity"
              sub="changes found per day, last 30 days"
              table={{ head: ["Day", "Critical", "Warning", "Info"], rows: days.map((x) => [x.day, x.critical, x.warning, x.info]) }}
            >
              <Columns
                data={days.map((x) => ({ label: x.day.slice(5), values: { critical: x.critical, warning: x.warning, info: x.info } }))}
                keys={[
                  { key: "critical", label: "Critical", color: TONE.critical },
                  { key: "warning", label: "Warning", color: TONE.warning },
                  { key: "info", label: "Info", color: TONE.neutral },
                ]}
              />
            </ChartCard>
            <ChartCard
              title="Portfolio risk"
              sub={`${analysed.length} analysed case(s)`}
              table={{ head: ["Level", "Cases"], rows: RISK.map((r) => [r.label, riskCount(d.by_level, r.key)]) }}
            >
              <StackedBar height={12} segments={RISK.map((r) => ({ key: r.key, label: r.label, value: riskCount(d.by_level, r.key), color: TONE[r.tone] }))} />
              <h4 className="mt-5 mb-2 text-[12px] font-semibold">Vigilance level</h4>
              <StackedBar height={12} segments={VIG.map((v) => ({ key: v.key, label: v.label, value: d.vigilance?.[v.key] ?? 0, color: v.color }))} />
            </ChartCard>
            <ChartCard
              title="Countries across cases"
              sub="jurisdictions of the companies in each network"
              table={{ head: ["Country", "Cases"], rows: d.by_country.map((c) => [countryName(c.code), c.cases]) }}
            >
              {d.by_country.length ? (
                <BarList rows={d.by_country.slice(0, 7).map((c) => ({ key: c.code, label: `${flag(c.code)} ${countryName(c.code)}`, value: c.cases }))} />
              ) : (
                <p className="text-xs text-slate-500">No country yet.</p>
              )}
            </ChartCard>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,1.2fr)]">
            {/* Cases table */}
            <div className="card overflow-hidden">
              <div className="flex items-center justify-between px-4 pt-3 pb-2">
                <h3 className="text-[13px] font-semibold">
                  {queue ? QUEUES.find((x) => x.key === queue)?.title : "All cases"} <span className="font-mono text-xs text-slate-400">{rows.length}</span>
                </h3>
                {queue && (
                  <button className="text-[11px] text-brand-700 underline dark:text-brand-400" onClick={() => setQueue(null)}>
                    show all cases
                  </button>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-[10.5px] uppercase tracking-wide text-slate-500">
                    <tr className="border-y border-slate-200 dark:border-white/[0.07]">
                      <th className="px-4 py-2 font-medium">Case</th>
                      <th className="px-3 py-2 font-medium">Risk</th>
                      <th className="px-3 py-2 font-medium">Vigilance</th>
                      <th className="px-3 py-2 font-medium">Countries</th>
                      <th className="px-3 py-2 font-medium">Next review</th>
                      <th className="px-3 py-2 font-medium">Changes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((c) => {
                      const next = c.questionnaire?.next_review;
                      const left = next ? daysTo(next) : null;
                      return (
                        <tr key={c.id} onClick={() => onOpenCase(c.id)} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-white/[0.05] dark:hover:bg-white/[0.03]">
                          <td className="px-4 py-2.5">
                            <a href={`#/cases/${c.id}`} className="font-medium hover:text-brand-700 dark:hover:text-brand-400" onClick={(e) => e.stopPropagation()}>
                              {c.title}
                            </a>
                            <div className="text-[11px] text-slate-500">
                              {c.subject_type} · {c.status === "closed" ? "closed" : STATE_LABEL[c.workflow_state ?? "to_complete"]}
                              {c.monitor && <BellRing className="ml-1 inline h-3 w-3" />}
                              {c.demo && " · demo"}
                            </div>
                          </td>
                          <td className="px-3 py-2.5">
                            {c.import_state ? (
                              <span className={`text-[11px] font-medium ${["ambiguous", "not_found", "error"].includes(c.import_state) ? "text-amber-600" : "text-slate-500"}`}>
                                {IMPORT_LABEL[c.import_state] ?? c.import_state}
                              </span>
                            ) : (
                              c.risk_level && (
                                <span className="flex w-28 items-center gap-2">
                                  <Meter className="flex-1" value={c.risk_score ?? 0} max={100} tone={RISK_TONE[c.risk_level] ?? "neutral"} label="Risk score" />
                                  <span className="w-7 text-right font-mono text-[11px] font-semibold tabular-nums">{c.risk_score?.toFixed(0)}</span>
                                </span>
                              )
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            {c.questionnaire?.vigilance ? <VigilanceBadge level={c.questionnaire.vigilance} small /> : !c.import_state && <span className="text-[11px] text-slate-400">to assess</span>}
                          </td>
                          <td className="px-3 py-2.5 text-xs">{c.countries.slice(0, 5).map((k) => flag(k)).join(" ")}</td>
                          <td className="px-3 py-2.5 text-xs whitespace-nowrap">
                            {left == null ? (
                              <span className="text-slate-400">—</span>
                            ) : (
                              <span className={left < 0 ? "font-semibold text-red-600" : left <= 30 ? "font-semibold text-amber-600" : "text-slate-500"}>
                                {left < 0 ? `${-left}d late` : `in ${left}d`}
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            {c.unseen_changes ? <span className="rounded bg-red-600 px-1.5 text-[11px] font-semibold text-white">{c.unseen_changes} new</span> : <span className="text-xs text-slate-400">—</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="space-y-4">
              <ChartCard title="Upcoming reviews" sub="next periodic reviews">
                {d.upcoming_reviews?.length ? (
                  <ul className="space-y-2">
                    {d.upcoming_reviews.slice(0, 6).map((r) => {
                      const left = daysTo(r.date);
                      return (
                        <li key={r.id}>
                          <button className="flex w-full items-center gap-2 text-left text-[12px] hover:text-brand-600" onClick={() => onOpenCase(r.id)}>
                            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: left < 0 ? TONE.critical : left <= 30 ? TONE.warning : TONE.good }} />
                            <span className="min-w-0 flex-1 truncate">{r.title}</span>
                            <span className="font-mono text-[11px] text-slate-500">{fmtDate(r.date)}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="text-xs text-slate-500">Review dates appear once the questionnaire is answered.</p>
                )}
              </ChartCard>
              <ChartCard title="Latest changes" sub="found by the daily monitoring">
                {d.recent_changes.length === 0 ? (
                  <p className="text-xs text-slate-500">Nothing yet: changes appear after the daily checks.</p>
                ) : (
                  <ul className="max-h-80 space-y-1.5 overflow-auto pr-1">
                    {d.recent_changes.map((x) => {
                      const Icon = SEV[x.severity] ?? Info;
                      return (
                        <li key={x.id} className="flex gap-2 text-xs">
                          <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${x.severity === "critical" ? "text-red-600" : x.severity === "warning" ? "text-amber-600" : "text-slate-400"}`} />
                          <button className="text-left hover:text-brand-600" onClick={() => x.case_id && onOpenCase(x.case_id)}>
                            <span className="font-semibold">{x.case_title}</span> · {x.description}
                            <span className="ml-1 font-mono text-[10px] text-slate-500">{x.run_at?.slice(0, 10)}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </ChartCard>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
