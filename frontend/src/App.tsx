import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { api, auth, AuthError } from "./api";
import CaseScreen from "./components/CaseScreen";
import Dashboard from "./components/Dashboard";
import CandidateList from "./components/CandidateList";
import Disclaimer from "./components/Disclaimer";
import Header from "./components/Header";
import InvestigationView from "./components/InvestigationView";
import SearchPanel, { type SearchParams } from "./components/SearchPanel";
import { useTheme } from "./lib/theme";
import type { InvestigationParams } from "./types";

const DEFAULT_SEARCH: SearchParams = { q: "", type: "any", depth: 2, maxNodes: 60 };

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [search, setSearch] = useState<SearchParams | null>(null);
  const [target, setTarget] = useState<InvestigationParams | null>(null);
  const [page, setPage] = useState<"main" | "cases">("main");
  const [caseId, setCaseId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const qc = useQueryClient();

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const connectors = useQuery({ queryKey: ["connectors"], queryFn: api.connectors });
  const live = !!connectors.data?.some((c) => c.enabled && !c.demo);
  const results = useQuery({
    queryKey: ["search", search?.q, search?.type],
    queryFn: () => api.search(search!.q, search!.type),
    enabled: !!search,
  });
  const investigation = useQuery({
    queryKey: ["investigation", target],
    queryFn: () => api.investigate(target!),
    enabled: !!target,
    // Keep the current graph on screen only while changing the depth of the same subject;
    // a new subject never shows the previous investigation.
    placeholderData: (previous, previousQuery) => {
      const prev = previousQuery?.queryKey[1] as InvestigationParams | undefined;
      const same = prev && target && prev.record_ids.join("|") === target.record_ids.join("|");
      return same ? keepPreviousData(previous) : undefined;
    },
  });

  const casesStatus = meta.data?.cases;
  const home = () => {
    setSearch(null);
    setTarget(null);
    setCaseId(null);
    setPage("main");
  };
  const openCase = (id: string) => {
    setCaseId(id);
    setPage("cases");
  };
  const saveCase = useMutation({
    mutationFn: (p: InvestigationParams) => api.createCase(p),
    onSuccess: (c) => {
      setSaveError(null);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      openCase(c.id);
    },
    onError: (e, params) => {
      if (e instanceof AuthError) {
        const pw = window.prompt("Password for cases (APP_PASSWORD):");
        if (pw) {
          auth.set(pw);
          saveCase.mutate(params);
          return;
        }
      }
      setSaveError(e instanceof AuthError ? "Password required to save cases." : (e as Error).message);
    },
  });

  return (
    <div className="flex min-h-full flex-col">
      <Header
        meta={meta.data}
        theme={theme}
        onToggleTheme={toggleTheme}
        onHome={home}
        onCases={() => {
          setCaseId(null);
          setPage("cases");
        }}
        casesActive={page === "cases"}
      />
      <Disclaimer text={meta.data?.disclaimer} />
      <main className="mx-auto w-full max-w-[1600px] flex-1 space-y-5 px-4 py-5">
        {page === "cases" && !caseId && <Dashboard status={casesStatus} onOpenCase={openCase} />}
        {page === "cases" && caseId && (
          <CaseScreen
            caseId={caseId}
            theme={theme}
            onBack={() => setCaseId(null)}
          />
        )}
        {page === "main" && !target && (
          <>
            {!search && (
              <div className="mx-auto max-w-3xl pt-8 text-center">
                <h1 className="text-3xl font-bold tracking-tight">Map who owns and controls what.</h1>
                <p className="mt-2 text-slate-600 dark:text-slate-400">
                  Search a person or a company across public registries, sanctions/PEP lists and leak databases. KBC resolves
                  homonyms, deduplicates entities across sources, expands the ownership network and explains every red flag,
                  with full source traceability.
                </p>
              </div>
            )}
            <SearchPanel initial={search ?? DEFAULT_SEARCH} demo={!!meta.data?.demo_mode} live={live} onSearch={setSearch} />
            {results.isFetching && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" /> Searching sources…
              </div>
            )}
            {results.error && <div className="text-sm text-red-600">Search failed: {(results.error as Error).message}</div>}
            {results.data && !results.isFetching && (
              <CandidateList
                data={results.data}
                onPick={(c) =>
                  setTarget({ record_ids: c.entity.record_ids, depth: search?.depth ?? 3, max_nodes: search?.maxNodes ?? 60 })
                }
              />
            )}
          </>
        )}

        {page === "main" && target && (
          <>
            {investigation.isLoading && (
              <div className="flex items-center justify-center gap-2 py-24 text-slate-500">
                <Loader2 className="h-5 w-5 animate-spin" /> Expanding the network, resolving entities and screening…
              </div>
            )}
            {investigation.error && (
              <div className="card p-6 text-sm text-red-600">
                Investigation failed: {(investigation.error as Error).message}{" "}
                <button className="btn-outline ml-2" onClick={() => setTarget(null)}>
                  Back
                </button>
              </div>
            )}
            {saveError && <div className="text-sm text-red-600">Could not save the case: {saveError}</div>}
            {investigation.data && (
              <InvestigationView
                investigation={investigation.data}
                theme={theme}
                refreshing={investigation.isFetching}
                onBack={() => setTarget(null)}
                onDepthChange={(depth) => setTarget({ ...target, depth })}
                onSaveCase={casesStatus?.enabled ? () => saveCase.mutate(investigation.data!.params) : undefined}
                saving={saveCase.isPending}
              />
            )}
          </>
        )}
      </main>
      <footer className="border-t border-slate-200 py-3 text-center text-[11px] text-slate-500 dark:border-slate-800">
        KBC Corporate Mapping v{meta.data?.version ?? "…"} · public & lawfully accessible sources only · personal data kept only in the
        local cache (clearable) · not legal advice
      </footer>
    </div>
  );
}
