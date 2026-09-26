import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, AlertTriangle, BellRing, FolderOpen, Info, Loader2, Lock } from "lucide-react";
import { useState } from "react";
import { api, auth, AuthError } from "../api";
import { countryName, ENTITY_COLORS, flag, fmtDate } from "../lib/format";
import type { CasesStatus, RiskLevel } from "../types";
import ImportPanel from "./ImportPanel";
import { VigilanceBadge } from "./KycQuestionnaire";
import PasswordGate from "./PasswordGate";

const IMPORT_LABEL: Record<string, string> = {
  pending: "in the queue",
  resolved: "analysis waiting",
  ambiguous: "pick the company",
  not_found: "not found",
  error: "failed",
};

const LEVELS: RiskLevel[] = ["critical", "high", "medium", "low"];
const SEV = { critical: AlertOctagon, warning: AlertTriangle, info: Info } as const;

interface Props {
  status?: CasesStatus;
  onOpenCase: (id: string) => void;
}

/** All cases at a glance: risk distribution, what needs review, latest changes, countries. */
export default function Dashboard({ status, onOpenCase }: Props) {
  const [attempt, setAttempt] = useState(0);
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
  const total = d.cases.length;
  const unseen = d.cases.reduce((n, c) => n + (c.unseen_changes ?? 0), 0);
  const monitored = d.cases.filter((c) => c.monitor && c.status === "open").length;
  const maxCountry = Math.max(1, ...d.by_country.map((c) => c.cases));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Cases</h1>
          <p className="text-xs text-slate-500">
            Saved investigations, re-checked daily when monitoring is on. Storage: {status?.storage ?? "—"}
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

      {/* Tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Cases", String(total), "neutral"],
          ["Need review", String(d.to_review), d.to_review ? "warning" : "good"],
          ["New changes", String(unseen), unseen ? "critical" : "good"],
          ["Monitored", String(monitored), "neutral"],
        ].map(([label, value, tone]) => (
          <div
            key={label}
            className={`rounded-lg border p-3 ${
              tone === "critical"
                ? "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
                : tone === "warning"
                  ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                  : "card"
            }`}
          >
            <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div>
            <div className="text-2xl font-bold">{value}</div>
          </div>
        ))}
      </div>

      <ImportPanel status={d.imports} />

      {total === 0 ? (
        <div className="card p-8 text-center text-sm text-slate-500">
          <FolderOpen className="mx-auto mb-2 h-8 w-8 text-slate-300" />
          No case yet. Open an investigation and click <b>Save as case</b>, or import a client list above.
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          {/* Cases table */}
          <div className="card overflow-hidden">
            <div className="flex h-2">
              {LEVELS.map((l) => (
                <div key={l} style={{ flex: d.by_level[l] ?? 0, background: ENTITY_COLORS[l] }} title={`${l}: ${d.by_level[l] ?? 0}`} />
              ))}
            </div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-[11px] uppercase tracking-wide text-slate-500 dark:bg-slate-800/60">
                <tr>
                  <th className="px-3 py-2">Case</th>
                  <th className="px-3 py-2">Risk</th>
                  <th className="px-3 py-2">Vigilance</th>
                  <th className="px-3 py-2">Countries</th>
                  <th className="px-3 py-2">Last check</th>
                  <th className="px-3 py-2">Changes</th>
                </tr>
              </thead>
              <tbody>
                {d.cases.map((c) => (
                  <tr key={c.id} onClick={() => onOpenCase(c.id)} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50">
                    <td className="px-3 py-2">
                      <div className="font-medium">{c.title}</div>
                      <div className="text-[11px] text-slate-500">
                        {c.subject_type} · {c.status}
                        {c.monitor && <BellRing className="ml-1 inline h-3 w-3" />}
                        {c.demo && " · demo"}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      {c.import_state ? (
                        <span
                          className={`text-[11px] font-medium ${
                            ["ambiguous", "not_found", "error"].includes(c.import_state) ? "text-amber-600" : "text-slate-500"
                          }`}
                        >
                          {IMPORT_LABEL[c.import_state] ?? c.import_state}
                        </span>
                      ) : c.risk_level && (
                        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase text-white" style={{ background: ENTITY_COLORS[c.risk_level] }}>
                          {c.risk_level} {c.risk_score?.toFixed(0)}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {c.questionnaire?.vigilance ? (
                        <VigilanceBadge level={c.questionnaire.vigilance} small />
                      ) : (
                        !c.import_state && <span className="text-[11px] text-slate-400">to assess</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">{c.countries.slice(0, 5).map((k) => flag(k)).join(" ")}</td>
                    <td className="px-3 py-2 text-xs text-slate-500">{c.last_run_at ? fmtDate(c.last_run_at) : "—"}</td>
                    <td className="px-3 py-2">
                      {c.unseen_changes ? <span className="rounded bg-red-600 px-1.5 text-[11px] font-semibold text-white">{c.unseen_changes} new</span> : <span className="text-xs text-slate-400">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-4">
            {/* Latest changes */}
            <div className="card p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Latest changes</h2>
              {d.recent_changes.length === 0 ? (
                <p className="text-xs text-slate-500">Nothing yet: changes appear after the daily checks.</p>
              ) : (
                <ul className="max-h-72 space-y-1.5 overflow-auto pr-1">
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
            </div>
            {/* Countries */}
            <div className="card p-4">
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Countries across cases</h2>
              <ul className="space-y-1">
                {d.by_country.slice(0, 12).map((c) => (
                  <li key={c.code} className="flex items-center gap-2 text-xs">
                    <span className="w-40 truncate">
                      {flag(c.code)} {countryName(c.code)}
                    </span>
                    <div className="h-2 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                      <div className="h-full rounded bg-brand-600" style={{ width: `${(100 * c.cases) / maxCountry}%` }} />
                    </div>
                    <span className="w-6 text-right font-mono">{c.cases}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
