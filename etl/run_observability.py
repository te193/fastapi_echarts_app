"""Local, warning-only ETL observations. Never query DB, send, stop or clean work.

Configuration (environment): DASHBOARD_PROGRESS_DIR; DASHBOARD_OBSERVE_INTERVAL_SECONDS
(10); DASHBOARD_NO_PROGRESS_WARN_SECONDS (900); DASHBOARD_WARNING_INTERVAL_SECONDS
(300); DASHBOARD_DISK_WARN_GIB (24); DASHBOARD_DISK_STAGE_MIN_GIB (16);
DASHBOARD_DISK_EXPECTED_PEAK_GIB (unset means unknown). Warnings do not enforce
these budgets: existing guard boundaries remain the enforcement points.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time
from etl.process_observability import sample_process_tree, unknown_memory


GIB = 1024**3


def observe(observer, method, *args, **kwargs):
    """Keep monitor failures outside the runner's existing process-stop path."""
    try:
        return getattr(observer, method)(*args, **kwargs)
    except Exception:
        try:
            observer.snapshot_write_error = 'observer_error'
        except Exception:
            pass


def environment_number(name, default, *, allow_zero=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f'{name} must be a finite positive number') from None
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f'{name} must be a finite positive number')
    return value


@dataclass(frozen=True)
class ObservationConfig:
    sample_seconds: float = 10
    no_progress_seconds: float = 900
    warning_interval_seconds: float = 300
    warning_free_gib: float = 24
    boundary_min_gib: float = 16
    expected_peak_gib: float | None = None

    @classmethod
    def from_environment(cls):
        return cls(
            sample_seconds=environment_number('DASHBOARD_OBSERVE_INTERVAL_SECONDS', 10),
            no_progress_seconds=environment_number('DASHBOARD_NO_PROGRESS_WARN_SECONDS', 900),
            warning_interval_seconds=environment_number('DASHBOARD_WARNING_INTERVAL_SECONDS', 300),
            warning_free_gib=environment_number('DASHBOARD_DISK_WARN_GIB', 24),
            boundary_min_gib=environment_number('DASHBOARD_DISK_STAGE_MIN_GIB', 16),
            expected_peak_gib=environment_number('DASHBOARD_DISK_EXPECTED_PEAK_GIB', None, allow_zero=True),
        )


