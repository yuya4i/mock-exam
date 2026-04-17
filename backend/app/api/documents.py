"""
Documents API Blueprint
ドキュメント（スクレイピング済みコンテンツ）のCRUDエンドポイント。
"""
import hashlib
import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from app.database import get_connection
from app.api._validation import parse_int  # query-param int parsing
from app.api._schemas import (
    DocumentCreateRequest,
    ValidationError,
    humanize_first_error,
)

documents_bp = Blueprint("documents", __name__)


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
    try:
        req = DocumentCreateRequest.model_validate(body)
    except ValidationError as e:
        return jsonify({"error": humanize_first_error(e)}), 400

    title       = req.title
    url         = req.url
    content     = req.content
    source_type = req.source_type
    page_count  = req.page_count
    doc_types   = req.doc_types

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
    """ドキュメントを削除する。

    quiz_sessions が document_id でこの行を参照していると、PRAGMA
    foreign_keys=ON + REFERENCES (ON DELETE 句なし = RESTRICT) のため
    DELETE が IntegrityError で 500 になっていた (BACKEND-1)。

    挙動: 履歴セッションは保持したいので CASCADE ではなく SET NULL
    相当を選択。先に参照行の document_id を NULL に更新してから DELETE
    する。両者を同一 sqlite3 接続のトランザクションで実行することで
    部分失敗を防ぐ。
    """
    conn = get_connection()
    try:
        with conn:  # commits on success, rollbacks on exception
            conn.execute(
                "UPDATE quiz_sessions SET document_id = NULL WHERE document_id = ?",
                (doc_id,),
            )
            cursor = conn.execute(
                "DELETE FROM documents WHERE id = ?", (doc_id,)
            )
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
