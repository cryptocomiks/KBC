import { useQuery } from "@tanstack/react-query";
import { BellRing, Download, ExternalLink, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { downloadCsv } from "../lib/csv";
import { BarList } from "./viz";
import { BlockSkeleton } from "./Skeleton";

const PERIODS = [
  [30, "30 days"],
  [90, "90 days"],
  [365, "12 months"],
] as const;

const fmt = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

/** Who was added to the official sanctions lists lately: what a sanctions officer re-screens against. */
export default function DesignationsPage() {
  const [days, setDays] = useState<number>(90);
  const [list, setList] = useState("all");
  const [needle, setNeedle] = useState("");
  const q = useQuery({
    queryKey: ["designations", days],
    queryFn: () => api.designations(days),
    // lists still downloading on the server: ask again until they are in
    refetchInterval: (query) => (query.state.data?.loading.length ? 5000 : false),
  });

  const items = useMemo(() => {
    const n = needle.trim().toLowerCase();
    return (q.data?.items ?? []).filter((x) => (list === "all" || x.list === list) && (!n || `${x.name} ${x.program ?? ""}`.toLowerCase().includes(n)));
  }, [q.data, list, needle]);

  const byDate = useMemo(() => {
    const m = new Map<string, typeof items>();
    for (const x of items) m.set(x.listed_on, [...(m.get(x.listed_on) ?? []), x]);
    return [...m.entries()];
  }, [items]);

  if (q.error) return <div className="card p-6 text-sm text-red-600 dark:text-red-400">{(q.error as Error).message}</div>;

  const d = q.data;
  const lists = Object.entries(d?.by_list ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="panel-enter mx-auto max-w-[1100px] space-y-8 pb-10">
      <div className="pt-6 text-center">
        <div className="eyebrow">New designations</div>
        <h1 className="headline mt-2 text-[clamp(2rem,4.4vw,3.2rem)]">Who was just added to the lists.</h1>
        <p className="subhead mx-auto mt-3 max-w-2xl text-[17px] text-slate-500">
          The latest entries on the official sanctions lists of the UN, the EU, the United Kingdom and the US export lists, read from the authorities. Re-screen your
          clients when a list moves.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-3">
        <div className="segmented" role="group" aria-label="Period">
          {PERIODS.map(([n, label]) => (
            <button
              key={n}
              aria-pressed={days === n}
              onClick={() => setDays(n)}
              className={`rounded-[8px] px-3 py-1 text-xs font-medium ${days === n ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}
            >
              {label}
            </button>
          ))}
        </div>
        <select className="input py-1 text-xs" aria-label="List" value={list} onChange={(e) => setList(e.target.value)}>
          <option value="all">All lists</option>
          {lists.map(([l, n]) => (
            <option key={l} value={l}>
              {l} ({n})
            </option>
          ))}
        </select>
        <input className="input w-56 py-1 text-xs" placeholder="Filter by name or programme" aria-label="Filter by name or programme" value={needle} onChange={(e) => setNeedle(e.target.value)} />
        <a className="btn-primary py-1.5 text-xs" href="#/screen">
          Screen my client list
        </a>
      </div>

      {!d ? (
        <BlockSkeleton rows={8} />
      ) : (
        <>
          {d.loading.length > 0 && (
            <p className="card flex items-center gap-2 p-4 text-sm text-amber-700 dark:text-amber-300" aria-live="polite">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Downloading on the server: {d.loading.join("; ")}. The page completes itself in a minute.
            </p>
          )}
          {lists.length > 0 && (
            <section className="card p-5" aria-labelledby="per-list">
              <h2 id="per-list" className="mb-3 text-sm font-semibold">
                {d.total} new entr{d.total === 1 ? "y" : "ies"} since {fmt(d.since)}
              </h2>
              <BarList rows={lists.map(([l, n]) => ({ key: l, label: l, value: n }))} />
            </section>
          )}
          <section className="card overflow-hidden" aria-labelledby="entries">
            <div className="flex items-center gap-2 border-b border-black/[0.06] px-5 py-3 dark:border-white/[0.08]">
              <BellRing className="h-4 w-4 text-brand-600" aria-hidden />
              <h2 id="entries" className="text-sm font-semibold">
                Entries{items.length !== d.items.length && ` (${items.length} shown)`}
              </h2>
              <button
                className="btn-outline ml-auto py-1 text-xs"
                disabled={!items.length}
                onClick={() =>
                  downloadCsv(
                    `new-designations-${d.until}.csv`,
                    [
                      { key: "listed_on", label: "Listed on" },
                      { key: "name", label: "Name" },
                      { key: "type", label: "Type" },
                      { key: "list", label: "List" },
                      { key: "program", label: "Programme" },
                      { key: "nationalities", label: "Nationalities" },
                      { key: "birth_date", label: "Birth date" },
                      { key: "reference", label: "Reference" },
                      { key: "source", label: "Source" },
                    ],
                    items.map((x) => ({ ...x })),
                  )
                }
              >
                <Download className="h-3.5 w-3.5" /> Export CSV
              </button>
            </div>
            {byDate.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-500">No new entry in this period{list !== "all" || needle ? " with these filters" : ""}.</p>
            ) : (
              <div className="divide-y divide-black/[0.05] dark:divide-white/[0.06]">
                {byDate.map(([date, rows]) => (
                  <div key={date}>
                    <h3 className="bg-black/[0.03] px-5 py-1.5 text-[12px] font-semibold text-slate-600 dark:bg-white/[0.04] dark:text-slate-300">
                      {fmt(date)} · {rows.length}
                    </h3>
                    <ul className="divide-y divide-black/[0.04] dark:divide-white/[0.05]">
                      {rows.map((x) => (
                        <li key={`${x.list}-${x.reference}-${x.name}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-5 py-2.5">
                          <div className="min-w-0 flex-1">
                            <div className="text-[14px] font-medium">{x.name}</div>
                            <div className="text-[12px] text-slate-500">
                              {[x.type, x.nationalities?.join(", "), x.birth_date && `born ${x.birth_date}`, x.program].filter(Boolean).join(" · ")}
                            </div>
                          </div>
                          <span className="text-[12px] text-slate-500">{x.list}</span>
                          <a
                            className="text-[12px] whitespace-nowrap text-brand-600 underline underline-offset-2"
                            href={`#/search?${new URLSearchParams({ q: x.name, type: x.type === "person" ? "person" : "company", depth: "2", n: "60" })}`}
                          >
                            Investigate
                          </a>
                          {x.source && (
                            <a className="text-slate-500 hover:text-brand-600" href={x.source} target="_blank" rel="noreferrer" aria-label={`Official source for ${x.name}`}>
                              <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </section>
          <p className="text-center text-[11.5px] text-slate-500">
            OFAC SDN and the Swiss list give no designation date in their files: screen against them with the list screening page. Dates are those published by each
            authority.
          </p>
        </>
      )}
    </div>
  );
}
