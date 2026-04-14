from flask import Blueprint, jsonify, request
from app.services.history_service import get_history_service
from app.api._validation import parse_int

history_bp = Blueprint("history", __name__)
_history_service = get_history_service()


@history_bp.get("/history")
def list_history():
    limit, err = parse_int(
        request.args.get("limit"), "limit",
        default=20, min_val=1, max_val=200,
    )
    if err:
        return jsonify({"error": err}), 400

    offset, err = parse_int(
        request.args.get("offset"), "offset",
        default=0, min_val=0, max_val=10_000,
    )
    if err:
        return jsonify({"error": err}), 400

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
