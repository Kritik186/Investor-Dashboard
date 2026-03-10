"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { fetchTransactions, type Transaction } from "@/lib/api";
import { formatCurrency, formatNumber, formatDate } from "@/lib/utils";
import { Button } from "@/components/ui/button";

export function TransactionsTable({
  ticker,
  lookbackDays,
  initialData,
}: {
  ticker: string;
  lookbackDays: number;
  initialData: Transaction[];
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "transaction_date", desc: true }]);
  const [pageIndex, setPageIndex] = useState(0);
  const pageSize = 20;

  const { data, isLoading } = useQuery({
    queryKey: ["transactions", ticker, lookbackDays, pageIndex],
    queryFn: () => fetchTransactions(ticker, lookbackDays, { limit: pageSize, offset: pageIndex * pageSize }),
    placeholderData: pageIndex === 0 ? { transactions: initialData, limit: pageSize, offset: 0 } : undefined,
  });

  const transactions = data?.transactions ?? [];

  const columns: ColumnDef<Transaction>[] = useMemo(
    () => [
      { id: "transaction_date", header: "Date", accessorFn: (r) => r.transaction_date, cell: ({ getValue }) => formatDate(getValue() as string) },
      { id: "insider_name", header: "Insider", accessorKey: "insider_name" },
      { id: "acq_disp", header: "Acq/Disp", accessorKey: "acq_disp", cell: ({ getValue }) => ((getValue() as string) === "A" ? "Acquired" : "Disposed") },
      { id: "shares", header: "Shares", accessorKey: "shares", cell: ({ getValue }) => formatNumber(getValue() as number) },
      { id: "price", header: "Price", accessorKey: "price", cell: ({ getValue }) => formatCurrency(getValue() as number) },
      { id: "value_usd", header: "Value USD", accessorKey: "value_usd", cell: ({ getValue }) => formatCurrency(getValue() as number) },
      { id: "shares_owned_following", header: "Shares After", accessorKey: "shares_owned_following", cell: ({ getValue }) => formatNumber(getValue() as number) },
      {
        id: "xml_url",
        header: "Filing",
        accessorKey: "xml_url",
        cell: ({ row }) => {
          const url = row.original.xml_url;
          if (!url) return "—";
          return (
            <a href={url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
              View filing
            </a>
          );
        },
      },
    ],
    []
  );

  const table = useReactTable({
    data: transactions,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: true,
    pageCount: Math.ceil((data?.transactions.length ?? 0) / pageSize) || 1,
  });

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
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
            {isLoading && transactions.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : transactions.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-muted-foreground">
                  No transactions in range.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="border-b border-border hover:bg-muted/30">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-2">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-border px-4 py-2">
        <span className="text-muted-foreground text-sm">
          Page {pageIndex + 1}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={pageIndex === 0} onClick={() => setPageIndex((p) => Math.max(0, p - 1))}>
            Previous
          </Button>
          <Button variant="outline" size="sm" disabled={transactions.length < pageSize} onClick={() => setPageIndex((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
