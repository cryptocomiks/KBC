import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { api, AuthError } from "../api";
import type { BoBoard, BoMail, BoReception, BoStats, BoTask, TaskStatus } from "../types";
import { analyst } from "./analyst";

const iso = () => new Date().toISOString().slice(0, 19) + "+00:00";
const plusDays = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString().slice(0, 10);
const today = () => new Date().toISOString().slice(0, 10);

/** Same figures as the server computes (used by the demo board, which lives in the browser). */
export function computeStats(b: Omit<BoBoard, "stats">): BoStats {
  const week = new Date(Date.now() - 7 * 86_400_000).toISOString();
  const month = new Date(Date.now() - 30 * 86_400_000).toISOString();
  const r = b.receptions;
  const delays = r
    .filter((x) => x.status === "received" && x.requested_at && x.received_at)
    .map((x) => Math.max(0, Math.round((Date.parse(x.received_at!.slice(0, 10)) - Date.parse(x.requested_at!.slice(0, 10))) / 86_400_000)))
    .sort((a, c) => a - c);
  const median = delays.length ? (delays.length % 2 ? delays[(delays.length - 1) / 2] : (delays[delays.length / 2 - 1] + delays[delays.length / 2]) / 2) : null;
  return {
    cases: b.cases.length,
    tasks_open: b.tasks.filter((t) => t.status !== "done").length,
    tasks_high: b.tasks.filter((t) => t.status !== "done" && t.priority === "high").length,
    tasks_done_week: b.tasks.filter((t) => t.status === "done" && (t.done_at ?? "") >= week).length,
    mails_draft: b.mails.filter((m) => m.status === "draft").length,
    mails_sent_week: b.mails.filter((m) => m.status === "sent" && (m.sent_at ?? "") >= week).length,
    follow_ups_due: b.mails.filter(
      (m) => m.status === "sent" && (m.follow_up ?? "9999") <= today() && r.some((x) => x.case_id === m.case_id && m.documents.includes(x.key) && x.status !== "received"),
    ).length,
    docs_total: r.length,
    docs_received: r.filter((x) => x.status === "received").length,
    docs_received_month: r.filter((x) => x.status === "received" && (x.received_at ?? "") >= month).length,
    docs_awaited: r.filter((x) => x.status === "awaited").length,
    docs_overdue: r.filter((x) => x.status === "overdue").length,
    docs_to_request: r.filter((x) => x.status === "to_request").length,
    median_days_to_receive: median,
  };
}

/** Demo board (fictitious cases), shifted so that its dates stay relative to today. */
async function loadDemo(): Promise<BoBoard> {
  const raw = (await import("../demo/workspace.json")).default as unknown as BoBoard & { recorded_on: string };
  const shift = Date.now() - Date.parse(raw.recorded_on);
  const move = (v?: string | null) => (v ? new Date(Date.parse(v.length === 10 ? `${v}T12:00:00Z` : v) + shift).toISOString().slice(0, v.length === 10 ? 10 : 19) + (v.length === 10 ? "" : "+00:00") : v);
  // "demo-" ids: the pages do not link to cases that do not exist on this server
  const cid = (v?: string | null) => (v ? `demo-${v}` : v);
  const b: BoBoard = {
    ...raw,
    cases: raw.cases.map((c) => ({ ...c, id: cid(c.id)! })),
    tasks: raw.tasks.map((t) => ({ ...t, case_id: cid(t.case_id), created_at: move(t.created_at)!, done_at: move(t.done_at), due: move(t.due) })),
    mails: raw.mails.map((m) => ({ ...m, case_id: cid(m.case_id), created_at: move(m.created_at)!, sent_at: move(m.sent_at), follow_up: move(m.follow_up) })),
    receptions: raw.receptions.map((x) => ({ ...x, case_id: cid(x.case_id)!, requested_at: move(x.requested_at), due_at: move(x.due_at), received_at: move(x.received_at), last_reminder_at: move(x.last_reminder_at) })),
  };
  return { ...b, stats: computeStats(b) };
}

export interface WorkspaceActions {
  moveTask: (id: string, status: TaskStatus) => Promise<void>;
  updateTask: (id: string, patch: Partial<BoTask>) => Promise<void>;
  addTask: (t: Partial<BoTask>) => Promise<void>;
  deleteTask: (id: string) => Promise<void>;
  editMail: (id: string, patch: Partial<BoMail>) => Promise<void>;
  newMail: (m: Partial<BoMail>) => Promise<string | undefined>;
  mailSent: (id: string) => Promise<void>;
  deleteMail: (id: string) => Promise<void>;
  received: (r: BoReception, value: boolean) => Promise<void>;
}

