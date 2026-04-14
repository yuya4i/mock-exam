"""
Database Module
SQLiteデータベースの初期化と接続管理。
"""
import os
import sqlite3
import logging
from pathlib import Path

from app.paths import resolve_data_path

logger = logging.getLogger(__name__)

# Resolve at import (cheap) so module-level callers see a consistent path.
# Operators can still override per-process via DB_PATH.
DB_PATH = resolve_data_path("DB_PATH", "quizgen.db")


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
                category TEXT NOT NULL DEFAULT '',
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

        # マイグレーション: category カラムが無ければ追加
        cursor = conn.execute("PRAGMA table_info(quiz_sessions)")
        columns = {row["name"] for row in cursor.fetchall()}
        if "category" not in columns:
            conn.execute(
                "ALTER TABLE quiz_sessions ADD COLUMN category TEXT NOT NULL DEFAULT ''"
            )
            # 既存レコードの category を source_title から推定
            conn.execute(
                "UPDATE quiz_sessions SET category = source_title WHERE category = ''"
            )
            conn.commit()
            logger.info("マイグレーション: quiz_sessions に category カラムを追加")

        logger.info(f"データベース初期化完了: {DB_PATH}")
    finally:
        conn.close()
