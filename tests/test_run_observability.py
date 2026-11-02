from datetime import datetime, timezone
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def observation_module():
    assert importlib.util.find_spec('etl.run_observability') is not None, 'local observation module is missing'
    return importlib.import_module('etl.run_observability')


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


def make_observer(tmp_path, **kwargs):
    module = observation_module()
    clock = Clock()
    kwargs.setdefault('process_sampler', lambda pid: module.unknown_memory(pid, 'mock_process'))
    observer = module.RunObserver(tmp_path / 'progress.json', 'run-test',
        config=module.ObservationConfig(sample_seconds=1, no_progress_seconds=30,
            warning_interval_seconds=60, warning_free_gib=24),
        monotonic=clock, now=lambda: datetime(2026, 10, 17, tzinfo=timezone.utc), **kwargs)
    observer.begin_step('labels', tmp_path / 'out.log', tmp_path / 'err.log')
    return module, observer, clock


def snapshot(observer):
    return json.loads(observer.path.read_text(encoding='utf-8'))


def test_log_activity_is_not_business_progress_or_a_processed_count(tmp_path):
    _, observer, clock = make_observer(tmp_path)
    clock.value = 10
    observer.record_output('labels', 'query is still running; password=never-store-this')
    observer.child_started('labels', 123)
    observer.tick(force=True)
    value = snapshot(observer)
    activity = value['steps']['labels']
    assert activity['child_pid'] == 123 and activity['child_alive'] is True
    assert activity['elapsed_seconds'] == 10
    assert activity['last_log_activity_at_utc']
    assert activity['last_business_progress_at_utc'] is None
    assert activity['business_progress'] is None
    assert 'never-store-this' not in observer.path.read_text(encoding='utf-8')


def test_evidenced_scope_progress_is_deduplicated_and_stale_warnings_are_throttled(tmp_path):
    warnings = []
    _, observer, clock = make_observer(tmp_path, warning_sink=warnings.append)
    clock.value = 10
    line = '{"stage":"scope_ready","done":2,"total":171,"secret":"do-not-copy"}'
    observer.record_output('labels', line)
    clock.value = 25
    observer.record_output('labels', line)
    clock.value = 41
    observer.tick(force=True)
    activity = snapshot(observer)['steps']['labels']
    assert activity['business_progress'] == {'event': 'scope_ready', 'done': 2, 'total': 171}
    assert activity['seconds_without_business_progress'] == 31
    assert len([w for w in warnings if 'no_progress' in w]) == 1
    clock.value = 45
    observer.tick(force=True)
    assert len([w for w in warnings if 'no_progress' in w]) == 1
    assert 'do-not-copy' not in observer.path.read_text(encoding='utf-8')
    clock.value = 102
    observer.tick(force=True)
    assert len([w for w in warnings if 'no_progress' in w]) == 2


def test_progress_must_have_valid_nonnegative_counts_and_consistent_totals(tmp_path):
    _, observer, _ = make_observer(tmp_path)
    for line in ('{"stage":"scope_ready","done":4,"total":3}',
                 '{"stage":"scope_ready","done":true,"total":3}',
                 '{"stage":"scope_ready","done":-1,"total":3}',
                 '{"stage":"unrecognized","rows":9}', '{"stage":[],"rows":9}'):
        observer.record_output('labels', line)
    observer.tick(force=True)
    assert snapshot(observer)['steps']['labels']['business_progress'] is None
    observer.record_output('labels', '[success] inventory_snapshot: affected_rows=17')
    observer.tick(force=True)
    assert snapshot(observer)['steps']['labels']['business_progress'] == {
        'event': 'step_result', 'unit': 'inventory_snapshot', 'rows': 17}


def test_runtime_disk_measurements_are_local_warn_only_and_track_minimum_peak_and_trend(tmp_path):
    warnings = []
    values = iter([40, 40, 20, 20])
    module, observer, clock = make_observer(tmp_path, database_directory=tmp_path,
        disk_usage=lambda _: SimpleNamespace(free=next(values) * 1024**3), warning_sink=warnings.append)
    # begin_step samples database and observation volumes at t=0.
    clock.value = 10
    observer.tick(force=True)
    disk = snapshot(observer)['disks']['database']
    assert disk['free_bytes'] == disk['min_free_bytes'] == 20 * 1024**3
    assert disk['peak_consumed_bytes'] == 20 * 1024**3
    assert disk['free_bytes_per_second'] == -2 * 1024**3
    assert any('disk_low' in warning for warning in warnings)
    assert snapshot(observer)['warnings']['disk_low:database']['active'] is True
    assert snapshot(observer)['status'] == 'running'
    assert not hasattr(observer, 'terminate')
    observer.disk_usage=lambda _:SimpleNamespace(free=40*1024**3)
    clock.value=20
    observer.tick(force=True)
    recovered=snapshot(observer)
    assert recovered['warnings']['disk_low:database']['active'] is False
    assert recovered['disks']['database']['min_free_bytes']==20*1024**3


