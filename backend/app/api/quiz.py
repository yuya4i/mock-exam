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
    RegenerateQuestionRequest,
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
    append-to-existing path. Returns dict with ``questions``,
    ``topics`` (formatted as "Topic (Level)"), and ``document_id``
    (nullable) — or None if the session does not exist or its JSON is
    corrupt.
    """
    try:
        from app.database import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT questions, document_id FROM quiz_sessions WHERE session_id = ?",
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
        return {
            "questions": questions,
            "topics": topics,
            "document_id": row["document_id"],
        }
    except Exception as e:
        logger.warning(f"既存セッションの読み込みエラー: {e}")
        return None


def _load_document_as_source_info(document_id: int) -> dict | None:
    """Build a source_info dict from the ``documents`` table so callers
    can pass it as ``source_info_override`` to the service layer and
    skip the Camoufox/safe_fetch re-scrape entirely.

    The returned shape matches what ``ContentService.fetch`` produces,
    with two caveats that are acceptable for the regenerate flow:
      - ``pages`` is [] (per-page URLs are not persisted; per-question
        source_hint resolution falls back to the top-level source URL).
      - ``depth`` defaults to 1 (not preserved in the documents table).
    """
    try:
        from app.database import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT id, title, url, content, source_type, page_count, doc_types "
            "FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        try:
            doc_types = json.loads(row["doc_types"] or "[]")
        except (json.JSONDecodeError, TypeError):
            doc_types = []
        return {
            "title":       row["title"] or "",
            "content":     row["content"] or "",
            "source":      row["url"] or "plain_text",
            "type":        row["source_type"] or "url_deep",
            "depth":       1,
            "doc_types":   doc_types,
            "page_count":  row["page_count"] or 1,
            "pages":       [],
            "document_id": row["id"],
        }
    except Exception as e:
        logger.warning(f"ドキュメント読み込みエラー: {e}")
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
    source_info_override: dict | None = None
    if append_sid:
        loaded = _load_existing_session(append_sid)
        if loaded:
            existing_questions = loaded["questions"]
            existing_topics = loaded["topics"]
            # Re-use the already-scraped content stored in the
            # `documents` table instead of re-scraping the URL. Saves a
            # Camoufox round-trip per regenerate.
            if loaded.get("document_id"):
                source_info_override = _load_document_as_source_info(
                    loaded["document_id"],
                )
        else:
            append_sid = None  # fall back

    # Service-level args. Only pass session_id / existing_topics if we
    # actually have an append target.
    service_kwargs = dict(params)
    if append_sid:
        service_kwargs["session_id"] = append_sid
        service_kwargs["existing_topics"] = existing_topics
        if source_info_override is not None:
            service_kwargs["source_info_override"] = source_info_override

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


# ------------------------------------------------------------------
# 1問だけ差し替え（Mermaid SyntaxError 等の自動リカバリ用）
# ------------------------------------------------------------------
@quiz_bp.post("/quiz/regenerate-question")
def regenerate_question():
    """Generate a single replacement question.

    The frontend calls this when a question's diagram fails to render
    (Mermaid SyntaxError). The new question avoids ``exclude_topics``
    so it explores a different theme. If ``session_id`` and
    ``question_id`` are both provided, the matching question in the
    SQLite session is replaced in-place — so reloading the session
    later won't resurrect the broken one.
    """
    body = request.get_json(silent=True) or {}
    try:
        req = RegenerateQuestionRequest.model_validate(body)
    except ValidationError as e:
        return jsonify({"error": humanize_first_error(e)}), 400

    # If the failing question belongs to a saved session whose source
    # was already scraped and stored, reuse that content instead of
    # re-scraping. Falls back to a live fetch silently if the session
    # row has no document_id or the documents row is missing.
    source_info_override: dict | None = None
    if req.session_id:
        loaded = _load_existing_session(req.session_id)
        if loaded and loaded.get("document_id"):
            source_info_override = _load_document_as_source_info(
                loaded["document_id"],
            )

    try:
        question = _quiz_service.generate_single_question(
            source=req.source,
            model=req.model,
            level=req.level,
            difficulty=req.difficulty,
            depth=req.depth,
            doc_types=req.doc_types,
            ollama_options=req.ollama_options,
            exclude_topics=req.exclude_topics,
            source_info_override=source_info_override,
        )
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.error(f"問題再生成エラー: {e}", exc_info=True)
        return jsonify({"error": f"問題再生成エラー: {e}"}), 500

    if question is None:
        return jsonify({"error": "問題の生成に失敗しました（2回リトライ済み）"}), 500

    # Optional: persist the replacement in the existing SQLite session.
    persisted = False
    if req.session_id and req.question_id:
        persisted = _replace_question_in_session(
            session_id=req.session_id,
            old_question_id=req.question_id,
            new_question=question,
        )

    return jsonify({"question": question, "persisted": persisted}), 200


def _replace_question_in_session(
    session_id: str, old_question_id: str, new_question: dict,
) -> bool:
    """Find the question with ``old_question_id`` inside the saved
    session and overwrite it with ``new_question`` (preserving its
    position so the user's index expectations don't shift).

    The new question's ``id`` is forced to match ``old_question_id``
    so the user's existing answer (if any) stays referentially valid.
    """
    try:
        from app.database import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT questions FROM quiz_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            conn.close()
            return False

        try:
            questions = json.loads(row["questions"] or "[]")
        except (json.JSONDecodeError, TypeError):
            conn.close()
            return False
        if not isinstance(questions, list):
            conn.close()
            return False

        # Stable ID makes the answer columns and revealed-state map
        # carry over without renumbering.
        new_question = {**new_question, "id": old_question_id}

        replaced = False
        for i, q in enumerate(questions):
            if isinstance(q, dict) and q.get("id") == old_question_id:
                questions[i] = new_question
                replaced = True
                break
        if not replaced:
            conn.close()
            return False

        conn.execute(
            "UPDATE quiz_sessions SET questions = ? WHERE session_id = ?",
            (json.dumps(questions, ensure_ascii=False), session_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"問題差し替えのDB更新エラー: {e}")
        return False
