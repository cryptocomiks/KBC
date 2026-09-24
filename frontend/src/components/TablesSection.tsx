import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { countryName, ENTITY_COLORS, ENTITY_LEVEL_LABEL, fmtDate, fmtPct, flag, scoreClass } from "../lib/format";
import type { Investigation, RiskLevel, Row } from "../types";
import DataTable, { type Column } from "./DataTable";

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

const link = (url: unknown) =>
  url ? (
    <a href={String(url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-brand-600 hover:underline" onClick={(e) => e.stopPropagation()}>
      open <ExternalLink className="h-3 w-3" />
    </a>
  ) : (
    "—"
  );
const jur = (r: Row, key = "jurisdiction") => (r[key] ? `${flag(String(r[key]))} ${r[key]}` : "—");
const badge = (level: unknown) => {
  const l = ((level as RiskLevel) ?? "none") as RiskLevel;
  return l === "none" ? (
    "—"
  ) : (
    <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white" style={{ background: ENTITY_COLORS[l] }}>
      {ENTITY_LEVEL_LABEL[l]}
    </span>
  );
};
const scoreBadge = (r: Row) => <span className={`rounded px-1.5 py-0.5 font-semibold ${scoreClass(Number(r.score))}`}>{Number(r.score).toFixed(0)}%</span>;
const urls = (r: Row) => {
  const list = (r.urls as string[] | undefined) ?? [];
  return list.length ? <span className="flex gap-2">{list.map((u) => <span key={u}>{link(u)}</span>)}</span> : "—";
};

export default function TablesSection({ investigation: inv, onSelect }: Props) {
  const t = inv.tables;
  const subject = inv.entities.find((e) => e.id === inv.subject_id)!;
  const slug = subject.name.replace(/[^a-z0-9]+/gi, "_").toLowerCase();
  const isPerson = subject.type === "person";

  const tabs: { key: string; label: string; rows: Row[]; columns: Column[]; empty?: string; click?: string }[] = [
    {
      key: "mandates",
      label: isPerson ? "Positions & holdings" : "Officers",
      rows: t.mandates,
      click: "entity_id",
      columns: [
        { key: "name", label: isPerson ? "Company" : "Officer" },
        { key: "jurisdiction", label: "Jur.", render: (r) => jur(r) },
        { key: "relation", label: "Relation" },
        { key: "role", label: "Role" },
        { key: "share_pct", label: "%", render: (r) => fmtPct(r.share_pct) },
        { key: "start_date", label: "From", render: (r) => fmtDate(r.start_date) },
        { key: "end_date", label: "To", render: (r) => fmtDate(r.end_date) },
        { key: "status", label: "Mandate" },
        { key: "company_status", label: "Company status" },
        { key: "sources", label: "Source" },
        { key: "urls", label: "Link", render: urls, value: (r) => (r.urls as string[]).join(" ") },
      ],
    },
    {
      key: "companies",
      label: "Related companies",
      rows: t.companies,
      click: "entity_id",
      columns: [
        { key: "name", label: "Company" },
        { key: "jurisdiction", label: "Jurisdiction", render: (r) => `${flag(String(r.jurisdiction ?? ""))} ${countryName(String(r.jurisdiction ?? ""))}` },
        { key: "registration_number", label: "Reg. no.", render: (r) => <span className="font-mono">{String(r.registration_number ?? "—")}</span> },
        { key: "status", label: "Status" },
        { key: "incorporation_date", label: "Incorporated" },
        { key: "last_accounts_date", label: "Last accounts", render: (r) => fmtDate(r.last_accounts_date) },
        { key: "offshore", label: "Offshore", render: (r) => (r.offshore ? "yes" : "") },
        { key: "depth", label: "Hops" },
        { key: "risk_level", label: "Risk", render: (r) => badge(r.risk_level) },
        { key: "flags", label: "Flags" },
        { key: "sources", label: "Sources" },
      ],
    },
    {
      key: "shareholders",
      label: "Shareholders & UBOs",
      rows: t.shareholders,
      columns: [
        { key: "company", label: "Company" },
        { key: "owner", label: "Owner" },
        { key: "owner_type", label: "Owner type" },
        { key: "relation", label: "Relation" },
        { key: "share_pct", label: "%", render: (r) => fmtPct(r.share_pct) },
        { key: "details", label: "Details" },
        { key: "sources", label: "Source" },
        { key: "urls", label: "Link", render: urls, value: (r) => (r.urls as string[]).join(" ") },
      ],
    },
    {
      key: "ownership",
      label: "Effective ownership",
      rows: t.ownership,
      columns: [
        { key: "owner", label: "Owner" },
        { key: "company", label: "Company" },
        { key: "direct_pct", label: "Direct %", render: (r) => fmtPct(r.direct_pct) },
        { key: "effective_pct", label: "Effective %", render: (r) => <strong>{fmtPct(r.effective_pct)}</strong> },
        { key: "ubo_threshold_met", label: "≥ 25% (UBO threshold)", render: (r) => (r.ubo_threshold_met ? "yes" : "no") },
      ],
      empty: "No computable ownership path (missing percentages).",
    },
    {
      key: "screening",
      label: "Sanctions & PEP",
      rows: t.screening,
      click: "entity_id",
      empty: "No sanctions or PEP hit.",
      columns: [
        { key: "entity", label: "Network entity" },
        { key: "matched_name", label: "Listed name" },
        { key: "list_type", label: "List", render: (r) => <span className="font-semibold uppercase">{String(r.list_type)}</span> },
        { key: "score", label: "Confidence", render: scoreBadge },
        { key: "status", label: "Assessment" },
        { key: "dataset", label: "Dataset" },
        { key: "explanation", label: "Why" },
        { key: "details", label: "Details" },
        { key: "retrieved_at", label: "Retrieved", render: (r) => fmtDate(r.retrieved_at) },
        { key: "url", label: "Link", render: (r) => link(r.url) },
      ],
    },
    {
      key: "leaks",
      label: "Leaks",
      rows: t.leaks,
      click: "entity_id",
      empty: "No appearance in leak datasets.",
      columns: [
        { key: "entity", label: "Network entity" },
        { key: "matched_name", label: "Name in dataset" },
        { key: "score", label: "Confidence", render: scoreBadge },
        { key: "dataset", label: "Dataset" },
        { key: "details", label: "Details" },
        { key: "retrieved_at", label: "Retrieved", render: (r) => fmtDate(r.retrieved_at) },
        { key: "url", label: "Link", render: (r) => link(r.url) },
      ],
    },
    {
      key: "sources",
      label: "Sources consulted",
      rows: t.sources,
      columns: [
        { key: "source", label: "Source" },
        { key: "connector", label: "Connector", render: (r) => <span className="font-mono">{String(r.connector)}</span> },
        { key: "queries", label: "Queries" },
        { key: "records", label: "Records returned" },
        { key: "errors", label: "Errors" },
        { key: "first_retrieved", label: "First retrieval", render: (r) => fmtDate(r.first_retrieved) },
        { key: "last_retrieved", label: "Last retrieval", render: (r) => fmtDate(r.last_retrieved) },
      ],
    },
    {
      key: "merges",
      label: "Entity resolution",
      rows: inv.merges.map((m) => ({ ...m, explanation: (m.explanation as string[]).join("; ") })),
      click: "canonical_id",
      empty: "No cross-source merge.",
      columns: [
        { key: "canonical_name", label: "Entity" },
        { key: "merged_name", label: "Merged record" },
        { key: "merged_source", label: "From source" },
        { key: "merged_record", label: "Record id", render: (r) => <span className="font-mono">{String(r.merged_record)}</span> },
        { key: "score", label: "Score", render: scoreBadge },
        { key: "explanation", label: "Evidence" },
      ],
    },
  ];
  const [active, setActive] = useState(tabs[0].key);
  const tab = tabs.find((x) => x.key === active)!;

  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800">
        {tabs.map((x) => (
          <button
            key={x.key}
            onClick={() => setActive(x.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              active === x.key ? "border-brand-600 text-brand-600" : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            }`}
          >
            {x.label}
            <span className="ml-1.5 rounded bg-slate-100 px-1.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">{x.rows.length}</span>
          </button>
        ))}
      </div>
      <DataTable
        key={tab.key}
        rows={tab.rows}
        columns={tab.columns}
        empty={tab.empty}
        csvName={`${slug}_${tab.key}.csv`}
        onRowClick={tab.click ? (r) => onSelect(String(r[tab.click!])) : undefined}
      />
    </div>
  );
}
