import { Check, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

const STEPS = [
  ["Looking the subject up in the registries", 0],
  ["Screening against sanctions, PEP and leak lists", 2],
  ["Expanding the network: officers, shareholders, subsidiaries", 5],
  ["Cross-referencing every new party across registries", 12],
  ["Collecting filings, notices and adverse media", 30],
  ["Screening every linked party", 60],
  ["Scoring the risk and writing the brief", 150],
] as const;

/** Progress while the investigation runs: steps light up with the elapsed time, over a skeleton of the overview. */
export default function LoadingInvestigation() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const t = setInterval(() => setElapsed((Date.now() - start) / 1000), 250);
    return () => clearInterval(t);
  }, []);
  const current = STEPS.reduce((acc, [, at], i) => (elapsed >= at ? i : acc), 0);

  return (
    <div className="panel-enter space-y-4" aria-busy="true" aria-live="polite">
      <div className="card flex flex-col items-center gap-4 px-6 py-8 text-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        <div>
          <div className="text-[15px] font-semibold">Investigation in progress</div>
          <div className="text-xs text-slate-500 tabular-nums">
            {Math.floor(elapsed)} s · large networks can take a few minutes, every answer is cached for the next run
          </div>
        </div>
        <ol className="w-full max-w-md space-y-1.5 text-left text-sm">
          {STEPS.map(([label], i) => (
            <li
              key={label}
              className={`flex items-center gap-2 transition-all duration-500 ${i > current ? "opacity-35" : "opacity-100"}`}
            >
              <span
                className={`grid h-5 w-5 shrink-0 place-items-center rounded-full transition-colors duration-500 ${
                  i < current ? "bg-[#079455] text-white" : i === current ? "bg-brand-600 text-white" : "bg-black/[0.06] dark:bg-white/[0.1]"
                }`}
              >
                {i < current ? <Check className="h-3 w-3" /> : i === current ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              </span>
              {label}
            </li>
          ))}
        </ol>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="card space-y-3 p-5" style={{ animationDelay: `${i * 60}ms` }}>
            <div className="h-4 w-40 animate-pulse rounded bg-black/[0.06] dark:bg-white/[0.08]" />
            {[0, 1, 2].map((j) => (
              <div key={j} className="h-3 animate-pulse rounded bg-black/[0.05] dark:bg-white/[0.06]" style={{ width: `${90 - j * 18}%` }} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
