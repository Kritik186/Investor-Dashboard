const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ResolveResult = { cik10: string; name: string };
export type DefaultCompany = { ticker: string; label: string };
export type TopInsider = { insider_cik: string; insider_name: string; shares_held_recent: number };
export type Holding = { insider_cik: string; insider_name: string; date: string; shares_owned_following: number };
export type DispositionLink = { transaction_date: string; shares: number; xml_url: string | null; is_margin_call_collateral?: boolean };

export type Aggregate = {
  insider_cik: string;
  insider_name: string;
  period_start?: string;
  period_end: string;
  shares_sold: number;
  shares_bought: number;
  value_sold_usd: number | null;
  value_bought_usd: number | null;
  start_shares: number | null;
  end_shares: number | null;
  change_shares: number | null;
  pct_sold: number | null;
  pct_sold_label: string | null;
  period_10b5_1_status?: "all" | "mixed" | "none";
  plan_adoption_date?: string | null;
  is_margin_call_collateral?: boolean;
  /** Low-signal: RSU vest (M), tax withholding (F), gift (G), 10b5-1 */
  has_rsu_vest?: boolean;
  has_tax_withholding?: boolean;
  has_gift?: boolean;
  /** Ownership/role: title, 10% owner before transaction */
  officer_title?: string | null;
  is_ten_percent_owner?: boolean;
  dispositions?: DispositionLink[];
};

/** Slug for API: P, S, 10b5-1, rsu_vest, tax_withholding, gift */
export type TransactionTypeSlug = "P" | "S" | "10b5-1" | "rsu_vest" | "tax_withholding" | "gift";
export type Transaction = {
  id: number | null;
  accession: string;
  company_cik: string;
  insider_cik: string;
  insider_name: string;
  is_director: boolean;
  is_officer: boolean;
  officer_title: string | null;
  security_title: string | null;
  transaction_date: string;
  transaction_code: string | null;
  acq_disp: string | null;
  shares: number | null;
  price: number | null;
  value_usd: number | null;
  shares_owned_following: number | null;
  xml_url: string | null;
};
export type Kpis = {
  ticker: string;
  lookback_days: number;
  total_value_sold_usd: number;
  total_value_bought_usd: number;
  total_shares_sold: number;
  total_shares_bought: number;
  net_shares: number;
  filings_count: number;
  last_refresh: string | null;
};

export type InsiderActivityPoint = {
  period_end: string;
  shares_bought: number;
  shares_sold: number;
  value_bought_usd: number | null;
  value_sold_usd: number | null;
};

export type InsiderSummaryRow = {
  insider_cik: string;
  insider_name: string;
  officer_title: string | null;
  is_director: boolean;
  is_officer: boolean;
  is_ten_percent_owner: boolean;
  bop_shares: number | null;
  eop_shares: number | null;
  pct_owner_post_sales: number | null;
  buys_usd: number;
  buys_shares: number;
  avg_cost_basis_buys: number | null;
  purchases_pct_bop: number | null;
  sales_total_usd: number;
  sales_core_usd: number;
  sales_core_shares: number;
  avg_cost_basis_core_sales: number | null;
  sales_pct_bop: number | null;
  sales_non_core_usd: number;
  sales_non_core_pct_total: number | null;
  net_buyer_or_seller: "Buyer" | "Seller" | "Neutral";
};

export type ClusterPeriod = {
  period: string;
  sellers: string[];
};

export type InsiderSummaryResponse = {
  ticker: string;
  lookback_days: number;
  insiders: InsiderSummaryRow[];
  cluster_periods: ClusterPeriod[];
};

export type StockPricePoint = { date: string; close: number };

export async function fetchStockPrices(
  ticker: string,
  lookback_days: number,
): Promise<{ ticker: string; prices: StockPricePoint[] }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/stock-prices?${params}`);
  if (!res.ok) throw new Error("Failed to fetch stock prices");
  return res.json();
}

export async function fetchInsiderSummary(
  ticker: string,
  lookback_days: number,
): Promise<InsiderSummaryResponse> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/insider-summary?${params}`);
  if (!res.ok) throw new Error("Failed to fetch insider summary");
  return res.json();
}

export async function fetchDefaultCompanies(): Promise<{ companies: DefaultCompany[] }> {
  const res = await fetch(`${API_URL}/api/default-companies`);
  if (!res.ok) throw new Error("Failed to fetch default companies");
  return res.json();
}

