# Insider Trading Dashboard — Product Specification

## 1. Overview

**Product name:** Insider Trading Dashboard (Fancy Insider Trading Dashboard)

**Purpose:** A web application that lets users view **SEC Form 4** insider trading data for US public companies: resolve stock tickers to companies, sync Form 4 filings from the SEC, and explore top insiders, holdings over time, buy/sell activity, and individual transactions.

**Stack:**
- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, Recharts, TanStack Table, TanStack Query
- **Backend:** FastAPI, SQLModel, requests, pandas
- **Data store:** PostgreSQL (production/Docker) or SQLite (local dev)
- **External data:** SEC EDGAR (public APIs and filings)

---

## 2. How It Works End-to-End

### 2.1 User flow

1. **Search:** User enters a ticker (e.g. AAPL) and clicks Search. The app resolves the ticker to a company (CIK and name) via the SEC.
2. **Sync (Refresh):** User clicks Refresh (or the app can sync on first load). The backend fetches the company’s recent Form 4 filings from the SEC, parses each filing’s XML, and stores companies, insiders, filings, and transactions in the database. Data is cached by accession number so the same filing is not re-downloaded.
3. **View:** User sees:
   - **KPI cards:** Total $ sold, total $ bought, net shares, # filings, last refresh (over a chosen lookback period).
   - **Lookback:** Preset ranges (30d, 60d, 90d, 180d, 1y, 3y) or a custom number of days (1–3650). All metrics and charts respect this lookback.
   - **Tabs:**
     - **Holdings:** Holdings over time for the top 15 insiders (by absolute transaction value); user can pick an insider to see their activity.
     - **Activity:** Monthly/quarterly aggregates (shares bought/sold, value) for the top 15.
     - **% Sold:** Per-insider percentage sold and related metrics.
     - **Transactions:** Paginated table of transactions with optional filter by insider; each row can link to the SEC filing XML (readable URL).

All dashboard data is filtered by the selected **lookback period** and is read from the local database after sync; the SEC is only called for resolve and sync.

### 2.2 Data flow (high level)

```
User (browser)
    → Frontend (Next.js, port 3000)
        → Backend API (FastAPI, port 8000)
            → Database (PostgreSQL or SQLite)
            → SEC EDGAR (HTTPS) — only for resolve + sync
```

- **Resolve:** One-off SEC call to resolve ticker → CIK + company name.
- **Sync:** SEC company submissions → list of Form 4 filings → for each new filing: fetch index, pick Form 4 XML, fetch XML, parse → write companies, insiders, filings, transactions to DB.
- **All other endpoints:** Read-only from DB (filtered by ticker and lookback_days).

---

## 3. Components

### 3.1 Frontend

| Component | Role |
|-----------|------|
| **App (Next.js)** | Single-page app; root layout and global styles. |
| **Dashboard** | Main UI: ticker search, lookback selector (presets + custom days), period (month/quarter), Refresh button, KPI cards, tabbed content. |
| **HoldingsChart** | Holdings over time for top 15 insiders; per-insider activity (uses insider activity API). |
| **ActivityCharts** | Charts for monthly/quarterly aggregates (shares and value bought/sold). |
| **PctSoldTab** | Per-insider “% sold” and related metrics (table). |
| **TransactionsTable** | Paginated, sortable transactions table; optional insider filter; “View XML” links to SEC readable filing URL. |
| **API client (lib/api.ts)** | All backend calls: resolve, sync, refresh, KPIs, top, holdings, aggregates, transactions, insider activity. |
| **React Query** | Caching and refetch for dashboard data; invalidation on lookback or ticker change. |

**Where it runs:**  
- **Local:** `npm run dev` → http://localhost:3000  
- **Docker:** `frontend` service → port 3000 (builds from `frontend/Dockerfile`).

### 3.2 Backend

| Component | Role |
|-----------|------|
| **main.py** | FastAPI app: CORS, routes, DB engine, table creation on startup. |
| **sec_client.py** | SEC EDGAR HTTP client: User-Agent, rate limiting, retries; resolve ticker→CIK, company submissions, filing index, fetch XML/text. |
| **parser.py** | Form 4: pick XML file from filing index, fetch and parse XML (non-derivative transactions), map to transaction dicts; convert fetch URL to readable SEC URL for storage/display. |
| **transforms.py** | Business logic: top 15 insiders by |value_usd|, holdings over time, monthly/quarterly aggregates, per-insider activity. |
| **models.py** | SQLModel entities: Company, Insider, Filing, Transaction. |

