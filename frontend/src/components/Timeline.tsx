import { CalendarClock, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import type { Investigation, TimelineEvent } from "../types";

const KINDS: Record<TimelineEvent["kind"], { label: string; dot: string }> = {
  company: { label: "Company life", dot: "bg-slate-500" },
  role: { label: "Officers", dot: "bg-sky-500" },
  ownership: { label: "Ownership", dot: "bg-indigo-500" },
  filing: { label: "Filings", dot: "bg-emerald-500" },
  legal_notice: { label: "Legal notices", dot: "bg-teal-500" },
  sanction: { label: "Sanctions & lists", dot: "bg-red-500" },
  media: { label: "Press", dot: "bg-orange-500" },
  transfer: { label: "Crypto flows", dot: "bg-amber-500" },
  country: { label: "Country risk", dot: "bg-fuchsia-500" },
};

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

export default function Timeline({ investigation: inv, onSelect }: Props) {
  const events = inv.timeline ?? [];
  const present = useMemo(() => [...new Set(events.map((e) => e.kind))], [events]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [showAll, setShowAll] = useState(false);
  if (!events.length) return null;

  const shown = events.filter((e) => !hidden.has(e.kind));
  const visible = showAll ? shown : shown.slice(0, 40);
  const toggle = (k: string) =>
    setHidden((h) => {
      const n = new Set(h);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });

  let lastYear = "";
  return (
    <div className="card p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <CalendarClock className="h-4 w-4 text-brand-600" /> Timeline
          <span className="text-[11px] font-normal text-slate-500">{events.length} dated events</span>
        </h2>
        <div className="ml-auto flex flex-wrap gap-1">
          {present.map((k) => (
            <button
              key={k}
              onClick={() => toggle(k)}
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] ${
                hidden.has(k) ? "border-slate-200 text-slate-400 dark:border-slate-700" : "border-slate-300 dark:border-slate-600"
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${KINDS[k]?.dot ?? "bg-slate-400"} ${hidden.has(k) ? "opacity-30" : ""}`} />
              {KINDS[k]?.label ?? k}
            </button>
          ))}
        </div>
      </div>
      <ol className="relative ml-2 border-l border-slate-200 dark:border-slate-700">
        {visible.map((e, i) => {
          const year = e.date.slice(0, 4);
          const header = year !== lastYear;
          lastYear = year;
          return (
            <li key={`${e.date}-${i}`} className="ml-4 pb-2">
              {header && <div className="-ml-8 mb-1 mt-2 w-12 bg-white text-xs font-bold text-slate-500 dark:bg-slate-900">{year}</div>}
              <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ring-2 ring-white dark:ring-slate-900 ${KINDS[e.kind]?.dot ?? "bg-slate-400"}`} />
              <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="w-20 shrink-0 font-mono text-[11px] text-slate-500">{e.date}</span>
                {e.entity_id ? (
                  <button onClick={() => onSelect(e.entity_id!)} className="text-left hover:text-brand-600">
                    {e.title}
                  </button>
                ) : (
                  <span>{e.title}</span>
                )}
                {e.url && (
                  <a href={e.url} target="_blank" rel="noreferrer" className="text-brand-600" title={e.source ?? e.url}>
                    <ExternalLink className="inline h-3 w-3" />
                  </a>
                )}
              </div>
              {(e.detail || e.source) && (
                <div className="ml-[5.5rem] text-[11px] text-slate-500">
                  {e.detail}
                  {e.detail && e.source ? " · " : ""}
                  {e.source}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {shown.length > 40 && (
        <button className="btn-ghost mt-2 text-xs" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Show fewer" : `Show all ${shown.length} events`}
        </button>
      )}
    </div>
  );
}
