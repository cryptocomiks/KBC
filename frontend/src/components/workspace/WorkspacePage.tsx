import { CalendarCheck2, Clock, Inbox, KanbanSquare, Mail, PackageCheck, TimerReset } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";
import type { CasesStatus } from "../../types";
import type { WorkspaceTab } from "../../lib/route";
import { useWorkspace } from "../../lib/workspace";
import PasswordGate from "../PasswordGate";
import { BlockSkeleton } from "../Skeleton";
import { Tile } from "../viz";
import MailCenter from "./MailCenter";
import Receptions from "./Receptions";
import TaskBoard from "./TaskBoard";
import TimeSaved from "./TimeSaved";

const TABS: { key: WorkspaceTab; label: string; Icon: typeof Mail }[] = [
  { key: "tasks", label: "Tasks", Icon: KanbanSquare },
  { key: "mail", label: "E-mails", Icon: Mail },
  { key: "receptions", label: "Receptions", Icon: PackageCheck },
  { key: "time", label: "Time saved", Icon: TimerReset },
];

/** The back office of a KYC team: what to do, what to send, what is awaited, and the time it saves. */
export default function WorkspacePage({ tab, onTab, status }: { tab: WorkspaceTab; onTab: (t: WorkspaceTab) => void; status?: CasesStatus }) {
  const [lang, setLang] = useState<"en" | "fr">("fr");
  const [focusCase, setFocusCase] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const ws = useWorkspace(lang, status?.enabled);
  const strip = useRef<HTMLDivElement>(null);
  const [pill, setPill] = useState<{ left: number; width: number } | null>(null);

  // Sliding highlight under the active tab.
  useLayoutEffect(() => {
    const el = strip.current?.querySelector<HTMLElement>(`[data-tab="${tab}"]`);
    if (el) setPill({ left: el.offsetLeft, width: el.offsetWidth });
  }, [tab, ws.board]);

  if (ws.authError) return <PasswordGate wrong={attempt > 0} onUnlock={() => (setAttempt((a) => a + 1), ws.retry())} />;
  const b = ws.board;
  const s = b?.stats;

  return (
    <div className="panel-enter mx-auto max-w-[1400px] space-y-6 pb-10">
      <div className="pt-4 text-center">
        <div className="eyebrow">Workspace</div>
        <h1 className="headline mt-2 text-[clamp(1.9rem,4vw,3rem)]">The whole team&apos;s KYC work, in one place.</h1>
        <p className="subhead mx-auto mt-2 max-w-2xl text-[16px] text-slate-500">
          Tasks drawn from every case, the letters to send, the documents awaited and the time it all saves.
        </p>
      </div>

      {ws.demo && (
        <div className="card flex flex-wrap items-center gap-2 border border-brand-500/20 bg-brand-500/[0.06] p-3 text-[13px]" role="note">
          <span className="rounded-full bg-brand-500 px-2 py-0.5 text-[11px] font-semibold text-white">Demo</span>
          Fictitious clients: try everything, nothing is saved. With cases switched on (Vercel: APP_PASSWORD and a database), this board is shared by the whole team.
        </div>
      )}
      {ws.error && <div className="card p-4 text-sm text-red-600 dark:text-red-400">{ws.error}</div>}

      {!b || !s ? (
        <BlockSkeleton rows={6} />
      ) : (
        <>
          <section aria-label="Today" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Tile label="Open tasks" value={s.tasks_open} sub={`${s.tasks_high} urgent`} tone={s.tasks_high ? "critical" : "good"} icon={<KanbanSquare className="h-3.5 w-3.5" aria-hidden />} onClick={() => onTab("tasks")} />
            <Tile label="Done this week" value={s.tasks_done_week} sub="tasks closed" tone="good" icon={<CalendarCheck2 className="h-3.5 w-3.5" aria-hidden />} onClick={() => onTab("tasks")} />
            <Tile label="E-mails to send" value={s.mails_draft} sub={`${s.mails_sent_week} sent this week`} tone={s.mails_draft ? "accent" : "good"} icon={<Mail className="h-3.5 w-3.5" aria-hidden />} onClick={() => onTab("mail")} />
            <Tile label="Documents awaited" value={s.docs_awaited} sub={`${s.docs_to_request} still to request`} tone="warning" icon={<Inbox className="h-3.5 w-3.5" aria-hidden />} onClick={() => onTab("receptions")} />
            <Tile label="Overdue" value={s.docs_overdue} sub={s.follow_ups_due ? `${s.follow_ups_due} follow-up(s) due` : "past the deadline"} tone={s.docs_overdue ? "critical" : "good"} icon={<Clock className="h-3.5 w-3.5" aria-hidden />} onClick={() => onTab("receptions")} />
            <Tile
              label="Received"
              value={`${s.docs_received}/${s.docs_total}`}
              sub={s.median_days_to_receive != null ? `in ${s.median_days_to_receive} days (median)` : "no delay measured yet"}
              tone="good"
              icon={<PackageCheck className="h-3.5 w-3.5" aria-hidden />}
              meter={{ value: s.docs_received, max: Math.max(1, s.docs_total), tone: "good" }}
              onClick={() => onTab("receptions")}
            />
          </section>

          <div ref={strip} role="tablist" aria-label="Workspace" className="relative mx-auto flex w-fit max-w-full gap-1 overflow-x-auto rounded-full bg-black/[0.05] p-1 dark:bg-white/[0.08]">
            {pill && <span aria-hidden className="ws-pill absolute top-1 bottom-1 rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.14)] dark:bg-slate-600" style={{ left: pill.left, width: pill.width }} />}
            {TABS.map((t) => {
              const badge = t.key === "tasks" ? s.tasks_open : t.key === "mail" ? s.mails_draft : t.key === "receptions" ? s.docs_overdue : 0;
              return (
                <button
                  key={t.key}
                  data-tab={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => onTab(t.key)}
                  className={`relative z-10 inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-[13px] font-medium whitespace-nowrap transition-colors ${tab === t.key ? "text-[#1d1d1f] dark:text-white" : "text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"}`}
                >
                  <t.Icon className="h-4 w-4" aria-hidden /> {t.label}
                  {badge > 0 && <span className="rounded-full bg-white/90 px-1.5 text-[11px] text-[#1d1d1f] tabular-nums dark:bg-white/[0.14] dark:text-white">{badge}</span>}
                </button>
              );
            })}
          </div>

          <div key={tab} role="tabpanel" aria-label={TABS.find((t) => t.key === tab)?.label} className="ws-panel">
            {tab === "tasks" && <TaskBoard board={b} actions={ws.actions} />}
            {tab === "mail" && <MailCenter board={b} actions={ws.actions} lang={lang} setLang={setLang} focusCase={focusCase} />}
            {tab === "receptions" && (
              <Receptions
                board={b}
                actions={ws.actions}
                onRemind={(id) => {
                  setFocusCase(id);
                  onTab("mail");
                }}
              />
            )}
            {tab === "time" && <TimeSaved />}
          </div>
        </>
      )}
    </div>
  );
}