def test_disk_sample_failure_does_not_reuse_stale_value_as_current(tmp_path):
    module, observer, clock = make_observer(tmp_path, database_directory=tmp_path,
        disk_usage=lambda _: SimpleNamespace(free=40 * 1024**3))
    observer.disk_usage = lambda _: (_ for _ in ()).throw(OSError('private filesystem error'))
    clock.value = 2
    observer.tick(force=True)
    disk = snapshot(observer)['disks']['database']
    assert disk['free_bytes'] is None and disk['sample_error'] == 'OSError'
    assert disk['min_free_bytes'] == 40 * 1024**3
    assert 'private filesystem error' not in observer.path.read_text(encoding='utf-8')


def test_snapshot_replaces_atomically_and_write_failure_preserves_previous_json(tmp_path, monkeypatch):
    module, observer, clock = make_observer(tmp_path)
    previous = observer.path.read_bytes()
    real_replace = module.os.replace
    observed = []
    def replace(source, destination):
        assert Path(destination).read_bytes() == previous
        observed.append(json.loads(Path(source).read_text(encoding='utf-8')))
        real_replace(source, destination)
    monkeypatch.setattr(module.os, 'replace', replace)
    clock.value = 2
    observer.tick(force=True)
    assert observed and snapshot(observer)['elapsed_seconds'] == 2
    previous = observer.path.read_bytes()
    monkeypatch.setattr(module.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    clock.value = 3
    observer.tick(force=True)
    assert observer.path.read_bytes() == previous
    assert observer.snapshot_write_error == 'OSError'


def test_completed_step_is_not_reported_as_stalled(tmp_path):
    warnings = []
    _, observer, clock = make_observer(tmp_path, warning_sink=warnings.append)
    clock.value = 5
    observer.finish_step('labels', 'success', 0)
    clock.value = 1000
    observer.complete('success', 0)
    value = snapshot(observer)
    assert value['status'] == 'success'
    assert value['steps']['labels']['child_alive'] is False
    assert value['steps']['labels']['elapsed_seconds'] == 5
    assert not any('no_progress' in warning for warning in warnings)


def test_failure_without_confirmed_child_exit_does_not_claim_it_is_stopped(tmp_path):
    _,observer,_=make_observer(tmp_path)
    observer.child_started('labels',123)
    observer.finish_step('labels','failed',1,child_exit_confirmed=False)
    value=snapshot(observer)
    assert value['steps']['labels']['child_alive'] is None
    assert value['steps']['labels']['child_exit_confirmed'] is False
    assert value['transaction_state']=='not_observed'


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'not-a-number', '0'])
def test_observer_rejects_invalid_positive_interval(monkeypatch, value):
    module = observation_module()
    monkeypatch.setenv('DASHBOARD_OBSERVE_INTERVAL_SECONDS', value)
    with pytest.raises(ValueError, match='DASHBOARD_OBSERVE_INTERVAL_SECONDS'):
        module.ObservationConfig.from_environment()


def test_expected_peak_is_explicit_config_not_a_fabricated_row_estimate(tmp_path, monkeypatch):
    module = observation_module()
    monkeypatch.setenv('DASHBOARD_DISK_EXPECTED_PEAK_GIB', '12')
    config = module.ObservationConfig.from_environment()
    assert config.expected_peak_gib == 12
    assert module.ObservationConfig().expected_peak_gib is None
    warnings = []
    observer = module.RunObserver(tmp_path/'progress.json', 'run', config=config,
        database_directory=tmp_path, warning_sink=warnings.append,
        disk_usage=lambda _: SimpleNamespace(free=25*1024**3))
    observer.tick(force=True)
    assert snapshot(observer)['disks']['database']['required_capacity_bytes'] == 28*1024**3
    assert any('disk_budget' in warning for warning in warnings)
