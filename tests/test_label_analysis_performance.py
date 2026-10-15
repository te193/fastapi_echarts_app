"""Regression checks for snapshot reuse, refresh and concurrent reads."""
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.services.label_analysis_repository import unpack_points
from app.services.label_analysis_service import AnalysisQuery, LabelAnalysisService, StaleAnalysis
from test_label_analysis_service import Repo


class RevisionRepo(Repo):
    def __init__(self):self.calls=0;self.current_revision=1
    def revision(self,end):return self.current_revision
    def load(self,*args):return {**super().load(*args),'revision':self.current_revision}


def test_packed_wire_retains_missing_values_and_duplicate_days():
    rows=list(unpack_points([{'store':'S','points':'[["2026-10-12",0],["2026-10-12",null]]'}],['date','stock']))
    assert rows==[{'store':'S','date':'2026-10-12','stock':0},{'store':'S','date':'2026-10-12','stock':None}]
    with pytest.raises(ValueError):list(unpack_points([{'points':[[1]]}],['date','stock']))


def test_unchanged_publication_reuses_dataset_after_two_minutes():
    repo=RevisionRepo();s=LabelAnalysisService(repo);q=AnalysisQuery(period=7)
    first=s.summary(q);entry=s._cache[first['version']]
    entry['created']-=121;entry['checked']-=121
    assert s.summary(q)['version']==first['version']
    assert repo.calls==1
    repo.current_revision=2;entry['checked']-=121
    new=s.summary(q)
    assert new['version']!=first['version'] and repo.calls==2
    assert s.details(q.model_copy(update={'version':first['version']}))['version']==first['version']


def test_force_refresh_reloads_only_once_and_preserves_pinned_snapshot():
    repo=RevisionRepo();s=LabelAnalysisService(repo);q=AnalysisQuery(period=7)
    a=s.summary(q)
    b=s.summary(q.model_copy(update={'version':a['version'],'force_refresh':True}))
    assert a['version']!=b['version'] and repo.calls==2
    s.details(q.model_copy(update={'version':b['version']}))
    assert repo.calls==2
    s._cache[a['version']]['created']-=1801
    with pytest.raises(StaleAnalysis):s.details(q.model_copy(update={'version':a['version']}))


def test_summary_cache_isolated_from_filters_columns_and_caller_mutations():
    s=LabelAnalysisService(RevisionRepo());q=AnalysisQuery(period=7,columns=['sales_qty'])
    first=s.summary(q);first['current']['object_count']['value']=-1
    assert s.summary(q)['current']['object_count']['value']==2
    narrow=q.model_copy(update={'conditions':AnalysisQuery(conditions=[{'kind':'label','parent_id':1,'ids':[101]}]).conditions})
    assert s.summary(narrow)['current']['object_count']['value']==1
    different=q.model_copy(update={'columns':['sales_amount']})
    metrics=s.summary(different)['categories'][0]['children'][0]['metrics']
    assert 'sales_amount' in metrics and 'sales_qty' not in metrics


def test_slow_new_dataset_does_not_block_pinned_reads_or_duplicate_load():
    started=threading.Event();release=threading.Event()
    class SlowRepo(RevisionRepo):
        def load(self,end,period,view):
            if period==14:
                started.set()
                assert release.wait(5)
            return super().load(end,period,view)
    repo=SlowRepo();s=LabelAnalysisService(repo);q=AnalysisQuery(period=7)
    first=s.summary(q);slow=AnalysisQuery(period=14)
    with ThreadPoolExecutor(max_workers=4) as pool:
        a=pool.submit(s.summary,slow)
        assert started.wait(2)
        b=pool.submit(s.summary,slow)
        try:
            pinned=pool.submit(s.details,q.model_copy(update={'version':first['version']}))
            assert pinned.result(timeout=2)['total']==2
            assert pool.submit(s.meta).result(timeout=2)['dates']
        finally:release.set()
        assert a.result(timeout=5)['version']==b.result(timeout=5)['version']
    assert repo.calls==2


def test_persistent_cache_validates_source_revision_and_code(tmp_path):
    repo=RevisionRepo();q=AnalysisQuery(period=7)
    first=LabelAnalysisService(repo,cache_directory=tmp_path).summary(q)
    restored=LabelAnalysisService(repo,cache_directory=tmp_path).summary(q)
    assert first['current']==restored['current'] and repo.calls==1
    repo.current_revision=2
    LabelAnalysisService(repo,cache_directory=tmp_path).summary(q)
    assert repo.calls==2
    changed=LabelAnalysisService(repo,cache_directory=tmp_path)
    changed._disk_cache.code_revision='changed calculation'
    changed.summary(q)
    assert repo.calls==3


def test_corrupt_disk_cache_falls_back_to_source(tmp_path):
    repo=RevisionRepo();q=AnalysisQuery(period=7)
    LabelAnalysisService(repo,cache_directory=tmp_path).summary(q)
    for f in tmp_path.glob('*.pkl'):f.write_bytes(b'broken')
    assert LabelAnalysisService(repo,cache_directory=tmp_path).summary(q)['current']['object_count']['value']==2
    assert repo.calls==2


def test_publication_change_during_read_is_not_persisted_or_reused(tmp_path):
    class ChangingRepo(RevisionRepo):
        def load(self,*args):
            result=super().load(*args)
            self.current_revision+=1
            return result
    repo=ChangingRepo();s=LabelAnalysisService(repo,cache_directory=tmp_path)
    first=s.summary(AnalysisQuery(period=7))
    assert not list(tmp_path.glob('*.pkl'))
    second=s.summary(AnalysisQuery(period=7))
    assert first['version']!=second['version'] and repo.calls==2
