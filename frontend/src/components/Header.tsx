import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Database, FolderOpen, Moon, Plug, Search, Sun, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { Theme } from "../lib/theme";
import type { Meta } from "../types";

interface Props {
  meta?: Meta;
  theme: Theme;
  onToggleTheme: () => void;
  onHome: () => void;
  onCases: () => void;
  casesActive: boolean;
  onQuickOpen: () => void;
}

export default function Header({ meta, theme, onToggleTheme, onHome, onCases, casesActive, onQuickOpen }: Props) {
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const qc = useQueryClient();
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const clear = useMutation({
    mutationFn: api.clearCache,
    onSuccess: (r) => {
      qc.removeQueries({ queryKey: ["search"] });
      qc.removeQueries({ queryKey: ["investigation"] });
      setNotice(`Cache cleared (${r.deleted} entries deleted)`);
      setTimeout(() => setNotice(null), 3500);
    },
  });
  const enabled = connectors.data?.filter((c) => c.enabled).length ?? 0;
  const live = connectors.data?.some((c) => c.enabled && !c.demo);

  return (
    <header className="sticky top-0 z-30 border-b border-white/[0.06] bg-[#0a0b0a]/80 text-white backdrop-blur-xl [&_.btn-ghost]:text-slate-300 [&_.btn-ghost:hover]:bg-white/[0.06] [&_.btn-ghost:hover]:text-white">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-3 px-4">
        <button onClick={onHome} className="flex items-center gap-2.5" aria-label="Home">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div className="hidden text-left leading-tight sm:block">
            <div className="text-sm font-extrabold tracking-tight">KYC <span className="text-glow">1</span> CLICK</div>
            <div className="text-[11px] text-slate-300">Due diligence & AML/KYC in one click</div>
          </div>
        </button>
        {meta?.demo_mode && (
          <span className="hidden rounded md:inline bg-amber-400/15 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-200 ring-1 ring-amber-300/30">
            {live ? "Demo + live public sources" : "Demo mode · fictitious data"}
          </span>
        )}
        <button
          onClick={onQuickOpen}
          className="ml-auto flex h-9 items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 text-[13px] text-slate-400 transition-colors hover:border-white/20 hover:text-slate-200 md:ml-6 md:w-72"
          aria-label="Quick open"
        >
          <Search className="h-4 w-4" />
          <span className="hidden md:inline">Search or open a case…</span>
          <kbd className="ml-auto hidden rounded border border-white/15 px-1.5 font-mono text-[10px] md:inline">{mac ? "⌘K" : "Ctrl K"}</kbd>
        </button>
        <div className="flex items-center gap-1 md:ml-auto">
          {notice && <span className="mr-2 text-xs text-emerald-300">{notice}</span>}
          <button className={`btn-ghost ${casesActive ? "bg-white/10 !text-white" : ""}`} onClick={onCases}>
            <FolderOpen className="h-4 w-4" /> <span className="hidden sm:inline">Cases</span>
          </button>
          <div className="relative">
            <button className="btn-ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              <Plug className="h-4 w-4" /> <span className="hidden sm:inline">Sources</span>
              <span className="rounded bg-white/15 px-1.5 text-[11px]">
                {enabled}/{connectors.data?.length ?? 0}
              </span>
            </button>
            {open && (
              <div className="card absolute right-0 mt-2 text-slate-800 dark:text-slate-100 max-h-[70vh] w-[min(420px,calc(100vw-2rem))] overflow-y-auto p-3 shadow-lg" onMouseLeave={() => setOpen(false)}>
                <div className="label mb-2">Data sources (connectors)</div>
                <ul className="space-y-2">
                  {[...(connectors.data ?? [])].sort((a, b) => Number(b.enabled) - Number(a.enabled)).map((c) => (
                    <li key={c.name} className="flex items-start gap-2 text-sm">
                      {c.enabled ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                      ) : (
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                      )}
                      <div>
                        <div className="font-medium">{c.label}</div>
                        <div className="text-xs text-slate-500">
                          {c.kind} · {c.message}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <button
            className="btn-ghost"
            title="Delete all cached API responses and investigations"
            onClick={() => {
              if (confirm("Clear the local cache? All cached API responses and investigations will be deleted.")) clear.mutate();
            }}
            disabled={clear.isPending}
          >
            <Trash2 className="h-4 w-4" /> <Database className="-ml-1 hidden h-3.5 w-3.5 sm:inline" /> <span className="hidden sm:inline">Clear cache</span>
          </button>
          <button className="btn-ghost" onClick={onToggleTheme} aria-label="Toggle theme">
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </header>
  );
}
