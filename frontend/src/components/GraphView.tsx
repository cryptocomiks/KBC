import cytoscape, { type Core, type ElementDefinition, type NodeSingular, type StylesheetJson } from "cytoscape";
import dagre from "cytoscape-dagre";
import fcose from "cytoscape-fcose";
import { Download, Maximize, Minimize, Minus, Plus, Scan, X } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { ENTITY_COLORS, ENTITY_LEVEL_LABEL } from "../lib/format";
import type { Theme } from "../lib/theme";
import type { Investigation, Relationship, RiskLevel } from "../types";

cytoscape.use(dagre);
cytoscape.use(fcose);

export type GraphLayout = "hierarchy" | "network";
export interface GraphFilters {
  crypto: boolean;
  addresses: boolean;
  officers: boolean;
  ended: boolean;
  /** Network view: companies grouped in one frame per country. */
  countries?: boolean;
}
export interface GraphHandle {
  exportPng: () => string | null;
  fit: () => void;
  /** Re-measures the container (after being hidden) and fits the graph. */
  refresh: () => void;
}

interface Props {
  investigation: Investigation;
  layout: GraphLayout;
  filters: GraphFilters;
  theme: Theme;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", "Helvetica Neue", sans-serif';
const MONO = 'ui-monospace, "SF Mono", Menlo, monospace';
const FONT_SIZE = 11.5;
const BLUE = "#0071e3";
/** Room around the chart for the floating controls. */
const PAD = 56;
const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

let measureCtx: CanvasRenderingContext2D | null = null;
function textWidth(text: string, mono = false): number {
  if (!measureCtx && typeof document !== "undefined") measureCtx = document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * 6.5;
  measureCtx.font = `500 ${FONT_SIZE}px ${mono ? MONO : FONT}`;
  return measureCtx.measureText(text).width;
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Mix a hex colour with a background (t = share of the background). */
function tint(hex: string, bg: string, t: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [a, b] = [p(hex), p(bg)];
  return `#${a.map((v, i) => Math.round(v * (1 - t) + b[i] * t).toString(16).padStart(2, "0")).join("")}`;
}

let regionNames: Intl.DisplayNames | null = null;
function countryName(iso: string): string {
  try {
    regionNames ??= new Intl.DisplayNames(["en"], { type: "region" });
    return regionNames.of(iso) ?? iso;
  } catch {
    return iso;
  }
}

function shortRole(role: string | null): string {
  if (!role) return "officer";
  return clip(role.split(" / ")[0].replace(/ \((Wikidata|EGRUL|RPO|Zefix)\)$/, ""), 26);
}

const LEGAL_FORMS: [RegExp, string][] = [
  [/soci[ée]t[ée] par actions simplifi[ée]e/i, "SAS"],
  [/soci[ée]t[ée] [àa] responsabilit[ée] limit[ée]e/i, "SARL"],
  [/soci[ée]t[ée] civile immobili[èe]re/i, "SCI"],
  [/soci[ée]t[ée] anonyme/i, "SA"],
  [/soci[ée]t[ée] en nom collectif/i, "SNC"],
  [/private (limited )?company|limited by shares|private limited/i, "Ltd"],
  [/public limited company/i, "PLC"],
  [/limited liability company/i, "LLC"],
  [/limited liability partnership/i, "LLP"],
  [/limited partnership/i, "LP"],
  [/bvi business company/i, "BVI BC"],
  [/gesellschaft mit beschr[äa]nkter haftung/i, "GmbH"],
  [/aktiengesellschaft/i, "AG"],
  [/foundation|stiftung|fondation/i, "Foundation"],
  [/trust/i, "Trust"],
];

function shortForm(form: string | null): string | null {
  if (!form) return null;
  const hit = LEGAL_FORMS.find(([re]) => re.test(form));
  if (hit) return hit[1];
  return form.length <= 14 ? form : null;
}

/** Splits a long name over two lines at a word boundary (max ~30 characters per line). */
function wrapName(name: string): string[] {
  if (name.length <= 34) return [name];
  const words = name.split(" ");
  let first = "";
  while (words.length && (first + " " + words[0]).trim().length <= 30) first = `${first} ${words.shift()}`.trim();
  if (!first) return [clip(name, 30)];
  return [first, clip(words.join(" "), 30)];
}

const PRIORITY: Relationship["type"][] = ["shareholder", "beneficial_owner", "controls", "transfer", "relative", "officer", "registered_at"];

function buildElements(inv: Investigation, filters: GraphFilters, layout: GraphLayout, theme: Theme): ElementDefinition[] {
  const dark = theme === "dark";
  const canvas = dark ? "#1c1c1e" : "#ffffff";
  const visible = new Set<string>();
  const nodes: ElementDefinition[] = [];
  const groups = new Map<string, number>();
  const grouped = layout === "network" && !!filters.countries;
  for (const e of inv.entities) {
    if (e.type === "address" && !filters.addresses) continue;
    if (e.type === "wallet" && !filters.crypto) continue;
    visible.add(e.id);
    const level: RiskLevel = inv.risk.entity_levels[e.id] ?? "none";
    const kind = e.type === "company" ? (e.is_offshore ? "offshore" : "company") : e.type;
    let lines: string[];
    if (e.type === "wallet") {
      lines = [`${e.name.slice(0, 6)}…${e.name.slice(-4)}`, [e.chain, e.extra.label ? clip(String(e.extra.label), 24) : null].filter(Boolean).join(" · ")];
    } else if (e.type === "address") {
      lines = [clip(e.name.split(",")[0], 30)];
    } else if (e.type === "company") {
      const meta = [e.jurisdiction, shortForm(e.legal_form), e.is_offshore ? "offshore" : null, e.status === "dissolved" ? "dissolved" : null];
      lines = [...wrapName(e.name), meta.filter(Boolean).join(" · ") || "Company"];
    } else {
      const meta = [e.nationalities[0], e.birth_date ? `b. ${e.birth_date.slice(0, 4)}` : null];
      lines = [...wrapName(e.name), meta.filter(Boolean).join(" · ") || "Person"];
    }
    lines = lines.filter(Boolean);
    const mono = e.type === "wallet";
    const w = Math.round(Math.min(230, Math.max(e.type === "address" ? 60 : 96, Math.max(...lines.map((l) => textWidth(l, mono))) + 26)));
    const h = 14 + lines.length * 15;
    const risk = ENTITY_COLORS[level];
    // Minor findings only colour the border: a tinted fill is kept for what needs attention.
    const flagged = level !== "none" && level !== "incomplete";
    const filled = level === "medium" || level === "high" || level === "critical";
    const parent = grouped && e.type === "company" && e.jurisdiction ? `country:${e.jurisdiction}` : undefined;
    if (parent) groups.set(parent, (groups.get(parent) ?? 0) + 1);
    nodes.push({
      data: {
        id: e.id,
        parent,
        label: lines.join("\n"),
        kind,
        level,
        w,
        h,
        radius: e.type === "person" ? h / 2 : 10,
        border: flagged ? risk : dark ? "#48484a" : "#d2d2d7",
        bg: filled ? tint(risk, canvas, dark ? 0.78 : 0.88) : dark ? "#2c2c2e" : "#ffffff",
        subject: e.id === inv.subject_id ? 1 : 0,
        dissolved: e.status === "dissolved" ? 1 : 0,
      },
    });
  }
  for (const [id] of groups) {
    const iso = id.slice(8);
    nodes.push({ data: { id, label: `${countryName(iso)} · ${iso}`.toUpperCase(), kind: "country", w: 1, h: 1, radius: 18, bg: canvas, border: canvas } });
  }

  // One visual edge per ordered pair: "60 % · UBO · President" instead of three parallel curves.
  const merged = new Map<string, Relationship[]>();
  for (const r of inv.relationships) {
    if (!visible.has(r.source_id) || !visible.has(r.target_id)) continue;
    if (r.type === "officer" && !filters.officers) continue;
    if (r.end_date && !filters.ended) continue;
    const key = `${r.source_id}>${r.target_id}`;
    merged.set(key, [...(merged.get(key) ?? []), r]);
  }
  const edges: ElementDefinition[] = [];
  for (const [key, rels] of merged) {
    rels.sort((a, b) => PRIORITY.indexOf(a.type) - PRIORITY.indexOf(b.type));
    const main = rels[0];
    const pct = Math.max(...rels.map((r) => (r.type === "shareholder" || r.type === "beneficial_owner" ? (r.share_pct ?? -1) : -1)));
    const types = new Set(rels.map((r) => r.type));
    const always: string[] = [];
    if (pct >= 0) always.push(`${Number(pct.toFixed(2))} %`);
    else if (types.has("shareholder")) always.push("shareholder");
    if (types.has("beneficial_owner")) always.push("UBO");
    if (types.has("controls")) always.push("controls");
    for (const r of rels) {
      if (r.type === "transfer")
        always.push(`${(r.amount ?? 0).toLocaleString("en", { maximumFractionDigits: r.currency === "BTC" || r.currency === "ETH" ? 4 : 0 })} ${r.currency ?? ""}`.trim());
      if (r.type === "relative") always.push((r.role ?? "relative").replace(" (Wikidata)", ""));
    }
    const roles = [...new Set(rels.filter((r) => r.type === "officer").map((r) => shortRole(r.role)))];
    const ended = rels.every((r) => r.end_date) ? 1 : 0;
    const suffix = ended ? " (ended)" : "";
    edges.push({
      data: {
        id: `e:${key}`,
        source: main.source_id,
        target: main.target_id,
        rel: main.type,
        ownership: types.has("shareholder") || types.has("beneficial_owner") ? 1 : 0,
        share: pct >= 0 ? pct : 0,
        label: always.length ? always.join(" · ") + suffix : "",
        full: [...always, ...roles].join(" · ") + suffix,
        ended,
      },
    });
  }
  return [...nodes, ...edges];
}

function buildStyle(theme: Theme): StylesheetJson {
  const dark = theme === "dark";
  const text = dark ? "#f5f5f7" : "#1d1d1f";
  const sub = dark ? "#a1a1a6" : "#6e6e73";
  const line = dark ? "#636366" : "#aeaeb2";
  const own = dark ? "#64a8ff" : "#1d4ed8";
  const pill = dark ? "#1c1c1e" : "#ffffff";
  return [
    {
      selector: "node",
      style: {
        shape: "round-rectangle",
        width: "data(w)",
        height: "data(h)",
        "corner-radius": "data(radius)",
        "background-color": "data(bg)",
        "border-width": 1.5,
        "border-color": "data(border)",
        label: "data(label)",
        color: text,
        "font-family": FONT,
        "font-size": FONT_SIZE,
        "font-weight": 500,
        "text-valign": "center",
        "text-halign": "center",
        "text-wrap": "wrap",
        "line-height": 1.35,
        "transition-property": "opacity, border-width, underlay-opacity",
        "transition-duration": 180,
        "underlay-shape": "round-rectangle",
        "underlay-corner-radius": 14,
        "underlay-padding": 0,
        "underlay-opacity": 0,
      },
    },
    { selector: 'node[level = "high"], node[level = "critical"]', style: { "border-width": 2.5 } },
    { selector: 'node[kind = "address"]', style: { "font-size": 10, color: sub, "border-style": "dashed", "background-color": dark ? "#2c2c2e" : "#f5f5f7" } },
    { selector: 'node[kind = "wallet"]', style: { "font-family": MONO, "font-size": 10.5, "border-color": "#f59e0b" } },
    { selector: 'node[kind = "offshore"]', style: { "border-style": "double", "border-width": 4 } },
    { selector: "node[dissolved = 1]", style: { opacity: 0.55, "border-style": "dashed" } },
    {
      selector: "node[subject = 1]",
      style: {
        "border-width": 2.5,
        "border-color": BLUE,
        "font-weight": 700,
        "underlay-color": BLUE,
        "underlay-opacity": 0.14,
        "underlay-padding": 7,
      },
    },
    {
      selector: 'node[kind = "country"]',
      style: {
        shape: "round-rectangle",
        "corner-radius": 18,
        "background-color": dark ? "#ffffff" : "#000000",
        "background-opacity": dark ? 0.04 : 0.025,
        "border-width": 1,
        "border-style": "dashed",
        "border-color": dark ? "#48484a" : "#d2d2d7",
        label: "data(label)",
        "font-size": 9.5,
        "font-weight": 600,
        color: sub,
        "text-valign": "top",
        "text-halign": "center",
        "text-margin-y": -6,
        padding: "18px",
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.4,
        "curve-style": "bezier",
        "control-point-step-size": 36,
        "line-color": line,
        "target-arrow-color": line,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.75,
        label: "data(label)",
        "font-family": FONT,
        "font-size": 10.5,
        "font-weight": 600,
        color: sub,
        "text-background-color": pill,
        "text-background-opacity": 1,
        "text-background-shape": "round-rectangle",
        "text-background-padding": "3px",
        "text-border-width": 1,
        "text-border-color": dark ? "#3a3a3c" : "#e5e5ea",
        "text-border-opacity": 1,
        "transition-property": "opacity, line-color, width",
        "transition-duration": 180,
      },
    },
    { selector: 'edge[label = ""]', style: { "text-background-opacity": 0, "text-border-opacity": 0 } },
    {
      selector: "edge[ownership = 1]",
      style: { width: "mapData(share, 0, 100, 1.6, 5)", "line-color": own, "target-arrow-color": own, color: own },
    },
    { selector: 'edge[rel = "beneficial_owner"]', style: { "line-style": "dashed", "line-color": "#8b5cf6", "target-arrow-color": "#8b5cf6", color: "#7c3aed" } },
    { selector: 'edge[rel = "officer"]', style: { "line-style": "dashed", "line-dash-pattern": [2, 4], "line-color": line, "target-arrow-color": line } },
    { selector: 'edge[rel = "transfer"]', style: { width: 2.2, "line-color": "#f59e0b", "target-arrow-color": "#f59e0b", color: dark ? "#fcd34d" : "#b45309" } },
    { selector: 'edge[rel = "relative"]', style: { "line-style": "dotted", width: 2, "line-color": "#ec4899", "target-arrow-shape": "none", color: dark ? "#f9a8d4" : "#be185d" } },
    { selector: 'edge[rel = "controls"]', style: { "line-style": "dashed", "line-color": "#14b8a6", "target-arrow-color": "#14b8a6", color: "#0f766e" } },
    { selector: 'edge[rel = "registered_at"]', style: { width: 1, "line-style": "dotted", "line-color": dark ? "#3a3a3c" : "#d2d2d7", "target-arrow-shape": "none" } },
    { selector: "edge[ended = 1]", style: { opacity: 0.45 } },
    { selector: "edge.show-label", style: { label: "data(full)", "text-background-opacity": 1, "text-border-opacity": 1, "z-index": 20 } },
    { selector: ".faded", style: { opacity: 0.14 } },
    { selector: "node:selected", style: { "underlay-color": BLUE, "underlay-opacity": 0.22, "underlay-padding": 8, "border-color": BLUE, "border-width": 2.5 } },
    { selector: "node.path", style: { "border-color": BLUE, "border-width": 2.5, "underlay-color": BLUE, "underlay-opacity": 0.14, "underlay-padding": 6 } },
    { selector: "edge.path", style: { "line-color": BLUE, "target-arrow-color": BLUE, color: BLUE, width: 4, "z-index": 30, opacity: 1 } },
    { selector: "node.hover", style: { "underlay-color": dark ? "#ffffff" : "#000000", "underlay-opacity": 0.08, "underlay-padding": 6 } },
  ] as StylesheetJson;
}

function runLayout(cy: Core, layout: GraphLayout, animate = false) {
  const anim = animate && !reducedMotion() ? { animate: true, animationDuration: 420, animationEasing: "ease-in-out-cubic" } : { animate: false };
  if (layout === "hierarchy") {
    // Ranked on ownership edges only (owners above what they hold); officer / address edges
    // only place nodes that would otherwise float unattached.
    const ownership = cy.edges("[ownership = 1]");
    const anchored = ownership.connectedNodes();
    const helpers = cy.edges('[rel != "shareholder"][rel != "beneficial_owner"]').filter(
      (e) => !anchored.contains(e.source()) || !anchored.contains(e.target()),
    );
    cy.elements()
      .not(cy.edges().not(ownership.union(helpers)))
      .layout({ name: "dagre", rankDir: "TB", nodeSep: 26, rankSep: 76, edgeSep: 12, ranker: "network-simplex", fit: true, padding: PAD, ...anim } as unknown as cytoscape.LayoutOptions)
      .run();
    return;
  }
  cy.layout({
    name: "fcose",
    quality: "proof",
    randomize: !animate,
    nodeRepulsion: 12000,
    idealEdgeLength: 120,
    edgeElasticity: 0.3,
    nestingFactor: 0.6,
    nodeSeparation: 90,
    tilingPaddingVertical: 24,
    tilingPaddingHorizontal: 24,
    fit: true,
    padding: PAD,
    ...anim,
  } as unknown as cytoscape.LayoutOptions).run();
}

/** Minimum zoom when a chart opens: a large network is centred on the subject at a readable size
 *  instead of being shrunk to fit (the "fit" control still shows it whole). */
const READABLE_ZOOM = 0.85;

function readableView(cy: Core, subjectId: string) {
  cy.fit(undefined, PAD);
  if (cy.zoom() >= READABLE_ZOOM) return;
  const subject = cy.getElementById(subjectId);
  cy.zoom(READABLE_ZOOM);
  cy.center(subject.nonempty() ? subject : undefined);
}

/** Ownership chain between the subject and a node, with the effective percentage. */
function controlChain(cy: Core, subjectId: string, id: string) {
  const ownership = cy.edges("[ownership = 1]");
  const graph = ownership.union(ownership.connectedNodes());
  const from = cy.getElementById(id);
  const to = cy.getElementById(subjectId);
  if (from.empty() || to.empty() || id === subjectId) return null;
  for (const [root, goal, down] of [
    [from, to, false], // the node owns the subject (upstream)
    [to, from, true], // the subject owns the node (downstream)
  ] as const) {
    const res = graph.aStar({ root, goal, directed: true });
    if (res.found && res.path.edges().length) {
      const shares = res.path.edges().map((e) => Number(e.data("share")) || 0);
      const effective = shares.every((s) => s > 0) ? shares.reduce((a, s) => (a * s) / 100, 100) : null;
      return { path: res.path, names: res.path.nodes().map((n) => String(n.data("label")).split("\n")[0]), effective, down };
    }
  }
  return null;
}

const GraphView = forwardRef<GraphHandle, Props>(function GraphView({ investigation, layout, filters, theme, selectedId, onSelect }, ref) {
  const wrap = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [chain, setChain] = useState<{ names: string[]; effective: number | null; down: boolean } | null>(null);
  const [full, setFull] = useState(false);

  const elements = useMemo(() => buildElements(investigation, filters, layout, theme), [investigation, filters, theme, layout === "network" && !!filters.countries]); // eslint-disable-line react-hooks/exhaustive-deps

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
      boxSelectionEnabled: false,
    });
    cy.on("tap", "node", (evt) => {
      if (evt.target.data("kind") !== "country") onSelectRef.current(evt.target.id());
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) onSelectRef.current(null);
    });
    cy.on("dbltap", "node", (evt) => {
      const n = evt.target as NodeSingular;
      cy.animate({ fit: { eles: n.closedNeighborhood(), padding: 60 }, duration: reducedMotion() ? 0 : 380, easing: "ease-in-out-cubic" });
    });
    cy.on("mouseover", "node", (evt) => {
      const n = evt.target as NodeSingular;
      if (n.data("kind") === "country") return;
      n.addClass("hover");
      n.connectedEdges().addClass("show-label");
      if (container.current) container.current.style.cursor = "pointer";
    });
    cy.on("mouseout", "node", (evt) => {
      const n = evt.target as NodeSingular;
      n.removeClass("hover");
      if (!n.selected()) n.connectedEdges().not(cy.$(":selected").connectedEdges()).removeClass("show-label");
      if (container.current) container.current.style.cursor = "";
    });
    runLayout(cy, layout);
    readableView(cy, investigation.subject_id);
    cyRef.current = cy;
    if (import.meta.env.DEV) (window as unknown as { __cy?: Core }).__cy = cy;
    return () => cy.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements]);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const cy = cyRef.current;
    if (!cy) return;
    cy.style(buildStyle(theme));
    runLayout(cy, layout, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout]);

  // Highlight the neighbourhood of the selected node and its ownership chain to the subject.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded show-label path").unselect();
    setChain(null);
    if (!selectedId) return;
    const node = cy.getElementById(selectedId);
    if (node.empty()) return;
    node.select();
    const hood = node.closedNeighborhood();
    const found = controlChain(cy, investigation.subject_id, selectedId);
    const keep = found ? hood.union(found.path) : hood;
    cy.elements().not(keep).not('node[kind = "country"]').addClass("faded");
    hood.edges().addClass("show-label");
    if (found) {
      found.path.addClass("path");
      setChain({ names: found.names, effective: found.effective, down: found.down });
    }
  }, [selectedId, elements, investigation.subject_id]);

  useEffect(() => {
    const onChange = () => {
      setFull(document.fullscreenElement === wrap.current);
      requestAnimationFrame(() => {
        cyRef.current?.resize();
        cyRef.current?.fit(undefined, PAD);
      });
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const exportPng = () => {
    const cy = cyRef.current;
    if (!cy) return null;
    // Always export with the light theme: the PDF has a white background.
    const light = buildElements(investigation, filters, layout, "light");
    const colours = new Map(light.map((e) => [e.data.id, e.data]));
    cy.batch(() => {
      cy.style(buildStyle("light"));
      cy.nodes().forEach((n) => {
        const d = colours.get(n.id());
        if (d) n.data({ bg: d.bg, border: d.border });
      });
      cy.elements().removeClass("faded show-label path hover").unselect();
    });
    const png = cy.png({ output: "base64uri", full: true, scale: 2, bg: "#ffffff", maxWidth: 3200, maxHeight: 2400 });
    const current = new Map(elements.map((e) => [e.data.id, e.data]));
    cy.batch(() => {
      cy.style(buildStyle(theme));
      cy.nodes().forEach((n) => {
        const d = current.get(n.id());
        if (d) n.data({ bg: d.bg, border: d.border });
      });
    });
    if (selectedId) onSelectRef.current(null);
    return png;
  };

  useImperativeHandle(ref, () => ({
    fit: () => cyRef.current?.fit(undefined, PAD),
    refresh: () => {
      if (!cyRef.current) return;
      cyRef.current.resize();
      readableView(cyRef.current, investigation.subject_id);
    },
    exportPng,
  }));

  const zoom = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    const level = Math.min(3, Math.max(0.15, cy.zoom() * factor));
    cy.animate({ zoom: { level, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }, duration: reducedMotion() ? 0 : 200 });
  };
  const download = () => {
    const png = exportPng();
    if (!png) return;
    const a = document.createElement("a");
    a.href = png;
    const name = investigation.entities.find((e) => e.id === investigation.subject_id)?.name ?? "network";
    a.download = `${name.normalize("NFD").replace(/[^\w]+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "network"}-structure.png`;
    a.click();
  };
  const toggleFull = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void wrap.current?.requestFullscreen?.();
  };

  return (
    <div ref={wrap} className={`relative h-full w-full ${full ? "bg-[#f5f5f7] dark:bg-black" : ""}`}>
      <div ref={container} className="h-full w-full" data-testid="graph" />
      {chain && (
        <div className="glass-panel absolute top-3 left-3 max-w-[calc(100%-1.5rem)] rounded-2xl px-3.5 py-2 text-[12px] shadow-sm">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#0071e3]">{chain.down ? "Held by the subject" : "Owns the subject"}</span>
            {chain.effective != null && (
              <span className="rounded-full bg-[#0071e3]/10 px-2 py-0.5 font-semibold text-[#0071e3] tabular-nums">
                effective {Number(chain.effective.toFixed(2))} %
              </span>
            )}
            <button onClick={() => onSelectRef.current(null)} className="ml-auto rounded-full p-0.5 text-slate-400 hover:text-slate-700 dark:hover:text-white" aria-label="Clear selection">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="mt-0.5 text-slate-600 dark:text-slate-300">{chain.names.join(" → ")}</div>
        </div>
      )}
      <div className="glass-panel absolute right-3 bottom-3 flex items-center gap-0.5 rounded-full p-1 shadow-sm">
        {(
          [
            [Plus, "Zoom in", () => zoom(1.25)],
            [Minus, "Zoom out", () => zoom(0.8)],
            [Scan, "Fit to screen", () => cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: PAD }, duration: reducedMotion() ? 0 : 300 })],
            [full ? Minimize : Maximize, full ? "Exit full screen" : "Full screen", toggleFull],
            [Download, "Download as image (PNG)", download],
          ] as const
        ).map(([Icon, label, onClick]) => (
          <button
            key={label}
            onClick={onClick}
            title={label}
            aria-label={label}
            className="flex h-8 w-8 items-center justify-center rounded-full text-slate-600 transition-colors hover:bg-black/[0.06] hover:text-slate-900 dark:text-slate-300 dark:hover:bg-white/[0.1] dark:hover:text-white"
          >
            <Icon className="h-4 w-4" />
          </button>
        ))}
      </div>
    </div>
  );
});

