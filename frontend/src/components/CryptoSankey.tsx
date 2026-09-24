import { sankey, sankeyLinkHorizontal, type SankeyLink, type SankeyNode } from "d3-sankey";
import { Waypoints } from "lucide-react";
import { useMemo, useState } from "react";
import type { Investigation } from "../types";

const W = 960;
const H = 280;

interface N {
  id: string;
  label: string;
  sanctioned: boolean;
  subject: boolean;
}
interface L {
  source: string;
  target: string;
  value: number;
  tx: number;
}

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

const short = (a: string) => (a.length > 16 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a);

/** Where the money comes from and where it goes: aggregated on-chain flows, sanctioned wallets in red. */
export default function CryptoSankey({ investigation: inv, onSelect }: Props) {
  const transfers = inv.relationships.filter((r) => r.type === "transfer" && r.amount);
  const currencies = useMemo(() => {
    const tot = new Map<string, number>();
    for (const r of transfers) tot.set(r.currency ?? "?", (tot.get(r.currency ?? "?") ?? 0) + (r.amount ?? 0));
    return [...tot.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c);
  }, [transfers]);
  const [currency, setCurrency] = useState<string | null>(null);
  const cur = currency ?? currencies[0];

  const graph = useMemo(() => {
    if (!cur) return null;
    const ents = new Map(inv.entities.map((e) => [e.id, e]));
    const sanctioned = new Set(inv.hits.filter((h) => h.list_type === "sanction" && h.score >= 85).map((h) => h.entity_id));
    // Owner of each wallet (controls relationship), to label wallets with a name.
    const owner = new Map<string, string>();
    for (const r of inv.relationships) if (r.type === "controls") owner.set(r.target_id, r.source_id);
    for (const [w, o] of owner) if (sanctioned.has(o)) sanctioned.add(w);

    // Net flows per pair (a sankey cannot draw A→B and B→A at once).
    const pair = new Map<string, L>();
    for (const r of transfers.filter((t) => (t.currency ?? "?") === cur)) {
      const [a, b] = [r.source_id, r.target_id];
      const back = pair.get(`${b}>${a}`);
      if (back) {
        back.value -= r.amount ?? 0;
        back.tx += r.tx_count ?? 0;
        if (back.value < 0) {
          pair.delete(`${b}>${a}`);
          pair.set(`${a}>${b}`, { source: a, target: b, value: -back.value, tx: back.tx });
        }
      } else {
        const cur2 = pair.get(`${a}>${b}`);
        pair.set(`${a}>${b}`, {
          source: a,
          target: b,
          value: (cur2?.value ?? 0) + (r.amount ?? 0),
          tx: (cur2?.tx ?? 0) + (r.tx_count ?? 0),
        });
      }
    }
    // Drop links closing a cycle (longer loops), keeping the largest flows first.
    const links: L[] = [];
    const adj = new Map<string, Set<string>>();
    const reaches = (from: string, to: string, seen = new Set<string>()): boolean => {
      if (from === to) return true;
      seen.add(from);
      for (const n of adj.get(from) ?? []) if (!seen.has(n) && reaches(n, to, seen)) return true;
      return false;
    };
    for (const l of [...pair.values()].filter((l) => l.value > 0).sort((a, b) => b.value - a.value)) {
      if (reaches(l.target, l.source)) continue;
      links.push(l);
      if (!adj.has(l.source)) adj.set(l.source, new Set());
      adj.get(l.source)!.add(l.target);
    }
    if (!links.length) return null;
    const ids = [...new Set(links.flatMap((l) => [l.source, l.target]))];
    const nodes: N[] = ids.map((id) => {
      const e = ents.get(id);
      const o = owner.get(id);
      const ownerName = o ? ents.get(o)?.name : undefined;
      const label = ownerName ? `${ownerName} · ${short(e?.name ?? id)}` : short(e?.name ?? id);
      return { id, label, sanctioned: sanctioned.has(id), subject: id === inv.subject_id || o === inv.subject_id };
    });
    const layout = sankey<N, L>()
      .nodeId((d) => d.id)
      .nodeWidth(12)
      .nodePadding(14)
      .extent([
        [8, 8],
        [W - 8, H - 8],
      ]);
    return layout({ nodes: nodes.map((d) => ({ ...d })), links: links.map((d) => ({ ...d })) });
  }, [inv, transfers, cur]);

  if (!transfers.length) return null;

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-2 dark:border-slate-800">
        <Waypoints className="h-4 w-4 text-brand-600" />
        <h2 className="text-sm font-semibold">Crypto flows</h2>
        <span className="text-[11px] text-slate-500">aggregated on-chain transfers, one hop · width = amount · red = sanctioned</span>
        {currencies.length > 1 && (
          <select className="input ml-auto py-1 text-xs" value={cur} onChange={(e) => setCurrency(e.target.value)}>
            {currencies.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        )}
      </div>
      {!graph ? (
        <p className="p-4 text-sm text-slate-500">No flow to draw in {cur}.</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="Crypto flow diagram">
          {graph.links.map((l: SankeyLink<N, L>, i) => {
            const s = l.source as SankeyNode<N, L>;
            const t = l.target as SankeyNode<N, L>;
            const red = s.sanctioned || t.sanctioned;
            return (
              <path
                key={i}
                d={sankeyLinkHorizontal()(l) ?? ""}
                fill="none"
                stroke={red ? "#dc2626" : "#64748b"}
                strokeOpacity={red ? 0.55 : 0.3}
                strokeWidth={Math.max(1.5, l.width ?? 1)}
              >
                <title>{`${s.label} → ${t.label}\n${l.value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${cur} · ${l.tx} tx`}</title>
              </path>
            );
          })}
          {graph.nodes.map((n: SankeyNode<N, L>) => {
            const x0 = n.x0 ?? 0;
            const x1 = n.x1 ?? 0;
            const y0 = n.y0 ?? 0;
            const y1 = n.y1 ?? 0;
            const left = x0 < W / 2;
            return (
              <g key={n.id} className="cursor-pointer" onClick={() => onSelect(n.id)}>
                <rect x={x0} y={y0} width={x1 - x0} height={Math.max(2, y1 - y0)} rx={2} fill={n.sanctioned ? "#dc2626" : n.subject ? "#2563eb" : "#94a3b8"} />
                <text
                  x={left ? x1 + 6 : x0 - 6}
                  y={(y0 + y1) / 2}
                  dy="0.35em"
                  textAnchor={left ? "start" : "end"}
                  className={`text-[11px] ${n.sanctioned ? "fill-red-700 font-semibold dark:fill-red-300" : "fill-slate-700 dark:fill-slate-200"}`}
                >
                  {n.label}
                  {n.sanctioned ? " · SANCTIONED" : ""}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}
