import { Building2, Search, User, Users } from "lucide-react";
import { type FormEvent, useState } from "react";

export interface SearchParams {
  q: string;
  type: "any" | "person" | "company";
  depth: number;
  maxNodes: number;
}

const LIVE_EXAMPLES = [
  { q: "TotalEnergies", type: "company" as const, hint: "FR registry + leaks screening" },
  { q: "Danone", type: "company" as const, hint: "officers from data.gouv.fr" },
];

const EXAMPLES = [
  { q: "Mohamed Qadrany", type: "person" as const, hint: "homonyms + transliteration" },
  { q: "Meridian Capital Holdings", type: "company" as const, hint: "LU holding, circular ownership" },
  { q: "Henri Castelnau", type: "person" as const, hint: "professional director" },
  { q: "Rouslan Terekhov", type: "person" as const, hint: "sanctions match" },
  { q: "TNRthgateMaritimeDEMwa111111111111", type: "any" as const, hint: "TRON wallet, sanctioned exposure" },
];

interface Props {
  initial: SearchParams;
  demo: boolean;
  live?: boolean;
  onSearch: (p: SearchParams) => void;
  compact?: boolean;
}

export default function SearchPanel({ initial, demo, live, onSearch, compact }: Props) {
  const [p, setP] = useState<SearchParams>(initial);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (p.q.trim().length >= 2) onSearch({ ...p, q: p.q.trim() });
  };
  const typeBtn = (t: SearchParams["type"], label: string, Icon: typeof User) => (
    <button
      type="button"
      onClick={() => setP({ ...p, type: t })}
      className={`inline-flex items-center gap-1.5 rounded-[8px] px-2.5 py-1 transition-all duration-200.5 text-xs font-medium ${
        p.type === t ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
      }`}
    >
      <Icon className="h-3.5 w-3.5" /> {label}
    </button>
  );

  return (
    <form onSubmit={submit} className={compact ? "" : "card p-5"}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[280px] flex-1">
          <label className="label mb-1 block" htmlFor="q">
            Person, company or crypto address
          </label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              id="q"
              className="input w-full pl-9 text-base"
              placeholder="Name, company… or a BTC / ETH / TRON address"
              value={p.q}
              onChange={(e) => setP({ ...p, q: e.target.value })}
              autoFocus={!compact}
            />
          </div>
        </div>
        <div>
          <span className="label mb-1 block">Type</span>
          <div className="segmented">
            {typeBtn("any", "Any", Users)}
            {typeBtn("person", "Person", User)}
            {typeBtn("company", "Company", Building2)}
          </div>
        </div>
        <div>
          <label className="label mb-1 block" htmlFor="depth">
            Depth
          </label>
          <select id="depth" className="input" value={p.depth} onChange={(e) => setP({ ...p, depth: Number(e.target.value) })}>
            <option value={1}>1 level</option>
            <option value={2}>2 levels</option>
            <option value={3}>3 levels</option>
          </select>
        </div>
        <div>
          <label className="label mb-1 block" htmlFor="nodes">
            Max nodes
          </label>
          <input
            id="nodes"
            type="number"
            min={5}
            max={250}
            className="input w-24"
            value={p.maxNodes}
            onChange={(e) => setP({ ...p, maxNodes: Math.max(5, Math.min(250, Number(e.target.value) || 60)) })}
          />
        </div>
        <button className="btn-primary h-[38px] px-5" type="submit">
          <Search className="h-4 w-4" /> Search
        </button>
      </div>
      {!compact &&
        ([
          ...(demo ? [["Fictitious demo scenario:", EXAMPLES] as const] : []),
          ...(live ? [["Real public data:", LIVE_EXAMPLES] as const] : []),
        ] as const).map(([title, list]) => (
        <div key={title} className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-500">{title}</span>
          {list.map((ex) => (
            <button
              key={ex.q}
              type="button"
              className="rounded-full bg-black/[0.05] px-3 py-1 transition hover:bg-brand-600/10 hover:text-brand-600 active:scale-[0.97] dark:bg-white/[0.08] dark:hover:text-brand-300"
              onClick={() => {
                const next = { ...p, q: ex.q, type: ex.type };
                setP(next);
                onSearch(next);
              }}
              title={ex.hint}
            >
              {ex.q} <span className="text-slate-400">· {ex.hint}</span>
            </button>
          ))}
        </div>
        ))}
    </form>
  );
}
