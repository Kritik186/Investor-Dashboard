"""Form 4 XML picking from index.json and parsing nonDerivativeTable/nonDerivativeTransaction.

Aligned with proven SEC Form 4 flow: strip namespaces, use same element paths as working reference.
"""

import re
from typing import Any, Optional
from xml.etree import ElementTree as ET

from sec_client import get_filing_index_json, get_filing_xml

from transaction_classifier import classify_transaction


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


def _collect_footnotes(root: ET.Element) -> dict[str, str]:
    """
    Build a map footnote_id -> footnote text from the document.
    Handles SEC patterns: footnote with id attribute or child id element; text in value or element text.
    Tag matching is case-insensitive (footnote / footNote).
    """
    out: dict[str, str] = {}
    for el in root.iter():
        tag_local = _strip_ns(el.tag)
        if (tag_local or "").lower() != "footnote":
            continue
        fid = el.get("id") or _text(el.find("id"))
        if not fid:
            continue
        text = _text(el.find("value")) or (el.text or "").strip()
        if text:
            out[fid.strip()] = text
    return out


def _footnote_ids_for_element(el: ET.Element) -> list[str]:
    """Collect all footnote IDs referenced by this element: footnoteId/footNoteId children and any *FootnoteId attributes."""
    ids: list[str] = []
    seen: set[str] = set()
    for child in el.iter():
        tag = _strip_ns(child.tag)
        if (tag or "").lower() == "footnoteid":
            t = (child.text or "").strip()
            if t and t not in seen:
                ids.append(t)
                seen.add(t)
        if (tag or "").lower() == "footnoteids":
            for sub in child:
                st = _strip_ns(sub.tag)
                if (st or "").lower() == "footnoteid":
                    t = (sub.text or "").strip()
                    if t and t not in seen:
                        ids.append(t)
                        seen.add(t)
        for attr_name, attr_val in (child.attrib or {}).items():
            an = (attr_name or "").lower()
            if an.endswith("footnoteid") or an == "footnoteid":
                v = (attr_val or "").strip()
                if v and v not in seen:
                    ids.append(v)
                    seen.add(v)
    return ids


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


def _parse_ownership_nature(el: ET.Element) -> tuple[str, Optional[str]]:
    """Extract (ownership_type, ownership_nature_desc) from ownershipNature child."""
    otype = _find_text(el, "ownershipNature/directOrIndirectOwnership/value")
    otype = (otype or "D").upper()[:1]
    nature = _find_text(el, "ownershipNature/natureOfOwnership/value")
    return otype, nature or None


def _parse_non_derivative_transactions(root: ET.Element, footnote_map: Optional[dict[str, str]] = None) -> list[dict]:
    """
    Parse nonDerivativeTable/nonDerivativeTransaction.
    Uses same element paths as working Streamlit reference (transactionShares, transactionPricePerShare,
    transactionAcquiredDisposedCode) with fallbacks for alternate SEC schema names.
    footnote_map: id -> text; if provided, each transaction gets a "footnotes" list of resolved texts.
    """
    footnote_map = footnote_map or {}
    out: list[dict] = []
    for table in root.findall(".//nonDerivativeTable"):
        table_security_title = _find_text(table, "securityTitle/value") or _find_text(table, "securityTitle") or None
        for txn in table.findall("nonDerivativeTransaction"):
            tdate = _find_text(txn, "transactionDate/value")
            tcode = _find_text(txn, "transactionCoding/transactionCode")
            acq_raw = _find_text(
                txn,
                "transactionAmounts/transactionAcquiredDisposedCode/value",
                "transactionAmounts/acquisitionDispositionCode/value",
                "transactionCoding/transactionFormType",
            )
            acq_disp = (acq_raw or "").upper()[:1] if acq_raw else None
            if acq_disp and acq_disp not in ("A", "D"):
                acq_disp = "A" if "A" in (acq_raw or "").upper() else "D" if "D" in (acq_raw or "").upper() else None
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
            footnote_ids = _footnote_ids_for_element(txn)
            footnotes = [footnote_map[i] for i in footnote_ids if i in footnote_map]
            otype, nature = _parse_ownership_nature(txn)
            out.append({
                "transaction_date": tdate,
                "transaction_code": tcode,
                "acq_disp": acq_disp,
                "shares": shares,
                "price": price,
                "value_usd": value_usd,
                "shares_owned_following": shares_following,
                "footnotes": footnotes,
                "security_title": table_security_title,
                "ownership_type": otype,
                "ownership_nature": nature,
            })
    return out


