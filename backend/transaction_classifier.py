"""
Classify each Form 4 transaction with explicit booleans:
- is_10b5_1, is_gift, is_tax_withholding, is_rsu_vest_related
Plus plan_adoption_date (10b5-1), is_margin_call_collateral, classification_confidence, reasoning.
"""

import re
from datetime import datetime
from typing import Any, Optional


def _footnote_text_lower(txn: dict) -> str:
    """Single normalized string of all footnote text for this transaction."""
    footnotes = txn.get("footnotes") or []
    return " ".join((f or "").lower() for f in footnotes)


def _security_title_lower(txn: dict) -> str:
    return (txn.get("security_title") or "").lower()


def _has_phrase(text: str, *phrases: str) -> bool:
    t = (text or "").lower()
    return any(p.lower() in t for p in phrases)


# Patterns for "adopted [optional words] on <date>" in footnote text (case-insensitive)
_ADOPTED_ON_PATTERNS = [
    re.compile(r"adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),   # November 18, 2024 or Nov 18 2024
    re.compile(r"adopted\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),            # 11/18/2024
    re.compile(r"adopted\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),                # 2024-11-18
    re.compile(r"adopted\s+on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),            # 11-18-2024
    re.compile(r"plan\s+adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"trading\s+plan\s+adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"10b5-1\s+plan\s+adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    # "adopted by the reporting person on 11/18/2024" and similar
    re.compile(r"adopted\s+by\s+[^.]*?\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"adopted\s+by\s+[^.]*?\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"adopted\s+by\s+[^.]*?\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"adopted\s+.+?\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),   # adopted ... on mm/dd/yyyy
    re.compile(r"adopted\s+.+?\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"adopted\s+.+?\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
]

_DATE_FORMATS = [
    "%B %d, %Y",   # November 18, 2024
    "%b %d, %Y",   # Nov 18, 2024
    "%B %d %Y",    # November 18 2024
    "%b %d %Y",    # Nov 18 2024
    "%m/%d/%Y",    # 11/18/2024
    "%Y-%m-%d",    # 2024-11-18
    "%m-%d-%Y",    # 11-18-2024
]


def _parse_adoption_date(footnote_text: str) -> Optional[str]:
    """Extract 10b5-1 plan adoption date from footnote text; return ISO YYYY-MM-DD or None."""
    if not footnote_text or not isinstance(footnote_text, str):
        return None
    text = footnote_text.strip()
    for pat in _ADOPTED_ON_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        date_str = m.group(1).strip()
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def classify_transaction(
    txn: dict,
    same_date_txns: Optional[list[dict]] = None,
    form_aff10b5_one: Optional[bool] = None,
) -> dict[str, Any]:
    """
    Classify one transaction. Returns dict with:
    is_10b5_1, is_rsu_vest_related, is_tax_withholding, is_gift,
    classification_confidence ("high"|"medium"|"low"), reasoning.
    """
    same_date_txns = same_date_txns or []
    code = (txn.get("transaction_code") or "").strip().upper()
    acq_disp = (txn.get("acq_disp") or "").upper()
    price = txn.get("price")
    footnote_text = _footnote_text_lower(txn)
    security_title = _security_title_lower(txn)
    reasons: list[str] = []

    # --- 1. 10b5-1 ---
    # From footnotes linked to this transaction, or from form-level Rule 10b5-1(c) indicator when footnotes are missing.
    is_10b5_1 = False
    if _has_phrase(
        footnote_text,
        "10b5-1",
        "rule 10b5-1",
        "10b5-1 trading plan",
        "trading plan intended to satisfy rule 10b5-1",
    ):
        is_10b5_1 = True
        reasons.append("footnote linked to transaction mentions 10b5-1 / Rule 10b5-1")
    # Form-level 10b5-1 applies to dispositions (sales) only; don't mark acquisitions (M, A, etc.) as 10b5-1.
    if form_aff10b5_one and not is_10b5_1 and acq_disp == "D":
        is_10b5_1 = True
        reasons.append("form-level Rule 10b5-1(c) indicator (aff10b5One); disposition only")

    # --- 1b. 10b5-1 plan adoption date (from footnotes) ---
    plan_adoption_date = _parse_adoption_date(footnote_text) if footnote_text else None
    if plan_adoption_date and is_10b5_1:
        reasons.append(f"plan adoption date: {plan_adoption_date}")

    # --- 1c. Sale due to margin call / collateral ---
    is_margin_call_collateral = False
    if _has_phrase(footnote_text, "margin call", "collateral"):
        is_margin_call_collateral = True
        reasons.append("footnote indicates margin call or collateral")

    # --- 2. Gift ---
    is_gift = False
    if code == "G":
        is_gift = True
        reasons.append("transaction_code=G (gift)")
    if _has_phrase(footnote_text, "gift", "transfer to family", "charitable", "donation", "transferred to"):
        is_gift = True
        reasons.append("footnote indicates gift/transfer/charitable")

    # --- 3. Tax withholding ---
    is_tax_withholding = False
    if code == "F":
        is_tax_withholding = True
        reasons.append("transaction_code=F (tax withholding)")
    if _has_phrase(
        footnote_text,
        "withheld to satisfy tax",
        "tax withholding",
        "withheld for tax",
        "retained to satisfy",
        "surrendered to satisfy tax",
        "net-share settlement",
        "withholding obligation",
    ):
        is_tax_withholding = True
        reasons.append("footnote indicates tax withholding/surrender")

    # --- 4. RSU vest / vest-related sale ---
    is_rsu_vest_related = False
    if _has_phrase(
        footnote_text,
        "rsu",
        "restricted stock unit",
        "vesting",
        "settlement of rsu",
        "vested",
        "settlement of restricted",
        "sold to cover taxes arising from vesting",
        "sold to cover taxes on vesting",
    ):
        is_rsu_vest_related = True
        reasons.append("footnote mentions RSU/vesting/settlement")
    # Same-day pattern: A or M at price 0 (vest/award) plus S or F (sale/disposition) -> mark disposition as vest-related
    if not is_rsu_vest_related and same_date_txns:
        has_zero_acquisition = any(
            (t.get("transaction_code") or "").strip().upper() in ("A", "M")
            and (t.get("price") is None or t.get("price") == 0)
            for t in same_date_txns
        )
        is_disposition = acq_disp == "D" or code in ("S", "F")
        if has_zero_acquisition and is_disposition:
            # Optional: only if we have some RSU-like footnote elsewhere on same day to avoid false positives
            for t in same_date_txns:
                if _has_phrase(_footnote_text_lower(t), "rsu", "restricted stock", "vest"):
                    is_rsu_vest_related = True
                    reasons.append("same-date vest (A/M @ 0) + disposition with RSU/vest footnote")
                    break
    # F with vesting footnote already covered above; F alone is tax withholding, not necessarily RSU unless footnote says so

    # Confidence
    if reasons:
        classification_confidence = "high" if any(
            "transaction_code=" in r or "footnote" in r for r in reasons
        ) else "medium"
    else:
        classification_confidence = "low"

    reasoning = "; ".join(reasons) if reasons else "No explicit code or footnote clues; left all labels false."

    return {
        "is_10b5_1": is_10b5_1,
        "plan_adoption_date": plan_adoption_date,
        "is_margin_call_collateral": is_margin_call_collateral,
        "is_gift": is_gift,
        "is_tax_withholding": is_tax_withholding,
        "is_rsu_vest_related": is_rsu_vest_related,
        "classification_confidence": classification_confidence,
        "reasoning": reasoning,
    }


def classification_to_json(
    transaction_id: str,
    transaction_code: Optional[str],
    classification: dict[str, Any],
) -> dict[str, Any]:
    """Format classification as the requested JSON shape (one object per transaction)."""
    return {
        "transaction_id": transaction_id,
        "transaction_code": transaction_code or "",
        "is_rsu_vest_related": classification.get("is_rsu_vest_related", False),
        "is_tax_withholding": classification.get("is_tax_withholding", False),
        "is_gift": classification.get("is_gift", False),
        "is_10b5_1": classification.get("is_10b5_1", False),
        "classification_confidence": classification.get("classification_confidence", "low"),
        "reasoning": classification.get("reasoning", ""),
    }
