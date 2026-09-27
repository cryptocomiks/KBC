import { useCountUp } from "../lib/motion";
/* Small data-viz kit shared by the case file, the dashboard and the tabs.
   Rules (see the palette tokens in index.css): thin marks with 4px rounded data ends,
   2px surface gaps between touching fills, recessive hairline grid, values and labels
   in text ink (never in the series colour), a legend whenever there are 2+ series,
   hover tooltips that never gate a value (legend values or the table view carry it). */
import { Table2 } from "lucide-react";
import { useState, type ReactNode } from "react";

export type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "accent";
export const TONE: Record<Tone, string> = {
  good: "var(--status-good)",
  warning: "var(--status-warning)",
  serious: "var(--status-serious)",
  critical: "var(--status-critical)",
  neutral: "var(--status-neutral)",
  accent: "var(--viz-accent)",
};
export const series = (i: number) => `var(--series-${(i % 8) + 1})`;
export const compact = (n: number) =>
  Math.abs(n) >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : Math.abs(n) >= 1e4 ? `${Math.round(n / 1e3)}K` : n.toLocaleString("en");

/* ------------------------------------------------------------------ tooltip */
interface Tip {
  x: number;
  y: number;
  body: ReactNode;
}
function useTip() {
  const [tip, setTip] = useState<Tip | null>(null);
  const show = (e: React.PointerEvent | React.FocusEvent, body: ReactNode) => {
    const host = (e.currentTarget as HTMLElement).closest("[data-viz]") as HTMLElement | null;
    if (!host) return;
    const r = host.getBoundingClientRect();
    const t = (e.currentTarget as Element).getBoundingClientRect();
    const px = "clientX" in e ? e.clientX : t.left + t.width / 2;
    const py = "clientY" in e ? e.clientY : t.top;
    setTip({ x: px - r.left, y: py - r.top, body });
  };
  const node = tip ? (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-30 min-w-28 -translate-x-1/2 -translate-y-[calc(100%+10px)] rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[11px] shadow-lg dark:border-white/10 dark:bg-[#161a20]"
      style={{ left: tip.x, top: tip.y }}
    >
      {tip.body}
    </div>
  ) : null;
  return { show, hide: () => setTip(null), node };
}
const TipRow = ({ color, label, value, line }: { color: string; label: string; value: ReactNode; line?: boolean }) => (
  <div className="flex items-center gap-2 whitespace-nowrap">
    <span className={line ? "h-0.5 w-3 rounded" : "h-2 w-2 rounded-[2px]"} style={{ background: color }} />
    <b className="text-slate-900 dark:text-white">{value}</b>
    <span className="text-slate-500">{label}</span>
  </div>
);

/* ---------------------------------------------------------------- stat tile */
export function Tile({
  label,
  value,
  sub,
  icon,
  tone,
  meter,
  onClick,
  hero,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
  meter?: { value: number; max: number; tone?: Tone };
  onClick?: () => void;
  hero?: boolean;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={`glass-tile flex min-w-0 flex-col rounded-xl p-3 text-left ${onClick ? "glass-press cursor-pointer" : ""}`}
    >
      <span className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
        {tone && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: TONE[tone] }} aria-hidden />}
        {icon}
        <span className="truncate">{label}</span>
      </span>
      <span className={`mt-1 font-semibold tracking-tight text-slate-900 tabular-nums dark:text-white ${hero ? "text-4xl" : "text-2xl"}`}>
        {typeof value === "number" && Number.isInteger(value) ? <CountUp value={value} /> : value}
      </span>
      {sub && <span className="mt-0.5 truncate text-[11px] text-slate-500">{sub}</span>}
      {meter && <Meter className="mt-2" value={meter.value} max={meter.max} tone={meter.tone} />}
    </Tag>
  );
}

/* -------------------------------------------------------------------- meter */
export function Meter({ value, max, tone = "accent", className = "", height = 6, label }: { value: number; max: number; tone?: Tone; className?: string; height?: number; label?: string }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (100 * value) / max)) : 0;
  return (
    <div
      className={`overflow-hidden rounded-full ${className}`}
      style={{ height, background: "var(--viz-track)" }}
      role="meter"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
    >
      <div className="bar-x h-full rounded-full" style={{ width: `${pct}%`, background: TONE[tone] }} />
    </div>
  );
}

