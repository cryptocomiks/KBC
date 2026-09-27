import { AlertTriangle, ArrowDownLeft, ArrowUpRight, Check, ChevronDown, Copy, FileSpreadsheet, Loader2, ShieldCheck, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../api";
import { toast } from "../lib/toast";
import type { StatementAnalysis, StatementAlert } from "../types";
import { RefChips } from "./LegalBasis";
import { compact, Tile } from "./viz";

const SEV: Record<string, { label: string; tone: string; dot: string }> = {
  critical: { label: "Critical", tone: "bg-[#d70015] text-white", dot: "bg-[#d70015]" },
  high: { label: "High", tone: "bg-[#d70015]/10 text-[#d70015] dark:text-[#ff453a]", dot: "bg-[#ff3b30]" },
  medium: { label: "Medium", tone: "bg-amber-500/15 text-amber-800 dark:text-amber-300", dot: "bg-amber-500" },
  low: { label: "Low", tone: "bg-slate-500/10 text-slate-600 dark:text-slate-300", dot: "bg-slate-400" },
};

const money = (v: number, ccy?: string | null) => `${v.toLocaleString("de-CH", { maximumFractionDigits: 0 })}${ccy ? ` ${ccy}` : ""}`;

export interface StatementProfile {
  country?: string;
  volume?: string;
  cash?: string;
}

/** Drop a bank statement (CSV / Excel): red flags in seconds, nothing stored. */
export default function TransactionAnalysis({ profile, subjectName }: { profile?: StatementProfile; subjectName?: string }) {
  const [result, setResult] = useState<StatementAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [threshold, setThreshold] = useState<string>("");
  const input = useRef<HTMLInputElement>(null);

  const run = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.analyzeStatement(file, { ...profile, threshold: threshold ? Number(threshold) : undefined }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const sample = async () => {
    const blob = await (await fetch("/media/sample-statement.csv")).blob();
    await run(new File([blob], "sample-statement.csv", { type: "text/csv" }));
  };

  return (
    <div className="panel-enter space-y-4">
      <section className="card p-5">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="flex items-center gap-2 text-[19px] font-semibold tracking-[-0.02em]">
              <FileSpreadsheet className="h-5 w-5 text-brand-500" /> Bank statement analysis
            </h2>
            <p className="mt-1 max-w-2xl text-[13px] text-slate-500">
              CSV or Excel export from any bank (English, French, German, Italian headers; Swiss, French and German number formats). The file is analysed in memory
              and never stored. Counterparties are screened against the enabled sanctions and watchlists.
            </p>
            {profile && (profile.volume || profile.cash) && (
              <p className="mt-1 text-[12px] text-slate-500">
                Compared with the KYC profile{subjectName ? ` of ${subjectName}` : ""}: {profile.volume ? `expected volume ${profile.volume.replace("_", "–")}` : ""}
                {profile.volume && profile.cash ? " · " : ""}
                {profile.cash ? `cash ${profile.cash}` : ""}
              </p>
            )}
          </div>
          <label className="text-[12px] text-slate-500">
            Threshold
            <input
              value={threshold}
              onChange={(e) => setThreshold(e.target.value.replace(/[^\d]/g, ""))}
              placeholder={profile?.country === "CH" ? "15000" : "10000"}
              className="input mt-1 block h-8 w-28 text-[13px]"
              inputMode="numeric"
              aria-label="Identification threshold"
            />
          </label>
        </div>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            const f = e.dataTransfer.files[0];
            if (f) void run(f);
          }}
          className={`mt-4 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-8 text-center transition-colors ${
            over ? "border-brand-500 bg-brand-500/5" : "border-slate-300 dark:border-white/15"
          }`}
        >
          {busy ? (
            <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              <Loader2 className="h-4 w-4 animate-spin" /> Analysing and screening the counterparties…
            </div>
          ) : (
            <>
              <Upload className="h-6 w-6 text-slate-400" />
              <p className="mt-2 text-sm">
                Drop a statement here, or{" "}
                <button onClick={() => input.current?.click()} className="font-medium text-brand-600 hover:underline">
                  choose a file
                </button>
              </p>
              <p className="mt-1 text-[12px] text-slate-500">
                .csv, .xlsx — 5 MB max ·{" "}
                <button onClick={sample} className="text-brand-600 hover:underline">
                  try with a sample statement
                </button>
              </p>
            </>
          )}
          <input
            ref={input}
            type="file"
            accept=".csv,.txt,.xlsx,.xlsm"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void run(f);
              e.target.value = "";
            }}
          />
        </div>
        {error && <p className="mt-3 text-sm text-[#d70015]">{error}</p>}
      </section>

      {result && <Results r={result} subjectName={subjectName} />}
    </div>
  );
}

