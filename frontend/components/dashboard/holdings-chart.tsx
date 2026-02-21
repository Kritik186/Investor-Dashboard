"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { TopInsider } from "@/lib/api";
import { fetchInsiderActivity } from "@/lib/api";

function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
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

  const { data: activityData, isLoading: activityLoading } = useQuery({
    queryKey: ["insider-activity", ticker, selectedInsider?.insider_cik, lookbackDays, period],
    queryFn: () =>
      fetchInsiderActivity(ticker, selectedInsider!.insider_cik, lookbackDays, period),
    enabled: !!ticker && !!selectedInsider?.insider_cik,
  });

  const activity = activityData?.activity ?? [];

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 text-lg font-semibold">Top 15 shareholders (by activity value)</h3>
        <p className="mb-4 text-sm text-muted-foreground">
          Click an insider to see their shares bought vs sold over time.
        </p>
        {topInsiders.length === 0 ? (
          <p className="text-muted-foreground">No top insiders in range. Run Refresh to sync Form 4 data.</p>
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
                    ({formatNumber(insider.total_abs_value_usd)})
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
            Shares bought vs sold — {selectedInsider.insider_name || selectedInsider.insider_cik}
          </h3>
          {activityLoading ? (
            <p className="py-8 text-center text-muted-foreground">Loading…</p>
          ) : activity.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">No activity in range for this insider.</p>
          ) : (
            <div className="h-[360px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={activity} margin={{ top: 5, right: 20, left: 5, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="period_end" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => formatNumber(v)} />
                  <Tooltip
                    formatter={(v: number, name: string) => [formatNumber(v), name === "shares_bought" ? "Shares bought" : "Shares sold"]}
                    labelFormatter={(l) => String(l)}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="shares_bought"
                    name="Shares bought"
                    stroke="#22c55e"
                    dot={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="shares_sold"
                    name="Shares sold"
                    stroke="#ef4444"
                    dot={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
