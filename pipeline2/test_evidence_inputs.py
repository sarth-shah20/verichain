import base64
import sqlite3
from unittest.mock import patch

import fitz
import pytest

import db
import extract
import schemas
import utils


def test_payslip_pan_survives_derivation(tmp_path):
    p = tmp_path / "salary.pdf"
    d = fitz.open(); d.new_page().insert_text((50, 50), "PAN: ABCPD1234E"); d.save(p); d.close()
    with patch("llm_client.call_vision", return_value={"doc_type": "payslip", "full_text": "PAN: ABCPD1234E"}), \
         patch("llm_client.call_text", return_value={"fields": {"pan": "ABCPD1234E"}}):
        result = extract.extract_document(str(p), "payslip")
    assert "pan" in schemas.SCHEMAS["payslip"]["fields"]
    assert result["fields"]["pan"] == "ABCPD1234E"
    assert not list(tmp_path.glob("*__page*"))


def test_nine_page_input_is_rejected(tmp_path):
    p = tmp_path / "long.pdf"
    d = fitz.open()
    for _ in range(9): d.new_page()
    d.save(p); d.close()
    with pytest.raises(ValueError, match="1–8"):
        utils.inspect_input(p.read_bytes())
    with pytest.raises(ValueError, match="8 pages"):
        utils.load_media(str(p))


def test_land_lookup_requires_exact_locality_and_subdivision(tmp_path):
    p = tmp_path / "land.db"
    with sqlite3.connect(p) as c:
        c.execute("CREATE TABLE land_records (parcel_id TEXT, survey_number TEXT, state TEXT, district TEXT, taluka TEXT, village TEXT, owner_name TEXT)")
        c.execute("INSERT INTO land_records VALUES ('P1','115/2','MH','D','T','V','Arun Demo')")
    good = dict(survey_number="115/2", state="MH", district="D", taluka="T", village="V")
    with patch.object(db, "_DB_PATH", str(p)):
        assert db.fetch_record("land_record", [], good)["found"]
        assert not db.fetch_record("land_record", [], {**good, "district": "Elsewhere"})["found"]
        assert not db.fetch_record("land_record", [], {**good, "survey_number": "115"})["found"]
        assert db.fetch_record("land_record", [], {"parcel_id": "P1"})["found"]