/** The back office board: the server's when cases are on, otherwise a demo that lives in this browser. */
export function useWorkspace(lang: "en" | "fr", casesEnabled: boolean | undefined) {
  const qc = useQueryClient();
  const live = useQuery({ queryKey: ["backoffice", lang], queryFn: () => api.backoffice(lang), enabled: casesEnabled === true, retry: false });
  const [demo, setDemo] = useState<BoBoard | null>(null);
  const isDemo = casesEnabled === false;

  useEffect(() => {
    if (isDemo && !demo) loadDemo().then(setDemo);
  }, [isDemo, demo]);

  const by = analyst.get() || "Analyst";
  const refresh = useCallback(() => qc.invalidateQueries({ queryKey: ["backoffice"] }), [qc]);
  const local = (fn: (b: BoBoard) => Omit<BoBoard, "stats">) =>
    setDemo((b) => {
      if (!b) return b;
      const next = fn(b);
      return { ...next, stats: computeStats(next) } as BoBoard;
    });

  const actions: WorkspaceActions = isDemo
    ? {
        moveTask: async (id, status) =>
          local((b) => ({
            ...b,
            tasks: b.tasks.map((t) => (t.id === id ? { ...t, status, done_at: status === "done" ? iso() : null, done_by: status === "done" ? by : null } : t)),
          })),
        updateTask: async (id, patch) => local((b) => ({ ...b, tasks: b.tasks.map((t) => (t.id === id ? { ...t, ...patch } : t)) })),
        addTask: async (t) =>
          local((b) => ({
            ...b,
            tasks: [
              { id: `demo-${Date.now()}`, title: t.title ?? "", status: "todo", priority: t.priority ?? "medium", source: "manual", created_at: iso(), created_by: by, ...t } as BoTask,
              ...b.tasks,
            ],
          })),
        deleteTask: async (id) => local((b) => ({ ...b, tasks: b.tasks.filter((t) => t.id !== id) })),
        editMail: async (id, patch) => local((b) => ({ ...b, mails: b.mails.map((m) => (m.id === id ? { ...m, ...patch, edited: true } : m)) })),
        newMail: async (m) => {
          const id = `demo-${Date.now()}`;
          local((b) => ({ ...b, mails: [{ id, type: "custom", status: "draft", to: "", subject: "", body: "", documents: [], created_at: iso(), ...m } as BoMail, ...b.mails] }));
          return id;
        },
        mailSent: async (id) =>
          local((b) => {
            const mail = b.mails.find((m) => m.id === id);
            if (!mail) return b;
            const reminder = mail.type === "reminder";
            return {
              ...b,
              mails: b.mails.map((m) => (m.id === id ? { ...m, status: "sent", sent_at: iso(), sent_by: by, follow_up: plusDays(reminder ? 7 : 14) } : m)),
              receptions: b.receptions.map((x) =>
                x.case_id === mail.case_id && mail.documents.includes(x.key) && x.status !== "received"
                  ? reminder
                    ? { ...x, status: "awaited", reminders: x.reminders + 1, last_reminder_at: iso(), due_at: plusDays(7) }
                    : { ...x, status: "awaited", requested_at: x.requested_at ?? iso(), due_at: plusDays(14) }
                  : x,
              ),
              tasks: b.tasks.map((t) =>
                t.case_id === mail.case_id && t.status !== "done" && ((reminder && t.rule === "chase") || (!reminder && t.rule === "request"))
                  ? { ...t, status: "done", done_at: iso(), done_by: "Automatically (resolved in the case)" }
                  : t,
              ),
            };
          }),
        deleteMail: async (id) => local((b) => ({ ...b, mails: b.mails.filter((m) => m.id !== id) })),
        received: async (r, value) =>
          local((b) => ({
            ...b,
            receptions: b.receptions.map((x) =>
              x.case_id === r.case_id && x.key === r.key
                ? { ...x, status: value ? "received" : x.requested_at ? ((x.due_at ?? "9999") < today() ? "overdue" : "awaited") : "to_request", received_at: value ? iso() : null, received_by: value ? by : null }
                : x,
            ),
          })),
      }
    : {
        moveTask: async (id, status) => void (await api.updateTask(id, { status, by }), await refresh()),
        updateTask: async (id, patch) => void (await api.updateTask(id, { ...patch, by }), await refresh()),
        addTask: async (t) => void (await api.addTask({ ...t, by }), await refresh()),
        deleteTask: async (id) => void (await api.deleteTask(id), await refresh()),
        editMail: async (id, patch) => void (await api.editMail(id, patch), await refresh()),
        newMail: async (m) => {
          const created = await api.newMail({ ...m, by });
          await refresh();
          return created.id;
        },
        mailSent: async (id) => void (await api.mailSent(id, by), await refresh()),
        deleteMail: async (id) => void (await api.deleteMail(id), await refresh()),
        received: async (r, value) => void (await api.received(r.case_id, r.key, value, by), await refresh()),
      };

  return {
    board: isDemo ? demo : (live.data ?? null),
    demo: isDemo,
    loading: isDemo ? !demo : live.isLoading,
    authError: live.error instanceof AuthError,
    error: live.error && !(live.error instanceof AuthError) ? (live.error as Error).message : null,
    retry: () => live.refetch(),
    actions,
  };
}
