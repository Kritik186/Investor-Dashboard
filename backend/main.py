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
from sqlalchemy import delete, or_, text
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

app = FastAPI(title="Insider Dashboard API")


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


# New columns added to transactions over time (table, column, type for non-boolean)
_MIGRATE_TRANSACTION_COLUMNS = [
    ("transactions", "is_10b5_1", None),
    ("transactions", "is_ten_percent_owner", None),
    ("transactions", "is_rsu_vest_related", None),
    ("transactions", "is_tax_withholding", None),
    ("transactions", "is_gift", None),
    ("transactions", "classification_confidence", "VARCHAR(20)"),
    ("transactions", "classification_reasoning", "TEXT"),
    ("transactions", "plan_adoption_date", "VARCHAR(12)"),
    ("transactions", "is_margin_call_collateral", None),
]
_MIGRATE_FILING_COLUMNS = [("filings", "is_10b5_1", None)]


@app.on_event("startup")
def ensure_tables():
    """Create all tables on startup; add any missing columns (migration for schema changes)."""
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        for table, col, col_type in _MIGRATE_FILING_COLUMNS + _MIGRATE_TRANSACTION_COLUMNS:
            try:
                if col_type is None:
                    # Boolean
                    if "sqlite" in str(engine.url):
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} BOOLEAN"))
                    else:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} BOOLEAN"))
                else:
                    if "sqlite" in str(engine.url):
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    else:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                conn.commit()
            except Exception:
                conn.rollback()
                pass
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


# Transaction type filter: open market (P, S) + sale-type flags (10b5-1, rsu_vest, tax_withholding, gift)
VALID_TRANSACTION_TYPE_SLUGS = {"P", "S", "10b5-1", "rsu_vest", "tax_withholding", "gift"}


def _parse_transaction_types(transaction_types: Optional[str]) -> set[str]:
    """Parse comma-separated transaction_types; return normalized set of slugs. Empty = no filter (all)."""
    if not transaction_types or not transaction_types.strip():
        return set()
    return {t.strip() for t in transaction_types.split(",") if t.strip() and t.strip() in VALID_TRANSACTION_TYPE_SLUGS}


def _txn_dict_matches_types(d: dict, types_set: set[str]) -> bool:
    """True if transaction dict matches any of the selected type slugs (code or classification)."""
    if not types_set:
        return True
    code = (d.get("transaction_code") or "").strip().upper()
    if code in types_set:
        return True
    if "10b5-1" in types_set and d.get("is_10b5_1") is True:
        return True
    if "rsu_vest" in types_set and d.get("is_rsu_vest_related") is True:
        return True
    if "tax_withholding" in types_set and d.get("is_tax_withholding") is True:
        return True
    if "gift" in types_set and d.get("is_gift") is True:
        return True
    return False


def _filter_txns_dict(txns: list[dict], transaction_types: Optional[list[str]] = None) -> list[dict]:
    """Filter transaction dicts by transaction type slugs. Empty types = show all. Match any selected type."""
    if not transaction_types:
        return txns
    types_set = {t.strip() for t in transaction_types if t and str(t).strip() and t.strip() in VALID_TRANSACTION_TYPE_SLUGS}
    if not types_set:
        return txns
    return [d for d in txns if _txn_dict_matches_types(d, types_set)]


def _transaction_types_where_clause(types_set: set[str]):
    """Build SQLAlchemy OR condition for Transaction model from type slugs. None if no filter."""
    if not types_set:
        return None
    conditions = []
    codes = [c for c in ("P", "S") if c in types_set]
    if codes:
        conditions.append(Transaction.transaction_code.in_(codes))
    if "10b5-1" in types_set:
        conditions.append(Transaction.is_10b5_1 == True)
    if "rsu_vest" in types_set:
        conditions.append(Transaction.is_rsu_vest_related == True)
    if "tax_withholding" in types_set:
        conditions.append(Transaction.is_tax_withholding == True)
    if "gift" in types_set:
        conditions.append(Transaction.is_gift == True)
    if not conditions:
        return None
    return or_(*conditions)


