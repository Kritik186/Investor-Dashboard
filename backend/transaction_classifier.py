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


# Patterns for adoption date: "adopted on", "trading plan adopted on", "plan adopted on", "10b5-1 plan adopted on"
# (case-insensitive). Capture date and convert to ISO YYYY-MM-DD.
_ADOPTED_ON_PATTERNS = [
    # "adopted on <date>"
    re.compile(r"adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"adopted\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"adopted\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"adopted\s+on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),
    # "trading plan adopted on <date>"
    re.compile(r"trading\s+plan\s+adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"trading\s+plan\s+adopted\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"trading\s+plan\s+adopted\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"trading\s+plan\s+adopted\s+on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),
    # "plan adopted on <date>"
    re.compile(r"plan\s+adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"plan\s+adopted\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"plan\s+adopted\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"plan\s+adopted\s+on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),
    # "10b5-1 plan adopted on <date>" (and "10b5-1" / "rule 10b5-1" variants)
    re.compile(r"10b5-1\s+plan\s+adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"10b5-1\s+plan\s+adopted\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"10b5-1\s+plan\s+adopted\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"10b5-1\s+plan\s+adopted\s+on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),
    re.compile(r"rule\s+10b5-1\s+.*?adopted\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"rule\s+10b5-1\s+.*?adopted\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    # "adopted by the reporting person on <date>" and other "adopted ... on <date>"
    re.compile(r"adopted\s+by\s+[^.]*?\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"adopted\s+by\s+[^.]*?\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"adopted\s+by\s+[^.]*?\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"adopted\s+.+?\s+on\s+(\d{1,2}/\d{1,2}/\d{4})", re.I),
    re.compile(r"adopted\s+.+?\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"adopted\s+.+?\s+on\s+(\d{4}-\d{2}-\d{2})", re.I),
    re.compile(r"adopted\s+.+?\s+on\s+(\d{1,2}-\d{1,2}-\d{4})", re.I),
]

_DATE_FORMATS = [
    "%B %d, %Y",   # November 18, 2024
    "%b %d, %Y",   # Nov 18, 2024
    "%B %d %Y",    # November 18 2024
    "%b %d %Y",    # Nov 18 2024
    "%m/%d/%Y",    # 11/18/2024 (US)
    "%d/%m/%Y",    # 18/11/2024 (day-first)
    "%Y-%m-%d",    # 2024-11-18 (ISO input)
    "%m-%d-%Y",    # 11-18-2024
    "%d-%m-%Y",    # 18-11-2024
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
    full_filing_footnotes: Optional[str] = None,
) -> dict[str, Any]:
    """
    Classify one transaction. Returns dict with:
    is_10b5_1, is_rsu_vest_related, is_tax_withholding, is_gift,
    classification_confidence ("high"|"medium"|"low"), reasoning.
    full_filing_footnotes: when the transaction has no linked footnotes, use this to try to extract adoption date.
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

    # --- 1b. 10b5-1 plan adoption date: transaction footnotes first, then all filing footnotes (for table-level notes) ---
    plan_adoption_date = _parse_adoption_date(footnote_text) if footnote_text else None
    if plan_adoption_date is None and full_filing_footnotes:
        plan_adoption_date = _parse_adoption_date(full_filing_footnotes)
    if plan_adoption_date and not is_10b5_1:
        plan_adoption_date = None  # only attach to 10b5-1 transactions
    if plan_adoption_date and is_10b5_1:
        reasons.append(f"plan adoption date: {plan_adoption_date}")

    # --- 1c. Sale due to margin call / collateral (explicit phrases only; no inference) ---
    _MARGIN_COLLATERAL_PHRASES = (
        "margin call",
        "margin requirements",
        "forced sale",
        "sale by broker",
        "collateral",
        "pledged shares",
        "margin loan",
    )
    combined_footnote_text = f"{(footnote_text or '').strip()} {(full_filing_footnotes or '').strip()}".strip()
    is_margin_call_collateral = _has_phrase(combined_footnote_text, *_MARGIN_COLLATERAL_PHRASES)
    if is_margin_call_collateral:
        reasons.append("footnote indicates margin call or collateral (explicit phrase)")

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

    # --- 4. RSU vest detection ---
    # Primary: derivative row with title containing "Restricted", code M, exercise price 0
    # Fallback: any row with code M and price 0 (Table I after derivative exercise)
    is_rsu_vest_related = False
    is_derivative = txn.get("is_derivative") is True
    derivative_title = (txn.get("derivative_security_title") or "").strip()
    exercise_price = txn.get("exercise_price")
    if is_derivative and "restricted" in derivative_title.lower():
        if code == "M" and (exercise_price is None or exercise_price == 0):
            is_rsu_vest_related = True
            reasons.append("derivative table; security title contains Restricted; transactionCode=M; exercisePrice=0")
    elif not is_derivative and code == "M":
        txn_price = txn.get("price")
        if txn_price is None or txn_price == 0:
            is_rsu_vest_related = True
            reasons.append("transactionCode=M; price=$0 (derivative exercise / RSU vest)")

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
