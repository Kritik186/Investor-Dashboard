"""Unit tests for Form 4 XML picking and parsing."""

import pytest
from xml.etree import ElementTree as ET

from parser import (
    pick_form4_xml_from_index,
    parse_form4_xml,
    _score_item,
)


class TestScoreItem:
    """Test _score_item for Form 4 XML filename preference."""

    def test_doc4_xml_scores_highest(self):
        assert _score_item("doc4.xml") > 0
        assert _score_item("Doc4.XML") > 0

    def test_form4_xml_scores(self):
        assert _score_item("form4.xml") > 0

    def test_random_xml_scores_zero(self):
        assert _score_item("other.xml") == 0
        assert _score_item("index.html") == 0

    def test_form4_in_path_scores_low(self):
        # form 4 somewhere in name and ends .xml
        assert _score_item("form4_something.xml") >= 1


class TestPickForm4XmlFromIndex:
    """Test picking Form 4 XML from index.json directory."""

    def test_prefers_doc4_over_other(self):
        index = {
            "directory": {
                "item": [
                    {"name": "other.xml", "href": "other.xml"},
                    {"name": "doc4.xml", "href": "doc4.xml"},
                ]
            }
        }
        base = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000123/"
        url = pick_form4_xml_from_index(index, base)
        assert url is not None
        assert "doc4.xml" in url

    def test_returns_none_empty_directory(self):
        index = {"directory": {"item": []}}
        base = "https://www.sec.gov/Archives/edgar/data/1/0000000001/"
        url = pick_form4_xml_from_index(index, base)
        assert url is None

    def test_single_item_dict(self):
        index = {"directory": {"item": {"name": "form4.xml", "href": "form4.xml"}}}
        base = "https://www.sec.gov/Archives/edgar/data/320193/000032019323000123/"
        url = pick_form4_xml_from_index(index, base)
        assert url is not None
        assert "form4.xml" in url


class TestParseForm4Xml:
    """Test parsing nonDerivativeTable / nonDerivativeTransaction."""

    def test_parses_single_transaction(self):
        xml = """
        <ownershipDocument>
            <reportingOwner>
                <reportingOwnerId>
                    <rptOwnerCik>0000320193</rptOwnerCik>
                    <rptOwnerName>John Smith</rptOwnerName>
                </reportingOwnerId>
                <reportingOwnerRelationship>
                    <isDirector>1</isDirector>
                    <isOfficer>1</isOfficer>
                    <officerTitle>CEO</officerTitle>
                </reportingOwnerRelationship>
            </reportingOwner>
            <securityTitle>Common Stock</securityTitle>
            <nonDerivativeTable>
                <nonDerivativeTransaction>
                    <securityTitle>Common Stock</securityTitle>
                    <transactionDate><value>2024-01-15</value></transactionDate>
                    <transactionCoding>
                        <transactionCode>S</transactionCode>
                        <transactionFormType>D</transactionFormType>
                    </transactionCoding>
                    <transactionAmounts>
                        <sharesAcquiredDisposed><value>1000</value></sharesAcquiredDisposed>
                        <pricePerShare><value>150.50</value></pricePerShare>
                        <value>150500</value>
                    </transactionAmounts>
                    <postTransactionAmounts>
                        <sharesOwnedFollowingTransaction><value>50000</value></sharesOwnedFollowingTransaction>
                    </postTransactionAmounts>
                </nonDerivativeTransaction>
            </nonDerivativeTable>
        </ownershipDocument>
        """
        result = parse_form4_xml(xml, "0000320193", "000032019323000123", "https://www.sec.gov/Archives/edgar/data/320193/000032019323000123/doc4.xml")
        assert len(result) == 1
        t = result[0]
        assert t["insider_cik"] == "0000320193"
        assert t["insider_name"] == "John Smith"
        assert t["transaction_date"] == "2024-01-15"
        assert t["acq_disp"] == "D"
        assert t["shares"] == 1000.0
        assert t["price"] == 150.5
        assert t["value_usd"] == 150500.0
        assert t["shares_owned_following"] == 50000.0
        assert t["xml_url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000123/doc4.xml"

    def test_returns_empty_for_no_transactions(self):
        xml = """
        <ownershipDocument>
            <reportingOwner>
                <reportingOwnerId><rptOwnerCik>1</rptOwnerCik><rptOwnerName>X</rptOwnerName></reportingOwnerId>
            </reportingOwner>
        </ownershipDocument>
        """
        result = parse_form4_xml(xml, "0000000001", "acc", "http://example.com/doc4.xml")
        assert result == []
