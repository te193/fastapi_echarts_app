from datetime import datetime
import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest

from etl import daily_update_guard as guard
from etl import daily_update_runner as runner


@pytest.mark.parametrize('code', [0, 7])
def test_summary_is_durable_before_final_or_failed_notification(tmp_path, code):
    observations = []
    def notifier(notice):
        path = tmp_path/'logs'/f'etl_run_summary_{notice.run_stamp}.json'
        assert path.exists(), 'notification must not precede durable run status'
        value = json.loads(path.read_text(encoding='utf-8'))
        observations.append(value)
        assert value['exit_code'] == code
        assert value['status'] == ('success' if code == 0 else 'failed')
        assert value['notifications'][-1]['state'] == 'sending'
        progress=json.loads((tmp_path/'logs'/f'etl_run_progress_{notice.run_stamp}.json').read_text(encoding='utf-8'))
        assert progress['status']==value['status']
        assert progress['transaction_state']=='not_observed'
    result = runner.run_daily_update(project_root=tmp_path,
        steps=(runner.DEFAULT_STEPS[0],), step_executor=lambda *args: code,
        notifier=notifier, emit=lambda _: None)
    assert result.exit_code == code
    assert observations
    summary = json.loads(next((tmp_path/'logs').glob('etl_run_summary_*.json')).read_text(encoding='utf-8'))
    assert summary['notifications'][-1]['state'] == 'sent'
    progress = json.loads(next((tmp_path/'logs').glob('etl_run_progress_*.json')).read_text(encoding='utf-8'))
    assert progress['steps']['source_preflight']['status'] == ('success' if code == 0 else 'failed')


def test_intermediate_notification_summary_keeps_running_status(tmp_path):
    seen = []
    def notice(request):
        value = json.loads((tmp_path/'logs'/f'etl_run_summary_{request.run_stamp}.json').read_text(encoding='utf-8'))
        seen.append(value)
    runner.run_daily_update(project_root=tmp_path, steps=(runner.DEFAULT_STEPS[2],),
        step_executor=lambda *args:0, notifier=notice, emit=lambda _:None)
    assert seen[0]['status'] == 'running' and seen[0]['finished_at'] is None
    assert seen[0]['exit_code'] is None
    assert seen[1]['status'] == 'success'


def test_notification_timeout_is_bounded_and_does_not_replace_etl_result(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs['timeout'] == 120
        raise subprocess.TimeoutExpired('notification', kwargs['timeout'], output=b'partial', stderr=b'')
    monkeypatch.setattr(runner.subprocess, 'run', timeout)
    result = runner.run_daily_update(project_root=tmp_path, steps=(runner.DEFAULT_STEPS[0],),
        step_executor=lambda *args:0, emit=lambda _:None)
    assert result.exit_code == 0
    value = json.loads(next((tmp_path/'logs').glob('etl_run_summary_*.json')).read_text(encoding='utf-8'))
    assert value['notifications'][-1]['state'] == 'failed'
    assert value['notifications'][-1]['delivery'] == 'unknown'
    assert (tmp_path/'logs'/f"dingtalk_notify_run_{value['run_stamp']}_all_success.log").read_text(encoding='utf-8') == 'partial'


def test_stage_capacity_uses_owner_bound_local_pin_without_database(tmp_path, monkeypatch):
    assert hasattr(guard, 'DATA_DIRECTORY_ENV'), 'guard does not export a verified local directory'
    monkeypatch.setenv('DASHBOARD_SHARED_PRODUCT_RUN', 'run')
    monkeypatch.setenv(guard.OWNER_ENV, '17')
    monkeypatch.setenv(guard.LOCK_ENV, 'lock')
    monkeypatch.setenv(guard.DATA_DIRECTORY_ENV, str(tmp_path.resolve()))
    monkeypatch.setenv(guard.DATA_DIRECTORY_OWNER_ENV, '17')
    monkeypatch.setattr(guard, 'connect_target', lambda: pytest.fail('pinned check must not read DB'))
    assert guard.check_stage_disk() > 16 * 1024**3
    monkeypatch.setenv(guard.DATA_DIRECTORY_OWNER_ENV, '18')
    with pytest.raises(RuntimeError, match='pin'):
        guard.check_stage_disk()


def test_guard_exports_only_db_verified_directory_and_restores_prior_pin(tmp_path, monkeypatch):
    assert hasattr(guard, 'DATA_DIRECTORY_ENV'), 'missing verified disk directory pin'
    monkeypatch.setenv(guard.DATA_DIRECTORY_ENV, 'previous')
    monkeypatch.setenv(guard.DATA_DIRECTORY_OWNER_ENV, 'previous-owner')
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = [
        {'acquired': 1}, {'connection_id':17}, {'data_directory':str(tmp_path)}]
    monkeypatch.setattr(guard, 'connect_target', lambda:conn)
    with guard.daily_guard():
        assert Path(guard.os.environ[guard.DATA_DIRECTORY_ENV]) == tmp_path.resolve()
        assert guard.os.environ[guard.DATA_DIRECTORY_OWNER_ENV] == '17'
        assert guard.pinned_data_directory() == tmp_path.resolve()
    assert guard.os.environ[guard.DATA_DIRECTORY_ENV] == 'previous'
    assert guard.os.environ[guard.DATA_DIRECTORY_OWNER_ENV] == 'previous-owner'


def test_stage_budget_is_configurable_and_never_silently_accepts_invalid_values(tmp_path, monkeypatch):
    assert hasattr(guard, 'DATA_DIRECTORY_ENV'), 'missing disk pin'
    monkeypatch.setenv('DASHBOARD_SHARED_PRODUCT_RUN','run')
    monkeypatch.setenv(guard.OWNER_ENV,'17');monkeypatch.setenv(guard.LOCK_ENV,'lock')
    monkeypatch.setenv(guard.DATA_DIRECTORY_ENV,str(tmp_path.resolve()))
    monkeypatch.setenv(guard.DATA_DIRECTORY_OWNER_ENV,'17')
    monkeypatch.setenv('DASHBOARD_DISK_STAGE_MIN_GIB','999999')
    with pytest.raises(RuntimeError,match='disk budget'):
        guard.check_stage_disk()
    monkeypatch.setenv('DASHBOARD_DISK_STAGE_MIN_GIB','nan')
    with pytest.raises(ValueError,match='DASHBOARD_DISK_STAGE_MIN_GIB'):
        guard.check_stage_disk()


def test_observer_exception_does_not_enter_existing_child_shutdown_path(tmp_path, monkeypatch):
    import io
    process = MagicMock()
    process.pid = 123
    process.stdout = io.StringIO('normal child output\n')
    process.stderr = io.StringIO('')
    process.wait.return_value = 0
    process.poll.return_value = None
    observer = MagicMock()
    observer.tick.side_effect = RuntimeError('monitor bug')
    monkeypatch.setattr(runner.subprocess, 'run', lambda *args, **kwargs:pytest.fail('monitor must not stop a child'))
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *args, **kwargs:process)
    assert runner.execute_subprocess(['python','-c','pass'], tmp_path/'out.log', tmp_path/'err.log',
        lambda _:None, cwd=tmp_path, observer=observer, step_key='test') == 0
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_missing_webhook_is_recorded_as_skipped_not_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess,'run',lambda *args,**kwargs:subprocess.CompletedProcess(
        args[0],0,stdout='DingTalk webhook is not configured; notification skipped.\n',stderr=''))
    result = runner.run_daily_update(project_root=tmp_path,steps=(runner.DEFAULT_STEPS[0],),
        step_executor=lambda *args:0,emit=lambda _:None)
    value=json.loads(next((tmp_path/'logs').glob('etl_run_summary_*.json')).read_text(encoding='utf-8'))
    assert result.exit_code==0
    assert value['notifications'][-1]['state']=='skipped'


