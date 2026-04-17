import logging

from flask import Blueprint, jsonify
from app.services.ollama_service import OllamaService

logger = logging.getLogger(__name__)
models_bp = Blueprint("models", __name__)


@models_bp.get("/models")
def list_models():
    """Ollamaにインストール済みのモデル一覧を返す。"""
    ollama = OllamaService()
    try:
        models = ollama.list_models()
        return jsonify({"models": models}), 200
    except ConnectionError as e:
        # ConnectionError carries a user-safe "Ollama not reachable" message.
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        # SEC-11: opaque to client, full detail in log.
        logger.error(f"モデル一覧取得エラー: {e}", exc_info=True)
        return jsonify({
            "error": "モデル一覧の取得中に内部エラーが発生しました。",
        }), 500
