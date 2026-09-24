import { AlertTriangle, ArrowLeft, FileDown, Loader2, Maximize2, Network, RefreshCw, Workflow } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../api";
import { countryName, fmtDate } from "../lib/format";
import type { Theme } from "../lib/theme";
import type { Investigation } from "../types";
import EntityPanel from "./EntityPanel";
import BriefCard from "./BriefCard";
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
  onDepthChange: (depth: number) => void;
}

export default function InvestigationView({ investigation: inv, theme, refreshing, onBack, onDepthChange }: Props) {
  const graph = useRef<GraphHandle>(null);
  const [layout, setLayout] = useState<GraphLayout>("hierarchy");
  const [filters, setFilters] = useState<GraphFilters>({ crypto: true, addresses: true, officers: true, ended: true });
  const [selected, setSelected] = useState<string | null>(null);
  const [pdfState, setPdfState] = useState<"idle" | "busy" | "error">("idle");
  const [reference, setReference] = useState("");
  const [tableTab, setTableTab] = useState<string | undefined>(undefined);
  const subject = inv.entities.find((e) => e.id === inv.subject_id)!;

  const select = (id: string | null) => {
    setSelected(id);
    if (id) document.getElementById("graph-card")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const exportPdf = async () => {
    setPdfState("busy");
    try {
      const png = graph.current?.exportPng() ?? undefined;
      await api.downloadPdf({ ...inv.params, graph_png: png, reference: reference || undefined });
      setPdfState("idle");
    } catch {
      setPdfState("error");
    }
  };

  const toggle = (k: keyof GraphFilters) => setFilters((f) => ({ ...f, [k]: !f[k] }));

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="card flex flex-wrap items-center gap-x-8 gap-y-4 p-4">
        <div className="min-w-[260px] flex-1">
          <button onClick={onBack} className="mb-1 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-brand-600">
            <ArrowLeft className="h-3 w-3" /> Back to candidates
          </button>
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
            <select id="inv-depth" className="input py-1.5" value={inv.params.depth} onChange={(e) => onDepthChange(Number(e.target.value))} disabled={refreshing}>
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
          <button className="btn-primary h-[34px]" onClick={exportPdf} disabled={pdfState === "busy"}>
            {pdfState === "busy" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
            PDF report
          </button>
          {pdfState === "error" && <span className="text-xs text-red-600">PDF generation failed</span>}
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

      <BriefCard
        investigation={inv}
        onSelect={select}
        onOpenTab={(t) => {
          setTableTab(t);
          setTimeout(() => document.getElementById("tables")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
        }}
      />
      <details className="group card">
        <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-semibold text-slate-600 dark:text-slate-300">
          Detailed findings ({inv.summary?.length ?? 0}) — full reading of the network, with sources
        </summary>
        <div className="border-t border-slate-200 dark:border-slate-800">
          <KeyFindings investigation={inv} onSelect={select} />
        </div>
      </details>

      {/* Graph + details */}
      <div id="graph-card" className="card grid overflow-hidden lg:grid-cols-[1fr_380px]">
        <div className="flex min-h-[640px] flex-col border-slate-200 dark:border-slate-800 lg:border-r">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-2 dark:border-slate-800">
            <div className="flex rounded-lg bg-slate-100 p-0.5 dark:bg-slate-800">
              {(
                [
                  ["hierarchy", "Ownership chart", Workflow],
                  ["network", "Network view", Network],
                ] as const
              ).map(([k, label, Icon]) => (
                <button
                  key={k}
                  onClick={() => setLayout(k)}
                  className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ${
                    layout === k ? "bg-white shadow-sm dark:bg-slate-700" : "text-slate-500"
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
        <div className="max-h-[720px] min-h-[400px]">
          <EntityPanel investigation={inv} entityId={selected ?? inv.subject_id} onSelect={select} />
        </div>
      </div>

      <RiskPanel investigation={inv} onSelect={select} />
      <Timeline investigation={inv} onSelect={select} />
      <TablesSection investigation={inv} onSelect={select} activeTab={tableTab} onTabChange={setTableTab} />
    </div>
  );
}
