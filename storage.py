"""本地去重存储模块。

使用 SQLite 记录已推送的快讯，通过内容哈希避免重复推送。
"""

import hashlib
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "data" / "jin10_monitor.db"
RETENTION_DAYS = 30

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id TEXT,
    content_hash TEXT UNIQUE,
    content_preview TEXT,
    stock_name TEXT,
    triggered_by TEXT,
    sent_at TEXT
)
"""


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """初始化数据库表（如不存在则创建）。"""
    conn = _get_conn()
    try:
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()
        logger.info("数据库初始化完成")
    finally:
        conn.close()


def _hash_content(content: str) -> str:
    return hashlib.md5(content.encode()).hexdigest()


def is_new(content: str) -> bool:
    """检查该内容是否从未推送过。"""
    h = _hash_content(content)
    conn = _get_conn()
    try:
        cur = conn.execute(
            "SELECT 1 FROM notifications WHERE content_hash = ?", (h,)
        )
        return cur.fetchone() is None
    finally:
        conn.close()


def mark_sent(
    news_id: str,
    content: str,
    stock_name: str = "",
    triggered_by: str = "",
) -> None:
    """标记一条快讯已推送。"""
    h = _hash_content(content)
    preview = content[:200]
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO notifications
               (news_id, content_hash, content_preview, stock_name, triggered_by, sent_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (news_id, h, preview, stock_name, triggered_by,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()


def cleanup_old() -> int:
    """删除超过保留期限的记录。返回删除条数。"""
    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM notifications WHERE sent_at < ?", (cutoff,)
        )
        conn.commit()
        deleted = cur.rowcount
        if deleted:
            logger.info(f"清理了 {deleted} 条过期记录")
        return deleted
    finally:
        conn.close()


def get_recent_notifications(limit: int = 20) -> list[dict]:
    """获取最近推送记录，供仪表盘展示。"""
    conn = _get_conn()
    try:
        cur = conn.execute(
            """SELECT content_preview, stock_name, triggered_by, sent_at
               FROM notifications
               ORDER BY sent_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [
            {
                "preview": row[0],
                "stock": row[1],
                "by": row[2],
                "sent_at": row[3],
            }
            for row in cur.fetchall()
        ]
    finally:
        conn.close()
