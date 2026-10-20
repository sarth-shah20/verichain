"""Invented TARP references. Reserved identifiers; never government records."""
from __future__ import annotations
PAN = "TARPD4321E"
ITR = dict(pan=PAN, name="Arun Demo", assessment_year="2025-26", gross_total_income=960000,
           total_tax_paid=50000, employer_name="Demo Industries", acknowledgement_number="DEMO-ITR-001")
LAND = dict(state="Maharashtra", district="Demo District", taluka="Demo Taluka", village="Demo Village",
            survey_number="901/2", owner_name="Arun Demo", area_hectare=2.5,
            parcel_id="TARP-DEMO-PARCEL-001", encumbrance="None")
def reference(collection: str, values: dict) -> dict | None:
    if collection == "itr" and values.get("pan") == PAN and values.get("assessment_year") == "2025-26":
        return dict(ITR)
    if collection == "land_record" and values.get("parcel_id") == LAND["parcel_id"]:
        return dict(LAND)
    return None
