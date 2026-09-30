import { BellRing, Check, Copy, Inbox, Mail, PenLine, Plus, Send, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { BoBoard, BoMail } from "../../types";
import type { WorkspaceActions } from "../../lib/workspace";
import { openEmail } from "../../lib/email";

const TYPE = {
  request: { label: "Document request", cls: "bg-brand-500/10 text-brand-700 dark:text-[#2997ff]" },
  reminder: { label: "Reminder", cls: "bg-[#dc6803]/15 text-[#b54708] dark:text-[#fec84b]" },
  review: { label: "Periodic review", cls: "bg-violet-500/10 text-violet-700 dark:text-violet-300" },
  custom: { label: "E-mail", cls: "bg-black/[0.05] text-slate-600 dark:bg-white/[0.08] dark:text-slate-300" },
} as const;
const when = (v?: string | null) => (v ? new Date(v.length === 10 ? `${v}T12:00:00` : v).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "");

/** Outbox: letters drafted from the cases, edited, sent from the analyst's own mail app, then logged. */
export default function MailCenter({
  board,
  actions,
  lang,
  setLang,
  focusCase,
}: {
  board: BoBoard;
  actions: WorkspaceActions;
  lang: "en" | "fr";
  setLang: (l: "en" | "fr") => void;
  focusCase?: string | null;
}) {
  const [box, setBox] = useState<"draft" | "sent">("draft");
  const list = useMemo(() => board.mails.filter((m) => m.status === box), [board.mails, box]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ to: string; subject: string; body: string }>({ to: "", subject: "", body: "" });
  const [opened, setOpened] = useState(false);
  const [copied, setCopied] = useState(false);
  const mail = board.mails.find((m) => m.id === selected) ?? list[0];

  useEffect(() => {
    if (focusCase) {
      const m = board.mails.find((x) => x.case_id === focusCase && x.status === "draft" && x.type === "reminder") ?? board.mails.find((x) => x.case_id === focusCase && x.status === "draft");
      if (m) {
        setBox("draft");
        setSelected(m.id);
      }
    }
  }, [focusCase, board.mails]);

  useEffect(() => {
    if (mail) setDraft({ to: mail.to ?? "", subject: mail.subject, body: mail.body });
    setOpened(false);
  }, [mail?.id, mail?.subject, mail?.body, mail?.to]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = !!mail && mail.status === "draft" && (draft.to !== (mail.to ?? "") || draft.subject !== mail.subject || draft.body !== mail.body);
  const save = async () => {
    if (mail && dirty) await actions.editMail(mail.id, draft);
  };
  const pending = (m: BoMail) => board.receptions.filter((r) => r.case_id === m.case_id && m.documents.includes(r.key) && r.status !== "received").length;
  const counts = { draft: board.mails.filter((m) => m.status === "draft").length, sent: board.mails.filter((m) => m.status === "sent").length };

  return (
    <div className="grid gap-3 lg:grid-cols-[340px_minmax(0,1fr)]">
      <section className="card flex flex-col overflow-hidden" aria-label="Mailboxes">
        <div className="flex items-center gap-2 border-b border-black/[0.06] p-3 dark:border-white/[0.08]">
          <div className="segmented" role="group" aria-label="Mailbox">
            {(["draft", "sent"] as const).map((k) => (
              <button
                key={k}
                aria-pressed={box === k}
                onClick={() => {
                  setBox(k);
                  setSelected(null);
                }}
                className={`rounded-[8px] px-2.5 py-1 text-xs font-medium ${box === k ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}
              >
                {k === "draft" ? `To send · ${counts.draft}` : `Sent · ${counts.sent}`}
              </button>
            ))}
          </div>
          <button
            className="btn-ghost ml-auto px-2 py-1 text-xs"
            onClick={async () => {
              const id = await actions.newMail({ subject: "", body: "" });
              setBox("draft");
              if (id) setSelected(id);
            }}
            aria-label="New e-mail"
          >
            <Plus className="h-3.5 w-3.5" /> New
          </button>
        </div>
        <ul className="max-h-[560px] flex-1 divide-y divide-black/[0.05] overflow-y-auto dark:divide-white/[0.06]" tabIndex={0} aria-label={box === "draft" ? "E-mails to send" : "Sent e-mails"}>
          {list.length === 0 && (
            <li className="flex flex-col items-center gap-2 p-8 text-center text-[13px] text-slate-500">
              <Inbox className="h-6 w-6" aria-hidden /> {box === "draft" ? "Nothing to send: every client has what they need." : "No e-mail sent yet."}
            </li>
          )}
          {list.map((m) => {
            const t = TYPE[m.type] ?? TYPE.custom;
            const active = m.id === mail?.id;
            const wait = m.status === "sent" ? pending(m) : 0;
            const followUp = m.status === "sent" && wait > 0 && (m.follow_up ?? "9999") <= new Date().toISOString().slice(0, 10);
            return (
              <li key={m.id}>
                <button onClick={() => setSelected(m.id)} aria-current={active ? "true" : undefined} className={`w-full px-3 py-2.5 text-left transition-colors ${active ? "bg-brand-500/10" : "hover:bg-black/[0.03] dark:hover:bg-white/[0.04]"}`}>
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${t.cls}`}>{m.type === "reminder" && m.reminder ? `Reminder ${m.reminder}` : t.label}</span>
                    {followUp && (
                      <span className="inline-flex items-center gap-1 text-[10.5px] font-semibold text-[#b54708] dark:text-[#fec84b]">
                        <BellRing className="h-3 w-3" aria-hidden /> follow up
                      </span>
                    )}
                    <span className="ml-auto text-[11px] text-slate-500">{when(m.sent_at ?? m.created_at)}</span>
                  </div>
                  <div className="mt-1 truncate text-[13px] font-medium">{m.subject || "(no subject)"}</div>
                  <div className="truncate text-[12px] text-slate-500">
                    {m.case_title || "No case"} · {m.to || "address to add"}
                    {m.status === "sent" && m.documents.length > 0 && ` · ${m.documents.length - wait}/${m.documents.length} received`}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="card min-w-0 p-4" aria-label="E-mail">
        {!mail ? (
          <p className="p-8 text-center text-sm text-slate-500">Select an e-mail.</p>
        ) : (
          <div key={mail.id} className="panel-enter space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${(TYPE[mail.type] ?? TYPE.custom).cls}`}>{(TYPE[mail.type] ?? TYPE.custom).label}</span>
              {mail.case_id && !mail.case_id.startsWith("demo") ? (
                <a className="text-[13px] text-brand-600 underline underline-offset-2" href={`#/cases/${mail.case_id}`}>
                  {mail.case_title}
                </a>
              ) : (
                <span className="text-[13px] text-slate-500">{mail.case_title}</span>
              )}
              {mail.status === "draft" && mail.type !== "custom" && (
                <div className="segmented ml-auto" role="group" aria-label="Language of the letter">
                  {(["fr", "en"] as const).map((l) => (
                    <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)} className={`rounded-[8px] px-2.5 py-1 text-xs font-medium ${lang === l ? "bg-white shadow-[0_1px_3px_rgb(0_0_0/0.12)] dark:bg-slate-600" : "text-slate-500"}`}>
                      {l === "fr" ? "Français" : "English"}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {mail.status === "sent" ? (
              <div className="rounded-xl bg-[#248a3d]/10 px-3 py-2 text-[13px] text-[#1b7331] dark:text-[#30d158]">
                <Check className="mr-1 inline h-3.5 w-3.5" aria-hidden />
                Sent on {when(mail.sent_at)} by {mail.sent_by}
                {mail.follow_up && ` · follow-up on ${when(mail.follow_up)}`}
                {mail.documents.length > 0 && ` · ${mail.documents.length - pending(mail)} of ${mail.documents.length} documents received`}
              </div>
            ) : null}
            <label className="block text-xs">
              <span className="label mb-1 block">To</span>
              <input className="input w-full py-1.5 text-sm" type="email" value={draft.to} readOnly={mail.status === "sent"} placeholder="client@company.com" onChange={(e) => setDraft({ ...draft, to: e.target.value })} onBlur={save} />
            </label>
            <label className="block text-xs">
              <span className="label mb-1 block">Subject</span>
              <input className="input w-full py-1.5 text-sm" value={draft.subject} readOnly={mail.status === "sent"} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} onBlur={save} />
            </label>
            <label className="block text-xs">
              <span className="label mb-1 block">Message</span>
              <textarea className="input h-72 w-full text-[13px] leading-relaxed" value={draft.body} readOnly={mail.status === "sent"} onChange={(e) => setDraft({ ...draft, body: e.target.value })} onBlur={save} />
            </label>
            {mail.status === "draft" && (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn-primary py-1.5 text-sm"
                  onClick={async () => {
                    await save();
                    openEmail(draft.subject, draft.body, draft.to);
                    setOpened(true);
                  }}
                >
                  <Mail className="h-4 w-4" /> Open in my mail app
                </button>
                <button
                  className={`${opened ? "btn-primary" : "btn-outline"} py-1.5 text-sm`}
                  onClick={async () => {
                    await save();
                    await actions.mailSent(mail.id);
                    setBox("sent");
                  }}
                >
                  <Send className="h-4 w-4" /> {opened ? "I sent it: mark as sent" : "Mark as sent"}
                </button>
                <button
                  className="btn-ghost py-1.5 text-sm"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1800);
                    } catch {
                      /* clipboard refused */
                    }
                  }}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} Copy
                </button>
                <button className="btn-ghost ml-auto py-1.5 text-sm hover:text-red-600" onClick={() => actions.deleteMail(mail.id)}>
                  <Trash2 className="h-4 w-4" /> Discard
                </button>
                {dirty && (
                  <span className="inline-flex w-full items-center gap-1 text-[11.5px] text-slate-500">
                    <PenLine className="h-3 w-3" aria-hidden /> Your changes are saved when you leave the field.
                  </span>
                )}
              </div>
            )}
            <p className="text-[11.5px] text-slate-500">
              The e-mail leaves from your own mail app: nothing is sent by the server. Marking it as sent starts the clock on the documents it asks for (14 days, 7 after a
              reminder).
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
