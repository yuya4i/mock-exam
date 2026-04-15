"""
Content API Blueprint
URL指定スクレイピング（階層指定・ドキュメント種別フィルタ）のエンドポイント。
"""
import json
import logging

from flask import Blueprint, jsonify, request, Response, stream_with_context

from app.services.content_service import ContentService
from app.api._schemas import ContentRequest, ValidationError, humanize_first_error

logger = logging.getLogger(__name__)

content_bp = Blueprint("content", __name__)
_content_service = ContentService()


def _parse_body() -> tuple[ContentRequest | None, str | None]:
    body = request.get_json(silent=True) or {}
    try:
        return ContentRequest.model_validate(body), None
    except ValidationError as e:
        return None, humanize_first_error(e)


def _parse_query() -> tuple[ContentRequest | None, str | None]:
    """Pivot query string into the same Pydantic schema as the bodies.
    ``doc_types`` arrives as a comma-separated string and is split before
    validation.
    """
    raw = {
        "source": request.args.get("source"),
        "depth": request.args.get("depth", 1),
        "doc_types": [
            dt.strip()
            for dt in request.args.get("doc_types", "").split(",")
            if dt.strip()
        ],
    }
    try:
        return ContentRequest.model_validate(raw), None
    except ValidationError as e:
        return None, humanize_first_error(e)


@content_bp.post("/content/preview")
def preview_content():
    """URLまたはテキストのプレビューを返す。"""
    params, err = _parse_body()
    if err:
        return jsonify({"error": err}), 400
    try:
        result = _content_service.preview(
            params.source,
            max_chars=600,
            depth=params.depth,
            doc_types=params.doc_types,
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.error(f"コンテンツ取得エラー: {e}", exc_info=True)
        return jsonify({"error": f"コンテンツ取得エラー: {e}"}), 500


@content_bp.post("/content/fetch")
def fetch_content():
    """URLまたはテキストのフルコンテンツを返す（問題生成に使用）。"""
    params, err = _parse_body()
    if err:
        return jsonify({"error": err}), 400
    try:
        result = _content_service.fetch(
            params.source,
            depth=params.depth,
            doc_types=params.doc_types,
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.error(f"コンテンツ取得エラー: {e}", exc_info=True)
        return jsonify({"error": f"コンテンツ取得エラー: {e}"}), 500


@content_bp.get("/content/scrape-stream")
def scrape_stream():
    """スクレイピング進捗をSSEで返すエンドポイント。"""
    params, err = _parse_query()
    if err:
        return jsonify({"error": err}), 400

    source, depth, doc_types = params.source, params.depth, params.doc_types

    def event_stream():
        try:
            yield _sse_event("progress", {
                "url": source, "depth": 0,
                "status": "starting", "pages_found": 0, "total_visited": 0,
            })

            result = _content_service.fetch(source, depth=depth, doc_types=doc_types)

            pages = result.get("pages", [])
            for i, page in enumerate(pages, 1):
                yield _sse_event("progress", {
                    "url":           page.get("url", source),
                    "depth":         page.get("depth", 0),
                    "status":        "scraped",
                    "pages_found":   len(pages),
                    "total_visited": i,
                })

            yield _sse_event("done", {
                "document_id": result.get("document_id"),
                "title":       result.get("title", ""),
                "page_count":  result.get("page_count", 1),
            })

        except Exception as e:
            logger.error(f"スクレイピングストリームエラー: {e}", exc_info=True)
            yield _sse_event("error_event", {"message": str(e)})

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


def _sse_event(event_type: str, data: dict) -> str:
    """SSEイベント文字列を構築する（名前付きイベント）。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"
