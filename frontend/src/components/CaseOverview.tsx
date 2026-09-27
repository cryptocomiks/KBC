import { ArrowRight, CheckCircle2, Circle } from "lucide-react";
import type { CaseTab } from "../lib/route";
import type { CaseOverview as Overview } from "../types";
import { BarList, ChartCard, Meter, StackedBar, TONE } from "./viz";

const LIST_LABEL: Record<string, string> = { sanction: "Sanctions", pep: "PEP", leak: "Leaks & investigations", adverse: "Adverse media / watchlists" };
export const TRIAGE_SEGMENTS = (t: Record<string, number>) => [
  { key: "likely", label: "Likely match", value: t.likely ?? 0, color: TONE.critical },
  { key: "verify", label: "To check", value: t.verify ?? 0, color: TONE.warning },
  { key: "namesake", label: "Probable namesake", value: t.namesake ?? 0, color: "var(--series-1)" },
  { key: "dismissed", label: "Silenced by memory", value: t.dismissed ?? 0, color: TONE.neutral },
];
const SOW_LABEL = { plausible: "plausible", partial: "partially explained", gap: "unexplained gap", incomplete: "incomplete" };

/** Top of the KYC tab: how far the file is from validation, and where the work is. */
export default function CaseOverview({ o, onTab }: { o: Overview; onTab: (t: CaseTab) => void }) {
  const lists = Object.entries(o.alerts.by_list).sort((a, b) => b[1].total - a[1].total);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard
        title="Ready for validation"
        sub={`${o.ready} of ${o.readiness.length} conditions met`}
        table={{ head: ["Condition", "Status", "Detail"], rows: o.readiness.map((r) => [r.label, r.done ? "done" : "open", r.detail]) }}
      >
        <div className="flex items-baseline gap-2">
          <span className="text-4xl font-semibold tracking-tight">{Math.round((100 * o.ready) / Math.max(1, o.readiness.length))}%</span>
          <span className="text-xs text-slate-500">complete</span>
        </div>
        <Meter className="mt-2" value={o.ready} max={o.readiness.length} tone={o.ready === o.readiness.length ? "good" : "accent"} height={8} label="Readiness" />
        <ul className="mt-3 space-y-1.5">
          {o.readiness.map((r) => (
            <li key={r.key}>
              <button className="group flex w-full items-center gap-2 text-left text-[12.5px]" onClick={() => onTab(r.tab as CaseTab)}>
                {r.done ? <CheckCircle2 className="h-4 w-4 shrink-0 text-[var(--status-good)]" /> : <Circle className="h-4 w-4 shrink-0 text-slate-400" />}
                <span className={r.done ? "text-slate-500" : "font-medium"}>{r.label}</span>
                <span className="ml-auto truncate text-[11px] text-slate-500">{r.detail}</span>
                <ArrowRight className="h-3 w-3 shrink-0 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            </li>
          ))}
        </ul>
      </ChartCard>

      <ChartCard
        title="Screening"
        sub={`${o.alerts.total} hit(s) · ${o.alerts.open} still open`}
        action={
          <button className="btn-ghost px-2 py-1 text-[11px]" onClick={() => onTab("alerts")}>
            Alerts <ArrowRight className="h-3 w-3" />
          </button>
        }
        table={{ head: ["List", "Hits", "Open"], rows: lists.map(([k, v]) => [LIST_LABEL[k] ?? k, v.total, v.open]) }}
      >
        <StackedBar segments={TRIAGE_SEGMENTS(o.alerts.triage)} />
        <div className="mt-4">
          {lists.length ? (
            <BarList
              rows={lists.map(([k, v]) => ({
                key: k,
                label: LIST_LABEL[k] ?? k,
                value: v.total,
                sub: v.open ? `${v.open} open` : "all resolved",
                color: v.open ? TONE.warning : TONE.accent,
              }))}
            />
          ) : (
            <p className="text-xs text-slate-500">No hit on any list.</p>
          )}
        </div>
      </ChartCard>

      <ChartCard title="File contents" sub="documents, beneficial owners, source of wealth">
        <div className="space-y-4">
          <div>
            <div className="flex items-baseline justify-between text-[12px]">
              <span className="font-medium">Documents received</span>
              <span className="font-semibold">
                {o.documents.received}/{o.documents.total}
              </span>
            </div>
            <Meter className="mt-1.5" value={o.documents.received} max={o.documents.total} tone={o.documents.required_missing ? "warning" : "good"} label="Documents" />
            <p className="mt-1 text-[11px] text-slate-500">{o.documents.required_missing ? `${o.documents.required_missing} required still missing` : "all required documents received"}</p>
          </div>
          <button className="block w-full text-left" onClick={() => onTab("cdb")}>
            <div className="flex items-baseline justify-between text-[12px]">
              <span className="font-medium">UBO forms · {o.cdb.forms.join(" + ") || "—"}</span>
              <span className="font-semibold">{o.cdb.persons} person(s)</span>
            </div>
            <p className={`mt-1 text-[11px] ${o.cdb.missing ? "text-amber-700 dark:text-amber-300" : "text-slate-500"}`}>
              {o.cdb.missing ? `${o.cdb.missing} field(s) to complete` : "complete — ready to sign"}
            </p>
          </button>
          <button className="block w-full text-left" onClick={() => onTab("sow")}>
            <div className="flex items-baseline justify-between text-[12px]">
              <span className="font-medium">Source of wealth</span>
              <span className="font-semibold">{o.sow?.coverage != null ? `${Math.round(o.sow.coverage * 100)}% explained` : "—"}</span>
            </div>
            {o.sow ? (
              <>
                <Meter
                  className="mt-1.5"
                  value={Math.min(1, o.sow.coverage ?? 0)}
                  max={1}
                  tone={o.sow.verdict === "plausible" ? "good" : o.sow.verdict === "gap" ? "critical" : "warning"}
                  label="Source of wealth coverage"
                />
                <p className="mt-1 text-[11px] text-slate-500">
                  {SOW_LABEL[o.sow.verdict]} · {o.sow.sources} source(s)
                </p>
              </>
            ) : (
              <p className="mt-1 text-[11px] text-slate-500">{o.vigilance === "enhanced" ? "required under enhanced vigilance" : "not documented"}</p>
            )}
          </button>
        </div>
      </ChartCard>
    </div>
  );
}
