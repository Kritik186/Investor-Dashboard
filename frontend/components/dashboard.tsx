"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Toast, ToastViewport } from "@/components/ui/toast";
import { Search, RefreshCw, BarChart3, TrendingUp, Percent, Table2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select } from "@/components/ui/select";
import {
  resolveTicker,
  syncTicker,
  fetchKpis,
  fetchTop,
  fetchAggregates,
  fetchTransactions,
  type Kpis,
  type Transaction,
} from "@/lib/api";
import { formatCurrency, formatNumber, formatDate } from "@/lib/utils";
import { HoldingsChart } from "@/components/dashboard/holdings-chart";
import { ActivityCharts } from "@/components/dashboard/activity-charts";
import { PctSoldTab } from "@/components/dashboard/pct-sold-tab";
import { TransactionsTable } from "@/components/dashboard/transactions-table";

const LOOKBACK_PRESETS = [
  { value: 30, label: "30d" },
  { value: 60, label: "60d" },
  { value: 90, label: "90d" },
  { value: 180, label: "180d" },
  { value: 365, label: "1y" },
  { value: 1095, label: "3y" },
];
const LOOKBACK_MIN = 1;
const LOOKBACK_MAX = 3650; // ~10 years
const isPreset = (days: number) => LOOKBACK_PRESETS.some((p) => p.value === days);

