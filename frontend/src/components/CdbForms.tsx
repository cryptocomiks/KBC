import { BlockSkeleton } from "./Skeleton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, FileDown, FileSignature, Loader2, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { fmtDate } from "../lib/format";
import type { CdbData, CdbForm, CdbPerson } from "../types";
import { BarList, ChartCard, Meter, Tile, TONE } from "./viz";

const FIELDS: { key: keyof CdbPerson; label: string }[] = [
  { key: "last_name", label: "Last name" },
  { key: "first_name", label: "First name(s)" },
  { key: "birth_date", label: "Date of birth" },
  { key: "nationality", label: "Nationality" },
  { key: "address", label: "Actual address of domicile" },
  { key: "country", label: "Country of domicile" },
];
const REQUIRED: Record<string, number> = { K: 4, A: 6, T: 6, S: 6 };
const PARTY: [string, string][] = [
  ["name", "Name / company"],
  ["legal_form", "Legal form"],
  ["registration_number", "Registration number"],
  ["country", "Country"],
  ["address", "Address"],
  ["relationship_no", "Relationship / account no."],
];
const ROLES: Record<string, [string, string][]> = {
  K: [["controlling", "Controlling person"]],
  A: [["beneficial_owner", "Beneficial owner"]],
  T: [["settlor", "Settlor"], ["trustee", "Trustee"], ["protector", "Protector"], ["beneficiary", "Beneficiary"]],
  S: [["founder", "Founder"], ["board", "Board member"], ["beneficiary", "Beneficiary"]],
};

/** An input saved when it loses focus (only if its value changed). */
function Field({ label, value, missing, onSave }: { label: string; value: string; missing?: boolean; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  return (
    <label className="block">
      <span className={`block text-[10px] font-medium uppercase tracking-wide ${missing ? "text-amber-600" : "text-slate-500"}`}>
        {label}
        {missing && " · to complete"}
      </span>
      <input
        className={`input mt-0.5 w-full py-1 text-[13px] ${missing ? "ring-1 ring-amber-500/40" : ""}`}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => v !== value && onSave(v)}
      />
    </label>
  );
}

function Person({ p, form, edit }: { p: CdbPerson; form: CdbForm; edit: (e: Record<string, unknown>) => void }) {
  const need = REQUIRED[form.code];
  const filled = need - p.missing.length;
  return (
    <div className="rounded-xl border border-slate-200 p-3 dark:border-white/10">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-brand-500/12 px-2 py-0.5 text-[10px] font-semibold text-brand-700 uppercase ring-1 ring-brand-500/25 dark:text-brand-300">
          {p.role_label}
        </span>
        <span className="min-w-0 flex-1 text-[12px] text-slate-600 dark:text-slate-400">{p.basis}</span>
        <span className="flex w-28 items-center gap-1.5 text-[10.5px] text-slate-500" title="Required fields filled">
          <Meter className="flex-1" value={filled} max={need} tone={filled === need ? "good" : "warning"} label="Completeness" />
          {filled}/{need}
        </span>
        {p.flags.map((f) => (
          <span key={f} className="rounded-full bg-red-500/12 px-2 py-0.5 text-[10px] font-semibold text-red-700 uppercase dark:text-red-300">
            {f}
          </span>
        ))}
        <button className="btn-ghost px-1.5 py-1 text-xs text-slate-400 hover:text-red-600" aria-label="Remove this person" onClick={() => edit({ form: form.id, remove: p.key })}>
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {FIELDS.map((f) => (
          <Field
            key={`${p.key}-${f.key}-${String(p[f.key])}`}
            label={f.label}
            value={String(p[f.key] ?? "")}
            missing={p.missing.includes(f.label)}
            onSave={(v) => edit({ form: form.id, person: p.key, fields: { [f.key]: v } })}
          />
        ))}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        {p.path.length > 2 && <>Chain: {p.path.join(" → ")} · </>}
        {p.source ? `Source: ${p.source}` : "Declared by the analyst"}
        {p.is_company && " · a legal entity: identify the natural persons behind it"}
      </p>
    </div>
  );
}

