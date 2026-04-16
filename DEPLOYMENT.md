# Deployment Guide

Complete instructions for deploying the Insider Dashboard in any environment: local development, Docker, or cloud (AWS, Azure, GCP).

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Environment Variables](#3-environment-variables)
4. [Database Setup (PostgreSQL)](#4-database-setup-postgresql)
5. [Backend Deployment (FastAPI)](#5-backend-deployment-fastapi)
6. [Frontend Deployment (Next.js)](#6-frontend-deployment-nextjs)
7. [Docker Compose (All-in-One)](#7-docker-compose-all-in-one)
8. [Corporate Network / SSL Configuration](#8-corporate-network--ssl-configuration)
9. [Production Hardening](#9-production-hardening)
10. [Cloud Deployment (AWS / Azure / GCP)](#10-cloud-deployment-aws--azure--gcp)
11. [Post-Deploy Checklist](#11-post-deploy-checklist)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────┐       ┌──────────────┐       ┌────────────┐
│  Next.js    │──API──▶│  FastAPI     │──SQL──▶│ PostgreSQL │
│  Frontend   │       │  Backend     │       │  Database   │
│  :3000      │       │  :8000       │       │  :5432      │
└─────────────┘       └──────┬───────┘       └────────────┘
                             │
                     ┌───────▼───────┐
                     │  SEC EDGAR    │
                     │  (HTTPS APIs) │
                     └───────────────┘
```

| Component  | Technology | Default Port |
|------------|-----------|-------------|
| Frontend   | Next.js 14, React 18, TypeScript, Tailwind CSS | 3000 |
| Backend    | FastAPI, Python 3.12, SQLModel, pandas | 8000 |
| Database   | PostgreSQL 16 (production) or SQLite (local dev) | 5432 |

---

## 2. Prerequisites

| Tool | Minimum Version | Notes |
|------|----------------|-------|
| Python | 3.12+ | Backend runtime |
| Node.js | 20+ | Frontend runtime |
| PostgreSQL | 14+ | Production database (SQLite works for local dev) |
| Docker & Docker Compose | Latest | Optional, for containerized deployment |
| Git | Any | To clone the repository |

---

## 3. Environment Variables

All configuration is done via environment variables. Copy `.env.example` to `backend/.env` for local development.

### Backend

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes (prod) | `sqlite:///./insider.db` | Database connection string. Use `postgresql://user:password@host:5432/dbname` for production. |
| `SEC_USER_AGENT` | Yes | `InsiderDashboard/1.0 (...)` | User-Agent header for SEC EDGAR requests. SEC requires this to identify your app and include a contact email. |
| `SEC_VERIFY_SSL` | No | `1` (enabled) | Set to `0` to disable SSL certificate verification for SEC and Yahoo Finance requests. Only use in trusted environments behind corporate proxies. See [Section 8](#8-corporate-network--ssl-configuration). |
| `CORS_ORIGINS` | No | `*` (any origin) | Comma-separated list of allowed frontend origins. In production, set to your frontend URL (e.g. `https://dashboard.example.com`). |

### Frontend

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | Yes (prod) | `http://localhost:8000` | Backend API base URL (no trailing slash). Must be the URL the **browser** uses to reach the backend. |

### Setting Environment Variables

- **Local dev**: Create `backend/.env` with your values. The backend loads it automatically via `python-dotenv`.
- **Docker**: Set in `docker-compose.yml` under each service's `environment` block.
- **Cloud (AWS, Azure, GCP)**: Set in the platform's environment variable / secrets settings for each service.

---

## 4. Database Setup (PostgreSQL)

### 4.1 Create the database

The backend creates **tables** automatically on startup, but the PostgreSQL **database itself** must exist first.

```sql
-- Connect to PostgreSQL as a superuser or admin, then:
CREATE DATABASE "InsiderDB";
```

### 4.2 Connection string format

```
postgresql://USERNAME:PASSWORD@HOST:PORT/DATABASE
```

Example:
```
postgresql://insider:strongpassword@localhost:5432/InsiderDB
```

> If you get a URL starting with `postgres://` (e.g. from some managed database providers), change it to `postgresql://`. SQLAlchemy requires the full `postgresql://` scheme.

### 4.3 Tables (auto-created)

On first startup, the backend runs `SQLModel.metadata.create_all(engine)` which creates:

| Table | Purpose |
|-------|---------|
| `companies` | Ticker, CIK, company name, last refresh timestamp |
| `insiders` | Insider CIK and name |
| `filings` | Filing accessions, dates, XML URLs |
| `transactions` | All parsed Form 4 transaction data |

New columns are added automatically via inline migrations (no Alembic required).

### 4.4 Using SQLite (local dev only)

For quick local development, no database setup is needed. If `DATABASE_URL` is not set, the backend creates a SQLite file at `backend/insider.db` automatically. SQLite is **not recommended for production** -- it does not support concurrent writes and data is lost on stateless hosting platforms.

---

## 5. Backend Deployment (FastAPI)

### 5.1 Local development

```bash
cd backend
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# Create .env with your DATABASE_URL (or skip for SQLite)
# Then start the server:
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Verify: open http://localhost:8000/docs to see Swagger UI.

### 5.2 Production

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

- Do **not** use `--reload` in production.
- For higher throughput, add `--workers 2` (or more, based on available CPU cores).
- Bind to `0.0.0.0` so the service is accessible from outside the container/VM.

### 5.3 Docker

The backend includes a `Dockerfile`:

```bash
cd backend
docker build -t insider-backend .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:password@host:5432/InsiderDB \
  -e SEC_USER_AGENT="YourCompany/InsiderDashboard/1.0 (email@example.com)" \
  insider-backend
```

### 5.4 Background jobs

The backend starts an APScheduler background job on startup that syncs Form 4 data for default tickers every Sunday at 00:00 UTC. No external cron or task runner is needed.

---

## 6. Frontend Deployment (Next.js)

### 6.1 Local development

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

Set the backend URL if it differs from the default:
```bash
# In frontend/.env.local:
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### 6.2 Production build

```bash
cd frontend
npm install
npm run build
npm run start
```

The production server listens on port 3000 by default.

> **Important**: `NEXT_PUBLIC_API_URL` is baked into the frontend at **build time**. You must set it before running `npm run build`. Changing it afterwards requires a rebuild.

### 6.3 Docker

```bash
cd frontend
docker build -t insider-frontend \
  --build-arg NEXT_PUBLIC_API_URL=https://api.example.com .
docker run -p 3000:3000 insider-frontend
```

Or pass it as an environment variable (it must be available during the `npm run build` step in the Dockerfile).

---

## 7. Docker Compose (All-in-One)

The quickest way to run everything:

```bash
docker compose up --build
```

This starts:
- **PostgreSQL** on port 5432 (with persistent volume)
- **Backend** on port 8000 (connected to PostgreSQL)
- **Frontend** on port 3000 (pointing to backend at localhost:8000)

### Customizing

Edit `docker-compose.yml` to change:
- Database credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`)
- `DATABASE_URL` on the backend service (must match the database credentials)
- `SEC_USER_AGENT` on the backend service
- `NEXT_PUBLIC_API_URL` on the frontend service
- `CORS_ORIGINS` on the backend service (set to your frontend URL)

### Persistent data

Database data is stored in a Docker volume (`postgres_data`). It persists across container restarts. To reset the database, remove the volume:

```bash
docker compose down -v
```

---

## 8. Corporate Network / SSL Configuration

In corporate environments, outbound HTTPS requests often pass through a TLS-intercepting proxy that uses a custom Certificate Authority (CA). This causes SSL certificate verification errors like:

```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate
```

### Option A: Install the corporate CA certificate (recommended)

This is the correct production approach. It keeps SSL verification enabled.

1. **Obtain your organization's root CA certificate** in PEM format (`.pem` or `.crt`). Your IT/security team can provide this.

2. **Set environment variables** to point Python and Node.js at the CA bundle:

   ```bash
   # For Python (requests + httpx)
   export REQUESTS_CA_BUNDLE=/path/to/corporate-ca-bundle.pem
   export SSL_CERT_FILE=/path/to/corporate-ca-bundle.pem

   # For Node.js (frontend build & SSR)
   export NODE_EXTRA_CA_CERTS=/path/to/corporate-ca-bundle.pem
   ```

3. **Docker**: Mount the certificate into the container and set the env vars:

   ```yaml
   # In docker-compose.yml, under the backend service:
   volumes:
     - /path/to/corporate-ca-bundle.pem:/etc/ssl/certs/corporate-ca.pem:ro
   environment:
     REQUESTS_CA_BUNDLE: /etc/ssl/certs/corporate-ca.pem
     SSL_CERT_FILE: /etc/ssl/certs/corporate-ca.pem
   ```

4. Keep `SEC_VERIFY_SSL=1` (the default). No code changes needed.

### Option B: Disable SSL verification (development only)

For quick local testing behind a corporate proxy where you cannot install the CA cert:

```bash
# In backend/.env:
SEC_VERIFY_SSL=0
```

This disables SSL verification for all outbound HTTPS requests from the backend (SEC EDGAR and Yahoo Finance). **Do not use this in production.**

### What the setting controls

| Request Target | Library | Controlled By |
|---------------|---------|---------------|
| SEC EDGAR (filings, submissions, XML) | `requests` | `SEC_VERIFY_SSL` env var |
| Yahoo Finance (stock prices) | `httpx` | `SEC_VERIFY_SSL` env var |

When `SEC_VERIFY_SSL=1` (default), both libraries use Python's default CA trust store and verify server certificates normally.

---

## 9. Production Hardening

### 9.1 CORS

By default, the backend allows requests from any origin (`CORS_ORIGINS=*`). In production, restrict this to your frontend domain:

```bash
CORS_ORIGINS=https://dashboard.example.com
```

Multiple origins can be comma-separated:
```bash
CORS_ORIGINS=https://dashboard.example.com,https://staging.example.com
```

### 9.2 SEC User-Agent

SEC EDGAR requires a descriptive User-Agent header with a contact email. Update `SEC_USER_AGENT` to identify your organization:

```bash
SEC_USER_AGENT=YourCompany/InsiderDashboard/1.0 (compliance@yourcompany.com)
```

### 9.3 Database credentials

- Use strong, unique passwords for PostgreSQL.
- Never commit credentials to version control. Use environment variables or secrets management.
- Use the platform's **internal/private** database URL when backend and database are on the same network (e.g. AWS VPC endpoints, Azure Private Link, GCP private IP).

### 9.4 HTTPS

- Serve both frontend and backend behind HTTPS in production.
- Most cloud platforms (AWS ALB/CloudFront, Azure App Gateway, GCP Cloud Load Balancer) handle TLS termination automatically.
- Ensure `NEXT_PUBLIC_API_URL` uses `https://` so the browser doesn't block mixed-content requests.

### 9.5 Python version

The backend is pinned to Python 3.12 via `backend/runtime.txt`. This avoids compatibility issues with newer Python versions and Pydantic/SQLModel.

---

## 10. Cloud Deployment (AWS / Azure / GCP)

The app is containerized and runs on any platform that supports Docker images or Python/Node.js runtimes. Below are recommended approaches for each major cloud provider.

### 10.1 Database (managed PostgreSQL)

| Provider | Service | Notes |
|----------|---------|-------|
| **AWS** | RDS for PostgreSQL | Use a private subnet; connect via VPC. |
| **Azure** | Azure Database for PostgreSQL Flexible Server | Use Private Link or VNet integration. |
| **GCP** | Cloud SQL for PostgreSQL | Use private IP with VPC connector. |

In all cases:
1. Create a PostgreSQL instance (v14+).
2. Create a database named `InsiderDB` (or your preferred name).
3. Note the **private/internal** connection string. Set it as `DATABASE_URL` on the backend.

### 10.2 Backend (FastAPI)

The backend is a single Python process. Recommended deployment options:

| Provider | Option A (Container) | Option B (PaaS) |
|----------|---------------------|-----------------|
| **AWS** | ECS Fargate or EKS | App Runner or Elastic Beanstalk |
| **Azure** | Azure Container Apps or AKS | Azure App Service (Python) |
| **GCP** | Cloud Run or GKE | App Engine (Python) |

**Container deployment** (recommended):
1. Build and push the Docker image:
   ```bash
   cd backend
   docker build -t insider-backend .
   # Tag and push to ECR / ACR / GCR
   ```
2. Deploy with the following environment variables:

   | Key | Value |
   |-----|-------|
   | `DATABASE_URL` | Private PostgreSQL connection string |
   | `SEC_USER_AGENT` | `YourCompany/InsiderDashboard/1.0 (email@company.com)` |
   | `CORS_ORIGINS` | Your frontend URL (e.g. `https://dashboard.example.com`) |

3. Expose port **8000**. Place behind a load balancer with HTTPS (ALB, App Gateway, or Cloud Load Balancer).

**PaaS deployment** (no Docker):
1. Set the root/source directory to `backend`.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port 8000`
4. Set the same environment variables as above.

### 10.3 Frontend (Next.js)

| Provider | Option A (Container) | Option B (PaaS/Static) |
|----------|---------------------|----------------------|
| **AWS** | ECS Fargate / App Runner | Amplify Hosting or S3 + CloudFront (static export) |
| **Azure** | Azure Container Apps | Azure Static Web Apps or App Service (Node) |
| **GCP** | Cloud Run | Firebase Hosting (static export) |

**Container deployment**:
1. Build the image with the backend URL baked in:
   ```bash
   cd frontend
   docker build -t insider-frontend \
     --build-arg NEXT_PUBLIC_API_URL=https://api.example.com .
   ```
2. Push to your container registry and deploy. Expose port **3000**.

**PaaS deployment**:
1. Set the root/source directory to `frontend`.
2. Build command: `npm install && npm run build`
3. Start command: `npm run start`
4. Set `NEXT_PUBLIC_API_URL` to your backend URL (**before** the build step, since it's baked in at build time).

### 10.4 Networking

```
Internet
   │
   ▼
┌──────────────────┐
│  Load Balancer   │  (HTTPS termination, SSL cert)
│  / CDN           │
└──┬──────────┬────┘
   │          │
   ▼          ▼
┌──────┐  ┌──────┐     ┌────────────┐
│ FE   │  │ BE   │────▶│ PostgreSQL │
│ :3000│  │ :8000│     │ (private)  │
└──────┘  └──┬───┘     └────────────┘
             │
             ▼
      SEC EDGAR APIs
      Yahoo Finance API
```

Key networking requirements:
- **Backend -> PostgreSQL**: Private network (VPC/VNet). No public exposure needed for the database.
- **Backend -> SEC EDGAR / Yahoo Finance**: Outbound HTTPS (port 443) to `www.sec.gov`, `data.sec.gov`, and `query1.finance.yahoo.com`. Ensure firewall/security groups allow this.
- **Frontend -> Backend**: The browser calls the backend directly. Both must be accessible from the user's network. Use HTTPS for both.
- **CORS**: Set `CORS_ORIGINS` on the backend to the frontend's public URL.

### 10.5 Secrets management

Store `DATABASE_URL` and other sensitive values using the platform's secrets service instead of plain environment variables:

| Provider | Service |
|----------|---------|
| **AWS** | Secrets Manager or SSM Parameter Store |
| **Azure** | Key Vault |
| **GCP** | Secret Manager |

---

## 11. Post-Deploy Checklist

- [ ] **Database**: Backend starts without errors; tables are created automatically.
- [ ] **API health**: Open `https://<backend-url>/docs` -- Swagger UI loads.
- [ ] **Frontend**: Open `https://<frontend-url>` -- the dashboard loads.
- [ ] **Data sync**: Enter a ticker, click Search/Refresh. Data populates within a few seconds.
- [ ] **SEC access**: If you get 403 errors, verify `SEC_USER_AGENT` is set correctly.
- [ ] **SSL**: If you get certificate errors, follow [Section 8](#8-corporate-network--ssl-configuration).
- [ ] **CORS**: If the frontend gets CORS errors, verify `CORS_ORIGINS` includes the frontend URL.

---

## 12. Troubleshooting

### "column X does not exist" (database errors)

The backend auto-migrates new columns on startup. If you see this after updating the code, restart the backend so the `ensure_tables` migration runs.

### Backend crashes on startup

Check the container/service logs for the actual Python traceback. Common causes:

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'main'` | Ensure the working directory is `backend/` (set root directory or `WORKDIR` correctly) |
| Database connection errors | Verify `DATABASE_URL` is set, uses `postgresql://` scheme, and the database is reachable from the backend's network |
| Port binding errors | Bind to `0.0.0.0` and expose the correct port (8000 by default) |
| `PydanticUserError: Field requires a type annotation` | Ensure Python 3.12 is used (pinned in `backend/runtime.txt`) |

### SSL certificate errors

See [Section 8](#8-corporate-network--ssl-configuration). Summary:
- **Production**: Install the corporate CA cert and set `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE`.
- **Dev only**: Set `SEC_VERIFY_SSL=0` in `backend/.env`.

### CORS errors in the browser

Set `CORS_ORIGINS` on the backend to your frontend URL. Example:
```bash
CORS_ORIGINS=https://dashboard.example.com
```

### Frontend shows "Error" / no data

1. Open browser DevTools -> Network tab. Check if API calls return errors.
2. Verify `NEXT_PUBLIC_API_URL` is correct and uses `https://` in production.
3. Verify the backend is running and accessible from the browser's network.