export function Dashboard() {
  const [tickerInput, setTickerInput] = useState("AAPL");
  const [ticker, setTicker] = useState<string | null>("AAPL");
  const [lookbackDays, setLookbackDays] = useState(365);
  const [isCustomMode, setIsCustomMode] = useState(false);
  const [customInputStr, setCustomInputStr] = useState("30"); // string so user can type/clear freely
  const [period, setPeriod] = useState<"month" | "quarter">("month");
  const [toastOpen, setToastOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState<{ title: string; description?: string; variant?: "success" | "error" }>({ title: "" });
  const queryClient = useQueryClient();
  const customDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Commit custom days to lookbackDays after user stops typing (so lookback APIs refetch once and dashboard updates)
  const showCustomInput = isCustomMode || !isPreset(lookbackDays);
  useEffect(() => {
    if (!showCustomInput) return;
    const n = parseInt(customInputStr, 10);
    if (Number.isNaN(n)) return;
    const clamped = Math.max(LOOKBACK_MIN, Math.min(LOOKBACK_MAX, n));
    if (customDebounceRef.current) clearTimeout(customDebounceRef.current);
    customDebounceRef.current = setTimeout(() => {
      customDebounceRef.current = null;
      setLookbackDays(clamped);
    }, 500);
    return () => {
      if (customDebounceRef.current) clearTimeout(customDebounceRef.current);
    };
  }, [customInputStr, showCustomInput]);

  // When lookback or ticker changes, invalidate dashboard queries so they refetch (fixes preset + custom not updating)
  useEffect(() => {
    if (!ticker) return;
    queryClient.invalidateQueries({ queryKey: ["kpis", ticker] });
    queryClient.invalidateQueries({ queryKey: ["top", ticker] });
    queryClient.invalidateQueries({ queryKey: ["aggregates", ticker] });
    queryClient.invalidateQueries({ queryKey: ["transactions", ticker] });
  }, [lookbackDays, ticker, queryClient]);

  const showToast = useCallback((title: string, description?: string) => {
    setToastMessage({ title, description });
    setToastOpen(true);
  }, []);

  const handleSearch = useCallback(async () => {
    const t = tickerInput.trim().toUpperCase();
    if (!t) return;
    try {
      await resolveTicker(t);
      setTicker(t);
    } catch (e) {
      showToast("Ticker not found", (e as Error).message);
    }
  }, [tickerInput, showToast]);

  const handleRefresh = useCallback(async () => {
    if (!ticker) return;
    try {
      const res = await syncTicker(ticker, lookbackDays);
      showToast("Refresh complete", `${res.transactions_created} new transactions stored.`);
      queryClient.invalidateQueries({ queryKey: [ticker] });
    } catch (e) {
      showToast("Refresh failed", (e as Error).message);
    }
  }, [ticker, lookbackDays, showToast, queryClient]);

  const { data: kpis, isLoading: kpisLoading } = useQuery({
    queryKey: ["kpis", ticker, lookbackDays],
    queryFn: () => fetchKpis(ticker!, lookbackDays),
    enabled: !!ticker,
  });

  const { data: topData } = useQuery({
    queryKey: ["top", ticker, lookbackDays],
    queryFn: () => fetchTop(ticker!, lookbackDays),
    enabled: !!ticker,
  });

  const { data: aggregatesData } = useQuery({
    queryKey: ["aggregates", ticker, lookbackDays, period],
    queryFn: () => fetchAggregates(ticker!, lookbackDays, period),
    enabled: !!ticker,
  });

  const { data: transactionsData } = useQuery({
    queryKey: ["transactions", ticker, lookbackDays],
    queryFn: () => fetchTransactions(ticker!, lookbackDays, { limit: 100, offset: 0 }),
    enabled: !!ticker,
  });

  return (
    <div className="container mx-auto max-w-7xl space-y-6 p-6">
      <header className="flex flex-wrap items-center gap-4 border-b border-border pb-6">
        <h1 className="text-2xl font-bold tracking-tight">Insider Trading Dashboard</h1>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Ticker (e.g. AAPL)"
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              className="w-36 pl-9"
            />
          </div>
          <Button onClick={handleSearch} variant="secondary">Search</Button>
          <div className="flex items-center gap-2">
            <Select
              value={showCustomInput ? "custom" : String(lookbackDays)}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "custom") {
                  setIsCustomMode(true);
                  setCustomInputStr(String(lookbackDays));
                } else {
                  setIsCustomMode(false);
                  setLookbackDays(Number(v));
                }
              }}
              className="w-24"
            >
              {LOOKBACK_PRESETS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
              <option value="custom">Custom</option>
            </Select>
            {showCustomInput && (
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  min={LOOKBACK_MIN}
                  max={LOOKBACK_MAX}
                  placeholder={`${LOOKBACK_MIN}-${LOOKBACK_MAX}`}
                  value={customInputStr}
                  onChange={(e) => setCustomInputStr(e.target.value)}
                  onBlur={() => {
                    const n = parseInt(customInputStr, 10);
                    const clamped = Number.isNaN(n) || n < LOOKBACK_MIN || n > LOOKBACK_MAX
                      ? Math.max(LOOKBACK_MIN, Math.min(LOOKBACK_MAX, lookbackDays))
                      : Math.max(LOOKBACK_MIN, Math.min(LOOKBACK_MAX, n));
                    setLookbackDays(clamped);
                    setCustomInputStr(String(clamped));
                    if (customDebounceRef.current) {
                      clearTimeout(customDebounceRef.current);
                      customDebounceRef.current = null;
                    }
                  }}
                  className="w-16 h-10 text-center"
                />
                <span className="text-sm text-muted-foreground">days</span>
              </div>
            )}
          </div>
          <div className="flex rounded-md border border-input bg-background p-1">
            <button
              type="button"
              onClick={() => setPeriod("month")}
              className={`rounded px-3 py-1 text-sm ${period === "month" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
            >
              Month
            </button>
            <button
              type="button"
              onClick={() => setPeriod("quarter")}
              className={`rounded px-3 py-1 text-sm ${period === "quarter" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
            >
              Quarter
            </button>
          </div>
          <Button onClick={handleRefresh} disabled={!ticker} variant="outline" size="sm">
            <RefreshCw className="mr-2 h-4 w-4" /> Refresh
          </Button>
        </div>
      </header>

      {ticker && (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <KpiCard title="Total $ Sold" value={kpis?.total_value_sold_usd} format="currency" loading={kpisLoading} />
            <KpiCard title="Total $ Bought" value={kpis?.total_value_bought_usd} format="currency" loading={kpisLoading} />
            <KpiCard title="Net Shares" value={kpis?.net_shares} format="number" loading={kpisLoading} />
            <KpiCard title="# Filings" value={kpis?.filings_count} format="number" loading={kpisLoading} />
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">Last Refresh</CardTitle>
              </CardHeader>
              <CardContent>
                <span className="text-lg font-semibold">
                  {kpisLoading ? "—" : kpis?.last_refresh ? formatDate(kpis.last_refresh) : "—"}
                </span>
              </CardContent>
            </Card>
          </section>

          <Tabs defaultValue="holdings" className="space-y-4">
            <TabsList className="grid w-full grid-cols-4 lg:w-auto lg:inline-grid">
              <TabsTrigger value="holdings" className="gap-2">
                <TrendingUp className="h-4 w-4" /> Holdings
              </TabsTrigger>
              <TabsTrigger value="activity" className="gap-2">
                <BarChart3 className="h-4 w-4" /> Activity
              </TabsTrigger>
              <TabsTrigger value="pct-sold" className="gap-2">
                <Percent className="h-4 w-4" /> % Sold
              </TabsTrigger>
              <TabsTrigger value="transactions" className="gap-2">
                <Table2 className="h-4 w-4" /> Transactions
              </TabsTrigger>
            </TabsList>
            <TabsContent value="holdings" className="space-y-4">
              <HoldingsChart
                ticker={ticker!}
                lookbackDays={lookbackDays}
                period={period}
                topInsiders={topData?.top_insiders ?? []}
              />
            </TabsContent>
            <TabsContent value="activity" className="space-y-4">
              <ActivityCharts aggregates={aggregatesData?.aggregates ?? []} />
            </TabsContent>
            <TabsContent value="pct-sold" className="space-y-4">
              <PctSoldTab aggregates={aggregatesData?.aggregates ?? []} period={period} />
            </TabsContent>
            <TabsContent value="transactions" className="space-y-4">
              <TransactionsTable ticker={ticker} lookbackDays={lookbackDays} initialData={transactionsData?.transactions ?? []} />
            </TabsContent>
          </Tabs>
        </>
      )}

      {!ticker && (
        <Card className="p-12 text-center">
          <p className="text-muted-foreground">Enter a ticker and click Search to load the dashboard (e.g. AAPL).</p>
        </Card>
      )}

      <Toast open={toastOpen} onOpenChange={setToastOpen} title={toastMessage.title} description={toastMessage.description} />
      <ToastViewport />
    </div>
  );
}

function KpiCard({
  title,
  value,
  format,
  loading,
}: {
  title: string;
  value: number | undefined;
  format: "currency" | "number";
  loading?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <span className="text-2xl font-bold">
          {loading ? "—" : format === "currency" ? formatCurrency(value) : formatNumber(value)}
        </span>
      </CardContent>
    </Card>
  );
}
