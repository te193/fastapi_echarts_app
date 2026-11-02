"""One-shot sanitized diagnosis of one local progress snapshot.

No business imports, native sampling, DB, network, log reads or background work.
Exit 0 means diagnosis completed, never publication or notification confirmation.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 4 * 1024**2
SCHEMA = 'etl-observability-v1'
STEPS = frozenset(('source_preflight', 'dashboard', 'replenishment', 'replenishment_tracking',
    'product_history', 'sales_role', 'return_goods', 'pricing', 'label_evidence',
    'stockout_historical_operating', 'return_strategy', 'label_analysis'))
EVENTS = {'step_result': ('rows',), 'scope_ready': ('done', 'total'),
    'traffic_block': ('objects',), 'source_delta_copy': ('rows',), 'source_progress': ('rows',),
    'source_incremental_complete': ('rows', 'transferred_rows'),
    'calculate_complete': ('fact_rows', 'evidence_rows'), 'calculate_step_complete': ()}


class InputProblem(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _number(value, *, positive=False):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def _count(value):
    return type(value) is int and value >= 0


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise InputProblem('invalid_timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise InputProblem('invalid_timestamp') from None


def _age(value, now):
    parsed = _time(value)
    seconds = (now - parsed).total_seconds()
    if seconds < -5:
        raise InputProblem('future_timestamp')
    return max(0.0, seconds)


def _optional_age(value, now):
    return None if value is None else _age(value, now)


def _base(reason='observation_unavailable'):
    return {'schema_version': 'etl-run-diagnostic-v1', 'state': 'observation_unknown',
        'reason': reason, 'run_stamp': None, 'run_status': None, 'terminal': None,
        'snapshot_age_seconds': None, 'file_age_seconds': None,
        'observer_heartbeat_age_seconds': None, 'steps': [], 'disks': [],
        'warning_only': True, 'publication_verified': False,
        'notification_receipt_verified': False}


def _business(value):
    if not isinstance(value, dict) or not isinstance(value.get('event'), str) or value['event'] not in EVENTS:
        raise InputProblem('invalid_business_evidence')
    result = {'event': value['event']}
    unit = value.get('unit')
    if (unit is not None or value['event'] in ('step_result', 'calculate_step_complete')):
        if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', unit):
            raise InputProblem('invalid_business_evidence')
    for name in EVENTS[value['event']]:
        count = value.get(name)
        if not _count(count):
            raise InputProblem('invalid_business_evidence')
        result[name] = count
    if result.get('done', 0) > result.get('total', float('inf')):
        raise InputProblem('invalid_business_evidence')
    # Identities, units, raw logs, SQL, parameters and date strings are omitted.
    return result


def _memory(value, pid, now, fresh_seconds):
    result = {'measurement': 'sampled_process_tree_working_set_sum', 'cached_observation': True,
        'complete': False, 'reason': 'cached_memory_unavailable', 'working_set_bytes': None,
        'peak_observed_working_set_bytes': None, 'peak_kind': 'maximum_of_complete_samples',
        'age_seconds': None, 'atomic': False, 'hard_limit_enforced': False}
    if not isinstance(value, dict):
        return result
    peak = value.get('peak_observed_working_set_bytes')
    if _count(peak):
        result['peak_observed_working_set_bytes'] = peak
    if value.get('sample_error') == 'sample_pending':
        result['reason'] = 'sample_pending'
        return result
    try:
        age = _age(value.get('sampled_at_utc'), now)
        result['age_seconds'] = age
        stored_age = value.get('sample_age_seconds')
        validity = value.get('fresh_for_seconds')
        if not _number(stored_age) or not _number(validity, positive=True):
            raise InputProblem('invalid_cached_memory')
        age = max(age, stored_age)
        result['age_seconds'] = age
        if age > min(fresh_seconds, validity) or value.get('sample_error') == 'sample_stale':
            result['reason'] = 'sample_stale'
            return result
        count = value.get('process_count')
        total = value.get('working_set_bytes')
        if (value.get('measurement') != result['measurement'] or value.get('atomic') is not False
                or value.get('hard_limit_enforced') is not False or value.get('root_pid') != pid
                or type(value.get('root_pid')) is not int
                or type(value.get('root_creation_time_100ns')) is not int
                or value['root_creation_time_100ns'] <= 0):
            raise InputProblem('invalid_cached_memory')
        if value.get('complete') is not True or value.get('sample_error') is not None:
            result['reason'] = 'partial_or_unavailable'
            return result
        if (not _count(total) or not _count(count) or count < 1
                or type(value.get('observed_process_count')) is not int
                or value['observed_process_count'] != count
                or not _count(value.get('observed_working_set_bytes'))
                or value['observed_working_set_bytes'] != total
                or peak is None or not _count(peak) or peak < total):
            raise InputProblem('invalid_cached_memory')
        result.update(complete=True, reason='fresh_cached_complete_sample', working_set_bytes=total)
    except InputProblem:
        result['reason'] = 'invalid_cached_memory'
    return result


def _disk(name, value, now, fresh_seconds):
    result = {'name': name, 'measurement': 'stored_snapshot_disk_free', 'live_measurement': False,
        'valid': False, 'reason': 'stored_disk_unavailable', 'free_bytes': None,
        'min_free_bytes': None, 'peak_consumed_bytes': None, 'age_seconds': None}
    if not isinstance(value, dict):
        return result
    try:
        age = _age(value.get('sampled_at_utc'), now)
        result['age_seconds'] = age
        if age > fresh_seconds:
            result['reason'] = 'stored_disk_stale'
            return result
        for field in ('free_bytes', 'min_free_bytes', 'peak_consumed_bytes'):
            if not _count(value.get(field)):
                raise InputProblem('invalid_disk_observation')
        if value['min_free_bytes'] > value['free_bytes']:
            raise InputProblem('invalid_disk_observation')
        result.update(valid=True, reason='fresh_stored_observation', **{
            field: value[field] for field in ('free_bytes', 'min_free_bytes', 'peak_consumed_bytes')})
    except InputProblem:
        result['reason'] = 'invalid_disk_observation'
    return result


def _step(key, value, now, no_progress_seconds, fresh_seconds, observed_age):
    result = {'key': key, 'state': 'observation_unknown', 'reason': 'invalid_step_observation',
        'step_status': None, 'child_pid': None, 'child_alive': None, 'elapsed_seconds': None,
        'last_business_evidence_age_seconds': None, 'seconds_without_business_progress': None,
        'last_log_activity_age_seconds': None, 'business_progress': None}
    if not isinstance(value, dict):
        return result
    status = value.get('status')
    if status in ('running', 'success', 'failed'):
        result['step_status'] = status
    pid = value.get('child_pid')
    if type(pid) is int and pid > 0:
        result['child_pid'] = pid
    alive = value.get('child_alive')
    if type(alive) is bool:
        result['child_alive'] = alive
    result['process_tree_memory'] = _memory(value.get('process_tree_memory'), result['child_pid'], now, fresh_seconds)
    try:
        started = _age(value.get('started_at_utc'), now)
        log_age = _optional_age(value.get('last_log_activity_at_utc'), now)
        evidence_age = _optional_age(value.get('last_business_progress_at_utc'), now)
        if (log_age is not None and log_age > started + 5) or (evidence_age is not None and evidence_age > started + 5):
            raise InputProblem('invalid_timestamp_order')
        if any(age is not None and age + 5 < observed_age for age in (started, log_age, evidence_age)):
            raise InputProblem('invalid_timestamp_order')
        elapsed = started
        if status in ('success', 'failed'):
            finished = _time(value.get('finished_at_utc'))
            finished_age = _age(value.get('finished_at_utc'), now)
            elapsed = (finished - _time(value.get('started_at_utc'))).total_seconds()
            if (elapsed < 0 or finished_age + 5 < observed_age
                    or any(age is not None and age + 5 < finished_age for age in (log_age, evidence_age))):
                raise InputProblem('invalid_timestamp_order')
            if 'elapsed_seconds' in value:
                stored = value['elapsed_seconds']
                # Observer duration uses monotonic time while timestamps use UTC.
                # Permit small sampling/clock rounding, never a growing duration.
                if not _number(stored) or abs(stored - elapsed) > 1:
                    raise InputProblem('inconsistent_elapsed_duration')
        elif status == 'running' and value.get('finished_at_utc') is not None:
            raise InputProblem('invalid_timestamp_order')
        result.update(elapsed_seconds=elapsed, last_log_activity_age_seconds=log_age,
                      last_business_evidence_age_seconds=evidence_age)
        evidence = value.get('business_progress')
        if evidence_age is not None:
            result['business_progress'] = _business(evidence)
        elif evidence is not None:
            raise InputProblem('invalid_business_evidence')
        business_clock = started if evidence_age is None else evidence_age
        result['seconds_without_business_progress'] = business_clock
        confirmed = value.get('child_exit_confirmed')
        if confirmed is not None and type(confirmed) is not bool:
            raise InputProblem('invalid_child_state')
        if result['step_status'] is None or result['child_pid'] is None or type(alive) is not bool:
            raise InputProblem('child_state_unknown')
        if confirmed is True and alive is True:
            raise InputProblem('inconsistent_child_state')
        if alive is False or confirmed is True:
            result.update(state='child_exited_terminal_unconfirmed', reason='child_exit_recorded_run_not_terminal')
        elif status != 'running':
            raise InputProblem('inconsistent_child_state')
        elif business_clock >= no_progress_seconds:
            result.update(state='running_without_observed_business_progress', reason='business_progress_not_observed_within_threshold')
        elif result['business_progress'] is not None:
            result.update(state='running_with_progress', reason='recent_recognized_business_evidence')
        else:
            result['reason'] = 'business_progress_not_yet_observed'
    except InputProblem as error:
        result['reason'] = error.reason
    return result


def diagnose_snapshot(payload, *, now=None, file_mtime=None, no_progress_seconds=900, fresh_seconds=120):
    """Pure allowlist projection. Ages describe stored observations, not live probes."""
    result = _base()
    try:
        now = now or datetime.now(timezone.utc)
        if (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset().total_seconds() != 0):
            raise InputProblem('invalid_diagnostic_clock')
        if not _number(no_progress_seconds, positive=True) or not _number(fresh_seconds, positive=True):
            raise InputProblem('invalid_options')
        if not isinstance(payload, dict):
            raise InputProblem('invalid_payload')
        if payload.get('schema_version') != SCHEMA:
            raise InputProblem('unsupported_schema')
        identity = payload.get('run_stamp')
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9]{8}_[0-9]{6}', identity):
            raise InputProblem('invalid_run_identity')
        try:
            datetime.strptime(identity, '%Y%m%d_%H%M%S')
        except ValueError:
            raise InputProblem('invalid_run_identity') from None
        result['run_stamp'] = identity
        status = payload.get('status')
        if status not in ('running', 'success', 'failed'):
            raise InputProblem('invalid_run_status')
        result['run_status'] = status
        observed = _age(payload.get('observed_at_utc'), now)
        started = _age(payload.get('started_at_utc'), now)
        heartbeat = _age(payload.get('observer_heartbeat_at_utc'), now)
        if not _number(file_mtime):
            raise InputProblem('invalid_file_timestamp')
        file_age = now.timestamp() - file_mtime
        if file_age < -5:
            raise InputProblem('future_file_timestamp')
        result.update(snapshot_age_seconds=observed, file_age_seconds=max(0, file_age),
                      observer_heartbeat_age_seconds=heartbeat)
        if observed > started + 5 or heartbeat > started + 5 or heartbeat + 5 < observed:
            raise InputProblem('invalid_timestamp_order')
        if status in ('success', 'failed'):
            code = payload.get('exit_code')
            finished = _age(payload.get('finished_at_utc'), now)
            if (type(code) is not int or (status == 'success' and code != 0)
                    or (status == 'failed' and code == 0)):
                raise InputProblem('inconsistent_terminal')
            if finished > started + 5 or finished + 5 < observed:
                raise InputProblem('invalid_timestamp_order')
            result.update(state='terminal_recorded', reason='local_terminal_record_only',
                terminal={'status': status, 'exit_code': code,
                          'finished_at_utc': _time(payload['finished_at_utc']).isoformat()})
            return result
        if payload.get('exit_code') is not None or payload.get('finished_at_utc') is not None:
            raise InputProblem('inconsistent_running_record')
        if observed > fresh_seconds or heartbeat > fresh_seconds or file_age > fresh_seconds:
            raise InputProblem('snapshot_stale')
        steps = payload.get('steps')
        if not isinstance(steps, dict) or not steps:
            raise InputProblem('steps_unavailable')
        unknown_key = False
        for key, value in steps.items():
            if key not in STEPS:
                unknown_key = True
                continue
            result['steps'].append(_step(key, value, now, no_progress_seconds, fresh_seconds, observed))
        disks = payload.get('disks', {})
        if isinstance(disks, dict):
            for name in ('observation', 'database'):
                if name in disks:
                    result['disks'].append(_disk(name, disks[name], now, fresh_seconds))
        active = [s for s in result['steps'] if s['step_status'] == 'running'] or result['steps']
        if unknown_key or not active or any(s['state'] == 'observation_unknown' for s in active):
            raise InputProblem('step_observation_unknown')
        for state in ('child_exited_terminal_unconfirmed', 'running_without_observed_business_progress', 'running_with_progress'):
            if any(s['state'] == state for s in active):
                result.update(state=state, reason='per_stage_observations')
                break
    except InputProblem as error:
        result.update(state='observation_unknown', reason=error.reason)
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputProblem('invalid_arguments')  # Never echo a path, option value or exception message.


def _positive(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('invalid positive number') from None
    if not _number(number, positive=True):
        raise argparse.ArgumentTypeError('invalid positive number')
    return number


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise InputProblem('invalid_json')
        result[key] = value
    return result


def _invalid_constant(value):
    raise InputProblem('invalid_json')


def main(argv=None, *, now=None):
    """Read one regular file in one bounded read and print exactly one JSON result."""
    try:
        parser = _Parser(description='Diagnose one stored local ETL progress snapshot.')
        parser.add_argument('--progress', required=True, metavar='PATH')
        parser.add_argument('--no-progress-seconds', type=_positive, default=900)
        parser.add_argument('--fresh-seconds', type=_positive, default=120)
        args = parser.parse_args(argv)
        with Path(args.progress).open('rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise InputProblem('input_not_regular_file')
            if metadata.st_size > MAX_BYTES:
                raise InputProblem('input_too_large')
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise InputProblem('input_too_large')
        payload = json.loads(raw.decode('utf-8'), parse_constant=_invalid_constant, object_pairs_hook=_pairs)
        if not isinstance(payload, dict):
            raise InputProblem('invalid_payload')
        result = diagnose_snapshot(payload, now=now, file_mtime=metadata.st_mtime,
            no_progress_seconds=args.no_progress_seconds, fresh_seconds=args.fresh_seconds)
        code = 0
    except InputProblem as error:
        result = _base(error.reason)
        code = 2
    except (UnicodeError, ValueError, RecursionError):
        result = _base('invalid_json')
        code = 2
    except OSError:
        result = _base('input_unavailable')
        code = 2
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
