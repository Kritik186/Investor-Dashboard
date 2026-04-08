"""SQLModel data models for companies, insiders, filings, transactions."""

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Company(SQLModel, table=True):
    __tablename__ = "companies"
    ticker: str = Field(primary_key=True)
    cik10: str = Field(index=True)
    name: str
    last_refresh: Optional[datetime] = None


class Insider(SQLModel, table=True):
    __tablename__ = "insiders"
    insider_cik: str = Field(primary_key=True)
    name: str


class Filing(SQLModel, table=True):
    __tablename__ = "filings"
    accession: str = Field(primary_key=True)
    company_cik: str = Field(index=True)
    filing_date: date
    xml_url: Optional[str] = None
    is_amendment: bool = False
    is_10b5_1: Optional[bool] = None  # True if at least one transaction in this filing is 10b5-1


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    id: Optional[int] = Field(default=None, primary_key=True)
    accession: str = Field(index=True)
    company_cik: str = Field(index=True)
    insider_cik: str = Field(index=True)
    insider_name: str
    is_director: bool = False
    is_officer: bool = False
    is_ten_percent_owner: Optional[bool] = None  # 10% owner before transaction (from Form 4)
    officer_title: Optional[str] = None
    security_title: Optional[str] = None
    transaction_date: date
    transaction_code: Optional[str] = None
    acq_disp: Optional[str] = None  # A or D
    shares: Optional[float] = None
    price: Optional[float] = None
    value_usd: Optional[float] = None
    shares_owned_following: Optional[float] = None
    ownership_type: Optional[str] = None  # "D" (direct) or "I" (indirect)
    ownership_nature: Optional[str] = None  # e.g. "By Trust", "By LLC" (when indirect)
    is_10b5_1: Optional[bool] = None  # Per-transaction: from footnote 10b5-1
    plan_adoption_date: Optional[str] = None  # 10b5-1 plan adoption date (ISO YYYY-MM-DD) from footnote
    is_margin_call_collateral: Optional[bool] = None  # Sale due to margin call/collateral from footnote
    is_rsu_vest_related: Optional[bool] = None
    is_tax_withholding: Optional[bool] = None
    is_gift: Optional[bool] = None
    is_derivative: Optional[bool] = None  # True = Table II (derivative/options/RSUs not yet converted)
    classification_confidence: Optional[str] = None  # high | medium | low
    classification_reasoning: Optional[str] = None
    xml_url: Optional[str] = None
