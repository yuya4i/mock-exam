import os
from flask import Flask
from flask_cors import CORS

from app.api.health import health_bp
from app.api.models import models_bp
from app.api.content import content_bp
from app.api.quiz import quiz_bp
from app.api.documents import documents_bp
from app.api.results import results_bp
from app.database import init_db
from app.security import register_auth, warn_if_insecurely_exposed


def create_app() -> Flask:
    app = Flask(__name__)

    # CORS設定（フロントエンドからのアクセスを許可）
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:1234").split(",")
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    # 認証ミドルウェア (API_TOKEN opt-in)。未設定ならこれまで通り素通り。
    register_auth(app)

    # データベース初期化
    init_db()

    # Blueprint登録
    app.register_blueprint(health_bp,     url_prefix="/api")
    app.register_blueprint(models_bp,     url_prefix="/api")
    app.register_blueprint(content_bp,    url_prefix="/api")
    app.register_blueprint(quiz_bp,       url_prefix="/api")
    app.register_blueprint(documents_bp,  url_prefix="/api")
    app.register_blueprint(results_bp,    url_prefix="/api")

    # 公開 bind + トークン未設定は高影響の踏み抜きパターンなので起動時に警告。
    warn_if_insecurely_exposed()

    return app


app = create_app()
