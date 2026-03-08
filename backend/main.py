"""FastAPI app: resolve, sync, top, holdings, aggregates, transactions."""

import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

# Load .env from backend directory so DATABASE_URL is set when running uvicorn from any cwd
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, create_engine, select

from config import DEFAULT_COMPANY_LABELS, DEFAULT_TICKERS
from models import Company, Filing, Insider, Transaction
from parser import fetch_and_parse_form4
from sec_client import get_company_submissions, resolve_ticker_to_cik
from transforms import aggregates_monthly_quarterly, holdings_over_time, insider_activity_over_time, top_15_insiders

# DB — use InsiderDB for PostgreSQL (create database first: CREATE DATABASE "InsiderDB";)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./insider.db")
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

# Ensure all tables exist (companies, insiders, filings, transactions)
from sqlmodel import SQLModel

SQLModel.metadata.create_all(engine)

app = FastAPI(title="Insider Trading Dashboard API")


def _weekly_sync_default_companies():
    """Sync Form 4 data for all default companies. Runs every Sunday."""
    log = logging.getLogger(__name__)
    lookback_days = 365
    max_forms = 500
    for ticker in DEFAULT_TICKERS:
        try:
            result = _do_sync(ticker, lookback_days=lookback_days, max_forms=max_forms)
            log.info("Weekly sync %s: %s transactions created", ticker, result.get("transactions_created", 0))
        except Exception as e:
            log.warning("Weekly sync %s failed: %s", ticker, e)


@app.on_event("startup")
def ensure_tables():
    """Create all tables on startup if they do not exist (idempotent)."""
    SQLModel.metadata.create_all(engine)
    scheduler = BackgroundScheduler()
    # Every Sunday at 00:00 UTC
    scheduler.add_job(_weekly_sync_default_companies, CronTrigger(day_of_week="sun", hour=0, minute=0))
    scheduler.start()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/response models ---
class SyncBody(BaseModel):
    ticker: str
    lookback_days: int = 365
    max_forms: Optional[int] = 100


def _txn_to_dict(t: Transaction) -> dict:
    return {
        "id": t.id,
        "accession": t.accession,
        "company_cik": t.company_cik,
        "insider_cik": t.insider_cik,
        "insider_name": t.insider_name,
        "is_director": t.is_director,
        "is_officer": t.is_officer,
        "officer_title": t.officer_title,
        "security_title": t.security_title,
        "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
        "transaction_code": t.transaction_code,
        "acq_disp": t.acq_disp,
        "shares": t.shares,
        "price": t.price,
        "value_usd": t.value_usd,
        "shares_owned_following": t.shares_owned_following,
        "xml_url": t.xml_url,
    }


