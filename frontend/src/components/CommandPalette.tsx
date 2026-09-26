import { useQuery } from "@tanstack/react-query";
import { Building2, CornerDownLeft, FolderOpen, Home, LayoutGrid, Search, User } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Route } from "../lib/route";

interface Item {
  id: string;
  label: string;
  hint?: string;
  Icon: typeof Search;
  route: Route;
}

interface Props {
  casesEnabled: boolean;
  onClose: () => void;
  onNavigate: (r: Route) => void;
}

const norm = (s: string) =>
  s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();

/** Quick open (Ctrl+K / ⌘K): jump to a case, search the registries, or go to a page. */
export default function CommandPalette({ casesEnabled, onClose, onNavigate }: Props) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  // Uses the cached dashboard when it is there; a locked store simply shows no case.
  const cases = useQuery({ queryKey: ["dashboard", 0], queryFn: api.dashboard, enabled: casesEnabled, retry: false, staleTime: 30_000 });

  const items = useMemo<Item[]>(() => {
    const text = q.trim();
    const out: Item[] = [];
    if (text.length >= 2) {
      out.push(
        { id: "s-any", label: `Search “${text}”`, hint: "companies, people, identifiers, wallets", Icon: Search, route: { name: "search", q: text, type: "any", depth: 2, maxNodes: 60 } },
        { id: "s-co", label: `Search companies: “${text}”`, Icon: Building2, route: { name: "search", q: text, type: "company", depth: 2, maxNodes: 60 } },
        { id: "s-pe", label: `Search people: “${text}”`, Icon: User, route: { name: "search", q: text, type: "person", depth: 2, maxNodes: 60 } },
      );
    }
    const n = norm(text);
    const matching = (cases.data?.cases ?? []).filter((c) => !n || norm(`${c.title} ${c.subject_name}`).includes(n)).slice(0, 8);
    for (const c of matching) {
      out.push({
        id: `c-${c.id}`,
        label: c.title,
        hint: [c.risk_level, c.workflow_state?.replace("_", " "), c.questionnaire?.vigilance && `${c.questionnaire.vigilance} vigilance`]
          .filter(Boolean)
          .join(" · "),
        Icon: FolderOpen,
        route: { name: "case", id: c.id, tab: "kyc" },
      });
    }
    const pages: Item[] = [
      { id: "p-home", label: "New search", Icon: Home, route: { name: "home" } },
      { id: "p-cases", label: "Cases dashboard", Icon: LayoutGrid, route: { name: "cases" } },
    ];
    out.push(...pages.filter((p) => !n || norm(p.label).includes(n)));
    return out;
  }, [q, cases.data]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 px-4 pt-[12vh] backdrop-blur-sm" onMouseDown={onClose}>
      <div
        className="card w-full max-w-xl overflow-hidden p-0 shadow-2xl"
        role="dialog"
        aria-label="Quick open"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 dark:border-white/10">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            autoFocus
            className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-slate-400"
            placeholder="Search a company, a person, an identifier — or open a case…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              else if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, items.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter" && items[active]) {
                e.preventDefault();
                onNavigate(items[active].route);
              }
            }}
          />
          <kbd className="rounded border border-slate-300 px-1.5 text-[10px] text-slate-500 dark:border-white/15">Esc</kbd>
        </div>
        <ul ref={listRef} className="max-h-[50vh] overflow-y-auto p-1.5">
          {items.length === 0 && <li className="px-3 py-6 text-center text-sm text-slate-500">Type at least 2 characters to search.</li>}
          {items.map((it, i) => (
            <li key={it.id} data-i={i}>
              <button
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ${
                  i === active ? "bg-brand-500/12 text-slate-900 dark:text-white" : "text-slate-700 dark:text-slate-200"
                }`}
                onMouseEnter={() => setActive(i)}
                onClick={() => onNavigate(it.route)}
              >
                <it.Icon className="h-4 w-4 shrink-0 text-slate-400" />
                <span className="min-w-0 flex-1 truncate">{it.label}</span>
                {it.hint && <span className="hidden truncate text-[11px] text-slate-500 sm:inline">{it.hint}</span>}
                {i === active && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-slate-400" />}
              </button>
            </li>
          ))}
        </ul>
        <div className="flex gap-4 border-t border-slate-200 px-4 py-2 text-[11px] text-slate-500 dark:border-white/10">
          <span>↑↓ to move</span>
          <span>↵ to open</span>
          <span className="ml-auto">Ctrl K / ⌘K anywhere</span>
        </div>
      </div>
    </div>
  );
}