/* ------------------------------------------------------------ stacked bar */
export interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
}
export function StackedBar({ segments, height = 10, legend = true, format = (n: number) => String(n), rest }: { segments: Segment[]; height?: number; legend?: boolean; format?: (n: number) => string; rest?: { label: string; value: number } }) {
  const tip = useTip();
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((n, s) => n + s.value, 0) + (rest?.value ?? 0);
  return (
    <div data-viz className="relative">
      <div className="flex w-full gap-[2px]" style={{ height }}>
        {total === 0 && <div className="flex-1 rounded" style={{ background: "var(--viz-track)" }} />}
        {shown.map((s, i) => (
          <div
            key={s.key}
            tabIndex={0}
            className={`bar-x h-full outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-brand-500 ${i === 0 ? "rounded-l" : ""} ${i === shown.length - 1 && !rest?.value ? "rounded-r" : ""}`}
            style={{ flex: s.value, background: s.color, minWidth: 3 }}
            onPointerMove={(e) => tip.show(e, <TipRow color={s.color} label={`${s.label} · ${Math.round((100 * s.value) / total)}%`} value={format(s.value)} />)}
            onFocus={(e) => tip.show(e, <TipRow color={s.color} label={s.label} value={format(s.value)} />)}
            onPointerLeave={tip.hide}
            onBlur={tip.hide}
          />
        ))}
        {!!rest?.value && (
          <div
            className="h-full rounded-r"
            style={{ flex: rest.value, background: "repeating-linear-gradient(135deg, var(--viz-track) 0 4px, transparent 4px 8px)", outline: "1px solid var(--viz-axis)", outlineOffset: -1 }}
            onPointerMove={(e) => tip.show(e, <TipRow color="var(--viz-axis)" label={rest.label} value={format(rest.value)} />)}
            onPointerLeave={tip.hide}
          />
        )}
      </div>
      {legend && (
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
          {segments.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
              <span className="text-slate-600 dark:text-slate-400">{s.label}</span>
              <b className="font-semibold text-slate-900 dark:text-white">{format(s.value)}</b>
            </li>
          ))}
          {!!rest?.value && (
            <li className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: "repeating-linear-gradient(135deg, var(--viz-axis) 0 2px, transparent 2px 4px)" }} />
              <span className="text-slate-600 dark:text-slate-400">{rest.label}</span>
              <b className="font-semibold text-slate-900 dark:text-white">{format(rest.value)}</b>
            </li>
          )}
        </ul>
      )}
      {tip.node}
    </div>
  );
}

/* ----------------------------------------------------------------- bar list */
export interface BarRow {
  key: string;
  label: ReactNode;
  value: number;
  display?: string;
  sub?: ReactNode;
  color?: string;
  onClick?: () => void;
}
/** Horizontal thin bars, one series (single hue unless a status colour carries meaning). */
export function BarList({ rows, max, marker, markerLabel }: { rows: BarRow[]; max?: number; marker?: number; markerLabel?: string }) {
  const tip = useTip();
  const top = max ?? Math.max(1, ...rows.map((r) => r.value));
  return (
    <div data-viz className="relative">
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.key}>
            <button
              type="button"
              disabled={!r.onClick}
              onClick={r.onClick}
              className="group grid w-full grid-cols-[minmax(0,11rem)_1fr_auto] items-center gap-3 text-left text-[12px] disabled:cursor-default"
              onPointerMove={(e) => tip.show(e, <TipRow color={r.color ?? TONE.accent} label={typeof r.label === "string" ? r.label : ""} value={r.display ?? r.value} />)}
              onPointerLeave={tip.hide}
            >
              <span className="min-w-0">
                <span className="block truncate text-slate-700 group-enabled:group-hover:text-brand-700 dark:text-slate-300 dark:group-enabled:group-hover:text-brand-400">{r.label}</span>
                {r.sub && <span className="block truncate text-[10.5px] text-slate-500">{r.sub}</span>}
              </span>
              <span className="relative h-2.5">
                <span className="absolute inset-0 rounded" style={{ background: "var(--viz-track)" }} />
                <span className="bar-x absolute inset-y-0 left-0 rounded-r" style={{ width: `${Math.max(1.5, (100 * r.value) / top)}%`, background: r.color ?? TONE.accent }} />
                {marker != null && (
                  <span className="absolute -inset-y-1 w-px bg-slate-500/70" style={{ left: `${(100 * marker) / top}%` }} title={markerLabel} />
                )}
              </span>
              <span className="w-14 text-right font-mono text-[11px] tabular-nums font-semibold text-slate-900 dark:text-white">{r.display ?? r.value}</span>
            </button>
          </li>
        ))}
      </ul>
      {marker != null && markerLabel && (
        <p className="mt-2 flex items-center gap-1.5 text-[10.5px] text-slate-500">
          <span className="h-3 w-px bg-slate-500/70" /> {markerLabel}
        </p>
      )}
      {tip.node}
    </div>
  );
}

