"""
Documents API Blueprint
ドキュメント（スクレイピング済みコンテンツ）のCRUDエンドポイント。
"""
import hashlib
import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from app.database import get_connection
from app.api._validation import parse_int, parse_non_empty_str

documents_bp = Blueprint("documents", __name__)

# 1 MiB: upper bound for a single document body stored via this endpoint.
# Anything larger is almost certainly a misuse or a bug (scraped content goes
# through ContentService which already caps at MAX_CONTENT_CHARS).
MAX_DOCUMENT_CONTENT_BYTES = 1 * 1024 * 1024
MAX_TITLE_LEN = 512
MAX_URL_LEN = 2048
MAX_SOURCE_TYPE_LEN = 64


@documents_bp.get("/documents")
def list_documents():
    """
    ドキュメント一覧を返す（scraped_at降順）。
    クエリパラメータ ?search= でタイトル・URLの部分一致検索が可能。
    """
    search = request.args.get("search", "").strip()
    conn = get_connection()
    try:
        if search:
            rows = conn.execute(
                """SELECT id, title, url, source_type, page_count, doc_types, scraped_at
                   FROM documents
                   WHERE title LIKE ? OR url LIKE ?
                   ORDER BY scraped_at DESC""",
                (f"%{search}%", f"%{search}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, title, url, source_type, page_count, doc_types, scraped_at
                   FROM documents
                   ORDER BY scraped_at DESC"""
            ).fetchall()

        documents = []
        for row in rows:
            doc = dict(row)
            # doc_types はJSON文字列なのでパースする
            if doc.get("doc_types"):
                try:
                    doc["doc_types"] = json.loads(doc["doc_types"])
                except (json.JSONDecodeError, TypeError):
                    pass
            documents.append(doc)

        return jsonify({"documents": documents}), 200
    finally:
        conn.close()


@documents_bp.get("/documents/by-url")
def get_document_by_url():
    """
    URLの完全一致でドキュメントを検索する。
    クエリパラメータ ?url=<exact_url> を必須とし、見つかった場合は
    メタ情報（id, title, url, source_type, page_count, doc_types, scraped_at）を返す。
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "url パラメータは必須です。"}), 400

    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT id, title, url, source_type, page_count, doc_types, scraped_at
               FROM documents
               WHERE url = ?
               ORDER BY scraped_at DESC
               LIMIT 1""",
            (url,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "見つかりません"}), 404

        doc = dict(row)
        if doc.get("doc_types"):
            try:
                doc["doc_types"] = json.loads(doc["doc_types"])
            except (json.JSONDecodeError, TypeError):
                pass
        return jsonify(doc), 200
    finally:
        conn.close()


@documents_bp.get("/documents/<int:doc_id>")
def get_document(doc_id: int):
    """ドキュメント詳細（content含む）を返す。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "ドキュメントが見つかりません。"}), 404

        doc = dict(row)
        if doc.get("doc_types"):
            try:
                doc["doc_types"] = json.loads(doc["doc_types"])
            except (json.JSONDecodeError, TypeError):
                pass
        return jsonify(doc), 200
    finally:
        conn.close()


@documents_bp.post("/documents")
def create_document():
    """
    ドキュメントを保存する。
    content_hash による重複チェックあり（409を返す）。
    """
    body = request.get_json(silent=True) or {}

    title, err = parse_non_empty_str(body.get("title"), "title", max_len=MAX_TITLE_LEN)
    if err:
        return jsonify({"error": err}), 400

    content, err = parse_non_empty_str(body.get("content"), "content")
    if err:
        return jsonify({"error": err}), 400
    if len(content.encode("utf-8")) > MAX_DOCUMENT_CONTENT_BYTES:
        return jsonify({
            "error": f"content は {MAX_DOCUMENT_CONTENT_BYTES} バイト以内で指定してください。",
        }), 413

    source_type, err = parse_non_empty_str(
        body.get("source_type"), "source_type", max_len=MAX_SOURCE_TYPE_LEN,
    )
    if err:
        return jsonify({"error": err}), 400

    raw_url = body.get("url")
    url: str | None
    if raw_url is None or raw_url == "":
        url = None
    elif isinstance(raw_url, str) and len(raw_url.strip()) <= MAX_URL_LEN:
        url = raw_url.strip() or None
    else:
        return jsonify({"error": f"url は {MAX_URL_LEN} 文字以内の文字列で指定してください。"}), 400

    page_count, err = parse_int(
        body.get("page_count"), "page_count",
        default=1, min_val=1, max_val=10_000,
    )
    if err:
        return jsonify({"error": err}), 400

    doc_types = body.get("doc_types", [])
    if not isinstance(doc_types, list):
        return jsonify({"error": "doc_types はリストで指定してください。"}), 400

    # content_hash 生成（URL + content の MD5）
    hash_source = (url or "") + content
    content_hash = hashlib.md5(hash_source.encode("utf-8")).hexdigest()

    scraped_at = datetime.now(timezone.utc).isoformat()
    doc_types_json = json.dumps(doc_types, ensure_ascii=False)

    conn = get_connection()
    try:
        # 重複チェック
        existing = conn.execute(
            "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        if existing:
            return jsonify({
                "error": "同一コンテンツが既に登録されています。",
                "existing_id": existing["id"],
            }), 409

        cursor = conn.execute(
            """INSERT INTO documents
               (title, url, content, source_type, page_count, doc_types, scraped_at, content_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, url, content, source_type, page_count, doc_types_json, scraped_at, content_hash),
        )
        conn.commit()

        return jsonify({"id": cursor.lastrowid, "scraped_at": scraped_at}), 201
    finally:
        conn.close()


@documents_bp.delete("/documents/<int:doc_id>")
def delete_document(doc_id: int):
    """ドキュメントを削除する。"""
    conn = get_connection()
    try:
        cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "ドキュメントが見つかりません。"}), 404
        return jsonify({"message": "削除しました。"}), 200
    finally:
        conn.close()


@documents_bp.get("/documents/<int:doc_id>/content-preview")
def content_preview(doc_id: int):
    """ドキュメントの先頭500文字を返す。"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT content FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "ドキュメントが見つかりません。"}), 404

        content = row["content"] or ""
        preview = content[:500]
        return jsonify({"preview": preview}), 200
    finally:
        conn.close()
