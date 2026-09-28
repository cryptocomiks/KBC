import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, Info, ShieldCheck, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { BlockSkeleton } from "./Skeleton";
import type { ConnectorStatus, Meta } from "../types";

type Category = ConnectorStatus["licence"]["category"];

const CATEGORIES: { key: Category; title: string; text: string; tone: string }[] = [
  { key: "open", title: "Open licence", text: "Official or openly licensed data: commercial reuse allowed, with attribution where required.", tone: "bg-[#248a3d]/10 text-[#248a3d] dark:text-[#30d158]" },
  { key: "terms", title: "Publisher's terms", text: "Free access under the publisher's terms of use: confirm with the publisher before a commercial deployment.", tone: "bg-brand-500/10 text-brand-600 dark:text-[#2997ff]" },
  { key: "subscription", title: "Subscription", text: "API key: commercial use depends on the plan behind the key.", tone: "bg-violet-500/10 text-violet-700 dark:text-violet-300" },
  { key: "non_commercial", title: "Non-commercial", text: "The licence forbids commercial use without a paid licence. Switched off in commercial mode.", tone: "bg-amber-500/15 text-amber-800 dark:text-amber-300" },
  { key: "demo", title: "Demo", text: "Fictitious dataset, for demonstrations only.", tone: "bg-slate-500/10 text-slate-600 dark:text-slate-300" },
];

const KINDS: Record<string, string> = {
  registry: "Registries",
  screening: "Sanctions & PEP",
  documents: "Gazettes, courts & regulators",
  media: "Media",
  archive: "Web & domains",
  leaks: "Leaks",
  chain: "Blockchains",
};

/** Every data source with its status and reuse terms: what a compliance buyer checks first. */
export default function SourcesPage({ meta }: { meta?: Meta }) {
  const q = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const [cat, setCat] = useState<Category | "all">("all");
  const [kind, setKind] = useState<string>("all");
  const [needle, setNeedle] = useState("");

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const s of q.data ?? []) c[s.licence.category] = (c[s.licence.category] ?? 0) + 1;
    return c;
  }, [q.data]);

  if (q.error) return <div className="card p-6 text-sm text-red-600">{(q.error as Error).message}</div>;
  if (!q.data) return <BlockSkeleton rows={8} />;

  const n = needle.trim().toLowerCase();
  const rows = q.data
    .filter((s) => (cat === "all" || s.licence.category === cat) && (kind === "all" || s.kind === kind))
    .filter((s) => !n || `${s.label} ${s.licence.name} ${s.name}`.toLowerCase().includes(n))
    .sort((a, b) => Number(b.enabled) - Number(a.enabled) || a.label.localeCompare(b.label));
  const enabled = q.data.filter((s) => s.enabled).length;
  const commercial = !!meta?.commercial_mode;

  return (
    <div className="panel-enter mx-auto max-w-[1100px] space-y-8 pb-10">
      <div className="pt-6 text-center">
        <div className="eyebrow">Data sources</div>
        <h1 className="headline mt-2 text-[clamp(2rem,4.4vw,3.2rem)]">Where every answer comes from.</h1>
        <p className="subhead mx-auto mt-3 max-w-2xl text-[17px] text-slate-500">
          {q.data.length} sources, {enabled} active. Each one with its status and the terms under which its data may be reused.
        </p>
      </div>

      <div
        className={`flex items-start gap-3 rounded-2xl px-5 py-4 text-[14px] ${
          commercial ? "bg-[#248a3d]/10 text-[#1d5e2c] dark:text-[#30d158]" : "bg-amber-50 text-amber-900 dark:bg-amber-400/10 dark:text-amber-200"
        }`}
      >
        {commercial ? <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" />}
        <p>
          {commercial ? (
            <>
              <b>Commercial mode is on.</b> Sources whose licence forbids commercial use are switched off, except those listed as licensed (LICENSED_SOURCES).
            </>
          ) : (
            <>
              <b>Commercial mode is off.</b> Non-commercial sources are active: fine for evaluation, not for a paid service. Set COMMERCIAL_MODE=true in the
              deployment to switch them off, and LICENSED_SOURCES to keep the ones you hold a licence for.
            </>
          )}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            onClick={() => setCat(cat === c.key ? "all" : c.key)}
            aria-pressed={cat === c.key}
            className={`glass-tile glass-press flex flex-col items-start justify-start rounded-2xl p-4 text-left transition-shadow ${cat === c.key ? "ring-2 ring-brand-500" : ""}`}
          >
            <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${c.tone}`}>{c.title}</span>
            <div className="mt-2 text-[28px] font-semibold tracking-[-0.03em] tabular-nums">{counts[c.key] ?? 0}</div>
            <p className="mt-1 text-[12px] leading-snug text-slate-500">{c.text}</p>
          </button>
        ))}
      </div>

      <section className="card overflow-hidden">
        <header className="flex flex-wrap items-center gap-2 px-5 pt-5">
          <h2 className="mr-auto text-[19px] font-semibold tracking-[-0.02em]">
            {rows.length} source{rows.length === 1 ? "" : "s"}
          </h2>
          <input
            value={needle}
            onChange={(e) => setNeedle(e.target.value)}
            placeholder="Filter"
            aria-label="Filter sources"
            className="input h-8 w-40 text-[13px]"
          />
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Source type" className="input h-8 w-auto text-[13px]">
            <option value="all">All types</option>
            {Object.entries(KINDS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </header>
        <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
          {rows.map((s) => {
            const c = CATEGORIES.find((x) => x.key === s.licence.category)!;
            return (
              <li key={s.name} className="grid gap-2 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <div className="flex items-start gap-2.5">
                  {s.enabled ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[#248a3d] dark:text-[#30d158]" aria-label="Active" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-label="Off" />
                  )}
                  <div className="min-w-0">
                    <div className="text-[14px] font-medium">
                      {s.homepage ? (
                        <a href={s.homepage} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-brand-600">
                          {s.label}
                          <ExternalLink className="h-3 w-3 opacity-50" />
                        </a>
                      ) : (
                        s.label
                      )}
                    </div>
                    <div className="text-[12px] text-slate-500">
                      {KINDS[s.kind] ?? s.kind} · {s.message}
                    </div>
                  </div>
                </div>
                <div className="pl-6 sm:pl-0">
                  <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${c.tone}`}>{c.title}</span>
                  {s.licence.commercial_licence_held && (
                    <span className="ml-1.5 inline-block rounded-full bg-[#248a3d]/10 px-2 py-0.5 text-[11px] font-semibold text-[#248a3d] dark:text-[#30d158]">
                      Licence held
                    </span>
                  )}
                  <div className="mt-1 text-[13px]">{s.licence.name}</div>
                  {s.licence.note && <div className="text-[12px] text-slate-500">{s.licence.note}</div>}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      <p className="text-center text-[12px] text-slate-500">
        An operational summary of each publisher's terms, not legal advice: the publisher's own terms prevail.
      </p>
    </div>
  );
}
