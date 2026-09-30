import { Clock, Coins, RotateCcw, Users } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

/** Minutes per client file, by hand and with KYC 1 CLICK. Orders of magnitude seen in KYC
 *  teams for a corporate client: every value can be replaced by the team's own measure. */
const STEPS = [
  { key: "map", label: "Registers and ownership chart (every country, owners of owners)", manual: 120, tool: 10 },
  { key: "screen", label: "Sanctions, PEP and press screening, triage of the hits", manual: 60, tool: 10 },
  { key: "risk", label: "Risk assessment, questionnaire and written justification", manual: 45, tool: 15 },
  { key: "request", label: "Writing the document requests", manual: 20, tool: 2 },
  { key: "chase", label: "Tracking receptions and chasing the client", manual: 40, tool: 5 },
  { key: "report", label: "File report, decision memo and PDF", manual: 60, tool: 10 },
];
const DEFAULTS = { team: 5, files: 8, reviews: 8, portfolio: 150, rate: 90, hours: 140, external: 350, reviewManual: 120, reviewTool: 25, rescreen: 3 };
const KEY = "kbc-roi";

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (v && typeof v === "object") return v;
  } catch {
    /* private mode */
  }
  return null;
}

/** Number that glides to its new value (instant when the user prefers less motion). */
function Animated({ value, format }: { value: number; format: (n: number) => string }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      setShown(value);
      from.current = value;
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / 600);
      const e = 1 - (1 - k) ** 3;
      setShown(a + (value - a) * e);
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{format(shown)}</>;
}

const nf = (d = 0) => (n: number) => n.toLocaleString("en-GB", { maximumFractionDigits: d, minimumFractionDigits: d }).replace(/,/g, "’");

function Num({ label, value, onChange, suffix, min = 0, step = 1 }: { label: string; value: number; onChange: (v: number) => void; suffix?: string; min?: number; step?: number }) {
  return (
    <label className="block text-xs">
      <span className="label mb-1 block">{label}</span>
      <span className="flex items-center gap-1.5">
        <input type="number" min={min} step={step} className="input w-full py-1.5 text-sm tabular-nums" value={value} onChange={(e) => onChange(Math.max(min, Number(e.target.value) || 0))} />
        {suffix && <span className="shrink-0 text-slate-500">{suffix}</span>}
      </span>
    </label>
  );
}

