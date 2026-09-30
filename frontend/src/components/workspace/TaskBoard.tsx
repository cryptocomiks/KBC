import { ArrowLeft, ArrowRight, Bot, CalendarClock, Check, Plus, Trash2, User } from "lucide-react";
import { useMemo, useState } from "react";
import type { BoBoard, BoTask, TaskStatus } from "../../types";
import type { WorkspaceActions } from "../../lib/workspace";
import { analyst } from "../../lib/analyst";

const COLUMNS: { key: TaskStatus; title: string; hint: string }[] = [
  { key: "todo", title: "To do", hint: "generated from the cases or added by the team" },
  { key: "doing", title: "In progress", hint: "someone is on it" },
  { key: "waiting", title: "Waiting", hint: "on the client, a colleague or the compliance officer" },
  { key: "done", title: "Done", hint: "the log of work done, with who and when" },
];
const PRIORITY = {
  high: { label: "Urgent", dot: "bg-[#ff3b30]" },
  medium: { label: "Normal", dot: "bg-[#ff9f0a]" },
  low: { label: "Low", dot: "bg-slate-400" },
} as const;

const day = (v?: string | null) => (v ? new Date(v.length === 10 ? `${v}T12:00:00` : v).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");
const late = (v?: string | null) => !!v && v.slice(0, 10) < new Date().toISOString().slice(0, 10);

function Card({ t, onMove, onDelete, dragging, setDragging }: { t: BoTask; onMove: (s: TaskStatus) => void; onDelete: () => void; dragging: boolean; setDragging: (id: string | null) => void }) {
  const i = COLUMNS.findIndex((c) => c.key === t.status);
  const p = PRIORITY[t.priority] ?? PRIORITY.medium;
  return (
    <li
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData("text/plain", t.id);
        e.dataTransfer.effectAllowed = "move";
        setDragging(t.id);
      }}
      onDragEnd={() => setDragging(null)}
      className={`ws-card group cursor-grab rounded-xl border border-black/[0.06] bg-white p-3 shadow-[0_1px_2px_rgb(0_0_0/0.05)] transition-[transform,box-shadow,opacity] duration-200 hover:-translate-y-0.5 hover:shadow-[0_6px_16px_-6px_rgb(0_0_0/0.18)] active:cursor-grabbing dark:border-white/[0.08] dark:bg-[#1c1c1e] ${dragging ? "scale-[0.98] opacity-40" : ""}`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${p.dot}`} title={p.label} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className={`text-[13.5px] leading-snug font-medium ${t.status === "done" ? "text-slate-500 line-through decoration-slate-400/60" : ""}`}>{t.title}</div>
          {t.case_title &&
            (t.case_id && !t.case_id.startsWith("demo") ? (
              <a className="mt-0.5 block truncate text-[12px] text-brand-600 underline-offset-2 hover:underline" href={`#/cases/${t.case_id}${t.tab && t.tab !== "kyc" && t.tab !== "mail" ? `/${t.tab}` : ""}`}>
                {t.case_title}
              </a>
            ) : (
              <span className="mt-0.5 block truncate text-[12px] text-brand-600">{t.case_title}</span>
            ))}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-slate-500">
            <span className="sr-only">Priority: {p.label}.</span>
            {t.source === "auto" ? (
              <span className="inline-flex items-center gap-1" title="Generated from the state of the case: closes itself when resolved">
                <Bot className="h-3 w-3" aria-hidden /> automatic
              </span>
            ) : (
              <span>added by {t.created_by || "the team"}</span>
            )}
            {t.due && (
              <span className={`inline-flex items-center gap-1 ${t.status !== "done" && late(t.due) ? "font-semibold text-[#b42318] dark:text-[#ff6961]" : ""}`}>
                <CalendarClock className="h-3 w-3" aria-hidden /> {day(t.due)}
              </span>
            )}
            {t.assignee && (
              <span className="inline-flex items-center gap-1">
                <User className="h-3 w-3" aria-hidden /> {t.assignee}
              </span>
            )}
          </div>
          {t.status === "done" && t.done_at && (
            <div className="mt-1 text-[11.5px] text-[#1b7331] dark:text-[#30d158]">
              <Check className="mr-0.5 inline h-3 w-3" aria-hidden />
              {day(t.done_at)} · {t.done_by}
            </div>
          )}
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
        <button className="btn-ghost px-1.5 py-0.5 text-[11px]" disabled={i === 0} onClick={() => onMove(COLUMNS[i - 1].key)} aria-label={`Move "${t.title}" to ${COLUMNS[i - 1]?.title ?? ""}`}>
          <ArrowLeft className="h-3 w-3" />
        </button>
        <button className="btn-ghost px-1.5 py-0.5 text-[11px]" disabled={i === COLUMNS.length - 1} onClick={() => onMove(COLUMNS[i + 1].key)} aria-label={`Move "${t.title}" to ${COLUMNS[i + 1]?.title ?? ""}`}>
          <ArrowRight className="h-3 w-3" />
        </button>
        {t.status !== "done" && (
          <button className="btn-ghost px-1.5 py-0.5 text-[11px]" onClick={() => onMove("done")} aria-label={`Mark "${t.title}" as done`}>
            <Check className="h-3 w-3" /> Done
          </button>
        )}
        {t.source === "manual" && (
          <button className="btn-ghost ml-auto px-1.5 py-0.5 text-[11px] hover:text-red-600" onClick={onDelete} aria-label={`Delete "${t.title}"`}>
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>
    </li>
  );
}

