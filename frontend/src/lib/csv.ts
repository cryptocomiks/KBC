import { triggerDownload } from "../api";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = Array.isArray(value) ? value.join(" | ") : typeof value === "object" ? JSON.stringify(value) : String(value);
  // Neutralise spreadsheet formula injection, then quote.
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return `"${safe.replace(/"/g, '""')}"`;
}

export function downloadCsv(filename: string, headers: { key: string; label: string }[], rows: Record<string, unknown>[]) {
  const lines = [headers.map((h) => cell(h.label)).join(",")];
  for (const row of rows) lines.push(headers.map((h) => cell(row[h.key])).join(","));
  // BOM so that Excel opens UTF-8 (accents, Cyrillic) correctly.
  triggerDownload(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), filename);
}
