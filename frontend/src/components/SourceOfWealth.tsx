import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Copy, Coins, Landmark, Loader2, Mail, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { documentRequest, openEmail } from "../lib/email";
import { fmtDate } from "../lib/format";
import type { SowData, SowSourceIn } from "../types";
import { ChartCard, StackedBar, Tile, compact, series } from "./viz";

const VERDICT = {
  plausible: { label: "Plausible", bar: "bg-brand-500", text: "text-brand-700 dark:text-brand-400" },
  partial: { label: "Partially explained", bar: "bg-amber-500", text: "text-amber-700 dark:text-amber-300" },
  gap: { label: "Unexplained gap", bar: "bg-red-500", text: "text-red-700 dark:text-red-300" },
  incomplete: { label: "Incomplete", bar: "bg-slate-400", text: "text-slate-500" },
} as const;
const SEV = { critical: "text-red-700 dark:text-red-300", warning: "text-amber-800 dark:text-amber-200", info: "text-sky-800 dark:text-sky-200" } as Record<string, string>;
const money = (v: number | null | undefined, cur: string) => `${cur} ${Math.round(v ?? 0).toLocaleString("de-CH")}`;
const blank = (i: number): SowSourceIn => ({ id: `s${Date.now()}${i}`, type: "employment", description: "", amount: 0, annual: 0, year_from: null, year_to: null, rate: null, country: "", received: [] });
const pick = (s: SowSourceIn): SowSourceIn => ({
  id: s.id, type: s.type, description: s.description, amount: s.amount, annual: s.annual, year_from: s.year_from,
  year_to: s.year_to, rate: s.rate, country: s.country, received: s.received,
}); // fmt: skip
const compactMoney = (v: number | null | undefined) => compact(Math.round(v ?? 0));
const num = (v: string) => (v === "" ? 0 : Number(v.replace(/['\s,]/g, "")) || 0);
const yr = (v: string) => (v ? Number(v) || null : null);

/** Source of wealth: declared sources → plausibility, public corroboration, documents, narrative. */
export default function SourceOfWealth({ caseId, subjectName }: { caseId: string; subjectName?: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["sow", caseId], queryFn: () => api.sow(caseId) });
  const [form, setForm] = useState<{ person_id: string; currency: string; declared_total: number; sources: SowSourceIn[]; notes: string } | null>(null);
  const [name, setName] = useState(analyst.get());
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (q.data && !form)
      setForm({ person_id: q.data.person_id, currency: q.data.currency, declared_total: q.data.declared_total, sources: q.data.sources.map(pick), notes: q.data.notes });
  }, [q.data, form]);
  const save = useMutation({
    mutationFn: (f: NonNullable<typeof form>) => api.saveSow(caseId, f, name),
    onSuccess: (d: SowData) => {
      analyst.set(name);
      qc.setQueryData(["sow", caseId], d);
      qc.invalidateQueries({ queryKey: ["review", caseId] });
    },
  });
  if (q.isLoading || !q.data || !form) return <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>;
  const a = q.data;
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  const setSrc = (i: number, patch: Partial<SowSourceIn>) => set({ sources: form.sources.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const toggleDoc = (id: string, label: string) => {
    const next = {
      ...form,
      sources: form.sources.map((s) => (s.id === id ? { ...s, received: s.received.includes(label) ? s.received.filter((x) => x !== label) : [...s.received, label] } : s)),
    };
    setForm(next);
    if (name.trim()) save.mutate(next);
  };
  const v = VERDICT[a.verdict];
  const pct = Math.min(100, Math.round((a.coverage ?? 0) * 100));

  return (
    <div className="panel-enter grid gap-4 xl:grid-cols-[1.1fr_1fr]">
      {/* Declaration */}
      <div className="card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Coins className="h-5 w-5 text-brand-600" />
          <span className="tag">Declared by the client</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-[1fr_90px_160px]">
          <label className="block text-[11px] text-slate-500">
            Whose wealth
            <select className="input w-full mt-0.5 text-sm" value={form.person_id} onChange={(e) => set({ person_id: e.target.value })}>
              {a.people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} — {p.why}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-slate-500">
            Currency
            <select className="input w-full mt-0.5 text-sm" value={form.currency} onChange={(e) => set({ currency: e.target.value })}>
              {["CHF", "EUR", "USD", "GBP"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="block text-[11px] text-slate-500">
            Total wealth declared
            <input className="input w-full mt-0.5 text-sm" inputMode="numeric" value={form.declared_total || ""} onChange={(e) => set({ declared_total: num(e.target.value) })} />
          </label>
        </div>
        <h4 className="mt-4 mb-2 text-[12px] font-semibold">How it was built</h4>
        <div className="space-y-2">
          {form.sources.map((s, i) => {
            const annual = a.types[s.type]?.mode === "annual";
            return (
              <div key={s.id} className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
                <div className="flex gap-2">
                  <select className="input w-full py-1 text-[13px]" value={s.type} onChange={(e) => setSrc(i, { type: e.target.value })}>
                    {Object.entries(a.types).map(([k, t]) => (
                      <option key={k} value={k}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  <button className="btn-ghost px-2 text-slate-400 hover:text-red-600" aria-label="Remove" onClick={() => set({ sources: form.sources.filter((_, j) => j !== i) })}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <input className="input w-full mt-2 py-1 text-[13px]" placeholder="Description (employer, company sold, deceased, property...)" value={s.description} onChange={(e) => setSrc(i, { description: e.target.value })} />
                <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {annual ? (
                    <input className="input w-full py-1 text-[13px] sm:col-span-2" inputMode="numeric" placeholder="Net amount per year" value={s.annual || ""} onChange={(e) => setSrc(i, { annual: num(e.target.value) })} />
                  ) : (
                    <input className="input w-full py-1 text-[13px] sm:col-span-2" inputMode="numeric" placeholder="Amount received" value={s.amount || ""} onChange={(e) => setSrc(i, { amount: num(e.target.value) })} />
                  )}
                  <input className="input w-full py-1 text-[13px]" placeholder={annual ? "From (year)" : "Year"} value={s.year_from ?? ""} onChange={(e) => setSrc(i, { year_from: yr(e.target.value) })} />
                  {annual && <input className="input w-full py-1 text-[13px]" placeholder="To (year)" value={s.year_to ?? ""} onChange={(e) => setSrc(i, { year_to: yr(e.target.value) })} />}
                  <input className="input w-full py-1 text-[13px]" placeholder="Country (ISO)" maxLength={2} value={s.country} onChange={(e) => setSrc(i, { country: e.target.value.toUpperCase() })} />
                  {annual && (
                    <label className="col-span-2 flex items-center gap-2 text-[11px] text-slate-500 sm:col-span-5">
                      Share retained (saved)
                      <input
                        className="input w-20 py-1 text-[13px]"
                        placeholder={`${Math.round((a.types[s.type]?.rate ?? 0.3) * 100)} %`}
                        value={s.rate == null ? "" : Math.round(s.rate * 100)}
                        onChange={(e) => setSrc(i, { rate: e.target.value === "" ? null : Math.min(100, Number(e.target.value) || 0) / 100 })}
                      />
                      <span>% — a salary is not saved in full (taxes, living costs)</span>
                    </label>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        <button className="btn-outline mt-2 py-1 text-xs" onClick={() => set({ sources: [...form.sources, blank(form.sources.length)] })}>
          <Plus className="h-3.5 w-3.5" /> Add a source
        </button>
        <textarea className="input w-full mt-3 h-16 text-[13px]" placeholder="Notes (interview, context)" value={form.notes} onChange={(e) => set({ notes: e.target.value })} />
        <div className="mt-3 flex items-center gap-2">
          <input className="input w-40 py-1 text-xs" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn-primary" disabled={save.isPending || !name.trim()} onClick={() => save.mutate(form)}>
            {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save & assess
          </button>
          {a.by && <span className="text-[11px] text-slate-500">Saved by {a.by}, {fmtDate(a.at)}</span>}
        </div>
        {save.error && <p className="mt-2 text-xs text-red-600">{(save.error as Error).message}</p>}
      </div>

      {/* Assessment */}
      <div className="space-y-4">
        <ChartCard
          title="Plausibility"
          sub={a.verdict_text}
          action={<span className={`text-sm font-semibold ${v.text}`}>{v.label}</span>}
          table={{
            head: ["Source", "Explained", "Share of declared"],
            rows: [
              ...a.sources.map((x) => [x.label, money(x.explained, a.currency), a.declared_total ? `${Math.round((100 * x.explained) / a.declared_total)} %` : "—"]),
              ["Unexplained gap", a.gap == null ? "—" : money(a.gap, a.currency), a.declared_total && a.gap != null ? `${Math.round((100 * a.gap) / a.declared_total)} %` : "—"],
            ],
          }}
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Tile label="Declared" value={compactMoney(a.declared_total)} sub={a.currency} />
            <Tile label="Explained" tone="accent" value={compactMoney(a.explained_total)} sub={a.coverage != null ? `${pct}% of declared` : a.currency} />
            <Tile label="Unexplained" tone={a.gap ? (a.verdict === "gap" ? "critical" : "warning") : "good"} value={a.gap == null ? "—" : compactMoney(a.gap)} sub={a.currency} />
            <Tile
              label="Corroborated"
              tone={a.sources.every((x) => x.corroborated) ? "good" : "warning"}
              value={`${a.sources.filter((x) => x.corroborated).length}/${a.sources.length}`}
              sub="sources with evidence"
            />
          </div>
          {a.sources.length > 0 && (
            <div className="mt-4">
              <StackedBar
                height={14}
                format={(n) => money(n, a.currency)}
                segments={a.sources.map((x, i) => ({ key: x.id, label: x.label, value: x.explained, color: series(i) }))}
                rest={a.gap ? { label: "Unexplained gap", value: a.gap } : undefined}
              />
            </div>
          )}
          {a.flags.map((f) => (
            <p key={f.text} className={`mt-2 flex gap-2 text-[12px] ${SEV[f.severity] ?? ""}`}>
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {f.text}
            </p>
          ))}
        </ChartCard>

        {a.sources.length > 0 && (
          <div className="card p-4">
            <span className="tag">Evidence per source</span>
            <ul className="mt-3 space-y-3">
              {a.sources.map((s) => (
                <li key={s.id} className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
                  <div className="flex items-center gap-2 text-[13px] font-semibold">
                    {s.label}
                    <span className="ml-auto font-mono text-xs">{money(s.explained, a.currency)}</span>
                  </div>
                  <div className="text-[11px] text-slate-500">{s.how}</div>
                  {s.public.map((p) => (
                    <p key={p} className="mt-1 flex gap-1.5 text-[12px] text-brand-700 dark:text-brand-400">
                      <Landmark className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {p}
                    </p>
                  ))}
                  {!s.public.length && <p className="mt-1 text-[12px] text-slate-500">No trace in the public registers: documents needed.</p>}
                  <div className="mt-2 space-y-1">
                    {s.documents.map((d) => (
                      <label key={d.label} className="flex items-center gap-2 text-[12px]">
                        <input type="checkbox" className="accent-brand-600" checked={d.received} onChange={() => toggleDoc(s.id, d.label)} />
                        <span className={d.received ? "" : "text-slate-500"}>{d.label}</span>
                      </label>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
            {a.to_request.length > 0 && (
              <button
                className="btn-outline mt-3 py-1.5 text-xs"
                onClick={() => {
                  const r = documentRequest(subjectName, a.to_request);
                  openEmail(r.subject.replace("Documents required", "Source of wealth — documents required"), r.body);
                }}
              >
                <Mail className="h-3.5 w-3.5" /> Ask the client for {a.to_request.length} document(s)
              </button>
            )}
          </div>
        )}

        <div className="card p-4">
          <div className="flex items-center gap-2">
            <span className="tag">Narrative for the file</span>
            <button
              className="btn-ghost ml-auto py-1 text-xs"
              onClick={() => {
                navigator.clipboard?.writeText(a.narrative);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} Copy
            </button>
          </div>
          <p className="mt-2 text-[13px] leading-relaxed">{a.narrative}</p>
          <p className="mt-2 text-[11px] text-slate-500">Also added to the decision memo when regenerated.</p>
        </div>

        {a.roles.length > 0 && (
          <details className="card p-4">
            <summary className="cursor-pointer text-[13px] font-semibold">
              Public record of {a.person} <span className="font-mono text-xs text-slate-400">{a.roles.length}</span>
            </summary>
            <ul className="mt-2 space-y-1 text-[12px]">
              {a.roles.map((r, i) => (
                <li key={i} className="text-slate-600 dark:text-slate-400">
                  <b className="text-slate-800 dark:text-slate-200">{r.company}</b> — {r.role}
                  {r.share_pct != null && ` ${r.share_pct} %`} · {(r.start ?? "?").slice(0, 4)}–{r.end ? r.end.slice(0, 4) : r.dissolved ? `${r.dissolved.slice(0, 4)} (dissolved)` : "today"}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
