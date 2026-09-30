import { Download, FileUp, ListChecks, Loader2, Play, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ScreenResult, ScreenRow } from "../types";
import { downloadCsv } from "../lib/csv";
import { Meter, Tile } from "./viz";

const MAX = 500;
const CHUNK = 60;
const SAMPLE = `name;country;reference
Ruslan Terekhov;CY;C-1001
Solenne Holdings Ltd;CY;C-1002
Huawei Technologies Co., Ltd.;CN;S-2001
JSC Gruppa Kremniy El;RU;S-2002
Gulf Star Trading FZE;AE;S-2003
Anna Muster;CH;C-1003
Nestle SA;CH;S-2004`;

/** Minimal CSV reader: quoted fields, ; , or tab separators, optional header row. */
function parseList(text: string): ScreenRow[] {
  const lines = text.replace(/^﻿/, "").split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  const sep = [";", "\t", ","].find((s) => lines[0].includes(s)) ?? ";";
  const split = (line: string) => {
    const out: string[] = [];
    let cur = "";
    let quoted = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (quoted && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else quoted = !quoted;
      } else if (ch === sep && !quoted) {
        out.push(cur.trim());
        cur = "";
      } else cur += ch;
    }
    out.push(cur.trim());
    return out;
  };
  let rows = lines.map(split);
  let cols = { name: 0, country: 1, reference: 2, type: -1 };
  const head = rows[0].map((h) => h.toLowerCase());
  if (head.some((h) => /^(name|nom|client|counterparty|contrepartie|raison sociale)$/.test(h))) {
    const find = (re: RegExp) => head.findIndex((h) => re.test(h));
    cols = {
      name: find(/^(name|nom|client|counterparty|contrepartie|raison sociale)$/),
      country: find(/^(country|pays|land|iso)$/),
      reference: find(/^(ref|reference|référence|id|client id|numéro)$/),
      type: find(/^(type|kind|nature)$/),
    };
    rows = rows.slice(1);
  }
  return rows
    .map((r) => {
      const t = cols.type >= 0 ? (r[cols.type] ?? "").toLowerCase() : "";
      return {
        name: r[cols.name] ?? "",
        country: cols.country >= 0 && /^[a-z]{2}$/i.test(r[cols.country] ?? "") ? r[cols.country].toUpperCase() : undefined,
        reference: cols.reference >= 0 ? r[cols.reference] || undefined : undefined,
        type: t.startsWith("p") || t.startsWith("ind") ? "person" : t.startsWith("c") || t.startsWith("ent") || t.startsWith("soc") ? "company" : undefined,
      } as ScreenRow;
    })
    .filter((r) => r.name.trim());
}

const STATUS = {
  strong: { label: "Strong match", Icon: ShieldAlert, cls: "bg-[#d70015]/10 text-[#b42318] dark:text-[#ff453a]" },
  possible: { label: "Possible match", Icon: ShieldQuestion, cls: "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]" },
  incomplete: { label: "Not fully screened", Icon: Loader2, cls: "bg-black/[0.05] text-slate-600 dark:bg-white/[0.08] dark:text-slate-300" },
  clear: { label: "No match", Icon: ShieldCheck, cls: "bg-[#248a3d]/10 text-[#1b7331] dark:text-[#30d158]" },
} as const;

