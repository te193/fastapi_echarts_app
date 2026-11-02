import importlib
import importlib.util

import pytest


def module():
    assert importlib.util.find_spec('etl.process_observability') is not None, 'tree memory sampler is missing'
    return importlib.import_module('etl.process_observability')


class Reader:
    def __init__(self, snapshots, records):
        self.snapshots = iter(snapshots)
        self.records = records
        self.read = []

    def process_parents(self):
        value=next(self.snapshots)
        if isinstance(value,Exception):raise value
        return value

    def process_memory(self,pid):
        self.read.append(pid)
        value=self.records[pid]
        if isinstance(value,Exception):raise value
        return {'working_set_bytes':value,'creation_time_100ns':pid*100}


def test_launcher_sample_includes_real_python_and_recursive_workers_only():
    sampler=module()
    tree={10:1,20:10,30:20,40:20,50:1}
    reader=Reader([tree,tree],{10:3,20:44,30:306,40:278,50:999})
    result=sampler.sample_process_tree(10,reader=reader)
    assert result['working_set_bytes']==631
    assert result['complete'] is True
    assert result['process_count']==4
    assert set(reader.read)=={10,20,30,40}
    assert result['measurement']=='sampled_process_tree_working_set_sum'
    assert result['atomic'] is False and result['hard_limit_enforced'] is False


def test_access_denied_child_makes_total_unknown_instead_of_launcher_only():
    sampler=module()
    tree={10:1,20:10}
    reader=Reader([tree,tree],{10:3,20:PermissionError(5,'private error detail')})
    result=sampler.sample_process_tree(10,reader=reader)
    assert result['complete'] is False
    assert result['working_set_bytes'] is None
    assert result['observed_working_set_bytes']==3
    assert result['unavailable_pids']==[20]
    assert 'private error detail' not in str(result)


def test_exited_root_cannot_be_reported_as_zero_memory():
    sampler=module()
    reader=Reader([{20:10}],{})
    result=sampler.sample_process_tree(10,reader=reader)
    assert result['working_set_bytes'] is None
    assert result['observed_working_set_bytes'] is None
    assert result['complete'] is False and result['sample_error']=='root_not_found'


@pytest.mark.parametrize('second_tree',[{10:1},{10:1,20:10,30:20}])
def test_tree_exit_or_spawn_during_measurement_is_explicitly_incomplete(second_tree):
    sampler=module()
    reader=Reader([{10:1,20:10},second_tree],{10:3,20:100})
    result=sampler.sample_process_tree(10,reader=reader)
    assert result['working_set_bytes'] is None
    assert result['complete'] is False and result['sample_error']=='tree_changed'


def test_failed_second_enumeration_does_not_pass_a_partial_total():
    sampler=module()
    reader=Reader([{10:1,20:10},OSError(5,'snapshot denied')],{10:3,20:100})
    result=sampler.sample_process_tree(10,reader=reader)
    assert result['working_set_bytes'] is None
    assert result['complete'] is False
    assert result['sample_error']=='enumeration_unavailable'


def test_pid_reuse_between_reads_is_not_accepted_as_the_same_worker():
    sampler=module()
    tree={10:1,20:10}
    reader=Reader([tree,tree],{10:3,20:100})
    original=reader.process_memory
    seen={}
    def memory(pid):
        value=original(pid)
        seen[pid]=seen.get(pid,0)+1
        if pid==20 and seen[pid]>1:value['creation_time_100ns']+=1
        return value
    reader.process_memory=memory
    result=sampler.sample_process_tree(10,reader=reader)
    assert result['working_set_bytes'] is None
    assert result['complete'] is False and result['sample_error']=='pid_reused'


@pytest.mark.parametrize('pid',[None,0,-1,True,'10'])
def test_invalid_pid_is_unknown_without_enumerating(pid):
    sampler=module()
    result=sampler.sample_process_tree(pid,reader=Reader([],{}))
    assert result['working_set_bytes'] is None and result['sample_error']=='invalid_pid'


def test_win32_backend_can_read_this_test_process_without_running_etl():
    import os
    sampler=module()
    if os.name!='nt':pytest.skip('Windows Toolhelp backend')
    result=sampler.sample_process_tree(os.getpid())
    assert result['complete'] is True
    assert result['working_set_bytes']>0
    assert result['root_creation_time_100ns']>0


def test_old_orphan_with_reused_parent_pid_cannot_inflate_tree_total():
    sampler=module()
    tree={10:1,20:10,30:20}
    reader=Reader([tree,tree],{10:3,20:100,30:999})
    original=reader.process_memory
    def memory(pid):
        record=original(pid)
        if pid==30:record['creation_time_100ns']=500
        return record
    reader.process_memory=memory
    value=sampler.sample_process_tree(10,reader=reader)
    assert value['complete'] is False and value['working_set_bytes'] is None
    assert value['sample_error']=='parent_pid_reused'


def fake_windows_reader(wait_results):
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace
    sampler=module()
    reader=sampler.WindowsProcessReader.__new__(sampler.WindowsProcessReader)
    class Memory(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('WorkingSetSize',ctypes.c_size_t)]
    waits=iter(wait_results);calls=[]
    def wait(handle,timeout):
        calls.append(('wait',timeout));return next(waits)
    def memory(handle,record,size):record._obj.WorkingSetSize=123;return True
    def times(handle,created,exited,kernel,user):
        created._obj.dwLowDateTime=456
        exited._obj.dwLowDateTime=999  # Undefined for live processes; must be ignored.
        return True
    reader.ctypes=ctypes;reader.Memory=Memory;reader.Filetime=wintypes.FILETIME
    reader.kernel=SimpleNamespace(OpenProcess=lambda flags,inherit,pid:calls.append(('open',flags)) or 42,
        CloseHandle=lambda handle:calls.append(('close',handle)),WaitForSingleObject=wait,GetProcessTimes=times)
    reader.psapi=SimpleNamespace(GetProcessMemoryInfo=memory)
    return reader,calls


@pytest.mark.parametrize('waits',[[0],[258,0]])
def test_already_exited_or_exit_during_memory_read_is_unknown(waits):
    reader,calls=fake_windows_reader(waits)
    with pytest.raises(ProcessLookupError):reader.process_memory(10)
    assert calls[-1]==('close',42)
    assert all(timeout==0 for name,timeout in calls if name=='wait')


def test_live_process_ignores_undefined_exit_time_and_checks_synchronize_handle():
    reader,calls=fake_windows_reader([258,258])
    assert reader.process_memory(10)=={'working_set_bytes':123,'creation_time_100ns':456}
    assert calls[0][1]&0x100000  # SYNCHRONIZE, no terminate permission.
    assert [entry for entry in calls if entry[0]=='wait']==[('wait',0),('wait',0)]
