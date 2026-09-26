import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, FileSearch, Loader2, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { api, auth, AuthError } from "./api";
import CaseScreen from "./components/CaseScreen";
import Dashboard from "./components/Dashboard";
import CandidateList from "./components/CandidateList";
import Disclaimer from "./components/Disclaimer";
import Header from "./components/Header";
import InvestigationView from "./components/InvestigationView";
import LoadingInvestigation from "./components/LoadingInvestigation";
import SearchPanel, { type SearchParams } from "./components/SearchPanel";
import { useTheme } from "./lib/theme";
import type { Entity, InvestigationParams } from "./types";

const DEFAULT_SEARCH: SearchParams = { q: "", type: "any", depth: 2, maxNodes: 60 };

export default function App() {
  const [theme, toggleTheme] = useTheme();
  const [search, setSearch] = useState<SearchParams | null>(null);
  const [target, setTarget] = useState<InvestigationParams | null>(null);
  const [page, setPage] = useState<"main" | "cases">("main");
  const [caseId, setCaseId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Pivots: investigations opened from a linked person / company, newest last.
  const [trail, setTrail] = useState<{ name: string; params: InvestigationParams }[]>([]);
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
  const pivot = (entity: Entity, from: { name: string; params: InvestigationParams }) => {
    setTrail((t) => [...t, from]);
    setTarget({ record_ids: entity.record_ids, depth: Math.min(from.params.depth, 2), max_nodes: from.params.max_nodes });
    setCaseId(null);
    setPage("main");
  };
  const back = () => {
    if (trail.length) {
      setTarget(trail[trail.length - 1].params);
      setTrail((t) => t.slice(0, -1));
    } else setTarget(null);
  };
  const home = () => {
    setTrail([]);
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
            onInvestigate={(entity, from) => {
              setTrail([]);
              pivot(entity, from);
            }}
          />
        )}
        {page === "main" && !target && (
          <>
            {!search && (
              <div className="mx-auto max-w-4xl pt-14 pb-6 text-center">
                <div className="chip mx-auto mb-7">
                  <span className="h-1.5 w-1.5 rounded-full bg-brand-500 shadow-[0_0_10px_2px_rgb(94_224_42/0.7)]" />
                  {meta.data?.demo_mode ? "Demo + live public sources" : "Live public sources"} · 40 connectors
                </div>
                <h1 className="display text-[clamp(2.6rem,6.5vw,4.6rem)]">
                  Know who is behind
                  <br />
                  any company, <span className="text-glow">now.</span>
                </h1>
                <p className="mx-auto mt-5 max-w-2xl text-[16px] leading-relaxed text-slate-600 dark:text-slate-400">
                  Registers, sanctions, PEPs, leaks, regulators and courts in one search.
                  <br className="hidden sm:block" /> Owners, red flags and the documents to request, with the source of every fact.
                </p>
                <div className="mt-7 flex flex-wrap justify-center gap-2.5">
                  {[
                    [Building2, "Registers in 10+ countries"],
                    [ShieldAlert, "32 sanctions & watch lists"],
                    [FileSearch, "Leaks, courts & regulators"],
                  ].map(([Icon, label]) => {
                    const I = Icon as typeof Building2;
                    return (
                      <span key={label as string} className="chip">
                        <I className="h-4 w-4 text-brand-600 dark:text-brand-500" /> {label as string}
                      </span>
                    );
                  })}
                </div>
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
                onPick={(c) => {
                  setTrail([]);
                  setTarget({ record_ids: c.entity.record_ids, depth: search?.depth ?? 3, max_nodes: search?.maxNodes ?? 60 });
                }}
              />
            )}
          </>
        )}

        {page === "main" && target && (
          <>
            {investigation.isLoading && (
              <LoadingInvestigation />
            )}
            {investigation.error && (
              <div className="card p-6 text-sm text-red-600">
                Investigation failed: {(investigation.error as Error).message}{" "}
                <button className="btn-outline ml-2" onClick={back}>
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
                onBack={back}
                onDepthChange={(depth) => setTarget({ ...target, depth })}
                trail={trail.map((t) => t.name)}
                onTrail={(i) => {
                  setTarget(trail[i].params);
                  setTrail((t) => t.slice(0, i));
                }}
                onInvestigate={(entity) => {
                  const inv = investigation.data!;
                  const subject = inv.entities.find((e) => e.id === inv.subject_id);
                  pivot(entity, { name: subject?.name ?? "Previous", params: inv.params });
                }}
                onSaveCase={casesStatus?.enabled ? () => saveCase.mutate(investigation.data!.params) : undefined}
                saving={saveCase.isPending}
              />
            )}
          </>
        )}
      </main>
      <footer className="border-t border-slate-200 py-3 text-center text-[11px] text-slate-500 dark:border-slate-800">
        KYC 1 CLICK v{meta.data?.version ?? "…"} · public & lawfully accessible sources only · personal data kept only in the
        local cache (clearable) · not legal advice
      </footer>
    </div>
  );
}
