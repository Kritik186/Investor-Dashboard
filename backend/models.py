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


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    id: Optional[int] = Field(default=None, primary_key=True)
    accession: str = Field(index=True)
    company_cik: str = Field(index=True)
    insider_cik: str = Field(index=True)
    insider_name: str
    is_director: bool = False
    is_officer: bool = False
    officer_title: Optional[str] = None
    security_title: Optional[str] = None
    transaction_date: date
    transaction_code: Optional[str] = None
    acq_disp: Optional[str] = None  # A or D
    shares: Optional[float] = None
    price: Optional[float] = None
    value_usd: Optional[float] = None
    shares_owned_following: Optional[float] = None
    xml_url: Optional[str] = None