/** CDB 20 tab: the beneficial-ownership forms to have signed, pre-filled from the registers. */
export default function CdbForms({ caseId }: { caseId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["cdb", caseId], queryFn: () => api.cdb(caseId) });
  const [name, setName] = useState(analyst.get());
  const [role, setRole] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: (e: Record<string, unknown>) => api.editCdb(caseId, { by: name || "analyst", ...e }),
    onSuccess: (d: CdbData) => qc.setQueryData(["cdb", caseId], d),
  });
  const pdf = useMutation({ mutationFn: () => api.downloadCdb(caseId) });
  if (q.isLoading || !q.data) return <BlockSkeleton rows={5} />;
  const d = q.data;
  const edit = (e: Record<string, unknown>) => {
    if (name) analyst.set(name);
    save.mutate(e);
  };

  return (
    <div className="panel-enter space-y-4">
      <div className="card p-4">
        <div className="flex flex-wrap items-center gap-2">
          <FileSignature className="h-5 w-5 text-brand-600" />
          <span className="tag">Beneficial ownership: CDB 20</span>
          {d.forms.map((f) => (
            <span key={f.id} className="rounded-md bg-slate-900 px-2 py-0.5 font-mono text-[11px] font-bold text-white dark:bg-white dark:text-slate-900">
              {f.code}
            </span>
          ))}
          <span className={`text-xs ${d.missing_total ? "text-amber-700 dark:text-amber-300" : "text-brand-700 dark:text-brand-400"}`}>
            {d.missing_total ? `${d.missing_total} field(s) to complete` : "complete: ready to sign"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <input className="input w-36 py-1 text-xs" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-ghost py-1.5 text-xs" title="Discard every edit" onClick={() => window.confirm("Discard all edits and go back to the registers?") && edit({ reset: true })}>
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
            <button className="btn-primary py-1.5 text-xs" onClick={() => pdf.mutate()} disabled={pdf.isPending}>
              {pdf.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileDown className="h-3.5 w-3.5" />} Forms PDF
            </button>
          </div>
        </div>
        <p className="mt-2 text-[12px] text-slate-500">
          {d.draft_note} {d.edited_by && <>Last edit by {d.edited_by}, {fmtDate(d.edited_at)}.</>}
        </p>
        {d.exemption && <p className="mt-2 rounded-lg bg-sky-500/10 px-3 py-2 text-[12px] text-sky-800 dark:text-sky-200">{d.exemption}</p>}
        {(save.error || pdf.error) && <p className="mt-2 text-xs text-red-600">{((save.error || pdf.error) as Error).message}</p>}
        <h4 className="mt-4 mb-2 text-[12px] font-semibold">Contracting party</h4>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {PARTY.map(([k, label]) => (
            <Field
              key={`${k}-${d.contracting_party[k] ?? ""}`}
              label={label}
              value={d.contracting_party[k] ?? ""}
              missing={k === "relationship_no" && !d.contracting_party[k]}
              onSave={(v) => edit({ header: { [k]: v } })}
            />
          ))}
        </div>
      </div>

      {(() => {
        const people = d.forms.flatMap((f) => f.persons.map((p) => ({ f, p })));
        const need = d.forms.reduce((n, f) => n + REQUIRED[f.code] * f.persons.length + f.structure.length, 0);
        const owners = people.filter(({ p }) => p.pct != null).sort((a, b) => (b.p.pct ?? 0) - (a.p.pct ?? 0));
        return (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <div className="grid grid-cols-2 gap-2">
              <Tile label="Forms to sign" value={d.forms.map((f) => f.code).join(" + ")} sub={d.forms.length > 1 ? "incl. structures in the chain" : d.forms[0]?.title.split(": ")[1]} />
              <Tile label="Persons identified" value={people.length} sub={`${people.filter(({ p }) => p.source).length} from the registers`} />
              <Tile
                label="Completeness"
                tone={d.missing_total ? "warning" : "good"}
                value={`${Math.round((100 * (need - d.missing_total)) / Math.max(1, need))}%`}
                sub={d.missing_total ? `${d.missing_total} field(s) to complete` : "ready to sign"}
                meter={{ value: need - d.missing_total, max: need, tone: d.missing_total ? "warning" : "good" }}
              />
              <Tile label="Flags on persons" tone={people.some(({ p }) => p.flags.length) ? "critical" : "good"} value={people.filter(({ p }) => p.flags.length).length} sub="sanctioned / PEP / in leaks" />
            </div>
            <ChartCard
              title="Ownership of the persons declared"
              sub="effective % through every layer · CDB 20 threshold at 25 %"
              table={{ head: ["Person", "Form", "Effective %"], rows: owners.map(({ f, p }) => [`${p.last_name} ${p.first_name}`.trim(), f.code, `${p.pct?.toFixed(1)} %`]) }}
            >
              {owners.length ? (
                <BarList
                  max={100}
                  marker={25}
                  markerLabel="25 %: controlling person / beneficial owner threshold"
                  rows={owners.map(({ f, p }) => ({
                    key: `${f.id}-${p.key}`,
                    label: `${p.first_name} ${p.last_name}`.trim(),
                    sub: p.path.length > 2 ? p.path.join(" → ") : p.role_label,
                    value: p.pct ?? 0,
                    display: `${(p.pct ?? 0).toFixed(1)}%`,
                    color: p.flags.length ? TONE.critical : TONE.accent,
                  }))}
                />
              ) : (
                <p className="text-xs text-slate-500">No shareholding in the registers: persons are retained by control or management.</p>
              )}
            </ChartCard>
          </div>
        );
      })()}

      {d.forms.map((f) => (
        <section key={f.id} className="card p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500/15 font-mono text-sm font-bold text-brand-700 ring-1 ring-brand-500/30 dark:text-brand-300">
              {f.code}
            </span>
            <h3 className="min-w-0 flex-1 text-[14px] font-semibold">{f.title}</h3>
            {f.missing_count > 0 && <span className="text-[11px] text-amber-700 dark:text-amber-300">{f.missing_count} to complete</span>}
          </div>
          <p className="mt-2 text-[12.5px] text-slate-600 dark:text-slate-400">{f.why}</p>
          {f.notes.map((n) => (
            <p key={n} className="mt-2 flex gap-2 text-[12px] text-amber-800 dark:text-amber-200">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {n}
            </p>
          ))}
          {f.structure.length > 0 && (
            <div className="mt-3 grid gap-2 sm:grid-cols-3">
              {f.structure.map((x) => (
                <Field
                  key={`${x.key}-${x.value}`}
                  label={x.label}
                  value={x.value}
                  missing={!x.value}
                  onSave={(v) => edit({ form: f.id, structure: { [x.key]: v } })}
                />
              ))}
            </div>
          )}
          <div className="mt-3 space-y-2">
            {f.persons.map((p) => (
              <Person key={p.key} p={p} form={f} edit={edit} />
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2">
            {ROLES[f.code].length > 1 && (
              <select className="input w-auto py-1 text-xs" value={role[f.id] ?? ROLES[f.code][0][0]} onChange={(e) => setRole({ ...role, [f.id]: e.target.value })}>
                {ROLES[f.code].map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            )}
            <button className="btn-outline py-1 text-xs" onClick={() => edit({ form: f.id, add: true, role: role[f.id] ?? ROLES[f.code][0][0] })}>
              <Plus className="h-3.5 w-3.5" /> Add a person
            </button>
            {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
          </div>
        </section>
      ))}
      <p className="px-1 text-[11px] text-slate-500">{d.declaration}</p>
    </div>
  );
}
