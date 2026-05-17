"""
APS 排程系统 — 数据库依赖注入
"""
import psycopg2
import psycopg2.extras
from src.config import DATABASE_CONFIG


def get_db():
    """FastAPI 依赖注入：获取数据库连接"""
    conn = psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
    finally:
        conn.close()
