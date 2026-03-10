"""Form 4 XML picking from index.json and parsing nonDerivativeTable/nonDerivativeTransaction.

Aligned with proven SEC Form 4 flow: strip namespaces, use same element paths as working reference.
"""

import re
from typing import Any, Optional
from xml.etree import ElementTree as ET

from sec_client import get_filing_index_json, get_filing_xml


def _strip_ns(tag: str) -> str:
    """Strip XML namespace from tag so find() works on SEC XML."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


# Prefer doc4.xml / form4.xml / primary_doc.xml / ownership patterns (match working reference)
FORM4_PATTERNS = [
    r"doc4\.xml$",
    r"form4\.xml$",
    r"primary_doc\.xml$",
    r"ownership/form4.*\.xml$",
    r"form4/.*doc4\.xml$",
]
XML_PREFERRED_NAMES = ("doc4.xml", "form4.xml", "primary_doc.xml")


def _score_item(name: str) -> int:
    """Higher = better match for Form 4 XML. 0 = no match."""
    name_lower = name.lower()
    if name_lower in XML_PREFERRED_NAMES:
        return 10
    for i, pat in enumerate(FORM4_PATTERNS):
        if re.search(pat, name_lower):
            return 8 - i
    if "ownership" in name_lower or "form4" in name_lower or "doc4" in name_lower:
        return 5
    if "form" in name_lower and "4" in name_lower and name_lower.endswith(".xml"):
        return 1
    return 0


def pick_form4_xml_from_index(index_json: dict, base_url: str) -> Optional[str]:
    """
    Choose Form 4 XML from index.json directory items (same logic as working reference).
    base_url: e.g. https://www.sec.gov/Archives/edgar/data/320193/000032019323000123/
    Returns full URL to the XML file, or None if no suitable item.
    """
    directory = index_json.get("directory", {})
    items = directory.get("item", [])
    if isinstance(items, dict):
        items = [items]
    names = [it.get("name") or it.get("href") or "" for it in items if isinstance(it, dict)]
    xmls = [n for n in names if n.lower().endswith(".xml")]
    if not xmls:
        return None
    preferred = [n for n in xmls if n.lower() in XML_PREFERRED_NAMES]
    if preferred:
        pick = preferred[0]
    else:
        fallback = [n for n in xmls if "ownership" in n.lower() or "form4" in n.lower() or "doc4" in n.lower()]
        pick = (fallback[0] if fallback else xmls[0])
    base = base_url.rstrip("/") + "/"
    return base + pick.lstrip("/") if not pick.startswith("http") else pick


# SEC serves human-readable Form 4 XML at this path (xslF345X05 = XSL for Form 3/4/5).
READABLE_XML_SUBDIR = "xslF345X05/"


def to_readable_xml_url(fetch_url: str) -> str:
    """
    Convert a fetch URL to the SEC's readable XML URL (under xslF345X05/).
    We keep fetching from the original URL; this is only for storage/display.
    """
    if not fetch_url or "/xslF345X05/" in fetch_url:
        return fetch_url
    if "/" not in fetch_url:
        return fetch_url
    base, filename = fetch_url.rsplit("/", 1)
    return f"{base}/{READABLE_XML_SUBDIR}{filename}"


def _text(el: Optional[ET.Element], default: str = "") -> str:
    if el is None:
        return default
    return (el.text or "").strip() or default


def _float_val(s: str) -> Optional[float]:
    if not s:
        return None
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _find_text(txn: ET.Element, *paths: str) -> Optional[str]:
    """First path that exists wins."""
    for p in paths:
        el = txn.find(p)
        if el is not None and (el.text or "").strip():
            return (el.text or "").strip()
    return None


def _find_float(txn: ET.Element, *paths: str) -> Optional[float]:
    v = _find_text(txn, *paths)
    return _float_val(v) if v is not None else None


def _parse_form_level_10b5_1(root: ET.Element) -> Optional[bool]:
    """
    Parse Rule 10b5-1(c) at form level (one value per Form 4 filing).
    Checks nonDerivativeTable (table-level), ownershipDocument, then root.
    Returns True/False/None.
    """
    for el in [
        root.find(".//nonDerivativeTable"),
        root.find("ownershipDocument"),
        root.find("ownershipDocument/nonDerivativeTable"),
        root,
    ]:
        if el is None:
            continue
        v = _find_text(el, "aff10b5One/value", "aff10b5One")
        if v is not None:
            s = (v or "").strip()
            if s == "1":
                return True
            if s == "0":
                return False
    return None


def _parse_non_derivative_transactions(root: ET.Element) -> list[dict]:
    """
    Parse nonDerivativeTable/nonDerivativeTransaction.
    Uses same element paths as working Streamlit reference (transactionShares, transactionPricePerShare,
    transactionAcquiredDisposedCode) with fallbacks for alternate SEC schema names.
    """
    out: list[dict] = []
    for table in root.findall(".//nonDerivativeTable"):
        for txn in table.findall("nonDerivativeTransaction"):
            tdate = _find_text(txn, "transactionDate/value")
            tcode = _find_text(txn, "transactionCoding/transactionCode")
            # Proven path first: transactionAcquiredDisposedCode (reference); fallbacks: acquisitionDispositionCode, transactionFormType
            acq_raw = _find_text(
                txn,
                "transactionAmounts/transactionAcquiredDisposedCode/value",
                "transactionAmounts/acquisitionDispositionCode/value",
                "transactionCoding/transactionFormType",
            )
            acq_disp = (acq_raw or "").upper()[:1] if acq_raw else None
            if acq_disp and acq_disp not in ("A", "D"):
                acq_disp = "A" if "A" in (acq_raw or "").upper() else "D" if "D" in (acq_raw or "").upper() else None
            # Proven: transactionShares, transactionPricePerShare; fallbacks: sharesAcquiredDisposed, pricePerShare
            shares = _find_float(
                txn,
                "transactionAmounts/transactionShares/value",
                "transactionAmounts/sharesAcquiredDisposed/value",
            )
            price = _find_float(
                txn,
                "transactionAmounts/transactionPricePerShare/value",
                "transactionAmounts/pricePerShare/value",
            )
            value_usd = _find_float(txn, "transactionAmounts/value")
            if value_usd is None and shares is not None and price is not None:
                value_usd = shares * price
            shares_following = _find_float(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
            out.append({
                "transaction_date": tdate,
                "transaction_code": tcode,
                "acq_disp": acq_disp,
                "shares": shares,
                "price": price,
                "value_usd": value_usd,
                "shares_owned_following": shares_following,
            })
    return out


def _parse_ownership_roots(root: ET.Element) -> list[dict]:
    """
    Parse reporting owner from root. SEC Form 4 often has root with direct children
    issuer, reportingOwner, nonDerivativeTable. After stripping namespaces we support
    root.reportingOwner or ownershipDocument.reportingOwner.
    """
    # Try root-level reportingOwner first (as in working reference)
    ro = root.find("reportingOwner")
    if ro is not None:
        return [_parse_one_ownership_from_reporter(ro)]
    ownership = root.find("ownershipDocument")
    if ownership is not None:
        return [_parse_one_ownership(ownership)]
    if root.tag and "ownershipDocument" in root.tag:
        return [_parse_one_ownership(root)]
    out = []
    for info in root.findall("informationTable/info"):
        if info is not None:
            o = _parse_info_table_info(info)
            if o:
                out.append(o)
    return out


def _parse_one_ownership_from_reporter(reporter: ET.Element) -> dict:
    """Extract insider info from a reportingOwner element."""
    d: dict = {
        "insider_name": "",
        "insider_cik": "",
        "is_director": False,
        "is_officer": False,
        "officer_title": None,
        "security_title": None,
    }
    r_id = reporter.find("reportingOwnerId")
    if r_id is not None:
        d["insider_cik"] = _text(r_id.find("rptOwnerCik")) or ""
        d["insider_name"] = _text(r_id.find("rptOwnerName")) or ""
    r_rel = reporter.find("reportingOwnerRelationship")
    if r_rel is not None:
        d["is_director"] = _text(r_rel.find("isDirector")).upper() == "1"
        d["is_officer"] = _text(r_rel.find("isOfficer")).upper() == "1"
        d["officer_title"] = _text(r_rel.find("officerTitle")) or None
    return d


def _parse_one_ownership(ownership: ET.Element) -> dict:
    d: dict = {
        "insider_name": "", "insider_cik": "", "is_director": False, "is_officer": False, "officer_title": None, "security_title": None,
    }
    reporter = ownership.find("reportingOwner")
    if reporter is not None:
        d = _parse_one_ownership_from_reporter(reporter)
    sec = ownership.find("securityTitle")
    if sec is not None:
        d["security_title"] = _text(sec) or None
    return d


def _parse_info_table_info(info: ET.Element) -> Optional[dict]:
    reporter = info.find("reportingOwner")
    if reporter is None:
        return None
    d: dict = {
        "insider_name": "",
        "insider_cik": "",
        "is_director": False,
        "is_officer": False,
        "officer_title": None,
        "security_title": None,
    }
    r_id = reporter.find("reportingOwnerId")
    if r_id is not None:
        d["insider_cik"] = _text(r_id.find("rptOwnerCik")) or ""
        d["insider_name"] = _text(r_id.find("rptOwnerName")) or ""
    r_rel = reporter.find("reportingOwnerRelationship")
    if r_rel is not None:
        d["is_director"] = _text(r_rel.find("isDirector")).upper() == "1"
        d["is_officer"] = _text(r_rel.find("isOfficer")).upper() == "1"
        d["officer_title"] = _text(r_rel.find("officerTitle")) or None
    sec = info.find("securityTitle/value")
    if sec is None:
        sec = info.find("securityTitle")
    if sec is not None:
        d["security_title"] = _text(sec) or None
    return d


def parse_form4_xml(xml_text: str, company_cik: str, accession: str, xml_url: str) -> list[dict]:
    """
    Parse Form 4 XML and return list of normalized transaction dicts suitable for DB.
    Strips XML namespaces first (as in working reference) so find() matches SEC tags.
    10b5-1 is form-level (one value per filing); we parse it once and set the same is_10b5_1 on every transaction.
    Each dict has: accession, company_cik, insider_cik, insider_name, is_director, is_officer,
    officer_title, security_title, transaction_date, transaction_code, acq_disp, shares, price,
    value_usd, shares_owned_following, is_10b5_1 (form-level), xml_url.
    """
    root = ET.fromstring(xml_text)
    # Strip namespaces so find() works on SEC Form 4 XML (same as working reference)
    for el in root.iter():
        el.tag = _strip_ns(el.tag)
    ownerships = _parse_ownership_roots(root)
    txns = _parse_non_derivative_transactions(root)
    if not ownerships:
        ownerships = [{"insider_name": "", "insider_cik": "", "is_director": False, "is_officer": False, "officer_title": None, "security_title": None}]
    # 10b5-1 is form-level: one value per filing (not per transaction)
    form_is_10b5_1 = _parse_form_level_10b5_1(root)
    # One ownership per form typically; if multiple, replicate txns per owner (simplified: use first)
    meta = ownerships[0]
    result = []
    for t in txns:
        result.append({
            "accession": accession,
            "company_cik": company_cik,
            "insider_cik": meta.get("insider_cik", ""),
            "insider_name": meta.get("insider_name", ""),
            "is_director": meta.get("is_director", False),
            "is_officer": meta.get("is_officer", False),
            "officer_title": meta.get("officer_title"),
            "security_title": meta.get("security_title"),
            "transaction_date": t.get("transaction_date"),
            "transaction_code": t.get("transaction_code"),
            "acq_disp": t.get("acq_disp"),
            "shares": t.get("shares"),
            "price": t.get("price"),
            "value_usd": t.get("value_usd"),
            "shares_owned_following": t.get("shares_owned_following"),
            "is_10b5_1": form_is_10b5_1,
            "xml_url": xml_url,
        })
    return result


def fetch_and_parse_form4(
    cik_int: str,
    accession_no_no_dashes: str,
    company_cik: str,
    base_url: str,
) -> tuple[Optional[str], list[dict]]:
    """
    Fetch index.json, pick Form 4 XML, fetch XML, parse. Returns (readable_xml_url, list of txn dicts).
    Fetch uses the original URL; we store and return the readable URL (xslF345X05/) for display.
    If no Form 4 XML found, returns (None, []).
    """
    index_json = get_filing_index_json(cik_int, accession_no_no_dashes)
    fetch_url = pick_form4_xml_from_index(index_json, base_url)
    if not fetch_url:
        return None, []
    xml_text = get_filing_xml(fetch_url)  # fetch from original URL
    readable_url = to_readable_xml_url(fetch_url)  # store/display the readable link
    accession = accession_no_no_dashes
    txns = parse_form4_xml(xml_text, company_cik, accession, readable_url)
    return readable_url, txns
