from pathlib import Path
from unittest.mock import MagicMock,patch
import pytest
from etl import daily_update_guard as guard


def test_disk_budget_rejects_before_work_but_does_not_change_database():
    conn=MagicMock();q=conn.cursor.return_value.__enter__.return_value
    q.fetchone.return_value={'data_directory':str(Path.cwd())}
    with patch.object(guard.shutil,'disk_usage',return_value=type('Disk',(),{'free':1024**3})()):
        with pytest.raises(RuntimeError,match='disk budget'):
            guard.assert_disk_budget(conn,minimum_gib=16)
    assert all(call.args[0].lower().startswith('select') for call in q.execute.call_args_list)


def test_guard_refuses_second_orchestrator_and_keeps_lock_session():
    conn=MagicMock();q=conn.cursor.return_value.__enter__.return_value
    q.fetchone.return_value={'acquired':0}
    with patch.object(guard,'connect_target',return_value=conn):
        with pytest.raises(RuntimeError,match='already running'):
            with guard.daily_guard():pass
    conn.close.assert_called_once()


def test_heartbeat_checks_live_original_session_without_reconnect():
    conn=MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value={'owner':17,'connection_id':17}
    guard.heartbeat_once(conn,'lock',17)
    conn.ping.assert_called_once_with(reconnect=False)
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value={'owner':None,'connection_id':17}
    with pytest.raises(RuntimeError,match='ownership'):
        guard.heartbeat_once(conn,'lock',17)


def test_publication_fence_rejects_a_replaced_lock_owner(monkeypatch):
    monkeypatch.setenv(guard.OWNER_ENV,'17')
    monkeypatch.setenv(guard.LOCK_ENV,'lock')
    conn=MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value={'owner':18}
    with pytest.raises(RuntimeError,match='ownership'):
        guard.assert_daily_lock(conn)


def test_dead_heartbeat_prevents_more_work(monkeypatch):
    state=guard.GuardState()
    state.error=RuntimeError('lost')
    monkeypatch.setattr(guard,'_active_guard',state)
    with pytest.raises(RuntimeError,match='lost'):
        guard.assert_guard_healthy()


def test_guard_restores_environment_after_success(monkeypatch):
    monkeypatch.delenv(guard.OWNER_ENV,raising=False);monkeypatch.delenv(guard.LOCK_ENV,raising=False)
    conn=MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.side_effect=[{'acquired':1},{'connection_id':17}]
    with patch.object(guard,'connect_target',return_value=conn),patch.object(guard,'assert_disk_budget',return_value=41*1024**3):
        with guard.daily_guard():
            assert guard.os.environ[guard.OWNER_ENV]=='17'
            guard.assert_guard_healthy()
    assert guard.OWNER_ENV not in guard.os.environ
    conn.close.assert_called_once()


def test_subprocess_lock_failure_uses_bounded_tree_shutdown(tmp_path,monkeypatch):
    import io,subprocess
    from etl import daily_update_runner as runner
    process=MagicMock();process.stdout=io.StringIO('progress\n');process.stderr=io.StringIO('')
    process.poll.return_value=None
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**k:process)
    stop=MagicMock(side_effect=subprocess.TimeoutExpired('taskkill',15))
    monkeypatch.setattr(runner.subprocess,'run',stop)
    monkeypatch.setattr(guard,'assert_guard_healthy',MagicMock(side_effect=RuntimeError('lost lock')))
    with pytest.raises(RuntimeError,match='lost lock'):
        runner.execute_subprocess(['python','-m','etl.test'],tmp_path/'out.log',tmp_path/'err.log',lambda line:None,cwd=tmp_path)
    process.kill.assert_called_once()
    assert process.wait.call_args.kwargs=={'timeout':10}


def test_guard_failure_still_reaches_failure_notifier(tmp_path,monkeypatch):
    from etl import daily_update_runner as runner
    state=guard.GuardState();state.error=RuntimeError('lost lock')
    monkeypatch.setattr(guard,'_active_guard',state)
    notices=[]
    result=runner.run_daily_update(project_root=tmp_path,notifier=notices.append,
        step_executor=lambda *args:0,emit=lambda line:None)
    assert result.exit_code==1
    assert [(n.status,n.stage) for n in notices]==[('failed','source_preflight')]
