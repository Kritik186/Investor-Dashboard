"""Business logic: top 15 insiders, holdings over time, monthly/quarterly aggregations."""

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
) -> list[dict]:
    """
    Monthly or quarterly aggregates for top 15: shares_sold, shares_bought, value_sold_usd,
    value_bought_usd, pct_sold. start_shares = previous known shares_owned_following before period
    (within range, or from position_before_cutoff when no prior txns in range); if missing,
    pct_sold = null and label "insufficient data".
    position_before_cutoff: optional dict insider_cik -> shares_owned_following (last before cutoff).
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
            following = t.get("shares_owned_following")
            t_id = t.get("id")
            is_10b5 = t.get("is_10b5_1")
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
            # Fallback when no data before cutoff (e.g. 3Y lookback but DB has <3Y): back out position at start of range from earliest txn
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
                # One link per unique filing (xml_url); include both acquisitions and dispositions
                seen_urls = set()
                dispositions = []
                for _, row in pg.sort_values("transaction_date").iterrows():
                    url = row.get("xml_url")
                    if url and url in seen_urls:
                        continue
                    if url:
                        seen_urls.add(url)
                    d = row.get("transaction_date")
                    td_str = d.isoformat()[:10] if hasattr(d, "isoformat") else str(d)[:10] if d else ""
                    dispositions.append({
                        "transaction_date": td_str,
                        "shares": float(row.get("shares", 0)),
                        "xml_url": url,
                    })
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
                    "dispositions": dispositions,
                })
        return results
    except Exception:
        return []
