import { Check, ChevronRight, ClipboardList, Copy, Mail } from "lucide-react";
import { documentRequest, openEmail } from "../lib/email";
import { useState } from "react";
import type { Investigation } from "../types";

interface Props {
  investigation: Investigation;
}

/** What to ask the client for, derived from the findings: tick, then copy as an e-mail. */
export default function DocRequests({ investigation: inv }: Props) {
  const items = inv.requests ?? [];
  const [done, setDone] = useState<Set<number>>(new Set());
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(true);
  if (!items.length) return null;
  const subject = inv.entities.find((e) => e.id === inv.subject_id);
  const pending = items.filter((_, i) => !done.has(i));

  const email = () => {
    const { subject: title, body } = documentRequest(
      subject?.name,
      pending.map((r) => r.document),
    );
    openEmail(title, body);
  };
  const copyEmail = async () => {
    const { subject: title, body } = documentRequest(
      subject?.name,
      pending.map((r) => r.document),
    );
    try {
      await navigator.clipboard.writeText(`${title}\n\n${body}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard refused: the e-mail button still works */
    }
  };

  const required = items.filter((r) => r.priority === "required").length;

  return (
    <section className="card">
      <div className="flex flex-wrap items-center gap-2 px-5 py-3">
        <h2 className="min-w-0 flex-1">
          <button type="button" className="flex w-full flex-wrap items-center gap-2 text-left" aria-expanded={open} aria-controls="doc-requests" onClick={() => setOpen((o) => !o)}>
            <ChevronRight className={`h-4 w-4 shrink-0 text-slate-500 transition-transform ${open ? "rotate-90" : ""}`} aria-hidden />
            <ClipboardList className="h-4 w-4 text-brand-600" aria-hidden />
            <span className="text-sm font-semibold">Documents to request</span>
            <span className="text-[11px] font-normal text-slate-500">
              {required} required · {items.length - required} recommended · derived from the findings
            </span>
          </button>
        </h2>
        <span className="ml-auto flex gap-1.5">
          <button className="btn-primary py-1 text-xs" onClick={email} disabled={!pending.length} title="Opens your mail app with the request written">
            <Mail className="h-3.5 w-3.5" /> E-mail the client ({pending.length})
          </button>
          <button className="btn-outline px-2.5 py-1 text-xs" onClick={copyEmail} disabled={!pending.length} aria-label="Copy the e-mail" title="Copy the e-mail text">
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
        </span>
      </div>
      {open && (
        <ul id="doc-requests" className="divide-y divide-black/[0.06] border-t border-black/[0.06] px-5 dark:divide-white/[0.08] dark:border-white/[0.08]">
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
                aria-label={`Received: ${r.document}`}
              />
              <div className={`min-w-0 flex-1 ${done.has(i) ? "text-slate-500 line-through" : ""}`}>
                <div className="text-sm">{r.document}</div>
                <div className="text-[11px] text-slate-500">{r.reason}</div>
              </div>
              <span
                className={`shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold ${
                  r.priority === "required" ? "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]" : "bg-black/[0.05] text-slate-600 dark:bg-white/[0.08] dark:text-slate-300"
                }`}
              >
                {r.priority === "required" ? "Required" : "Recommended"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
