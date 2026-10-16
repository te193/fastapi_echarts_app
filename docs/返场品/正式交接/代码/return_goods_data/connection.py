"""Read-only source connection; configure credentials outside the handoff files."""
from __future__ import annotations
import configparser
import os
from pathlib import Path
import pymysql


def apply_database_ini_env():
    path = Path(os.getenv('RETURN_GOODS_DB_CONFIG', 'config/database.ini'))
    parser = configparser.ConfigParser(interpolation=None)
    if path.exists():
        parser.read(path, encoding='utf-8-sig')
        if parser.has_section('source'):
            for field in ('host', 'port', 'user', 'password'):
                value = parser['source'].get(field)
                if value:
                    os.environ.setdefault('RETURN_GOODS_DB_' + field.upper(), value)


def _source_connect():
    missing = [k for k in ('HOST', 'USER', 'PASSWORD') if not os.getenv('RETURN_GOODS_DB_' + k)]
    if missing:
        raise ValueError('缺少远端只读连接配置: ' + ','.join(missing))
    return pymysql.connect(host=os.environ['RETURN_GOODS_DB_HOST'],
        port=int(os.getenv('RETURN_GOODS_DB_PORT', '3306')),
        user=os.environ['RETURN_GOODS_DB_USER'], password=os.environ['RETURN_GOODS_DB_PASSWORD'],
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, autocommit=False,
        read_timeout=300, connect_timeout=20, init_command='set session transaction read only')
