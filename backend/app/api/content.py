"""
Content API Blueprint
URL指定スクレイピング（階層指定・ドキュメント種別フィルタ）のエンドポイント。
"""
import json
import logging
from flask import Blueprint, jsonify, request, Response, stream_with_context
from app.services.content_service import ContentService, MAX_DEPTH

logger = logging.getLogger(__name__)

content_bp = Blueprint("content", __name__)
_content_service = ContentService()


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
    body      = request.get_json(silent=True) or {}
    source    = body.get("source", "").strip()
    depth     = int(body.get("depth", 1))
    doc_types = body.get("doc_types", ["table", "csv", "pdf", "png"])

    if not source:
        return jsonify({"error": "source は必須です。"}), 400

    if not (1 <= depth <= MAX_DEPTH):
        return jsonify({"error": f"depth は 1〜{MAX_DEPTH} の範囲で指定してください。"}), 400

    if not isinstance(doc_types, list) or not doc_types:
        return jsonify({"error": "doc_types は空でないリストで指定してください。"}), 400

    try:
        result = _content_service.preview(
            source,
            max_chars=600,
            depth=depth,
            doc_types=doc_types,
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
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
    body      = request.get_json(silent=True) or {}
    source    = body.get("source", "").strip()
    depth     = int(body.get("depth", 1))
    doc_types = body.get("doc_types", ["table", "csv", "pdf", "png"])

    if not source:
        return jsonify({"error": "source は必須です。"}), 400

    if not (1 <= depth <= MAX_DEPTH):
        return jsonify({"error": f"depth は 1〜{MAX_DEPTH} の範囲で指定してください。"}), 400

    try:
        result = _content_service.fetch(source, depth=depth, doc_types=doc_types)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
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
    source    = request.args.get("source", "").strip()
    depth     = int(request.args.get("depth", 1))
    doc_types_raw = request.args.get("doc_types", "table,csv,pdf,png")
    doc_types = [dt.strip() for dt in doc_types_raw.split(",") if dt.strip()]

    if not source:
        return jsonify({"error": "source は必須です。"}), 400

    if not (1 <= depth <= MAX_DEPTH):
        return jsonify({"error": f"depth は 1〜{MAX_DEPTH} の範囲で指定してください。"}), 400

    def event_stream():
        try:
            # 進捗イベント送信
            yield _sse_event("progress", {
                "url": source, "depth": 0,
                "status": "starting", "pages_found": 0, "total_visited": 0,
            })

            # 実際のスクレイピング実行
            result = _content_service.fetch(source, depth=depth, doc_types=doc_types)

            # ページ情報から進捗イベントを生成
            pages = result.get("pages", [])
            for i, page in enumerate(pages, 1):
                yield _sse_event("progress", {
                    "url":           page.get("url", source),
                    "depth":         page.get("depth", 0),
                    "status":        "scraped",
                    "pages_found":   len(pages),
                    "total_visited": i,
                })

            # 完了イベント
            yield _sse_event("done", {
                "document_id": result.get("document_id"),
                "title":       result.get("title", ""),
                "page_count":  result.get("page_count", 1),
            })

        except Exception as e:
            logger.error(f"スクレイピングストリームエラー: {e}")
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