/** Screen a customer list or payment counterparties against every list at once. Nothing is stored. */
export default function ScreenListPage() {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<"auto" | "person" | "company">("auto");
  const [results, setResults] = useState<ScreenResult[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "matches" | "clear">("all");
  const fileRef = useRef<HTMLInputElement>(null);

  const rows = useMemo(() => parseList(text), [text]);
  const running = progress !== null && progress.done < progress.total;

  /** Screen `list` (all rows, or only the rows not fully screened) and merge into the results. */
  const screenRows = async (list: ScreenRow[], positions: number[], base: ScreenResult[]) => {
    setError(null);
    setProgress({ done: 0, total: list.length });
    const out = [...base];
    const seen = new Set<string>();
    try {
      for (let i = 0; i < list.length; i += CHUNK) {
        const res = await api.screen(list.slice(i, i + CHUNK));
        res.results.forEach((r, k) => (out[positions[i + k]] = r));
        res.notes.forEach((n) => seen.add(n));
        setResults([...out]);
        setProgress({ done: Math.min(i + CHUNK, list.length), total: list.length });
      }
    } catch (e) {
      setError((e as Error).message);
      setProgress(null);
    }
    setNotes([...seen]);
  };
  const [sent, setSent] = useState<ScreenRow[]>([]);
  const run = () => {
    const list = rows.slice(0, MAX).map((r) => ({ ...r, type: r.type ?? kind }));
    setSent(list);
    setResults([]);
    setNotes([]);
    return screenRows(list, list.map((_, i) => i), []);
  };
  const retry = () => {
    const positions = results.map((r, i) => (r.status === "incomplete" ? i : -1)).filter((i) => i >= 0);
    return screenRows(positions.map((i) => sent[i]), positions, results);
  };

  const counts = { strong: 0, possible: 0, incomplete: 0, clear: 0 };
  results.forEach((r) => counts[r.status]++);
  const order = { strong: 0, possible: 1, incomplete: 2, clear: 3 };
  const shown = results
    .filter((r) => filter === "all" || (filter === "clear" ? r.status === "clear" : r.status === "strong" || r.status === "possible"))
    .sort((a, b) => order[a.status] - order[b.status] || (b.matches[0]?.score ?? 0) - (a.matches[0]?.score ?? 0));

  const exportCsv = () =>
    downloadCsv(
      `screening-${new Date().toISOString().slice(0, 10)}.csv`,
      [
        { key: "reference", label: "Reference" },
        { key: "name", label: "Name" },
        { key: "type", label: "Type" },
        { key: "country", label: "Country" },
        { key: "status", label: "Result" },
        { key: "list", label: "Best match: list" },
        { key: "listed_as", label: "Listed as" },
        { key: "score", label: "Score" },
        { key: "program", label: "Programme" },
        { key: "others", label: "Other matches" },
        { key: "source", label: "Source" },
      ],
      results.map((r) => ({
        ...r,
        status: STATUS[r.status].label,
        list: r.matches[0]?.list,
        listed_as: r.matches[0]?.listed_as,
        score: r.matches[0]?.score,
        program: r.matches[0]?.program,
        others: r.matches.slice(1).map((m) => `${m.list} (${m.score})`),
        source: r.matches[0]?.source,
      })),
    );

  return (
    <div className="panel-enter mx-auto max-w-[1100px] space-y-8 pb-10">
      <div className="pt-6 text-center">
        <div className="eyebrow">List screening</div>
        <h1 className="headline mt-2 text-[clamp(2rem,4.4vw,3.2rem)]">Screen a whole list at once.</h1>
        <p className="subhead mx-auto mt-3 max-w-2xl text-[17px] text-slate-500">
          A customer portfolio, the counterparties of a payment run, a list of directors: up to {MAX} names against every sanctions, PEP and watchlist source. Nothing
          is stored.
        </p>
      </div>

      <section className="card space-y-3 p-5" aria-labelledby="list-input">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="list-input" className="text-sm font-semibold">
            Names
          </h2>
          <span className="text-[12px] text-slate-500">one per line; optional columns: country (ISO code) and your reference, separated by ; or a comma</span>
          <span className="ml-auto flex flex-wrap gap-2">
            <button className="btn-ghost py-1 text-xs" onClick={() => setText(SAMPLE)}>
              Try with a sample list
            </button>
            <button className="btn-outline py-1 text-xs" onClick={() => fileRef.current?.click()}>
              <FileUp className="h-3.5 w-3.5" /> Open a CSV file
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.txt,.tsv"
              className="hidden"
              aria-label="CSV file with the names"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setText(await f.text());
                e.target.value = "";
              }}
            />
          </span>
        </div>
        <textarea
          className="input h-40 w-full font-mono text-[12.5px]"
          placeholder={"Ruslan Terekhov;CY;C-1001\nGulf Star Trading FZE;AE\nAnna Muster"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Names to screen"
        />
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[12.5px] text-slate-500">
            {rows.length} name{rows.length === 1 ? "" : "s"}
            {rows.length > MAX && ` (the first ${MAX} will be screened)`}
          </span>
          <div className="segmented" role="group" aria-label="Kind of names">
            {(["auto", "person", "company"] as const).map((k) => (
              <button
                key={k}
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={`rounded-[8px] px-2.5 py-1 text-xs font-medium ${kind === k ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}
              >
                {k === "auto" ? "Detect" : k === "person" ? "People" : "Companies"}
              </button>
            ))}
          </div>
          <button className="btn-primary ml-auto py-1.5 text-sm" onClick={run} disabled={!rows.length || running}>
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Screen {Math.min(rows.length, MAX) || ""} name
            {Math.min(rows.length, MAX) === 1 ? "" : "s"}
          </button>
        </div>
        {progress && (
          <div aria-live="polite">
            <Meter value={progress.done} max={Math.max(1, progress.total)} label="Screening progress" tone={running ? "accent" : "good"} />
            <p className="mt-1 text-[12px] text-slate-500">
              {progress.done} of {progress.total} screened{running ? "…" : "."} The first run on a server that has just started can take up to half a minute while the
              lists load.
            </p>
          </div>
        )}
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      </section>

      {results.length > 0 && (
        <>
          {counts.incomplete > 0 && !running && (
            <div className="card flex flex-wrap items-center gap-3 p-4 text-sm" role="status">
              <Loader2 className="h-4 w-4 text-amber-700 dark:text-amber-300" aria-hidden />
              <span className="min-w-0 flex-1">
                <b className="font-semibold">{counts.incomplete} name{counts.incomplete === 1 ? " was" : "s were"} not fully screened:</b> some lists were still downloading
                on the server. They take about a minute on a server that has just started.
              </span>
              <button className="btn-primary py-1.5 text-xs" onClick={retry}>
                Screen them again
              </button>
            </div>
          )}
          <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Screened" value={results.length} tone="accent" />
            <Tile label="Strong matches (sanctions)" value={counts.strong} tone={counts.strong ? "critical" : "good"} />
            <Tile label="Possible matches" value={counts.possible} tone={counts.possible ? "warning" : "good"} />
            <Tile label="No match" value={counts.clear} sub={counts.incomplete ? `${counts.incomplete} not fully screened` : undefined} tone="good" />
          </section>

          <section className="card overflow-hidden" aria-labelledby="list-results">
            <div className="flex flex-wrap items-center gap-2 border-b border-black/[0.06] px-5 py-3 dark:border-white/[0.08]">
              <ListChecks className="h-4 w-4 text-brand-600" aria-hidden />
              <h2 id="list-results" className="text-sm font-semibold">
                Results
              </h2>
              <div className="segmented ml-auto" role="group" aria-label="Show">
                {(
                  [
                    ["all", `All · ${results.length}`],
                    ["matches", `Matches · ${counts.strong + counts.possible}`],
                    ["clear", `No match · ${counts.clear}`],
                  ] as const
                ).map(([k, l]) => (
                  <button
                    key={k}
                    aria-pressed={filter === k}
                    onClick={() => setFilter(k)}
                    className={`rounded-[8px] px-2.5 py-1 text-xs font-medium ${filter === k ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}
                  >
                    {l}
                  </button>
                ))}
              </div>
              <button className="btn-outline py-1 text-xs" onClick={exportCsv}>
                <Download className="h-3.5 w-3.5" /> Export CSV
              </button>
            </div>
            <div className="relative overflow-x-auto" tabIndex={0} role="region" aria-label="Screening results">
              <table className="w-full text-left text-[13px]">
                <thead className="text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-5 py-2 font-medium">Result</th>
                    <th className="px-3 py-2 font-medium">Name</th>
                    <th className="px-3 py-2 font-medium">Best match</th>
                    <th className="px-3 py-2 text-right font-medium">Score</th>
                    <th className="px-5 py-2 font-medium">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-black/[0.05] dark:divide-white/[0.06]">
                  {shown.map((r, i) => {
                    const s = STATUS[r.status];
                    const m = r.matches[0];
                    return (
                      <tr key={`${r.name}-${i}`} className="align-top">
                        <td className="px-5 py-2.5">
                          <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${s.cls}`}>
                            <s.Icon className="h-3 w-3" aria-hidden /> {s.label}
                          </span>
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="font-medium">{r.name}</div>
                          <div className="text-[11.5px] text-slate-500">
                            {r.type}
                            {r.country && ` · ${r.country}`}
                            {r.reference && ` · ${r.reference}`}
                          </div>
                        </td>
                        <td className="px-3 py-2.5">
                          {m ? (
                            <>
                              <div>
                                {m.listed_as} <span className="text-slate-500">on</span> {m.list}
                              </div>
                              <div className="text-[11.5px] text-slate-500">
                                {[m.program, m.why?.[0], r.matches.length > 1 && `+${r.matches.length - 1} other list${r.matches.length > 2 ? "s" : ""}`]
                                  .filter(Boolean)
                                  .join(" · ")}
                              </div>
                            </>
                          ) : (
                            <span className="text-slate-500">none</span>
                          )}
                        </td>
                        <td className="px-3 py-2.5 text-right font-semibold tabular-nums">{m ? Math.round(m.score) : ""}</td>
                        <td className="px-5 py-2.5 text-right">
                          <a className="text-[12px] whitespace-nowrap text-brand-600 underline underline-offset-2" href={`#/search?${new URLSearchParams({ q: r.name, type: r.type, depth: "2", n: "60" })}`}>
                            Investigate
                          </a>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
          {notes.length > 0 && (
            <ul className="space-y-1 text-[12px] text-amber-700 dark:text-amber-300">
              {notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <p className="text-center text-[11.5px] text-slate-500">
            Possible matches rest on the name only: confirm or rule them out with the date of birth, nationality or registration number before any decision.
          </p>
        </>
      )}
    </div>
  );
}
