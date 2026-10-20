import sys
from pathlib import Path
import base64
import fitz
from fastapi import FastAPI
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parent))
from routes.batch import router
from routes.demo import router as demo_router
import store

def client(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'_DB_PATH',str(tmp_path/'api.db'));store.init()
    app=FastAPI();app.include_router(router);app.include_router(demo_router);return TestClient(app)

def test_batch_rejects_invalid_and_overlong_inputs(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    assert c.post('/verify/batch',json={'documents':[{'document_type':'unknown','file_base64':'%%%'}]}).status_code==400
    with fitz.open() as pdf:
        for _ in range(9):pdf.new_page()
        data=base64.b64encode(pdf.tobytes()).decode()
    assert c.post('/verify/batch',json={'documents':[{'document_type':'unknown','file_base64':data}]}).status_code==400

def test_required_note_and_persisted_result_contract(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    store.save({'job_id':'api_test','applicant_id':'TARP','documents':[],'overall':{'risk_score':70,'decision':'human_review'},'analysis_status':'partial','analysis_warnings':['Provider unavailable']})
    assert c.post('/verify/batch/api_test/decision',json={'decision':'review'}).status_code==400
    assert c.post('/verify/batch/api_test/decision',json={'decision':'review','note':'Await completed analysis'}).status_code==200
    job=c.get('/verify/batch/api_test').json();assert job['reviewer_note']=='Await completed analysis';assert job['analysis_warnings']==['Provider unavailable']
    assert c.get('/demo/scenarios').status_code==200
    assert c.get('/demo/scenarios/missing').status_code==404
