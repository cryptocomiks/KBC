import { ExternalLink } from "lucide-react";
import { useState } from "react";
import { countryName, ENTITY_COLORS, ENTITY_LEVEL_LABEL, fmtDate, fmtPct, flag, scoreClass } from "../lib/format";
import type { Investigation, RiskLevel, Row } from "../types";
import DataTable, { type Column } from "./DataTable";

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
  activeTab?: string;
  onTabChange?: (tab: string) => void;
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
const riskTone = (high: boolean, medium: boolean) =>
  high
    ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300"
    : medium
      ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
      : "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
const scoreBadge = (r: Row) => <span className={`rounded px-1.5 py-0.5 font-semibold ${scoreClass(Number(r.score))}`}>{Number(r.score).toFixed(0)}%</span>;
const urls = (r: Row) => {
  const list = (r.urls as string[] | undefined) ?? [];
  return list.length ? <span className="flex gap-2">{list.map((u) => <span key={u}>{link(u)}</span>)}</span> : "—";
};

export default function TablesSection({ investigation: inv, onSelect, activeTab, onTabChange }: Props) {
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
      label: "Sanctions, PEP & watchlists",
      rows: t.screening,
      click: "entity_id",
      empty: "No sanctions, PEP or watchlist hit.",
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
      key: "crypto",
      label: "Crypto wallets & flows",
      rows: t.crypto ?? [],
      click: "to_id",
      empty: "No crypto wallet in this network.",
      columns: [
        { key: "relation", label: "Relation" },
        { key: "from", label: "From", render: (r) => <span className="break-all font-mono text-[11px]">{String(r.from)}</span> },
        { key: "to", label: "To", render: (r) => <span className="break-all font-mono text-[11px]">{String(r.to)}</span> },
        { key: "chain", label: "Chain" },
        { key: "amount", label: "Amount", render: (r) => (r.amount != null ? Number(r.amount).toLocaleString("en", { maximumFractionDigits: 4 }) : "—") },
        { key: "currency", label: "Currency" },
        { key: "tx_count", label: "Tx" },
        { key: "since", label: "Since", render: (r) => fmtDate(r.since) },
        {
          key: "sanctioned_party",
          label: "Sanctioned party",
          render: (r) =>
            r.sanctioned_party ? <span className="rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-800 dark:bg-red-900/40 dark:text-red-300">{String(r.sanctioned_party)}</span> : "",
        },
        { key: "urls", label: "Explorer", render: urls, value: (r) => (r.urls as string[]).join(" ") },
      ],
    },
    {
      key: "documents",
      label: "Documents & filings",
      rows: t.documents ?? [],
      click: "entity_id",
      empty: "No linked document.",
      columns: [
        { key: "entity", label: "Entity" },
        { key: "date", label: "Date", render: (r) => fmtDate(r.date) },
        {
          key: "title",
          label: "Document",
          render: (r) =>
            r.url ? (
              <a href={String(r.url)} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline" onClick={(e) => e.stopPropagation()}>
                {String(r.title)}
              </a>
            ) : (
              String(r.title)
            ),
        },
        { key: "kind", label: "Type" },
        { key: "summary", label: "Summary" },
        {
          key: "flags",
          label: "Flags",
          render: (r) =>
            r.flags ? <span className="rounded bg-red-100 px-1.5 py-0.5 font-semibold text-red-800 dark:bg-red-900/40 dark:text-red-300">{String(r.flags)}</span> : "",
        },
        { key: "source", label: "Source" },
      ],
    },
    {
      key: "jurisdictions",
      label: "Country risk",
      rows: t.jurisdictions ?? [],
      empty: "No jurisdiction identified.",
      columns: [
        { key: "country", label: "Country", render: (r) => `${flag(String(r.code))} ${String(r.country)}` },
        { key: "entities", label: "Entities" },
        { key: "examples", label: "Examples" },
        {
          key: "basel_aml_score",
          label: "Basel AML (0–10)",
          render: (r) =>
            r.basel_aml_score == null ? "—" : (
              <span className={`rounded px-1.5 py-0.5 font-semibold ${riskTone(Number(r.basel_aml_score) >= 6, Number(r.basel_aml_score) >= 5)}`}>
                {Number(r.basel_aml_score).toFixed(2)} · #{String(r.basel_aml_rank)}
              </span>
            ),
        },
        {
          key: "cpi_score",
          label: "CPI (0–100)",
          render: (r) =>
            r.cpi_score == null ? "—" : (
              <span className={`rounded px-1.5 py-0.5 font-semibold ${riskTone(Number(r.cpi_score) < 30, Number(r.cpi_score) < 50)}`}>
                {Number(r.cpi_score).toFixed(0)} ({String(r.cpi_year)})
              </span>
            ),
        },
        { key: "wgi_control_of_corruption", label: "WGI corruption control", render: (r) => (r.wgi_control_of_corruption == null ? "—" : Number(r.wgi_control_of_corruption).toFixed(2)) },
        { key: "lists", label: "Lists" },
      ],
    },
    {
      key: "financials",
      label: "Financials",
      rows: t.financials ?? [],
      click: "entity_id",
      empty: "No published financial statement in the sources queried (many small companies are exempt or opt out).",
      columns: [
        { key: "name", label: "Company" },
        { key: "jurisdiction", label: "Jur.", render: (r) => jur(r) },
        { key: "year", label: "Year" },
        { key: "revenue", label: "Revenue" },
        { key: "net_income", label: "Net income" },
        { key: "total_assets", label: "Total assets" },
        { key: "currency", label: "Cur." },
        { key: "source", label: "Source" },
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
  const [localActive, setLocalActive] = useState(tabs[0].key);
  const active = activeTab && tabs.some((x) => x.key === activeTab) ? activeTab : localActive;
  const setActive = (key: string) => (onTabChange ? onTabChange(key) : setLocalActive(key));
  const tab = tabs.find((x) => x.key === active)!;

  return (
    <div id="tables" className="card p-4">
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
