import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, AtSign, Bitcoin, CheckCircle2, CircleHelp, Globe, Info, Landmark, Loader2, ShieldAlert } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { api } from "../api";
import type { CheckBlock, CheckStatus, QuickCheckRequest } from "../types";

const STATUS: Record<CheckStatus, { label: string; cls: string; Icon: typeof Info }> = {
  alert: { label: "Alert", cls: "text-red-600 dark:text-red-400", Icon: ShieldAlert },
  warn: { label: "To check", cls: "text-amber-600 dark:text-amber-400", Icon: AlertTriangle },
  unknown: { label: "Unknown", cls: "text-slate-500", Icon: CircleHelp },
  info: { label: "Info", cls: "text-sky-600 dark:text-sky-400", Icon: Info },
  ok: { label: "OK", cls: "text-emerald-600 dark:text-emerald-400", Icon: CheckCircle2 },
};
const ORDER: CheckStatus[] = ["alert", "warn", "unknown", "info", "ok"];

const FIELDS: { key: keyof QuickCheckRequest; label: string; placeholder: string; Icon: typeof Info; hint: string }[] = [
  { key: "iban", label: "IBAN", placeholder: "CH93 0076 2011 6238 5295 7", Icon: Landmark, hint: "Check digits, country risk, Swiss / Liechtenstein bank (SIX)" },
  { key: "email", label: "E-mail", placeholder: "ceo@company.com", Icon: AtSign, hint: "Mail server, SPF / DMARC, domain age, free or disposable mailbox, scam lists" },
  { key: "website", label: "Website", placeholder: "company.com", Icon: Globe, hint: "Domain age, resemblance to the name, phishing / scam lists" },
  { key: "wallet", label: "Crypto address", placeholder: "0x… / bc1… / T…", Icon: Bitcoin, hint: "Sanctions (OFAC, UN, NBCTF, FBI), ransomware and scam addresses" },
];

/** Quick checks on the details the client gave: nothing is stored, every line cites its source. */
export default function QuickChecks({ company, country }: { company?: string; country?: string }) {
  const [form, setForm] = useState<QuickCheckRequest>({});
  const run = useMutation({ mutationFn: (body: QuickCheckRequest) => api.checks(body) });
  const filled = FIELDS.some((f) => (form[f.key] ?? "").trim());

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!filled) return;
    run.mutate({ ...form, company, client_country: country });
  };

  return (
    <div className="panel-enter space-y-4">
      <form onSubmit={submit} className="glass rounded-[22px] p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <div className="tag">Quick checks</div>
            <h2 className="mt-1 text-lg font-semibold tracking-tight">Payment and contact details given by the client</h2>
          </div>
          <p className="max-w-md text-xs text-slate-500">Checked live against public sources. Nothing is stored: copy the result into the file if needed.</p>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {FIELDS.map((f) => (
            <label key={f.key} className="block">
              <span className="label flex items-center gap-1.5">
                <f.Icon className="h-3.5 w-3.5" /> {f.label}
              </span>
              <input
                className="input mt-1 w-full font-mono text-[13px]"
                placeholder={f.placeholder}
                value={form[f.key] ?? ""}
                onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
                autoComplete="off"
                spellCheck={false}
              />
              <span className="mt-1 block text-[11px] text-slate-500">{f.hint}</span>
            </label>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button className="btn-primary" disabled={!filled || run.isPending}>
            {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldAlert className="h-4 w-4" />} Run the checks
          </button>
          {company && <span className="text-xs text-slate-500">Domains are compared with “{company}”.</span>}
          {run.error && <span className="text-sm text-red-600">{(run.error as Error).message}</span>}
        </div>
      </form>

      {run.data && (
        <div className="space-y-3">
          <Verdict status={run.data.verdict} />
          <div className="grid gap-3 lg:grid-cols-2">
            {run.data.iban && (
              <Result title="IBAN" Icon={Landmark} block={run.data.iban}>
                {run.data.iban.normalized && <span className="font-mono">{run.data.iban.normalized}</span>}
                {run.data.iban.country && <span> · {run.data.iban.country.name}</span>}
              </Result>
            )}
            {run.data.email && <Result title="E-mail" Icon={AtSign} block={run.data.email} />}
            {run.data.website && <Result title="Website" Icon={Globe} block={run.data.website} />}
            {run.data.wallet && <Result title="Crypto address" Icon={Bitcoin} block={run.data.wallet} />}
          </div>
        </div>
      )}
    </div>
  );
}

function Verdict({ status }: { status: CheckStatus }) {
  const s = STATUS[status];
  const text = {
    alert: "At least one alert: do not proceed before it is cleared.",
    warn: "Points to clarify with the client.",
    unknown: "Some sources could not be reached: re-run or check manually.",
    info: "No alert. Information only.",
    ok: "Nothing found.",
  }[status];
  return (
    <div className={`glass flex items-center gap-3 rounded-2xl px-4 py-3 ${s.cls}`}>
      <s.Icon className="h-5 w-5 shrink-0" />
      <span className="font-semibold">{s.label}</span>
      <span className="text-sm text-slate-600 dark:text-slate-300">{text}</span>
    </div>
  );
}

function Result({ title, Icon, block, children }: { title: string; Icon: typeof Info; block: CheckBlock; children?: ReactNode }) {
  const lines = [...block.checks].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  return (
    <section className="card p-4">
      <header className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-brand-600 dark:text-brand-500" />
        <h3 className="font-semibold">{title}</h3>
        <span className="min-w-0 truncate font-mono text-xs text-slate-500">{block.domain ?? block.chain ?? ""}</span>
      </header>
      {children && <div className="mt-1 text-xs text-slate-500">{children}</div>}
      {block.bank && (
        <div className="mt-2 rounded-xl bg-slate-100 px-3 py-2 text-sm dark:bg-white/[0.04]">
          <span className="font-medium">{block.bank.name}</span>
          <span className="text-slate-500"> · {block.bank.town}{block.bank.bic ? ` · BIC ${block.bank.bic}` : ""}</span>
        </div>
      )}
      <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
        {lines.map((c, i) => {
          const s = STATUS[c.status];
          return (
            <li key={i} className="flex items-start gap-2.5 py-2 text-sm">
              <s.Icon className={`mt-0.5 h-4 w-4 shrink-0 ${s.cls}`} aria-label={s.label} />
              <div className="min-w-0">
                <span className="font-medium">{c.label}</span>
                <span className="text-slate-600 dark:text-slate-300">: {c.detail}</span>
                {c.source && <div className="text-[11px] text-slate-500">Source: {c.source}</div>}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
