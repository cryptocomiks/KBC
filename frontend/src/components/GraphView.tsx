import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from "cytoscape";
import dagre from "cytoscape-dagre";
import fcose from "cytoscape-fcose";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import { ENTITY_COLORS, ENTITY_LEVEL_LABEL } from "../lib/format";
import type { Theme } from "../lib/theme";
import type { Investigation, RiskLevel } from "../types";

cytoscape.use(dagre);
cytoscape.use(fcose);

export type GraphLayout = "hierarchy" | "network";
export interface GraphFilters {
  addresses: boolean;
  officers: boolean;
  ended: boolean;
}
export interface GraphHandle {
  exportPng: () => string | null;
  fit: () => void;
}

interface Props {
  investigation: Investigation;
  layout: GraphLayout;
  filters: GraphFilters;
  theme: Theme;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

function shortRole(role: string | null): string {
  if (!role) return "officer";
  const r = role.split(" / ")[0];
  return r.length > 22 ? `${r.slice(0, 20)}…` : r;
}

function buildElements(inv: Investigation, filters: GraphFilters): ElementDefinition[] {
  const visible = new Set<string>();
  const nodes: ElementDefinition[] = [];
  for (const e of inv.entities) {
    if (e.type === "address" && !filters.addresses) continue;
    visible.add(e.id);
    const level: RiskLevel = inv.risk.entity_levels[e.id] ?? "none";
    const kind = e.type === "company" ? (e.is_offshore ? "offshore" : "company") : e.type;
    const suffix = e.type === "company" && e.jurisdiction ? `\n${e.jurisdiction}${e.status === "dissolved" ? " · dissolved" : ""}` : "";
    nodes.push({
      data: {
        id: e.id,
        label: e.type === "address" ? e.name.split(",")[0] : `${e.name}${suffix}`,
        kind,
        color: ENTITY_COLORS[level],
        level,
        subject: e.id === inv.subject_id ? 1 : 0,
        dissolved: e.status === "dissolved" ? 1 : 0,
      },
    });
  }
  const edges: ElementDefinition[] = [];
  for (const r of inv.relationships) {
    if (!visible.has(r.source_id) || !visible.has(r.target_id)) continue;
    if (r.type === "officer" && !filters.officers) continue;
    const ended = r.end_date ? 1 : 0;
    if (ended && !filters.ended) continue;
    let label = "";
    if (r.type === "shareholder") label = r.share_pct != null ? `${r.share_pct}%` : "shareholder";
    else if (r.type === "beneficial_owner") label = `UBO${r.share_pct != null ? ` ${r.share_pct}%` : ""}`;
    else if (r.type === "officer") label = shortRole(r.role);
    edges.push({
      data: { id: r.id, source: r.source_id, target: r.target_id, rel: r.type, label: ended ? `${label} (ended)` : label, ended },
    });
  }
  return [...nodes, ...edges];
}

function buildStyle(theme: Theme): StylesheetJson {
  const dark = theme === "dark";
  const text = dark ? "#e2e8f0" : "#0f172a";
  const halo = dark ? "#020617" : "#ffffff";
  const edge = dark ? "#64748b" : "#64748b";
  return [
    {
      selector: "node",
      style: {
        label: "data(label)",
        "background-color": "data(color)",
        "border-width": 2,
        "border-color": dark ? "#0f172a" : "#ffffff",
        color: text,
        "font-size": 10,
        "font-family": "Inter, system-ui, sans-serif",
        "text-valign": "bottom",
        "text-margin-y": 5,
        "text-wrap": "wrap",
        "text-max-width": "130px",
        "text-outline-color": halo,
        "text-outline-width": 2,
        width: 34,
        height: 34,
      },
    },
    { selector: 'node[kind = "person"]', style: { shape: "ellipse" } },
    { selector: 'node[kind = "company"]', style: { shape: "round-rectangle", width: 44, height: 30 } },
    { selector: 'node[kind = "offshore"]', style: { shape: "diamond", width: 44, height: 44 } },
    {
      selector: 'node[kind = "address"]',
      style: { shape: "round-tag", width: 22, height: 22, "background-color": dark ? "#475569" : "#cbd5e1", "font-size": 8, color: dark ? "#94a3b8" : "#64748b" },
    },
    { selector: "node[dissolved = 1]", style: { "background-opacity": 0.45, "border-style": "dashed", "border-color": edge } },
    {
      selector: "node[subject = 1]",
      style: { "border-width": 5, "border-color": "#2563eb", "font-weight": "bold", "font-size": 12, width: 48, height: 48 },
    },
    { selector: 'node[subject = 1][kind = "company"]', style: { width: 60, height: 40 } },
    {
      selector: "edge",
      style: {
        width: 1.6,
        "curve-style": "bezier",
        "line-color": edge,
        "target-arrow-color": edge,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.9,
        label: "data(label)",
        "font-size": 8.5,
        color: dark ? "#cbd5e1" : "#334155",
        "text-background-color": halo,
        "text-background-opacity": 0.9,
        "text-background-padding": "2px",
        "text-rotation": "autorotate",
      },
    },
    { selector: 'edge[rel = "shareholder"]', style: { width: 2.4, "font-weight": "bold", "line-color": dark ? "#93c5fd" : "#1e40af", "target-arrow-color": dark ? "#93c5fd" : "#1e40af" } },
    { selector: 'edge[rel = "beneficial_owner"]', style: { "line-style": "dashed", "line-color": "#8b5cf6", "target-arrow-color": "#8b5cf6", color: "#7c3aed" } },
    // Officer roles would clutter the chart: their labels only show around the selected node.
    { selector: 'edge[rel = "officer"]', style: { "line-style": "dotted", "line-color": dark ? "#64748b" : "#94a3b8", "target-arrow-color": dark ? "#64748b" : "#94a3b8", label: "" } },
    { selector: 'edge[rel = "officer"].show-label', style: { label: "data(label)" } },
    { selector: 'edge[rel = "registered_at"]', style: { width: 1, "line-style": "dotted", "line-color": dark ? "#334155" : "#cbd5e1", "target-arrow-shape": "none", label: "" } },
    { selector: "edge[ended = 1]", style: { opacity: 0.4 } },
    { selector: ".faded", style: { opacity: 0.12 } },
    { selector: "node:selected", style: { "overlay-color": "#2563eb", "overlay-opacity": 0.18, "overlay-padding": 6 } },
  ] as StylesheetJson;
}

function runLayout(cy: Core, layout: GraphLayout) {
  if (layout === "hierarchy") {
    // The ownership chart is ranked on ownership edges only (owners above the
    // companies they hold). Officer / address edges are used only for nodes
    // that would otherwise float unattached.
    const ownership = cy.edges('[rel = "shareholder"], [rel = "beneficial_owner"]');
    const anchored = ownership.connectedNodes();
    const helpers = cy.edges('[rel = "officer"], [rel = "registered_at"]').filter(
      (e) => !anchored.contains(e.source()) || !anchored.contains(e.target()),
    );
    cy.elements()
      .not(cy.edges().not(ownership.union(helpers)))
      .layout({
        name: "dagre",
        rankDir: "TB",
        nodeSep: 30,
        rankSep: 90,
        edgeSep: 10,
        nodeDimensionsIncludeLabels: true,
        animate: false,
        fit: true,
        padding: 30,
      } as cytoscape.LayoutOptions)
      .run();
    return;
  }
  cy.layout({
    name: "fcose",
    quality: "proof",
    animate: false,
    randomize: true,
    nodeRepulsion: 9000,
    idealEdgeLength: 110,
    nodeDimensionsIncludeLabels: true,
    fit: true,
    padding: 30,
  } as cytoscape.LayoutOptions).run();
}

const GraphView = forwardRef<GraphHandle, Props>(function GraphView(
  { investigation, layout, filters, theme, selectedId, onSelect },
  ref,
) {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const elements = useMemo(() => buildElements(investigation, filters), [investigation, filters]);

  // Create / rebuild the graph when data or filters change.
  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current,
      elements,
      style: buildStyle(theme),
      wheelSensitivity: 0.25,
      minZoom: 0.15,
      maxZoom: 3,
    });
    cy.on("tap", "node", (evt) => onSelectRef.current(evt.target.id()));
    cy.on("tap", (evt) => {
      if (evt.target === cy) onSelectRef.current(null);
    });
    runLayout(cy, layout);
    cyRef.current = cy;
    return () => cy.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements]);

  useEffect(() => {
    if (cyRef.current) runLayout(cyRef.current, layout);
  }, [layout]);

  useEffect(() => {
    cyRef.current?.style(buildStyle(theme));
  }, [theme]);

  // Highlight the neighbourhood of the selected node.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded show-label").unselect();
    if (!selectedId) return;
    const node = cy.getElementById(selectedId);
    if (node.empty()) return;
    node.select();
    const hood = node.closedNeighborhood();
    cy.elements().not(hood).addClass("faded");
    hood.edges().addClass("show-label");
  }, [selectedId, elements]);

  useImperativeHandle(ref, () => ({
    fit: () => cyRef.current?.fit(undefined, 30),
    exportPng: () => {
      const cy = cyRef.current;
      if (!cy) return null;
      // Always export with the light theme: the PDF has a white background.
      cy.style(buildStyle("light"));
      cy.elements().removeClass("faded show-label").unselect();
      const png = cy.png({ output: "base64uri", full: true, scale: 2, bg: "#ffffff", maxWidth: 3000, maxHeight: 2200 });
      cy.style(buildStyle(theme));
      return png;
    },
  }));

  return <div ref={container} className="h-full w-full" data-testid="graph" />;
});

