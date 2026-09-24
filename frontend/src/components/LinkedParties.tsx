import { Building2, ChevronRight, User, Wallet } from "lucide-react";
import { useMemo, useState } from "react";
import { ENTITY_COLORS, fmtPct } from "../lib/format";
import type { Entity, Investigation, RiskLevel } from "../types";

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

const ICON = { person: User, company: Building2, wallet: Wallet, address: Building2 };
const REL: Record<string, string> = {
  officer: "Officer",
  shareholder: "Shareholder",
  beneficial_owner: "Beneficial owner",
  controls: "Controls",
  transfer: "Crypto flows",
  relative: "Family / associate",
};
const TAG_STYLE: Record<string, string> = {
  Sanctioned: "bg-[#ff3b30]/12 text-[#d70015] dark:bg-[#ff453a]/20 dark:text-[#ff6961]",
  PEP: "bg-[#af52de]/12 text-[#8944ab] dark:bg-[#bf5af2]/20 dark:text-[#da8fff]",
  "In leaks": "bg-[#ff9500]/15 text-[#c93400] dark:bg-[#ff9f0a]/20 dark:text-[#ffb340]",
  "Adverse list": "bg-[#ff9500]/15 text-[#c93400] dark:bg-[#ff9f0a]/20 dark:text-[#ffb340]",
  Offshore: "bg-[#0071e3]/10 text-[#0066cc] dark:bg-[#0a84ff]/20 dark:text-[#64b5ff]",
  Dissolved: "bg-black/[0.05] text-slate-500 dark:bg-white/[0.08]",
};
const HIT_TAG = { sanction: "Sanctioned", pep: "PEP", leak: "In leaks", adverse: "Adverse list" } as const;

export interface Party {
  entity: Entity;
  level: RiskLevel;
  points: number;
  tags: string[];
  relation: string;
  depth: number;
}

/** Every person / company of the network, ranked by what matters: risk first, then proximity. */
export function useParties(inv: Investigation): Party[] {
  return useMemo(() => {
    const tags = new Map<string, Set<string>>();
    for (const h of inv.hits) {
      if (h.triage === "namesake" || h.triage === "dismissed" || h.score < 70) continue;
      if (!tags.has(h.entity_id)) tags.set(h.entity_id, new Set());
      tags.get(h.entity_id)!.add(HIT_TAG[h.list_type]);
    }
    const s = inv.subject_id;
    return inv.entities
      .filter((e) => e.id !== s && e.type !== "address")
      .map((e) => {
        const t = new Set(tags.get(e.id) ?? []);
        if (e.is_offshore) t.add("Offshore");
        if (e.status === "dissolved") t.add("Dissolved");
        const direct = inv.relationships
          .filter((r) => (r.source_id === s && r.target_id === e.id) || (r.target_id === s && r.source_id === e.id))
          .sort((a, b) => Number(!!a.end_date) - Number(!!b.end_date))[0];
        const depth = inv.depth[e.id] ?? 9;
        let relation = `${depth} links away`;
        if (direct) {
          const role = direct.role || REL[direct.type] || direct.type;
          const pct = direct.share_pct != null ? ` · ${fmtPct(direct.share_pct)}` : "";
          relation = `${role}${pct}${direct.end_date ? " · ended" : ""}`;
        }
        return {
          entity: e,
          level: inv.risk.entity_levels[e.id] ?? "none",
          points: inv.risk.entity_points[e.id] ?? 0,
          tags: [...t],
          relation,
          depth,
        };
      })
      .sort(
        (a, b) =>
          b.points - a.points ||
          b.tags.length - a.tags.length ||
          a.depth - b.depth ||
          a.entity.name.localeCompare(b.entity.name),
      );
  }, [inv]);
}

export function PartyRow({ p, onSelect, i = 0 }: { p: Party; onSelect: (id: string) => void; i?: number }) {
  const Icon = ICON[p.entity.type];
  return (
    <li style={{ ["--i" as string]: i }}>
      <button
        onClick={() => onSelect(p.entity.id)}
        className="lift group flex w-full items-center gap-3 rounded-xl bg-black/[0.025] px-3 py-2.5 text-left hover:bg-black/[0.05] dark:bg-white/[0.04] dark:hover:bg-white/[0.08]"
      >
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-white shadow-sm"
          style={{ background: p.level === "none" ? "#8e8e93" : ENTITY_COLORS[p.level] }}
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold">{p.entity.name}</span>
          <span className="block truncate text-[11px] text-slate-500">{p.relation}</span>
          {p.tags.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1">
              {p.tags.map((t) => (
                <span key={t} className={`rounded-full px-1.5 py-px text-[10px] font-semibold ${TAG_STYLE[t] ?? TAG_STYLE.Dissolved}`}>
                  {t}
                </span>
              ))}
            </span>
          )}
        </span>
        <ChevronRight className="h-4 w-4 shrink-0 text-slate-300 transition-transform duration-200 group-hover:translate-x-0.5 dark:text-slate-600" />
      </button>
    </li>
  );
}

/** Linked people and companies, clickable: each opens its own file. */
export default function LinkedParties({ investigation: inv, onSelect }: Props) {
  const parties = useParties(inv);
  const people = parties.filter((p) => p.entity.type === "person");
  const companies = parties.filter((p) => p.entity.type !== "person");
  const [tab, setTab] = useState<"people" | "companies">(people.length ? "people" : "companies");
  const [all, setAll] = useState(false);
  const list = tab === "people" ? people : companies;
  const shown = all ? list : list.slice(0, 8);
  if (!parties.length) return null;

  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold">Linked people & companies</h2>
        <span className="text-[11px] text-slate-500">riskiest first · click to open their file</span>
        <div className="segmented ml-auto">
          {(
            [
              ["people", `People · ${people.length}`],
              ["companies", `Companies · ${companies.length}`],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              onClick={() => {
                setTab(k);
                setAll(false);
              }}
              className={`rounded-[8px] px-2.5 py-1 text-xs font-medium transition-all duration-200 ${
                tab === k ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {list.length === 0 ? (
        <p className="text-sm text-slate-500">None found in the sources queried.</p>
      ) : (
        <ul key={tab} className="stagger grid gap-2 sm:grid-cols-2">
          {shown.map((p, i) => (
            <PartyRow key={p.entity.id} p={p} onSelect={onSelect} i={i} />
          ))}
        </ul>
      )}
      {list.length > 8 && (
        <button className="btn-ghost mt-3 text-xs" onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${list.length}`}
        </button>
      )}
    </section>
  );
}
