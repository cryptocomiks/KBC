import { Building2, User, Wallet } from "lucide-react";
import { useMemo, useState } from "react";
import { fmtPct } from "../lib/format";
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
  Sanctioned: "bg-[#d92d20]/10 text-[#b42318] dark:bg-[#f04438]/20 dark:text-[#fda29b]",
  PEP: "bg-[#6941c6]/12 text-[#5925dc] dark:bg-[#9b8afb]/20 dark:text-[#bdb4fe]",
  "In leaks": "bg-[#dc6803]/15 text-[#b54708] dark:bg-[#f79009]/20 dark:text-[#fec84b]",
  "Adverse list": "bg-[#dc6803]/15 text-[#b54708] dark:bg-[#f79009]/20 dark:text-[#fec84b]",
  Offshore: "bg-[#1d4a7a]/10 text-[#1d4a7a] dark:bg-[#5b8bc4]/20 dark:text-[#9bb9e0]",
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

const LEVEL_TEXT: Record<string, string> = {
  critical: "text-[#b42318] dark:text-[#fda29b]",
  high: "text-[#b54708] dark:text-[#fec84b]",
  medium: "text-[#a15c07] dark:text-[#fde272]",
  low: "text-slate-600 dark:text-slate-300",
  none: "text-slate-400",
};

export function PartyRow({ p, onSelect, i = 0 }: { p: Party; onSelect: (id: string) => void; i?: number }) {
  const Icon = ICON[p.entity.type];
  return (
    <tr
      style={{ ["--i" as string]: i }}
      onClick={() => onSelect(p.entity.id)}
      className="group cursor-pointer border-b border-slate-100 last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
    >
      <td className="py-2 pr-3 pl-4">
        <span className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          <span className="font-medium text-slate-900 group-hover:text-brand-700 group-hover:underline dark:text-slate-100">{p.entity.name}</span>
        </span>
      </td>
      <td className="py-2 pr-3 text-slate-600 dark:text-slate-400">{p.relation}</td>
      <td className="py-2 pr-3">
        <span className="flex flex-wrap gap-1">
          {p.tags.map((t) => (
            <span key={t} className={`rounded px-1.5 py-px text-[10px] font-semibold ${TAG_STYLE[t] ?? TAG_STYLE.Dissolved}`}>
              {t}
            </span>
          ))}
        </span>
      </td>
      <td className={`py-2 pr-4 text-right text-[11px] font-semibold uppercase ${LEVEL_TEXT[p.level] ?? LEVEL_TEXT.none}`}>
        {p.level === "none" ? "—" : p.level}
      </td>
    </tr>
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
  const shown = all ? list : list.slice(0, 10);
  if (!parties.length) return null;

  return (
    <section className="card p-5">
      <div className="tag mb-2">Network</div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold">Linked people & companies</h2>
        <span className="text-[11px] text-slate-500">highest risk first · click a row to open the file</span>
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
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="border-y border-slate-200 bg-slate-50 text-left text-[11px] font-semibold tracking-wider text-slate-500 uppercase dark:border-slate-800 dark:bg-slate-800/40">
                <th className="py-1.5 pr-3 pl-4">Name</th>
                <th className="py-1.5 pr-3">Relationship to the subject</th>
                <th className="py-1.5 pr-3">Flags</th>
                <th className="py-1.5 pr-4 text-right">Risk</th>
              </tr>
            </thead>
            <tbody key={tab} className="stagger">
              {shown.map((p, i) => (
                <PartyRow key={p.entity.id} p={p} onSelect={onSelect} i={i} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {list.length > 10 && (
        <button className="btn-ghost mt-3 text-xs" onClick={() => setAll((a) => !a)}>
          {all ? "Show fewer" : `Show all ${list.length}`}
        </button>
      )}
    </section>
  );
}
