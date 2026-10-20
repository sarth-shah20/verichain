import sys
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).parent))
from routes.batch import _render_report_pdf

def test_report_preserves_note_score_and_source_evidence(tmp_path):
    path=tmp_path/'report.pdf'
    _render_report_pdf({'applicant_id':'TARP','overall':{'risk_score':40,'decision':'auto_reject'},'reviewer_note':'Recovered salary edit confirmed','underwriter_decision':'rejected','analysis_status':'complete','documents':[{'doc_id':'doc_0','filename':'salary.pdf','risk_score':40,'revision_evidence':{'changes':[{'original_value':'80000','current_value':'200000','page_number':2,'weight':'high'}]},'findings':[{'state':'failed','label':'Salary arithmetic','detail':'Net pay does not reconcile','page':2,'id':'evidence_1'}]}]},str(path))
    with fitz.open(path) as doc:
        text=''.join(p.get_text() for p in doc)
    assert 'Authenticity: 40 / 100' in text
    assert 'Recovered salary edit confirmed' in text
    assert '80000 -> 200000' in text
    assert 'page 2' in text
