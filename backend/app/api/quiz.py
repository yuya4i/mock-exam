"""
Quiz API Blueprint
1問ずつ逐次生成するSSEエンドポイント。
"""
import json
import logging
from flask import Blueprint, jsonify, request, Response, stream_with_context
from app.services.quiz_service import QuizService
from app.services.history_service import get_history_service
from app.services.content_service import MAX_DEPTH

logger = logging.getLogger(__name__)

quiz_bp = Blueprint("quiz", __name__)
_quiz_service = QuizService()
_history_service = get_history_service()

VALID_DOC_TYPES = {"table", "csv", "pdf", "png"}


def _derive_category(title: str, source_url: str) -> str:
    """ソースタイトル/URLからカテゴリ名を推定する。"""
    import re
    # 既知のキーワードマッピング
    keywords = {
        "jstqb":    "JSTQB",
        "istqb":    "ISTQB",
        "ネットワークスペシャリスト": "ネットワークスペシャリスト",
        "応用情報":  "応用情報技術者",
        "基本情報":  "基本情報技術者",
        "情報セキュリティ": "情報セキュリティ",
        "データベーススペシャリスト": "データベーススペシャリスト",
        "aws":      "AWS",
        "azure":    "Azure",
        "gcp":      "Google Cloud",
        "python":   "Python",
        "java":     "Java",
        "javascript": "JavaScript",
    }
    combined = f"{title} {source_url}".lower()
    for keyword, category in keywords.items():
        if keyword in combined:
            return category
    # マッチしなければタイトルをそのままカテゴリに
    return title if title else "その他"


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


def _parse_request(body: dict) -> dict:
    """リクエストボディを検証・パースして返す。"""
    source = body.get("source", "").strip()
    if not source:
        raise ValueError("source は必須です。")

    model = body.get("model", "").strip()
    if not model:
        raise ValueError("model は必須です。")

    count = int(body.get("count", 5))
    if not (1 <= count <= 20):
        raise ValueError("count は 1〜20 の範囲で指定してください。")

    levels = body.get("levels", ["K2", "K3", "K4"])
    valid_levels = {"K1", "K2", "K3", "K4"}
    levels = [lv for lv in levels if lv in valid_levels] or ["K2", "K3", "K4"]

    difficulty = body.get("difficulty", "medium")
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "medium"

    depth = int(body.get("depth", 1))
    if not (1 <= depth <= MAX_DEPTH):
        raise ValueError(f"depth は 1〜{MAX_DEPTH} の範囲で指定してください。")

    doc_types = body.get("doc_types", ["table", "csv", "pdf", "png"])
    if not isinstance(doc_types, list) or not doc_types:
        raise ValueError("doc_types は空でないリストで指定してください。")
    doc_types = [dt for dt in doc_types if dt in VALID_DOC_TYPES]
    if not doc_types:
        doc_types = ["table", "csv", "pdf", "png"]

    ollama_options = body.get("ollama_options", {})

    return {
        "source":         source,
        "model":          model,
        "count":          count,
        "levels":         levels,
        "difficulty":     difficulty,
        "depth":          depth,
        "doc_types":      doc_types,
        "ollama_options": ollama_options,
    }


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
    try:
        params = _parse_request(body)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

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