**Where it runs:**  
- **Local:** `uvicorn main:app --reload --host 0.0.0.0 --port 8000` (from `backend/`).  
- **Docker:** `backend` service → port 8000 (builds from `backend/Dockerfile`), depends on Postgres.

### 3.3 Database

- **Tables:** `companies`, `insiders`, `filings`, `transactions` (see §4).  
- **Creation:** Tables are created automatically on backend startup (`SQLModel.metadata.create_all(engine)`).  
- **Where it runs:**  
  - **Local dev:** SQLite file `backend/insider.db` (default) or PostgreSQL (e.g. `InsiderDB`).  
  - **Docker:** PostgreSQL 16 in `postgres` service; database name `InsiderDB`; backend connects via `DATABASE_URL`.

### 3.4 External dependency: SEC EDGAR

- **APIs used:**  
  - `https://www.sec.gov/files/company_tickers.json` — ticker → CIK + company name.  
  - `https://data.sec.gov/submissions/CIK{cik}.json` — company’s recent filings list.  
  - `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json` — filing index.  
  - `https://www.sec.gov/Archives/edgar/data/...` — Form 4 XML (fetched by URL from index).  
- **Data as of:** Whatever is currently published by the SEC at request time (no fixed “as of” date; sync pulls the latest filings that fall within the requested lookback window).  
- **Compliance:** All requests send a configurable `User-Agent` header; optional rate limiting and retries; SSL verification can be disabled only for trusted environments (e.g. corporate proxy).

---

## 4. Data Model and Data Pulled

### 4.1 Source of truth and “as of” date

- **Ticker list / company info:** From SEC `company_tickers.json` and company submissions (live at request time).  
- **Form 4 data:** From SEC EDGAR filings. Sync uses **filing date** (and optional lookback) to decide which filings to process; **transaction date** is stored per transaction.  
- **“As of” meaning:** Data reflects what the SEC had at the time of the last **sync** for that ticker. There is no continuous real-time feed; each Refresh re-runs sync for the selected lookback and adds any new filings since last sync.

### 4.2 Database tables (models.py)

| Table | Key fields | Purpose |
|-------|------------|---------|
| **companies** | ticker (PK), cik10, name, last_refresh | One row per synced company. |
| **insiders** | insider_cik (PK), name | One row per distinct insider (from Form 4). |
| **filings** | accession (PK), company_cik, filing_date, xml_url, is_amendment | One row per Form 4 filing. |
| **transactions** | id (PK), accession, company_cik, insider_cik, insider_name, transaction_date, acq_disp, shares, price, value_usd, shares_owned_following, xml_url, … | One row per non-derivative transaction; links to filing and insider. |

### 4.3 What is pulled from the SEC (sync)

- **Company submissions** → list of recent filings (form type, accession number, filing date).  
- **Form 4 filings only** (filtered by form type "4").  
- For each filing not already in DB: **index.json** → choose Form 4 XML file → **fetch XML** → **parse** non-derivative transactions (transaction date, shares, price, value, shares owned following, insider, officer/director, acquisition/disposition, etc.).  
- Stored **xml_url** is the SEC’s human-readable XML URL (xslF345X05 path) for display; fetch uses the standard URL.  
- Sync is **idempotent per accession:** already-seen filings are skipped.

---

