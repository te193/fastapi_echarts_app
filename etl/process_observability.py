"""Read-only sampled process-tree working sets; never an enforcement budget.

The sum includes a venv launcher, its real interpreter and all descendants.
Shared pages can be counted in several processes. Samples are not atomic and
can miss peaks between observations; this is not unique physical RAM usage.
An inaccessible/exited/reused process or changing tree makes the total unknown.
Only the standard library and read-only Win32 handles are used.
"""
import os


def unknown_memory(root_pid, reason):
    return {'root_pid':root_pid, 'working_set_bytes':None,
        'observed_working_set_bytes':None, 'complete':False,
        'process_count':None, 'observed_process_count':0,
        'root_creation_time_100ns':None, 'unavailable_pids':[],
        'sample_error':reason, 'measurement':'sampled_process_tree_working_set_sum',
        'atomic':False, 'hard_limit_enforced':False}


def _tree(parents, root_pid):
    children={}
    for pid,parent in parents.items():
        children.setdefault(parent,[]).append(pid)
    found=set();pending=[root_pid]
    while pending:
        pid=pending.pop()
        if pid in found:continue
        found.add(pid)
        pending.extend(children.get(pid,()))
    return found


def _error(exc,pid=None):
    code=getattr(exc,'winerror',None) or getattr(exc,'errno',None)
    return {'pid':pid,'type':type(exc).__name__, 'code':code if type(code) is int else None}


def sample_process_tree(root_pid, *, reader=None):
    """A complete sample requires stable membership and process identities.

    The two membership snapshots and identity reads reduce exit/PID-reuse races;
    they do not freeze processes or make simultaneous memory measurements.
    """
    result=unknown_memory(root_pid,'invalid_pid')
    if type(root_pid) is not int or root_pid<=0:return result
    if reader is None:
        if os.name!='nt':return unknown_memory(root_pid,'unsupported_platform')
        try:reader=WindowsProcessReader()
        except Exception as exc:
            result.update(sample_error='backend_unavailable',errors=[_error(exc)])
            return result
    try:
        before=reader.process_parents()
        if root_pid not in before:return unknown_memory(root_pid,'root_not_found')
        members=_tree(before,root_pid)
    except Exception as exc:
        result.update(sample_error='enumeration_unavailable',errors=[_error(exc)])
        return result
    result.update(process_count=len(members),process_ids=sorted(members))
    records={};errors=[]
    for pid in sorted(members):
        try:
            record=reader.process_memory(pid)
            if (type(record['working_set_bytes']) is not int or record['working_set_bytes']<0
                    or type(record['creation_time_100ns']) is not int or record['creation_time_100ns']<=0):
                raise ValueError('invalid process measurement')
            records[pid]=record
        except Exception as exc:
            errors.append(_error(exc,pid))
    result.update(observed_process_count=len(records),
        observed_working_set_bytes=sum(r['working_set_bytes'] for r in records.values()) if records else None,
        root_creation_time_100ns=records.get(root_pid,{}).get('creation_time_100ns'),
        unavailable_pids=sorted(members-records.keys()))
    if errors:result['errors']=errors
    try:
        after=reader.process_parents()
        if (root_pid not in after or _tree(after,root_pid)!=members
                or any(after.get(pid)!=before.get(pid) for pid in members if pid!=root_pid)):
            result['sample_error']='tree_changed'
            return result
    except Exception as exc:
        result.update(sample_error='enumeration_unavailable',errors=errors+[_error(exc)])
        return result
    if errors:
        result['sample_error']='process_unavailable'
        return result
    # Toolhelp PPIDs survive a parent's exit. A recycled parent PID can make an
    # old orphan look like a descendant before both snapshots are even taken.
    if any(pid!=root_pid and records[pid]['creation_time_100ns']<
           records[before[pid]]['creation_time_100ns'] for pid in members):
        result['sample_error']='parent_pid_reused'
        return result
    for pid,record in records.items():
        try:
            if reader.process_memory(pid)['creation_time_100ns']!=record['creation_time_100ns']:
                result['sample_error']='pid_reused'
                return result
        except Exception as exc:
            result.update(sample_error='process_unavailable',unavailable_pids=[pid],errors=[_error(exc,pid)])
            return result
    result.update(complete=True,sample_error=None,working_set_bytes=result['observed_working_set_bytes'])
    return result


class WindowsProcessReader:
    """Toolhelp membership + GetProcessMemoryInfo/GetProcessTimes, no command lines."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.psapi=ctypes.WinDLL('psapi',use_last_error=True)

        class Entry(ctypes.Structure):
            _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
                ('th32ProcessID',wintypes.DWORD),('th32DefaultHeapID',ctypes.c_size_t),
                ('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
                ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),
                ('dwFlags',wintypes.DWORD),('szExeFile',wintypes.WCHAR*260)]

        class Memory(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[
                (name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize',
                'QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage',
                'QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]

        self.Entry=Entry;self.Memory=Memory;self.Filetime=wintypes.FILETIME
        self.kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
        for name in ('Process32FirstW','Process32NextW'):
            function=getattr(self.kernel,name)
            function.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]
            function.restype=wintypes.BOOL
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.kernel.CloseHandle.restype=wintypes.BOOL
        self.kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        self.kernel.OpenProcess.restype=wintypes.HANDLE
        self.psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
        self.psapi.GetProcessMemoryInfo.restype=wintypes.BOOL
        self.kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
        self.kernel.GetProcessTimes.restype=wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype=wintypes.DWORD

    def process_parents(self):
        ctypes=self.ctypes
        handle=self.kernel.CreateToolhelp32Snapshot(0x2,0)  # TH32CS_SNAPPROCESS
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry=self.Entry();entry.dwSize=ctypes.sizeof(entry)
            ctypes.set_last_error(0)
            available=self.kernel.Process32FirstW(handle,ctypes.byref(entry))
            parents={}
            while available:
                parents[int(entry.th32ProcessID)]=int(entry.th32ParentProcessID)
                ctypes.set_last_error(0)
                available=self.kernel.Process32NextW(handle,ctypes.byref(entry))
            error=ctypes.get_last_error()
            if error!=18:raise ctypes.WinError(error)  # ERROR_NO_MORE_FILES, not a failed partial tree
            return parents
        finally:self.kernel.CloseHandle(handle)

    def process_memory(self,pid):
        ctypes=self.ctypes
        # Query/VM read/SYNCHRONIZE only. Zero-time waits never block or stop work.
        handle=self.kernel.OpenProcess(0x1000|0x10|0x100000,False,pid)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._require_live(handle)
            memory=self.Memory();memory.cb=ctypes.sizeof(memory)
            if not self.psapi.GetProcessMemoryInfo(handle,ctypes.byref(memory),memory.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            created,exited,kernel,user=(self.Filetime() for _ in range(4))
            if not self.kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),
                                              ctypes.byref(kernel),ctypes.byref(user)):
                raise ctypes.WinError(ctypes.get_last_error())
            # ExitTime is undefined for a live process, so never inspect it.
            self._require_live(handle)
            return {'working_set_bytes':int(memory.WorkingSetSize),
                    'creation_time_100ns':(int(created.dwHighDateTime)<<32)|int(created.dwLowDateTime)}
        finally:self.kernel.CloseHandle(handle)

    def _require_live(self,handle):
        status=self.kernel.WaitForSingleObject(handle,0)
        if status==0x102:return  # WAIT_TIMEOUT: process is not signaled.
        if status==0:raise ProcessLookupError('process exited')
        if status==0xffffffff:raise self.ctypes.WinError(self.ctypes.get_last_error())
        raise OSError('unexpected process wait status')