@app.get("/api/resolve")
def resolve(ticker: str = Query(..., alias="ticker")):
    """Resolve ticker to cik10 and company name."""
    try:
        cik10, name = resolve_ticker_to_cik(ticker)
        return {"cik10": cik10, "name": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _do_sync(ticker: str, lookback_days: int = 365, max_forms: int = 500) -> dict:
    """Fetch Form 4 filings for a ticker, parse, store. Used by POST /api/sync and weekly job. Raises ValueError if ticker not found."""
    ticker = ticker.upper().strip()
    cik10, name = resolve_ticker_to_cik(ticker)
    cik_int = str(int(cik10))
    submissions = get_company_submissions(cik10)
    filings_list = submissions.get("filings", {}).get("recent") or {}
    forms = filings_list.get("form") or []
    accessions = filings_list.get("accessionNumber") or []
    filing_dates = filings_list.get("filingDate") or []
    form4_indices = [i for i, f in enumerate(forms) if (f or "").upper() == "4"]
    cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None
    to_process = []
    for i in form4_indices[: max_forms * 2]:
        if i >= len(accessions) or i >= len(filing_dates):
            continue
        acc = (accessions[i] or "").replace("-", "")
        fd = filing_dates[i]
        try:
            fd_date = datetime.strptime(fd[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        if cutoff and fd_date < cutoff:
            continue
        to_process.append((accessions[i], acc, fd_date))
    to_process = to_process[:max_forms]
    base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
    created = 0
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            session.add(Company(ticker=ticker, cik10=cik10, name=name))
            session.commit()
        for acc_with_dashes, acc_no_dashes, fd in to_process:
            existing = session.exec(select(Filing).where(Filing.accession == acc_no_dashes)).first()
            if existing:
                continue
            try:
                xml_url, txns = fetch_and_parse_form4(cik_int, acc_no_dashes, cik10, base_url + acc_no_dashes + "/")
            except Exception:
                continue
            if not xml_url:
                session.add(Filing(accession=acc_no_dashes, company_cik=cik10, filing_date=fd, xml_url=None, is_amendment=False))
                session.commit()
                continue
            session.add(Filing(accession=acc_no_dashes, company_cik=cik10, filing_date=fd, xml_url=xml_url, is_amendment=False))
            for t in txns:
                insider_cik = t.get("insider_cik") or ""
                insider_name = t.get("insider_name") or ""
                if insider_cik:
                    if not session.get(Insider, insider_cik):
                        session.add(Insider(insider_cik=insider_cik, name=insider_name))
                td = t.get("transaction_date")
                if isinstance(td, str):
                    try:
                        td = datetime.strptime(td[:10], "%Y-%m-%d").date()
                    except Exception:
                        continue
                if not td:
                    continue
                session.add(
                    Transaction(
                        accession=acc_no_dashes,
                        company_cik=cik10,
                        insider_cik=insider_cik,
                        insider_name=insider_name,
                        is_director=t.get("is_director", False),
                        is_officer=t.get("is_officer", False),
                        officer_title=t.get("officer_title"),
                        security_title=t.get("security_title"),
                        transaction_date=td,
                        transaction_code=t.get("transaction_code"),
                        acq_disp=t.get("acq_disp"),
                        shares=t.get("shares"),
                        price=t.get("price"),
                        value_usd=t.get("value_usd"),
                        shares_owned_following=t.get("shares_owned_following"),
                        xml_url=t.get("xml_url"),
                    )
                )
                created += 1
            session.commit()
        company = session.get(Company, ticker)
        if company:
            company.last_refresh = datetime.utcnow()
            session.add(company)
            session.commit()
    return {"ticker": ticker, "cik10": cik10, "processed": len(to_process), "transactions_created": created}


@app.get("/api/default-companies")
def get_default_companies():
    """Return the list of default companies (always on dashboard), with display labels."""
    companies = [{"ticker": t, "label": DEFAULT_COMPANY_LABELS.get(t, t)} for t in DEFAULT_TICKERS]
    return {"companies": companies}


@app.post("/api/sync")
def sync(body: SyncBody):
    """Fetch Form 4 filings, parse, store. Cache by accession to avoid re-downloading."""
    try:
        return _do_sync(body.ticker, body.lookback_days, body.max_forms or 500)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/{ticker}/top")
def get_top(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
):
    """Top 15 insiders by shares held on the most recent date. Independent of lookback_days (uses all data)."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "lookback_days": lookback_days, "top_insiders": []}
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10)
        txns = list(session.exec(stmt))
    txns_dict = [_txn_to_dict(t) for t in txns]
    for d in txns_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    top = top_15_insiders(txns_dict, lookback_days=None)
    return {"ticker": ticker, "lookback_days": lookback_days, "top_insiders": top}


@app.get("/api/{ticker}/holdings")
def get_holdings(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
):
    """Holdings over time for top 15 (shares_owned_following at each transaction date). Top 15 is independent of lookback."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "lookback_days": lookback_days, "holdings": []}
        stmt_all = select(Transaction).where(Transaction.company_cik == company.cik10)
        txns_all = list(session.exec(stmt_all))
        cutoff = date.today() - timedelta(days=lookback_days)
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
        txns = list(session.exec(stmt))
    txns_all_dict = [_txn_to_dict(t) for t in txns_all]
    for d in txns_all_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    txns_dict = [_txn_to_dict(t) for t in txns]
    for d in txns_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    top = top_15_insiders(txns_all_dict, lookback_days=None)
    holdings = holdings_over_time(txns_dict, top, lookback_days)
    return {"ticker": ticker, "lookback_days": lookback_days, "holdings": holdings}


@app.get("/api/{ticker}/aggregates")
def get_aggregates(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    period: str = Query("month", alias="period"),
):
    """Monthly or quarterly aggregates for top 15. Top 15 is independent of lookback."""
    if period not in ("month", "quarter"):
        raise HTTPException(status_code=400, detail="period must be month or quarter")
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "lookback_days": lookback_days, "period": period, "aggregates": []}
        stmt_all = select(Transaction).where(Transaction.company_cik == company.cik10)
        txns_all = list(session.exec(stmt_all))
        cutoff = date.today() - timedelta(days=lookback_days)
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
        txns = list(session.exec(stmt))
    txns_all_dict = [_txn_to_dict(t) for t in txns_all]
    for d in txns_all_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    txns_dict = [_txn_to_dict(t) for t in txns]
    for d in txns_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    top = top_15_insiders(txns_all_dict, lookback_days=None)
    agg = aggregates_monthly_quarterly(txns_dict, top, lookback_days, period)
    return {"ticker": ticker, "lookback_days": lookback_days, "period": period, "aggregates": agg}


@app.get("/api/{ticker}/transactions")
def get_transactions(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    insider_cik: Optional[str] = Query(None, alias="insider_cik"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated transactions; optional filter by insider_cik. Returns empty list if company not synced yet."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "transactions": [], "limit": limit, "offset": offset}
        cutoff = date.today() - timedelta(days=lookback_days)
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
        if insider_cik:
            stmt = stmt.where(Transaction.insider_cik == insider_cik)
        stmt = stmt.order_by(Transaction.transaction_date.desc()).offset(offset).limit(limit)
        txns = list(session.exec(stmt))
    return {
        "ticker": ticker,
        "transactions": [_txn_to_dict(t) for t in txns],
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/{ticker}/insider/{insider_cik}/activity")
def get_insider_activity(
    ticker: str,
    insider_cik: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    period: str = Query("month", alias="period"),
):
    """Per-insider time series of shares bought and sold by period (month/quarter). For Holdings tab: pick an insider and show their activity chart."""
    if period not in ("month", "quarter"):
        raise HTTPException(status_code=400, detail="period must be month or quarter")
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "insider_cik": insider_cik, "activity": []}
        cutoff = date.today() - timedelta(days=lookback_days)
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
        txns = list(session.exec(stmt))
    txns_dict = [_txn_to_dict(t) for t in txns]
    for d in txns_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    activity = insider_activity_over_time(txns_dict, insider_cik, lookback_days, period)
    return {"ticker": ticker, "insider_cik": insider_cik, "period": period, "activity": activity}


@app.post("/api/{ticker}/refresh")
def refresh(ticker: str, body: Optional[SyncBody] = None):
    """Alias for sync: POST body can override lookback_days and max_forms."""
    b = body or SyncBody(ticker=ticker, lookback_days=365, max_forms=100)
    if b.ticker.upper() != ticker.upper():
        b = SyncBody(ticker=ticker, lookback_days=b.lookback_days, max_forms=b.max_forms)
    return sync(b)


@app.get("/api/{ticker}/kpis")
def get_kpis(ticker: str, lookback_days: int = Query(365, alias="lookback_days")):
    """KPI cards: total $ sold, total $ bought, net shares, #filings, last refresh. Returns zeros if company not synced yet."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {
                "ticker": ticker,
                "lookback_days": lookback_days,
                "total_value_sold_usd": 0,
                "total_value_bought_usd": 0,
                "total_shares_sold": 0,
                "total_shares_bought": 0,
                "net_shares": 0,
                "filings_count": 0,
                "last_refresh": None,
            }
        cutoff = date.today() - timedelta(days=lookback_days)
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
        txns = list(session.exec(stmt))
        filings_stmt = select(Filing).where(Filing.company_cik == company.cik10, Filing.filing_date >= cutoff)
        filings_count = len(list(session.exec(filings_stmt)))
    total_sold = sum((t.value_usd or 0) for t in txns if (t.acq_disp or "").upper() == "D")
    total_bought = sum((t.value_usd or 0) for t in txns if (t.acq_disp or "").upper() == "A")
    shares_sold = sum((t.shares or 0) for t in txns if (t.acq_disp or "").upper() == "D")
    shares_bought = sum((t.shares or 0) for t in txns if (t.acq_disp or "").upper() == "A")
    net_shares = sum((t.shares or 0) * (1 if (t.acq_disp or "").upper() == "A" else -1) for t in txns)
    with Session(engine) as session:
        company = session.get(Company, ticker)
        last_refresh = company.last_refresh.isoformat() if company and company.last_refresh else None
    return {
        "ticker": ticker,
        "lookback_days": lookback_days,
        "total_value_sold_usd": total_sold,
        "total_value_bought_usd": total_bought,
        "total_shares_sold": shares_sold,
        "total_shares_bought": shares_bought,
        "net_shares": net_shares,
        "filings_count": filings_count,
        "last_refresh": last_refresh,
    }


@app.get("/")
def root():
    return {"message": "Insider Trading Dashboard API", "docs": "/docs"}
