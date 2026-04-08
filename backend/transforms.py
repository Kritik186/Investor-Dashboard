"""Business logic: top 15 insiders, holdings over time, monthly/quarterly aggregations, insider summary."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd


def top_15_insiders(
    transactions: list[dict],
    lookback_days: Optional[int] = 365,
) -> list[dict]:
    """
    Top 15 insiders by shares held on the most recent date.
    When lookback_days is None, use all transactions (top 15 independent of date range).
    Otherwise filter to transactions within lookback, then rank by latest shares in that window.
    """
    if not transactions:
        return []
    cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None
    rows = []
    for t in transactions:
        if t.get("is_derivative"):
            continue
        td = _parse_d(t.get("transaction_date"))
        if not td:
            continue
        if cutoff and td < cutoff:
            continue
        sh = t.get("shares_owned_following")
        if sh is None:
            continue
        rows.append({
            "insider_cik": t.get("insider_cik"),
            "insider_name": t.get("insider_name"),
            "transaction_date": td,
            "shares_owned_following": float(sh),
        })
    if not rows:
        return []
    df = pd.DataFrame(rows)
    idx = df.groupby(["insider_cik", "insider_name"])["transaction_date"].idxmax()
    latest = df.loc[idx].copy()
    latest = latest.rename(columns={"shares_owned_following": "shares_held_recent"})
    latest = latest.sort_values("shares_held_recent", ascending=False).head(15)
    return latest[["insider_cik", "insider_name", "shares_held_recent"]].to_dict("records")


def holdings_over_time(
    transactions: list[dict],
    top_15: list[dict],
    lookback_days: int = 365,
) -> list[dict]:
    """
    For each of top 15 insiders, time series of shares_owned_following at each transaction date.
    Returns list of { insider_cik, insider_name, date, shares_owned_following }. Gaps allowed.
    """
    if not top_15:
        return []
    top_ciks = {r["insider_cik"] for r in top_15}
    cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None
    out = []
    for t in transactions:
        if t.get("is_derivative"):
            continue
        if t.get("insider_cik") not in top_ciks:
            continue
        td = t.get("transaction_date")
        if isinstance(td, str):
            try:
                td = datetime.strptime(td[:10], "%Y-%m-%d").date()
            except Exception:
                continue
        if cutoff and (not td or td < cutoff):
            continue
        sh = t.get("shares_owned_following")
        if sh is not None:
            out.append({
                "insider_cik": t.get("insider_cik"),
                "insider_name": t.get("insider_name"),
                "date": td.isoformat() if td else None,
                "shares_owned_following": float(sh),
            })
    return out


def _parse_d(d: Any) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, date):
        return d
    if isinstance(d, datetime):
        return d.date()
    s = str(d)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def insider_activity_over_time(
    transactions: list[dict],
    insider_cik: str,
    lookback_days: int = 365,
    period: str = "month",
) -> list[dict]:
    """
    For one insider: time series by period of shares_bought, shares_sold, value_bought_usd, value_sold_usd.
    Returns list of { period_end, shares_bought, shares_sold, value_bought_usd, value_sold_usd }.
    """
    try:
        cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None
        rows = []
        for t in transactions:
            if (t.get("insider_cik") or "") != insider_cik:
                continue
            td = _parse_d(t.get("transaction_date"))
            if not td or (cutoff and td < cutoff):
                continue
            acq = (t.get("acq_disp") or "").upper()
            shares = float(t.get("shares") or 0)
            value = t.get("value_usd")
            value_f = float(value) if value is not None else None
            rows.append({
                "transaction_date": td,
                "acq_disp": acq,
                "shares": shares,
                "value_usd": value_f,
            })
        if not rows:
            return []
        df = pd.DataFrame(rows)
        freq = "ME" if period == "month" else "QE"
        try:
            period_ser = pd.to_datetime(df["transaction_date"]).dt.to_period(freq)
        except Exception:
            freq = "M" if period == "month" else "Q"
            period_ser = pd.to_datetime(df["transaction_date"]).dt.to_period(freq)
        df["period_end"] = period_ser.dt.to_timestamp(how="end").dt.date
        bought = df[df["acq_disp"] == "A"].groupby("period_end")["shares"].sum()
        sold = df[df["acq_disp"] == "D"].groupby("period_end")["shares"].sum()
        value_bought = df[df["acq_disp"] == "A"].groupby("period_end")["value_usd"].sum()
        value_sold = df[df["acq_disp"] == "D"].groupby("period_end")["value_usd"].sum()
        periods = sorted(df["period_end"].unique())
        out = []
        for pe in periods:
            pe_str = pe.isoformat()[:10] if hasattr(pe, "isoformat") else str(pe)[:10]
            sb = bought.get(pe, 0)
            ss = sold.get(pe, 0)
            vb = value_bought.get(pe)
            vs = value_sold.get(pe)
            out.append({
                "period_end": pe_str,
                "shares_bought": float(sb),
                "shares_sold": float(ss),
                "value_bought_usd": None if pd.isna(vb) else float(vb),
                "value_sold_usd": None if pd.isna(vs) else float(vs),
            })
        return out
    except Exception:
        return []


def aggregates_monthly_quarterly(
    transactions: list[dict],
    top_15: list[dict],
    lookback_days: int = 365,
    period: str = "month",
    position_before_cutoff: Optional[dict] = None,
    use_synthetic_positions: bool = False,
) -> list[dict]:
    """
    Monthly or quarterly aggregates for top 15: shares_sold, shares_bought, value_sold_usd,
    value_bought_usd, pct_sold.
    When use_synthetic_positions is False: start_shares/end_shares from shares_owned_following
    (actual position from filings). When True (e.g. transaction type filter active): start/end/change
    are computed only from the passed-in transactions (synthetic running balance).
    position_before_cutoff: insider_cik -> shares (last before cutoff, or synthetic sum A-D before cutoff).
    """
    try:
        if not transactions or not top_15:
            return []
        top_ciks = {r["insider_cik"] for r in top_15}
        cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None
        freq = "ME" if period == "month" else "QE"
        rows = []
        for t in transactions:
            if t.get("insider_cik") not in top_ciks:
                continue
            td = _parse_d(t.get("transaction_date"))
            if not td or (cutoff and td < cutoff):
                continue
            shares = t.get("shares")
            value = t.get("value_usd")
            if value is None and shares is not None and t.get("price") is not None:
                try:
                    value = float(shares) * float(t["price"])
                except (TypeError, ValueError):
                    pass
            acq = (t.get("acq_disp") or "").upper()
            following = t.get("shares_owned_following") if not t.get("is_derivative") else None
            t_id = t.get("id")
            is_10b5 = t.get("is_10b5_1")
            tcode = (t.get("transaction_code") or "").strip().upper()
            rows.append({
                "insider_cik": t["insider_cik"],
                "insider_name": t.get("insider_name"),
                "transaction_date": td,
                "transaction_id": t_id if t_id is not None else -1,
                "shares": float(shares) if shares is not None else 0,
                "value_usd": float(value) if value is not None else None,
                "acq_disp": acq,
                "shares_owned_following": float(following) if following is not None else None,
                "is_10b5_1": is_10b5 is True,
                "plan_adoption_date": t.get("plan_adoption_date"),
                "is_margin_call_collateral": t.get("is_margin_call_collateral") is True,
                "transaction_code": tcode or None,
                "officer_title": t.get("officer_title"),
                "is_ten_percent_owner": t.get("is_ten_percent_owner") is True,
                "xml_url": t.get("xml_url"),
            })
        if not rows:
            return []
        df = pd.DataFrame(rows)
        dt_ser = pd.to_datetime(df["transaction_date"])
        try:
            period_ser = dt_ser.dt.to_period(freq)
        except Exception:
            freq = "M" if period == "month" else "Q"
            period_ser = dt_ser.dt.to_period(freq)
        df["period_end"] = period_ser.dt.to_timestamp(how="end").dt.date
        results = []
        for (insider_cik, insider_name), grp in df.groupby(["insider_cik", "insider_name"]):
            grp = grp.sort_values("transaction_date").copy()
            # When using synthetic positions (filtered view), run a running balance per period in order
            if use_synthetic_positions:
                # Filtered view: only selected transaction types; each period uses only txns in that period.
                synthetic_position = float(position_before_cutoff.get(insider_cik, 0) or 0)
                periods_order = sorted(grp["period_end"].unique(), key=lambda x: (x.isoformat() if hasattr(x, "isoformat") else str(x)))
                for period_end in periods_order:
                    pg = grp[grp["period_end"] == period_end].copy()
                    period_date = period_end if isinstance(period_end, date) else (period_end.date() if hasattr(period_end, "date") and callable(getattr(period_end, "date", None)) else period_end)
                    if hasattr(period_date, "replace"):
                        try:
                            if period == "month":
                                period_start_date = period_date.replace(day=1)
                            else:
                                q_start_month = (period_date.month - 1) // 3 * 3 + 1
                                period_start_date = period_date.replace(month=q_start_month, day=1)
                        except Exception:
                            period_start_date = None
                    else:
                        period_start_date = None
                    if period_start_date is not None and not pg.empty:
                        pg_dt = pd.to_datetime(pg["transaction_date"])
                        start_ts = pd.Timestamp(period_start_date)
                        end_ts = pd.Timestamp(period_end)
                        pg = pg[(pg_dt >= start_ts) & (pg_dt <= end_ts)]
                    sold_mask = pg["acq_disp"] == "D"
                    buy_mask = pg["acq_disp"] == "A"
                    shares_sold = float(pg.loc[sold_mask, "shares"].sum())
                    shares_bought = float(pg.loc[buy_mask, "shares"].sum())
                    vs = pg.loc[sold_mask, "value_usd"].sum()
                    vb = pg.loc[buy_mask, "value_usd"].sum()
                    value_sold = None if pd.isna(vs) else float(vs)
                    value_bought = None if pd.isna(vb) else float(vb)
                    start_shares = synthetic_position
                    end_shares = start_shares + shares_bought - shares_sold
                    change_shares = end_shares - start_shares
                    synthetic_position = end_shares
                    has_insufficient = start_shares is None or (isinstance(start_shares, (int, float)) and start_shares == 0)
                    pct_sold = None if has_insufficient else (float(shares_sold) / float(start_shares) if start_shares else None)
                    pct_sold_label = "insufficient data" if has_insufficient else None
                    pe_str = str(period_end)[:10] if period_end else ""
                    if hasattr(period_end, "isoformat"):
                        try:
                            pe_str = period_end.isoformat()[:10]
                        except Exception:
                            pe_str = str(period_end)[:10]
                    ps_str = period_start_date.isoformat()[:10] if period_start_date and hasattr(period_start_date, "isoformat") else ""
                    n_10b5 = int((pg["is_10b5_1"] == True).sum()) if "is_10b5_1" in pg.columns else 0
                    n_total = len(pg)
                    period_10b5_1_status = "all" if n_total and n_10b5 == n_total else ("mixed" if n_10b5 else "none")
                    # All distinct 10b5-1 plan adoption dates in this period (multiple filings can have different dates)
                    plan_adoption_date_val = None
                    if "plan_adoption_date" in pg.columns:
                        non_null = pg["plan_adoption_date"].dropna().astype(str).str.strip()
                        unique_dates = sorted(non_null[non_null != ""].unique())
                        if unique_dates:
                            plan_adoption_date_val = ", ".join(unique_dates)
                    is_margin_call_collateral_val = bool((pg["is_margin_call_collateral"] == True).any()) if "is_margin_call_collateral" in pg.columns else False
                    tcode_col = pg.get("transaction_code") if "transaction_code" in pg.columns else None
                    has_rsu_vest = bool((tcode_col == "M").any()) if tcode_col is not None else False
                    has_tax_withholding = bool((tcode_col == "F").any()) if tcode_col is not None else False
                    has_gift = bool((tcode_col == "G").any()) if tcode_col is not None else False
                    first_row = pg.iloc[0] if not pg.empty else None
                    officer_title = first_row.get("officer_title") if first_row is not None and hasattr(first_row, "get") else None
                    is_ten_percent_owner = bool(first_row.get("is_ten_percent_owner", False)) if first_row is not None and hasattr(first_row, "get") else False
                    # One entry per filing (xml_url): sum shares from selected transactions in this period
                    dispositions = []
                    if not pg.empty and "xml_url" in pg.columns:
                        pg_sorted = pg.sort_values("transaction_date")
                        for url in pg_sorted["xml_url"].dropna().unique():
                            subset = pg_sorted[pg_sorted["xml_url"] == url]
                            total_shares = float(subset["shares"].sum())
                            first_d = subset.iloc[0].get("transaction_date")
                            td_str = first_d.isoformat()[:10] if hasattr(first_d, "isoformat") else str(first_d)[:10] if first_d else ""
                            disp_margin = bool((subset["is_margin_call_collateral"] == True).any()) if "is_margin_call_collateral" in subset.columns else False
                            dispositions.append({"transaction_date": td_str, "shares": total_shares, "xml_url": url, "is_margin_call_collateral": disp_margin})
                    results.append({
                        "insider_cik": insider_cik,
                        "insider_name": insider_name,
                        "period_start": ps_str,
                        "period_end": pe_str,
                        "shares_sold": shares_sold,
                        "shares_bought": shares_bought,
                        "value_sold_usd": value_sold,
                        "value_bought_usd": value_bought,
                        "start_shares": float(start_shares) if start_shares is not None else None,
                        "end_shares": float(end_shares) if end_shares is not None else None,
                        "change_shares": float(change_shares) if change_shares is not None else None,
                        "pct_sold": pct_sold,
                        "pct_sold_label": pct_sold_label,
                        "period_10b5_1_status": period_10b5_1_status,
                        "plan_adoption_date": plan_adoption_date_val,
                        "is_margin_call_collateral": is_margin_call_collateral_val,
                        "has_rsu_vest": has_rsu_vest,
                        "has_tax_withholding": has_tax_withholding,
                        "has_gift": has_gift,
                        "officer_title": officer_title,
                        "is_ten_percent_owner": is_ten_percent_owner,
                        "dispositions": dispositions,
                    })
                continue
            # Non-synthetic path (no filter or legacy)
            position_at_start_of_range = None
            first_period_end = None
            if not grp.empty:
                first_row = grp.iloc[0]
                following = first_row.get("shares_owned_following")
                sh = first_row.get("shares") or 0
                acq = (first_row.get("acq_disp") or "").upper()
                if following is not None and sh is not None:
                    if acq == "D":
                        position_at_start_of_range = float(following) + float(sh)
                    else:
                        position_at_start_of_range = float(following) - float(sh)
                first_period_end = first_row.get("period_end")
            for period_end, pg in grp.groupby("period_end"):
                sold_mask = pg["acq_disp"] == "D"
                buy_mask = pg["acq_disp"] == "A"
                shares_sold = float(pg.loc[sold_mask, "shares"].sum())
                shares_bought = float(pg.loc[buy_mask, "shares"].sum())
                vs = pg.loc[sold_mask, "value_usd"].sum()
                vb = pg.loc[buy_mask, "value_usd"].sum()
                value_sold = None if pd.isna(vs) else float(vs)
                value_bought = None if pd.isna(vb) else float(vb)
                if isinstance(period_end, date):
                    period_date = period_end
                elif hasattr(period_end, "date") and callable(getattr(period_end, "date", None)):
                    period_date = period_end.date()
                else:
                    period_date = period_end
                period_start_date = None
                if period_date:
                    try:
                        d = period_date.date() if hasattr(period_date, "date") and callable(getattr(period_date, "date", None)) else period_date
                        if hasattr(d, "replace"):
                            if period == "month":
                                period_start_date = d.replace(day=1)
                            else:
                                q_start_month = (d.month - 1) // 3 * 3 + 1
                                period_start_date = d.replace(month=q_start_month, day=1)
                    except Exception:
                        pass
                grp_dt = pd.to_datetime(grp["transaction_date"])
                before = grp[grp_dt < pd.Timestamp(period_start_date)] if period_start_date else pd.DataFrame()
                start_shares = None
                if not pg.empty:
                    first_in_period = pg.sort_values(["transaction_date", "transaction_id"]).iloc[0]
                    following = first_in_period.get("shares_owned_following")
                    sh = first_in_period.get("shares") or 0
                    acq = (first_in_period.get("acq_disp") or "").upper()
                    if following is not None and sh is not None:
                        if acq == "D":
                            start_shares = float(following) + float(sh)
                        else:
                            start_shares = float(following) - float(sh)
                if start_shares is None and not before.empty:
                    last_row = before.sort_values(["transaction_date", "transaction_id"]).iloc[-1]
                    start_shares = last_row.get("shares_owned_following")
                if start_shares is None and position_before_cutoff and insider_cik in position_before_cutoff:
                    start_shares = position_before_cutoff.get(insider_cik)
                if start_shares is None and position_at_start_of_range is not None and first_period_end is not None:
                    if str(period_end)[:10] == str(first_period_end)[:10]:
                        start_shares = position_at_start_of_range
                end_shares = None
                if not pg.empty:
                    last_in_period = pg.sort_values(["transaction_date", "transaction_id"]).iloc[-1]
                    end_shares = last_in_period.get("shares_owned_following")
                change_shares = None
                if start_shares is not None and end_shares is not None:
                    change_shares = float(end_shares) - float(start_shares)
                has_insufficient = start_shares is None or (isinstance(start_shares, (int, float)) and start_shares == 0)
                pct_sold = None if has_insufficient else float(shares_sold) / float(start_shares)
                pct_sold_label = "insufficient data" if has_insufficient else None
                pe_str = str(period_end)[:10] if period_end else ""
                if hasattr(period_end, "isoformat"):
                    try:
                        pe_str = period_end.isoformat()[:10]
                    except Exception:
                        pe_str = str(period_end)[:10]
                ps_str = period_start_date.isoformat()[:10] if period_start_date and hasattr(period_start_date, "isoformat") else ""
                n_10b5 = int((pg["is_10b5_1"] == True).sum()) if "is_10b5_1" in pg.columns else 0
                n_total = len(pg)
                period_10b5_1_status = "all" if n_total and n_10b5 == n_total else ("mixed" if n_10b5 else "none")
                # All distinct 10b5-1 plan adoption dates in this period (multiple filings can have different dates)
                plan_adoption_date_val = None
                if "plan_adoption_date" in pg.columns:
                    non_null = pg["plan_adoption_date"].dropna().astype(str).str.strip()
                    unique_dates = sorted(non_null[non_null != ""].unique())
                    if unique_dates:
                        plan_adoption_date_val = ", ".join(unique_dates)
                is_margin_call_collateral_val = bool((pg["is_margin_call_collateral"] == True).any()) if "is_margin_call_collateral" in pg.columns else False
                # Low-signal: RSU vest (M), tax withholding (F), gift (G), 10b5-1
                tcode_col = pg.get("transaction_code") if "transaction_code" in pg.columns else None
                has_rsu_vest = bool((tcode_col == "M").any()) if tcode_col is not None else False
                has_tax_withholding = bool((tcode_col == "F").any()) if tcode_col is not None else False
                has_gift = bool((tcode_col == "G").any()) if tcode_col is not None else False
                first_row = pg.iloc[0] if not pg.empty else None
                officer_title = first_row.get("officer_title") if first_row is not None and hasattr(first_row, "get") else None
                is_ten_percent_owner = bool(first_row.get("is_ten_percent_owner", False)) if first_row is not None and hasattr(first_row, "get") else False
                # One entry per filing (xml_url): sum shares from transactions in this period
                dispositions = []
                if not pg.empty and "xml_url" in pg.columns:
                    pg_sorted = pg.sort_values("transaction_date")
                    for url in pg_sorted["xml_url"].dropna().unique():
                        subset = pg_sorted[pg_sorted["xml_url"] == url]
                        total_shares = float(subset["shares"].sum())
                        first_d = subset.iloc[0].get("transaction_date")
                        td_str = first_d.isoformat()[:10] if hasattr(first_d, "isoformat") else str(first_d)[:10] if first_d else ""
                        disp_margin = bool((subset["is_margin_call_collateral"] == True).any()) if "is_margin_call_collateral" in subset.columns else False
                        dispositions.append({"transaction_date": td_str, "shares": total_shares, "xml_url": url, "is_margin_call_collateral": disp_margin})
                results.append({
                    "insider_cik": insider_cik,
                    "insider_name": insider_name,
                    "period_start": ps_str,
                    "period_end": pe_str,
                    "shares_sold": shares_sold,
                    "shares_bought": shares_bought,
                    "value_sold_usd": value_sold,
                    "value_bought_usd": value_bought,
                    "start_shares": float(start_shares) if start_shares is not None else None,
                    "end_shares": float(end_shares) if end_shares is not None else None,
                    "change_shares": float(change_shares) if change_shares is not None else None,
                    "pct_sold": pct_sold,
                    "pct_sold_label": pct_sold_label,
                    "period_10b5_1_status": period_10b5_1_status,
                    "plan_adoption_date": plan_adoption_date_val,
                    "is_margin_call_collateral": is_margin_call_collateral_val,
                    "has_rsu_vest": has_rsu_vest,
                    "has_tax_withholding": has_tax_withholding,
                    "has_gift": has_gift,
                    "officer_title": officer_title,
                    "is_ten_percent_owner": is_ten_percent_owner,
                    "dispositions": dispositions,
                })
        return results
    except Exception:
        return []


def _is_core_transaction(t: dict) -> bool:
    """Core = open-market P or S with none of the classification flags set."""
    code = (t.get("transaction_code") or "").strip().upper()
    if code not in ("P", "S"):
        return False
    if t.get("is_10b5_1") is True:
        return False
    if t.get("is_rsu_vest_related") is True:
        return False
    if t.get("is_tax_withholding") is True:
        return False
    if t.get("is_gift") is True:
        return False
    return True


def insider_summary(
    transactions: list[dict],
    lookback_days: int = 365,
) -> dict:
    """
    Build the insider summary table data: one row per insider (top 15 by shares held),
    with core/non-core splits, BoP/EoP, and cluster detection.
    Returns {"insiders": [...], "cluster_periods": [...]}.
    """
    if not transactions:
        return {"insiders": [], "cluster_periods": []}

    top = top_15_insiders(transactions, lookback_days=lookback_days)
    if not top:
        return {"insiders": [], "cluster_periods": []}

    top_ciks = {r["insider_cik"] for r in top}
    cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None

    filtered: list[dict] = []
    for t in transactions:
        if t.get("insider_cik") not in top_ciks:
            continue
        td = _parse_d(t.get("transaction_date"))
        if not td or (cutoff and td < cutoff):
            continue
        filtered.append({**t, "_td": td})

    if not filtered:
        return {"insiders": [], "cluster_periods": []}

    by_insider: dict[str, list[dict]] = defaultdict(list)
    for t in filtered:
        by_insider[t["insider_cik"]].append(t)

    seller_months: dict[str, dict[str, str]] = defaultdict(dict)  # month -> {cik: name}

    insiders_out = []
    for top_row in top:
        cik = top_row["insider_cik"]
        name = top_row["insider_name"]
        txns = sorted(by_insider.get(cik, []), key=lambda x: (x["_td"], x.get("id") or 0))
        if not txns:
            continue

        non_deriv = [t for t in txns if not t.get("is_derivative")]

        bop_shares: float | None = None
        if non_deriv:
            first_nd = non_deriv[0]
            following_first = first_nd.get("shares_owned_following")
            sh_first = float(first_nd.get("shares") or 0)
            acq_first = (first_nd.get("acq_disp") or "").upper()
            if following_first is not None:
                bop_shares = float(following_first) + sh_first if acq_first == "D" else float(following_first) - sh_first

        eop_shares: float | None = None
        if non_deriv:
            last_nd = non_deriv[-1]
            eop_shares = float(last_nd["shares_owned_following"]) if last_nd.get("shares_owned_following") is not None else None

        officer_title = None
        is_director = False
        is_officer = False
        is_ten_percent_owner = False
        for t in txns:
            if t.get("officer_title"):
                officer_title = t["officer_title"]
            if t.get("is_director"):
                is_director = True
            if t.get("is_officer"):
                is_officer = True
            if t.get("is_ten_percent_owner"):
                is_ten_percent_owner = True

        buys_usd = 0.0
        buys_shares = 0.0
        sales_total_usd = 0.0
        sales_total_shares = 0.0
        sales_core_usd = 0.0
        sales_core_shares = 0.0
        sales_non_core_usd = 0.0
        sales_non_core_shares = 0.0
        buys_core_usd = 0.0
        buys_core_shares = 0.0

        for t in txns:
            acq = (t.get("acq_disp") or "").upper()
            shares = float(t.get("shares") or 0)
            value = t.get("value_usd")
            if value is None and t.get("price") is not None:
                try:
                    value = shares * float(t["price"])
                except (TypeError, ValueError):
                    value = None
            val = float(value) if value is not None else 0.0
            core = _is_core_transaction(t)

            if acq == "A":
                buys_usd += val
                buys_shares += shares
                if core:
                    buys_core_usd += val
                    buys_core_shares += shares
            elif acq == "D":
                sales_total_usd += val
                sales_total_shares += shares
                month_key = t["_td"].strftime("%Y-%m")
                seller_months[month_key][cik] = name
                if core:
                    sales_core_usd += val
                    sales_core_shares += shares
                else:
                    sales_non_core_usd += val
                    sales_non_core_shares += shares

        avg_cost_buys = buys_usd / buys_shares if buys_shares else None
        avg_cost_core_sales = sales_core_usd / sales_core_shares if sales_core_shares else None
        purchases_pct_bop = buys_shares / bop_shares if bop_shares and bop_shares > 0 else None
        sales_pct_bop = sales_total_shares / bop_shares if bop_shares and bop_shares > 0 else None
        sales_non_core_pct = sales_non_core_usd / sales_total_usd if sales_total_usd > 0 else None

        net_core = buys_core_usd - sales_core_usd
        if net_core > 0:
            net_label = "Buyer"
        elif net_core < 0:
            net_label = "Seller"
        else:
            net_label = "Neutral"

        insiders_out.append({
            "insider_cik": cik,
            "insider_name": name,
            "officer_title": officer_title,
            "is_director": is_director,
            "is_officer": is_officer,
            "is_ten_percent_owner": is_ten_percent_owner,
            "bop_shares": bop_shares,
            "eop_shares": eop_shares,
            "pct_owner_post_sales": None,  # computed after loop
            "buys_usd": buys_usd,
            "buys_shares": buys_shares,
            "buys_core_shares": buys_core_shares,
            "buys_non_core_shares": buys_shares - buys_core_shares,
            "avg_cost_basis_buys": avg_cost_buys,
            "purchases_pct_bop": purchases_pct_bop,
            "sales_total_usd": sales_total_usd,
            "sales_total_shares": sales_total_shares,
            "sales_core_usd": sales_core_usd,
            "sales_core_shares": sales_core_shares,
            "avg_cost_basis_core_sales": avg_cost_core_sales,
            "sales_pct_bop": sales_pct_bop,
            "sales_non_core_usd": sales_non_core_usd,
            "sales_non_core_shares": sales_non_core_shares,
            "sales_non_core_pct_total": sales_non_core_pct,
            "net_buyer_or_seller": net_label,
        })

    total_eop = sum(r.get("eop_shares") or 0 for r in insiders_out)
    if total_eop > 0:
        for r in insiders_out:
            eop = r.get("eop_shares") or 0
            r["pct_owner_post_sales"] = eop / total_eop if eop else 0.0
    else:
        for r in insiders_out:
            r["pct_owner_post_sales"] = None

    cluster_periods = sorted(
        [
            {"period": m, "sellers": sorted(cik_names.values())}
            for m, cik_names in seller_months.items()
            if len(cik_names) >= 3
        ],
        key=lambda x: x["period"],
    )

    return {"insiders": insiders_out, "cluster_periods": cluster_periods}