def _accession_to_sec_index_url(company_cik: str, accession_no_dashes: str) -> str:
    """SEC filing index page (fallback when xml_url is missing). Accession format: 10-2-6 with dashes."""
    acc = (accession_no_dashes or "").replace("-", "")
    if len(acc) >= 18:
        dashed = f"{acc[:10]}-{acc[10:12]}-{acc[12:]}"
    else:
        dashed = accession_no_dashes or acc
    return f"https://www.sec.gov/Archives/edgar/data/{company_cik}/{dashed}/"


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
        "is_10b5_1": getattr(t, "is_10b5_1", None),
        "plan_adoption_date": getattr(t, "plan_adoption_date", None),
        "is_margin_call_collateral": getattr(t, "is_margin_call_collateral", None),
        "is_rsu_vest_related": getattr(t, "is_rsu_vest_related", None),
        "is_tax_withholding": getattr(t, "is_tax_withholding", None),
        "is_gift": getattr(t, "is_gift", None),
        "classification_confidence": getattr(t, "classification_confidence", None),
        "classification_reasoning": getattr(t, "classification_reasoning", None),
        "is_ten_percent_owner": getattr(t, "is_ten_percent_owner", None),
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
            form_10b5_1 = any(t.get("is_10b5_1") for t in txns) if txns else None
            session.add(Filing(accession=acc_no_dashes, company_cik=cik10, filing_date=fd, xml_url=xml_url, is_amendment=False, is_10b5_1=form_10b5_1))
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
                        is_10b5_1=t.get("is_10b5_1"),
                        plan_adoption_date=t.get("plan_adoption_date"),
                        is_margin_call_collateral=t.get("is_margin_call_collateral"),
                        is_rsu_vest_related=t.get("is_rsu_vest_related"),
                        is_tax_withholding=t.get("is_tax_withholding"),
                        is_gift=t.get("is_gift"),
                        classification_confidence=t.get("classification_confidence"),
                        classification_reasoning=t.get("classification_reasoning"),
                        is_ten_percent_owner=t.get("is_ten_percent_owner"),
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


@app.post("/api/backfill-10b5-1")
def backfill_10b5_1(max_filings: int = Query(200, ge=1, le=2000, alias="max_filings")):
    """
    One-time backfill: for existing transactions with is_10b5_1 IS NULL, re-fetch Form 4 XML,
    re-run classification (10b5-1, gift, tax withholding, RSU vest), and set per-transaction
    and filing fields.
    """
    updated = 0
    errors = 0
    with Session(engine) as session:
        rows = list(session.exec(
            select(Transaction.accession, Transaction.company_cik).where(Transaction.is_10b5_1.is_(None)).distinct()
        ))
        seen = set()
        accessions_to_process = []
        for acc, cik in rows:
            if (acc, cik) in seen:
                continue
            seen.add((acc, cik))
            accessions_to_process.append((acc, cik))
        accessions_to_process = accessions_to_process[:max_filings]
    for accession, company_cik in accessions_to_process:
        try:
            cik_int = str(int(company_cik))
            base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/"
            _, parsed_list = fetch_and_parse_form4(cik_int, accession, company_cik, base_url)
            if not parsed_list:
                continue
            filing_is_10b5_1 = any(p.get("is_10b5_1") for p in parsed_list)
            with Session(engine) as session:
                filing = session.get(Filing, accession)
                if filing is not None:
                    filing.is_10b5_1 = filing_is_10b5_1
                    session.add(filing)
                db_txns = list(
                    session.exec(
                        select(Transaction).where(
                            Transaction.accession == accession,
                            Transaction.company_cik == company_cik,
                        ).order_by(Transaction.id)
                    )
                )
                for i, t in enumerate(db_txns):
                    if i < len(parsed_list):
                        p = parsed_list[i]
                        t.is_10b5_1 = p.get("is_10b5_1")
                        t.is_rsu_vest_related = p.get("is_rsu_vest_related")
                        t.plan_adoption_date = p.get("plan_adoption_date")
                        t.is_margin_call_collateral = p.get("is_margin_call_collateral")
                        t.is_tax_withholding = p.get("is_tax_withholding")
                        t.is_gift = p.get("is_gift")
                        t.classification_confidence = p.get("classification_confidence")
                        t.classification_reasoning = p.get("classification_reasoning")
                        session.add(t)
                        updated += 1
                session.commit()
        except Exception:
            errors += 1
    return {"updated": updated, "errors": errors, "accessions_processed": len(accessions_to_process)}


def _txn_to_classification_json(t: Transaction, transaction_id: str) -> dict:
    """One transaction in the classification output format (explicit booleans + confidence + reasoning)."""
    return {
        "transaction_id": transaction_id,
        "transaction_code": t.transaction_code or "",
        "is_rsu_vest_related": bool(getattr(t, "is_rsu_vest_related", None)),
        "is_tax_withholding": bool(getattr(t, "is_tax_withholding", None)),
        "is_gift": bool(getattr(t, "is_gift", None)),
        "is_10b5_1": bool(getattr(t, "is_10b5_1", None)),
        "classification_confidence": getattr(t, "classification_confidence", None) or "low",
        "reasoning": getattr(t, "classification_reasoning", None) or "",
    }


