"use client";

import { Fragment, useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { ExternalLink, ChevronDown, ChevronRight, HelpCircle } from "lucide-react";
import type { Aggregate, TopInsider } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/utils";

export function PctSoldTab({
  aggregates,
  period,
  topInsiders = [],
  filter10b5_1 = "all",
}: {
  aggregates: Aggregate[];
  period: "month" | "quarter";
  topInsiders?: TopInsider[];
  filter10b5_1?: "all" | "only" | "exclude";
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: "shares_held_recent", desc: true }]);
  const [expandedInsiderCik, setExpandedInsiderCik] = useState<string | null>(null);

  const changeByPeriod = useMemo(() => {
    const byPeriod: Record<string, number> = {};
    for (const a of aggregates) {
      if (a.change_shares == null) continue;
      byPeriod[a.period_end] = (byPeriod[a.period_end] ?? 0) + a.change_shares;
    }
    return Object.entries(byPeriod)
      .map(([period_end, change_shares]) => ({ period_end, change_shares }))
      .sort((a, b) => a.period_end.localeCompare(b.period_end));
  }, [aggregates]);

  const tableData = useMemo(() => {
    const byInsider: Record<
      string,
      { insider_cik: string; insider_name: string; periods: number; net_change: number; net_value_change: number; insufficient: number; first_start_shares: number | null }
    > = {};
    for (const a of aggregates) {
      const key = a.insider_cik;
      if (!byInsider[key])
        byInsider[key] = {
          insider_cik: a.insider_cik,
          insider_name: a.insider_name,
          periods: 0,
          net_change: 0,
          net_value_change: 0,
          insufficient: 0,
          first_start_shares: null,
        };
      byInsider[key].periods += 1;
      if (a.pct_sold_label === "insufficient data") {
        byInsider[key].insufficient += 1;
      }
      if (a.change_shares != null) {
        byInsider[key].net_change += a.change_shares;
      }
      const vb = a.value_bought_usd ?? 0;
      const vs = a.value_sold_usd ?? 0;
      byInsider[key].net_value_change += vb - vs;
    }
    for (const key of Object.keys(byInsider)) {
      const insiderPeriods = aggregates.filter((a) => a.insider_cik === key).sort((a, b) => a.period_end.localeCompare(b.period_end));
      const first = insiderPeriods[0];
      if (first?.start_shares != null && first.start_shares > 0) {
        byInsider[key].first_start_shares = first.start_shares;
      }
    }
    let rows = Object.values(byInsider).map((r) => ({
      ...r,
      pct_change:
        r.first_start_shares != null && r.first_start_shares > 0 ? (r.net_change / r.first_start_shares) * 100 : null,
      shares_held_recent: 0,
    }));
    const topMap = new Map(topInsiders.map((t, i) => [t.insider_cik, { shares_held_recent: t.shares_held_recent, rank: i }]));
    rows = rows.map((r) => ({
      ...r,
      shares_held_recent: topMap.get(r.insider_cik)?.shares_held_recent ?? 0,
    }));
    rows.sort((a, b) => {
      const rankA = topMap.get(a.insider_cik)?.rank ?? 9999;
      const rankB = topMap.get(b.insider_cik)?.rank ?? 9999;
      return rankA - rankB;
    });
    return rows;
  }, [aggregates, topInsiders]);

  const columns: ColumnDef<typeof tableData[0]>[] = useMemo(
    () => [
      {
        id: "expand",
        header: "",
        size: 32,
        enableSorting: false,
        cell: ({ row }) => {
          const cik = row.original.insider_cik;
          const isExpanded = expandedInsiderCik === cik;
          return (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setExpandedInsiderCik((prev) => (prev === cik ? null : cik));
              }}
              className="p-1 rounded hover:bg-muted"
              aria-label={isExpanded ? "Collapse" : "Expand audit trail"}
            >
              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          );
        },
      },
      { id: "insider_name", header: "Insider", accessorFn: (r) => r.insider_name },
      {
        id: "shares_held_recent",
        header: "Shares held (recent)",
        accessorFn: (r) => r.shares_held_recent,
        cell: ({ getValue }) => formatNumber(getValue() as number),
      },
      {
        id: "periods",
        header: () => (
          <span className="inline-flex items-center gap-1">
            Periods
            <span title="Number of periods (months or quarters) with activity for this insider." className="text-muted-foreground cursor-help">
              <HelpCircle className="h-3.5 w-3.5" />
            </span>
          </span>
        ),
        accessorKey: "periods",
      },
      {
        id: "net_change",
        header: "Net change (all periods)",
        accessorFn: (r) => r.net_change,
        cell: ({ getValue }) => {
          const v = getValue() as number;
          return (
            <span className={v >= 0 ? "text-green-600" : "text-red-600"}>
              {v >= 0 ? "+" : ""}{formatNumber(v)}
            </span>
          );
        },
      },
      {
        id: "net_value_change",
        header: "Net value change (USD)",
        accessorFn: (r) => r.net_value_change,
        cell: ({ getValue }) => {
          const v = getValue() as number;
          if (v === 0) return formatCurrency(0);
          return (
            <span className={v >= 0 ? "text-green-600" : "text-red-600"}>
              {v >= 0 ? "+" : ""}{formatCurrency(v)}
            </span>
          );
        },
      },
      {
        id: "pct_change",
        header: "% change",
        accessorFn: (r) => r.pct_change,
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          if (v == null) return "—";
          return (
            <span className={v >= 0 ? "text-green-600" : "text-red-600"}>
              {v >= 0 ? "+" : ""}{v.toFixed(2)}%
            </span>
          );
        },
      },
      {
        id: "insufficient",
        header: () => (
          <span className="inline-flex items-center gap-1">
            Insufficient data
            <span title="Number of periods where start or end shares were missing for that period." className="text-muted-foreground cursor-help">
              <HelpCircle className="h-3.5 w-3.5" />
            </span>
          </span>
        ),
        accessorKey: "insufficient",
      },
    ],
    [expandedInsiderCik]
  );

  const table = useReactTable({
    data: tableData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (aggregates.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center">
        <p className="text-muted-foreground">No shareholding change data for this range.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-2 text-lg font-semibold">Change in shareholding by period (total across insiders)</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          Change = acquired − sold (net). Total net change in shares held (start → end of each {period}) across all insiders. Positive = net buying, negative = net selling.
        </p>
        <div className="h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={changeByPeriod} margin={{ top: 5, right: 20, left: 5, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="period_end" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => formatNumber(v)} />
              <Tooltip formatter={(v: number) => [formatNumber(v), "Net change (shares)"]} />
              <Bar dataKey="change_shares" name="Net change (shares)" fill="#f59e0b" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <h3 className="p-4 pb-2 text-lg font-semibold">Change in shareholding per insider</h3>
        <p className="px-4 pb-2 text-sm text-muted-foreground">
          Change = acquired − sold (net). Listed by highest shareholders first. Sort by column headers (e.g. % change). Click a row to expand audit trail.
        </p>
        <p className="px-4 pb-4 text-xs text-muted-foreground">
          <strong>Periods:</strong> Number of {period}s with activity. <strong>% change:</strong> Net change ÷ shares at start of first period. <strong>Insufficient data:</strong> Periods where start or end shares were missing.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-border bg-muted/50">
                  {hg.headers.map((h) => (
                    <th
                      key={h.id}
                      className="px-4 py-2 text-left font-medium cursor-pointer select-none hover:bg-muted/50"
                      onClick={h.column.getToggleSortingHandler()}
                    >
                      <span className="inline-flex items-center gap-1">
                        {flexRender(h.column.columnDef.header, h.getContext())}
                        {h.column.getIsSorted() === "asc" ? " ↑" : h.column.getIsSorted() === "desc" ? " ↓" : ""}
                      </span>
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => {
                const cik = row.original.insider_cik;
                const isExpanded = expandedInsiderCik === cik;
                const insiderAggregates = aggregates
                  .filter((a) => a.insider_cik === cik)
                  .sort((a, b) => a.period_end.localeCompare(b.period_end));
                return (
                  <Fragment key={row.id}>
                    <tr
                      key={row.id}
                      onClick={() => setExpandedInsiderCik((prev) => (prev === cik ? null : cik))}
                      className="border-b border-border hover:bg-muted/30 cursor-pointer"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-4 py-2">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                    {isExpanded && (
                      <tr key={`${row.id}-audit`} className="border-b border-border bg-muted/20">
                        <td colSpan={row.getVisibleCells().length} className="p-4">
                          <div className="rounded border border-border bg-background overflow-hidden space-y-4">
                            {insiderAggregates.length > 0 && (() => {
                              const chartData = insiderAggregates.map((a) => {
                                const pct =
                                  a.start_shares != null &&
                                  a.start_shares > 0 &&
                                  a.change_shares != null
                                    ? (a.change_shares / a.start_shares) * 100
                                    : null;
                                return { period_end: a.period_end, pct_change: pct };
                              });
                              const hasAnyPct = chartData.some((d) => d.pct_change != null);
                              return hasAnyPct ? (
                                <div className="px-4 pt-2">
                                  <h4 className="mb-2 text-sm font-semibold">% change in shareholding per period</h4>
                                  <div className="h-[240px]">
                                    <ResponsiveContainer width="100%" height="100%">
                                      <BarChart
                                        data={chartData}
                                        margin={{ top: 5, right: 20, left: 5, bottom: 5 }}
                                      >
                                        <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                                        <XAxis dataKey="period_end" tick={{ fontSize: 10 }} />
                                        <YAxis
                                          tick={{ fontSize: 10 }}
                                          tickFormatter={(v) => `${v}%`}
                                          domain={["auto", "auto"]}
                                        />
                                        <Tooltip
                                          formatter={(v: number) => [v != null ? `${v.toFixed(2)}%` : "—", "% change"]}
                                          labelFormatter={(label) => `Period end: ${label}`}
                                        />
                                        <Bar dataKey="pct_change" name="% change" radius={[2, 2, 0, 0]}>
                                          {chartData.map((entry, i) => (
                                            <Cell
                                              key={i}
                                              fill={
                                                entry.pct_change == null
                                                  ? "hsl(var(--muted-foreground))"
                                                  : entry.pct_change >= 0
                                                    ? "hsl(142, 76%, 36%)"
                                                    : "hsl(0, 84%, 60%)"
                                              }
                                            />
                                          ))}
                                        </Bar>
                                      </BarChart>
                                    </ResponsiveContainer>
                                  </div>
                                </div>
                              ) : null;
                            })()}
                            <div>
                              <p className="px-4 py-2 text-xs font-medium text-muted-foreground border-b border-border">
                                For each {period}: period start → end (selected range). Change = acquired − sold = End − Start. Filings link to SEC Form 4.
                              </p>
                              <table className="w-full text-sm">
                              <thead>
                                <tr className="border-b border-border bg-muted/50">
                                  <th className="px-4 py-2 text-left font-medium">Period start</th>
                                  <th className="px-4 py-2 text-left font-medium">Period end</th>
                                  <th className="px-4 py-2 text-right font-medium">Start shares</th>
                                  <th className="px-4 py-2 text-right font-medium">End shares</th>
                                  <th className="px-4 py-2 text-right font-medium">Change</th>
                                  <th className="px-4 py-2 text-right font-medium">Value change (USD)</th>
                                  <th className="px-4 py-2 text-center font-medium" title="Rule 10b5-1(c): All = all under plan; Mixed = some; None = none">10b5-1</th>
                                  <th className="px-4 py-2 text-left font-medium">Filings</th>
                                </tr>
                              </thead>
                              <tbody>
                                {insiderAggregates.map((a, i) => (
                                  <tr key={`${a.period_end}-${i}`} className="border-b border-border hover:bg-muted/20">
                                    <td className="px-4 py-2">{a.period_start ?? "—"}</td>
                                    <td className="px-4 py-2">{a.period_end}</td>
                                    <td className="px-4 py-2 text-right">{a.start_shares != null ? formatNumber(a.start_shares) : "—"}</td>
                                    <td className="px-4 py-2 text-right">{a.end_shares != null ? formatNumber(a.end_shares) : "—"}</td>
                                    <td className="px-4 py-2 text-right">
                                      {a.change_shares != null ? (
                                        <span className={a.change_shares >= 0 ? "text-green-600" : "text-red-600"}>
                                          {a.change_shares >= 0 ? "+" : ""}{formatNumber(a.change_shares)}
                                        </span>
                                      ) : (
                                        "—"
                                      )}
                                    </td>
                                    <td className="px-4 py-2 text-right">
                                      {(() => {
                                        const vb = a.value_bought_usd ?? 0;
                                        const vs = a.value_sold_usd ?? 0;
                                        const val = vb - vs;
                                        if (vb === 0 && vs === 0) return "—";
                                        return (
                                          <span className={val >= 0 ? "text-green-600" : "text-red-600"}>
                                            {val >= 0 ? "+" : ""}{formatCurrency(val)}
                                          </span>
                                        );
                                      })()}
                                    </td>
                                    <td className="px-4 py-2 text-center" title={a.period_10b5_1_status === "all" ? "All transactions in this period under Rule 10b5-1(c) plan" : a.period_10b5_1_status === "mixed" ? "Some transactions under 10b5-1 plan" : "No 10b5-1 transactions in this period"}>
                                      {a.period_10b5_1_status === "all" ? (
                                        <span className="rounded bg-primary/15 px-1.5 py-0.5 text-xs font-medium text-primary">All</span>
                                      ) : a.period_10b5_1_status === "mixed" ? (
                                        <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">Mixed</span>
                                      ) : a.period_10b5_1_status === "none" ? (
                                        <span className="text-muted-foreground text-xs">None</span>
                                      ) : (
                                        "—"
                                      )}
                                    </td>
                                    <td className="px-4 py-2">
                                      {a.dispositions && a.dispositions.length > 0 ? (
                                        <ul className="flex flex-wrap gap-2">
                                          {a.dispositions.map((d, j) => (
                                            <li key={j}>
                                              <a
                                                href={d.xml_url ?? "#"}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="inline-flex items-center gap-1 text-primary hover:underline"
                                                onClick={(e) => e.stopPropagation()}
                                              >
                                                <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                                                {d.transaction_date}
                                              </a>
                                            </li>
                                          ))}
                                        </ul>
                                      ) : (
                                        <span className="text-muted-foreground">—</span>
                                      )}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                              {insiderAggregates.length === 0 && (
                                <p className="p-4 text-sm text-muted-foreground">No period-level data for this insider.</p>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
