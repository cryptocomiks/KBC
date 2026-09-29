import { Copy, Scale } from "lucide-react";
import { useState } from "react";
import { toast } from "../lib/toast";
import type { Investigation, LegalRef } from "../types";

const FLAG: Record<string, string> = { CH: "CH", EU: "EU", US: "US", FATF: "FATF" };

export function RefChips({ refs }: { refs: LegalRef[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {refs.map((r) => {
        const body = (
          <>
            {!r.short.startsWith(r.jurisdiction) && <span className="text-[9px] font-bold tracking-wide text-slate-600 dark:text-slate-300">{FLAG[r.jurisdiction] ?? r.jurisdiction}</span>} {r.short}
          </>
        );
        const cls = "inline-flex items-center gap-1 rounded-md bg-black/[0.04] px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-white/[0.06] dark:text-slate-300";
        return r.url ? (
          <a key={r.id} href={r.url} target="_blank" rel="noreferrer" title={r.title} className={`${cls} hover:text-brand-600`}>
            {body}
          </a>
        ) : (
          <span key={r.id} title={r.title} className={cls}>
            {body}
          </span>
        );
      })}
    </span>
  );
}

/** Each red flag with the texts it rests on and a justification to paste in the file. */
export default function LegalBasis({ investigation: inv }: { investigation: Investigation }) {
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const items = inv.legal ?? [];
  if (!items.length) return null;
  const copy = async (text: string, what: string) => {
    await navigator.clipboard?.writeText(text).catch(() => undefined);
    toast(what);
  };
  const all = items.map((i) => `• ${i[lang] ?? i.label}`).join("\n");
  return (
    <section className="card overflow-hidden">
      <header className="flex flex-wrap items-center gap-2 px-5 pt-5">
        <div className="mr-auto">
          <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
            <Scale className="h-4 w-4 text-brand-500" /> Legal basis and justification
          </h2>
          <p className="text-[13px] text-slate-500">Each red flag with the provisions it rests on (Switzerland, EU, FATF, OFAC) and a text ready for the file.</p>
        </div>
        <div className="segmented" role="group" aria-label="Language of the justifications">
          {(["fr", "en"] as const).map((l) => (
            <button
              key={l}
              onClick={() => setLang(l)}
              aria-pressed={lang === l}
              className={`rounded-[8px] px-2.5 py-1 text-xs font-medium ${lang === l ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}
            >
              {l === "fr" ? "Français" : "English"}
            </button>
          ))}
        </div>
        <button onClick={() => copy(all, "Justifications copied")} className="btn-outline h-8 text-xs">
          <Copy className="h-3.5 w-3.5" /> Copy all
        </button>
      </header>
      <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
        {items.map((i) => (
          <li key={i.key} className="px-5 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[14px] font-medium">{i.label}</span>
              {i.points > 0 && <span className="text-[11px] text-slate-500 tabular-nums">{i.points} pts</span>}
              <span className="ml-auto">
                <RefChips refs={i.refs} />
              </span>
            </div>
            {i[lang] && (
              <p className="mt-1.5 text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">
                {i[lang]}{" "}
                <button onClick={() => copy(i[lang] ?? "", "Justification copied")} className="ml-1 inline-flex items-center gap-1 text-[12px] text-brand-600 hover:underline">
                  <Copy className="h-3 w-3" /> copy
                </button>
              </p>
            )}
          </li>
        ))}
      </ul>
      <p className="border-t border-slate-200/70 px-5 py-3 text-[11px] text-slate-500 dark:border-white/[0.06]">
        An operational map to the texts, not legal advice: check the current version of each text and your institution's directives.
      </p>
    </section>
  );
}
