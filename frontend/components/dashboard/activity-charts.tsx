"use client";

import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { Aggregate } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/utils";

export function ActivityCharts({ aggregates }: { aggregates: Aggregate[] }) {
  const byPeriod = useMemo(() => {
    const map: Record<string, { period_end: string; shares_sold: number; shares_bought: number; value_sold_usd: number; value_bought_usd: number }> = {};
    for (const a of aggregates) {
      const key = a.period_end;
      if (!map[key]) {
        map[key] = { period_end: key, shares_sold: 0, shares_bought: 0, value_sold_usd: 0, value_bought_usd: 0 };
      }
      map[key].shares_sold += a.shares_sold;
      map[key].shares_bought += a.shares_bought;
      map[key].value_sold_usd += a.value_sold_usd ?? 0;
      map[key].value_bought_usd += a.value_bought_usd ?? 0;
    }
    return Object.values(map).sort((a, b) => a.period_end.localeCompare(b.period_end));
  }, [aggregates]);

  if (byPeriod.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground">
        No activity data in range.
      </div>
    );
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 text-lg font-semibold">Shares Bought vs Sold</h3>
        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={byPeriod} margin={{ top: 5, right: 20, left: 5, bottom: 5 }} stackOffset="sign">
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="period_end" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => formatNumber(v)} />
              <Tooltip formatter={(v: number) => [formatNumber(v), "Shares"]} />
              <Legend />
              <Bar dataKey="shares_bought" name="Shares Bought" stackId="a" fill="#22c55e" />
              <Bar dataKey="shares_sold" name="Shares Sold" stackId="a" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="mb-4 text-lg font-semibold">$ Bought vs $ Sold</h3>
        <div className="h-[320px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={byPeriod} margin={{ top: 5, right: 20, left: 5, bottom: 5 }} stackOffset="sign">
              <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
              <XAxis dataKey="period_end" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => (v >= 1e6 ? `${(v / 1e6).toFixed(0)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}k` : String(v))} />
              <Tooltip formatter={(v: number) => [formatCurrency(v), "USD"]} />
              <Legend />
              <Bar dataKey="value_bought_usd" name="$ Bought" stackId="b" fill="#22c55e" />
              <Bar dataKey="value_sold_usd" name="$ Sold" stackId="b" fill="#ef4444" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