def _parse_non_derivative_holdings(root: ET.Element) -> list[dict]:
    """
    Parse nonDerivativeTable/nonDerivativeHolding (position-only rows, no transaction).
    These rows report sharesOwnedFollowing for indirect ownership entities (trusts, LLCs)
    that had no activity in the filing period but still contribute to total holdings.
    """
    out: list[dict] = []
    for table in root.findall(".//nonDerivativeTable"):
        for hold in table.findall("nonDerivativeHolding"):
            shares_following = _find_float(hold, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
            if shares_following is None:
                continue
            otype, nature = _parse_ownership_nature(hold)
            out.append({
                "shares_owned_following": shares_following,
                "ownership_type": otype,
                "ownership_nature": nature,
            })
    return out


def _parse_derivative_transactions(root: ET.Element, footnote_map: Optional[dict[str, str]] = None) -> list[dict]:
    """
    Parse derivativeTable/derivativeTransaction (Table II).
    Returns list of dicts with same shape as non-derivative where possible, plus:
    is_derivative=True, derivative_security_title, exercise_price for RSU classification.
    """
    footnote_map = footnote_map or {}
    out: list[dict] = []
    for table in root.findall(".//derivativeTable"):
        table_derivative_title = _find_text(table, "securityTitle/value") or _find_text(table, "securityTitle") or None
        for txn in table.findall("derivativeTransaction"):
            tdate = _find_text(txn, "transactionDate/value") or _find_text(txn, "transactionDate")
            tcode = _find_text(txn, "transactionCoding/transactionCode") or _find_text(txn, "transactionCode")
            # Conversion or exercise price of derivative
            exercise_price = _find_float(
                txn,
                "conversionOrExercisePrice/value",
                "conversionOrExercisePrice",
                "exercisePrice/value",
                "exercisePrice",
            )
            acq_raw = _find_text(
                txn,
                "transactionAmounts/transactionAcquiredDisposedCode/value",
                "transactionAmounts/acquisitionDispositionCode/value",
                "transactionCoding/transactionFormType",
            )
            acq_disp = (acq_raw or "").upper()[:1] if acq_raw else None
            if acq_disp and acq_disp not in ("A", "D"):
                acq_disp = "A" if "A" in (acq_raw or "").upper() else "D" if "D" in (acq_raw or "").upper() else None
            # Underlying shares
            shares = _find_float(
                txn,
                "transactionAmounts/shares/value",
                "transactionAmounts/transactionShares/value",
                "underlyingShares/value",
            )
            value_usd = _find_float(txn, "transactionAmounts/value")
            shares_following = _find_float(txn, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
            footnote_ids = _footnote_ids_for_element(txn)
            footnotes = [footnote_map[i] for i in footnote_ids if i in footnote_map]
            derivative_title = _find_text(txn, "securityTitle/value") or _find_text(txn, "securityTitle") or table_derivative_title or ""
            out.append({
                "transaction_date": tdate,
                "transaction_code": tcode,
                "acq_disp": acq_disp,
                "shares": shares,
                "price": exercise_price,
                "value_usd": value_usd,
                "shares_owned_following": shares_following,
                "footnotes": footnotes,
                "security_title": table_derivative_title or derivative_title,
                "is_derivative": True,
                "derivative_security_title": derivative_title or table_derivative_title or "",
                "exercise_price": exercise_price,
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
        "is_ten_percent_owner": False,
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
        d["is_ten_percent_owner"] = _text(r_rel.find("isTenPercentOwner")).upper() == "1"
        d["officer_title"] = _text(r_rel.find("officerTitle")) or None
    return d


def _parse_one_ownership(ownership: ET.Element) -> dict:
    d: dict = {
        "insider_name": "", "insider_cik": "", "is_director": False, "is_officer": False, "is_ten_percent_owner": False, "officer_title": None, "security_title": None,
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
        "is_ten_percent_owner": False,
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
        d["is_ten_percent_owner"] = _text(r_rel.find("isTenPercentOwner")).upper() == "1"
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
    Each transaction is classified (is_10b5_1, is_gift, is_tax_withholding, is_rsu_vest_related)
    from transaction code, footnotes, and same-date transactions.
    Each dict has: accession, company_cik, insider_*, security_title, transaction_*, shares, price,
    value_usd, shares_owned_following, is_10b5_1, is_rsu_vest_related, is_tax_withholding, is_gift,
    classification_confidence, classification_reasoning, xml_url.
    """
    root = ET.fromstring(xml_text)
    for el in root.iter():
        el.tag = _strip_ns(el.tag)
    footnote_map = _collect_footnotes(root)
    ownerships = _parse_ownership_roots(root)

    nd_txns = _parse_non_derivative_transactions(root, footnote_map)
    for t in nd_txns:
        t["is_derivative"] = False
        t["derivative_security_title"] = ""
        t["exercise_price"] = t.get("price")

    nd_holdings = _parse_non_derivative_holdings(root)

    # Compute filing-level total shares_owned_following by aggregating across
    # all ownership buckets (direct + each indirect trust/LLC/entity).
    # Each bucket is identified by (ownership_type, ownership_nature).
    # We take the latest reported position per bucket from both transaction rows
    # and holding-only rows, then sum all buckets for the true total.
    bucket_positions: dict[tuple[str, Optional[str]], float] = {}
    for row in nd_txns + nd_holdings:
        sf = row.get("shares_owned_following")
        if sf is None:
            continue
        bucket_key = (row.get("ownership_type", "D"), row.get("ownership_nature"))
        bucket_positions[bucket_key] = float(sf)

    total_shares_following: Optional[float] = None
    if bucket_positions:
        total_shares_following = sum(bucket_positions.values())

    if total_shares_following is not None:
        for t in nd_txns:
            t["shares_owned_following"] = total_shares_following

    deriv_txns = _parse_derivative_transactions(root, footnote_map)

    if not ownerships:
        ownerships = [{"insider_name": "", "insider_cik": "", "is_director": False, "is_officer": False, "is_ten_percent_owner": False, "officer_title": None, "security_title": None}]
    form_aff10b5_one = _parse_form_level_10b5_1(root)
    full_filing_footnotes = " ".join(footnote_map.values()) if footnote_map else ""

    all_txns = nd_txns + deriv_txns
    for i, t in enumerate(all_txns):
        tdate = t.get("transaction_date")
        same_date = [t2 for j, t2 in enumerate(all_txns) if j != i and t2.get("transaction_date") == tdate]
        classification = classify_transaction(
            t, same_date_txns=same_date, form_aff10b5_one=form_aff10b5_one, full_filing_footnotes=full_filing_footnotes
        )
        t["is_10b5_1"] = classification.get("is_10b5_1", False)
        t["plan_adoption_date"] = classification.get("plan_adoption_date")
        t["is_margin_call_collateral"] = classification.get("is_margin_call_collateral", False)
        t["is_gift"] = classification.get("is_gift", False)
        t["is_tax_withholding"] = classification.get("is_tax_withholding", False)
        t["is_rsu_vest_related"] = classification.get("is_rsu_vest_related", False)
        t["classification_confidence"] = classification.get("classification_confidence", "low")
        t["classification_reasoning"] = classification.get("reasoning", "")

    # Match derivative rows to their Table I counterparts and enrich.
    # A derivative exercise (e.g. RSU vest, code M) appears in both tables on the
    # same date with the same code and similar share count.  We transfer the
    # derivative metadata (title, exercise price, footnotes, classification flags)
    # onto the Table I row so it carries the full context.
    used_deriv: set[int] = set()
    for nd in nd_txns:
        nd_date = nd.get("transaction_date")
        nd_code = (nd.get("transaction_code") or "").upper()
        nd_shares = nd.get("shares")
        best: Optional[int] = None
        for di, dt in enumerate(deriv_txns):
            if di in used_deriv:
                continue
            if dt.get("transaction_date") != nd_date:
                continue
            if (dt.get("transaction_code") or "").upper() != nd_code:
                continue
            dt_shares = dt.get("shares")
            if nd_shares is not None and dt_shares is not None and abs(nd_shares - dt_shares) > 1:
                continue
            best = di
            break
        if best is not None:
            used_deriv.add(best)
            matched = deriv_txns[best]
            nd["derivative_security_title"] = matched.get("derivative_security_title") or ""
            nd["exercise_price"] = matched.get("exercise_price")
            deriv_footnotes = matched.get("footnotes") or []
            existing = nd.get("footnotes") or []
            nd["footnotes"] = existing + [f for f in deriv_footnotes if f not in existing]
            for flag in ("is_10b5_1", "is_rsu_vest_related", "is_tax_withholding",
                         "is_gift", "is_margin_call_collateral"):
                if matched.get(flag):
                    nd[flag] = True
            if matched.get("plan_adoption_date") and not nd.get("plan_adoption_date"):
                nd["plan_adoption_date"] = matched["plan_adoption_date"]
            if matched.get("classification_reasoning"):
                prev = nd.get("classification_reasoning") or ""
                extra = matched["classification_reasoning"]
                if extra not in prev:
                    nd["classification_reasoning"] = f"{prev}; {extra}".strip("; ") if prev else extra

    # Only output Table I (non-derivative) rows.
    meta = ownerships[0]
    result = []
    for t in nd_txns:
        result.append({
            "accession": accession,
            "company_cik": company_cik,
            "insider_cik": meta.get("insider_cik", ""),
            "insider_name": meta.get("insider_name", ""),
            "is_director": meta.get("is_director", False),
            "is_officer": meta.get("is_officer", False),
            "is_ten_percent_owner": meta.get("is_ten_percent_owner", False),
            "officer_title": meta.get("officer_title"),
            "security_title": t.get("security_title") or meta.get("security_title"),
            "transaction_date": t.get("transaction_date"),
            "transaction_code": t.get("transaction_code"),
            "acq_disp": t.get("acq_disp"),
            "shares": t.get("shares"),
            "price": t.get("price"),
            "value_usd": t.get("value_usd"),
            "shares_owned_following": t.get("shares_owned_following"),
            "ownership_type": t.get("ownership_type", "D"),
            "ownership_nature": t.get("ownership_nature"),
            "is_10b5_1": t.get("is_10b5_1"),
            "plan_adoption_date": t.get("plan_adoption_date"),
            "is_margin_call_collateral": t.get("is_margin_call_collateral"),
            "is_gift": t.get("is_gift"),
            "is_tax_withholding": t.get("is_tax_withholding"),
            "is_rsu_vest_related": t.get("is_rsu_vest_related"),
            "is_derivative": False,
            "classification_confidence": t.get("classification_confidence"),
            "classification_reasoning": t.get("classification_reasoning"),
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
