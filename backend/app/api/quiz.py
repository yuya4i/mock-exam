"""
Quiz API Blueprint
1問ずつ逐次生成するSSEエンドポイント。
"""
import json
import logging
from flask import Blueprint, jsonify, request, Response, stream_with_context
from app.services.quiz_service import QuizService
from app.api._schemas import (
    QuizGenerateRequest,
    ValidationError,
    humanize_first_error,
)

logger = logging.getLogger(__name__)

quiz_bp = Blueprint("quiz", __name__)
_quiz_service = QuizService()


def _derive_category(title: str, source_url: str) -> str:
    """
    ソースタイトル/URLからカテゴリ名を推定する汎用ロジック。
    特定ドメインや資格名のハードコードはせず、タイトルとURLドメインから抽出する。

    優先順位:
    1. タイトル（空でなければそのまま使用、長すぎる場合は切り詰め）
    2. URLのホスト名（タイトルが無い場合のフォールバック）
    3. "その他"
    """
    if title and title.strip():
        t = title.strip()
        # タイトルが長すぎる場合は先頭40文字で切り詰め
        return t if len(t) <= 40 else t[:40] + "…"

    if source_url:
        from urllib.parse import urlparse
        host = urlparse(source_url).netloc
        if host:
            # www. プレフィックスを除去
            return host.removeprefix("www.")

    return "その他"


def _save_quiz_session(result: dict, params: dict) -> None:
    """クイズセッションをSQLiteに保存する。

    Append mode (``params["append_to_session_id"]`` が真) では:
        - INSERT ではなく UPDATE。
        - questions / question_count / generated_at を上書き。
        - levels は既存と新規をマージ (重複排除しつつ順序保持)。
    """
    try:
        from app.database import get_connection
        conn = get_connection()

        source_info = result.get("source_info", {})
        document_id = source_info.get("document_id")
        title = source_info.get("title", "")
        source_url = source_info.get("source", "")
        category = _derive_category(title, source_url)
        all_questions = result.get("questions", [])
        new_levels = params.get("levels", [])

        if params.get("append_to_session_id"):
            # Merge levels: existing ∪ new, preserve order, dedup.
            row = conn.execute(
                "SELECT levels FROM quiz_sessions WHERE session_id = ?",
                (result["session_id"],),
            ).fetchone()
            if row:
                try:
                    existing_levels = json.loads(row["levels"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    existing_levels = []
                merged_levels = list(dict.fromkeys(existing_levels + new_levels))
            else:
                merged_levels = list(new_levels)

            conn.execute(
                """UPDATE quiz_sessions
                   SET questions = ?,
                       question_count = ?,
                       levels = ?,
                       generated_at = ?
                   WHERE session_id = ?""",
                (
                    json.dumps(all_questions, ensure_ascii=False),
                    len(all_questions),
                    json.dumps(merged_levels, ensure_ascii=False),
                    result.get("generated_at", ""),
                    result["session_id"],
                ),
            )
        else:
            conn.execute(
                """INSERT OR IGNORE INTO quiz_sessions
                   (session_id, document_id, model, source_title, source_type,
                    category, question_count, difficulty, levels, questions, generated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    result["session_id"],
                    document_id,
                    result["model"],
                    title,
                    source_info.get("type", ""),
                    category,
                    len(all_questions),
                    params.get("difficulty", "medium"),
                    json.dumps(new_levels, ensure_ascii=False),
                    json.dumps(all_questions, ensure_ascii=False),
                    result.get("generated_at", ""),
                ),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"クイズセッションDB保存エラー: {e}")


def _load_existing_session(session_id: str) -> dict | None:
    """Load just enough of an existing quiz_sessions row to support the
    append-to-existing path. Returns dict with ``questions`` and
    derived ``topics`` (formatted to match generate_incremental's
    "Topic (Level)" convention), or None if the session does not
    exist or its JSON is corrupt.
    """
    try:
        from app.database import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT questions FROM quiz_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        try:
            questions = json.loads(row["questions"] or "[]")
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(questions, list):
            return None
        topics = [
            f"{q.get('topic', 'N/A')} ({q.get('level', 'N/A')})"
            for q in questions
            if isinstance(q, dict)
        ]
        return {"questions": questions, "topics": topics}
    except Exception as e:
        logger.warning(f"既存セッションの読み込みエラー: {e}")
        return None


def _parse_request(body: dict) -> tuple[dict | None, str | None]:
    """リクエストボディを Pydantic で検証し、サービス層に渡す dict を返す。

    Returns:
        ``(params, None)`` on success, ``(None, error_message)`` on failure.
        Error messages are safe to surface to the client as-is.
    """
    try:
        model = QuizGenerateRequest.model_validate(body)
    except ValidationError as e:
        return None, humanize_first_error(e)
    return model.model_dump(), None


def _sse(event: str, data: dict) -> str:
    """名前付きSSEイベント文字列を構築する。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ------------------------------------------------------------------
# 1問ずつSSEストリーミング生成（メインエンドポイント）
# ------------------------------------------------------------------
@quiz_bp.post("/quiz/generate")
def generate_quiz():
    body = request.get_json(silent=True) or {}
    params, err = _parse_request(body)
    if err:
        return jsonify({"error": err}), 400

    # Resolve append-to-existing-session before kicking off the stream.
    # If the requested session no longer exists, silently fall back to
    # a fresh generation (the user picked it then deleted it elsewhere
    # — better to generate something than to 404).
    append_sid = params.pop("append_to_session_id", None)
    existing_questions: list[dict] = []
    existing_topics: list[str] = []
    if append_sid:
        loaded = _load_existing_session(append_sid)
        if loaded:
            existing_questions = loaded["questions"]
            existing_topics = loaded["topics"]
        else:
            append_sid = None  # fall back

    # Service-level args. Only pass session_id / existing_topics if we
    # actually have an append target.
    service_kwargs = dict(params)
    if append_sid:
        service_kwargs["session_id"] = append_sid
        service_kwargs["existing_topics"] = existing_topics

    # Persistence-level params (used by _save_quiz_session). Keep the
    # append flag here so the save path knows to UPDATE.
    save_params = dict(params)
    if append_sid:
        save_params["append_to_session_id"] = append_sid

    def event_stream():
        try:
            for event_type, data in _quiz_service.generate_incremental(**service_kwargs):
                # Append mode: merge existing questions into the done
                # payload BEFORE yielding, so the frontend's done handler
                # ends up with the full set (existing + new).
                if event_type == "done" and append_sid:
                    merged = list(existing_questions) + data.get("questions", [])
                    data["questions"] = merged
                    data["question_count"] = len(merged)

                yield _sse(event_type, data)

                if event_type == "done":
                    # SQLite is the canonical store post P1-E. The
                    # legacy JSON-backed HistoryService was removed
                    # (audit M-006).
                    _save_quiz_session(data, save_params)

        except ConnectionError as e:
            yield _sse("error", {"message": str(e)})
        except Exception as e:
            logger.error(f"問題生成ストリームエラー: {e}", exc_info=True)
            yield _sse("error", {"message": f"問題生成エラー: {e}"})

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
