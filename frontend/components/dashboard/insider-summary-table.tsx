"use client";

import { useState, useMemo, useCallback } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowUpDown, ArrowUp, ArrowDown, Download, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { InsiderSummaryRow, ClusterPeriod } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/utils";

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function fmtCurrency(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "$0";
  return formatCurrency(v);
}

function fmtShares(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "0";
  return formatNumber(v);
}

const col = createColumnHelper<InsiderSummaryRow>();

function SortHeader({ label, sorted }: { label: string; sorted: false | "asc" | "desc" }) {
  return (
    <span className="inline-flex items-center gap-1">
      {label}
      {sorted === "asc" ? (
        <ArrowUp className="h-3 w-3" />
      ) : sorted === "desc" ? (
        <ArrowDown className="h-3 w-3" />
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-40" />
      )}
    </span>
  );
}

export function InsiderSummaryTable({
  insiders,
  clusterPeriods,
  coreSalesOnly,
  tenPctOnly,
  onCoreSalesToggle,
  onTenPctToggle,
  onInsiderClick,
}: {
  insiders: InsiderSummaryRow[];
  clusterPeriods: ClusterPeriod[];
  coreSalesOnly: boolean;
  tenPctOnly: boolean;
  onCoreSalesToggle: () => void;
  onTenPctToggle: () => void;
  onInsiderClick: (insider: InsiderSummaryRow) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const filteredData = useMemo(
    () => (tenPctOnly ? insiders.filter((r) => r.is_ten_percent_owner) : insiders),
    [insiders, tenPctOnly]
  );

  const columns = useMemo(
    () => [
      col.accessor("insider_name", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Name" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => (
          <button
            type="button"
            className="text-left font-medium text-primary hover:underline"
            onClick={() => onInsiderClick(info.row.original)}
          >
            {info.getValue() || info.row.original.insider_cik}
          </button>
        ),
      }),
      col.accessor("officer_title", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Title / Role" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => {
          const row = info.row.original;
          const title = info.getValue();
          if (title) return title;
          const parts: string[] = [];
          if (row.is_director) parts.push("Director");
          if (row.is_officer) parts.push("Officer");
          if (row.is_ten_percent_owner) parts.push(">10% Owner");
          return parts.join(", ") || "—";
        },
      }),
      col.accessor("pct_owner_post_sales", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="% EoP (of Top 15)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => (info.getValue() != null ? fmtPct(info.getValue()) : "N/A"),
      }),
      col.accessor("net_buyer_or_seller", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Net Buyer/Seller" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => {
          const v = info.getValue();
          const cls = v === "Buyer" ? "text-green-600" : v === "Seller" ? "text-red-600" : "text-muted-foreground";
          return <span className={cls}>{v}</span>;
        },
      }),
      col.accessor("buys_usd", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Buys ($)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtCurrency(info.getValue()),
      }),
      col.accessor("buys_shares", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Buys (#)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtShares(info.getValue()),
      }),
      col.accessor("avg_cost_basis_buys", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Avg Cost Buys ($)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => (info.getValue() != null ? `$${info.getValue()!.toFixed(2)}` : "—"),
      }),
      col.accessor("purchases_pct_bop", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Purchases % BoP" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtPct(info.getValue()),
      }),
      col.accessor("sales_total_usd", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Sales Total ($)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtCurrency(info.getValue()),
      }),
      col.accessor("sales_core_usd", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Sales Core ($)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtCurrency(info.getValue()),
      }),
      col.accessor("sales_core_shares", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Sales Core (#)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtShares(info.getValue()),
      }),
      col.accessor("avg_cost_basis_core_sales", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Avg Cost Core Sales ($)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => (info.getValue() != null ? `$${info.getValue()!.toFixed(2)}` : "—"),
      }),
      col.accessor("sales_pct_bop", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Sales % BoP" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtPct(info.getValue()),
      }),
      col.accessor("sales_non_core_usd", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Non-Core ($)" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtCurrency(info.getValue()),
      }),
      col.accessor("sales_non_core_pct_total", {
        header: ({ column }) => (
          <button type="button" onClick={column.getToggleSortingHandler()} className="cursor-pointer select-none">
            <SortHeader label="Non-Core % Total" sorted={column.getIsSorted()} />
          </button>
        ),
        cell: (info) => fmtPct(info.getValue()),
      }),
    ],
    [onInsiderClick]
  );

  const table = useReactTable({
    data: filteredData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const handleCsvExport = useCallback(() => {
    const headers = [
      "Name", "Title / Role", "% Owner Post-Sales", "Net Buyer/Seller",
      "Buys ($)", "Buys (#)", "Avg Cost Buys ($)", "Purchases % BoP",
      "Sales Total ($)", "Sales Core ($)", "Sales Core (#)", "Avg Cost Core Sales ($)",
      "Sales % BoP", "Non-Core ($)", "Non-Core % Total",
    ];
    const rows = table.getRowModel().rows.map((r) => {
      const d = r.original;
      return [
        d.insider_name, d.officer_title ?? "", d.pct_owner_post_sales ?? "N/A",
        d.net_buyer_or_seller, d.buys_usd, d.buys_shares, d.avg_cost_basis_buys ?? "",
        d.purchases_pct_bop ?? "", d.sales_total_usd, d.sales_core_usd, d.sales_core_shares,
        d.avg_cost_basis_core_sales ?? "", d.sales_pct_bop ?? "", d.sales_non_core_usd,
        d.sales_non_core_pct_total ?? "",
      ].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",");
    });
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "insider_summary.csv";
    a.click();
    URL.revokeObjectURL(url);
  }, [table]);

  const clusterDisplay = useMemo(() => {
    return clusterPeriods.map((cp) => {
      const [y, mo] = cp.period.split("-");
      const d = new Date(Number(y), Number(mo) - 1);
      const label = d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
      return { label, sellers: cp.sellers };
    });
  }, [clusterPeriods]);

  return (
    <div className="space-y-4">
      {clusterDisplay.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm dark:border-amber-700 dark:bg-amber-950/30">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <div>
              <strong>Coordinated selling detected:</strong> 3+ insiders sold in the same period.
              <ul className="mt-1.5 space-y-1">
                {clusterDisplay.map((cp) => (
                  <li key={cp.label}>
                    <span className="font-medium">{cp.label}:</span>{" "}
                    {cp.sellers.join(", ")}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={tenPctOnly}
            onChange={onTenPctToggle}
            className="h-4 w-4 rounded border-input"
          />
          &gt;10% Owners Only
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={coreSalesOnly}
            onChange={onCoreSalesToggle}
            className="h-4 w-4 rounded border-input"
          />
          Core Sales Only
        </label>
        <div className="ml-auto">
          <Button variant="outline" size="sm" onClick={handleCsvExport}>
            <Download className="mr-2 h-4 w-4" />
            Download CSV
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-border bg-muted/50">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    className="whitespace-nowrap px-3 py-2 text-left text-xs font-medium"
                  >
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-8 text-center text-muted-foreground">
                  No insider data available.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-border hover:bg-muted/20">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="whitespace-nowrap px-3 py-2">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
