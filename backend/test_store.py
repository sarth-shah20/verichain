import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import store

def test_fresh_database_saves_decision_and_note(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'_DB_PATH',str(tmp_path/'fresh.db'));store.init()
    store.save({'job_id':'job_test','applicant_id':'TARP','submitted_at':'2026-10-08','document_count':0,'documents':[],'overall':{'risk_score':70,'decision':'human_review'}})
    assert store.record_decision('job_test','review','Synthetic review completed')
    saved=store.get('job_test');assert saved['underwriter_decision']=='review';assert saved['reviewer_note']=='Synthetic review completed'
