import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, ChevronDown, ChevronRight, ClipboardCheck, Loader2, Sparkles, X } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { countryName, flag, fmtDate } from "../lib/format";
import type { KycAnswers, KycQuestion, KycQuestionnaire as Q, Vigilance } from "../types";

export const VIGILANCE: Record<Vigilance, { label: string; cls: string }> = {
  simplified: {
    label: "Simplified",
    cls: "bg-[#ecfdf3] text-[#067647] ring-[#abefc6] dark:bg-[#053321]/60 dark:text-[#47cd89] dark:ring-[#085d3a]",
  },
  standard: {
    label: "Standard",
    cls: "bg-[#eff8ff] text-[#175cd3] ring-[#b2ddff] dark:bg-[#102a56]/60 dark:text-[#84caff] dark:ring-[#1849a9]",
  },
  enhanced: {
    label: "Enhanced",
    cls: "bg-[#fef3f2] text-[#b42318] ring-[#fecdca] dark:bg-[#55160c]/60 dark:text-[#fda29b] dark:ring-[#912018]",
  },
};

export function VigilanceBadge({ level, small }: { level: Vigilance; small?: boolean }) {
  const v = VIGILANCE[level];
  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold tracking-wide uppercase ring-1 ring-inset ${v.cls} ${
        small ? "px-2 py-0.5 text-[10px]" : "px-3 py-1 text-xs"
      }`}
    >
      {v.label}
    </span>
  );
}

function Countries({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState("");
  const add = () => {
    const codes = text
      .split(/[\s,;]+/)
      .map((c) => c.trim().toUpperCase())
      .filter((c) => /^[A-Z]{2}$/.test(c));
    if (codes.length) onChange([...new Set([...value, ...codes])].sort());
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {value.map((c) => (
        <span key={c} className="chip py-0.5 pr-1.5 pl-2.5 text-xs">
          {flag(c)} {countryName(c)}
          <button className="rounded-full p-0.5 hover:bg-black/10 dark:hover:bg-white/10" onClick={() => onChange(value.filter((x) => x !== c))} aria-label={`Remove ${c}`}>
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        className="input w-36 py-1 text-xs"
        placeholder="Add: FR, CH, AE…"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
      />
    </div>
  );
}

function Question({
  q,
  value,
  suggested,
  onChange,
}: {
  q: KycQuestion;
  value: string | string[] | undefined;
  suggested: boolean;
  onChange: (v: string | string[]) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-2 text-[13px] font-medium">
        {q.label}
        {suggested && (
          <span className="inline-flex items-center gap-1 rounded-full bg-brand-500/10 px-2 py-0.5 text-[10px] font-semibold text-brand-700 dark:text-brand-400">
            <Sparkles className="h-3 w-3" /> from the screening — confirm
          </span>
        )}
      </div>
      {q.help && <p className="text-[11px] text-slate-500">{q.help}</p>}
      {q.type === "choice" && (
        <div className="flex flex-wrap gap-1.5">
          {q.options!.map((o) => {
            const on = value === o.value;
            return (
              <button
                key={o.value}
                type="button"
                onClick={() => onChange(o.value)}
                className={`rounded-xl border px-3 py-1.5 text-left text-xs transition-colors ${
                  on
                    ? "border-brand-500 bg-brand-500/10 font-semibold text-slate-900 dark:text-white"
                    : "border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-white/10 dark:text-slate-300 dark:hover:bg-white/[0.04]"
                }`}
              >
                {on && <Check className="mr-1 inline h-3 w-3 text-brand-600" />}
                {o.label}
              </button>
            );
          })}
        </div>
      )}
      {q.type === "text" && (
        <textarea
          className="input h-16 w-full resize-y text-sm"
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {q.type === "countries" && <Countries value={(value as string[]) ?? []} onChange={onChange} />}
    </div>
  );
}

interface Props {
  caseId: string;
  data: Q;
}

/** KYC / AML-CFT questionnaire of a case: client-risk answers → vigilance level and measures. */
export default function KycQuestionnaire({ caseId, data }: Props) {
  const qc = useQueryClient();
  const answered = Object.keys(data.answers).length > 0;
  const [open, setOpen] = useState(!answered);
  // Unanswered questions start from what the screening already shows.
  const [answers, setAnswers] = useState<KycAnswers>({ ...data.suggested, ...data.answers });
  const [author, setAuthor] = useState(data.author);
  const [dirty, setDirty] = useState(false);
  const save = useMutation({
    mutationFn: () => api.saveQuestionnaire(caseId, answers, author),
    onSuccess: () => {
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
  const sections = useMemo(() => {
    const out: [string, KycQuestion[]][] = [];
    for (const q of data.form) {
      const last = out[out.length - 1];
      if (last && last[0] === q.section) last[1].push(q);
      else out.push([q.section, [q]]);
    }
    return out;
  }, [data.form]);
  const a = save.data?.assessment ?? data.assessment;
  const scored = data.form.filter((q) => q.type !== "text");
  const done = scored.filter((q) => {
    const v = answers[q.id];
    return Array.isArray(v) ? v.length > 0 : !!v;
  }).length;

  return (
    <div className="card overflow-hidden">
      <button className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        <ClipboardCheck className="h-5 w-5 text-brand-600" />
        <div className="min-w-0 flex-1">
          <div className="tag">KYC / AML-CFT questionnaire</div>
          <div className="text-[12px] text-slate-500">
            {a && !dirty
              ? `Answered ${data.answered_at ? fmtDate(data.answered_at) : ""}${data.author ? ` by ${data.author}` : ""} · next review by ${fmtDate(a.next_review)}`
              : `Client risk questions (LCB-FT) · ${done}/${scored.length} answered`}
          </div>
        </div>
        {a ? (
          <span className="flex items-center gap-2 text-xs text-slate-500">
            Vigilance <VigilanceBadge level={a.level} />
          </span>
        ) : (
          <span className="text-xs font-medium text-amber-600">Not completed</span>
        )}
      </button>

      {open && (
        <div className="grid gap-5 border-t border-slate-200 p-4 lg:grid-cols-[minmax(0,1fr)_320px] dark:border-slate-800">
          <div className="space-y-5">
            {sections.map(([section, qs]) => (
              <fieldset key={section} className="space-y-3">
                <legend className="label mb-2">{section}</legend>
                {qs.map((q) => (
                  <Question
                    key={q.id}
                    q={q}
                    value={answers[q.id]}
                    suggested={q.id in data.suggested && !(q.id in data.answers) && answers[q.id] === data.suggested[q.id]}
                    onChange={(v) => {
                      setAnswers((s) => ({ ...s, [q.id]: v }));
                      setDirty(true);
                    }}
                  />
                ))}
              </fieldset>
            ))}
          </div>

          <aside className="space-y-3 lg:sticky lg:top-20 lg:self-start">
            <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
              <div className="label mb-2">Vigilance level</div>
              {a ? (
                <>
                  <div className="flex items-center gap-3">
                    <VigilanceBadge level={a.level} />
                    <span className="text-xs text-slate-500">{a.points} risk points</span>
                  </div>
                  <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
                    <CalendarClock className="h-3.5 w-3.5" /> Review every {a.review_months} months · next by {fmtDate(a.next_review)}
                  </div>
                  {dirty && <p className="mt-2 text-[11px] text-amber-600">Answers changed: save to update the level.</p>}
                  {a.triggers.length > 0 && (
                    <div className="mt-3">
                      <div className="text-[11px] font-semibold text-slate-500">Enhanced because</div>
                      <ul className="mt-1 space-y-0.5 text-xs">
                        {a.triggers.map((t) => (
                          <li key={t} className="text-[#b42318] dark:text-[#fda29b]">
                            • {t}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="mt-3">
                    <div className="text-[11px] font-semibold text-slate-500">Measures required</div>
                    <ul className="mt-1 space-y-1 text-xs leading-snug">
                      {a.measures.map((m) => (
                        <li key={m} className="flex gap-1.5">
                          <Check className="mt-0.5 h-3 w-3 shrink-0 text-brand-600" /> {m}
                        </li>
                      ))}
                    </ul>
                  </div>
                  {a.reasons.length > 0 && (
                    <details className="mt-3 text-xs">
                      <summary className="cursor-pointer text-[11px] font-semibold text-slate-500">What drives the level</summary>
                      <ul className="mt-1 space-y-0.5">
                        {a.reasons.map((r, i) => (
                          <li key={i} className="flex justify-between gap-2">
                            <span>
                              <b>{r.item}</b> — {r.detail}
                            </span>
                            {r.points > 0 && <span className="font-mono text-slate-500">+{r.points}</span>}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {a.missing.length > 0 && <p className="mt-2 text-[11px] text-amber-600">Unanswered: {a.missing.join(", ")}.</p>}
                </>
              ) : (
                <p className="text-xs text-slate-500">
                  Answer the questions and save: the level combines your answers with the automatic screening of the case.
                </p>
              )}
            </div>
            <input className="input w-full text-sm" placeholder="Analyst name (audit trail)" value={author} onChange={(e) => { setAuthor(e.target.value); setDirty(true); }} />
            <button className="btn-primary w-full justify-center" disabled={save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save and assess
            </button>
            {save.error && <p className="text-xs text-red-600">{(save.error as Error).message}</p>}
            <p className="text-[10px] leading-snug text-slate-500">
              Client risk factors of the EU AML directives and of the French Monetary and Financial Code (art. L561-4-1 to
              L561-10-2). Printed in the PDF report of the case.
            </p>
          </aside>
        </div>
      )}
    </div>
  );
}
