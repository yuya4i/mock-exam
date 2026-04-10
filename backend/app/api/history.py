from flask import Blueprint, jsonify, request
from app.services.history_service import get_history_service

history_bp = Blueprint("history", __name__)
_history_service = get_history_service()


@history_bp.get("/history")
def list_history():
    limit  = int(request.args.get("limit",  20))
    offset = int(request.args.get("offset",  0))
    return jsonify(_history_service.list(limit=limit, offset=offset)), 200


@history_bp.get("/history/<session_id>")
def get_history(session_id: str):
    session = _history_service.get(session_id)
    if session is None:
        return jsonify({"error": "セッションが見つかりません。"}), 404
    return jsonify(session), 200


@history_bp.delete("/history/<session_id>")
def delete_history(session_id: str):
    deleted = _history_service.delete(session_id)
    if not deleted:
        return jsonify({"error": "セッションが見つかりません。"}), 404
    return jsonify({"message": "削除しました。"}), 200
