import { useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Loader2, Pause, Play, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, triggerDownload } from "../api";
import type { ImportStatus } from "../types";

const TEMPLATE =
  "reference;name;identifier;country\nC-0001;Example Company SAS;552100554;FR\nC-0002;Example Holding SA;CHE-105.805.080;CH\nC-0003;Example Ltd;;GB\n";

interface Props {
  status?: ImportStatus;
}

/** Bulk import: a CSV / Excel client list becomes cases, analysed one by one while this page is open. */
export default function ImportPanel({ status }: Props) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [depth, setDepth] = useState(2);
  const [monitor, setMonitor] = useState(true);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<string | null>(null);
  const [done, setDone] = useState(0);
  const runRef = useRef(false);
  const remaining = status?.remaining ?? 0;
  const toFix = status?.to_fix ?? 0;
  const [open, setOpen] = useState(remaining > 0);

  const loop = async () => {
    if (runRef.current) return;
    runRef.current = true;
    setRunning(true);
    setError(null);
    try {
      while (runRef.current) {
        const r = await api.importNext();
        qc.invalidateQueries({ queryKey: ["dashboard"] });
        if (!r.step) break;
        setCurrent(`${r.step.title} — ${r.step.state.replace("_", " ")}`);
        if (r.step.state !== "resolved") setDone((n) => n + 1);
        if (r.remaining === 0) break;
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      runRef.current = false;
      setRunning(false);
      setCurrent(null);
    }
  };
  useEffect(() => () => void (runRef.current = false), []);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.importFile(file, { depth, monitor });
      setMessage(`${r.created} client${r.created === 1 ? "" : "s"} imported from ${file.name}.`);
      setWarnings(r.warnings);
      setFile(null);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      void loop();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <button className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen((o) => !o)}>
        <FileSpreadsheet className="h-5 w-5 text-brand-600" />
        <div className="min-w-0 flex-1">
          <div className="tag">Bulk import</div>
          <div className="text-[12px] text-slate-500">Import a client list (CSV or Excel): one case per client, found and screened automatically.</div>
        </div>
        {remaining > 0 && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 dark:text-slate-300">
            {running && <Loader2 className="h-3.5 w-3.5 animate-spin" />} {remaining} in the queue
          </span>
        )}
        {toFix > 0 && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300">{toFix} to check</span>}
      </button>
      {open && (
        <div className="space-y-3 border-t border-slate-200 p-4 dark:border-slate-800">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex min-w-[240px] flex-1 cursor-pointer items-center gap-2 rounded-xl border border-dashed border-slate-300 px-3 py-2.5 text-sm hover:border-brand-500 dark:border-white/15">
              <Upload className="h-4 w-4 text-slate-400" />
              <span className="truncate">{file ? file.name : "Choose a .csv or .xlsx file…"}</span>
              <input type="file" accept=".csv,.txt,.xlsx,.xlsm" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
            <label className="text-xs">
              <span className="label mb-1 block">Depth</span>
              <select className="input py-1.5 text-xs" value={depth} onChange={(e) => setDepth(Number(e.target.value))}>
                <option value={1}>1 — direct links (fast)</option>
                <option value={2}>2 — owners of owners</option>
              </select>
            </label>
            <label className="inline-flex items-center gap-1.5 pb-2 text-xs">
              <input type="checkbox" className="accent-brand-600" checked={monitor} onChange={(e) => setMonitor(e.target.checked)} /> Daily monitoring
            </label>
            <button className="btn-primary" disabled={!file || busy} onClick={upload}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />} Import
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-500">
            <span>
              Columns recognised: <b>name</b> / raison sociale, <b>identifier</b> (SIREN, SIRET, LEI, UID, company number), <b>country</b>,{" "}
              <b>reference</b>. Up to 500 clients. The file is read in memory and not kept.
            </span>
            <button className="btn-ghost py-0.5 text-[11px]" onClick={() => triggerDownload(new Blob([TEMPLATE], { type: "text/csv" }), "kyc1click_import_template.csv")}>
              <Download className="h-3 w-3" /> Template
            </button>
          </div>
          {message && <p className="text-xs text-[#067647] dark:text-[#47cd89]">{message}</p>}
          {warnings.length > 0 && (
            <ul className="text-[11px] text-amber-700 dark:text-amber-300">
              {warnings.slice(0, 8).map((w) => (
                <li key={w}>• {w}</li>
              ))}
              {warnings.length > 8 && <li>• …and {warnings.length - 8} more</li>}
            </ul>
          )}
          {(remaining > 0 || running) && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-3 py-2 text-xs dark:bg-white/[0.03]">
              {running ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin text-brand-600" />
                  <span className="min-w-0 flex-1 truncate">
                    Analysing — {done} processed, {remaining} left{current ? ` · ${current}` : ""}. Keep this page open.
                  </span>
                  <button className="btn-outline py-1 text-xs" onClick={() => (runRef.current = false)}>
                    <Pause className="h-3.5 w-3.5" /> Pause
                  </button>
                </>
              ) : (
                <>
                  <span className="min-w-0 flex-1">
                    {remaining} client{remaining === 1 ? "" : "s"} waiting. They are also processed by the daily monitoring job.
                  </span>
                  <button className="btn-outline py-1 text-xs" onClick={() => void loop()}>
                    <Play className="h-3.5 w-3.5" /> Analyse now
                  </button>
                </>
              )}
            </div>
          )}
          {toFix > 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-300">
              {toFix} line{toFix === 1 ? "" : "s"} need{toFix === 1 ? "s" : ""} you: several companies match or none was found. Open them in the list
              below to pick the right company.
            </p>
          )}
          {error && <p className="text-xs text-red-600">{error}</p>}
        </div>
      )}
    </div>
  );
}
