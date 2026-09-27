import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FolderOpen, Moon, Plug, Search, Sun, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import Logo from "./Logo";
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
    <header className="sticky top-0 z-30 border-b border-black/[0.08] bg-[rgb(251_251_253/0.8)] text-[#1d1d1f] backdrop-blur-xl backdrop-saturate-[1.8] dark:border-white/[0.08] dark:bg-[rgb(22_22_23/0.8)] dark:text-[#f5f5f7]">
      <div className="mx-auto flex h-12 max-w-[1100px] items-center gap-1 px-4 text-[13px] xl:max-w-[1400px]">
        <button onClick={onHome} className="mr-2 flex items-center gap-2 opacity-90 transition-opacity hover:opacity-100" aria-label="Home">
          <Logo className="h-[22px] w-[22px]" />
          <span className="hidden text-[15px] font-semibold tracking-[-0.02em] sm:inline">
            KYC <span className="text-brand-500 dark:text-[#2997ff]">1</span> CLICK
          </span>
        </button>
        {meta?.demo_mode && (
          <span className="hidden rounded-full bg-black/[0.05] px-2.5 py-0.5 text-[11px] text-[#6e6e73] md:inline dark:bg-white/[0.08] dark:text-[#a1a1a6]">
            {live ? "Demo + live public sources" : "Demo · fictitious data"}
          </span>
        )}
        <nav className="ml-auto flex items-center gap-0.5">
          <NavLink active={casesActive} onClick={onCases} Icon={FolderOpen} label="Cases" />
          <div className="relative">
            <NavLink active={open} onClick={() => setOpen((o) => !o)} Icon={Plug} label="Sources" badge={`${enabled}/${connectors.data?.length ?? 0}`} />
            {open && (
              <div className="glass-panel absolute right-0 mt-3 rounded-2xl text-slate-800 dark:text-slate-100 max-h-[70vh] w-[min(420px,calc(100vw-2rem))] overflow-y-auto p-3 shadow-lg" onMouseLeave={() => setOpen(false)}>
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
          <NavIcon
            title="Clear the local cache (API responses and investigations)"
            onClick={() => {
              if (confirm("Clear the local cache? All cached API responses and investigations will be deleted.")) clear.mutate();
            }}
            disabled={clear.isPending}
            Icon={Trash2}
          />
          <NavIcon title="Search or open a case" onClick={onQuickOpen} Icon={Search} kbd={mac ? "⌘K" : "Ctrl K"} />
          <NavIcon title={theme === "dark" ? "Light appearance" : "Dark appearance"} onClick={onToggleTheme} Icon={theme === "dark" ? Sun : Moon} />
        </nav>
        {notice && <span className="ml-2 hidden text-xs text-[#6e6e73] md:inline">{notice}</span>}
      </div>
    </header>
  );
}

function NavLink({ active, onClick, Icon, label, badge }: { active: boolean; onClick: () => void; Icon: typeof Search; label: string; badge?: string }) {
  return (
    <button
      onClick={onClick}
      aria-expanded={badge ? active : undefined}
      className={`flex h-8 items-center gap-1.5 rounded-full px-3 transition-colors ${
        active ? "bg-black/[0.06] text-[#1d1d1f] dark:bg-white/[0.12] dark:text-white" : "text-[#1d1d1f]/80 hover:text-[#1d1d1f] dark:text-[#f5f5f7]/80 dark:hover:text-white"
      }`}
    >
      <Icon className="h-[15px] w-[15px] sm:hidden" />
      <span className="hidden sm:inline">{label}</span>
      {badge && <span className="text-[11px] text-[#6e6e73] tabular-nums dark:text-[#a1a1a6]">{badge}</span>}
    </button>
  );
}

function NavIcon({ title, onClick, Icon, disabled, kbd }: { title: string; onClick: () => void; Icon: typeof Search; disabled?: boolean; kbd?: string }) {
  return (
    <button
      title={kbd ? `${title} (${kbd})` : title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      className="flex h-8 w-8 items-center justify-center rounded-full text-[#1d1d1f]/80 transition-colors hover:bg-black/[0.05] hover:text-[#1d1d1f] disabled:opacity-40 dark:text-[#f5f5f7]/80 dark:hover:bg-white/[0.1] dark:hover:text-white"
    >
      <Icon className="h-[15px] w-[15px]" />
    </button>
  );
}
