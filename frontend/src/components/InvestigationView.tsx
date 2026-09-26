import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  FileDown,
  FileSearch,
  FolderPlus,
  LayoutDashboard,
  Loader2,
  Map as MapIcon,
  Maximize2,
  Network,
  RefreshCw,
  Workflow,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, downloadSar } from "../api";
import { countryName, fmtDate } from "../lib/format";
import type { Theme } from "../lib/theme";
import type { Decision, DecisionValue, Entity, Investigation } from "../types";
import EntityDrawer from "./EntityDrawer";
import EntityPanel from "./EntityPanel";
import { CountryExposure, FinancialsChart, OwnershipChart } from "./Infographics";
import LinkedParties from "./LinkedParties";
import BriefCard from "./BriefCard";
import ClientDocuments from "./ClientDocuments";
import DocRequests from "./DocRequests";
import CryptoSankey from "./CryptoSankey";
import WorldMap from "./WorldMap";
import KeyFindings from "./KeyFindings";
import Timeline from "./Timeline";
import GraphView, { GraphLegend, type GraphFilters, type GraphHandle, type GraphLayout } from "./GraphView";
import RiskPanel, { RiskGauge } from "./RiskPanel";
import TablesSection from "./TablesSection";

interface Props {
  investigation: Investigation;
  theme: Theme;
  refreshing: boolean;
  onBack: () => void;
  onDepthChange?: (depth: number) => void;
  /** Set when the investigation is shown inside a saved case. */
  caseId?: string;
  decisions?: Record<string, Decision>;
  onDecide?: (key: string, label: string, decision: DecisionValue | "none") => void;
  /** Offered when cases are enabled and this investigation is not saved yet. */
  onSaveCase?: () => void;
  saving?: boolean;
  /** Opens a full investigation on a linked person / company. */
  onInvestigate?: (entity: Entity) => void;
  /** Subjects investigated before this one (pivots), for the breadcrumb. */
  trail?: string[];
  onTrail?: (index: number) => void;
}

type Tab = "overview" | "network" | "map" | "evidence";
const TABS: [Tab, string, typeof Network][] = [
  ["overview", "Overview", LayoutDashboard],
  ["network", "Network", Network],
  ["map", "Map & timeline", MapIcon],
  ["evidence", "Evidence & tables", FileSearch],
];