## 5. API Summary

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/resolve?ticker=` | Resolve ticker to CIK and company name (SEC). |
| POST | `/api/sync` | Sync Form 4 data (body: ticker, lookback_days, max_forms). |
| GET | `/api/{ticker}/top?lookback_days=` | Top 15 insiders by abs(value_usd) over lookback. |
| GET | `/api/{ticker}/holdings?lookback_days=` | Holdings over time for top 15. |
| GET | `/api/{ticker}/aggregates?lookback_days=&period=month\|quarter` | Monthly or quarterly aggregates. |
| GET | `/api/{ticker}/transactions?lookback_days=&insider_cik=&limit=&offset=` | Paginated transactions. |
| GET | `/api/{ticker}/insider/{insider_cik}/activity?lookback_days=&period=` | Per-insider activity time series. |
| POST | `/api/{ticker}/refresh` | Alias for sync (same body options). |
| GET | `/api/{ticker}/kpis?lookback_days=` | KPI card data (totals, net shares, filings count, last refresh). |

All lookback endpoints filter by **transaction_date** within the last `lookback_days` days (from today).

---

## 6. What Is Required to Run

### 6.1 Backend

- **Runtime:** Python 3.x (e.g. 3.12).  
- **Dependencies:** See `backend/requirements.txt` (FastAPI, uvicorn, requests, pandas, SQLModel, psycopg2-binary, python-dotenv, etc.).  
- **Env (minimal):**  
  - `DATABASE_URL`: SQLite default `sqlite:///./insider.db` or PostgreSQL (e.g. `postgresql://user:pass@host:5432/InsiderDB`).  
  - Optional: `SEC_USER_AGENT`, `SEC_VERIFY_SSL` (see README).  
- **Network:** Outbound HTTPS to `sec.gov` (and to Postgres if using PostgreSQL).  
- **Start:** From `backend/`, run `uvicorn main:app --reload --host 0.0.0.0 --port 8000` (or equivalent).  
- **Database:** For PostgreSQL, the database (e.g. `InsiderDB`) must exist; tables are created on startup.

### 6.2 Frontend

- **Runtime:** Node.js (LTS).  
- **Dependencies:** See `frontend/package.json` (Next.js, React, TanStack Query, Recharts, Tailwind, etc.).  
- **Env:** `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) so the app can call the backend.  
- **Start:** From `frontend/`, run `npm run dev` (port 3000) or `npm run build && npm run start` for production.

### 6.3 Docker (all-in-one)

- **Requirement:** Docker and Docker Compose.  
- **Command:** From project root, `docker compose up --build`.  
- **Result:**  
  - **postgres:** PostgreSQL 16, DB `InsiderDB`, port 5432.  
  - **backend:** FastAPI on port 8000, connected to Postgres.  
  - **frontend:** Next.js on port 3000; `NEXT_PUBLIC_API_URL=http://localhost:8000` (browser talks to host’s 8000).

---

## 7. File / Repo Structure (reference)

```
Main Project/
├── backend/
│   ├── main.py          # FastAPI app, routes, DB engine
│   ├── models.py        # SQLModel tables
│   ├── parser.py       # Form 4 fetch + parse, readable URL
│   ├── sec_client.py   # SEC HTTP client
│   ├── transforms.py   # Top 15, holdings, aggregates
│   ├── requirements.txt
│   ├── .env            # DATABASE_URL, SEC_* (optional)
│   └── tests/
├── frontend/
│   ├── app/             # Next.js App Router (page, layout)
│   ├── components/      # Dashboard, charts, tables, UI
│   ├── lib/             # api.ts, utils
│   └── package.json
├── docker-compose.yml   # postgres, backend, frontend
├── README.md
└── docs/
    └── PRODUCT_SPEC.md  # This document
```

---

## 8. Default companies and auto-update

**Default companies:** Six companies are always available on the dashboard: **Amazon** (AMZN), **Roblox** (RBLX), **Carvana** (CVNA), **Meta** (META), **Coupang** (CPNG), and **ServiceTitan** (TTAN). The user chooses one to view its analyses and charts; they can also search for any other ticker.

**Auto-update:** The dashboard automatically refreshes Form 4 data for these six companies **every Sunday** (weekly job at 00:00 UTC). Their insider data stays current without manual refresh. Users can still refresh any ticker manually at any time.

---

## 9. Summary

- **What it is:** A dashboard that syncs SEC Form 4 insider trading data for a given ticker and shows KPIs, top insiders, holdings over time, activity, and transactions over a configurable lookback (presets or custom days).  
- **Data:** Comes from SEC EDGAR; stored in PostgreSQL or SQLite; “as of” = last sync for that ticker.  
- **Where it runs:** Frontend (Next.js) and backend (FastAPI) on localhost or in Docker; DB is local SQLite or Docker/remote Postgres.  
- **What you need:** Python + Node.js (or Docker), env for DB and optional SEC/API URL, and outbound access to the SEC and (if applicable) Postgres.
