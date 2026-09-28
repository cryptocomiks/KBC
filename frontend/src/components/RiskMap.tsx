import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Radar, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { fmtDate } from "../lib/format";
import type { KycQuestionnaire, RiskAxis, Vigilance } from "../types";
import { VIGILANCE, VigilanceBadge } from "./KycQuestionnaire";

const ORDER = ["geography", "activity", "client", "transactions"] as const;
const LEVEL_COLOR = { low: "#17b26a", medium: "#f79009", high: "#f04438" } as const;

/** Four-axis radar (0 at the centre, 100 at the tip), polygon filled with the brand colour. */
function RadarChart({ axes }: { axes: Record<string, RiskAxis> }) {
  const size = 240;
  const c = size / 2;
  const r = 82;
  // top, right, bottom, left
  const pt = (i: number, v: number) => {
    const angle = -Math.PI / 2 + (i * Math.PI) / 2;
    return [c + Math.cos(angle) * r * (v / 100), c + Math.sin(angle) * r * (v / 100)];
  };
  const poly = ORDER.map((k, i) => pt(i, Math.max(axes[k].score, 4)).join(",")).join(" ");
  return (
    <svg viewBox={`-48 0 ${size + 96} ${size}`} className="h-60 w-[21rem] max-w-full shrink-0" role="img" aria-label="Risk map">
      {[25, 50, 75, 100].map((ring) => (
        <polygon
          key={ring}
          points={ORDER.map((_, i) => pt(i, ring).join(",")).join(" ")}
          className="fill-none stroke-slate-200 dark:stroke-white/10"
          strokeWidth={1}
        />
      ))}
      {ORDER.map((_, i) => {
        const [x, y] = pt(i, 100);
        return <line key={i} x1={c} y1={c} x2={x} y2={y} className="stroke-slate-200 dark:stroke-white/10" />;
      })}
      <polygon points={poly} fill="var(--color-brand-500)" fillOpacity={0.22} stroke="var(--color-brand-500)" strokeWidth={1.8} />
      {ORDER.map((k, i) => {
        const [x, y] = pt(i, Math.max(axes[k].score, 4));
        return <circle key={k} cx={x} cy={y} r={4} fill={LEVEL_COLOR[axes[k].level]} />;
      })}
      {ORDER.map((k, i) => {
        const [x, y] = pt(i, 128);
        return (
          <text key={k} x={x} y={y + 4} textAnchor="middle" className="fill-slate-600 text-[11px] font-medium dark:fill-slate-300">
            {axes[k].label}
          </text>
        );
      })}
    </svg>
  );
}

interface Props {
  caseId: string;
  data: KycQuestionnaire;
}

/** Risk map of the client (four axes) and the analyst's adjustment of the vigilance level. */
export default function RiskMap({ caseId, data }: Props) {
  const qc = useQueryClient();
  const a = data.assessment;
  const [editing, setEditing] = useState(false);
  const [level, setLevel] = useState<Vigilance | "">(a?.override?.level ?? "");
  const [why, setWhy] = useState("");
  const [name, setName] = useState(analyst.get());
  const save = useMutation({
    mutationFn: () => api.overrideVigilance(caseId, level || null, why, name),
    onSuccess: () => {
      analyst.set(name);
      setEditing(false);
      setWhy("");
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  if (!a) return null;

  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Radar className="h-5 w-5 text-brand-600" />
        <span className="tag">Risk map</span>
        <span className="ml-auto flex items-center gap-2 text-xs text-slate-500">
          Final vigilance <VigilanceBadge level={a.level} />
        </span>
      </div>
      <div className="flex flex-col items-center gap-5 md:flex-row md:items-start">
        <RadarChart axes={a.axes} />
        <ul className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
          {ORDER.map((k) => {
            const ax = a.axes[k];
            return (
              <li key={k} className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
                <div className="flex items-center justify-between text-[13px] font-semibold">
                  {ax.label}
                  <span className="font-mono text-xs" style={{ color: LEVEL_COLOR[ax.level] }}>
                    {ax.score}/100
                  </span>
                </div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                  <div className="bar-x h-full rounded-full" style={{ width: `${ax.score}%`, background: LEVEL_COLOR[ax.level] }} />
                </div>
                <ul className="mt-2 space-y-0.5 text-[11px] leading-snug text-slate-500">
                  {ax.items.length ? ax.items.slice(0, 4).map((i) => <li key={i}>• {i}</li>) : <li>No risk factor on this axis.</li>}
                  {ax.items.length > 4 && <li>+ {ax.items.length - 4} more</li>}
                </ul>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Analyst adjustment */}
      <div className="mt-4 border-t border-slate-200 pt-3 dark:border-white/10">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <SlidersHorizontal className="h-4 w-4 text-slate-400" />
          <span>
            Computed level: <b>{VIGILANCE[a.computed_level].label}</b>
          </span>
          {a.override && (
            <span className="text-amber-700 dark:text-amber-300">
              · adjusted to <b>{VIGILANCE[a.level].label}</b> by {a.override.by} on {fmtDate(a.override.at)}: “{a.override.justification}”
            </span>
          )}
          {!editing && (
            <button className="btn-outline ml-auto py-1 text-xs" onClick={() => setEditing(true)}>
              Adjust the level
            </button>
          )}
        </div>
        {editing && (
          <form
            className="mt-3 grid gap-2 md:grid-cols-[180px_1fr_160px_auto]"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate();
            }}
          >
            <select className="input text-sm" value={level} onChange={(e) => setLevel(e.target.value as Vigilance | "")}>
              <option value="">Computed ({VIGILANCE[a.computed_level].label})</option>
              <option value="simplified">Simplified</option>
              <option value="standard">Standard</option>
              <option value="enhanced">Enhanced</option>
            </select>
            <input
              className="input text-sm"
              placeholder="Justification (required, kept in the audit trail)"
              value={why}
              onChange={(e) => setWhy(e.target.value)}
            />
            <input className="input text-sm" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
            <div className="flex gap-1.5">
              <button className="btn-primary" disabled={save.isPending || why.trim().length < 15 || !name.trim()}>
                {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save
              </button>
              <button type="button" className="btn-ghost" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
            {why.trim().length > 0 && why.trim().length < 15 && (
              <p className="text-[11px] text-slate-500 md:col-span-4">At least 15 characters: explain what the computation does not see.</p>
            )}
            {save.error && <p className="text-xs text-red-600 md:col-span-4">{(save.error as Error).message}</p>}
          </form>
        )}
        {!!data.override_history?.length && (
          <details className="mt-2 text-[11px] text-slate-500">
            <summary className="cursor-pointer">Adjustment history ({data.override_history.length})</summary>
            <ul className="mt-1 space-y-0.5">
              {data.override_history.map((h, i) => (
                <li key={i}>
                  {h.at.slice(0, 16).replace("T", " ")}: {h.by}: {h.level ? VIGILANCE[h.level].label : "back to computed"}: {h.justification}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