def atomic_json_write(path, value):
    """One writer per path. A failed replacement leaves the prior JSON readable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
    os.replace(temporary, path)


_RESULT = re.compile(r'^\[success\]\s+([A-Za-z0-9_.-]+):.*?\b(?:affected_rows|rows)=(\d+)\b')
_IDENTITY = re.compile(r'[\w.:-]{1,160}', re.UNICODE)
_EVENT_FIELDS = {
    'scope_ready': ('done', 'total'),
    'traffic_block': ('objects',),
    'source_delta_copy': ('rows',),
    'source_progress': ('rows',),
    'source_incremental_complete': ('rows', 'transferred_rows'),
    'calculate_complete': ('fact_rows', 'evidence_rows'),
    'calculate_step_complete': (),
}


def evidenced_progress(line):
    """Copy only recognized evidence, never raw logs, SQL parameters or secrets."""
    match = _RESULT.match(line)
    if match:
        return {'event': 'step_result', 'unit': match[1], 'rows': int(match[2])}
    try:
        value = json.loads(line)
    except (ValueError, TypeError):
        return None
    if (not isinstance(value, dict) or not isinstance(value.get('stage'), str)
            or value['stage'] not in _EVENT_FIELDS):
        return None
    event = value['stage']
    result = {'event': event}
    for field in _EVENT_FIELDS[event]:
        count = value.get(field)
        if isinstance(count, str) and count.isascii() and count.isdecimal():
            count = int(count)
        if type(count) is not int or count < 0:
            return None
        result[field] = count
    if 'done' in result and result['done'] > result['total']:
        return None
    unit = value.get('step') or value.get('local_name') or value.get('source')
    if isinstance(unit, str) and _IDENTITY.fullmatch(unit):
        result['unit'] = unit
    if not _EVENT_FIELDS[event] and 'unit' not in result:
        return None
    for field in ('start', 'end', 'date'):
        if isinstance(value.get(field), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value[field]):
            result[field] = value[field]
    return result


class RunObserver:
    def __init__(self, path, run_stamp, *, config=None, database_directory=None,
                 monotonic=time.monotonic, now=None, disk_usage=shutil.disk_usage,
                 warning_sink=None, process_sampler=None):
        self.path = Path(path)
        self.config = config or ObservationConfig.from_environment()
        self.monotonic = monotonic
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.disk_usage = disk_usage
        self.warning_sink = warning_sink or (lambda _: None)
        self.process_sampler = process_sampler or sample_process_tree
        self._process_roots = {}
        self._process_tokens = {}
        self._process_cache = {}
        self._process_peaks = {}
        self._process_pending = {}
        self._memory_collecting = False
        self._memory_thread = None
        self._memory_wake = threading.Event()
        self.started = monotonic()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._last_tick = None
        self._step_times = {}
        self._disk_times = {}
        self._warning_times = {}
        self.snapshot_write_error = None
        self._directories = {'observation': self.path.parent}
        if database_directory is not None:
            self._directories['database'] = Path(database_directory)
        self.state = {'schema_version': 'etl-observability-v1', 'run_stamp': run_stamp,
            'started_at_utc': self._utc(), 'status': 'running', 'exit_code': None,
            'config': asdict(self.config), 'steps': {}, 'disks': {},
            'warnings': {}, 'notifications': [], 'snapshot_write_error': None,
            'transaction_state': 'not_observed'}

    def _utc(self):
        current = self.now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat()

    def begin_step(self, key, stdout, stderr):
        with self._lock:
            self._process_tokens[key] = object()
            self._process_roots.pop(key, None)
            self._process_cache.pop(key, None)
            self._process_peaks.pop(key, None)
            self._step_times[key] = {'started': self.monotonic(), 'progress': None}
            self.state['steps'][key] = {'status': 'running', 'started_at_utc': self._utc(),
                'child_pid': None, 'child_alive': None, 'stdout': str(stdout), 'stderr': str(stderr),
                'last_log_activity_at_utc': None, 'last_business_progress_at_utc': None,
                'business_progress': None}
        self.tick(force=True)

    def child_started(self, key, pid):
        with self._lock:
            if key in self.state['steps']:
                self._process_roots.pop(key,None)
                self._process_tokens[key] = object()
                self._process_cache.pop(key, None)
                self.state['steps'][key].update(child_pid=pid if type(pid) is int else None,
                                               child_alive=True)
        self._memory_wake.set()

    def record_output(self, key, line, stream='stdout'):
        with self._lock:
            item = self.state['steps'].get(key)
            if item is None:
                return
            item['last_log_activity_at_utc'] = self._utc()
            progress = evidenced_progress(line)
            if progress is not None and progress != item['business_progress']:
                item['business_progress'] = progress
                item['last_business_progress_at_utc'] = self._utc()
                self._step_times[key]['progress'] = self.monotonic()

    def finish_step(self, key, status, exit_code, *, child_exit_confirmed=True):
        with self._lock:
            item = self.state['steps'].get(key)
            if item is not None:
                item.update(status=status, exit_code=exit_code,
                            child_alive=False if child_exit_confirmed else None,
                            child_exit_confirmed=child_exit_confirmed,
                            finished_at_utc=self._utc(),
                            elapsed_seconds=max(0,self.monotonic()-self._step_times[key]['started']))
        self.tick(force=True)

    def notifications(self, records):
        with self._lock:
            self.state['notifications'] = [dict(record) for record in records]
        self.tick(force=True)

    def complete(self, status, exit_code):
        with self._lock:
            self.state.update(status=status, exit_code=exit_code, finished_at_utc=self._utc())
        self.tick(force=True)

    def _warning(self, key, current, messages):
        record = self.state['warnings'].setdefault(key,
            {'count': 0, 'first_seen_at_utc': self._utc()})
        record.update(active=True,last_seen_at_utc=self._utc())
        previous = self._warning_times.get(key)
        if previous is None or current - previous >= self.config.warning_interval_seconds:
            self._warning_times[key] = current
            record.update(count=record['count'] + 1, last_emitted_at_utc=self._utc())
            messages.append(f'[warn] observation {key}; warning only; active work is not stopped')

    def _sample_disk(self, name, directory, current, messages):
        item = self.state['disks'].setdefault(name, {'directory': str(directory),
            'initial_free_bytes': None, 'min_free_bytes': None, 'peak_consumed_bytes': 0})
        previous_free = item.get('free_bytes')
        previous_time = self._disk_times.get(name)
        try:
            free = self.disk_usage(directory).free
        except OSError as exc:
            item.update(free_bytes=None, sample_error=type(exc).__name__,
                        free_bytes_per_second=None, sampled_at_utc=self._utc())
            self._warning('disk_sample_unavailable:' + name, current, messages)
            return
        if item['initial_free_bytes'] is None:
            item['initial_free_bytes'] = free
        minimum = item['min_free_bytes']
        item.update(free_bytes=free, sample_error=None, sampled_at_utc=self._utc(),
            min_free_bytes=free if minimum is None else min(free, minimum),
            free_bytes_per_second=((free - previous_free) / (current - previous_time)
                if previous_free is not None and previous_time is not None and current > previous_time else None))
        item['peak_consumed_bytes'] = max(0, item['initial_free_bytes'] - item['min_free_bytes'])
        self._disk_times[name] = current
        required = ((self.config.boundary_min_gib + self.config.expected_peak_gib) * GIB
                    if name == 'database' and self.config.expected_peak_gib is not None else None)
        item['required_capacity_bytes'] = required
        if free < self.config.warning_free_gib * GIB:
            self._warning('disk_low:' + name, current, messages)
        if required is not None and free < required:
            self._warning('disk_budget:' + name, current, messages)

    def _collect_process_samples(self):
        """Only the single memory daemon calls native I/O, always outside _lock.

        A hung backend occupies this daemon, never the runner or heartbeat.
        Tokens discard results from a replaced PID or a newly begun same-name step.
        """
        with self._lock:
            if self._memory_collecting or self._stop.is_set():
                return
            self._memory_collecting = True
            targets = [(key, item['child_pid'], self._process_tokens[key])
                for key, item in self.state['steps'].items()
                if self.state['status'] == 'running' and item['status'] == 'running'
                and item.get('child_alive') is True
                and type(item.get('child_pid')) is int and item['child_pid'] > 0]
        try:
            for key, pid, token in targets:
                with self._lock:
                    if self._stop.is_set() or self._process_tokens.get(key) is not token:
                        continue
                    self._process_pending[key] = token
                started = self.monotonic()
                sampled_at = self._utc()
                try:
                    value = dict(self.process_sampler(pid))
                except Exception:
                    value = unknown_memory(pid, 'sampler_unavailable')
                with self._lock:
                    if self._process_pending.get(key) is token:
                        self._process_pending.pop(key, None)
                    item = self.state['steps'].get(key)
                    if (self._stop.is_set() or self.state['status'] != 'running'
                            or self._process_tokens.get(key) is not token or item is None
                            or item['status'] != 'running' or item.get('child_pid') != pid
                            or item.get('child_alive') is not True):
                        continue
                    total = value.get('working_set_bytes')
                    identity = value.get('root_creation_time_100ns')
                    readable_identity = type(identity) is int and identity > 0
                    first = self._process_roots.setdefault(key, identity) if readable_identity else None
                    valid = (value.get('complete') is True and type(total) is int and total >= 0
                             and readable_identity)
                    if readable_identity and first != identity:
                        value.update(complete=False, working_set_bytes=None, sample_error='root_pid_reused')
                    elif not valid:
                        value.update(complete=False, working_set_bytes=None)
                    elif self.monotonic() - started > self._memory_fresh_seconds():
                        value = unknown_memory(pid, 'sample_stale')
                    else:
                        previous = self._process_peaks.get(key)
                        self._process_peaks[key] = total if previous is None else max(previous, total)
                    self._process_cache[key] = (token, pid, started, sampled_at, value)
        finally:
            with self._lock:
                self._memory_collecting = False

    def _memory_fresh_seconds(self):
        return max(1.0, 2 * self.config.sample_seconds)

    def _sample_process(self, key, item):
        """Read cache only: runner calls never invoke or wait for native sampling."""
        pid = item.get('child_pid')
        token = self._process_tokens.get(key)
        sampled_at = self._utc()
        age = None
        if item['status'] != 'running' or item.get('child_alive') is not True:
            reason = ('child_exit_unconfirmed' if item.get('child_exit_confirmed') is False
                      else 'child_not_running')
            value = unknown_memory(pid, reason)
        elif type(pid) is not int or pid <= 0:
            value = unknown_memory(pid, 'child_pid_unknown')
        elif self._process_pending.get(key) is token:
            value = unknown_memory(pid, 'sample_pending')
        else:
            cached = self._process_cache.get(key)
            if cached is None or cached[0] is not token or cached[1] != pid:
                value = unknown_memory(pid, 'sample_pending')
            else:
                _, _, started, sampled_at, cached_value = cached
                age = max(0, self.monotonic() - started)
                value = (unknown_memory(pid, 'sample_stale') if age > self._memory_fresh_seconds()
                         else dict(cached_value))
        value.update(sampled_at_utc=sampled_at, sample_age_seconds=age,
                     fresh_for_seconds=self._memory_fresh_seconds(),
                     peak_observed_working_set_bytes=self._process_peaks.get(key),
                     measurement='sampled_process_tree_working_set_sum', atomic=False,
                     hard_limit_enforced=False)
        item['process_tree_memory'] = value

    def tick(self, *, force=False):
        """Sampling and snapshot errors are observations, never work failures."""
        messages = []
        with self._lock:
            current = self.monotonic()
            if not force and self._last_tick is not None and current - self._last_tick < self.config.sample_seconds:
                return
            self._last_tick = current
            self.state.update(observed_at_utc=self._utc(),observer_heartbeat_at_utc=self._utc(),
                              elapsed_seconds=max(0, current - self.started))
            for warning in self.state['warnings'].values():
                warning['active']=False
            self.state['active_stages'] = [key for key,item in self.state['steps'].items() if item['status']=='running']
            for key, item in self.state['steps'].items():
                self._sample_process(key,item)
                times = self._step_times[key]
                if item['status'] == 'running':
                    item['elapsed_seconds'] = max(0, current - times['started'])
                since = times['progress'] if times['progress'] is not None else times['started']
                item['seconds_without_business_progress'] = max(0, current - since)
                for stream in ('stdout', 'stderr'):
                    try:
                        item[stream + '_bytes'] = Path(item[stream]).stat().st_size
                    except OSError:
                        item[stream + '_bytes'] = None
                if item['status'] == 'running' and current - since >= self.config.no_progress_seconds:
                    self._warning('no_progress:' + key, current, messages)
            # The directory is pinned by the guard, never discovered by a DB call here.
            for name, directory in self._directories.items():
                self._sample_disk(name, directory, current, messages)
            self.state['snapshot_write_error'] = self.snapshot_write_error
            try:
                atomic_json_write(self.path, self.state)
                self.snapshot_write_error = None
            except (OSError, ValueError, TypeError) as exc:
                self.snapshot_write_error = type(exc).__name__
                self._warning('snapshot_write_unavailable', current, messages)
        for message in messages:
            try:
                self.warning_sink(message)
            except Exception:
                pass

    def start(self):
        if self._thread is not None:
            return
        self.tick(force=True)
        def sample():
            while not self._stop.wait(self.config.sample_seconds):
                try:
                    self.tick()
                except Exception:
                    # A monitor bug must not be promoted into a guard/transaction error.
                    self.snapshot_write_error = 'observer_error'
        def memory():
            while not self._stop.is_set():
                try:
                    self._collect_process_samples()
                except Exception:
                    pass  # No failure can enter the guard or runner error path.
                self._memory_wake.wait(self.config.sample_seconds)
                self._memory_wake.clear()
        self._thread = threading.Thread(target=sample, daemon=True, name='daily-etl-observation')
        self._memory_thread = threading.Thread(target=memory, daemon=True, name='daily-etl-memory-observation')
        self._thread.start()
        self._memory_thread.start()

    def close(self):
        self._stop.set()
        self._memory_wake.set()
        deadline = time.monotonic() + 1
        for thread in (self._thread, self._memory_thread):
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0, deadline - time.monotonic()))
