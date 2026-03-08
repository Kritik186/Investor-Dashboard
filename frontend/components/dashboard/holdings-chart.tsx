"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { TopInsider, Transaction } from "@/lib/api";
import { fetchTransactions } from "@/lib/api";

function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}

type ScatterPoint = { date: string; dateNum: number; shares: number; xml_url: string | null; fill: string; label: string };

function toScatterPoint(txn: Transaction, fill: string): ScatterPoint {
  const shares = Math.abs(txn.shares ?? 0);
  const label = txn.acq_disp === "A" ? "Acquired" : txn.acq_disp === "D" ? "Disposed" : "";
  return {
    date: txn.transaction_date,
    dateNum: new Date(txn.transaction_date).getTime(),
    shares,
    xml_url: txn.xml_url ?? null,
    fill,
    label: `${txn.transaction_date} — ${label} ${formatNumber(shares)} shares`,
  };
}

export function HoldingsChart({
  ticker,
  lookbackDays,
  period,
  topInsiders,
}: {
  ticker: string;
  lookbackDays: number;
  period: "month" | "quarter";
  topInsiders: TopInsider[];
}) {
  const [selectedInsider, setSelectedInsider] = useState<TopInsider | null>(null);

  const { data: transactionsData, isLoading: transactionsLoading } = useQuery({
    queryKey: ["transactions", ticker, lookbackDays, selectedInsider?.insider_cik],
    queryFn: () =>
      fetchTransactions(ticker, lookbackDays, { insider_cik: selectedInsider!.insider_cik, limit: 500, offset: 0 }),
    enabled: !!ticker && !!selectedInsider?.insider_cik,
  });

  const transactions = transactionsData?.transactions ?? [];
  const { boughtPoints, soldPoints } = useMemo(() => {
    const bought: ReturnType<typeof toScatterPoint>[] = [];
    const sold: ReturnType<typeof toScatterPoint>[] = [];
    const sorted = [...transactions].sort((a, b) => a.transaction_date.localeCompare(b.transaction_date));
    for (const t of sorted) {
      if (t.acq_disp === "A") bought.push(toScatterPoint(t, "#22c55e"));
      else if (t.acq_disp === "D") sold.push(toScatterPoint(t, "#ef4444"));
    }
    return { boughtPoints: bought, soldPoints: sold };
  }, [transactions]);

  const allPoints = useMemo(() => [...boughtPoints, ...soldPoints], [boughtPoints, soldPoints]);

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 text-lg font-semibold">Top 15 shareholders (by shares held on most recent date)</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          Independent of the selected date range. Click an insider to see their activity; green dots = bought, red = disposed. Click a dot to open the filing.
        </p>
        {topInsiders.length === 0 ? (
          <p className="text-muted-foreground">No top insiders. Run Refresh to sync Form 4 data.</p>
        ) : (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {topInsiders.map((insider) => (
              <li key={insider.insider_cik}>
                <button
                  type="button"
                  onClick={() => setSelectedInsider(insider)}
                  className={`w-full rounded-lg border px-4 py-3 text-left text-sm transition-colors ${
                    selectedInsider?.insider_cik === insider.insider_cik
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border bg-muted/30 hover:bg-muted/50"
                  }`}
                >
                  <span className="font-medium">{insider.insider_name || insider.insider_cik}</span>
                  <span className="ml-2 text-muted-foreground">
                    ({formatNumber(insider.shares_held_recent)} shares)
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {selectedInsider && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-4 text-lg font-semibold">
            Activity (selected period) — {selectedInsider.insider_name || selectedInsider.insider_cik}
          </h3>
          <p className="mb-4 text-sm text-muted-foreground">
            Green = acquired, red = disposed. Click a dot to open the SEC filing.
          </p>
          {transactionsLoading ? (
            <p className="py-8 text-center text-muted-foreground">Loading…</p>
          ) : allPoints.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">No activity in range for this insider.</p>
          ) : (
            <div className="h-[360px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 5, right: 20, left: 5, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="dateNum" type="number" tick={{ fontSize: 11 }} tickFormatter={(ts) => new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" })} domain={["dataMin", "dataMax"]} />
                  <YAxis type="number" dataKey="shares" name="Shares" tick={{ fontSize: 11 }} tickFormatter={(v) => formatNumber(v)} />
                  <Tooltip
                    formatter={(value: number) => [formatNumber(value), "Shares"]}
                    labelFormatter={(label) => String(label)}
                    content={({ active, payload }) =>
                      active && payload?.[0]?.payload ? (
                        <div className="rounded border border-border bg-card px-3 py-2 text-sm shadow">
                          <p className="font-medium">{(payload[0].payload as ScatterPoint).label}</p>
                          {(payload[0].payload as ScatterPoint).xml_url && (
                            <a
                              href={(payload[0].payload as ScatterPoint).xml_url!}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-1 text-primary hover:underline"
                            >
                              Open filing →
                            </a>
                          )}
                        </div>
                      ) : null
                    }
                  />
                  <Legend />
                  <Scatter
                    data={boughtPoints}
                    name="Acquired"
                    fill="#22c55e"
                    onClick={(entry: ScatterPoint) => entry?.xml_url && window.open(entry.xml_url, "_blank")}
                    cursor="pointer"
                  />
                  <Scatter
                    data={soldPoints}
                    name="Disposed"
                    fill="#ef4444"
                    onClick={(entry: ScatterPoint) => entry?.xml_url && window.open(entry.xml_url, "_blank")}
                    cursor="pointer"
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
