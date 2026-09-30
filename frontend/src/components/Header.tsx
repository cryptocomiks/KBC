import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, FolderOpen, ListChecks, Moon, Plug, Search, Sun, Trash2 } from "lucide-react";
import { api } from "../api";
import { toast } from "../lib/toast";
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
  onSources: () => void;
  onScreen: () => void;
  screenActive: boolean;
  onDesignations: () => void;
  designationsActive: boolean;
  sourcesActive: boolean;
  onQuickOpen: () => void;
}

export default function Header({ meta, theme, onToggleTheme, onHome, onCases, casesActive, onSources, sourcesActive, onScreen, screenActive, onDesignations, designationsActive, onQuickOpen }: Props) {
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  const qc = useQueryClient();
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const clear = useMutation({
    mutationFn: api.clearCache,
    onSuccess: (r) => {
      qc.removeQueries({ queryKey: ["search"] });
      qc.removeQueries({ queryKey: ["investigation"] });
      toast(`Cache cleared: ${r.deleted} entries deleted`);
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
          <span className="hidden rounded-full bg-black/[0.05] px-2.5 py-0.5 text-[11px] text-[#636366] md:inline dark:bg-white/[0.08] dark:text-[#a1a1a6]">
            {live ? "Demo + live public sources" : "Demo · fictitious data"}
          </span>
        )}
        <nav className="ml-auto flex items-center gap-0.5">
          <NavLink active={casesActive} onClick={onCases} Icon={FolderOpen} label="Cases" tour="cases" />
          <NavLink active={screenActive} onClick={onScreen} Icon={ListChecks} label="Screen a list" />
          <NavLink active={designationsActive} onClick={onDesignations} Icon={BellRing} label="New listings" />
          <NavLink active={sourcesActive} onClick={onSources} Icon={Plug} label="Sources" badge={`${enabled}/${connectors.data?.length ?? 0}`} />
          <NavIcon
            title="Clear the local cache (API responses and investigations)"
            onClick={() => {
              if (confirm("Clear the local cache? All cached API responses and investigations will be deleted.")) clear.mutate();
            }}
            disabled={clear.isPending}
            Icon={Trash2}
          />
          <NavIcon title="Search or open a case" onClick={onQuickOpen} Icon={Search} kbd={mac ? "⌘K" : "Ctrl K"} tour="palette" />
          <NavIcon title={theme === "dark" ? "Light appearance" : "Dark appearance"} onClick={onToggleTheme} Icon={theme === "dark" ? Sun : Moon} />
        </nav>
      </div>
    </header>
  );
}

function NavLink({ active, onClick, Icon, label, badge, tour }: { active: boolean; onClick: () => void; Icon: typeof Search; label: string; badge?: string; tour?: string }) {
  return (
    <button
      data-tour={tour}
      onClick={onClick}
      aria-label={badge ? `${label} (${badge})` : label}
      aria-current={active ? "page" : undefined}
      className={`flex h-8 items-center gap-1.5 rounded-full px-3 transition-colors ${
        active ? "bg-black/[0.06] text-[#1d1d1f] dark:bg-white/[0.12] dark:text-white" : "text-[#1d1d1f]/80 hover:text-[#1d1d1f] dark:text-[#f5f5f7]/80 dark:hover:text-white"
      }`}
    >
      <Icon className="h-[15px] w-[15px] sm:hidden" aria-hidden />
      <span className="hidden sm:inline">{label}</span>
      {badge && <span className="text-[11px] text-[#636366] tabular-nums dark:text-[#a1a1a6]">{badge}</span>}
    </button>
  );
}

function NavIcon({ title, onClick, Icon, disabled, kbd, tour }: { title: string; onClick: () => void; Icon: typeof Search; disabled?: boolean; kbd?: string; tour?: string }) {
  return (
    <button
      data-tour={tour}
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
