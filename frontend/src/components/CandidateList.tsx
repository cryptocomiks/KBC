import { ArrowRight, Building2, Info, User } from "lucide-react";
import { countryName, flag, matchScoreClass } from "../lib/format";
import type { SearchCandidate, SearchResponse } from "../types";

interface Props {
  data: SearchResponse;
  onPick: (c: SearchCandidate) => void;
}

export default function CandidateList({ data, onPick }: Props) {
  const persons = data.candidates.filter((c) => c.entity.type === "person").length;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-lg font-semibold">
          {data.candidates.length} candidate{data.candidates.length === 1 ? "" : "s"} for “{data.query}”
        </h2>
        <span className="text-xs text-slate-500">searched in: {data.sources.join(" · ")}</span>
      </div>
      {persons > 1 && (
        <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-900/50 dark:bg-blue-950/40 dark:text-blue-200">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            <strong>Possible homonyms.</strong> Several people match this name (spelling and transliteration variants included).
            Compare date of birth, nationality and linked companies, then select the right person. Records already
            recognised as the same person across sources are grouped.
          </p>
        </div>
      )}
      {data.warnings.map((w) => (
        <div key={w} className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
          {w}
        </div>
      ))}
      {data.candidates.length === 0 && <div className="card p-6 text-center text-sm text-slate-500">No match found in the enabled sources.</div>}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {data.candidates.map((c) => {
          const e = c.entity;
          return (
            <div key={e.id} className="card flex flex-col p-4">
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-slate-100 p-2 dark:bg-slate-800">
                  {e.type === "person" ? <User className="h-5 w-5" /> : <Building2 className="h-5 w-5" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold leading-tight">{e.name}</div>
                  {e.aliases.length > 0 && <div className="truncate text-xs text-slate-500">aka {e.aliases.join(", ")}</div>}
                </div>
                <span
                  className={`rounded-md px-2 py-0.5 text-xs font-semibold ${matchScoreClass(c.score)}`}
                  title={c.explanation.join("\n")}
                >
                  {c.score.toFixed(0)}% match
                </span>
              </div>
              <dl className="mt-3 grid grid-cols-[110px_1fr] gap-y-1 text-xs">
                {e.type === "person" ? (
                  <>
                    <dt className="text-slate-500">Date of birth</dt>
                    <dd className="font-medium">{e.birth_date ?? "—"}</dd>
                    <dt className="text-slate-500">Nationality</dt>
                    <dd>{e.nationalities.map((n) => `${flag(n)} ${countryName(n)}`).join(", ") || "—"}</dd>
                  </>
                ) : (
                  <>
                    <dt className="text-slate-500">Jurisdiction</dt>
                    <dd>
                      {flag(e.jurisdiction)} {countryName(e.jurisdiction)}
                    </dd>
                    <dt className="text-slate-500">Registration</dt>
                    <dd className="font-mono">{e.registration_number ?? "—"}</dd>
                    <dt className="text-slate-500">Status</dt>
                    <dd>{e.status ?? "—"}</dd>
                  </>
                )}
                <dt className="text-slate-500">{e.type === "person" ? "Companies" : "Linked parties"}</dt>
                <dd>{c.linked_companies.length ? c.linked_companies.join(" · ") : "—"}</dd>
                <dt className="text-slate-500">Sources</dt>
                <dd className="text-slate-600 dark:text-slate-400">{[...new Set(e.sources.map((s) => s.source_label))].join(" · ")}</dd>
              </dl>
              <p className="mt-2 text-[11px] text-slate-500">Why: {c.explanation.join(" · ")}</p>
              <button className="btn-primary mt-auto self-end" onClick={() => onPick(c)} style={{ marginTop: 12 }}>
                Investigate <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
