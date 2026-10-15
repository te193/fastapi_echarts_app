import json,os
from datetime import date
from pathlib import Path
import pytest
from etl import label_analysis_bounded_refresh as module

def test_scope_identity_is_stable_without_daily_payload():
    scope={'country_category':'欧洲站','store':'CHO OJEE','mskus':['a','b']}
    assert module.scoped_key(scope)==module.scoped_key(json.loads(module.dumps(scope)))
    assert len(module.scoped_key(scope))==64
    assert module.scoped_key(scope)==module.scoped_key(dict(reversed(list(scope.items()))))

def test_pc_budget_rejects_unbounded_concurrency_before_migration(monkeypatch):
    monkeypatch.setattr(module,'ensure_schema',lambda:pytest.fail('must reject before DB'))
    with pytest.raises(ValueError):module.refresh_bounded(workers=9)
    with pytest.raises(ValueError):module.refresh_bounded(chunk_size=81)

def test_worker_launch_is_hidden_low_priority_and_releases_over_budget(monkeypatch,tmp_path):
    captures={}
    class Process:
        pid=12;returncode=None
        def __init__(self,*args,**kwargs):captures.update(kwargs)
        def poll(self):return self.returncode
        def terminate(self):self.returncode=-1;captures['terminated']=True
        def wait(self,**kwargs):return self.returncode
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    monkeypatch.setattr(module,'working_set',lambda pid:513*1024**2)
    spec={'scope':{'country_category':'欧洲站','store':'test','mskus':['a']}}
    with pytest.raises(RuntimeError,match='内存预算'):module.launch_scope(spec,tmp_path)
    assert captures['terminated']
    if os.name=='nt':
        assert captures['creationflags'] & module.subprocess.CREATE_NO_WINDOW
        assert captures['creationflags'] & module.subprocess.BELOW_NORMAL_PRIORITY_CLASS

def test_code_hash_covers_engine_and_input_contract():
    assert len(module.code_hash())==64
