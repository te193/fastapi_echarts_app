"""Session lock and measured local database disk headroom for ETL runs."""
from contextlib import contextmanager, suppress
from pathlib import Path
import os
import shutil
import threading
from etl.dashboard_daily_update import connect_target,build_schema_config
from etl.run_observability import environment_number


def _local_disk_budget(directory, minimum_gib):
    if not directory.is_dir():
        raise RuntimeError('database disk budget cannot be measured on this execution host')
    free=shutil.disk_usage(directory).free
    if free < minimum_gib * 1024**3:
        raise RuntimeError(f'database disk budget insufficient: free={free/1024**3:.2f} GiB minimum={minimum_gib} GiB')
    return free


def assert_disk_budget(conn, *, minimum_gib=32, pin_owner=None):
    with conn.cursor() as cursor:
        cursor.execute('select @@datadir as data_directory')
        directory=Path(cursor.fetchone()['data_directory'])
    if not directory.is_absolute():
        raise RuntimeError('database directory must be an absolute local path')
    directory=directory.resolve()
    free=_local_disk_budget(directory, minimum_gib)
    if pin_owner is not None:
        # Only a freshly confirmed server datadir can create an inherited pin.
        os.environ[DATA_DIRECTORY_ENV]=str(directory)
        os.environ[DATA_DIRECTORY_OWNER_ENV]=str(pin_owner)
    return free


OWNER_ENV='DASHBOARD_DAILY_LOCK_OWNER'
LOCK_ENV='DASHBOARD_DAILY_LOCK_NAME'
DATA_DIRECTORY_ENV='DASHBOARD_DAILY_DATA_DIRECTORY'
DATA_DIRECTORY_OWNER_ENV='DASHBOARD_DAILY_DATA_DIRECTORY_OWNER'
_active_guard=None


def pinned_data_directory():
    value=os.getenv(DATA_DIRECTORY_ENV);pinned_owner=os.getenv(DATA_DIRECTORY_OWNER_ENV)
    if not value and not pinned_owner:return None
    owner=os.getenv(OWNER_ENV)
    directory=Path(value or '')
    if (not owner or not os.getenv(LOCK_ENV) or pinned_owner!=owner
            or not directory.is_absolute() or not directory.is_dir()
            or directory.resolve()!=directory):
        raise RuntimeError('database directory pin contract is invalid')
    return directory


class GuardState:
    def __init__(self):
        self.stop=threading.Event();self.error=None


def heartbeat_once(conn,lock,owner):
    conn.ping(reconnect=False)
    with conn.cursor() as cursor:
        cursor.execute('select is_used_lock(%s) as owner,connection_id() as connection_id',(lock,))
        row=cursor.fetchone()
    if row['owner']!=owner or row['connection_id']!=owner:
        raise RuntimeError('daily ETL lock ownership was lost')


def assert_guard_healthy():
    if _active_guard is not None and _active_guard.error is not None:
        raise RuntimeError('daily ETL lock session lost; further work is blocked') from _active_guard.error


def assert_daily_lock(conn):
    owner=os.getenv(OWNER_ENV);lock=os.getenv(LOCK_ENV)
    if not owner and not lock:return
    if not owner or not lock:raise RuntimeError('daily ETL lock ownership contract is incomplete')
    with conn.cursor() as cursor:
        cursor.execute('select is_used_lock(%s) as owner',(lock,))
        actual=cursor.fetchone()['owner']
    if actual!=int(owner):raise RuntimeError('daily ETL lock ownership was lost before publication')


@contextmanager
def daily_guard():
    global _active_guard
    conn=connect_target();lock='dashboard_daily_update:'+build_schema_config().target_schema
    acquired=False;thread=None;state=GuardState()
    prior={key:os.environ.get(key) for key in (OWNER_ENV,LOCK_ENV,DATA_DIRECTORY_ENV,DATA_DIRECTORY_OWNER_ENV)}
    try:
        with conn.cursor() as cursor:
            cursor.execute('select get_lock(%s,0) as acquired',(lock,))
            acquired=cursor.fetchone()['acquired']==1
        if not acquired:raise RuntimeError('daily ETL orchestrator is already running')
        with conn.cursor() as cursor:
            cursor.execute('select connection_id() as connection_id')
            owner=int(cursor.fetchone()['connection_id'])
        minimum=environment_number('DASHBOARD_DISK_STARTUP_MIN_GIB',40)
        free=assert_disk_budget(conn,minimum_gib=minimum,pin_owner=owner)
        conn._read_timeout=5;conn._write_timeout=5
        os.environ[OWNER_ENV]=str(owner);os.environ[LOCK_ENV]=lock
        def heartbeat():
            while not state.stop.wait(10):
                try:heartbeat_once(conn,lock,owner)
                except Exception as exc:
                    state.error=exc;return
        _active_guard=state
        thread=threading.Thread(target=heartbeat,daemon=True,name='daily-etl-lock-heartbeat')
        thread.start()
        print(f'[guard] daily lock acquired; database_disk_free_gib={free/1024**3:.2f}',flush=True)
        yield
        assert_guard_healthy()
    finally:
        state.stop.set()
        if thread is not None:
            thread.join(timeout=30)
            if thread.is_alive():
                # Closing the socket interrupts blocked I/O without sending a
                # second command concurrently on the PyMySQL connection.
                conn._force_close()
                thread.join(timeout=5)
        _active_guard=None
        if acquired and (thread is None or not thread.is_alive()) and getattr(conn,'open',True):
            with suppress(Exception):
                with conn.cursor() as cursor:cursor.execute('select release_lock(%s)',(lock,))
        conn.close()
        for key,value in prior.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def check_stage_disk():
    if not os.getenv('DASHBOARD_SHARED_PRODUCT_RUN'):return
    minimum=environment_number('DASHBOARD_DISK_STAGE_MIN_GIB',16)
    directory=pinned_data_directory()
    if directory is not None:
        return _local_disk_budget(directory,minimum)
    with connect_target() as conn:
        free=assert_disk_budget(conn,minimum_gib=minimum)
    return free
