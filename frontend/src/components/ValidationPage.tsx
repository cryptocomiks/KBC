import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, Info, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { BlockSkeleton } from "./Skeleton";
import { CountUp, Meter } from "./viz";

/** How well the match engine separates the same person / company from namesakes, on a
 *  labelled test set: the evidence a compliance auditor asks for. */
export default function ValidationPage() {
  const q = useQuery({ queryKey: ["validation"], queryFn: api.validation, staleTime: Infinity });
  const [showAll, setShowAll] = useState(false);
  if (q.error) return <div className="card p-6 text-sm text-red-600 dark:text-red-400">{(q.error as Error).message}</div>;
  if (!q.data) return <BlockSkeleton rows={6} />;
  const r = q.data;
  const o = r.overall;
  return (
    <div className="panel-enter mx-auto max-w-[1100px] space-y-8 pb-10">
      <div className="pt-6 text-center">
        <div className="eyebrow">Matching validation</div>
        <h1 className="headline mt-2 text-[clamp(2rem,4.4vw,3.2rem)]">Does it catch the right people?</h1>
        <p className="subhead mx-auto mt-3 max-w-2xl text-[17px] text-slate-500">
          {o.pairs} labelled pairs, transliterations, legal forms, typos, namesakes, generic company names, run through the
          production engine and its alert triage.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Detection rate" value={o.detection_rate} sub={`${o.detected} of ${o.match_pairs} same-entity pairs raise an alert`} good />
        <Stat label="False-positive rate" value={o.false_positive_rate} sub={`${o.false_positives} of ${o.no_match_pairs} different-entity pairs raise an alert`} />
        <Stat label="Strong detection" value={o.strong_detection_rate} sub={`score ≥ ${r.thresholds.strong_match}: flagged as a likely match`} good />
      </div>

      <div className="flex items-start gap-3 rounded-2xl bg-amber-50 px-5 py-4 text-[14px] text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p>{r.limits}</p>
      </div>

      <section className="card overflow-hidden">
        <header className="px-5 pt-5">
          <h2 className="text-[19px] font-semibold tracking-[-0.02em]">By category</h2>
          <p className="text-[13px] text-slate-500">
            Alert threshold {r.thresholds.possible_match} · test set v{r.testset_version} · engine {r.engine_version} · generated{" "}
            {new Date(r.generated_at).toLocaleString()}
          </p>
        </header>
        <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
          {r.categories.map((c) => {
            const isMatch = c.expected === "match";
            const rate = (isMatch ? c.detection_rate : c.false_positive_rate) ?? 0;
            const ok = isMatch ? rate >= 95 : rate <= 5;
            return (
              <li key={c.category} className="grid items-center gap-3 px-5 py-3 sm:grid-cols-[1fr_220px_110px]">
                <div>
                  <div className="text-[14px] font-medium">{c.category}</div>
                  <div className="text-[12px] text-slate-500">
                    {c.pairs} pairs · {isMatch ? "should raise an alert" : "should stay silent"}
                  </div>
                </div>
                <Meter value={isMatch ? rate : 100 - rate} max={100} tone={ok ? "good" : "critical"} height={6} label={c.category} />
                <div className={`text-right text-[14px] font-semibold tabular-nums ${ok ? "text-[#1b7331] dark:text-[#30d158]" : "text-[#d70015] dark:text-[#ff453a]"}`}>
                  {isMatch ? `${rate} % caught` : `${rate} % alerts`}
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {r.errors.length > 0 && (
        <section className="card p-5">
          <h2 className="text-[19px] font-semibold tracking-[-0.02em]">Errors ({r.errors.length})</h2>
          <ul className="mt-3 space-y-2">
            {r.errors.map((e, i) => (
              <li key={i} className="text-[13px]">
                <b>{e.expected === "match" ? "Missed" : "False alert"}</b>: {e.query} ↔ {e.candidate}: {e.score} ({e.triage}):{" "}
                <span className="text-slate-500">{e.explanation.join("; ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card overflow-hidden">
        <button className="flex w-full items-center justify-between px-5 py-4 text-left" onClick={() => setShowAll((s) => !s)} aria-expanded={showAll}>
          <span className="text-[17px] font-semibold tracking-[-0.02em]">All {r.pairs.length} pairs, with the engine's explanation</span>
          <ChevronDown className={`h-5 w-5 text-slate-400 transition-transform ${showAll ? "rotate-180" : ""}`} />
        </button>
        {showAll && (
          <div className="overflow-x-auto border-t border-slate-200/70 dark:border-white/[0.06]">
            <table className="w-full text-[13px]">
              <thead className="text-left text-[12px] text-slate-500">
                <tr>
                  <th className="px-5 py-2 font-medium">Our side</th>
                  <th className="px-3 py-2 font-medium">List side</th>
                  <th className="px-3 py-2 font-medium">Expected</th>
                  <th className="px-3 py-2 text-right font-medium">Score</th>
                  <th className="px-3 py-2 font-medium">Triage</th>
                  <th className="px-5 py-2 font-medium">Why</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200/70 dark:divide-white/[0.06]">
                {r.pairs.map((p, i) => (
                  <tr key={i}>
                    <td className="px-5 py-2">{p.query}</td>
                    <td className="px-3 py-2">{p.candidate}</td>
                    <td className="px-3 py-2 whitespace-nowrap">{p.expected === "match" ? "same" : "different"}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{p.score}</td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1">
                        {p.correct ? <CheckCircle2 className="h-3.5 w-3.5 text-[#34c759]" /> : <XCircle className="h-3.5 w-3.5 text-[#ff3b30]" />}
                        {p.flagged ? "alert" : p.triage === "namesake" ? "set aside" : "silent"}
                      </span>
                    </td>
                    <td className="px-5 py-2 text-slate-500">{p.explanation.join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value, sub, good }: { label: string; value: number | null; sub: string; good?: boolean }) {
  const v = value ?? 0;
  return (
    <div className="card p-6 text-center">
      <div className="text-[13px] font-medium text-slate-500">{label}</div>
      <div className={`headline mt-2 text-[52px] tabular-nums ${good ? "" : ""}`}>
        <CountUp value={Math.round(v)} />
        <span className="text-[28px] text-slate-400"> %</span>
      </div>
      <div className="mt-1 text-[13px] text-slate-500">{sub}</div>
    </div>
  );
}
