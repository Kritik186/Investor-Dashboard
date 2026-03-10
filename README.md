# Fancy Insider Trading Dashboard

A web app to view SEC Form 4 insider trading data: resolve tickers, sync filings, and explore top insiders, holdings over time, activity, and transactions.

## Data source (APIs, not scraping)

All market data comes from **SEC EDGAR over HTTP APIs**—no HTML scraping.

- **`backend/sec_client.py`**: HTTP client with rate limiting and retries.
  - `get_json(url)` / `get_text(url)`: fetch JSON or text (XML) from SEC.
  - `resolve_ticker_to_cik(ticker)`: uses `https://www.sec.gov/files/company_tickers.json`.
  - `get_company_submissions(cik10)`: uses `https://data.sec.gov/submissions/CIK{cik}.json`.
  - `get_filing_index_json()` / `get_filing_xml()`: fetch filing index and Form 4 XML from `https://www.sec.gov/Archives/edgar/...`.
- **`backend/parser.py`**: uses `sec_client` to get filing index and XML, then parses Form 4 XML with Python’s `xml.etree.ElementTree`.
- **`backend/main.py`**: calls `resolve_ticker_to_cik`, `get_company_submissions`, and `fetch_and_parse_form4` (from parser) during sync/refresh.

## Stack

- **Frontend**: Next.js (App Router), TypeScript, Tailwind, shadcn/ui, Recharts, TanStack Table, TanStack Query
- **Backend**: FastAPI, requests, pandas, SQLModel, Postgres (Docker) / SQLite (dev)

## Quick Start

```bash
# Clone or cd into project, then:
docker compose up --build
```

- **Frontend**: http://localhost:3000  
- **Backend API**: http://localhost:8000  
- **API docs**: http://localhost:8000/docs  

## Database (no manual setup for SQLite)

**You do not need to create the database yourself.** The backend creates it automatically.

### How it works

1. When you start the backend (`uvicorn main:app ...`), the app loads `main.py`.
2. It reads `DATABASE_URL` from the environment (default: `sqlite:///./insider.db`).
3. It creates a SQLite **file** at `backend/insider.db` if it doesn’t exist (relative to where you run the command).
4. It runs **`SQLModel.metadata.create_all(engine)`**, which creates all tables defined in `models.py`:
   - `companies` (ticker, cik10, name, last_refresh)
   - `insiders` (insider_cik, name)
   - `filings` (accession, company_cik, filing_date, xml_url, is_amendment)
   - `transactions` (id, accession, company_cik, insider_cik, …)

### Steps (local dev with SQLite)

1. **Go to the backend folder**
   ```bash
   cd backend
   ```
2. **Create and activate a virtual environment** (optional but recommended)
   ```bash
   python -m venv .venv
   .venv\Scripts\activate    # Windows
   ```
3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
4. **Start the backend** (no `.env` or `DATABASE_URL` needed for SQLite)
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
5. On first run, **`insider.db`** is created in the `backend` folder and all tables are created. After that, use the dashboard **Refresh** (or `POST /api/sync`) to load data for a ticker.

### Using Postgres instead

1. **Create the database** (Postgres does not create it automatically). From `psql` or any PostgreSQL client:
   ```sql
   CREATE DATABASE "InsiderDB";
   ```
2. Set `DATABASE_URL` to use **InsiderDB** (e.g. in `backend/.env`):
   ```bash
   DATABASE_URL=postgresql://postgres:kritik@localhost:5432/InsiderDB
   ```
3. Start the backend from the `backend` folder. All tables (`companies`, `insiders`, `filings`, `transactions`) are created automatically on startup.

### Viewing the database in DBeaver

1. **Create the database first** (if you haven’t). In DBeaver, connect to your PostgreSQL server using the default `postgres` database (Host: `localhost`, Port: `5432`, User: `postgres`, Password: `kritik`). Then run:
   ```sql
   CREATE DATABASE "InsiderDB";
   ```
   If you get “already exists”, the database is there. Close and reopen the connection or refresh the server node.

2. **Connect to InsiderDB**, not `postgres`. Create a **new connection** (or edit the existing one):
   - **Host:** `localhost`
   - **Port:** `5432`
   - **Database:** `InsiderDB` (must match exactly; try `insiderdb` in lowercase if you created the DB without quotes)
   - **Username:** `postgres`
   - **Password:** `kritik`
   Then **Test connection** and **Finish**.

3. **Expand the connection:** `InsiderDB` → **Schemas** → **public** → **Tables**. You should see `companies`, `insiders`, `filings`, `transactions`. If not, start the backend once so it can create the tables.

4. **Data appears after sync.** Tables are created empty. Use the app’s **Refresh** for a ticker (or `POST /api/sync`) to load Form 4 data; then refresh the tables in DBeaver to see rows.

---

## Environment Variables

| Variable | Description | Default (dev) |
|----------|-------------|----------------|
| `DATABASE_URL` | DB connection string | `sqlite:///./insider.db` |
| `SEC_USER_AGENT` | User-Agent for SEC requests | `InsiderDashboard/1.0 (kritik.ajmani@bain.com)` |
| `SEC_VERIFY_SSL` | Set to `0` or `false` to disable SSL verification for SEC requests (e.g. corporate proxy with custom CA). Use only in trusted environments. | `1` (verify enabled) |
| `NEXT_PUBLIC_API_URL` | Backend base URL for frontend | `http://localhost:8000` |

For Docker, backend uses Postgres; override `DATABASE_URL` in `docker-compose.yml` if needed.

### SSL certificate errors

If you see `[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate` when the backend calls the SEC (e.g. on sync or resolve), your network is likely using a corporate proxy or custom CA that Python’s trust store doesn’t include. Options:

1. **Quick workaround (dev only)**: In the backend folder, set `SEC_VERIFY_SSL=0` in your environment or a `.env` file, then restart the server. This disables SSL verification for SEC requests only and is less secure—use only in a trusted environment.
2. **Proper fix**: Install your organization’s root CA and point Python at it (e.g. set `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE` to a PEM file that includes your corporate CA).

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
# Uses SQLite if DATABASE_URL not set
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local` if needed.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/resolve?ticker=AAPL` | Resolve ticker to CIK and company name |
| POST | `/api/sync` | Sync Form 4 data (body: ticker, lookback_days, max_forms) |
| GET | `/api/{ticker}/top?lookback_days=` | Top 15 insiders by abs(value_usd) |
| GET | `/api/{ticker}/holdings?lookback_days=` | Holdings over time for top 15 |
| GET | `/api/{ticker}/aggregates?lookback_days=&period=month\|quarter` | Monthly/quarterly aggregates |
| GET | `/api/{ticker}/transactions?lookback_days=&insider_cik=&limit=&offset=` | Paginated transactions |
| POST | `/api/{ticker}/refresh` | Alias for sync |

## Testing

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v
```

## SEC Compliance

- All SEC requests send the configured `User-Agent` header.
- Rate limiting uses small delays and retries with backoff; the `Host` header is not overridden.
