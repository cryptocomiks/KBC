import { geoCentroid, geoNaturalEarth1, geoPath, type GeoPermissibleObjects } from "d3-geo";
import { Globe2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { feature } from "topojson-client";
import type { Investigation, Row } from "../types";

// Small jurisdictions missing from the 1:110m world map (lon, lat): drawn as markers.
const MICRO: Record<string, [number, number]> = {
  VG: [-64.62, 18.42], KY: [-81.25, 19.31], BM: [-64.75, 32.3], BS: [-77.4, 25.03], JE: [-2.13, 49.21],
  GG: [-2.58, 49.45], IM: [-4.55, 54.24], GI: [-5.35, 36.14], MT: [14.45, 35.9], LI: [9.55, 47.16],
  MC: [7.42, 43.74], SC: [55.45, -4.62], MU: [57.55, -20.25], CW: [-68.99, 12.17], AI: [-63.05, 18.22],
  TC: [-71.8, 21.7], MH: [171.2, 7.1], VU: [168.3, -17.7], WS: [-172.1, -13.76], LU: [6.13, 49.61],
  SG: [103.82, 1.35], HK: [114.17, 22.32], AD: [1.52, 42.55], SM: [12.46, 43.94], BH: [50.55, 26.07],
  KN: [-62.78, 17.3], AG: [-61.8, 17.07], LC: [-60.98, 13.9], VC: [-61.2, 13.25], BB: [-59.55, 13.1],
  MO: [113.54, 22.2], CK: [-159.78, -21.24], NR: [166.93, -0.52], LB: [35.86, 33.87], CY: [33.43, 35.13],
}; // fmt: skip

const W = 960;
const H = 440;

function baselColor(score: number | null | undefined): string {
  if (score == null) return "var(--map-nodata)";
  if (score >= 6.5) return "#b91c1c";
  if (score >= 6) return "#ea580c";
  if (score >= 5) return "#f59e0b";
  if (score >= 4) return "#a3a948";
  return "#16a34a";
}

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

type Geo = { type: "Feature"; id?: string; properties: { name: string } } & GeoPermissibleObjects;

/** Where the network sits: countries by money-laundering risk, and ownership flows between them. */
export default function WorldMap({ investigation: inv, onSelect }: Props) {
  const [world, setWorld] = useState<Geo[] | null>(null);
  const [hover, setHover] = useState<Row | null>(null);

  useEffect(() => {
    let alive = true;
    import("world-atlas/countries-110m.json").then((m) => {
      const topo = (m.default ?? m) as unknown as Parameters<typeof feature>[0];
      const fc = feature(topo, (topo as unknown as { objects: { countries: Parameters<typeof feature>[1] } }).objects.countries) as unknown as {
        features: Geo[];
      };
      if (alive) setWorld(fc.features.filter((f) => String(f.id) !== "010")); // no Antarctica
    });
    return () => {
      alive = false;
    };
  }, []);

  const rows = inv.tables.jurisdictions ?? [];
  const byNumeric = useMemo(() => new Map(rows.filter((r) => r.numeric).map((r) => [String(r.numeric), r])), [rows]);

  const projection = useMemo(
    () =>
      world
        ? geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], { type: "FeatureCollection", features: world } as GeoPermissibleObjects)
        : geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], { type: "Sphere" }),
    [world],
  );
  const path = useMemo(() => geoPath(projection), [projection]);

  // Country anchor points (centroid of the shape, or the micro-state coordinates).
  const anchors = useMemo(() => {
    const out = new Map<string, [number, number]>();
    for (const r of rows) {
      const code = String(r.code);
      const f = world?.find((g) => String(g.id) === String(r.numeric));
      const lonlat = MICRO[code] ?? (f ? (geoCentroid(f) as [number, number]) : null);
      const p = lonlat ? projection(lonlat) : null;
      if (p) out.set(code, p as [number, number]);
    }
    return out;
  }, [rows, world, projection]);

  // Ownership flows between countries (owner country -> owned company country).
  const flows = useMemo(() => {
    const ents = new Map(inv.entities.map((e) => [e.id, e]));
    const countryOf = (id: string) => {
      const e = ents.get(id);
      return e ? (e.type === "company" ? e.jurisdiction : e.nationalities[0]) : null;
    };
    const agg = new Map<string, { from: string; to: string; n: number }>();
    for (const r of inv.relationships) {
      if (r.type !== "shareholder" && r.type !== "beneficial_owner") continue;
      const a = countryOf(r.source_id)?.toUpperCase();
      const b = countryOf(r.target_id)?.toUpperCase();
      if (!a || !b || a === b) continue;
      const k = `${a}>${b}`;
      agg.set(k, { from: a, to: b, n: (agg.get(k)?.n ?? 0) + 1 });
    }
    return [...agg.values()];
  }, [inv]);

  if (!rows.length) return null;
  const firstEntity = (code: string) => inv.entities.find((e) => (e.type === "company" ? e.jurisdiction : e.nationalities[0])?.toUpperCase() === code);

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <Globe2 className="h-4 w-4 text-brand-600" />
        <h2 className="text-sm font-semibold">Where the network sits</h2>
        <span className="text-[11px] text-slate-500">{rows.length} countries · {flows.length} cross-border ownership links</span>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
          Basel AML Index:
          {[
            ["< 4", "#16a34a"],
            ["4–5", "#a3a948"],
            ["5–6", "#f59e0b"],
            ["6–6.5", "#ea580c"],
            ["≥ 6.5", "#b91c1c"],
          ].map(([l, c]) => (
            <span key={l} className="inline-flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />
              {l}
            </span>
          ))}
          <span className="inline-flex items-center gap-1">
            <span className="h-0.5 w-5 bg-slate-700 dark:bg-slate-200" /> ownership
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-3 w-3 rounded-full border border-dashed border-slate-700 dark:border-slate-200" /> offshore centre
          </span>
        </div>
      </div>
      <div className="relative bg-sky-50/60 dark:bg-slate-950 [--map-land:#e2e8f0] [--map-nodata:#94a3b8] dark:[--map-land:#1e293b] dark:[--map-nodata:#64748b]">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="World map of the network">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-slate-700 dark:fill-slate-200" />
            </marker>
          </defs>
          {world?.map((f) => {
            const r = byNumeric.get(String(f.id));
            return (
              <path
                key={String(f.id) + f.properties.name}
                d={path(f) ?? ""}
                fill={r ? baselColor(r.basel_aml_score as number | null) : "var(--map-land)"}
                className={`stroke-white dark:stroke-slate-900 ${r ? "cursor-pointer" : ""}`}
                strokeWidth={0.5}
                onMouseEnter={() => r && setHover(r)}
                onMouseLeave={() => setHover(null)}
                onClick={() => {
                  const e = r && firstEntity(String(r.code));
                  if (e) onSelect(e.id);
                }}
              />
            );
          })}
          {flows.map((fl) => {
            const a = anchors.get(fl.from);
            const b = anchors.get(fl.to);
            if (!a || !b) return null;
            const mx = (a[0] + b[0]) / 2;
            const my = (a[1] + b[1]) / 2 - Math.min(120, Math.hypot(b[0] - a[0], b[1] - a[1]) / 3);
            return (
              <path
                key={`${fl.from}>${fl.to}`}
                d={`M${a[0]},${a[1]} Q${mx},${my} ${b[0]},${b[1]}`}
                fill="none"
                className="stroke-slate-700 dark:stroke-slate-200"
                strokeWidth={Math.min(4, 1 + fl.n * 0.6)}
                strokeOpacity={0.8}
                markerEnd="url(#arrow)"
              >
                <title>{`${fl.from} → ${fl.to}: ${fl.n} ownership link(s)`}</title>
              </path>
            );
          })}
          {rows.map((r) => {
            const code = String(r.code);
            const p = anchors.get(code);
            if (!p) return null;
            const offshore = String(r.lists).includes("Offshore");
            return (
              <g key={code} onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
                <circle cx={p[0]} cy={p[1]} r={5} fill={baselColor(r.basel_aml_score as number | null)} className="stroke-slate-900 dark:stroke-white" strokeWidth={1.2} />
                {offshore && <circle cx={p[0]} cy={p[1]} r={9} fill="none" className="stroke-slate-900 dark:stroke-white" strokeWidth={1.2} strokeDasharray="2 2" />}
                <text x={p[0] + 9} y={p[1] + 4} className="fill-slate-800 text-[11px] font-semibold dark:fill-slate-100">
                  {code}
                </text>
              </g>
            );
          })}
        </svg>
        {hover && (
          <div className="pointer-events-none absolute left-3 top-3 max-w-xs rounded-lg border border-slate-200 bg-white/95 p-2.5 text-xs shadow dark:border-slate-700 dark:bg-slate-900/95">
            <div className="font-semibold">{String(hover.country)}</div>
            <div>{String(hover.entities)} entit(ies): {String(hover.examples)}</div>
            <div className="mt-1 text-slate-500">
              Basel AML {hover.basel_aml_score != null ? `${Number(hover.basel_aml_score).toFixed(2)}/10` : "n/a"} · CPI{" "}
              {hover.cpi_score != null ? `${hover.cpi_score}/100` : "n/a"}
            </div>
            {hover.lists ? <div className="font-semibold text-red-600">{String(hover.lists)}</div> : null}
          </div>
        )}
      </div>
    </div>
  );
}