@app.get("/api/{ticker}/classifications")
def get_classifications(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
):
    """Return one classification object per transaction. Optional transaction_types (comma-separated: P, S, 10b5-1, rsu_vest, tax_withholding, gift)."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "classifications": []}
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10)
        if lookback_days:
            cutoff = date.today() - timedelta(days=lookback_days)
            stmt = stmt.where(Transaction.transaction_date >= cutoff)
        txns = list(session.exec(stmt))
    txns_dict = [_txn_to_dict(t) for t in txns]
    types_set = _parse_transaction_types(transaction_types)
    txns_dict = _filter_txns_dict(txns_dict, list(types_set) if types_set else None)
    seen_ids = {d["id"] for d in txns_dict}
    txns_filtered = [t for t in txns if t.id in seen_ids]
    classifications = [
        _txn_to_classification_json(t, transaction_id=str(t.id) if t.id is not None else f"{t.accession}|{t.transaction_date}")
        for t in txns_filtered
    ]
    return {"ticker": ticker, "classifications": classifications}


@app.get("/api/{ticker}/top")
def get_top(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
):
    """Top 15 insiders by shares held (recent). Always uses all transactions so shares held does not change with type filter."""
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
    # Always use unfiltered transactions for top/shares held so the number does not change with type filter
    top = top_15_insiders(txns_dict, lookback_days=lookback_days)
    return {"ticker": ticker, "lookback_days": lookback_days, "top_insiders": top}


@app.get("/api/{ticker}/holdings")
def get_holdings(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
):
    """Holdings over time for top 15; optional transaction_types (comma-separated: P, S, 10b5-1, rsu_vest, tax_withholding, gift)."""
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
    types_set = _parse_transaction_types(transaction_types)
    types_list = list(types_set) if types_set else None
    txns_all_dict = _filter_txns_dict(txns_all_dict, types_list)
    txns_dict = _filter_txns_dict(txns_dict, types_list)
    top = top_15_insiders(txns_all_dict, lookback_days=None)
    holdings = holdings_over_time(txns_dict, top, lookback_days)
    return {"ticker": ticker, "lookback_days": lookback_days, "holdings": holdings}


@app.get("/api/{ticker}/aggregates")
def get_aggregates(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    period: str = Query("month", alias="period"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
):
    """Monthly or quarterly aggregates for top 15. Optional transaction_types (comma-separated: P, S, 10b5-1, rsu_vest, tax_withholding, gift)."""
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
        stmt = (
            select(Transaction)
            .where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
            .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
        )
        txns = list(session.exec(stmt))
    txns_all_dict = [_txn_to_dict(t) for t in txns_all]
    for d in txns_all_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    txns_dict = [_txn_to_dict(t) for t in txns]
    for d in txns_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    types_set = _parse_transaction_types(transaction_types)
    txns_dict_unfiltered = txns_dict  # all txns in lookback (for actual start/end positions)
    txns_dict_filtered = _filter_txns_dict(txns_dict, list(types_set) if types_set else None)
    cutoff_str = cutoff.isoformat()
    # Actual position before cutoff (from all transactions) for start-of-range
    last_before_cutoff = {}
    for d in txns_all_dict:
        td = d.get("transaction_date") or ""
        if not td or td >= cutoff_str:
            continue
        cik = d.get("insider_cik")
        following = d.get("shares_owned_following")
        if cik is None or following is None:
            continue
        if cik not in last_before_cutoff or td > last_before_cutoff[cik][0]:
            last_before_cutoff[cik] = (td, float(following))
    position_before_cutoff = {cik: val[1] for cik, val in last_before_cutoff.items()}
    top = top_15_insiders(txns_all_dict, lookback_days=None)

    if types_set:
        # Filtered view: start shares = actual (from unfiltered); change = from filtered types only; end = start + change (not filing end).
        agg_actual = aggregates_monthly_quarterly(
            txns_dict_unfiltered, top, lookback_days, period, position_before_cutoff, use_synthetic_positions=False
        )
        agg_filtered = aggregates_monthly_quarterly(
            txns_dict_filtered, top, lookback_days, period, position_before_cutoff, use_synthetic_positions=True
        )
        def _period_key(period_end) -> str:
            """Normalize period_end to YYYY-MM-DD string so merge keys match."""
            if period_end is None:
                return ""
            if hasattr(period_end, "isoformat"):
                return period_end.isoformat()[:10]
            return str(period_end)[:10]

        filtered_by_key = {
            (r["insider_cik"], r["insider_name"], _period_key(r.get("period_end"))): r for r in agg_filtered
        }
        merged = []
        for row in agg_actual:
            key = (row["insider_cik"], row["insider_name"], _period_key(row.get("period_end")))
            start_shares = row.get("start_shares")
            if key in filtered_by_key:
                fr = filtered_by_key[key]
                change_shares = fr.get("change_shares")
                if change_shares is None:
                    change_shares = 0
                else:
                    change_shares = float(change_shares)
                # End shares = start + change (only selected types). Never use filing's end (row["end_shares"]).
                end_shares = (start_shares + change_shares) if start_shares is not None else None
                shares_sold = fr.get("shares_sold") or 0
                shares_bought = fr.get("shares_bought") or 0
                value_sold = fr.get("value_sold_usd")
                value_bought = fr.get("value_bought_usd")
                pct_sold = (float(shares_sold) / float(start_shares)) if start_shares and start_shares != 0 else None
                pct_sold_label = "insufficient data" if not start_shares or start_shares == 0 else None
                merged.append({
                    **row,
                    "start_shares": float(start_shares) if start_shares is not None else None,
                    "end_shares": float(end_shares) if end_shares is not None else None,
                    "change_shares": change_shares,
                    "shares_sold": shares_sold,
                    "shares_bought": shares_bought,
                    "value_sold_usd": value_sold,
                    "value_bought_usd": value_bought,
                    "pct_sold": pct_sold,
                    "pct_sold_label": pct_sold_label,
                    "dispositions": fr.get("dispositions", row.get("dispositions", [])),
                    "period_10b5_1_status": fr.get("period_10b5_1_status", row.get("period_10b5_1_status")),
                    "plan_adoption_date": fr.get("plan_adoption_date"),
                    "is_margin_call_collateral": fr.get("is_margin_call_collateral", False),
                    "has_rsu_vest": fr.get("has_rsu_vest", row.get("has_rsu_vest")),
                    "has_tax_withholding": fr.get("has_tax_withholding", row.get("has_tax_withholding")),
                    "has_gift": fr.get("has_gift", row.get("has_gift")),
                })
            else:
                change_shares = 0
                end_shares = start_shares
                merged.append({
                    **row,
                    "start_shares": float(start_shares) if start_shares is not None else None,
                    "end_shares": float(end_shares) if end_shares is not None else None,
                    "change_shares": 0,
                    "shares_sold": 0,
                    "shares_bought": 0,
                    "value_sold_usd": None,
                    "value_bought_usd": None,
                    "pct_sold": None,
                    "pct_sold_label": "insufficient data" if not start_shares or start_shares == 0 else None,
                    "dispositions": [],
                    "plan_adoption_date": None,
                    "is_margin_call_collateral": False,
                })
        agg = merged
    else:
        agg = aggregates_monthly_quarterly(
            txns_dict_unfiltered, top, lookback_days, period, position_before_cutoff, use_synthetic_positions=False
        )
    return {"ticker": ticker, "lookback_days": lookback_days, "period": period, "aggregates": agg}


@app.get("/api/{ticker}/transactions")
def get_transactions(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    insider_cik: Optional[str] = Query(None, alias="insider_cik"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated transactions; optional filter by insider_cik, transaction_types (comma-separated: P, S, 10b5-1, rsu_vest, tax_withholding, gift).
    Fills missing transaction xml_url from Filing (same accession) so older rows still show links."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            return {"ticker": ticker, "transactions": [], "limit": limit, "offset": offset}
        cutoff = date.today() - timedelta(days=lookback_days)
        stmt = select(Transaction).where(Transaction.company_cik == company.cik10, Transaction.transaction_date >= cutoff)
        if insider_cik:
            stmt = stmt.where(Transaction.insider_cik == insider_cik)
        types_set = _parse_transaction_types(transaction_types)
        type_where = _transaction_types_where_clause(types_set)
        if type_where is not None:
            stmt = stmt.where(type_where)
        stmt = stmt.order_by(Transaction.transaction_date.desc()).offset(offset).limit(limit)
        txns = list(session.exec(stmt))
        accessions_missing_url = list({t.accession for t in txns if not t.xml_url})
        filing_url_map = {}
        for acc in accessions_missing_url:
            filing = session.get(Filing, acc)
            if filing and filing.xml_url:
                filing_url_map[acc] = filing.xml_url
        def txn_to_dict_with_filing_url(t):
            d = _txn_to_dict(t)
            if not d.get("xml_url"):
                if t.accession in filing_url_map:
                    d["xml_url"] = filing_url_map[t.accession]
                else:
                    d["xml_url"] = _accession_to_sec_index_url(t.company_cik, t.accession)
            return d
        transactions_out = [txn_to_dict_with_filing_url(t) for t in txns]
    return {
        "ticker": ticker,
        "transactions": transactions_out,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/{ticker}/insider/{insider_cik}/activity")
def get_insider_activity(
    ticker: str,
    insider_cik: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    period: str = Query("month", alias="period"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
):
    """Per-insider time series by period; optional transaction_types (comma-separated: P, S, 10b5-1, rsu_vest, tax_withholding, gift)."""
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
    types_set = _parse_transaction_types(transaction_types)
    txns_dict = _filter_txns_dict(txns_dict, list(types_set) if types_set else None)
    activity = insider_activity_over_time(txns_dict, insider_cik, lookback_days, period)
    return {"ticker": ticker, "insider_cik": insider_cik, "period": period, "activity": activity}


@app.post("/api/{ticker}/refresh")
def refresh(ticker: str, body: Optional[SyncBody] = None):
    """Alias for sync: POST body can override lookback_days and max_forms."""
    b = body or SyncBody(ticker=ticker, lookback_days=365, max_forms=100)
    if b.ticker.upper() != ticker.upper():
        b = SyncBody(ticker=ticker, lookback_days=b.lookback_days, max_forms=b.max_forms)
    return sync(b)


@app.post("/api/{ticker}/backfill")
def backfill_ticker(
    ticker: str,
    lookback_days: int = Query(365, ge=1, le=3650, alias="lookback_days"),
    max_forms: int = Query(500, ge=1, le=2000, alias="max_forms"),
):
    """
    Clear all filings and transactions for this company, then re-fetch from the SEC.
    Use after schema or parsing changes to repopulate with the latest logic.
    """
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        cik10 = company.cik10
        session.execute(delete(Transaction).where(Transaction.company_cik == cik10))
        session.execute(delete(Filing).where(Filing.company_cik == cik10))
        session.commit()
    result = _do_sync(ticker, lookback_days=lookback_days, max_forms=max_forms)
    return {
        "ticker": ticker,
        "backfill": True,
        "transactions_created": result.get("transactions_created", 0),
        "processed": result.get("processed", 0),
    }


@app.delete("/api/{ticker}")
def delete_company(ticker: str):
    """Delete a company and all its filings and transactions from the database."""
    ticker = ticker.upper()
    with Session(engine) as session:
        company = session.get(Company, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        cik10 = company.cik10
        session.execute(delete(Transaction).where(Transaction.company_cik == cik10))
        session.execute(delete(Filing).where(Filing.company_cik == cik10))
        session.delete(company)
        session.commit()
    return {"ticker": ticker, "deleted": True}


@app.get("/api/{ticker}/kpis")
def get_kpis(
    ticker: str,
    lookback_days: int = Query(365, alias="lookback_days"),
    transaction_types: Optional[str] = Query(None, alias="transaction_types"),
):
    """KPI cards: total $ sold, total $ bought, net shares, #filings, last refresh. Optional transaction_types (comma-separated: P, S, 10b5-1, rsu_vest, tax_withholding, gift)."""
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
    txns_dict = [_txn_to_dict(t) for t in txns]
    for d in txns_dict:
        d["transaction_date"] = d["transaction_date"][:10] if d.get("transaction_date") else None
    types_set = _parse_transaction_types(transaction_types)
    txns_dict = _filter_txns_dict(txns_dict, list(types_set) if types_set else None)
    total_sold = sum((d.get("value_usd") or 0) for d in txns_dict if (d.get("acq_disp") or "").upper() == "D")
    total_bought = sum((d.get("value_usd") or 0) for d in txns_dict if (d.get("acq_disp") or "").upper() == "A")
    shares_sold = sum((d.get("shares") or 0) for d in txns_dict if (d.get("acq_disp") or "").upper() == "D")
    shares_bought = sum((d.get("shares") or 0) for d in txns_dict if (d.get("acq_disp") or "").upper() == "A")
    net_shares = sum((d.get("shares") or 0) * (1 if (d.get("acq_disp") or "").upper() == "A" else -1) for d in txns_dict)
    filings_count_filtered = len({d["accession"] for d in txns_dict if d.get("accession")})
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
        "filings_count": filings_count_filtered,
        "last_refresh": last_refresh,
    }


@app.get("/")
def root():
    return {"message": "Insider Dashboard API", "docs": "/docs"}
