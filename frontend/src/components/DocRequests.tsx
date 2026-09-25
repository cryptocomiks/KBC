import { Check, ClipboardList, Copy } from "lucide-react";
import { useState } from "react";
import type { Investigation } from "../types";

interface Props {
  investigation: Investigation;
}

/** What to ask the client for, derived from the findings — tick, then copy as an e-mail. */
export default function DocRequests({ investigation: inv }: Props) {
  const items = inv.requests ?? [];
  const [done, setDone] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState(false);
  if (!items.length) return null;
  const subject = inv.entities.find((e) => e.id === inv.subject_id);
  const pending = items.filter((_, i) => !done.has(i));

  const copyEmail = async () => {
    const lines = pending.map((r, i) => `${i + 1}. ${r.document}`);
    const text = [
      `Subject: Documents required — ${subject?.name ?? "your file"}`,
      "",
      "Dear client,",
      "",
      "As part of our customer due diligence obligations, we kindly ask you to provide the following documents:",
      "",
      ...lines,
      "",
      "Documents should be recent (less than 3 months old for register extracts and proofs of address) and certified where applicable.",
      "",
      "Thank you for your cooperation.",
      "Kind regards,",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy the e-mail:", text);
    }
  };

  return (
    <details className="card group" open>
      <summary className="flex cursor-pointer items-center gap-2 px-5 py-3">
        <ClipboardList className="h-4 w-4 text-brand-600" />
        <span className="text-sm font-semibold">Documents to request</span>
        <span className="text-[11px] text-slate-500">
          {items.filter((r) => r.priority === "required").length} required · {items.length - items.filter((r) => r.priority === "required").length} recommended ·
          derived from the findings
        </span>
        <button
          className="btn-outline ml-auto py-1 text-xs"
          onClick={(e) => {
            e.preventDefault();
            copyEmail();
          }}
          disabled={!pending.length}
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : `Copy as e-mail to the client (${pending.length})`}
        </button>
      </summary>
      <ul className="divide-y divide-black/[0.06] border-t border-black/[0.06] px-5 dark:divide-white/[0.08] dark:border-white/[0.08]">
        {items.map((r, i) => (
          <li key={r.document} className="flex items-start gap-3 py-2">
            <input
              type="checkbox"
              className="mt-1 accent-brand-600"
              checked={done.has(i)}
              onChange={() =>
                setDone((d) => {
                  const n = new Set(d);
                  if (n.has(i)) n.delete(i);
                  else n.add(i);
                  return n;
                })
              }
              aria-label="Received"
            />
            <div className={`min-w-0 flex-1 ${done.has(i) ? "opacity-50 line-through" : ""}`}>
              <div className="text-sm">{r.document}</div>
              <div className="text-[11px] text-slate-500">{r.reason}</div>
            </div>
            <span
              className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold ${
                r.priority === "required"
                  ? "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]"
                  : "bg-black/[0.05] text-slate-600 dark:bg-white/[0.08] dark:text-slate-300"
              }`}
            >
              {r.priority === "required" ? "Required" : "Recommended"}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}
