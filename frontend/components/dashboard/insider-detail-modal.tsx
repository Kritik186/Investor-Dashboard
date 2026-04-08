"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import {
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Line,
  ComposedChart,
} from "recharts";
import type { InsiderSummaryRow, Transaction, StockPricePoint } from "@/lib/api";
import { fetchTransactions, fetchStockPrices } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/utils";

type ChartView = "sales" | "waterfall";

function classifyTransaction(t: Transaction): "core" | "non-core" {
  const code = (t.transaction_code ?? "").toUpperCase();
  if (code !== "P" && code !== "S") return "non-core";
  const d = t as Record<string, unknown>;
  if (d.is_10b5_1 === true) return "non-core";
  if (d.is_rsu_vest_related === true) return "non-core";
  if (d.is_tax_withholding === true) return "non-core";
  if (d.is_gift === true) return "non-core";
  return "core";
}

type SalesChartPoint = {
  period: string;
  coreSalesUsd: number;
  nonCoreSalesUsd: number;
  pctSold: number | null;
  stockPrice: number | null;
};

type WaterfallPoint = {
  label: string;
  value: number;
  base: number;
  fill: string;
  isTotal?: boolean;
  displayValue: number;
  sign: "positive" | "negative" | "total";
};

function buildSalesData(
  transactions: Transaction[],
  coreSalesOnly: boolean,
  stockPrices: StockPricePoint[] = [],
): SalesChartPoint[] {
  const byMonth = new Map<string, { coreSold: number; nonCoreSold: number }>();

  const sorted = [...transactions]
    .filter((t) => (t.acq_disp ?? "").toUpperCase() === "D")
    .sort((a, b) => a.transaction_date.localeCompare(b.transaction_date));

  for (const t of sorted) {
    const month = t.transaction_date.slice(0, 7);
    if (!byMonth.has(month)) byMonth.set(month, { coreSold: 0, nonCoreSold: 0 });
    const entry = byMonth.get(month)!;
    const val = t.value_usd ?? (t.shares && t.price ? t.shares * t.price : 0);
    if (classifyTransaction(t) === "core") {
      entry.coreSold += val;
    } else {
      entry.nonCoreSold += val;
    }
  }

  const allSorted = [...transactions].sort((a, b) => a.transaction_date.localeCompare(b.transaction_date));
  const nonDerivSorted = allSorted.filter((t) => !t.is_derivative);
  const monthStartShares = new Map<string, number>();
  for (const t of nonDerivSorted) {
    const month = t.transaction_date.slice(0, 7);
    if (!monthStartShares.has(month) && t.shares_owned_following != null) {
      const shares = t.shares ?? 0;
      const acq = (t.acq_disp ?? "").toUpperCase();
      const start = acq === "D" ? t.shares_owned_following + shares : t.shares_owned_following - shares;
      monthStartShares.set(month, start);
    }
  }

  const priceByMonth = new Map<string, number>();
  for (const sp of stockPrices) {
    priceByMonth.set(sp.date.slice(0, 7), sp.close);
  }

  const points: SalesChartPoint[] = [];
  for (const [month, data] of Array.from(byMonth.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
    const coreUsd = data.coreSold;
    const nonCoreUsd = coreSalesOnly ? 0 : data.nonCoreSold;
    const start = monthStartShares.get(month);
    const monthTxns = allSorted.filter((t) => t.transaction_date.startsWith(month));
    const totalAcquiredShares = monthTxns
      .filter((t) => (t.acq_disp ?? "").toUpperCase() === "A")
      .reduce((sum, t) => sum + (t.shares ?? 0), 0);
    const totalSoldShares = sorted
      .filter((t) => t.transaction_date.startsWith(month))
      .filter((t) => !coreSalesOnly || classifyTransaction(t) === "core")
      .reduce((sum, t) => sum + (t.shares ?? 0), 0);
    const totalSoldUsd = coreUsd + nonCoreUsd;
    const available = (start ?? 0) + totalAcquiredShares;
    const pct = available > 0 && totalSoldUsd > 0 ? totalSoldShares / available : null;
    points.push({
      period: month,
      coreSalesUsd: coreUsd,
      nonCoreSalesUsd: nonCoreUsd,
      pctSold: pct,
      stockPrice: priceByMonth.get(month) ?? null,
    });
  }
  return points;
}

function buildWaterfallData(insider: InsiderSummaryRow): WaterfallPoint[] {
  const bop = insider.bop_shares ?? 0;
  const eop = insider.eop_shares ?? 0;
  const coreBuys = insider.buys_core_shares ?? 0;
  const nonCoreBuys = insider.buys_non_core_shares ?? 0;
  const coreSales = insider.sales_core_shares;
  const nonCoreSales = insider.sales_non_core_shares ?? 0;

  const classifiedNet = bop + coreBuys + nonCoreBuys - coreSales - nonCoreSales;
  const gap = eop - classifiedNet;

  let running = bop;
  const points: WaterfallPoint[] = [
    { label: "BoP Shares", value: bop, base: 0, fill: "hsl(217, 91%, 60%)", isTotal: true, displayValue: bop, sign: "total" },
  ];

  if (coreBuys > 0) {
    points.push({ label: "Core Buys", value: coreBuys, base: running, fill: "hsl(142, 76%, 36%)", displayValue: coreBuys, sign: "positive" });
    running += coreBuys;
  }

  if (nonCoreBuys > 0) {
    points.push({ label: "Non-Core Buys", value: nonCoreBuys, base: running, fill: "hsl(152, 60%, 52%)", displayValue: nonCoreBuys, sign: "positive" });
    running += nonCoreBuys;
  }

  if (coreSales > 0) {
    points.push({ label: "Core Sales", value: coreSales, base: running - coreSales, fill: "hsl(0, 84%, 60%)", displayValue: -coreSales, sign: "negative" });
    running -= coreSales;
  }

  if (nonCoreSales > 0) {
    points.push({ label: "Non-Core Sales", value: nonCoreSales, base: running - nonCoreSales, fill: "hsl(25, 95%, 53%)", displayValue: -nonCoreSales, sign: "negative" });
    running -= nonCoreSales;
  }

  if (Math.abs(gap) > 0.5) {
    if (gap > 0) {
      points.push({ label: "Other/Adj.", value: gap, base: running, fill: "hsl(var(--muted-foreground))", displayValue: gap, sign: "positive" });
    } else {
      points.push({ label: "Other/Adj.", value: -gap, base: running + gap, fill: "hsl(var(--muted-foreground))", displayValue: gap, sign: "negative" });
    }
    running += gap;
  }

  points.push({ label: "EoP Shares", value: eop, base: 0, fill: "hsl(217, 91%, 60%)", isTotal: true, displayValue: eop, sign: "total" });

  return points;
}

function WaterfallChart({ data }: { data: WaterfallPoint[] }) {
  if (!data.length) return <div className="flex h-[400px] items-center justify-center text-muted-foreground">No data.</div>;

  const margin = { top: 28, right: 16, bottom: 32, left: 60 };
  const [size, setSize] = useState({ w: 600, h: 400 });
  const ref = useMemo(() => {
    let ro: ResizeObserver | null = null;
    return (el: HTMLDivElement | null) => {
      ro?.disconnect();
      if (!el) return;
      ro = new ResizeObserver(([e]) => {
        const { width, height } = e.contentRect;
        if (width > 0 && height > 0) setSize({ w: width, h: height });
      });
      ro.observe(el);
      const { width, height } = el.getBoundingClientRect();
      if (width > 0 && height > 0) setSize({ w: width, h: height });
    };
  }, []);

  const chartW = size.w - margin.left - margin.right;
  const chartH = size.h - margin.top - margin.bottom;

  const tops = data.map((d) => d.base + d.value);
  const bottoms = data.map((d) => d.base);
  const yMax = Math.max(...tops) * 1.08;
  const yMin = Math.min(0, ...bottoms);

  const scaleY = (v: number) => margin.top + chartH * (1 - (v - yMin) / (yMax - yMin));
  const barW = chartW / data.length;
  const barPad = barW * 0.2;

  const ticks = useMemo(() => {
    const range = yMax - yMin;
    const rawStep = range / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const step = Math.ceil(rawStep / mag) * mag;
    const result: number[] = [];
    for (let v = Math.ceil(yMin / step) * step; v <= yMax; v += step) result.push(v);
    return result;
  }, [yMin, yMax]);

  const [hover, setHover] = useState<number | null>(null);

  return (
    <div ref={ref} className="h-[400px] w-full">
      <svg width={size.w} height={size.h} className="select-none">
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={margin.left}
              x2={size.w - margin.right}
              y1={scaleY(t)}
              y2={scaleY(t)}
              stroke="hsl(var(--muted))"
              strokeDasharray="3 3"
            />
            <text
              x={margin.left - 8}
              y={scaleY(t)}
              textAnchor="end"
              dominantBaseline="middle"
              fontSize={11}
              fill="hsl(var(--muted-foreground))"
            >
              {smartSharesFmt(t)}
            </text>
          </g>
        ))}

        {data.map((d, i) => {
          const x = margin.left + i * barW + barPad;
          const w = barW - barPad * 2;
          const top = scaleY(d.base + d.value);
          const bot = scaleY(d.base);
          const h = Math.max(Math.abs(bot - top), 1);
          const barY = Math.min(top, bot);

          const prevTop = i > 0 ? scaleY(data[i - 1].base + data[i - 1].value) : null;
          const connY = d.sign === "positive" ? barY + h : barY;

          return (
            <g
              key={d.label}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {i > 0 && !d.isTotal && prevTop != null && (
                <line
                  x1={margin.left + (i - 1) * barW + barW - barPad}
                  x2={x}
                  y1={connY}
                  y2={connY}
                  stroke="hsl(var(--muted-foreground))"
                  strokeDasharray="4 2"
                  strokeWidth={1}
                  opacity={0.5}
                />
              )}
              <rect x={x} y={barY} width={w} height={h} fill={d.fill} rx={3} ry={3} />
              <text
                x={x + w / 2}
                y={barY - 6}
                textAnchor="middle"
                fontSize={10}
                fill="hsl(var(--muted-foreground))"
              >
                {d.sign !== "total" && (d.sign === "positive" ? "+" : "")}
                {smartSharesFmt(d.displayValue)}
              </text>
              <text
                x={margin.left + i * barW + barW / 2}
                y={size.h - margin.bottom + 16}
                textAnchor="middle"
                fontSize={11}
                fill="hsl(var(--muted-foreground))"
              >
                {d.label}
              </text>
              {hover === i && (
                <g>
                  <rect
                    x={x + w / 2 - 60}
                    y={barY - 40}
                    width={120}
                    height={28}
                    rx={4}
                    fill="hsl(var(--card))"
                    stroke="hsl(var(--border))"
                  />
                  <text
                    x={x + w / 2}
                    y={barY - 22}
                    textAnchor="middle"
                    fontSize={11}
                    fill="hsl(var(--foreground))"
                  >
                    {d.sign === "positive" ? "+" : d.sign === "negative" ? "" : ""}
                    {formatNumber(d.displayValue)} shares
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function smartAxisFmt(v: number, prefix = "$"): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000_000) return `${prefix}${(v / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${prefix}${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${prefix}${(v / 1_000).toFixed(0)}k`;
  return `${prefix}${v}`;
}

function smartSharesFmt(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(v / 1_000).toFixed(0)}k`;
  return String(v);
}

export function InsiderDetailModal({
  insider,
  ticker,
  lookbackDays,
  coreSalesOnly,
  open,
  onOpenChange,
}: {
  insider: InsiderSummaryRow | null;
  ticker: string;
  lookbackDays: number;
  coreSalesOnly: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [view, setView] = useState<ChartView>("sales");

  const { data: txnData } = useQuery({
    queryKey: ["modal-transactions", ticker, lookbackDays, insider?.insider_cik],
    queryFn: () =>
      fetchTransactions(ticker, lookbackDays, {
        insider_cik: insider!.insider_cik,
        limit: 500,
        offset: 0,
      }),
    enabled: open && !!insider,
  });

  const { data: stockData } = useQuery({
    queryKey: ["stock-prices", ticker, lookbackDays],
    queryFn: () => fetchStockPrices(ticker, lookbackDays),
    enabled: open && !!insider,
    staleTime: 5 * 60 * 1000,
  });

  const transactions = txnData?.transactions ?? [];
  const stockPrices = stockData?.prices ?? [];

  const salesChartData = useMemo(
    () => (transactions.length > 0 ? buildSalesData(transactions, coreSalesOnly, stockPrices) : []),
    [transactions, coreSalesOnly, stockPrices]
  );

  const waterfallData = useMemo(
    () => (insider ? buildWaterfallData(insider) : []),
    [insider]
  );

  if (!insider) return null;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[90vw] max-w-4xl -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-card p-6 shadow-lg data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%]">
          <div className="flex items-center justify-between mb-4">
            <div>
              <Dialog.Title className="text-lg font-semibold">
                {insider.insider_name || insider.insider_cik}
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                {insider.officer_title || (insider.is_director ? "Director" : insider.is_officer ? "Officer" : "")}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="rounded-full p-1.5 hover:bg-muted transition-colors"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>

          <div className="flex gap-2 mb-4">
            <button
              type="button"
              onClick={() => setView("sales")}
              className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                view === "sales"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              Sales Over Time
            </button>
            <button
              type="button"
              onClick={() => setView("waterfall")}
              className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${
                view === "waterfall"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              Waterfall
            </button>
          </div>

          {view === "sales" && (
            <div className="h-[400px] w-full">
              {salesChartData.length === 0 ? (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                  No sales data in this period.
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={salesChartData} margin={{ top: 5, right: 60, left: 5, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                    <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                    <YAxis
                      yAxisId="left"
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v) => smartAxisFmt(v)}
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                    />
                    <YAxis yAxisId="price" orientation="right" hide />
                    <Tooltip
                      formatter={(value: number, name: string) => {
                        if (name === "% Holdings Sold") return [`${(value * 100).toFixed(2)}%`, name];
                        if (name === "Stock Price") return [`$${value.toFixed(2)}`, name];
                        return [formatCurrency(value), name];
                      }}
                    />
                    <Legend />
                    {salesChartData.some((d) => d.stockPrice != null) && (
                      <Line
                        yAxisId="price"
                        type="monotone"
                        dataKey="stockPrice"
                        name="Stock Price"
                        stroke="hsl(217, 91%, 60%)"
                        strokeWidth={1.5}
                        strokeDasharray="5 3"
                        dot={{ r: 3 }}
                        connectNulls
                      />
                    )}
                    <Bar
                      yAxisId="left"
                      dataKey="coreSalesUsd"
                      name="Core Sales ($)"
                      fill="hsl(0, 84%, 60%)"
                      stackId="sales"
                      radius={[0, 0, 0, 0]}
                    />
                    {!coreSalesOnly && (
                      <Bar
                        yAxisId="left"
                        dataKey="nonCoreSalesUsd"
                        name="Non-Core Sales ($)"
                        fill="hsl(25, 95%, 53%)"
                        stackId="sales"
                        radius={[2, 2, 0, 0]}
                      />
                    )}
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="pctSold"
                      name="% Holdings Sold"
                      stroke="hsl(262, 83%, 58%)"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      connectNulls
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
          )}

          {view === "waterfall" && (
            <WaterfallChart data={waterfallData} />
          )}

          <div className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <p className="text-muted-foreground">BoP Shares</p>
              <p className="font-medium">{formatNumber(insider.bop_shares)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">EoP Shares</p>
              <p className="font-medium">{formatNumber(insider.eop_shares)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Total Buys</p>
              <p className="font-medium text-green-600">{formatCurrency(insider.buys_usd)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Total Sales</p>
              <p className="font-medium text-red-600">{formatCurrency(insider.sales_total_usd)}</p>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
