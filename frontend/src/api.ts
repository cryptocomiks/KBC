import type {
  CaseChange,
  CaseRecord,
  CaseView,
  ConnectorStatus,
  Dashboard,
  Decision,
  DecisionValue,
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

  async downloadPdf(params: InvestigationParams & { graph_png?: string; reference?: string; analyst?: string; case_id?: string }) {
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
