import json

from etl.run_observability import RunObserver


def result(total,*,complete=True,identity=111):
    return {'working_set_bytes':total,'observed_working_set_bytes':total,
        'complete':complete,'process_count':3,'root_creation_time_100ns':identity,
        'sample_error':None if complete else 'process_unavailable',
        'measurement':'sampled_process_tree_working_set_sum',
        'atomic':False,'hard_limit_enforced':False}


def test_observer_records_complete_tree_and_sampled_peak_without_enforcement(tmp_path):
    samples=iter([result(300),result(500),result(None,complete=False),result(400)])
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:next(samples))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    first=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert first['working_set_bytes']==300 and first['peak_observed_working_set_bytes']==300
    observer._collect_process_samples();observer.tick(force=True)
    observer._collect_process_samples();observer.tick(force=True)
    unknown=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert unknown['working_set_bytes'] is None
    assert unknown['peak_observed_working_set_bytes']==500
    assert unknown['hard_limit_enforced'] is False
    observer._collect_process_samples();observer.tick(force=True)
    recovered=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert recovered['working_set_bytes']==400 and recovered['peak_observed_working_set_bytes']==500
    assert recovered['sampled_at_utc']
    assert observer.state['status']=='running'


def test_observer_sampler_error_is_unknown_and_does_not_interrupt_tick(tmp_path):
    def unavailable(pid):raise OSError('access denied')
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=unavailable)
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    value=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['sample_error']=='sampler_unavailable'
    assert value['peak_observed_working_set_bytes'] is None


def test_observer_detects_reused_root_pid_across_ticks(tmp_path):
    samples=iter([result(300),result(900,identity=222)])
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:next(samples))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    observer._collect_process_samples();observer.tick(force=True)
    value=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['complete'] is False
    assert value['sample_error']=='root_pid_reused'
    assert value['peak_observed_working_set_bytes']==300


def test_observer_does_not_sample_missing_pid_or_claim_zero_after_step_exit(tmp_path):
    calls=[]
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:calls.append(pid) or result(300))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    assert calls==[]
    observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    observer.finish_step('analysis','success',0)
    value=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert calls==[10]
    assert value['working_set_bytes'] is None and value['sample_error']=='child_not_running'
    assert value['peak_observed_working_set_bytes']==300


def test_readable_root_identity_is_pinned_even_when_first_tree_sample_is_incomplete(tmp_path):
    samples=iter([result(None,complete=False,identity=111),result(900,identity=222)])
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:next(samples))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    observer._collect_process_samples();observer.tick(force=True)
    value=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None
    assert value['sample_error']=='root_pid_reused'
    assert value['peak_observed_working_set_bytes'] is None


def test_unconfirmed_exit_does_not_label_tree_as_stopped_or_sample_it_as_zero(tmp_path):
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:result(300))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    observer.finish_step('analysis','failed',1,child_exit_confirmed=False)
    value=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None
    assert value['sample_error']=='child_exit_unconfirmed'
    assert value['peak_observed_working_set_bytes']==300


def test_runner_tick_never_calls_native_memory_sampler(tmp_path):
    calls=[]
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:calls.append(pid) or result(300))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.child_started('analysis',10)
    observer.tick(force=True)
    assert calls==[]
    assert observer.state['steps']['analysis']['process_tree_memory']['sample_error']=='sample_pending'


def test_blocked_single_sampler_cannot_block_runner_progress_complete_or_close(tmp_path):
    import threading
    entered=threading.Event();release=threading.Event();done=threading.Event();calls=[]
    def blocked(pid):
        calls.append(pid);entered.set();release.wait(5);return result(300)
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=blocked)
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err')
    observer.start()
    observer.child_started('analysis',10)
    try:
        assert entered.wait(1)
        memory_thread=observer._memory_thread
        def main_work():
            observer.tick(force=True)
            observer.record_output('analysis','{"stage":"scope_ready","done":1,"total":2}')
            observer.finish_step('analysis','success',0)
            observer.complete('success',0)
            done.set()
        worker=threading.Thread(target=main_work,daemon=True);worker.start()
        assert done.wait(1),'sampler held the observer lock or runner called sampler synchronously'
        for _ in range(5):observer.tick(force=True)
        assert calls==[10] and observer._memory_thread is memory_thread
        import time
        before=time.monotonic();observer.close()
        assert time.monotonic()-before<1.5
        assert observer.state['status']=='success'
        assert observer.state['steps']['analysis']['business_progress']['done']==1
    finally:
        release.set();observer.close()


def test_stale_cached_sample_is_unknown_and_does_not_inflate_observed_peak(tmp_path):
    clock=[0.0]
    observer=RunObserver(tmp_path/'progress.json','run',monotonic=lambda:clock[0],process_sampler=lambda pid:result(300))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err');observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    clock[0]=21
    observer.tick(force=True)
    value=observer.state['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['sample_error']=='sample_stale'
    assert value['peak_observed_working_set_bytes']==300


def test_inflight_result_for_replaced_stage_pid_is_discarded(tmp_path):
    def replace(pid):
        observer.child_started('analysis',20)
        return result(999)
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=replace)
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err');observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    value=observer.state['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['sample_error']=='sample_pending'
    assert value['peak_observed_working_set_bytes'] is None


def test_slow_completed_sample_does_not_raise_observed_peak(tmp_path):
    clock=[0.0]
    def slow(pid):
        clock[0]=21
        return result(999)
    observer=RunObserver(tmp_path/'progress.json','run',monotonic=lambda:clock[0],process_sampler=slow)
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err');observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    value=observer.state['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['sample_error']=='sample_stale'
    assert value['peak_observed_working_set_bytes'] is None


def test_result_from_old_stage_generation_with_same_pid_is_discarded(tmp_path):
    def replace(pid):
        observer.begin_step('analysis',tmp_path/'out2',tmp_path/'err2')
        observer.child_started('analysis',10)
        return result(999)
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=replace)
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err');observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    value=observer.state['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['sample_error']=='sample_pending'
    assert value['peak_observed_working_set_bytes'] is None


def test_pending_sample_preserves_prior_observed_peak(tmp_path):
    observer=RunObserver(tmp_path/'progress.json','run',process_sampler=lambda pid:result(300))
    observer.begin_step('analysis',tmp_path/'out',tmp_path/'err');observer.child_started('analysis',10)
    observer._collect_process_samples();observer.tick(force=True)
    with observer._lock:
        observer._process_pending['analysis']=observer._process_tokens['analysis']
    observer.tick(force=True)
    value=observer.state['steps']['analysis']['process_tree_memory']
    assert value['working_set_bytes'] is None and value['sample_error']=='sample_pending'
    assert value['peak_observed_working_set_bytes']==300
