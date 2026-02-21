"""SEC EDGAR HTTP client with User-Agent, rate limiting, and retries."""

import os
import time
from typing import Any, Optional

import requests

USER_AGENT = os.getenv("SEC_USER_AGENT", "InsiderDashboard/1.0 (kritik.ajmani@bain.com)")
# Set SEC_VERIFY_SSL=0 or false to disable SSL verification (e.g. corporate proxy with custom CA).
# Only use in trusted environments; disabling verification is less secure.
_VERIFY_SSL = os.getenv("SEC_VERIFY_SSL", "1").strip().lower() not in ("0", "false", "no")
BASE_DELAY = 0.15
MAX_RETRIES = 3
BACKOFF_FACTOR = 2


def _headers() -> dict[str, str]:
    # Same headers as working reference; do NOT set Host - requests sets it from URL.
    return {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "keep-alive",
    }


def get_json(url: str, params: Optional[dict[str, Any]] = None) -> Any:
    """GET JSON with rate limit and retries. Do not set Host header."""
    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(BASE_DELAY)
            r = requests.get(url, params=params, headers=_headers(), timeout=30, verify=_VERIFY_SSL)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_DELAY * (BACKOFF_FACTOR ** attempt))
    raise last_error or RuntimeError("get_json failed")


def get_text(url: str) -> str:
    """GET text (e.g. XML) with rate limit and retries."""
    last_error: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(BASE_DELAY)
            r = requests.get(url, headers=_headers(), timeout=30, verify=_VERIFY_SSL)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_DELAY * (BACKOFF_FACTOR ** attempt))
    raise last_error or RuntimeError("get_text failed")


def resolve_ticker_to_cik(ticker: str) -> tuple[str, str]:
    """Return (cik10, company_name) for ticker using company_tickers.json."""
    url = "https://www.sec.gov/files/company_tickers.json"
    data = get_json(url)
    ticker_upper = ticker.upper().strip()
    for entry in data.values():
        if str(entry.get("ticker", "")).upper() == ticker_upper:
            cik = str(entry["cik_str"])
            cik10 = cik.zfill(10)
            return cik10, entry.get("title", "Unknown")
    raise ValueError(f"Ticker not found: {ticker}")


def get_company_submissions(cik10: str) -> dict:
    """Fetch company submissions JSON. CIK must be 10-digit."""
    url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    return get_json(url)


def get_filing_index_json(cik_int: str, accession_no_no_dashes: str) -> dict:
    """Fetch index.json for a filing. accession_no_no_dashes has no hyphens."""
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_no_dashes}/"
    return get_json(base + "index.json")


def get_filing_xml(xml_url: str) -> str:
    """Fetch full URL for Form 4 XML (url can be path or full)."""
    if xml_url.startswith("http"):
        return get_text(xml_url)
    base = "https://www.sec.gov"
    url = xml_url if xml_url.startswith("/") else "/" + xml_url
    return get_text(base + url)
