# Insider Dashboard

A web application for analyzing SEC Form 4 insider trading data for US public companies. Search any ticker, sync filings directly from the SEC, and explore insider buying/selling activity through interactive charts and tables.

---

## Table of Contents

1. [Features](#features)
2. [How It Works](#how-it-works)
3. [Dashboard Walkthrough](#dashboard-walkthrough)
4. [Quick Start](#quick-start)
5. [Tech Stack](#tech-stack)
6. [Project Structure](#project-structure)
7. [Environment Variables](#environment-variables)
8. [API Endpoints](#api-endpoints)
9. [Data Model](#data-model)
10. [Testing](#testing)
11. [Deployment](#deployment)

---

## Features

- **Ticker search**: Enter any US public company ticker to load its insider trading data from SEC EDGAR.
- **Configurable lookback**: Preset ranges (30d, 60d, 90d, 180d, 1y, 3y) or a custom value in days, months, or years. All metrics and charts respect the selected period.
- **KPI summary cards**: Total $ sold, total $ bought, shares bought, net shares, filing count, and last refresh timestamp.
- **Insider summary table**: Top 15 insiders ranked by shareholding, with columns for name, title, BoP/EoP shares, buys, sales (total/core/non-core), cost basis, % of BoP sold, and net buyer/seller classification.
- **Core vs. Non-Core classification**: Transactions are classified as Core (open-market buys/sales with no special flags) or Non-Core (10b5-1 plan sales, RSU vests, tax withholdings, gifts, margin calls).
- **Drill-down modal**: Click any insider row to see:
  - **Sales Over Time chart**: Stacked monthly bars (core vs. non-core sales in $), with a secondary axis for % holdings sold per month and an optional stock price overlay via Yahoo Finance.
  - **Waterfall chart**: Visual bridge from Beginning of Period (BoP) shares through Core Buys, Non-Core Buys, Core Sales, Non-Core Sales, and Other/Adj. to End of Period (EoP) shares.
- **Cluster detection**: Alerts when 3+ distinct insiders sell in the same month, listing their names.
- **Shareholding change tab**: Monthly/quarterly aggregates showing shares and dollar values bought/sold per insider, with 10b5-1 plan adoption dates.
- **Transactions tab**: Paginated, sortable table of every transaction with filters by transaction type. Each row links to the SEC filing XML.
- **Toggles**: ">10% Owners Only" and "Core Sales Only" filters on the summary table.
- **CSV/Excel export**: Download the insider summary table data.
- **Transaction type filter**: Filter the dashboard by specific transaction types (open market sale, open market purchase, RSU vest, tax withholding, gift, 10b5-1).
- **Auto-sync**: Default tickers (AMZN, RBLX, CVNA, META, CPNG, TTAN) are synced automatically every Sunday. Any ticker can also be refreshed manually.
- **Direct + indirect ownership**: Aggregates shares held directly and through trusts/LLCs/entities for accurate position tracking.

---

## How It Works

```
User (browser)
    -> Frontend (Next.js, port 3000)
        -> Backend API (FastAPI, port 8000)
            -> Database (PostgreSQL or SQLite)
            -> SEC EDGAR (HTTPS APIs) -- only for resolve + sync
            -> Yahoo Finance (HTTPS) -- stock price overlay
```

1. **Search**: User enters a ticker. The backend resolves it to a company CIK via SEC EDGAR.
2. **Sync**: User clicks Refresh. The backend fetches the company's Form 4 filings from the SEC, parses each filing's XML, classifies transactions, and stores everything in the database. Filings are cached by accession number so they are never re-downloaded.
3. **View**: The dashboard reads from the local database. The SEC is only called during resolve and sync. All charts, tables, and metrics are computed from stored transaction data filtered by the selected lookback period.

### Data sources

All data comes from public APIs -- no HTML scraping.

| Source | What | When called |
|--------|------|-------------|
| SEC EDGAR `company_tickers.json` | Ticker to CIK resolution | On search |
| SEC EDGAR `submissions/CIK{cik}.json` | Company's recent filings list | On sync |
| SEC EDGAR `Archives/edgar/data/...` | Form 4 XML filings | On sync (per filing) |
| Yahoo Finance chart API | Monthly stock prices | When drill-down modal opens |

### Transaction classification

Each transaction is automatically classified using transaction codes, footnotes, and filing metadata:

| Classification | How detected |
|---------------|-------------|
| **10b5-1 plan** | Form-level `aff10b5One` indicator + footnote keywords; applied to dispositions only |
| **RSU vest** | Derivative table: `transactionCode=M` + `exercisePrice=0` + security title contains "Restricted"; or non-derivative with `code=M` and `price=$0` |
| **Tax withholding** | `transactionCode=F` or footnote keywords ("tax", "withholding") |
| **Gift** | `transactionCode=G` or footnote keywords ("gift", "bona fide") |
| **Margin call** | Explicit footnote phrases ("margin call", "collateral") |
| **Core** | Open-market transactions with none of the above flags |

---

## Dashboard Walkthrough

### 1. Search and refresh

At the top of the page, enter a ticker (e.g. `AMZN`) and click **Search**. The app resolves the ticker and loads cached data. Click **Refresh** to pull the latest Form 4 filings from the SEC.

### 2. Lookback period

Use the dropdown to select a time range: 30d, 60d, 90d, 180d, 1y, 3y, or Custom. For custom, enter a number and choose the unit (Days, Months, Years). All metrics, charts, and tables update to reflect this period.

### 3. KPI cards

Six summary cards across the top: Total $ Sold, Total $ Bought, Shares Bought, Net Shares, # Filings, and Last Refresh.

### 4. Holdings tab (default)

Contains the **Insider Summary Table** -- a sortable table of the top 15 insiders with:

| Column | Meaning |
|--------|---------|
| Name / Title | Insider name and officer title |
| BoP Shares | Shares held at the beginning of the lookback period |
| EoP Shares | Shares held at the end of the lookback period (most recent transaction) |
| % EoP (of Top 15) | This insider's EoP shares as a percentage of all top-15 insiders' total EoP |
| Net Buyer/Seller | Based on core buys vs. core sales in $ |
| Buys ($) / Buys (#) | Total acquisition value and share count |
| Avg Cost Basis (Buys) | Average price per share for purchases |
| Purchases as % of BoP | Shares bought / BoP shares |
| Sales Total ($) | Total disposition value |
| Sales Core ($) / Core (#) | Open-market sales with no special flags |
| Avg Cost Core Sales ($) | Average price for core sales |
| Sales as % of BoP | Total shares sold / BoP shares |
| Non-Core ($) | 10b5-1, RSU, tax, gift, and margin call sales |
| Non-Core % of Total | Non-core sales $ / total sales $ |

**Toggles** above the table:
- **>10% Owners Only**: Filter to insiders who are 10%+ beneficial owners.
- **Core Sales Only**: Show only core (open-market) transactions in the summary.

**Cluster detection**: If 3+ insiders sold in the same month, a banner appears listing the month and seller names.

**Export**: Click the export button to download the table as CSV.

### 5. Insider drill-down modal

Click any row in the summary table to open a detail modal with two charts:

**Sales Over Time** (stacked bar + line chart):
- Left Y-axis: Monthly sales in $ (stacked bars for Core and Non-Core).
- Right Y-axis: % Holdings Sold per month (line).
- Stock price overlay (line) showing monthly close prices for months with sales activity.

**Waterfall chart** (custom SVG):
- Visual bridge: BoP Shares + Core Buys + Non-Core Buys - Core Sales - Non-Core Sales +/- Other/Adj. = EoP Shares.
- Floating bars with connector lines; hover for tooltips.

### 6. Shareholding Change tab

Monthly or quarterly aggregates per insider showing shares bought, shares sold, dollar values, and shares owned following. Includes 10b5-1 plan adoption dates when available.

### 7. Transactions tab

Paginated table of every individual transaction within the lookback period. Columns include date, insider name, transaction code, shares, price, value, shares after, and flags (10b5-1, RSU, gift, etc.). Each row has a link to view the original SEC filing XML.

Filter by transaction type using the dropdown above the table.

---

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API docs (Swagger)**: http://localhost:8000/docs

### Local development (without Docker)

**Backend:**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Uses SQLite by default (no database setup needed). A file `backend/insider.db` is created automatically.

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local` if needed.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, shadcn/ui |
| Charts | Recharts (Sales Over Time), Custom SVG (Waterfall) |
| Tables | TanStack Table (React Table) |
| Data fetching | TanStack Query (React Query) |
| Backend | FastAPI, Python 3.12, SQLModel (SQLAlchemy + Pydantic) |
| Data processing | pandas |
| HTTP clients | `requests` (SEC EDGAR), `httpx` (Yahoo Finance) |
| Database | PostgreSQL 16 (production) or SQLite (local dev) |
| Scheduling | APScheduler (weekly auto-sync) |

---

## Project Structure

```
Main Project/
├── backend/
│   ├── main.py                  # FastAPI app, routes, DB engine, migrations
│   ├── models.py                # SQLModel tables (Company, Insider, Filing, Transaction)
│   ├── parser.py                # Form 4 XML parsing, Table I/II handling, ownership aggregation
│   ├── sec_client.py            # SEC EDGAR HTTP client (rate limiting, retries)
│   ├── transforms.py            # Business logic (top 15, BoP/EoP, aggregates, insider summary)
│   ├── transaction_classifier.py # Transaction classification (10b5-1, RSU, gift, tax, margin)
│   ├── config.py                # Default tickers and labels
│   ├── requirements.txt         # Python dependencies
│   ├── runtime.txt              # Python version pin (3.12)
│   ├── Dockerfile
│   └── tests/
├── frontend/
│   ├── app/                     # Next.js App Router (page, layout)
│   ├── components/
│   │   ├── dashboard.tsx        # Main dashboard (search, KPIs, tabs, filters)
│   │   └── dashboard/
│   │       ├── insider-summary-table.tsx   # Top 15 insiders table
│   │       ├── insider-detail-modal.tsx    # Drill-down modal (charts)
│   │       ├── holdings-chart.tsx          # Holdings over time
│   │       ├── activity-charts.tsx         # Monthly/quarterly activity
│   │       ├── pct-sold-tab.tsx            # Shareholding change tab
│   │       └── transactions-table.tsx      # Transactions table
│   ├── lib/
│   │   └── api.ts               # API client, types, fetch functions
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml           # PostgreSQL + backend + frontend
├── .env.example                 # Documented environment variables
├── DEPLOYMENT.md                # Full deployment guide
└── README.md                    # This file
```

---

## Environment Variables

Copy `.env.example` to `backend/.env` for local development.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes (prod) | `sqlite:///./insider.db` | Database connection string. Use `postgresql://user:pass@host:5432/dbname` for production. |
| `SEC_USER_AGENT` | Yes | `InsiderDashboard/1.0 (...)` | User-Agent for SEC EDGAR requests. Must identify your app and include a contact email. |
| `SEC_VERIFY_SSL` | No | `1` (enabled) | Set to `0` to disable SSL verification (corporate proxy). See [DEPLOYMENT.md](DEPLOYMENT.md). |
| `CORS_ORIGINS` | No | `*` | Comma-separated allowed frontend origins. Set to your frontend URL in production. |
| `NEXT_PUBLIC_API_URL` | Yes (prod) | `http://localhost:8000` | Backend API URL for the frontend (baked in at build time). |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/resolve?ticker=AAPL` | Resolve ticker to CIK and company name |
| POST | `/api/sync` | Sync Form 4 data (body: `{ticker, lookback_days, max_forms}`) |
| POST | `/api/{ticker}/refresh` | Alias for sync |
| GET | `/api/{ticker}/kpis?lookback_days=` | KPI summary (totals, net shares, filings count) |
| GET | `/api/{ticker}/top?lookback_days=` | Top 15 insiders by shares held |
| GET | `/api/{ticker}/holdings?lookback_days=` | Holdings over time for top 15 |
| GET | `/api/{ticker}/aggregates?lookback_days=&period=month|quarter` | Monthly/quarterly aggregates |
| GET | `/api/{ticker}/insider-summary?lookback_days=` | Insider summary table data (BoP, EoP, buys, sales, classification) |
| GET | `/api/{ticker}/insider/{cik}/activity?lookback_days=&period=` | Per-insider activity time series |
| GET | `/api/{ticker}/transactions?lookback_days=&insider_cik=&limit=&offset=` | Paginated transactions |
| GET | `/api/{ticker}/stock-prices?lookback_days=` | Monthly stock prices (Yahoo Finance) |

All lookback endpoints filter by transaction date within the last `lookback_days` days from today. Interactive API documentation is available at `/docs` (Swagger UI).

---

## Data Model

### Database tables

| Table | Key Fields | Purpose |
|-------|-----------|---------|
| `companies` | ticker (PK), cik10, name, last_refresh | One row per synced company |
| `insiders` | insider_cik (PK), name | One row per distinct insider |
| `filings` | accession (PK), company_cik, filing_date, xml_url | One row per Form 4 filing |
| `transactions` | id (PK), accession, company_cik, insider_cik, transaction_date, shares, price, value_usd, shares_owned_following, ownership_type, is_10b5_1, is_rsu_vest_related, is_derivative, ... | One row per parsed transaction |

Tables are created automatically on backend startup. New columns are added via inline migrations (no Alembic required).

### How positions are tracked

- **Direct + indirect ownership**: Each Form 4 filing reports shares held per ownership bucket (direct, each trust/LLC). The parser aggregates all buckets into a single `shares_owned_following` total per filing.
- **BoP (Beginning of Period)**: Derived from the first non-derivative transaction in the lookback window by reversing the transaction's effect on `shares_owned_following`.
- **EoP (End of Period)**: The `shares_owned_following` from the last non-derivative transaction in the lookback window.
- **Derivative exclusion**: Table II (derivative) transactions are used for classification metadata (RSU detection, security titles) but their positions are excluded from share counts to avoid double-counting.

---

## Testing

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

---

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete deployment instructions covering:

- Database setup (PostgreSQL)
- Backend and frontend deployment (local, Docker, cloud)
- Docker Compose all-in-one setup
- Corporate network / SSL configuration
- Production hardening (CORS, HTTPS, secrets)
- Cloud deployment guides for AWS, Azure, and GCP
- Troubleshooting

### SEC compliance

- All SEC requests include a configurable `User-Agent` header identifying the app and a contact email.
- Rate limiting uses delays between requests and retries with exponential backoff.
- SSL verification is enabled by default; can be configured for corporate proxy environments.
