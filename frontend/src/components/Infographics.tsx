import { Globe2, Landmark, PieChart } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { compact, toNumber, useCountUp, useWidth } from "../lib/motion";
import { countryName, flag } from "../lib/format";
import type { Investigation, Row } from "../types";

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

const PALETTE = ["#1d4a7a", "#2f6aa8", "#5b8bc4", "#8fb0d6", "#0e7c86", "#667085", "#98a2b3", "#344054"];

function Card({ icon: Icon, title, hint, children, className = "" }: { icon: typeof Globe2; title: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={`card p-5 ${className}`}>
      <div className="mb-4 flex items-baseline gap-2">
        <Icon className="h-4 w-4 translate-y-0.5 text-brand-600" />
        <h2 className="text-[15px] font-semibold">{title}</h2>
        {hint && <span className="truncate text-[11px] text-slate-500">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

/* ------------------------------------------------------------ ownership */

function Donut({ slices, center, sub }: { slices: { pct: number; color: string; key: string }[]; center: string; sub: string }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg viewBox="0 0 140 140" className="h-40 w-40 shrink-0" role="img" aria-label={`${center} ${sub}`}>
      <circle cx="70" cy="70" r={r} fill="none" strokeWidth="18" className="stroke-black/[0.06] dark:stroke-white/[0.08]" />
      {slices.map((s, i) => {
        const len = (Math.min(100, s.pct) / 100) * c;
        const el = (
          <circle
            key={s.key}
            cx="70"
            cy="70"
            r={r}
            fill="none"
            stroke={s.color}
            strokeWidth="18"
            strokeDasharray={`${len} ${c}`}
            strokeDashoffset={-offset}
            transform="rotate(-90 70 70)"
            style={{ transition: "stroke-dasharray 900ms var(--ease-fluid)", animation: `fade 500ms ${i * 90}ms both` }}
          />
        );
        offset += len;
        return el;
      })}
      <text x="70" y="68" textAnchor="middle" className="fill-current text-[20px] font-semibold">
        {center}
      </text>
      <text x="70" y="86" textAnchor="middle" className="fill-slate-500 text-[10px]">
        {sub}
      </text>
    </svg>
  );
}

export function OwnershipChart({ investigation: inv, onSelect }: Props) {
  const b = inv.brief;
  if (!b || (b.subject_type !== "company" && b.subject_type !== "person")) return null;
  const owners = b.owners;
  const company = b.subject_type === "company";
  const identified = Math.min(100, owners.reduce((s, o) => s + o.pct, 0));
  const color = (i: number, flags: string[]) => (flags.includes("sanctioned") ? "#d92d20" : PALETTE[i % PALETTE.length]);

  return (
    <Card icon={PieChart} title={company ? "Who owns it" : "What they hold"} hint="effective %, through every layer">
      {owners.length === 0 ? (
        <p className="text-sm text-slate-500">
          {company
            ? "No owner found in the sources — ask the client for the UBO declaration and a group structure chart."
            : "No shareholding found — see the officer roles in Linked companies."}
        </p>
      ) : (
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-start">
          {company && (
            <Donut
              slices={owners.map((o, i) => ({ pct: o.pct, color: color(i, o.flags), key: o.entity_id }))}
              center={`${identified.toFixed(0)}%`}
              sub="identified"
            />
          )}
          <ul className="stagger w-full min-w-0 flex-1 space-y-2.5">
            {owners.map((o, i) => (
              <li key={o.entity_id} style={{ ["--i" as string]: i }}>
                <button onClick={() => onSelect(o.entity_id)} className="group w-full text-left">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color(i, o.flags) }} />
                    <span className="truncate font-medium group-hover:text-brand-600">{o.name}</span>
                    {o.flags.map((f) => (
                      <span key={f} className="rounded bg-[#d92d20]/10 px-1.5 text-[10px] font-semibold text-[#b42318] uppercase">
                        {f}
                      </span>
                    ))}
                    <span className="ml-auto font-mono text-xs font-semibold tabular-nums">{o.pct.toFixed(o.pct < 1 ? 2 : 1)}%</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/[0.05] dark:bg-white/[0.08]">
                    <div className="bar-x h-full rounded-full" style={{ width: `${Math.min(100, o.pct)}%`, background: color(i, o.flags), ["--i" as string]: i }} />
                  </div>
                  {o.path.length > 2 && (
                    <div className="mt-0.5 truncate text-[11px] text-slate-500">
                      {company ? "via " : "through "}
                      {o.path.slice(1, -1).join(" → ")}
                    </div>
                  )}
                </button>
              </li>
            ))}
            {company && identified < 99.5 && (
              <li className="text-[11px] text-slate-500">{(100 - identified).toFixed(0)}% not identified in the sources (free float, undisclosed or below reporting thresholds).</li>
            )}
          </ul>
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------ financials */

const METRICS = [
  { key: "revenue", label: "Revenue", color: "#1d4a7a" },
  { key: "net_income", label: "Net income", color: "#0e7c86" },
  { key: "total_assets", label: "Total assets", color: "#98a2b3" },
] as const;

export function FinancialsChart({ investigation: inv, onSelect }: Props) {
  const byEntity = useMemo(() => {
    const m = new Map<string, Row[]>();
    for (const r of inv.tables.financials ?? []) {
      const id = String(r.entity_id);
      if (!m.has(id)) m.set(id, []);
      m.get(id)!.push(r);
    }
    return [...m.entries()].sort(([a, ra], [b, rb]) => Number(b === inv.subject_id) - Number(a === inv.subject_id) || rb.length - ra.length);
  }, [inv]);
  const [pick, setPick] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const width = useWidth(box);
  const current = byEntity.find(([id]) => id === pick) ?? byEntity[0];

  if (!current) {
    return (
      <Card icon={Landmark} title="Financials">
        <p className="text-sm text-slate-500">
          No published accounts in the sources queried — request the latest audited financial statements (small companies may legally opt out of
          publication).
        </p>
      </Card>
    );
  }
  const [entityId, rows] = current;
  const years = [...rows].sort((a, b) => String(a.year).localeCompare(String(b.year)));
  const metrics = METRICS.filter((m) => years.some((y) => toNumber(y[m.key]) !== null));
  const values = years.flatMap((y) => metrics.map((m) => toNumber(y[m.key]) ?? 0));
  const max = Math.max(1, ...values);
  const min = Math.min(0, ...values);
  const W = width;
  const H = 220;
  const top = 12;
  const bottom = 26;
  const left = 46;
  const scale = (v: number) => top + ((max - v) / (max - min)) * (H - top - bottom);
  const zero = scale(0);
  const groupW = (W - left - 8) / years.length;
  const barW = Math.min(40, (groupW - 24) / Math.max(1, metrics.length));
  const currency = String(years[0]?.currency ?? "");
  const last = years[years.length - 1];
  const prev = years[years.length - 2];
  const growth = (k: string) => {
    const a = toNumber(prev?.[k]);
    const b2 = toNumber(last?.[k]);
    return a && b2 ? ((b2 - a) / Math.abs(a)) * 100 : null;
  };

  return (
    <Card icon={Landmark} title="Financials" hint={`${currency} · ${String(years[0]?.source ?? "")}`} >
      {byEntity.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {byEntity.map(([id, r]) => (
            <button
              key={id}
              onClick={() => setPick(id)}
              className={`rounded px-2.5 py-1 text-xs font-medium transition ${
                id === entityId ? "bg-brand-600 text-white" : "bg-black/[0.05] text-slate-600 hover:bg-black/[0.08] dark:bg-white/[0.08] dark:text-slate-300"
              }`}
            >
              {String(r[0].name)}
            </button>
          ))}
        </div>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {metrics.map((m) => (
          <KeyNumber key={m.key} label={`${m.label} ${String(last.year)}`} value={toNumber(last[m.key])} color={m.color} growth={growth(m.key)} />
        ))}
      </div>
      <div ref={box}>
      <svg key={entityId} width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="block" role="img" aria-label="Financials by year">
        {[max, max / 2, 0, min]
          .filter((v, i, a) => a.indexOf(v) === i && (v === 0 || Math.abs(scale(v) - zero) > 14))
          .map((v) => (
          <g key={v}>
            <line x1={left} x2={W} y1={scale(v)} y2={scale(v)} className={v === 0 ? "stroke-slate-400/60" : "stroke-black/[0.06] dark:stroke-white/[0.08]"} />
            <text x={left - 6} y={scale(v) + 3} textAnchor="end" className="fill-slate-500 text-[10px]">
              {compact(v)}
            </text>
          </g>
        ))}
        {years.map((y, yi) => (
          <g key={String(y.year)}>
            {metrics.map((m, mi) => {
              const v = toNumber(y[m.key]);
              if (v === null) return null;
              const x = left + yi * groupW + (groupW - barW * metrics.length) / 2 + mi * barW;
              const yTop = v >= 0 ? scale(v) : zero;
              const h = Math.max(1, Math.abs(scale(v) - zero));
              const neg = v < 0;
              return (
                <rect
                  key={m.key}
                  x={x + 1}
                  y={yTop}
                  width={barW - 2}
                  height={h}
                  rx={4}
                  fill={neg ? "#d92d20" : m.color}
                  className="bar-y"
                  style={{ ["--i" as string]: yi * metrics.length + mi, transformOrigin: neg ? "top" : "bottom" }}
                >
                  <title>{`${m.label} ${String(y.year)}: ${v.toLocaleString("en")} ${currency}`}</title>
                </rect>
              );
            })}
            <text x={left + yi * groupW + groupW / 2} y={H - 8} textAnchor="middle" className="fill-slate-500 text-[11px]">
              {String(y.year)}
            </text>
          </g>
        ))}
      </svg>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
        {metrics.map((m) => (
          <span key={m.key} className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm" style={{ background: m.color }} /> {m.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-[#d92d20]" /> Loss
        </span>
        <button className="ml-auto text-brand-600 hover:underline" onClick={() => onSelect(entityId)}>
          Open the company file
        </button>
      </div>
    </Card>
  );
}

function KeyNumber({ label, value, color, growth }: { label: string; value: number | null; color: string; growth: number | null }) {
  const v = useCountUp(value ?? 0);
  return (
    <div className="rounded-xl bg-black/[0.03] px-3 py-2 dark:bg-white/[0.05]">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} /> {label}
      </div>
      <div className="text-[20px] font-semibold tracking-[-0.01em] tabular-nums">{value === null ? "—" : compact(v)}</div>
      {growth !== null && (
        <div className={`text-[11px] font-medium ${growth >= 0 ? "text-[#067647] dark:text-[#47cd89]" : "text-[#b42318] dark:text-[#fda29b]"}`}>
          {growth >= 0 ? "▲" : "▼"} {Math.abs(growth).toFixed(1)}% vs previous year
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ countries */

const basel = (s: number | null) =>
  s === null ? "#98a2b3" : s >= 6.5 ? "#d92d20" : s >= 5.5 ? "#dc6803" : s >= 4.5 ? "#eaaa08" : "#079455";

export function CountryExposure({ investigation: inv }: Props) {
  const rows = (inv.tables.jurisdictions ?? []).filter((r) => Number(r.entities) > 0);
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => Number(r.entities)));
  const sorted = [...rows].sort((a, b) => (toNumber(b.basel_aml_score) ?? 0) - (toNumber(a.basel_aml_score) ?? 0) || Number(b.entities) - Number(a.entities));
  return (
    <Card icon={Globe2} title="Country exposure" hint="bar = entities · colour = Basel AML Index">
      <ul className="stagger space-y-2.5">
        {sorted.slice(0, 10).map((r, i) => {
          const score = toNumber(r.basel_aml_score);
          const lists = String(r.lists ?? "")
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
          return (
            <li key={String(r.code)} style={{ ["--i" as string]: i }}>
              <div className="flex items-center gap-2 text-sm">
                <span>{flag(String(r.code))}</span>
                <span className="truncate font-medium">{countryName(String(r.code))}</span>
                <span className="ml-auto shrink-0 text-[11px] text-slate-500 tabular-nums">
                  {score !== null ? `Basel ${score.toFixed(1)}` : "Basel —"}
                  {r.cpi_score != null && ` · CPI ${String(r.cpi_score)}`}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-black/[0.05] dark:bg-white/[0.08]">
                  <div className="bar-x h-full rounded-full" style={{ width: `${(Number(r.entities) / max) * 100}%`, background: basel(score), ["--i" as string]: i }} />
                </div>
                <span className="w-16 shrink-0 text-right text-[11px] text-slate-500 tabular-nums">{String(r.entities)} {Number(r.entities) === 1 ? "entity" : "entities"}</span>
              </div>
              {lists.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {lists.map((l) => (
                    <span key={l} className="rounded bg-[#dc6803]/15 px-1.5 text-[10px] font-semibold text-[#b54708] dark:text-[#fec84b]">
                      {l}
                    </span>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