def test_notification_log_disk_failure_does_not_replace_success(tmp_path):
    calls=[]
    def emit(message):
        if message.startswith('钉钉通知：'):raise OSError('console volume unavailable')
    result=runner.run_daily_update(project_root=tmp_path,steps=(runner.DEFAULT_STEPS[0],),
        step_executor=lambda *args:0,notifier=lambda request:calls.append(request),emit=emit)
    value=json.loads(next((tmp_path/'logs').glob('etl_run_summary_*.json')).read_text(encoding='utf-8'))
    assert result.exit_code==0 and len(calls)==1
    assert value['notifications'][-1]['state']=='sent'


def test_relative_server_directory_cannot_be_exported_as_a_trusted_pin(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn=MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value={'data_directory':'.'}
    with pytest.raises(RuntimeError,match='absolute'):
        guard.assert_disk_budget(conn,minimum_gib=16,pin_owner=17)


def test_summary_write_failure_still_allows_file_only_notifier(tmp_path,monkeypatch):
    notices=[]
    monkeypatch.setattr(runner,'atomic_json_write',lambda *args:(_ for _ in ()).throw(OSError('disk full')))
    result=runner.run_daily_update(project_root=tmp_path,steps=(runner.DEFAULT_STEPS[0],),
        step_executor=lambda *args:7,notifier=notices.append,emit=lambda _:None)
    assert result.exit_code==7
    assert [(notice.status,notice.stage) for notice in notices]==[('failed','source_preflight')]


def test_local_child_pid_and_output_are_observed_without_running_an_etl(tmp_path):
    import sys
    from etl.run_observability import RunObserver
    observer=RunObserver(tmp_path/'progress.json','local-child')
    observer.begin_step('test',tmp_path/'out.log',tmp_path/'err.log')
    observer.start()
    try:
        code=runner.execute_subprocess([sys.executable,'-B','-c',
            'print(\'[success] local_probe: rows=3\',flush=True)'],
            tmp_path/'out.log',tmp_path/'err.log',lambda _:None,
            cwd=tmp_path,observer=observer,step_key='test')
        observer.finish_step('test','success',code)
    finally:
        observer.close()
    value=json.loads(observer.path.read_text(encoding='utf-8'))['steps']['test']
    assert code==0 and type(value['child_pid']) is int and value['child_pid']>0
    assert value['business_progress']=={'event':'step_result','unit':'local_probe','rows':3}
    assert value['child_alive'] is False
    assert not observer._thread.is_alive()
