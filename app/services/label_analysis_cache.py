"""Local, source-validated prepared snapshots; never generates business data."""
import hashlib
import os
from pathlib import Path
import pickle
import tempfile
import time


class PreparedSnapshotCache:
    def __init__(self,directory):
        self.directory=Path(directory)
        source=Path(__file__).parent
        self.code_revision=hashlib.sha256(b''.join((source/name).read_bytes() for name in (
            'label_analysis_cache.py','label_analysis_engine.py','label_analysis_metrics.py',
            'label_analysis_repository.py','label_analysis_service.py','label_analysis_inventory.py','label_analysis_traffic.py','replenishment_data.py'))).hexdigest()

    def _path(self,key):
        name=hashlib.sha256(repr((key,self.code_revision)).encode()).hexdigest()
        return self.directory/(name+'.pkl')

    def read(self,key,revision):
        try:
            with self._path(key).open('rb') as f:stored=pickle.load(f)
            if stored['revision']!=revision or time.time()-stored['saved_at']>86400:return None
            return stored['data']
        except (OSError,EOFError,pickle.UnpicklingError,ValueError,KeyError):return None

    def write(self,key,revision,data):
        temporary=None
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.directory,suffix='.tmp',delete=False) as f:
                temporary=f.name
                pickle.dump(dict(revision=revision,saved_at=time.time(),data=data),f,protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(temporary,self._path(key));temporary=None
            # Limit local disk usage to the three most recently prepared datasets.
            files=sorted(self.directory.glob('*.pkl'),key=lambda p:p.stat().st_mtime,reverse=True)
            for path in files[3:]:path.unlink(missing_ok=True)
        except OSError:pass  # Cache failure must not prevent a successful data read.
        finally:
            if temporary:
                try:Path(temporary).unlink(missing_ok=True)
                except OSError:pass
