const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ResolveResult = { cik10: string; name: string };
export type DefaultCompany = { ticker: string; label: string };
export type TopInsider = { insider_cik: string; insider_name: string; shares_held_recent: number };
export type Holding = { insider_cik: string; insider_name: string; date: string; shares_owned_following: number };
export type Aggregate = {
  insider_cik: string;
  insider_name: string;
  period_end: string;
  shares_sold: number;
  shares_bought: number;
  value_sold_usd: number | null;
  value_bought_usd: number | null;
  start_shares: number | null;
  pct_sold: number | null;
  pct_sold_label: string | null;
};
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

export async function fetchTop(ticker: string, lookback_days: number): Promise<{ top_insiders: TopInsider[] }> {
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/top?lookback_days=${lookback_days}`);
  if (!res.ok) throw new Error("Failed to fetch top insiders");
  return res.json();
}

export async function fetchHoldings(ticker: string, lookback_days: number): Promise<{ holdings: Holding[] }> {
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/holdings?lookback_days=${lookback_days}`);
  if (!res.ok) throw new Error("Failed to fetch holdings");
  return res.json();
}

export async function fetchInsiderActivity(
  ticker: string,
  insider_cik: string,
  lookback_days: number,
  period: "month" | "quarter"
): Promise<{ activity: InsiderActivityPoint[] }> {
  const res = await fetch(
    `${API_URL}/api/${encodeURIComponent(ticker)}/insider/${encodeURIComponent(insider_cik)}/activity?lookback_days=${lookback_days}&period=${period}`
  );
  if (!res.ok) throw new Error("Failed to fetch insider activity");
  return res.json();
}

export async function fetchAggregates(ticker: string, lookback_days: number, period: "month" | "quarter"): Promise<{ aggregates: Aggregate[] }> {
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/aggregates?lookback_days=${lookback_days}&period=${period}`);
  if (!res.ok) throw new Error("Failed to fetch aggregates");
  return res.json();
}

export async function fetchTransactions(
  ticker: string,
  lookback_days: number,
  opts?: { insider_cik?: string; limit?: number; offset?: number }
): Promise<{ transactions: Transaction[]; limit: number; offset: number }> {
  const params = new URLSearchParams({ lookback_days: String(lookback_days) });
  if (opts?.insider_cik) params.set("insider_cik", opts.insider_cik);
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  if (opts?.offset != null) params.set("offset", String(opts.offset));
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/transactions?${params}`);
  if (!res.ok) throw new Error("Failed to fetch transactions");
  return res.json();
}

export async function fetchKpis(ticker: string, lookback_days: number): Promise<Kpis> {
  const res = await fetch(`${API_URL}/api/${encodeURIComponent(ticker)}/kpis?lookback_days=${lookback_days}`);
  if (!res.ok) throw new Error("Failed to fetch KPIs");
  return res.json();
}
