# Deployment Guide: Insider Trading Dashboard on Render

This document describes how to deploy the Insider Trading Dashboard to **Render.com** so it runs on a public website, including database setup and SEC API configuration.

---

## 1. Overview

- **Backend**: FastAPI app (Python) → deploy as a **Web Service** on Render.
- **Frontend**: Next.js app → deploy as a **Web Service** on Render.
- **Database**: PostgreSQL → create a **PostgreSQL** instance on Render (required for production; do not use SQLite on a stateless server).
- **SEC API**: When requests come from your Render backend (not your laptop), you must set a proper **User-Agent** and respect SEC’s fair-access policy (your app already uses rate limiting).

---

## 2. Database Setup on Render

### 2.1 Create a PostgreSQL instance

1. Log in to [Render](https://render.com) and open the **Dashboard**.
2. Click **New +** → **PostgreSQL**.
3. Choose a name (e.g. `insider-dashboard-db`), region, and plan (Free tier is fine for testing).
4. Click **Create Database**.
5. Wait until the instance is **Available**.

### 2.2 Get the connection URL

1. Open your PostgreSQL service.
2. In **Connections**, copy the **Internal Database URL** (use this for the backend Web Service on Render so traffic stays on Render’s network).
   - Format: `postgresql://user:password@hostname/database?options`
3. Optionally note the **External Database URL** if you need to connect from your machine (e.g. for migrations or debugging).

### 2.3 Create the database (if needed)

Render’s PostgreSQL usually gives you **one database per instance**; the URL already includes the database name. You do **not** need to run `CREATE DATABASE` unless you use a template that has no default database.

- If your URL has no database name or you want a specific name (e.g. `InsiderDB`), connect with `psql` or a GUI and run:
  ```sql
  CREATE DATABASE "InsiderDB";
  ```
- Then use a connection URL that ends with `/InsiderDB` (or whatever name you chose).

### 2.4 Tables

The backend creates all tables automatically on startup (`SQLModel.metadata.create_all(engine)`). No manual table creation is required. Tables created from `models.py`:

- `companies`
- `insiders`
- `filings`
- `transactions`

---

## 3. SEC API Configuration (Required for Web Deployment)

When the app runs on Render, **all SEC requests come from Render’s servers**, not your laptop. The SEC requires a proper **User-Agent** and enforces rate limits.

### 3.1 User-Agent (required)

- **Requirement**: SEC expects a User-Agent that identifies your application and contact (e.g. name/email or company).
- **Current behavior**: The app reads `SEC_USER_AGENT` from the environment; if unset, it uses a default string.
- **What to do**: In the **backend** Web Service on Render, set the environment variable:
  ```bash
  SEC_USER_AGENT=YourCompany/InsiderDashboard/1.0 (your-email@yourcompany.com)
  ```
  Replace with your real app name and contact. Example:
  ```bash
  SEC_USER_AGENT=Bain/InsiderDashboard/1.0 (contact@bain.com)
  ```

### 3.2 Rate limiting

- The backend already uses a short delay (e.g. 0.15 s) between SEC requests and retries with backoff.
- SEC’s guideline is roughly **no more than 10 requests per second** per User-Agent. Your current logic is conservative; no code change needed if you keep it.

### 3.3 SSL (optional)

- If you see SSL/certificate errors when calling the SEC from Render (e.g. due to network/proxy), you can set:
  ```bash
  SEC_VERIFY_SSL=0
  ```
  Use only if necessary; turning off verification is less secure.

---

## 4. Deploy the Backend (FastAPI) on Render

### 4.1 New Web Service

1. **Dashboard** → **New +** → **Web Service**.
2. Connect your **Git** repository (GitHub/GitLab/Bitbucket) and select the repo that contains this project.
3. Configure:
   - **Name**: e.g. `insider-dashboard-api`
   - **Region**: Same as the database (recommended).
   - **Branch**: e.g. `main`.

### 4.2 Build & start

- **Runtime**: **Python 3**.
- **Root Directory**: `backend`  
  (so Render runs commands from the folder that has `main.py` and `requirements.txt`).
- **Build Command**:
  ```bash
  pip install -r requirements.txt
  ```
- **Start Command**:
  ```bash
  uvicorn main:app --host 0.0.0.0 --port $PORT
  ```
  Render sets `$PORT` (often 10000). Binding to `0.0.0.0` is required for external traffic.

### 4.3 Environment variables (backend)

In the Web Service → **Environment** tab, add:

| Key               | Value / notes                                                                 |
|-------------------|-------------------------------------------------------------------------------|
| `DATABASE_URL`    | The **Internal Database URL** from your Render PostgreSQL instance.           |
| `SEC_USER_AGENT`  | Your app name and contact, e.g. `Company/InsiderDashboard/1.0 (email@domain.com)`. |
| `SEC_VERIFY_SSL`  | Optional. Set to `0` only if you get SSL errors calling the SEC.              |

Do **not** commit real URLs or secrets to Git; use only Render’s environment (or Render’s “Secret Files” if you prefer).

### 4.4 Deploy

1. Click **Create Web Service**.
2. Wait for the first deploy to finish.
3. Note the service URL, e.g. `https://insider-dashboard-api.onrender.com`. This is your **backend (API) base URL**.

---

## 5. Deploy the Frontend (Next.js) on Render

### 5.1 New Web Service

1. **Dashboard** → **New +** → **Web Service**.
2. Connect the **same** repository.
3. Configure:
   - **Name**: e.g. `insider-dashboard`
   - **Region**: Any (or same as backend).
   - **Branch**: e.g. `main`.

### 5.2 Build & start

- **Runtime**: **Node**.
- **Root Directory**: `frontend`.
- **Build Command**:
  ```bash
  npm install && npm run build
  ```
- **Start Command**:
  ```bash
  npm run start
  ```

### 5.3 Environment variables (frontend)

The frontend calls the backend using `NEXT_PUBLIC_API_URL`. Set it to your **backend** Web Service URL:

| Key                     | Value                                                                 |
|-------------------------|-----------------------------------------------------------------------|
| `NEXT_PUBLIC_API_URL`   | Backend URL, e.g. `https://insider-dashboard-api.onrender.com`        |

Do **not** add a trailing slash. Use **https** so the browser can call the API from your deployed site.

### 5.4 Deploy

1. Click **Create Web Service**.
2. After the first deploy, the app will be available at e.g. `https://insider-dashboard.onrender.com`.

---

## 6. Post-Deploy Checklist

1. **Database**: Backend starts and creates tables automatically; no manual DB steps if `DATABASE_URL` is set.
2. **API health**: Open `https://<your-backend>.onrender.com/docs` and confirm Swagger UI loads.
3. **Frontend**: Open `https://<your-frontend>.onrender.com`, enter a ticker, and click **Search** then **Refresh** to trigger sync. If the API URL is correct, data should load.
4. **SEC**: If you get 403 or “Unauthorized” from the SEC, double-check `SEC_USER_AGENT` on the backend and that it clearly identifies your app and contact.

---

## 7. Optional: Backfill and defaults

- **10b5-1 backfill**: After the first syncs, you can run the backfill from the UI (**Backfill 10b5-1** button) or by calling `POST https://<your-backend>.onrender.com/api/backfill-10b5-1?max_filings=200` once. This fills `is_10b5_1` for existing transactions.
- **Default companies**: The app uses a default list of tickers; you can change `DEFAULT_TICKERS` / `DEFAULT_COMPANY_LABELS` in the backend config and redeploy if you want different defaults.

---

## 8. Summary of What You Need on Render

| Item           | What to create / set                                                                 |
|----------------|--------------------------------------------------------------------------------------|
| **Database**   | One PostgreSQL instance; copy **Internal Database URL** into backend `DATABASE_URL`. |
| **Backend**    | One Web Service (Python), root `backend`, uvicorn start command, `DATABASE_URL` + `SEC_USER_AGENT`. |
| **Frontend**   | One Web Service (Node), root `frontend`, `npm run build` / `npm run start`, `NEXT_PUBLIC_API_URL` = backend URL. |
| **SEC**        | Set `SEC_USER_AGENT` on the backend to a proper app/contact string for web/server use. |

No code changes are required if you set the environment variables above; the app is already built to read `DATABASE_URL`, `SEC_USER_AGENT`, `SEC_VERIFY_SSL`, and the frontend to use `NEXT_PUBLIC_API_URL`.

---

## 9. Troubleshooting: "Exited with status 1" on deploy

If the backend build succeeds but the **Deploy** step fails with **Exited with status 1**, the start command or app startup is failing. Check the **Logs** tab for the backend Web Service on Render to see the real Python traceback. Common causes and fixes:

### 9.1 Root Directory not set

- **Symptom**: Logs show `ModuleNotFoundError: No module named 'main'` or similar.
- **Fix**: In the backend Web Service → **Settings** → **Build & Deploy**, set **Root Directory** to `backend` (no leading slash). Save and redeploy.

### 9.2 DATABASE_URL missing or wrong

- **Symptom**: Logs show errors about database connection, `create_engine`, or SQLAlchemy when the app starts.
- **Fix**:
  1. In the backend Web Service → **Environment**, add **DATABASE_URL** and paste the **Internal Database URL** from your Render PostgreSQL service (Connections section). The backend must have this set in production.
  2. If the URL starts with `postgres://`, change it to **postgresql://** (e.g. `postgresql://user:pass@host/dbname`) before pasting. SQLModel/SQLAlchemy expect the `postgresql://` scheme.

### 9.3 PORT not set or start command

- **Symptom**: Logs show uvicorn failing on port or "address already in use".
- **Fix**: Render sets `PORT` automatically. If you see the literal `$PORT` in logs or a port error, try this **Start Command** instead (explicit fallback):
  ```bash
  uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}
  ```
  Or ensure the **Start Command** is exactly:
  ```bash
  uvicorn main:app --host 0.0.0.0 --port $PORT
  ```
  with no extra quotes or spaces.

### 9.4 Pydantic: "Field 'ticker' requires a type annotation"

- **Symptom**: Logs show `PydanticUserError: Field 'ticker' requires a type annotation` when loading `models.py` (or similar field names). This can happen when Render uses **Python 3.14**, which enforces stricter annotation handling with Pydantic/SQLModel.
- **Fix**: The repo pins the backend to **Python 3.12** via `backend/runtime.txt` (e.g. `python-3.12.7`). Ensure that file exists and that the backend service’s **Root Directory** is `backend` so Render uses it. Then redeploy. If the error persists, check that every field in `backend/models.py` has an explicit type (e.g. `ticker: str`, `name: str`).

### 9.5 Viewing the actual error

1. Open your **backend** Web Service on Render.
2. Go to the **Logs** tab.
3. Select the latest deploy and scroll to the end of the **Deploy** phase (after "Running 'uvicorn ...'").
4. The line before "Exited with status 1" is usually the Python exception (e.g. `ImportError`, `OperationalError`, or missing env var). Use that message to apply the right fix above.
