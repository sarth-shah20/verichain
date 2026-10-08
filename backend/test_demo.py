import base64
import sys
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).parent))
from routes.demo import files, SCENARIOS
from demo_records import reference, PAN
from routes.verify import _run_pipeline1

def test_six_scenarios_have_valid_synthetic_inputs():
    for scenario in SCENARIOS:
        for item in files(scenario['id']):
            with fitz.open(stream=base64.b64decode(item['file_base64']),filetype='pdf') as doc:
                assert len(doc)==1
                assert 'SYNTHETIC DEMONSTRATION' in doc[0].get_text()

def test_demo_reference_is_explicit_and_reserved():
    assert reference('itr',{'pan':PAN,'assessment_year':'2025-26'})['gross_total_income']==960000
    assert reference('itr',{'pan':'PRIVATE0000X','assessment_year':'2025-26'}) is None

def test_salary_demo_recovers_original(tmp_path):
    item=files('salary_edit')[0];path=tmp_path/'salary.pdf';path.write_bytes(base64.b64decode(item['file_base64']))
    report=_run_pipeline1(str(path))
    assert any('revision_edit' in r['signals'] for r in report['suspect_regions'])
