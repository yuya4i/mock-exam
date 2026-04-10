from flask import Blueprint, jsonify
from app.services.ollama_service import OllamaService

models_bp = Blueprint("models", __name__)


@models_bp.get("/models")
def list_models():
    """Ollamaにインストール済みのモデル一覧を返す。"""
    ollama = OllamaService()
    try:
        models = ollama.list_models()
        return jsonify({"models": models}), 200
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500
