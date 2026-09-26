import type {
  CaseChange,
  CaseRecord,
  CaseView,
  ConnectorStatus,
  Dashboard,
  Decision,
  DocComparison,
  DocExtraction,
  DecisionValue,
  ImportStatus,
  KycAnswers,
  KycQuestionnaire,
  Investigation,
  InvestigationParams,
  Meta,
  SearchResponse,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";
const PW_KEY = "kbc-password";

/** Password for cases (kept in this browser only). */
export const auth = {
  get: (): string | null => {
    try {
      return localStorage.getItem(PW_KEY);
    } catch {
      return null;
    }
  },
  set: (pw: string) => {
    try {
      localStorage.setItem(PW_KEY, pw);
    } catch {
      /* private mode */
    }
  },
  clear: () => {
    try {
      localStorage.removeItem(PW_KEY);
    } catch {
      /* private mode */
    }
  },
};

export class AuthError extends Error {}

function authHeaders(): Record<string, string> {
  const pw = auth.get();
  return pw ? { "X-KBC-Password": pw } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (res.status === 401) throw new AuthError("Password required");
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = `${res.status} — ${typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)}`;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  meta: () => request<Meta>("/meta"),
  connectors: () => request<ConnectorStatus[]>("/connectors"),
  search: (q: string, type: string) =>
    request<SearchResponse>(`/search?${new URLSearchParams({ q, type })}`),
  investigate: (params: InvestigationParams) =>
    request<Investigation>("/investigations", { method: "POST", body: JSON.stringify(params) }),
  clearCache: () => request<{ deleted: number }>("/cache", { method: "DELETE" }),

  dashboard: () => request<Dashboard>("/cases"),
  createCase: (params: InvestigationParams & { title?: string; monitor?: boolean }) =>
    request<CaseRecord>("/cases", { method: "POST", body: JSON.stringify(params) }),
  getCase: (id: string) => request<CaseView>(`/cases/${id}`),
  updateCase: (id: string, patch: Partial<Pick<CaseRecord, "title" | "notes" | "status" | "monitor">>) =>
    request<CaseRecord>(`/cases/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteCase: (id: string) => request<{ deleted: string }>(`/cases/${id}`, { method: "DELETE" }),
  refreshCase: (id: string) =>
    request<{ case: CaseRecord; changes: CaseChange[] }>(`/cases/${id}/refresh`, { method: "POST" }),
  markSeen: (id: string) => request<{ ok: boolean }>(`/cases/${id}/seen`, { method: "POST" }),
  decide: (id: string, d: { item_key: string; item_label: string; decision: DecisionValue | "none"; comment?: string; author?: string }) =>
    request<{ decisions: Decision[] }>(`/cases/${id}/decisions`, { method: "PUT", body: JSON.stringify(d) }),

  saveQuestionnaire: (id: string, answers: KycAnswers, author: string) =>
    request<KycQuestionnaire>(`/cases/${id}/questionnaire`, { method: "PUT", body: JSON.stringify({ answers, author }) }),
  resolveCase: (id: string, record_ids: string[]) =>
    request<CaseRecord>(`/cases/${id}/resolve`, { method: "POST", body: JSON.stringify({ record_ids }) }),
  importStatus: () => request<ImportStatus>("/cases/import/status"),
  importNext: (caseId?: string) =>
    request<ImportStatus & { step: { case_id: string; title: string; state: string } | null }>(
      `/cases/import/next${caseId ? `?case_id=${encodeURIComponent(caseId)}` : ""}`,
      { method: "POST" },
    ),
  async importFile(file: File, opts: { depth: number; monitor: boolean }) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("depth", String(opts.depth));
    fd.append("monitor", String(opts.monitor));
    const res = await fetch(`${BASE}/cases/import`, { method: "POST", body: fd, headers: authHeaders() });
    if (res.status === 401) throw new AuthError("Password required");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.detail ?? `Import failed (${res.status})`);
    return body as ImportStatus & { batch: string; created: number; warnings: string[] };
  },

  async extractDocument(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/documents/extract`, { method: "POST", body: fd });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body?.detail ?? `Extraction failed (${res.status})`);
    }
    return (await res.json()) as DocExtraction;
  },
  compareDocument: (body: InvestigationParams & Pick<DocExtraction, "company" | "officers" | "owners">) =>
    request<DocComparison>("/documents/compare", { method: "POST", body: JSON.stringify(body) }),

  async downloadPdf(params: InvestigationParams & { graph_png?: string; reference?: string; analyst?: string; case_id?: string; template?: string }) {
    const res = await fetch(`${BASE}/reports/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(`PDF generation failed (${res.status})`);
    const blob = await res.blob();
    const name =
      res.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ?? "due_diligence_report.pdf";
    triggerDownload(blob, name);
  },
};

export async function downloadSar(params: InvestigationParams & { fiu: string; case_id?: string; reference?: string }) {
  const res = await fetch(`${BASE}/reports/sar`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(`Draft generation failed (${res.status})`);
  const name = res.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ?? "DRAFT_SAR.pdf";
  triggerDownload(await res.blob(), name);
}

export function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
