import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";
import { api, AuthError } from "../api";
import type { Theme } from "../lib/theme";
import type { Decision, DecisionValue, Entity, InvestigationParams } from "../types";
import CaseBar from "./CaseBar";
import ImportPending from "./ImportPending";
import InvestigationView from "./InvestigationView";
import KycQuestionnaire from "./KycQuestionnaire";
import PasswordGate from "./PasswordGate";

interface Props {
  caseId: string;
  theme: Theme;
  onBack: () => void;
  onInvestigate?: (entity: Entity, from: { name: string; params: InvestigationParams }) => void;
}

/** A saved case: case bar (monitoring, changes, notes) above the investigation, with analyst decisions. */
export default function CaseScreen({ caseId, theme, onBack, onInvestigate }: Props) {
  const [attempt, setAttempt] = useState(0);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["case", caseId, attempt], queryFn: () => api.getCase(caseId), retry: false });
  const decide = useMutation({
    mutationFn: (d: { item_key: string; item_label: string; decision: DecisionValue | "none"; comment: string }) =>
      api.decide(caseId, d),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["case", caseId] }),
  });
  const decisions = useMemo(
    () => Object.fromEntries((q.data?.decisions ?? []).map((d: Decision) => [d.item_key, d])),
    [q.data?.decisions],
  );

  if (q.error instanceof AuthError) return <PasswordGate wrong={attempt > 0} onUnlock={() => setAttempt((a) => a + 1)} />;
  if (q.isLoading || !q.data) {
    return q.error ? (
      <div className="card p-6 text-sm text-red-600">{(q.error as Error).message}</div>
    ) : (
      <div className="flex items-center justify-center gap-2 py-24 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" /> Opening the case…
      </div>
    );
  }
  const inv = q.data.investigation;
  if (!inv) return <ImportPending view={q.data} onBack={onBack} />;
  return (
    <div className="space-y-4">
      <CaseBar key={q.data.case.updated_at} view={q.data} onDeleted={onBack} />
      <KycQuestionnaire key={`${caseId}-${q.data.questionnaire.answered_at ?? ""}`} caseId={caseId} data={q.data.questionnaire} />
      <InvestigationView
        investigation={inv}
        theme={theme}
        refreshing={q.isFetching || decide.isPending}
        onBack={onBack}
        caseId={caseId}
        onInvestigate={
          onInvestigate &&
          ((entity) =>
            onInvestigate(entity, { name: q.data!.case.subject_name as string, params: inv.params }))
        }
        decisions={decisions}
        onDecide={(key, label, decision) => {
          const comment =
            decision === "none" ? "" : (window.prompt("Comment for the audit trail (optional):", decisions[key]?.comment ?? "") ?? "");
          decide.mutate({ item_key: key, item_label: label, decision, comment });
        }}
      />
    </div>
  );
}