export default GraphView;

export function GraphLegend() {
  const item = (shape: React.ReactNode, label: string) => (
    <div key={label} className="flex items-center gap-1.5">
      {shape}
      <span>{label}</span>
    </div>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-600 dark:text-slate-400">
      {item(<span className="inline-block h-3 w-3 rounded-full bg-slate-400" />, "Person")}
      {item(<span className="inline-block h-2.5 w-3.5 rounded-sm bg-slate-400" />, "Company")}
      {item(<span className="inline-block h-2.5 w-2.5 rotate-45 bg-slate-400" />, "Offshore entity")}
      {item(<span className="inline-block h-2.5 w-2.5 rounded-sm bg-slate-300 dark:bg-slate-600" />, "Address")}
      {item(<span className="inline-block h-0.5 w-5 bg-blue-800 dark:bg-blue-300" />, "Shareholding %")}
      {item(<span className="inline-block w-5 border-t-2 border-dashed border-violet-500" />, "Declared UBO")}
      {item(<span className="inline-block w-5 border-t-2 border-dotted border-slate-400" />, "Officer")}
      <span className="mx-1 h-3 w-px bg-slate-300 dark:bg-slate-700" />
      {(["none", "low", "medium", "high", "critical"] as RiskLevel[]).map((l) =>
        item(<span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: ENTITY_COLORS[l] }} />, ENTITY_LEVEL_LABEL[l]),
      )}
    </div>
  );
}
