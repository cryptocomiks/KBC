import { useCallback, useEffect, useState } from "react";

const KEY = "kbc-tour";
const STEPS = [
  { target: "#q", title: "Start with a name", text: "A company, a person, an identifier (SIREN, LEI, CHE-UID, UK number) or a crypto address." },
  { target: '[data-tour="film"]', title: "90 seconds to see it", text: "The film shows a full case: search, network, red flags, KYC file and report." },
  { target: '[data-tour="cases"]', title: "Your clients", text: "Save an investigation as a case: questionnaire, documents, four-eyes validation and daily monitoring." },
  { target: '[data-tour="palette"]', title: "Anywhere, anytime", text: "⌘K / Ctrl K opens any case or starts a new search." },
];

function seen(): boolean {
  try {
    return localStorage.getItem(KEY) === "done";
  } catch {
    return true;
  }
}

/** A four-step guided tour on the first visit: a spotlight on each element with a short note. */
export default function Tour() {
  const [step, setStep] = useState<number | null>(null);
  const [box, setBox] = useState<DOMRect | null>(null);

  useEffect(() => {
    if (seen()) return;
    const t = setTimeout(() => setStep(0), 1400);
    return () => clearTimeout(t);
  }, []);

  const finish = useCallback(() => {
    setStep(null);
    try {
      localStorage.setItem(KEY, "done");
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    if (step === null) return;
    const el = document.querySelector<HTMLElement>(STEPS[step].target);
    if (!el) {
      if (step < STEPS.length - 1) setStep(step + 1);
      else finish();
      return;
    }
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    const measure = () => setBox(el.getBoundingClientRect());
    const t = setTimeout(measure, 350);
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, { passive: true });
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && finish();
    window.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure);
      window.removeEventListener("keydown", onKey);
    };
  }, [step, finish]);

  if (step === null || !box) return null;
  const s = STEPS[step];
  const pad = 8;
  const below = box.bottom + 190 < window.innerHeight;
  const left = Math.min(Math.max(16, box.left + box.width / 2 - 170), window.innerWidth - 356);
  return (
    <div className="fixed inset-0 z-[70]" role="dialog" aria-label={s.title} onClick={finish}>
      <div
        className="tour-ring pointer-events-none fixed rounded-2xl"
        style={{ top: box.top - pad, left: box.left - pad, width: box.width + pad * 2, height: box.height + pad * 2 }}
      />
      <div
        key={step}
        className="tour-card glass-panel fixed w-[340px] max-w-[calc(100vw-32px)] rounded-2xl p-5"
        style={below ? { top: box.bottom + pad + 12, left } : { top: Math.max(16, box.top - pad - 180), left }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-[12px] font-medium text-slate-500">
          {step + 1} of {STEPS.length}
        </div>
        <div className="mt-1 text-[17px] font-semibold tracking-[-0.02em]">{s.title}</div>
        <p className="mt-1 text-[14px] leading-relaxed text-slate-600 dark:text-slate-300">{s.text}</p>
        <div className="mt-4 flex items-center justify-between">
          <button className="text-[13px] text-slate-500 hover:text-slate-800 dark:hover:text-slate-200" onClick={finish}>
            Skip
          </button>
          <div className="flex items-center gap-3">
            <div className="flex gap-1" aria-hidden>
              {STEPS.map((_, i) => (
                <span key={i} className={`h-1.5 rounded-full transition-all ${i === step ? "w-4 bg-brand-500" : "w-1.5 bg-slate-300 dark:bg-slate-600"}`} />
              ))}
            </div>
            <button className="btn-primary !py-1.5" onClick={() => (step < STEPS.length - 1 ? setStep(step + 1) : finish())}>
              {step < STEPS.length - 1 ? "Next" : "Done"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