/** Kanban of the team's work: drag a card, or use its arrows (keyboard). */
export default function TaskBoard({ board, actions }: { board: BoBoard; actions: WorkspaceActions }) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<TaskStatus | null>(null);
  const [mine, setMine] = useState(false);
  const [showAllDone, setShowAllDone] = useState(false);
  const [form, setForm] = useState<{ open: boolean; title: string; case_id: string; due: string; priority: BoTask["priority"]; assignee: string }>({
    open: false,
    title: "",
    case_id: "",
    due: "",
    priority: "medium",
    assignee: analyst.get(),
  });
  const me = analyst.get();
  const tasks = useMemo(() => board.tasks.filter((t) => !mine || !me || t.assignee === me), [board.tasks, mine, me]);
  const done = tasks.filter((t) => t.status === "done").sort((a, b) => (b.done_at ?? "").localeCompare(a.done_at ?? ""));

  const drop = (status: TaskStatus, e: React.DragEvent) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/plain");
    setOver(null);
    setDragging(null);
    const t = board.tasks.find((x) => x.id === id);
    if (t && t.status !== status) actions.moveTask(id, status);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary py-1.5 text-xs" onClick={() => setForm((f) => ({ ...f, open: !f.open }))} aria-expanded={form.open}>
          <Plus className="h-3.5 w-3.5" /> New task
        </button>
        {me && (
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs">
            <input type="checkbox" className="accent-brand-600" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only mine ({me})
          </label>
        )}
        <span className="ml-auto text-[12px] text-slate-500">Automatic tasks close themselves when the case is fixed. Drag a card or use its arrows.</span>
      </div>
      {form.open && (
        <form
          className="card panel-enter grid gap-2 p-4 sm:grid-cols-[1fr_180px_140px_120px_150px_auto]"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!form.title.trim()) return;
            await actions.addTask({ title: form.title.trim(), case_id: form.case_id || undefined, case_title: board.cases.find((c) => c.id === form.case_id)?.title, due: form.due || undefined, priority: form.priority, assignee: form.assignee || undefined });
            setForm((f) => ({ ...f, open: false, title: "", due: "" }));
          }}
        >
          <input className="input py-1.5 text-sm" placeholder="What needs doing?" aria-label="Task" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} autoFocus />
          <select className="input py-1.5 text-sm" aria-label="Case" value={form.case_id} onChange={(e) => setForm({ ...form, case_id: e.target.value })}>
            <option value="">No case</option>
            {board.cases.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <input type="date" className="input py-1.5 text-sm" aria-label="Due date" value={form.due} onChange={(e) => setForm({ ...form, due: e.target.value })} />
          <select className="input py-1.5 text-sm" aria-label="Priority" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as BoTask["priority"] })}>
            <option value="high">Urgent</option>
            <option value="medium">Normal</option>
            <option value="low">Low</option>
          </select>
          <input className="input py-1.5 text-sm" placeholder="Assignee" aria-label="Assignee" value={form.assignee} onChange={(e) => setForm({ ...form, assignee: e.target.value })} />
          <button className="btn-primary py-1.5 text-sm" type="submit">
            Add
          </button>
        </form>
      )}
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {COLUMNS.map((col) => {
          const rows = col.key === "done" ? (showAllDone ? done : done.slice(0, 8)) : tasks.filter((t) => t.status === col.key);
          const count = col.key === "done" ? done.length : rows.length;
          return (
            <section
              key={col.key}
              aria-labelledby={`col-${col.key}`}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(col.key);
              }}
              onDragLeave={() => setOver((o) => (o === col.key ? null : o))}
              onDrop={(e) => drop(col.key, e)}
              className={`flex min-h-[220px] flex-col rounded-2xl p-2.5 transition-colors duration-200 ${over === col.key ? "bg-brand-500/10 ring-2 ring-brand-500/40" : "bg-black/[0.03] dark:bg-white/[0.04]"}`}
            >
              <header className="mb-2 flex items-baseline gap-2 px-1">
                <h3 id={`col-${col.key}`} className="text-[13px] font-semibold">
                  {col.title}
                </h3>
                <span className="rounded-full bg-black/[0.06] px-1.5 text-[11px] font-semibold tabular-nums dark:bg-white/[0.1]">{count}</span>
              </header>
              <p className="mb-2 px-1 text-[11px] text-slate-500">{col.hint}</p>
              <ul className="flex flex-1 flex-col gap-2">
                {rows.map((t) => (
                  <Card key={t.id} t={t} dragging={dragging === t.id} setDragging={setDragging} onMove={(s) => actions.moveTask(t.id, s)} onDelete={() => actions.deleteTask(t.id)} />
                ))}
                {rows.length === 0 && <li className="rounded-xl border border-dashed border-black/[0.1] p-4 text-center text-[12px] text-slate-500 dark:border-white/[0.12]">Drop a card here</li>}
              </ul>
              {col.key === "done" && done.length > 8 && (
                <button className="btn-ghost mt-2 py-1 text-xs" onClick={() => setShowAllDone((v) => !v)}>
                  {showAllDone ? "Show the latest only" : `Show all ${done.length}`}
                </button>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