export default function InvestigationView({
  investigation: inv,
  theme,
  refreshing,
  onBack,
  onDepthChange,
  caseId,
  decisions,
  onDecide,
  onSaveCase,
  saving,
  onInvestigate,
  trail = [],
  onTrail,
}: Props) {
  const [tab, setTab] = useState<Tab>("overview");
  const [drawer, setDrawer] = useState<string | null>(null);
  useEffect(() => {
    setDrawer(null);
    setTab("overview");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [inv.subject_id]);
  const graph = useRef<GraphHandle>(null);
  const [layout, setLayout] = useState<GraphLayout>("hierarchy");
  const [filters, setFilters] = useState<GraphFilters>({ crypto: true, addresses: true, officers: true, ended: true });
  const [selected, setSelected] = useState<string | null>(null);
  const [pdfState, setPdfState] = useState<"idle" | "busy" | "error">("idle");
  const [reference, setReference] = useState("");
  const [template, setTemplate] = useState<"full" | "kyc" | "edd" | "review">("full");
  const [sarState, setSarState] = useState<"idle" | "busy" | "error">("idle");
  const draftSar = async (fiu: string) => {
    if (!fiu) return;
    setSarState("busy");
    try {
      await downloadSar({ ...inv.params, fiu, case_id: caseId, reference: reference || undefined });
      setSarState("idle");
    } catch {
      setSarState("error");
    }
  };
  const [tableTab, setTableTab] = useState<string | undefined>(undefined);
  const subject = inv.entities.find((e) => e.id === inv.subject_id)!;

  // In the network tab the side panel shows the entity; elsewhere its file slides in.
  const select = (id: string | null) => {
    setSelected(id);
    if (tab !== "network") setDrawer(id);
  };
  const openTab = (t: Tab) => {
    setTab(t);
    if (t === "network") requestAnimationFrame(() => graph.current?.refresh());
  };

  const exportPdf = async () => {
    setPdfState("busy");
    try {
      const png = graph.current?.exportPng() ?? undefined;
      await api.downloadPdf({ ...inv.params, graph_png: png, reference: reference || undefined, case_id: caseId, template });
      setPdfState("idle");
    } catch {
      setPdfState("error");
    }
  };

  const toggle = (k: keyof GraphFilters) => setFilters((f) => ({ ...f, [k]: !f[k] }));

  return (
    <div className="space-y-4">
      {trail.length > 0 && (
        <nav className="panel-enter flex flex-wrap items-center gap-1 text-xs text-slate-500" aria-label="Investigation path">
          {trail.map((name, i) => (
            <span key={`${name}-${i}`} className="inline-flex items-center gap-1">
              <button className="rounded px-1.5 py-0.5 hover:bg-slate-200/70 hover:text-brand-700 dark:hover:bg-slate-800" onClick={() => onTrail?.(i)}>
                {name}
              </button>
              <ChevronRight className="h-3 w-3" />
            </span>
          ))}
          <span className="px-1.5 py-0.5 font-semibold text-slate-800 dark:text-white">{subject.name}</span>
        </nav>
      )}
      {/* Summary */}
      <div className="card flex flex-wrap items-center gap-x-8 gap-y-4 p-4">
        <div className="min-w-[260px] flex-1">
          {/* Inside a case, the case header already has the way back */}
          {!caseId && (
            <button onClick={onBack} className="mb-1 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-brand-600">
              <ArrowLeft className="h-3 w-3" /> {trail.length ? `Back to ${trail[trail.length - 1]}` : "Back to candidates"}
            </button>
          )}
          <h1 className="flex items-center gap-2 text-xl font-bold tracking-tight">
            {subject.name}
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                inv.demo ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300" : "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300"
              }`}
            >
              {inv.demo ? "Demo · fictitious" : "Real public data"}
            </span>
          </h1>
          <p className="text-xs text-slate-500">
            {subject.type === "person"
              ? `Person · born ${subject.birth_date ?? "?"} · ${subject.nationalities.map(countryName).join(", ")}`
              : subject.type === "wallet"
                ? `Crypto wallet · ${subject.chain} · ${String(subject.extra.balance ?? "")}`
                : `Company · ${countryName(subject.jurisdiction)} · ${subject.registration_number ?? ""}`}
            {subject.aliases.length > 0 && ` · aka ${subject.aliases.join(", ")}`}
          </p>
          <p className="mt-1 text-[11px] text-slate-500">
            Generated {fmtDate(inv.generated_at)} · {inv.stats.persons} persons · {inv.stats.companies} companies ·{" "}
            {inv.stats.relationships} relationships · {inv.stats.queries} queries to {inv.stats.sources} sources
          </p>
        </div>
        <RiskGauge score={inv.risk.score} level={inv.risk.level} />
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="label mb-1 block" htmlFor="inv-depth">
              Depth
            </label>
            <select
              id="inv-depth"
              className="input py-1.5"
              value={inv.params.depth}
              onChange={(e) => onDepthChange?.(Number(e.target.value))}
              disabled={refreshing || !onDepthChange}
            >
              <option value={1}>1 level</option>
              <option value={2}>2 levels</option>
              <option value={3}>3 levels</option>
            </select>
          </div>
          {refreshing && <RefreshCw className="mb-2 h-4 w-4 animate-spin text-slate-400" />}
          <div>
            <label className="label mb-1 block" htmlFor="ref">
              Case reference
            </label>
            <input id="ref" className="input w-36 py-1.5" placeholder="optional" value={reference} onChange={(e) => setReference(e.target.value)} />
          </div>
          {onSaveCase && (
            <button className="btn-outline h-[34px]" onClick={onSaveCase} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderPlus className="h-4 w-4" />}
              Save as case
            </button>
          )}
          <div>
            <label className="label mb-1 block" htmlFor="tpl">
              Report
            </label>
            <select id="tpl" className="input py-1.5" value={template} onChange={(e) => setTemplate(e.target.value as typeof template)}>
              <option value="full">Full due diligence</option>
              <option value="kyc">KYC / KYB (standard)</option>
              <option value="edd">Enhanced due diligence</option>
              <option value="review">Periodic review</option>
            </select>
          </div>
          <button className="btn-primary h-[34px]" onClick={exportPdf} disabled={pdfState === "busy"}>
            {pdfState === "busy" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
            PDF report
          </button>
          {pdfState === "error" && <span className="text-xs text-red-600">PDF generation failed</span>}
          <div>
            <label className="label mb-1 block" htmlFor="sar">
              Suspicious activity report
            </label>
            <select
              id="sar"
              className="input py-1.5"
              value=""
              disabled={sarState === "busy"}
              onChange={(e) => draftSar(e.target.value)}
              title="Pre-filled draft to check and complete — never filed automatically"
            >
              <option value="">{sarState === "busy" ? "Preparing draft…" : "Draft for…"}</option>
              <option value="tracfin">TRACFIN (France)</option>
              <option value="mros">MROS (Switzerland)</option>
              <option value="lu_crf">CRF (Luxembourg)</option>
            </select>
          </div>
          {sarState === "error" && <span className="text-xs text-red-600">Draft failed</span>}
        </div>
      </div>

      {(inv.truncated || inv.warnings.length > 0) && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <ul>
            {inv.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Tabs */}
      <div className={`${caseId ? "" : "sticky top-14 z-20"} -mx-4 border-b border-slate-200 bg-slate-50/95 px-4 backdrop-blur-sm dark:border-slate-800 dark:bg-slate-950/95`}>
        <div className="flex gap-1 overflow-x-auto" role="tablist">
          {TABS.map(([k, label, Icon]) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              onClick={() => openTab(k)}
              className={`-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-[13px] font-medium transition-colors ${
                tab === k
                  ? "border-brand-600 text-brand-700 dark:border-brand-300 dark:text-white"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Overview: everything needed to decide, on one screen */}
      {tab === "overview" && (
        <div className="panel-enter space-y-4">
          <BriefCard
            investigation={inv}
            onSelect={select}
            hideOwners={subject.type === "company" || subject.type === "person"}
            onOpenTab={(t) => {
              setTableTab(t);
              setTab("evidence");
              setTimeout(() => document.getElementById("tables")?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
            }}
          />
          <div className="grid items-start gap-4 xl:grid-cols-2 [&>*]:min-w-0">
            <div className="space-y-4">
              <LinkedParties investigation={inv} onSelect={select} />
              <OwnershipChart investigation={inv} onSelect={select} />
              <CountryExposure investigation={inv} onSelect={select} />
            </div>
            <div
              className={`space-y-4 xl:sticky xl:overflow-y-auto xl:rounded-[18px] ${
                caseId ? "xl:top-[174px] xl:max-h-[calc(100vh-190px)]" : "xl:top-[116px] xl:max-h-[calc(100vh-132px)]"
              }`}
            >
              <DocRequests investigation={inv} />
            </div>
          </div>
          <FinancialsChart investigation={inv} onSelect={select} />
          <CryptoSankey investigation={inv} onSelect={select} />
          <details className="group card">
            <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-semibold text-slate-600 dark:text-slate-300">
              Detailed findings ({inv.summary?.length ?? 0}) — full reading of the network, with sources
            </summary>
            <div className="border-t border-slate-200 dark:border-slate-800">
              <KeyFindings investigation={inv} onSelect={select} />
            </div>
          </details>
        </div>
      )}

      {/* Graph + details: kept mounted so the PDF can include the chart from any tab */}
      <div id="graph-card" className={`card grid overflow-hidden lg:grid-cols-[1fr_380px] ${tab === "network" ? "panel-enter" : "hidden"}`}>
        <div className="flex min-h-[640px] flex-col border-slate-200 dark:border-slate-800 lg:border-r">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
            <div className="segmented">
              {(
                [
                  ["hierarchy", "Ownership chart", Workflow],
                  ["network", "Network view", Network],
                ] as const
              ).map(([k, label, Icon]) => (
                <button
                  key={k}
                  onClick={() => setLayout(k)}
                  className={`inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1 transition-all duration-200 text-xs font-medium ${
                    layout === k ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" /> {label}
                </button>
              ))}
            </div>
            {(
              [
                ["officers", "Officers"],
                ["crypto", "Crypto"],
                ["addresses", "Addresses"],
                ["ended", "Ended links"],
              ] as const
            ).map(([k, label]) => (
              <label key={k} className="inline-flex cursor-pointer items-center gap-1 text-xs text-slate-600 dark:text-slate-300">
                <input type="checkbox" checked={filters[k]} onChange={() => toggle(k)} className="accent-brand-600" /> {label}
              </label>
            ))}
            <button className="btn-ghost ml-auto py-1 text-xs" onClick={() => graph.current?.fit()}>
              <Maximize2 className="h-3.5 w-3.5" /> Fit
            </button>
          </div>
          <div className="relative flex-1 bg-[radial-gradient(circle,_rgba(148,163,184,0.18)_1px,_transparent_1px)] [background-size:18px_18px]">
            <div className="absolute inset-0">
              <GraphView ref={graph} investigation={inv} layout={layout} filters={filters} theme={theme} selectedId={selected} onSelect={setSelected} />
            </div>
          </div>
          <div className="border-t border-slate-200 px-3 py-2 dark:border-slate-800">
            <GraphLegend />
          </div>
        </div>
        <div className="flex max-h-[720px] min-h-[400px] flex-col">
          {onInvestigate && selected && selected !== inv.subject_id && (
            <InvestigateBar investigation={inv} entityId={selected} onInvestigate={onInvestigate} />
          )}
          <div className="min-h-0 flex-1">
            <EntityPanel investigation={inv} entityId={selected ?? inv.subject_id} onSelect={setSelected} />
          </div>
        </div>
      </div>

      {tab === "map" && (
        <div className="panel-enter space-y-4">
          <WorldMap investigation={inv} onSelect={select} />
          <CryptoSankey investigation={inv} onSelect={select} />
          <Timeline investigation={inv} onSelect={select} />
        </div>
      )}

      {tab === "evidence" && (
        <div className="panel-enter space-y-4">
          <RiskPanel investigation={inv} onSelect={select} />
          <ClientDocuments investigation={inv} onSelect={select} />
          <TablesSection
            investigation={inv}
            onSelect={select}
            activeTab={tableTab}
            onTabChange={setTableTab}
            decisions={decisions}
            onDecide={onDecide}
          />
        </div>
      )}

      <EntityDrawer investigation={inv} entityId={drawer} onClose={() => setDrawer(null)} onInvestigate={onInvestigate} />
    </div>
  );
}

function InvestigateBar({ investigation: inv, entityId, onInvestigate }: { investigation: Investigation; entityId: string; onInvestigate: (e: Entity) => void }) {
  const e = inv.entities.find((x) => x.id === entityId);
  if (!e || e.type === "address" || !e.record_ids.length) return null;
  return (
    <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
      <span className="truncate text-xs text-slate-500">Go further on {e.name}</span>
      <button className="btn-primary ml-auto shrink-0 py-1 text-xs" onClick={() => onInvestigate(e)}>
        Investigate
      </button>
    </div>
  );
}