/** What the team gets back: hours per collaborator, full-time equivalents, money, against an external provider. */
export default function TimeSaved() {
  const saved = load();
  const [p, setP] = useState<typeof DEFAULTS>({ ...DEFAULTS, ...(saved?.p ?? {}) });
  const [steps, setSteps] = useState(STEPS.map((s) => ({ ...s, ...(saved?.steps?.[s.key] ?? {}) })));
  useEffect(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ p, steps: Object.fromEntries(steps.map((s) => [s.key, { manual: s.manual, tool: s.tool }])) }));
    } catch {
      /* private mode */
    }
  }, [p, steps]);

  const r = useMemo(() => {
    const perFileManual = steps.reduce((n, s) => n + s.manual, 0);
    const perFileTool = steps.reduce((n, s) => n + s.tool, 0);
    const filesMin = p.files * (perFileManual - perFileTool);
    const reviewsMin = p.reviews * (p.reviewManual - p.reviewTool);
    const rescreenMin = p.portfolio * p.rescreen; // monthly manual re-screening replaced by daily monitoring
    const perCollabHours = (filesMin + reviewsMin + rescreenMin) / 60;
    const teamHoursYear = perCollabHours * p.team * 12;
    const fte = (perCollabHours * p.team) / Math.max(1, p.hours);
    const valueYear = teamHoursYear * p.rate;
    const inHousePerFile = (perFileTool / 60) * p.rate;
    return {
      perFileManual,
      perFileTool,
      perCollabHours,
      share: Math.min(100, (perCollabHours / Math.max(1, p.hours)) * 100),
      teamHoursYear,
      fte,
      valueYear,
      inHousePerFile,
      ratio: inHousePerFile > 0 ? p.external / inHousePerFile : 0,
      speed: perFileTool > 0 ? perFileManual / perFileTool : 0,
    };
  }, [p, steps]);
  const max = Math.max(...steps.map((s) => s.manual), 1);

  return (
    <div className="space-y-6">
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Result">
        {[
          { Icon: Clock, label: "Hours saved per collaborator, per month", value: r.perCollabHours, fmt: nf(0), sub: `${Math.round(r.share)} % of their working time` },
          { Icon: Users, label: "Full-time equivalents freed in the team", value: r.fte, fmt: nf(1), sub: `${nf(0)(r.teamHoursYear)} hours a year` },
          { Icon: Coins, label: "Value of the time saved, per year", value: r.valueYear, fmt: (n: number) => `CHF ${nf(0)(n)}`, sub: `at CHF ${p.rate} an hour` },
          { Icon: Clock, label: "One client file", value: r.perFileTool, fmt: (n: number) => `${nf(0)(n)} min`, sub: `instead of ${Math.round(r.perFileManual / 60 * 10) / 10} h: ${nf(1)(r.speed)}× faster` },
        ].map((k) => (
          <div key={k.label} className="glass-tile rounded-2xl p-4">
            <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-slate-500">
              <k.Icon className="h-3.5 w-3.5" aria-hidden /> {k.label}
            </div>
            <div className="mt-1 text-[32px] leading-tight font-semibold tracking-tight tabular-nums" aria-live="polite">
              <Animated value={k.value} format={k.fmt} />
            </div>
            <div className="text-[12px] text-slate-500">{k.sub}</div>
          </div>
        ))}
      </section>

      <section className="card p-5" aria-labelledby="vs-external">
        <h3 id="vs-external" className="text-sm font-semibold">
          Compared with an external provider
        </h3>
        <p className="mt-1 text-[13px] text-slate-500">
          A corporate KYC file done by a fiduciary or an audit firm is billed around CHF {p.external}. Done in-house with KYC 1 CLICK it costs {Math.round(r.perFileTool)} minutes of
          an analyst: CHF {nf(0)(r.inHousePerFile)}.
        </p>
        <div className="mt-4 space-y-2">
          {[
            ["External provider", p.external, "bg-slate-400"],
            ["In-house with KYC 1 CLICK", r.inHousePerFile, "bg-brand-500"],
          ].map(([label, v, cls]) => (
            <div key={label as string} className="grid items-center gap-3 sm:grid-cols-[200px_minmax(0,1fr)_110px]">
              <span className="text-[13px]">{label}</span>
              <div className="h-3 overflow-hidden rounded-full bg-black/[0.05] dark:bg-white/[0.08]">
                <div className={`bar-x h-full rounded-full ${cls}`} style={{ width: `${Math.max(1.5, ((v as number) / Math.max(p.external, r.inHousePerFile, 1)) * 100)}%` }} />
              </div>
              <span className="text-right text-[13px] font-semibold tabular-nums">CHF {nf(0)(v as number)}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[15px] font-semibold">
          <Animated value={r.ratio} format={nf(1)} />× cheaper per file
        </p>
      </section>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card p-5" aria-labelledby="steps">
          <div className="flex items-center gap-2">
            <h3 id="steps" className="text-sm font-semibold">
              Minutes per client file, step by step
            </h3>
            <button
              className="btn-ghost ml-auto px-2 py-1 text-xs"
              onClick={() => {
                setSteps(STEPS.map((s) => ({ ...s })));
                setP(DEFAULTS);
              }}
            >
              <RotateCcw className="h-3.5 w-3.5" /> Defaults
            </button>
          </div>
          <ul className="mt-3 space-y-3">
            {steps.map((s, i) => (
              <li key={s.key}>
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="min-w-0 flex-1">{s.label}</span>
                  <label className="flex items-center gap-1 text-[11.5px] text-slate-500">
                    by hand
                    <input type="number" min={0} className="input w-16 px-2 py-0.5 text-xs tabular-nums" value={s.manual} aria-label={`${s.label}: minutes by hand`} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, manual: Math.max(0, Number(e.target.value) || 0) } : x)))} />
                  </label>
                  <label className="flex items-center gap-1 text-[11.5px] text-slate-500">
                    with the tool
                    <input type="number" min={0} className="input w-16 px-2 py-0.5 text-xs tabular-nums" value={s.tool} aria-label={`${s.label}: minutes with KYC 1 CLICK`} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, tool: Math.max(0, Number(e.target.value) || 0) } : x)))} />
                  </label>
                </div>
                <div className="mt-1.5 space-y-1" aria-hidden>
                  <div className="h-1.5 overflow-hidden rounded-full bg-black/[0.05] dark:bg-white/[0.08]">
                    <div className="bar-x h-full rounded-full bg-slate-400" style={{ width: `${(s.manual / max) * 100}%` }} />
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-black/[0.05] dark:bg-white/[0.08]">
                    <div className="bar-x h-full rounded-full bg-brand-500" style={{ width: `${(s.tool / max) * 100}%` }} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-[12px] text-slate-500">
            Grey: by hand. Blue: with KYC 1 CLICK. Default values are typical orders of magnitude for a corporate client with a foreign holding: replace them with your team&apos;s
            own measures.
          </p>
        </section>

        <section className="card space-y-3 p-5" aria-labelledby="team">
          <h3 id="team" className="text-sm font-semibold">
            Your team
          </h3>
          <Num label="Collaborators on KYC" value={p.team} onChange={(v) => setP({ ...p, team: v })} min={1} />
          <Num label="New client files per collaborator, per month" value={p.files} onChange={(v) => setP({ ...p, files: v })} />
          <Num label="Periodic reviews per collaborator, per month" value={p.reviews} onChange={(v) => setP({ ...p, reviews: v })} />
          <div className="grid grid-cols-2 gap-2">
            <Num label="Review by hand" value={p.reviewManual} onChange={(v) => setP({ ...p, reviewManual: v })} suffix="min" />
            <Num label="Review with the tool" value={p.reviewTool} onChange={(v) => setP({ ...p, reviewTool: v })} suffix="min" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Num label="Clients followed per collaborator" value={p.portfolio} onChange={(v) => setP({ ...p, portfolio: v })} />
            <Num label="Monthly re-screening by hand" value={p.rescreen} onChange={(v) => setP({ ...p, rescreen: v })} suffix="min/client" step={0.5} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Num label="Full cost of an hour" value={p.rate} onChange={(v) => setP({ ...p, rate: v })} suffix="CHF" />
            <Num label="Working hours a month" value={p.hours} onChange={(v) => setP({ ...p, hours: v })} min={1} />
          </div>
          <Num label="External provider, price per file" value={p.external} onChange={(v) => setP({ ...p, external: v })} suffix="CHF" />
          <p className="text-[11.5px] text-slate-500">Monitoring re-screens every client every day, so the monthly manual re-screening disappears. Your figures stay in this browser.</p>
        </section>
      </div>
    </div>
  );
}