export async function resolveTicker(ticker: string): Promise<ResolveResult> {
  const res = await fetch(`${API_URL}/api/resolve?ticker=${encodeURIComponent(ticker)}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Ticker not found");
  }
  return res.json();
}

export async function syncTicker(ticker: string, lookback_days: number, max_forms?: number): Promise<{ ticker: string; transactions_created: number }> {
  const res = await fetch(`${API_URL}/api/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, lookback_days, max_forms: max_forms ?? 100 }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Sync failed");
  }
  return res.json();
}

export async function refreshTicker(ticker: string, lookback_days: number): Promise<{ ticker: string; transactions_created: number }> {
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, lookback_days, max_forms: 100 }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Refresh failed");
  }
  return res.json();
}

export type BackfillResult = {
  ticker: string;
  backfill: boolean;
  transactions_created: number;
  processed: number;
};

export async function backfillTicker(
  ticker: string,
  lookback_days: number,
  max_forms?: number
): Promise<BackfillResult> {
  const params = new URLSearchParams({
    lookback_days: String(lookback_days),
    max_forms: String(max_forms ?? 500),
  });
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/backfill?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Backfill failed");
  }
  return res.json();
}

export type TransactionTypeFilter = {
  transaction_types: string[];
};

function appendFilterParams(params: URLSearchParams, filter: TransactionTypeFilter): void {
  if (filter.transaction_types.length > 0) params.set("transaction_types", filter.transaction_types.join(","));
}

export async function fetchTop(
  ticker: string,
  lookback_days: number,
  filter?: TransactionTypeFilter
): Promise<{ top_insiders: TopInsider[] }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  if (filter) appendFilterParams(params, filter);
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/top?${params}`);
  if (!res.ok) throw new Error("Failed to fetch top insiders");
  return res.json();
}

export async function fetchHoldings(
  ticker: string,
  lookback_days: number,
  filter?: TransactionTypeFilter
): Promise<{ holdings: Holding[] }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  if (filter) appendFilterParams(params, filter);
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/holdings?${params}`);
  if (!res.ok) throw new Error("Failed to fetch holdings");
  return res.json();
}

export async function fetchInsiderActivity(
  ticker: string,
  insider_cik: string,
  lookback_days: number,
  period: "month" | "quarter",
  filter?: TransactionTypeFilter
): Promise<{ activity: InsiderActivityPoint[] }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days), period });
  if (filter) appendFilterParams(params, filter);
  const res = await fetch(
    `${API_URL}/api/${encodeURIComponent(ticker)}/insider/${encodeURIComponent(insider_cik)}/activity?${params}`
  );
  if (!res.ok) throw new Error("Failed to fetch insider activity");
  return res.json();
}

export async function fetchAggregates(
  ticker: string,
  lookback_days: number,
  period: "month" | "quarter",
  transaction_types: string[] = []
): Promise<{ aggregates: Aggregate[] }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days), period });
  if (transaction_types.length > 0) params.set("transaction_types", transaction_types.join(","));
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/aggregates?${params}`);
  if (!res.ok) throw new Error("Failed to fetch aggregates");
  return res.json();
}

export async function deleteCompany(ticker: string): Promise<{ ticker: string; deleted: boolean }> {
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}`, { method: "DELETE" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || "Delete failed");
  }
  return res.json();
}

export async function fetchTransactions(
  ticker: string,
  lookback_days: number,
  opts?: { insider_cik?: string; limit?: number; offset?: number; transaction_types?: string[] }
): Promise<{ transactions: Transaction[]; limit: number; offset: number }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  if (opts?.insider_cik) params.set("insider_cik", opts.insider_cik);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  if (opts?.transaction_types && opts.transaction_types.length > 0)
    params.set("transaction_types", opts.transaction_types.join(","));
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/transactions?${params}`);
  if (!res.ok) throw new Error("Failed to fetch transactions");
  return res.json();
}

export async function fetchKpis(
  ticker: string,
  lookback_days: number,
  filter?: TransactionTypeFilter
): Promise<Kpis> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  if (filter) appendFilterParams(params, filter);
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/kpis?${params}`);
  if (!res.ok) throw new Error("Failed to fetch KPIs");
  return res.json();
}
