"""Business logic: top 15 insiders, holdings over time, monthly/quarterly aggregations."""

from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd


def top_15_insiders(
    transactions: list[dict],
    lookback_days: int = 365,
) -> list[dict]:
    """
    Top 15 insiders by total ABS(value_usd) over lookback. If value_usd missing, use ABS(shares).
    """
    if not transactions:
        return []
    cutoff = (date.today() - timedelta(days=lookback_days)) if lookback_days else None
    rows = []
    for t in transactions:
        td = t.get("transaction_date")
        if isinstance(td, str):
            try:
                td = datetime.strptime(td[:10], "%Y-%m-%d").date()
            except Exception:
                continue
        if cutoff and (not td or td < cutoff):
            continue
        val = t.get("value_usd")
        if val is None:
            sh = t.get("shares")
            val = abs(sh) if sh is not None else 0
        else:
            val = abs(float(val))
        rows.append({
            "insider_cik": t.get("insider_cik"),
            "insider_name": t.get("insider_name"),
            "total_abs_value_usd": val,
        })
    if not rows:
        return []
    df = pd.DataFrame(rows)
    agg = df.groupby(["insider_cik", "insider_name"], dropna=False).agg(total_abs_value_usd=("total_abs_value_usd", "sum")).reset_index()
    agg = agg.sort_values("total_abs_value_usd", ascending=False).head(15)
    return agg.to_dict("records")


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
) -> list[dict]:
    """
    Monthly or quarterly aggregates for top 15: shares_sold, shares_bought, value_sold_usd,
    value_bought_usd, pct_sold. start_shares = previous known shares_owned_following before period;
    if missing, pct_sold = null and label "insufficient data".
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
            acq = (t.get("acq_disp") or "").upper()
            following = t.get("shares_owned_following")
            rows.append({
                "insider_cik": t["insider_cik"],
                "insider_name": t.get("insider_name"),
                "transaction_date": td,
                "shares": float(shares) if shares is not None else 0,
                "value_usd": float(value) if value is not None else None,
                "acq_disp": acq,
                "shares_owned_following": float(following) if following is not None else None,
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
                grp_dt = pd.to_datetime(grp["transaction_date"])
                before = grp[grp_dt < pd.Timestamp(period_date)]
                start_shares = None
                if not before.empty:
                    last_row = before.iloc[-1]
                    start_shares = last_row.get("shares_owned_following")
                if start_shares is None or (isinstance(start_shares, (int, float)) and start_shares == 0):
                    pct_sold = None
                    pct_sold_label = "insufficient data"
                else:
                    pct_sold = float(shares_sold) / float(start_shares)
                    pct_sold_label = None
                pe_str = str(period_end)[:10] if period_end else ""
                if hasattr(period_end, "isoformat"):
                    try:
                        pe_str = period_end.isoformat()[:10]
                    except Exception:
                        pe_str = str(period_end)[:10]
                results.append({
                    "insider_cik": insider_cik,
                    "insider_name": insider_name,
                    "period_end": pe_str,
                    "shares_sold": shares_sold,
                    "shares_bought": shares_bought,
                    "value_sold_usd": value_sold,
                    "value_bought_usd": value_bought,
                    "start_shares": float(start_shares) if start_shares is not None else None,
                    "pct_sold": pct_sold,
                    "pct_sold_label": pct_sold_label,
                })
        return results
    except Exception:
        return []
