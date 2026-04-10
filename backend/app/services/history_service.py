"""
HistoryService
生成した問題セッションの履歴をインメモリ + JSONファイルで管理する。
将来的にDBへの切り替えも容易な構造。
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

HISTORY_FILE = Path(os.getenv("HISTORY_FILE", "/app/.cache/history.json"))
MAX_HISTORY  = 100  # 最大保持件数


class HistoryService:
    def __init__(self):
        self._sessions: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # 追加
    # ------------------------------------------------------------------
    def add(self, session: dict) -> None:
        self._sessions.insert(0, session)
        # 上限超過分を削除
        if len(self._sessions) > MAX_HISTORY:
            self._sessions = self._sessions[:MAX_HISTORY]
        self._save()

    # ------------------------------------------------------------------
    # 一覧取得
    # ------------------------------------------------------------------
    def list(self, limit: int = 20, offset: int = 0) -> dict:
        sliced = self._sessions[offset:offset + limit]
        # 問題本文は一覧では返さない（軽量化）
        summaries = [
            {
                "session_id":    s["session_id"],
                "generated_at":  s["generated_at"],
                "model":         s["model"],
                "source_title":  s["source_info"]["title"],
                "source_type":   s["source_info"]["type"],
                "question_count": len(s["questions"]),
            }
            for s in sliced
        ]
        return {
            "total":  len(self._sessions),
            "limit":  limit,
            "offset": offset,
            "items":  summaries,
        }

    # ------------------------------------------------------------------
    # 詳細取得
    # ------------------------------------------------------------------
    def get(self, session_id: str) -> dict | None:
        for s in self._sessions:
            if s["session_id"] == session_id:
                return s
        return None

    # ------------------------------------------------------------------
    # 削除
    # ------------------------------------------------------------------
    def delete(self, session_id: str) -> bool:
        before = len(self._sessions)
        self._sessions = [s for s in self._sessions if s["session_id"] != session_id]
        if len(self._sessions) < before:
            self._save()
            return True
        return False

    # ------------------------------------------------------------------
    # 永続化
    # ------------------------------------------------------------------
    def _save(self) -> None:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self._sessions, f, ensure_ascii=False, indent=2)

    def _load(self) -> None:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    self._sessions = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._sessions = []
        else:
            self._sessions = []


# シングルトン
_history_service = HistoryService()


def get_history_service() -> HistoryService:
    return _history_service
