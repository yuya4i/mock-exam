from flask import Blueprint, jsonify
from app.services.ollama_service import OllamaService

health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health():
    ollama = OllamaService()
    ollama_ok = ollama.health()
    return jsonify({
        "status":       "ok",
        "ollama":       "connected" if ollama_ok else "disconnected",
        "ollama_url":   ollama.base_url,
    }), 200
