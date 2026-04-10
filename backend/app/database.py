"""
Database Module
SQLiteデータベースの初期化と接続管理。
"""
import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/.cache/quizgen.db")


def get_connection() -> sqlite3.Connection:
    """SQLiteデータベース接続を取得する。"""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """テーブルが存在しない場合は作成する。"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT,
                content TEXT NOT NULL,
                source_type TEXT NOT NULL,
                page_count INTEGER DEFAULT 1,
                doc_types TEXT,
                scraped_at TEXT NOT NULL,
                content_hash TEXT UNIQUE
            );

            CREATE TABLE IF NOT EXISTS quiz_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                document_id INTEGER REFERENCES documents(id),
                model TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                question_count INTEGER NOT NULL,
                difficulty TEXT NOT NULL,
                levels TEXT NOT NULL,
                questions TEXT NOT NULL,
                user_answers TEXT,
                score_correct INTEGER,
                score_total INTEGER,
                generated_at TEXT NOT NULL,
                answered_at TEXT
            );
        """)
        conn.commit()
        logger.info(f"データベース初期化完了: {DB_PATH}")
    finally:
        conn.close()