export default GraphView;

export function GraphLegend() {
  const item = (shape: React.ReactNode, label: string) => (
    <div key={label} className="flex items-center gap-1.5">
      {shape}
      <span>{label}</span>
    </div>
  );
  const card = "inline-block h-3 border-[1.5px] border-slate-400 bg-white dark:bg-slate-800";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-600 dark:text-slate-400">
      {item(<span className={`${card} w-4 rounded-full`} />, "Person")}
      {item(<span className={`${card} w-4 rounded-[3px]`} />, "Company")}
      {item(<span className="inline-block h-3 w-4 rounded-[3px] border-[3px] border-double border-slate-400" />, "Offshore")}
      {item(<span className="inline-block h-3 w-4 rounded-[3px] border-2 border-[#0071e3]" />, "Subject")}
      {item(<span className="inline-block h-[3px] w-5 rounded bg-blue-700 dark:bg-blue-400" />, "Shareholding (width = %)")}
      {item(<span className="inline-block w-5 border-t-2 border-dashed border-violet-500" />, "Declared UBO")}
      {item(<span className="inline-block w-5 border-t-2 border-dotted border-slate-400" />, "Officer")}
      {item(<span className="inline-block h-0.5 w-5 bg-amber-500" />, "On-chain flow")}
      {item(<span className="inline-block w-5 border-t-2 border-dotted border-pink-500" />, "Family / associate")}
      <span className="mx-1 h-3 w-px bg-slate-300 dark:bg-slate-700" />
      {(["low", "medium", "high", "critical"] as RiskLevel[]).map((l) =>
        item(<span className="inline-block h-3 w-4 rounded-[3px] border-[1.5px]" style={{ borderColor: ENTITY_COLORS[l], background: `${ENTITY_COLORS[l]}22` }} />, ENTITY_LEVEL_LABEL[l]),
      )}
      <span className="text-slate-400">Click: control chain · double-click: zoom on neighbours</span>
    </div>
  );
}
