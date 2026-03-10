"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Toast, ToastViewport } from "@/components/ui/toast";
import { Search, RefreshCw, TrendingUp, Percent, Table2, X, Loader2 } from "lucide-react";
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
  fetchDefaultCompanies,
  deleteCompany,
  type Kpis,
  type Transaction,
  type DefaultCompany,
} from "@/lib/api";
import { formatCurrency, formatNumber, formatDate } from "@/lib/utils";
import { HoldingsChart } from "@/components/dashboard/holdings-chart";
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

const CUSTOM_COMPANIES_KEY = "insider-dashboard-custom-companies";
const REMOVED_COMPANIES_KEY = "insider-dashboard-removed-tickers";

function loadCustomCompanies(): DefaultCompany[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(CUSTOM_COMPANIES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as DefaultCompany[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveCustomCompanies(list: DefaultCompany[]) {
  try {
    localStorage.setItem(CUSTOM_COMPANIES_KEY, JSON.stringify(list));
  } catch {
    /* ignore */
  }
}

function loadRemovedTickers(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(REMOVED_COMPANIES_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as string[];
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch {
    return new Set();
  }
}

function saveRemovedTickers(set: Set<string>) {
  try {
    localStorage.setItem(REMOVED_COMPANIES_KEY, JSON.stringify(Array.from(set)));
  } catch {
    /* ignore */
  }
}

const DEFAULT_COMPANIES_FALLBACK: DefaultCompany[] = [
  { ticker: "AMZN", label: "Amazon" },
  { ticker: "RBLX", label: "Roblox" },
  { ticker: "CVNA", label: "Carvana" },
  { ticker: "META", label: "Meta" },
  { ticker: "CPNG", label: "Coupang" },
  { ticker: "TTAN", label: "ServiceTitan" },
];

export function Dashboard() {
  const { data: defaultCompaniesData } = useQuery({
    queryKey: ["default-companies"],
    queryFn: fetchDefaultCompanies,
    placeholderData: { companies: DEFAULT_COMPANIES_FALLBACK },
  });
  const defaultCompanies = defaultCompaniesData?.companies ?? DEFAULT_COMPANIES_FALLBACK;
  const [customCompanies, setCustomCompanies] = useState<DefaultCompany[]>([]);
  const [removedTickers, setRemovedTickers] = useState<Set<string>>(new Set());
  // Load custom and removed lists after mount to avoid hydration mismatch
  useEffect(() => {
    setCustomCompanies(loadCustomCompanies());
    setRemovedTickers(loadRemovedTickers());
  }, []);
  const visibleDefaults = defaultCompanies.filter((c) => !removedTickers.has(c.ticker));
  const allCompanies = [...visibleDefaults, ...customCompanies];
  const defaultTicker = allCompanies[0]?.ticker ?? "AMZN";

  const [tickerInput, setTickerInput] = useState("");
  const [ticker, setTicker] = useState<string | null>(defaultTicker);
  const [addToListPrompt, setAddToListPrompt] = useState<{ ticker: string; label: string } | null>(null);
  const [lookbackDays, setLookbackDays] = useState(365);
  const [isCustomMode, setIsCustomMode] = useState(false);
  const [customInputStr, setCustomInputStr] = useState("30"); // string so user can type/clear freely
  const [period, setPeriod] = useState<"month" | "quarter">("month");
  const [filter10b5_1, setFilter10b5_1] = useState<"all" | "only" | "exclude">("all");
  const [toastOpen, setToastOpen] = useState(false);
  const [toastMessage, setToastMessage] = useState<{ title: string; description?: string; variant?: "success" | "error" }>({ title: "" });
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState<string>("");
  const [deletingTicker, setDeletingTicker] = useState<string | null>(null);
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

  // When lookback or ticker changes, invalidate dashboard queries so they refetch
  useEffect(() => {
    if (!ticker) return;
    queryClient.invalidateQueries({ queryKey: ["kpis", ticker] });
    queryClient.invalidateQueries({ queryKey: ["top", ticker] });
    queryClient.invalidateQueries({ queryKey: ["aggregates", ticker] });
    queryClient.invalidateQueries({ queryKey: ["transactions", ticker] });
  }, [lookbackDays, ticker, queryClient]);

  // Auto-sync when company changes so data flows without clicking Refresh; show progress
  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setIsSyncing(true);
    setSyncProgress("Resolving company & fetching filings…");
    syncTicker(ticker, lookbackDays)
      .then((res) => {
        if (!cancelled) {
          setSyncProgress("Storing data…");
          queryClient.invalidateQueries({ queryKey: ["kpis", ticker] });
          queryClient.invalidateQueries({ queryKey: ["top", ticker] });
          queryClient.invalidateQueries({ queryKey: ["aggregates", ticker] });
          queryClient.invalidateQueries({ queryKey: ["transactions", ticker] });
        }
      })
      .catch(() => { /* ignore; user can click Refresh */ })
      .finally(() => {
        if (!cancelled) {
          setIsSyncing(false);
          setSyncProgress("");
        }
      });
    return () => { cancelled = true; };
  }, [ticker, queryClient]);

  const showToast = useCallback((title: string, description?: string) => {
    setToastMessage({ title, description });
    setToastOpen(true);
  }, []);

  const handleSearch = useCallback(async () => {
    const t = tickerInput.trim().toUpperCase();
    if (!t) return;
    try {
      const resolved = await resolveTicker(t);
      setTicker(t);
      setTickerInput(t);
      const alreadyInList = defaultCompanies.some((c) => c.ticker === t) || customCompanies.some((c) => c.ticker === t);
      if (!alreadyInList) {
        setAddToListPrompt({ ticker: t, label: resolved.name || t });
      }
    } catch (e) {
      showToast("Ticker not found", (e as Error).message);
    }
  }, [tickerInput, showToast, defaultCompanies, customCompanies]);

  const handleRefresh = useCallback(async () => {
    if (!ticker) return;
    setIsSyncing(true);
    setSyncProgress("Fetching data from SEC…");
    try {
      const res = await syncTicker(ticker, lookbackDays);
      showToast("Data fetching complete", `${res.transactions_created} new transactions stored. Data will update below.`);
      queryClient.invalidateQueries({ queryKey: ["kpis", ticker] });
      queryClient.invalidateQueries({ queryKey: ["top", ticker] });
      queryClient.invalidateQueries({ queryKey: ["aggregates", ticker] });
      queryClient.invalidateQueries({ queryKey: ["transactions", ticker] });
    } catch (e) {
      showToast("Refresh failed", (e as Error).message);
    } finally {
      setIsSyncing(false);
      setSyncProgress("");
    }
  }, [ticker, lookbackDays, showToast, queryClient]);

  const handleDeleteCompany = useCallback(
    async (c: DefaultCompany) => {
      if (!window.confirm(`Remove ${c.label} (${c.ticker}) from the dashboard and delete its data from the server?`)) return;
      setDeletingTicker(c.ticker);
      try {
        await deleteCompany(c.ticker);
        const isCustom = customCompanies.some((x) => x.ticker === c.ticker);
        if (isCustom) {
          const next = customCompanies.filter((x) => x.ticker !== c.ticker);
          setCustomCompanies(next);
          saveCustomCompanies(next);
        } else {
          const next = new Set(removedTickers);
          next.add(c.ticker);
          setRemovedTickers(next);
          saveRemovedTickers(next);
        }
        if (ticker === c.ticker) {
          const remaining = allCompanies.filter((x) => x.ticker !== c.ticker);
          setTicker(remaining[0]?.ticker ?? null);
          setTickerInput("");
        }
        showToast("Company removed", `${c.label} has been removed and its data deleted.`);
      } catch (e) {
        showToast("Delete failed", (e as Error).message);
      } finally {
        setDeletingTicker(null);
      }
    },
    [customCompanies, removedTickers, ticker, allCompanies, showToast]
  );

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
    queryKey: ["aggregates", ticker, lookbackDays, period, filter10b5_1],
    queryFn: () => fetchAggregates(ticker!, lookbackDays, period, filter10b5_1),
    enabled: !!ticker,
  });

  const { data: transactionsData } = useQuery({
    queryKey: ["transactions", ticker, lookbackDays],
    queryFn: () => fetchTransactions(ticker!, lookbackDays, { limit: 100, offset: 0 }),
    enabled: !!ticker,
  });

  return (
    <div className="container relative mx-auto max-w-7xl space-y-6 p-6">
      {isSyncing && (
        <div className="absolute inset-0 z-50 flex items-start justify-center bg-background/80 pt-24 backdrop-blur-[2px]">
          <div className="flex flex-col items-center gap-3 rounded-lg border border-border bg-card px-6 py-4 shadow-lg">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-sm font-medium">Syncing data for {ticker ?? "company"}</p>
            <p className="text-xs text-muted-foreground">{syncProgress || "Please wait…"}</p>
          </div>
        </div>
      )}
      <header className="flex flex-col gap-4 border-b border-border pb-6">
        <h1 className="text-2xl font-bold tracking-tight">Insider Trading Dashboard</h1>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-muted-foreground">Company:</span>
          <div className="flex flex-wrap gap-2">
            {allCompanies.map((c) => {
              const isSelected = ticker === c.ticker;
              const isDeleting = deletingTicker === c.ticker;
              return (
                <div
                  key={c.ticker}
                  className={`group flex items-center rounded-full border transition-colors ${
                    isSelected
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-input bg-muted/50 hover:bg-muted hover:border-muted-foreground/20"
                  }`}
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 rounded-l-full py-1.5 pl-3 pr-2 text-left text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
                    onClick={() => {
                      setTicker(c.ticker);
                      setTickerInput("");
                    }}
                  >
                    <span className="truncate">{c.label}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${c.label} from list`}
                    disabled={isDeleting}
                    className={`shrink-0 rounded-full p-1 transition-opacity focus:outline-none focus:ring-2 focus:ring-ring rounded-r-full ${
                      isDeleting ? "opacity-100" : "opacity-0 group-hover:opacity-100"
                    } ${isSelected ? "text-primary-foreground/80 hover:bg-primary-foreground/20" : "text-muted-foreground hover:bg-destructive/15 hover:text-destructive"}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteCompany(c);
                    }}
                  >
                    {isDeleting ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <X className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>
              );
            })}
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-muted-foreground">Other:</span>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Ticker (e.g. AAPL)"
                value={tickerInput}
                onChange={(e) => setTickerInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="w-28 h-9 pl-8"
              />
            </div>
            <Button onClick={handleSearch} variant="secondary" size="sm">Search</Button>
          </div>
        </div>
        {addToListPrompt && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-2 text-sm">
            <span className="text-muted-foreground">
              Add <strong className="text-foreground">{addToListPrompt.label}</strong> ({addToListPrompt.ticker}) to your company list?
            </span>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  const next = [...customCompanies, { ticker: addToListPrompt.ticker, label: addToListPrompt.label }];
                  setCustomCompanies(next);
                  saveCustomCompanies(next);
                  setAddToListPrompt(null);
                  showToast("Added to list", `${addToListPrompt.label} is now in your company list.`);
                }}
              >
                Add to list
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setAddToListPrompt(null)}
              >
                No thanks
              </Button>
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
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
          <Select
            value={filter10b5_1}
            onChange={(e) => setFilter10b5_1(e.target.value as "all" | "only" | "exclude")}
            className="w-[180px]"
          >
            <option value="all">All transactions</option>
            <option value="only">10b5-1 only</option>
            <option value="exclude">Non-10b5-1</option>
          </Select>
          <Button onClick={handleRefresh} disabled={!ticker || isSyncing} variant="outline" size="sm">
            <RefreshCw className={`mr-2 h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} />
            {isSyncing ? "Syncing…" : "Refresh"}
          </Button>
          {isSyncing && syncProgress && (
            <span className="text-sm text-muted-foreground">{syncProgress}</span>
          )}
        </div>
      </header>

      {ticker && (
        <>
          <section className="grid gap-4 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4">
            <KpiCard title="Total $ Sold" value={kpis?.total_value_sold_usd} format="currency" loading={kpisLoading} />
            <KpiCard title="Total $ Bought" value={kpis?.total_value_bought_usd} format="currency" loading={kpisLoading} />
            <KpiCard title="Shares Sold" value={kpis?.total_shares_sold} format="number" loading={kpisLoading} />
            <KpiCard title="Shares Bought" value={kpis?.total_shares_bought} format="number" loading={kpisLoading} />
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
            <TabsList className="grid w-full grid-cols-3 lg:w-auto lg:inline-grid">
              <TabsTrigger value="holdings" className="gap-2">
                <TrendingUp className="h-4 w-4" /> Holdings
              </TabsTrigger>
              <TabsTrigger value="pct-sold" className="gap-2">
                <Percent className="h-4 w-4" /> Shareholding change
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
            <TabsContent value="pct-sold" className="space-y-4">
              <PctSoldTab
                aggregates={aggregatesData?.aggregates ?? []}
                period={period}
                topInsiders={topData?.top_insiders ?? []}
                filter10b5_1={filter10b5_1}
              />
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
