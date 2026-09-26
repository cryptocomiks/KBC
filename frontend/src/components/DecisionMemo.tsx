import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, FileDown, Loader2, RotateCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { analyst } from "../lib/analyst";
import { fmtDate } from "../lib/format";

/** Renders the memo's light markup: "# " title, "## " section, "- " bullets, [placeholders] highlighted. */
function Preview({ text }: { text: string }) {
  const mark = (s: string) =>
    s.split(/(\[[^\]]*\])/g).map((part, i) =>
      part.startsWith("[") && part.endsWith("]") ? (
        <mark key={i} className="rounded bg-amber-500/15 px-0.5 text-amber-800 dark:text-amber-300">
          {part}
        </mark>
      ) : (
        part
      ),
    );
  return (
    <div className="space-y-1 text-[13px] leading-relaxed">
      {text.split("\n").map((line, i) => {
        if (line.startsWith("# ")) return <h2 key={i} className="text-lg font-semibold">{mark(line.slice(2))}</h2>;
        if (line.startsWith("## "))
          return (
            <h3 key={i} className="mt-4 border-b border-brand-500/40 pb-1 text-[14px] font-semibold text-slate-900 dark:text-white">
              {mark(line.slice(3))}
            </h3>
          );
        if (line.startsWith("  - ")) return <p key={i} className="pl-8 text-slate-600 dark:text-slate-400">– {mark(line.slice(4))}</p>;
        if (line.startsWith("- ")) return <p key={i} className="pl-3">• {mark(line.slice(2))}</p>;
        if (!line.trim()) return <div key={i} className="h-1" />;
        return <p key={i} className="text-slate-500">{mark(line)}</p>;
      })}
    </div>
  );
}

/** Decision memo tab: a draft written from the case, edited by the analyst, saved and exported. */
export default function DecisionMemo({ caseId }: { caseId: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["memo", caseId], queryFn: () => api.getMemo(caseId) });
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (q.data) setText(q.data.text);
  }, [q.data]);
  const save = useMutation({
    mutationFn: () => api.saveMemo(caseId, text, analyst.get() || "analyst"),
    onSuccess: (m) => qc.setQueryData(["memo", caseId], m),
  });
  const regenerate = useMutation({
    mutationFn: () => api.getMemo(caseId, true),
    onSuccess: (m) => {
      setText(m.text);
      setMode("edit");
    },
  });
  const pdf = useMutation({
    mutationFn: async () => {
      if (!q.data || q.data.draft || text !== q.data.text) await save.mutateAsync();
      await api.downloadMemo(caseId);
    },
  });

  if (q.isLoading)
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-slate-500">
        <Loader2 className="h-5 w-5 animate-spin" /> Writing the memo from the case…
      </div>
    );
  if (q.error) return <div className="card p-6 text-sm text-red-600">{(q.error as Error).message}</div>;
  const m = q.data!;
  const dirty = text !== m.text || m.draft;
  const placeholders = (text.match(/\[[^\]]*\]/g) ?? []).length;

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-white/10">
        <div className="min-w-0 flex-1">
          <div className="tag">Decision memo</div>
          <div className="text-[12px] text-slate-500">
            {m.draft
              ? "Draft written from the case — review, complete the [placeholders], then save."
              : `Saved${m.updated_by ? ` by ${m.updated_by}` : ""}${m.updated_at ? ` on ${fmtDate(m.updated_at)}` : ""}.`}
            {placeholders > 0 && <span className="ml-1 text-amber-700 dark:text-amber-300">{placeholders} placeholder(s) left.</span>}
          </div>
        </div>
        <div className="segmented text-xs">
          {(["preview", "edit"] as const).map((k) => (
            <button
              key={k}
              className={`rounded-full px-3 py-1 font-medium ${mode === k ? "bg-white shadow-sm dark:bg-white/10" : "text-slate-500"}`}
              onClick={() => setMode(k)}
            >
              {k === "preview" ? "Preview" : "Edit"}
            </button>
          ))}
        </div>
        <button
          className="btn-ghost py-1.5 text-xs"
          disabled={regenerate.isPending}
          onClick={() => (!dirty || window.confirm("Replace your text with a fresh draft from the current case?")) && regenerate.mutate()}
          title="Write a fresh draft from the current state of the case"
        >
          {regenerate.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />} Redraft
        </button>
        <button
          className="btn-ghost py-1.5 text-xs"
          onClick={async () => {
            await navigator.clipboard.writeText(text).catch(() => undefined);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} Copy
        </button>
        <button className="btn-outline py-1.5 text-xs" disabled={save.isPending || !dirty} onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save
        </button>
        <button className="btn-primary py-1.5 text-xs" disabled={pdf.isPending} onClick={() => pdf.mutate()}>
          {pdf.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileDown className="h-3.5 w-3.5" />} PDF
        </button>
      </div>
      {(save.error || pdf.error || regenerate.error) && (
        <p className="px-4 pt-2 text-xs text-red-600">{((save.error || pdf.error || regenerate.error) as Error).message}</p>
      )}
      <div className="p-5">
        {mode === "edit" ? (
          <textarea
            className="input h-[70vh] w-full resize-y font-mono text-[12.5px] leading-relaxed"
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck
          />
        ) : (
          <Preview text={text} />
        )}
      </div>
    </div>
  );
}
