import { ArrowLeft, ArrowRight, Building2, ExternalLink, FileText, Flag, Landmark, MapPin, User, Wallet } from "lucide-react";
import { countryName, ENTITY_COLORS, ENTITY_LEVEL_LABEL, fmtDate, fmtPct, flag, scoreClass } from "../lib/format";
import type { Entity, Investigation, RiskLevel } from "../types";

interface Props {
  investigation: Investigation;
  entityId: string;
  onSelect: (id: string) => void;
}

const ICONS = { person: User, company: Building2, address: MapPin, wallet: Wallet };
const REL_LABEL: Record<string, string> = {
  officer: "Officer",
  shareholder: "Shareholder",
  beneficial_owner: "Declared UBO",
  registered_at: "Registered at",
  controls: "Controls",
  transfer: "Flows",
  relative: "Family / associate",
};

const HIDDEN_EXTRA = new Set(["financials", "accounts_unknown"]);

function financials(value: unknown): React.ReactNode {
  const rows = (value as Record<string, string | null>[] | undefined) ?? [];
  if (!rows.length) return undefined;
  return (
    <table className="w-full text-[11px]">
      <thead className="text-slate-500">
        <tr>
          <th className="text-left font-medium">Year</th>
          <th className="text-right font-medium">Revenue</th>
          <th className="text-right font-medium">Net income</th>
          <th className="text-right font-medium">Assets</th>
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 4).map((r) => (
          <tr key={String(r.year)}>
            <td>{r.year}</td>
            <td className="text-right font-mono">{r.revenue ?? "—"}</td>
            <td className="text-right font-mono">{r.net_income ?? "—"}</td>
            <td className="text-right font-mono">{r.total_assets ?? "—"}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={4} className="pt-0.5 text-slate-500">
            {rows[0].currency} · {rows[0].source}
          </td>
        </tr>
      </tfoot>
    </table>
  );
}

export default function EntityPanel({ investigation: inv, entityId, onSelect }: Props) {
  const byId = new Map(inv.entities.map((e) => [e.id, e]));
  const e = byId.get(entityId);
  if (!e) return null;
  const Icon = ICONS[e.type];
  const level: RiskLevel = inv.risk.entity_levels[e.id] ?? "none";
  const flags = inv.risk.entity_flags[e.id] ?? [];
  const hits = inv.hits.filter((h) => h.entity_id === e.id);
  const outgoing = inv.relationships.filter((r) => r.source_id === e.id);
  const incoming = inv.relationships.filter((r) => r.target_id === e.id);

  const countryRisk = (code: string | null) => {
    const row = (inv.tables.jurisdictions ?? []).find((r) => r.code === code);
    if (!row) return undefined;
    const bits = [
      row.basel_aml_score != null && `Basel AML ${Number(row.basel_aml_score).toFixed(2)}/10`,
      row.cpi_score != null && `CPI ${row.cpi_score}/100`,
      row.lists && String(row.lists),
    ].filter(Boolean);
    return bits.length ? bits.join(" · ") : undefined;
  };

  const attrs: [string, React.ReactNode][] =
    e.type === "person"
      ? [
          ["Date of birth", e.birth_date],
          ["Nationality", e.nationalities.map((n) => `${flag(n)} ${countryName(n)}`).join(", ")],
          ["Active mandates", e.extra.active_mandates as number | undefined],
        ]
      : e.type === "company"
        ? [
            ["Jurisdiction", `${flag(e.jurisdiction)} ${countryName(e.jurisdiction)}${e.is_offshore ? " · offshore centre" : ""}`],
            ["Registration no.", <span className="font-mono">{e.registration_number}</span>],
            ["Legal form", e.legal_form],
            ["Status", e.status === "dissolved" ? `dissolved ${e.dissolution_date ?? ""}` : e.status],
            ["Incorporated", e.incorporation_date],
            ["Last accounts", e.last_accounts_date ?? "none on file"],
            ["Activity", e.activity],
            ["Address", e.address],
            ["Country risk", countryRisk(e.jurisdiction)],
            ...Object.entries(e.extra)
              .filter(([k]) => !HIDDEN_EXTRA.has(k))
              .map(([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " "), String(v)] as [string, React.ReactNode]),
            ["Financials", financials(e.extra.financials)],
          ]
        : e.type === "wallet"
          ? [
              ["Blockchain", e.chain],
              ["Address", <span className="break-all font-mono">{e.name}</span>],
              ...Object.entries(e.extra).map(
                ([k, v]) => [k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " "), String(v)] as [string, React.ReactNode],
              ),
            ]
          : [["Companies registered here", e.extra.companies_registered as number | undefined]];

  const relRow = (other: Entity | undefined, label: string, detail: string, dir: "in" | "out", ended: boolean, key: string) =>
    other && (
      <li key={key}>
        <button
          onClick={() => onSelect(other.id)}
          className={`flex w-full items-start gap-2 rounded-md px-2 py-1 text-left hover:bg-slate-100 dark:hover:bg-slate-800 ${ended ? "opacity-60" : ""}`}
        >
          {dir === "out" ? <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" /> : <ArrowLeft className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />}
          <span className="min-w-0">
            <span className="font-medium">{other.name}</span>
            <span className="block text-[11px] text-slate-500">
              {label}
              {detail && ` · ${detail}`}
              {ended && " · ended"}
            </span>
          </span>
        </button>
      </li>
    );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-slate-200 p-4 dark:border-slate-800">
        <div className="flex items-start gap-2">
          <Icon className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold leading-tight">{e.name}</div>
            {e.aliases.length > 0 && <div className="text-xs text-slate-500">aka {e.aliases.join(" · ")}</div>}
          </div>
          <span
            className="rounded px-2 py-0.5 text-[11px] font-semibold uppercase text-white"
            style={{ background: ENTITY_COLORS[level] }}
          >
            {ENTITY_LEVEL_LABEL[level]}
          </span>
        </div>
        {e.id === inv.subject_id && <div className="mt-1 text-[11px] font-medium text-brand-600">Investigated subject</div>}
        {inv.depth[e.id] !== undefined && e.id !== inv.subject_id && (
          <div className="mt-1 text-[11px] text-slate-500">{inv.depth[e.id]} hop(s) from the subject</div>
        )}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        {flags.length > 0 && (
          <section>
            <div className="label mb-1.5 flex items-center gap-1">
              <Flag className="h-3 w-3" /> Red flags
            </div>
            <ul className="space-y-1">
              {flags.map((f) => (
                <li key={f} className="rounded-md bg-red-50 px-2 py-1 text-xs text-red-800 dark:bg-red-950/40 dark:text-red-300">
                  {f}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <div className="label mb-1.5">Details</div>
          <dl className="grid grid-cols-[120px_1fr] gap-x-2 gap-y-1 text-xs">
            {attrs
              .filter(([, v]) => v !== undefined && v !== null && v !== "")
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-slate-500">{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
          </dl>
        </section>

        {hits.length > 0 && (
          <section>
            <div className="label mb-1.5 flex items-center gap-1">
              <Landmark className="h-3 w-3" /> Screening hits
            </div>
            <ul className="space-y-2">
              {hits.map((h) => (
                <li key={`${h.dataset}-${h.provenance.record_id}`} className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-700">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold uppercase">{h.list_type}</span>
                    <span className={`rounded px-1.5 font-semibold ${scoreClass(h.score)}`}>{h.score.toFixed(0)}%</span>
                    <span className="truncate text-slate-500">{h.dataset}</span>
                  </div>
                  <div className="mt-1">
                    Listed as <strong>{h.matched_name}</strong>
                  </div>
                  <div className="mt-0.5 text-slate-500">{h.explanation.join(" · ")}</div>
                  <div className="mt-0.5 text-slate-600 dark:text-slate-400">
                    {Object.entries(h.details)
                      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${Array.isArray(v) ? v.join(", ") : v}`)
                      .join(" · ")}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {(outgoing.length > 0 || incoming.length > 0) && (
          <section>
            <div className="label mb-1.5">Relationships</div>
            <ul className="space-y-0.5 text-xs">
              {incoming.map((r) =>
                relRow(byId.get(r.source_id), r.type === "transfer" ? "Received from" : REL_LABEL[r.type], [r.role, r.share_pct != null ? fmtPct(r.share_pct) : ""].filter(Boolean).join(" · "), "in", !!r.end_date, r.id),
              )}
              {outgoing.map((r) =>
                relRow(byId.get(r.target_id), r.type === "transfer" ? "Sent to" : r.type === "controls" ? "Controls" : `${REL_LABEL[r.type]} of`, [r.role, r.share_pct != null ? fmtPct(r.share_pct) : ""].filter(Boolean).join(" · "), "out", !!r.end_date, r.id),
              )}
            </ul>
          </section>
        )}

        {e.documents?.length > 0 && (
          <section>
            <div className="label mb-1.5 flex items-center gap-1">
              <FileText className="h-3 w-3" /> Documents & filings ({e.documents.length})
            </div>
            <ul className="space-y-1.5 text-xs">
              {e.documents.map((d, i) => (
                <li
                  key={`${d.url}-${i}`}
                  className={`rounded-md border p-2 ${
                    d.flags.includes("insolvency")
                      ? "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/40"
                      : "border-slate-200 dark:border-slate-700"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className="font-medium">
                      {d.url ? (
                        <a href={d.url} target="_blank" rel="noreferrer" className="inline-flex items-start gap-1 text-brand-600 hover:underline">
                          {d.title} <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                        </a>
                      ) : (
                        d.title
                      )}
                    </span>
                    {d.date && <span className="ml-auto shrink-0 text-slate-500">{d.date}</span>}
                  </div>
                  {d.summary && <div className="mt-0.5 text-slate-600 dark:text-slate-400">{d.summary}</div>}
                  <div className="mt-0.5 text-[10px] text-slate-400">{d.source}</div>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <div className="label mb-1.5">Sources ({e.sources.length})</div>
          {e.sources.length === 0 && <p className="text-xs text-slate-500">Derived from the addresses of the linked companies.</p>}
          <ul className="space-y-1.5 text-xs">
            {e.sources.map((s, i) => (
              <li key={i} className="rounded-md bg-slate-50 p-2 dark:bg-slate-800/60">
                <div className="font-medium">{s.source_label}</div>
                <div className="text-slate-500">
                  record <span className="font-mono">{s.record_id}</span> · retrieved {fmtDate(s.retrieved_at)}
                </div>
                {s.url && (
                  <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">
                    {s.url.replace(/^https?:\/\//, "").slice(0, 60)} <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
