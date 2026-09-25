import { FileSearch, Loader2, Plus, ShieldCheck, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { api } from "../api";
import type { DeclaredPerson, DocComparison, DocExtraction, Investigation } from "../types";

const STATUS = {
  match: { label: "Consistent", cls: "bg-[#079455]/15 text-[#067647] dark:text-[#47cd89]" },
  mismatch: { label: "Different", cls: "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]" },
  missing_in_registry: { label: "Not in registries", cls: "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]" },
  missing_in_document: { label: "Not declared", cls: "bg-[#d92d20]/12 text-[#b42318] dark:text-[#fda29b]" },
} as const;

const EMPTY: DocExtraction = {
  kind: "manual",
  pages: 0,
  characters: 0,
  company: { name: null, registration_number: null, address: null },
  officers: [],
  owners: [],
  warnings: [],
};

interface Props {
  investigation: Investigation;
  onSelect: (id: string) => void;
}

/** Register extract / UBO declaration from the client vs what the registries say. Nothing is stored. */
export default function ClientDocuments({ investigation: inv, onSelect }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [doc, setDoc] = useState<DocExtraction | null>(null);
  const [file, setFile] = useState<string | null>(null);
  const [busy, setBusy] = useState<"read" | "compare" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DocComparison | null>(null);

  const read = async (f: File) => {
    setBusy("read");
    setError(null);
    setResult(null);
    try {
      setDoc(await api.extractDocument(f));
      setFile(f.name);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const run = async () => {
    if (!doc) return;
    setBusy("compare");
    setError(null);
    try {
      setResult(await api.compareDocument({ ...inv.params, company: doc.company, officers: doc.officers, owners: doc.owners }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const edit = (list: "officers" | "owners", i: number, patch: Partial<DeclaredPerson>) =>
    setDoc((d) => d && { ...d, [list]: d[list].map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  const remove = (list: "officers" | "owners", i: number) => setDoc((d) => d && { ...d, [list]: d[list].filter((_, j) => j !== i) });
  const add = (list: "officers" | "owners") =>
    setDoc((d) => d && { ...d, [list]: [...d[list], { name: "", role: list === "owners" ? "Beneficial owner" : "Director", pct: null }] });

  const personTable = (list: "officers" | "owners", title: string) =>
    doc && (
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="label">{title}</span>
          <button className="btn-ghost py-0.5 text-xs" onClick={() => add(list)}>
            <Plus className="h-3 w-3" /> Add
          </button>
        </div>
        {doc[list].length === 0 ? (
          <p className="text-xs text-slate-500">None read — add them manually if needed.</p>
        ) : (
          <ul className="space-y-1.5">
            {doc[list].map((p, i) => (
              <li key={i} className="flex items-center gap-1.5">
                <input className="input min-w-0 flex-1 py-1 text-xs" value={p.name} onChange={(e) => edit(list, i, { name: e.target.value })} placeholder="Name" />
                {list === "owners" ? (
                  <input
                    className="input w-20 py-1 text-xs"
                    type="number"
                    min={0}
                    max={100}
                    value={p.pct ?? ""}
                    onChange={(e) => edit(list, i, { pct: e.target.value === "" ? null : Number(e.target.value) })}
                    placeholder="%"
                  />
                ) : (
                  <input className="input w-36 py-1 text-xs" value={p.role ?? ""} onChange={(e) => edit(list, i, { role: e.target.value })} placeholder="Role" />
                )}
                <button className="btn-ghost p-1" onClick={() => remove(list, i)} aria-label="Remove">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    );

  return (
    <details className="card">
      <summary className="flex cursor-pointer items-center gap-2 px-5 py-3">
        <FileSearch className="h-4 w-4 text-brand-600" />
        <span className="text-sm font-semibold">Compare with the client's documents</span>
        <span className="text-[11px] text-slate-500">register extract (Kbis…), UBO declaration, PSC register — read in memory, never stored</span>
      </summary>
      <div className="space-y-4 border-t border-black/[0.06] px-5 py-4 dark:border-white/[0.08]">
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={input}
            type="file"
            accept=".pdf,.txt,application/pdf,text/plain"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && read(e.target.files[0])}
          />
          <button className="btn-primary" onClick={() => input.current?.click()} disabled={busy !== null}>
            {busy === "read" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            Read a document (PDF)
          </button>
          <button className="btn-outline" onClick={() => { setDoc({ ...EMPTY }); setFile(null); setResult(null); }}>
            Enter manually
          </button>
          {file && doc && (
            <span className="text-xs text-slate-500">
              {file} · {doc.kind} · {doc.pages} page(s) — check and correct the rows below, then compare.
            </span>
          )}
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {doc?.warnings.map((w) => (
          <p key={w} className="text-xs text-[#b54708] dark:text-[#fec84b]">
            {w}
          </p>
        ))}

        {doc && (
          <>
            <div className="grid gap-2 sm:grid-cols-3">
              {(["name", "registration_number", "address"] as const).map((k) => (
                <label key={k} className="block">
                  <span className="label mb-1 block">{k === "name" ? "Company name" : k === "registration_number" ? "Registration no." : "Address"}</span>
                  <input
                    className="input w-full py-1 text-xs"
                    value={doc.company[k] ?? ""}
                    onChange={(e) => setDoc({ ...doc, company: { ...doc.company, [k]: e.target.value || null } })}
                  />
                </label>
              ))}
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              {personTable("officers", "Officers declared")}
              {personTable("owners", "Owners / beneficial owners declared")}
            </div>
            <button className="btn-primary" onClick={run} disabled={busy !== null}>
              {busy === "compare" ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              Compare with the registries
            </button>
          </>
        )}

        {result && (
          <div>
            <div className="mb-2 flex flex-wrap gap-2 text-xs">
              {(Object.keys(STATUS) as (keyof typeof STATUS)[]).map((k) => (
                <span key={k} className={`rounded px-2 py-0.5 font-semibold ${STATUS[k].cls}`}>
                  {result.summary[k] ?? 0} {STATUS[k].label.toLowerCase()}
                </span>
              ))}
            </div>
            <table className="w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="py-1.5 pr-2">Item</th>
                  <th className="py-1.5 pr-2">Client document</th>
                  <th className="py-1.5 pr-2">Registries</th>
                  <th className="py-1.5 pr-2">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-black/[0.06] dark:divide-white/[0.08]">
                {result.rows.map((r, i) => (
                  <tr key={i} className={r.entity_id ? "cursor-pointer hover:bg-black/[0.03] dark:hover:bg-white/[0.04]" : ""} onClick={() => r.entity_id && onSelect(r.entity_id)}>
                    <td className="py-1.5 pr-2">
                      <div className="font-medium">{r.name}</div>
                      <div className="text-[11px] text-slate-500">{r.kind}</div>
                    </td>
                    <td className="py-1.5 pr-2 text-xs">{r.declared ?? "—"}</td>
                    <td className="py-1.5 pr-2 text-xs">{r.registry ?? "—"}</td>
                    <td className="py-1.5 pr-2">
                      <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${STATUS[r.status].cls}`}>{STATUS[r.status].label}</span>
                      {r.note && <div className="mt-0.5 text-[11px] text-slate-500">{r.note}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  );
}
