import type { ConnectorStatus, Investigation, InvestigationParams, Meta, SearchResponse } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
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

  async downloadPdf(params: InvestigationParams & { graph_png?: string; reference?: string; analyst?: string }) {
    const res = await fetch(`${BASE}/reports/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
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
