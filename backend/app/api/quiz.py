"""
Quiz API Blueprint
1問ずつ逐次生成するSSEエンドポイント。
"""
import json
import logging
from flask import Blueprint, jsonify, request, Response, stream_with_context
from app.services.quiz_service import QuizService
from app.services.history_service import get_history_service
from app.api._schemas import (
    QuizGenerateRequest,
    ValidationError,
    humanize_first_error,
)

logger = logging.getLogger(__name__)

quiz_bp = Blueprint("quiz", __name__)
_quiz_service = QuizService()
_history_service = get_history_service()


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
    """クイズセッションをSQLiteに保存する。"""
    try:
        from app.database import get_connection
        conn = get_connection()

        source_info = result.get("source_info", {})
        document_id = source_info.get("document_id")
        title = source_info.get("title", "")
        source_url = source_info.get("source", "")
        category = _derive_category(title, source_url)

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
                len(result.get("questions", [])),
                params.get("difficulty", "medium"),
                json.dumps(params.get("levels", []), ensure_ascii=False),
                json.dumps(result.get("questions", []), ensure_ascii=False),
                result.get("generated_at", ""),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"クイズセッションDB保存エラー: {e}")


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

    def event_stream():
        try:
            for event_type, data in _quiz_service.generate_incremental(**params):
                yield _sse(event_type, data)

                if event_type == "done":
                    _history_service.add(data)
                    _save_quiz_session(data, params)

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
