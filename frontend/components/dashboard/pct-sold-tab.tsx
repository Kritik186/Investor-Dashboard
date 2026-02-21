"use client";

import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import type { Aggregate } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

export function PctSoldTab({ aggregates, period }: { aggregates: Aggregate[]; period: "month" | "quarter" }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "avg_pct_sold", desc: true }]);

  const avgByPeriod = useMemo(() => {
    const byPeriod: Record<string, { total: number; sum: number; count: number }> = {};
    for (const a of aggregates) {
      const key = a.period_end
      if (!byPeriod[key]) byPeriod[key] = { total: 0, sum: 0, count: 0 };
      byPeriod[key].total += 1;
      if (a.pct_sold != null && a.pct_sold_label !== "insufficient data") {
        byPeriod[key].sum += a.pct_sold;
        byPeriod[key].count += 1;
      }
    }
    return Object.entries(byPeriod)
      .map(([period_end, v]) => ({
        period_end,
        avg_pct_sold: v.count ? (v.sum / v.count) * 100 : null,
        count: v.count,
      }))
      .sort((a, b) => a.period_end.localeCompare(b.period_end));
  }, [aggregates]);

  const tableData = useMemo(() => {
    const byInsider: Record<string, { insider_cik: string; insider_name: string; periods: number; avg_pct_sold: number; insufficient: number }> = {};
    for (const a of aggregates) {
      const key = a.insider_cik;
      if (!byInsider[key]) byInsider[key] = { insider_cik: a.insider_cik, insider_name: a.insider_name, periods: 0, avg_pct_sold: 0, insufficient: 0 };
      byInsider[key].periods += 1;
      if (a.pct_sold_label === "insufficient data") {
        byInsider[key].insufficient += 1;
      } else if (a.pct_sold != null) {
        byInsider[key].avg_pct_sold += a.pct_sold * 100;
      }
    }
    return Object.values(byInsider).map((r) => ({
      ...r,
      avg_pct_sold: r.periods - r.insufficient > 0 ? (r.avg_pct_sold / (r.periods - r.insufficient)) : null,
    }));
  }, [aggregates]);

  const columns: ColumnDef<typeof tableData[0]>[] = useMemo(
    () => [
      { id: "insider_name", header: "Insider", accessorFn: (r) => r.insider_name },
      { id: "periods", header: "Periods", accessorKey: "periods" },
      {
        id: "avg_pct_sold",
        header: "Avg % Sold",
        accessorFn: (r) => r.avg_pct_sold,
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          return v != null ? `${v.toFixed(2)}%` : "—";
        },
      },
      { id: "insufficient", header: "Insufficient data", accessorKey: "insufficient" },
    ],
    []
  );

  const table = useReactTable({
    data: tableData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 text-lg font-semibold">Avg % Sold by Period</h3>
        <div className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={avgByPeriod.filter((d) => d.avg_pct_sold != null)} margin={{ top: 5, right: 20, left: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="period_end" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(v: number) => [`${Number(v).toFixed(2)}%`, "Avg % Sold"]} />
              <Bar dataKey="avg_pct_sold" name="Avg % Sold" fill="#f59e0b" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <h3 className="p-4 text-lg font-semibold">Per Insider (sortable)</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-border bg-muted/50">
                  {hg.headers.map((h) => (
                    <th key={h.id} className="px-4 py-2 text-left font-medium">
                      {flexRender(h.column.columnDef.header, h.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-border hover:bg-muted/30">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-2">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
