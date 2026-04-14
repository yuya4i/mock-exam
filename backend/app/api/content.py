"""
Content API Blueprint
URL指定スクレイピング（階層指定・ドキュメント種別フィルタ）のエンドポイント。
"""
import json
import logging
from flask import Blueprint, jsonify, request, Response, stream_with_context
from app.services.content_service import ContentService, MAX_DEPTH
from app.api._validation import parse_int, parse_non_empty_str, parse_str_list

logger = logging.getLogger(__name__)

content_bp = Blueprint("content", __name__)
_content_service = ContentService()

VALID_DOC_TYPES = ["table", "csv", "pdf", "png"]
DEFAULT_DOC_TYPES = ["table", "csv", "pdf", "png"]


def _parse_common_fetch_params(
    source_raw,
    depth_raw,
    doc_types_raw,
) -> tuple[dict | None, str | None]:
    """Validate the (source, depth, doc_types) triple used by all three
    content endpoints. Returns ``(params, None)`` on success or
    ``(None, error_message)`` on the first validation failure.
    """
    source, err = parse_non_empty_str(source_raw, "source", max_len=2048)
    if err:
        return None, err

    depth, err = parse_int(
        depth_raw, "depth", default=1, min_val=1, max_val=MAX_DEPTH,
    )
    if err:
        return None, err

    doc_types, err = parse_str_list(
        doc_types_raw,
        "doc_types",
        allowed=VALID_DOC_TYPES,
        default=DEFAULT_DOC_TYPES,
    )
    if err:
        return None, err

    return {"source": source, "depth": depth, "doc_types": doc_types}, None


@content_bp.post("/content/preview")
def preview_content():
    """
    URLまたはテキストのプレビューを返す。
    フロントエンドで「このコンテンツで問題を作成」する前の確認に使用。

    Request JSON:
        source    (str):  URL or plain text
        depth     (int):  スクレイピング階層数 1〜8（デフォルト: 1）
        doc_types (list): 対象ドキュメント種別（デフォルト: ["table","csv","pdf","png"]）
    """
    body = request.get_json(silent=True) or {}
    params, err = _parse_common_fetch_params(
        body.get("source"), body.get("depth"), body.get("doc_types"),
    )
    if err:
        return jsonify({"error": err}), 400

    try:
        result = _content_service.preview(
            params["source"],
            max_chars=600,
            depth=params["depth"],
            doc_types=params["doc_types"],
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.error(f"コンテンツ取得エラー: {e}", exc_info=True)
        return jsonify({"error": f"コンテンツ取得エラー: {e}"}), 500


@content_bp.post("/content/fetch")
def fetch_content():
    """
    URLまたはテキストのフルコンテンツを返す（問題生成に使用）。

    Request JSON:
        source    (str):  URL or plain text
        depth     (int):  スクレイピング階層数 1〜8（デフォルト: 1）
        doc_types (list): 対象ドキュメント種別（デフォルト: ["table","csv","pdf","png"]）
    """
    body = request.get_json(silent=True) or {}
    params, err = _parse_common_fetch_params(
        body.get("source"), body.get("depth"), body.get("doc_types"),
    )
    if err:
        return jsonify({"error": err}), 400

    try:
        result = _content_service.fetch(
            params["source"],
            depth=params["depth"],
            doc_types=params["doc_types"],
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.error(f"コンテンツ取得エラー: {e}", exc_info=True)
        return jsonify({"error": f"コンテンツ取得エラー: {e}"}), 500


@content_bp.get("/content/scrape-stream")
def scrape_stream():
    """
    スクレイピング進捗をSSEで返すエンドポイント。
    EventSource（GETのみ）対応のため、クエリパラメータで受け取る。

    Query Params:
        source    (str):  URL
        depth     (int):  スクレイピング階層数 1〜8（デフォルト: 1）
        doc_types (str):  カンマ区切りのドキュメント種別（デフォルト: "table,csv,pdf,png"）
    """
    params, err = _parse_common_fetch_params(
        request.args.get("source"),
        request.args.get("depth"),
        request.args.get("doc_types"),
    )
    if err:
        return jsonify({"error": err}), 400

    source = params["source"]
    depth = params["depth"]
    doc_types = params["doc_types"]

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
