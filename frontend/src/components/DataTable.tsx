import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Download, Search } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { downloadCsv } from "../lib/csv";
import type { Row } from "../types";

export interface Column {
  key: string;
  label: string;
  render?: (row: Row) => ReactNode;
  width?: string;
  /** value used for sorting / filtering / CSV when different from row[key] */
  value?: (row: Row) => unknown;
}

interface Props {
  rows: Row[];
  columns: Column[];
  csvName: string;
  empty?: string;
  onRowClick?: (row: Row) => void;
}

export default function DataTable({ rows, columns, csvName, empty = "No data.", onRowClick }: Props) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState("");

  const defs = useMemo<ColumnDef<Row>[]>(
    () =>
      columns.map((c) => ({
        id: c.key,
        header: c.label,
        accessorFn: (row) => {
          const v = c.value ? c.value(row) : row[c.key];
          return v === null || v === undefined ? "" : (v as string | number);
        },
        cell: (ctx) => (c.render ? c.render(ctx.row.original) : String(ctx.getValue() ?? "") || "—"),
        sortingFn: "alphanumeric",
      })),
    [columns],
  );

  const table = useReactTable({
    data: rows,
    columns: defs,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    globalFilterFn: "includesString",
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const visibleRows = table.getRowModel().rows;

  const exportCsv = () =>
    downloadCsv(
      csvName,
      columns.map((c) => ({ key: c.key, label: c.label })),
      visibleRows.map((r) => Object.fromEntries(columns.map((c) => [c.key, c.value ? c.value(r.original) : r.original[c.key]]))),
    );

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
          <input
            className="input w-64 py-1.5 pl-8"
            placeholder="Filter rows…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <span className="text-xs text-slate-500">
          {visibleRows.length} / {rows.length} rows
        </span>
        <button className="btn-outline ml-auto" onClick={exportCsv} disabled={!visibleRows.length}>
          <Download className="h-3.5 w-3.5" /> CSV
        </button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-100 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const sorted = h.column.getIsSorted();
                  const col = columns.find((c) => c.key === h.column.id);
                  return (
                    <th
                      key={h.id}
                      className="cursor-pointer select-none whitespace-nowrap px-3 py-2 font-semibold"
                      style={{ width: col?.width }}
                      onClick={h.column.getToggleSortingHandler()}
                    >
                      <span className="inline-flex items-center gap-1">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {sorted === "asc" ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : sorted === "desc" ? (
                          <ArrowDown className="h-3 w-3" />
                        ) : (
                          <ArrowUpDown className="h-3 w-3 opacity-30" />
                        )}
                      </span>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {visibleRows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-center text-slate-500">
                  {empty}
                </td>
              </tr>
            )}
            {visibleRows.map((r) => (
              <tr
                key={r.id}
                className={`align-top hover:bg-slate-50 dark:hover:bg-slate-800/40 ${onRowClick ? "cursor-pointer" : ""}`}
                onClick={() => onRowClick?.(r.original)}
              >
                {r.getVisibleCells().map((c) => (
                  <td key={c.id} className="px-3 py-2">
                    {flexRender(c.column.columnDef.cell, c.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
