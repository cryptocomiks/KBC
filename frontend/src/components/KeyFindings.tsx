import { AlertOctagon, AlertTriangle, ExternalLink, Info, Sparkles } from "lucide-react";
import type { Finding, Investigation } from "../types";

const ICON = { info: Info, warning: AlertTriangle, critical: AlertOctagon } as const;
const TONE = {
  info: "text-slate-500",
  warning: "text-amber-600 dark:text-amber-400",
  critical: "text-red-600 dark:text-red-400",
} as const;

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

/** Key findings: a short, sourced reading of the network, generated from the data (no black box). */
export default function KeyFindings({ investigation: inv, onSelect }: Props) {
  if (!inv.summary?.length) return null;
  const names = new Map(inv.entities.map((e) => [e.id, e.name]));
  return (
    <div className="card p-4">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Sparkles className="h-4 w-4 text-brand-600" /> Key findings
        <span className="text-[11px] font-normal text-slate-500">generated from the sources below — verify before relying on it</span>
      </h2>
      <ul className="space-y-1.5">
        {inv.summary.map((f: Finding, i) => {
          const Icon = ICON[f.severity] ?? Info;
          return (
            <li key={i} className="flex gap-2 text-sm leading-snug">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${TONE[f.severity] ?? TONE.info}`} />
              <span>
                {f.text}
                {f.entity_ids.filter((id) => names.has(id)).length > 0 && (
                  <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
                    {[...new Set(f.entity_ids)]
                      .filter((id) => names.has(id))
                      .slice(0, 4)
                      .map((id) => (
                        <button
                          key={id}
                          onClick={() => onSelect(id)}
                          className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-brand-50 hover:text-brand-700 dark:bg-slate-800 dark:text-slate-300"
                        >
                          {names.get(id)}
                        </button>
                      ))}
                  </span>
                )}
                {f.urls.slice(0, 2).map((u) => (
                  <a key={u} href={u} target="_blank" rel="noreferrer" className="ml-1 inline-flex align-middle text-brand-600" title={u}>
                    <ExternalLink className="h-3 w-3" />
                  </a>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
