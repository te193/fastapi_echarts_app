"""Bounded per-connection resources for the serial label calculation."""
from contextlib import contextmanager


SORT_BUFFER_BYTES = 8 * 1024 * 1024
TEMP_TABLE_BYTES = 256 * 1024 * 1024


@contextmanager
def calculation_session(conn):
    """Reduce sort spills without changing global settings or numeric policy.

    TempTable's server-wide memory cap still applies. Respect an administrator's
    larger session values and restore both values on success or failure.
    """
    with conn.cursor() as q:
        q.execute('select @@session.sort_buffer_size as sort_bytes,@@session.tmp_table_size as temp_bytes')
        original = q.fetchone()
    before = (int(original['sort_bytes']), int(original['temp_bytes']))
    limits = (max(before[0], SORT_BUFFER_BYTES), max(before[1], TEMP_TABLE_BYTES))
    changed = limits != before
    failed = False
    try:
        if changed:
            with conn.cursor() as q:
                q.execute('set session sort_buffer_size=%s,tmp_table_size=%s', limits)
        yield {'sort_bytes':limits[0], 'temp_bytes':limits[1]}
    except BaseException:
        failed = True
        raise
    finally:
        if changed:
            try:
                with conn.cursor() as q:
                    q.execute('set session sort_buffer_size=%s,tmp_table_size=%s', before)
            except Exception:
                if not failed:
                    raise
