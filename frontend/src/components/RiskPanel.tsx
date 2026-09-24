import { ChevronDown, ChevronRight, Scale } from "lucide-react";
import { Fragment, useState } from "react";
import { RISK_BADGE, RISK_COLORS } from "../lib/format";
import { useCountUp } from "../lib/motion";
import type { Investigation } from "../types";

export function RiskGauge({ score: target, level }: { score: number; level: keyof typeof RISK_COLORS }) {
  const r = 34;
  const c = 2 * Math.PI * r;
  const score = useCountUp(target, 1100);
  return (
    <div className="flex items-center gap-3">
      <svg width="84" height="84" viewBox="0 0 84 84" role="img" aria-label={`Risk score ${target} of 100`}>
        <circle cx="42" cy="42" r={r} fill="none" strokeWidth="8" className="stroke-slate-200 dark:stroke-slate-800" />
        <circle
          cx="42"
          cy="42"
          r={r}
          fill="none"
          strokeWidth="8"
          stroke={RISK_COLORS[level]}
          style={{ transition: "stroke 400ms ease" }}
          strokeDasharray={`${(score / 100) * c} ${c}`}
          strokeLinecap="round"
          transform="rotate(-90 42 42)"
        />
        <text x="42" y="47" textAnchor="middle" className="fill-current text-[20px] font-bold">
          {level === "incomplete" ? `≥${Math.round(score)}` : Math.round(score)}
        </text>
      </svg>
      <div>
        <div className="label">Risk score</div>
        <span className={`mt-1 inline-block rounded px-2 py-0.5 text-xs font-bold uppercase ${RISK_BADGE[level]}`}>{level}</span>
        {level === "incomplete" && <div className="mt-1 max-w-[12rem] text-[11px] text-slate-500">Subject not screened in time — rerun</div>}
      </div>
    </div>
  );
}

export default function RiskPanel({ investigation: inv, onSelect }: { investigation: Investigation; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [showMethod, setShowMethod] = useState(false);
  const names = new Map(inv.entities.map((e) => [e.id, e.name]));
  const max = Math.max(1, ...inv.risk.factors.map((f) => f.points));

  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center gap-2">
        <Scale className="h-4 w-4" />
        <h3 className="font-semibold">Why this score? — explained risk factors</h3>
        <span className="ml-auto text-xs text-slate-500">
          Σ points = <strong>{inv.risk.score}</strong> / 100
        </span>
      </div>
      {inv.risk.factors.length === 0 && <p className="text-sm text-slate-500">No risk factor triggered.</p>}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 pr-2 font-medium">Factor</th>
              <th className="px-2 font-medium">Weight</th>
              <th className="px-2 font-medium" title="Distance of the closest affected entity to the subject">
                Hops
              </th>
              <th className="px-2 font-medium">Proximity</th>
              <th className="w-1/3 px-2 font-medium">Points</th>
              <th className="px-2 font-medium">Entities</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {inv.risk.factors.map((f) => (
              <Fragment key={f.key}>
                <tr className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => setOpen(open === f.key ? null : f.key)}>
                  <td className="py-1.5 pr-2 font-medium">
                    <span className="inline-flex items-center gap-1">
                      {open === f.key ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      {f.label}
                    </span>
                  </td>
                  <td className="px-2">{f.weight}</td>
                  <td className="px-2">{f.distance}</td>
                  <td className="px-2">×{f.multiplier}</td>
                  <td className="px-2">
                    <div className="flex items-center gap-2">
                      <div className="h-2 rounded bg-red-500/80" style={{ width: `${(f.points / max) * 100}%`, minWidth: 4 }} />
                      <span className="font-semibold">+{f.points}</span>
                    </div>
                  </td>
                  <td className="px-2">{f.entities.length}</td>
                </tr>
                {open === f.key && (
                  <tr>
                    <td colSpan={6} className="bg-slate-50 px-6 py-2 dark:bg-slate-800/40">
                      <ul className="list-disc space-y-0.5 pl-4">
                        {f.evidence.map((ev) => (
                          <li key={ev}>{ev}</li>
                        ))}
                      </ul>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {f.entities.map((id) => (
                          <button key={id} className="rounded border border-slate-300 px-1.5 py-0.5 hover:border-brand-500 dark:border-slate-600" onClick={() => onSelect(id)}>
                            {names.get(id) ?? id}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <button className="mt-3 text-xs text-brand-600 hover:underline" onClick={() => setShowMethod((s) => !s)}>
        {showMethod ? "Hide" : "Show"} methodology
      </button>
      {showMethod && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-slate-600 dark:text-slate-400">
          {inv.risk.methodology.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