function Results({ r, subjectName }: { r: StatementAnalysis; subjectName?: string }) {
  const s = r.summary;
  const ccy = s.currency;
  const [only, setOnly] = useState<string | null>(null);
  const flaggedRows = new Set(r.alerts.filter((a) => !only || a.rule + a.title === only).flatMap((a) => a.rows));
  const rows = r.transactions.filter((t) => (only ? flaggedRows.has(t.idx) : t.flags.length > 0));
  const worst = r.alerts[0]?.severity;
  const copy = async () => {
    const text = [
      `Statement analysis${subjectName ? ` — ${subjectName}` : ""} (${s.period_from} to ${s.period_to}, ${s.transactions} transactions, ${ccy ?? ""})`,
      `Inflows ${money(s.inflow, ccy)} · outflows ${money(s.outflow, ccy)} · annualised inflows ${money(s.annualised_inflow, ccy)}`,
      ...r.alerts.map((a) => `- [${a.severity.toUpperCase()}] ${a.title}. ${a.detail}`),
    ].join("\n");
    await navigator.clipboard?.writeText(text).catch(() => undefined);
    toast("Findings copied");
  };
  const max = Math.max(1, ...r.monthly.map((m) => Math.max(m.in, m.out)));

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Transactions" value={s.transactions} sub={`${s.period_from} → ${s.period_to}`} />
        <Tile label="Inflows" value={compact(s.inflow)} sub={`${s.count_in} credits · ${ccy ?? ""}`} icon={<ArrowDownLeft className="h-3 w-3" />} />
        <Tile label="Outflows" value={compact(s.outflow)} sub={`${s.count_out} debits · ${ccy ?? ""}`} icon={<ArrowUpRight className="h-3 w-3" />} />
        <Tile
          label="Red flags"
          value={r.alerts.length}
          sub={`${s.flagged_transactions} transactions flagged · ${s.screened} counterparties screened`}
          tone={worst === "critical" || worst === "high" ? "critical" : worst ? "warning" : "good"}
        />
      </div>

      {r.warnings.length > 0 && (
        <div className="rounded-2xl bg-amber-50 px-5 py-3 text-[13px] text-amber-900 dark:bg-amber-400/10 dark:text-amber-200">
          {r.warnings.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </div>
      )}

      <section className="card overflow-hidden">
        <header className="flex flex-wrap items-center gap-2 px-5 pt-5">
          <h2 className="mr-auto text-[19px] font-semibold tracking-[-0.02em]">Red flags</h2>
          {r.alerts.length > 0 && (
            <button onClick={copy} className="btn-outline h-8 text-xs">
              <Copy className="h-3.5 w-3.5" /> Copy for the file
            </button>
          )}
        </header>
        {r.alerts.length === 0 ? (
          <p className="flex items-center gap-2 px-5 py-4 text-sm text-slate-500">
            <ShieldCheck className="h-4 w-4 text-[#248a3d]" /> No red flag on these transactions with the current rules.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-200/70 dark:divide-white/[0.06]">
            {r.alerts.map((a) => (
              <AlertRow key={a.rule + a.title} a={a} ccy={ccy} active={only === a.rule + a.title} onShow={() => setOnly(only === a.rule + a.title ? null : a.rule + a.title)} />
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card p-5">
          <h3 className="text-[15px] font-semibold">Monthly flows</h3>
          <div className="mt-3 space-y-1.5">
            {r.monthly.map((m) => (
              <div key={m.month} className="grid grid-cols-[64px_1fr_72px] items-center gap-2 text-[12px]">
                <span className="font-mono text-slate-500">{m.month}</span>
                <div className="space-y-0.5">
                  <div className="h-2 rounded-full bg-[#248a3d]/80" style={{ width: `${(100 * m.in) / max}%` }} title={`in ${money(m.in, ccy)}`} />
                  <div className="h-2 rounded-full bg-[#0071e3]/80" style={{ width: `${(100 * m.out) / max}%` }} title={`out ${money(m.out, ccy)}`} />
                </div>
                <span className="text-right tabular-nums text-slate-600 dark:text-slate-300">{compact(m.in + m.out)}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 flex gap-4 text-[11px] text-slate-500">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-3 rounded-full bg-[#248a3d]/80" /> Inflows
            </span>
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-3 rounded-full bg-[#0071e3]/80" /> Outflows
            </span>
          </div>
        </section>
        <section className="card p-5">
          <h3 className="text-[15px] font-semibold">Countries of the counterparties</h3>
          <ul className="mt-3 space-y-2">
            {r.countries.length === 0 && <li className="text-[13px] text-slate-500">No IBAN or country column: countries unknown.</li>}
            {r.countries.map((c) => (
              <li key={c.iso} className="flex items-start justify-between gap-3 text-[13px]">
                <div>
                  <span className="font-medium">{c.name}</span> <span className="text-slate-400">{c.iso}</span>
                  {c.risk.length > 0 && <div className="text-[11px] text-amber-700 dark:text-amber-300">{c.risk.join(" · ")}</div>}
                </div>
                <span className="tabular-nums text-slate-600 dark:text-slate-300">
                  {money(c.amount, ccy)} · {c.count}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="card overflow-hidden">
        <header className="flex flex-wrap items-center gap-2 px-5 pt-5">
          <h3 className="mr-auto text-[15px] font-semibold">
            {only ? "Transactions behind the selected flag" : "Flagged transactions"} ({rows.length})
          </h3>
          {only && (
            <button onClick={() => setOnly(null)} className="text-[12px] text-brand-600 hover:underline">
              Show all flagged
            </button>
          )}
        </header>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead className="text-left text-[11px] text-slate-500 uppercase">
              <tr className="border-b border-slate-200/70 dark:border-white/[0.06]">
                <th className="px-5 py-2 font-medium">Date</th>
                <th className="px-2 py-2 font-medium">Counterparty</th>
                <th className="px-2 py-2 font-medium">Description</th>
                <th className="px-2 py-2 text-right font-medium">Amount</th>
                <th className="px-5 py-2 font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 300).map((t) => (
                <tr key={t.idx} className="border-b border-slate-200/50 dark:border-white/[0.04]">
                  <td className="px-5 py-1.5 whitespace-nowrap tabular-nums">{t.date}</td>
                  <td className="px-2 py-1.5">
                    {t.counterparty ?? <span className="text-slate-400">—</span>}
                    {t.country && <span className="ml-1 text-slate-400">{t.country}</span>}
                  </td>
                  <td className="max-w-[260px] truncate px-2 py-1.5 text-slate-500" title={t.description ?? ""}>
                    {t.description}
                  </td>
                  <td className={`px-2 py-1.5 text-right whitespace-nowrap tabular-nums ${t.direction === "in" ? "text-[#248a3d] dark:text-[#30d158]" : ""}`}>
                    {t.direction === "in" ? "+" : "−"}
                    {money(t.amount)}
                  </td>
                  <td className="px-5 py-1.5 text-[11px] text-slate-500">{t.flags.map((f) => f.replace(/_/g, " ")).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="px-5 py-3 text-[11px] text-slate-500">
          Columns read: {Object.entries(r.mapping).map(([k, v]) => `${k} = “${v}”`).join(" · ")} · threshold {money(r.threshold)}
        </p>
      </section>
    </>
  );
}

function AlertRow({ a, ccy, active, onShow }: { a: StatementAlert; ccy: string | null; active: boolean; onShow: () => void }) {
  const sev = SEV[a.severity] ?? SEV.low;
  return (
    <li className={`px-5 py-3 ${active ? "bg-brand-500/[0.04]" : ""}`}>
      <div className="flex flex-wrap items-start gap-3">
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${sev.dot}`} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[14px] font-medium">{a.title}</span>
            <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${sev.tone}`}>{sev.label}</span>
          </div>
          <p className="mt-0.5 text-[13px] text-slate-600 dark:text-slate-300">{a.detail}</p>
          {a.legal && a.legal.length > 0 && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <RefChips refs={a.legal} />
              {a.justification_fr && (
                <button
                  onClick={async () => {
                    await navigator.clipboard?.writeText(a.justification_fr ?? "").catch(() => undefined);
                    toast("Justification copied (FR)");
                  }}
                  className="inline-flex items-center gap-1 text-[11px] text-brand-600 hover:underline"
                >
                  <Copy className="h-3 w-3" /> justification FR
                </button>
              )}
              {a.justification_en && (
                <button
                  onClick={async () => {
                    await navigator.clipboard?.writeText(a.justification_en ?? "").catch(() => undefined);
                    toast("Justification copied (EN)");
                  }}
                  className="inline-flex items-center gap-1 text-[11px] text-brand-600 hover:underline"
                >
                  <Copy className="h-3 w-3" /> EN
                </button>
              )}
            </div>
          )}
        </div>
        <button onClick={onShow} className="flex items-center gap-1 text-[12px] whitespace-nowrap text-brand-600 hover:underline">
          {active ? <Check className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {a.count} transaction{a.count > 1 ? "s" : ""} · {money(a.amount, ccy)}
        </button>
      </div>
      {a.severity === "critical" && (
        <p className="mt-2 ml-5 flex items-center gap-1.5 text-[12px] text-[#d70015]">
          <AlertTriangle className="h-3.5 w-3.5" /> Do not execute further payments with this counterparty until the match is ruled out.
        </p>
      )}
    </li>
  );
}