/* ------------------------------------------------------------ stacked columns */
export function Columns({
  data,
  keys,
  height = 120,
}: {
  data: { label: string; values: Record<string, number> }[];
  keys: { key: string; label: string; color: string }[];
  height?: number;
}) {
  const tip = useTip();
  const totals = data.map((d) => keys.reduce((n, k) => n + (d.values[k.key] ?? 0), 0));
  const top = Math.max(1, ...totals);
  const nice = top <= 4 ? 4 : Math.ceil(top / 4) * 4;
  const ticks = [0, nice / 2, nice];
  return (
    <div data-viz className="relative">
      <div className="flex gap-2">
        <div className="relative w-6 shrink-0 font-mono text-[10px] tabular-nums text-slate-500" style={{ height }}>
          {ticks.map((t) => (
            <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: `${100 - (100 * t) / nice}%` }}>
              {t}
            </span>
          ))}
        </div>
        <div className="relative flex-1" style={{ height }}>
          {ticks.map((t) => (
            <div key={t} className="absolute inset-x-0 h-px" style={{ top: `${100 - (100 * t) / nice}%`, background: t === 0 ? "var(--viz-axis)" : "var(--viz-grid)" }} />
          ))}
          <div className="absolute inset-0 flex items-end gap-[3px]">
            {data.map((d, i) => (
              <div
                key={d.label}
                tabIndex={0}
                className="group flex h-full flex-1 cursor-default flex-col justify-end rounded outline-none hover:bg-slate-500/5 focus-visible:ring-2 focus-visible:ring-brand-500"
                onPointerMove={(e) =>
                  tip.show(
                    e,
                    <div>
                      <div className="mb-1 font-medium text-slate-500">{d.label}</div>
                      {keys.map((k) => (
                        <TipRow key={k.key} color={k.color} label={k.label} value={d.values[k.key] ?? 0} />
                      ))}
                    </div>,
                  )
                }
                onFocus={(e) => tip.show(e, <b>{`${d.label}: ${totals[i]}`}</b>)}
                onPointerLeave={tip.hide}
                onBlur={tip.hide}
              >
                <div className="mx-auto flex w-full max-w-[24px] flex-col-reverse gap-[2px]">
                  {keys.map((k, j) => {
                    const v = d.values[k.key] ?? 0;
                    if (!v) return null;
                    const last = keys.slice(j + 1).every((kk) => !(d.values[kk.key] ?? 0));
                    return <div key={k.key} className={`bar-y ${last ? "rounded-t" : ""}`} style={{ height: (height * v) / nice - 2, background: k.color }} />;
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-1 ml-8 flex justify-between font-mono text-[10px] text-slate-500">
        <span>{data[0]?.label}</span>
        <span>{data[Math.floor(data.length / 2)]?.label}</span>
        <span>{data[data.length - 1]?.label}</span>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
        {keys.map((k) => (
          <li key={k.key} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: k.color }} />
            <span className="text-slate-600 dark:text-slate-400">{k.label}</span>
            <b className="text-slate-900 dark:text-white">{data.reduce((n, d) => n + (d.values[k.key] ?? 0), 0)}</b>
          </li>
        ))}
      </ul>
      {tip.node}
    </div>
  );
}

/* --------------------------------------------------------------- chart card */
export function ChartCard({
  title,
  sub,
  children,
  table,
  action,
  className = "",
}: {
  title: string;
  sub?: ReactNode;
  children: ReactNode;
  table?: { head: string[]; rows: (string | number)[][] };
  action?: ReactNode;
  className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <section className={`card p-4 ${className}`}>
      <div className="mb-3 flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-[13px] font-semibold text-slate-900 dark:text-white">{title}</h3>
          {sub && <p className="text-[11px] text-slate-500">{sub}</p>}
        </div>
        {action}
        {table && (
          <button
            className={`btn-ghost px-2 py-1 text-[11px] ${asTable ? "text-brand-700 dark:text-brand-400" : ""}`}
            onClick={() => setAsTable(!asTable)}
            aria-pressed={asTable}
            title="Show the values as a table"
          >
            <Table2 className="h-3.5 w-3.5" /> Table
          </button>
        )}
      </div>
      {asTable && table ? (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-[12px]">
            <thead className="text-left text-[10.5px] uppercase tracking-wide text-slate-500">
              <tr>
                {table.head.map((h) => (
                  <th key={h} className="py-1 pr-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {table.rows.map((r, i) => (
                <tr key={i} className="border-t border-slate-100 dark:border-white/5">
                  {r.map((c, j) => (
                    <td key={j} className="py-1 pr-3">
                      {c}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ stepper */
export function Steps({ steps, current }: { steps: { key: string; label: string }[]; current: number }) {
  return (
    <ol className="flex items-center gap-1.5">
      {steps.map((s, i) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span
            className={`flex h-5 items-center gap-1 rounded-full px-2 text-[10.5px] font-semibold ${
              i < current
                ? "bg-brand-500/15 text-brand-700 dark:text-brand-300"
                : i === current
                  ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                  : "bg-slate-500/10 text-slate-500"
            }`}
          >
            {i < current ? "✓" : i + 1} {s.label}
          </span>
          {i < steps.length - 1 && <span className={`h-px w-3 ${i < current ? "bg-brand-500" : "bg-slate-300 dark:bg-white/15"}`} />}
        </li>
      ))}
    </ol>
  );
}

/** An integer that counts up to its value when it appears (static with reduced motion). */
export function CountUp({ value }: { value: number }) {
  const v = useCountUp(value, 800);
  return <>{Math.round(v).toLocaleString("en-US")}</>;
}
