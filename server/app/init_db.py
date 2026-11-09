"""建表入口：python -m app.init_db

读取 sql/schema.sql，按语句分割后逐条执行（幂等，全部 CREATE ... IF NOT EXISTS）。
"""
import re
from pathlib import Path

import pymysql

from . import config

SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def split_statements(sql: str):
    sql = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in sql.split(";") if s.strip()]


def main() -> None:
    statements = split_statements(SCHEMA.read_text(encoding="utf-8"))
    # 第一段 CREATE DATABASE / USE 需要不带 database 的连接
    conn = pymysql.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
        charset="utf8mb4", autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
    finally:
        conn.close()
    print(f"已执行 {len(statements)} 条 DDL，数据库 {config.DB_NAME} 就绪")


if __name__ == "__main__":
    main()
