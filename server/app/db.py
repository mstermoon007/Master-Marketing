"""MySQL 8 数据访问基础层。

设计要点：
- 主键统一为字符串 id（24 位 hex，形态接近云数据库 _id），前端拿到的就是 `id`，
  旧云函数里的 normalize(_id -> id) 逻辑因此可以直接退休，页面零改动。
- 时间统一存 ISO8601 UTC 字符串（...Z），与旧云函数 new Date().toISOString() 完全一致，
  避免 records.js 里 new Date(created_at) 的"补录"判定发生漂移。
- 所有 SQL 均参数化，禁止字符串拼接用户输入。
"""
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import pymysql
from pymysql.cursors import DictCursor

from . import config

# 表名 -> 需要反序列化的 JSON 列
JSON_COLUMNS: Dict[str, List[str]] = {
    "teams": ["config"],
    "members": [],
    "form_templates": ["fields", "scope"],
    "daily_entries": ["form_data"],
    "audit_logs": ["detail"],
}


@contextmanager
def connection() -> Iterator[pymysql.connections.Connection]:
    conn = pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    """与 JS new Date().toISOString() 同形：2026-11-09T09:08:02.000Z"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def gen_id() -> str:
    return secrets.token_hex(12)


def jdump(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def row_to_dict(row: Optional[dict], table: str) -> Optional[dict]:
    """把数据库行转成前端期望的普通对象；JSON 列反序列化。"""
    if row is None:
        return None
    out = dict(row)
    for col in JSON_COLUMNS.get(table, []):
        raw = out.get(col)
        if isinstance(raw, (str, bytes)):
            try:
                out[col] = json.loads(raw)
            except (ValueError, TypeError):
                out[col] = None
    return out


def rows_to_dicts(rows: List[dict], table: str) -> List[dict]:
    return [row_to_dict(r, table) for r in rows]


def query(conn, sql: str, args=None) -> List[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, args or ())
        return list(cur.fetchall())


def one(conn, sql: str, args=None) -> Optional[dict]:
    rows = query(conn, sql, args)
    return rows[0] if rows else None


def execute(conn, sql: str, args=None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, args or ())
        return cur.rowcount


_ALLOWED_TABLES = frozenset(JSON_COLUMNS.keys())
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_table(table: str) -> str:
    """表名必须是代码内登记的白名单，杜绝任意表访问。"""
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"非法表名 {table}")
    return table


def _check_column(name: str) -> str:
    """列名必须匹配标识符正则（用于动态拼接的 SET / INSERT 列名）。"""
    if not isinstance(name, str) or not _IDENT_RE.fullmatch(name):
        raise ValueError(f"非法列名 {name}")
    return name


def get_doc(conn, table: str, doc_id: str) -> Optional[dict]:
    _check_table(table)
    return row_to_dict(one(conn, f"SELECT * FROM `{table}` WHERE id = %s", (doc_id,)), table)


def get_doc_by_field(conn, table: str, field: str, value) -> Optional[dict]:
    """按白名单字段查单行（字段名为代码内常量，值参数化）。"""
    _check_table(table)
    _check_column(field)
    return row_to_dict(one(conn, f"SELECT * FROM `{table}` WHERE `{field}` = %s LIMIT 1", (value,)), table)


def insert(conn, table: str, data: dict) -> str:
    """写入一行并返回生成的字符串主键。"""
    _check_table(table)
    payload = dict(data)
    doc_id = payload.get("id") or gen_id()
    payload["id"] = doc_id
    for col in JSON_COLUMNS.get(table, []):
        if col in payload and not isinstance(payload[col], (str, bytes)):
            payload[col] = jdump(payload[col])
    cols = list(payload.keys())
    for c in cols:
        _check_column(c)
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(f"`{c}`" for c in cols)
    execute(
        conn,
        f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})",
        tuple(payload[c] for c in cols),
    )
    return doc_id


def update(conn, table: str, doc_id: str, patch: dict) -> None:
    if not patch:
        return
    _check_table(table)
    payload = dict(patch)
    for col in JSON_COLUMNS.get(table, []):
        if col in payload and not isinstance(payload[col], (str, bytes)):
            payload[col] = jdump(payload[col])
    for col in payload:
        _check_column(col)
    sets = ", ".join(f"`{c}` = %s" for c in payload)
    execute(conn, f"UPDATE `{table}` SET {sets} WHERE id = %s", tuple(payload.values()) + (doc_id,))


def remove(conn, table: str, doc_id: str) -> None:
    _check_table(table)
    execute(conn, f"DELETE FROM `{table}` WHERE id = %s", (doc_id,))
