"""Downloadable invented documents; verification always uses the live pipeline."""
from __future__ import annotations
import base64
import tempfile
from pathlib import Path
import fitz
from fastapi import APIRouter, HTTPException
from demo_records import PAN, ITR, LAND
router = APIRouter(prefix="/demo", tags=["demo"])
SCENARIOS = [
    {"id":"clean", "title":"Consistent applicant pack", "expected":["ITR and land match invented references", "Net salary matches bank credit", "Payslip and bank remain unverified without issuer records"]},
    {"id":"salary_edit", "title":"Edited salary figure", "expected":["Recover gross pay 80000 -> 200000", "Payslip arithmetic fails", "Reject recommendation"]},
    {"id":"itr_edit", "title":"Inflated ITR income", "expected":["Income 2400000 differs from reference 960000", "Reject recommendation"]},
    {"id":"bank_balance", "title":"Broken bank balance", "expected":["Salary credit fails running balance arithmetic", "Reject recommendation"]},
    {"id":"land_area", "title":"Inflated land holding", "expected":["Holding 12.5 hectares differs from reference 2.5", "Reject recommendation"]},
    {"id":"pan_conflict", "title":"Conflicting applicant PAN", "expected":["Two structurally valid PANs disagree", "Cross-document identity conflict", "Reject recommendation"]},
]
def scenario(identifier: str) -> dict:
    result = next((s for s in SCENARIOS if s["id"] == identifier), None)
    if result is None: raise HTTPException(404, "Unknown demonstration.")
    return dict(result)
def pdf(lines: list[str], edit: tuple[str,str] | None = None) -> bytes:
    with tempfile.TemporaryDirectory(prefix="tarp-demo-") as folder:
        path = Path(folder)/"document.pdf"
        with fitz.open() as doc:
            page=doc.new_page(); page.insert_text((45,48), "TARP / SYNTHETIC DEMONSTRATION",fontsize=15)
            page.insert_text((45,75),"Invented applicant data. Not an official document.",fontsize=10)
            for n,line in enumerate(lines): page.insert_text((45,115+n*24),line,fontsize=11)
            doc.save(path)
        if edit:
            with fitz.open(path) as doc:
                page=doc[0]; boxes=page.search_for(edit[0]); box=boxes[0]
                page.draw_rect(box,color=(1,1,1),fill=(1,1,1));page.insert_text((box.x0,box.y1-2),edit[1],fontsize=11)
                doc.save(path,incremental=True,encryption=fitz.PDF_ENCRYPT_KEEP)
        return path.read_bytes()
def files(identifier: str) -> list[dict]:
    scenario(identifier)
    salary=["Salary Slip - Demo Industries", "Employee: Arun Demo", "Employee ID: DEMO-001",f"PAN: {PAN}","Pay period: March 2025", "Account ending: 4821", "Gross Pay: 80000", "Deductions: 10000", "Net Pay: 70000"]
    itr=["Indian Income Tax Return - ITR",*[f"{k.replace('_',' ').title()}: {v}" for k,v in ITR.items()]]
    land=["Maharashtra 7/12 Land Record",*[f"{k.replace('_',' ').title()}: {v}" for k,v in LAND.items()]]
    bank=["Bank Statement - Demo Bank", "Account holder: Arun Demo",f"PAN: {PAN}","Account ending: 4821", "Statement period: 2025-03-01 to 2025-04-07", "Currency: INR", "Opening balance: 10000", "Date | Description | Debit | Credit | Balance", "2025-03-05 | Rent | 2000 | 0 | 8000", "2025-03-31 | SALARY DEMO INDUSTRIES | 0 | 70000 | 78000", "Closing balance: 78000", "End of statement - all transactions shown"]
    definitions={"clean":[("salary_slip",salary,None),("itr",itr,None),("bank_statement",bank,None),("land_record",land,None)],
      "salary_edit":[("salary_slip",salary,("80000","200000"))],
      "itr_edit":[("itr",[l.replace("960000","2400000") for l in itr],None)],
      "bank_balance":[("bank_statement",[l.replace("78000","178000") for l in bank],None)],
      "land_area":[("land_record",[l.replace("2.5","12.5") for l in land],None)],
      "pan_conflict":[("itr",itr,None),("salary_slip",[l.replace(PAN,"QWEPD9876A") for l in salary],None)]}
    return [{"filename":f"synthetic_{identifier}_{kind}.pdf", "document_type":kind,
             "file_base64":base64.b64encode(pdf(lines,edit)).decode()} for kind,lines,edit in definitions[identifier]]
@router.get("/scenarios")
def list_scenarios(): return SCENARIOS
@router.get("/scenarios/{identifier}")
def download_scenario(identifier: str): return {"scenario":scenario(identifier),"documents":files(identifier)}
