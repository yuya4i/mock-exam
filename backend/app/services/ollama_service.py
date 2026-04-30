"""
OllamaService
Ollama REST API との通信を担う。
ベースURLは環境変数 OLLAMA_BASE_URL で切り替え可能。
"""
import os
import json
import requests
from typing import Generator

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
TIMEOUT_CONNECT = 5
TIMEOUT_READ    = 120


class OllamaService:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ------------------------------------------------------------------
    # モデル一覧取得
    # ------------------------------------------------------------------
    def list_models(self) -> list[dict]:
        """Ollamaにインストール済みのモデル一覧を返す。"""
        url = f"{self.base_url}/api/tags"
        try:
            resp = requests.get(url, timeout=(TIMEOUT_CONNECT, TIMEOUT_READ))
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models", [])
            return [
                {
                    "name":     m["name"],
                    "size":     m.get("size", 0),
                    "modified": m.get("modified_at", ""),
                }
                for m in models
            ]
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Ollamaに接続できません。{self.base_url} が起動しているか確認してください。"
            )
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Ollama API エラー: {e}")

    # ------------------------------------------------------------------
    # チャット（ストリーミング）
    # ------------------------------------------------------------------
    def chat_stream(
        self,
        model: str,
        messages: list[dict],
        options: dict | None = None,
        timeout: tuple[int, int] | None = None,
    ) -> Generator[str, None, None]:
        """
        /api/chat をストリーミングで呼び出し、トークンを逐次 yield する。
        messages は [{"role": "system"|"user"|"assistant", "content": "..."}] 形式。

        timeout: ``(connect, read)`` の秒タプル。指定が無ければ
                 (TIMEOUT_CONNECT, TIMEOUT_READ) を使用。長文応答や大きい
                 num_ctx では read を伸ばす必要あり。
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model":    model,
            "messages": messages,
            "stream":   True,
            "options":  options or {},
        }
        with requests.post(
            url,
            json=payload,
            stream=True,
            timeout=timeout or (TIMEOUT_CONNECT, TIMEOUT_READ),
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines():
                if not raw_line:
                    continue
                chunk = json.loads(raw_line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break

    # ------------------------------------------------------------------
    # チャット（一括取得）
    # ------------------------------------------------------------------
    def chat(
        self,
        model: str,
        messages: list[dict],
        options: dict | None = None,
        timeout: tuple[int, int] | None = None,
    ) -> str:
        """ストリーミングを内部で結合して完全な応答文字列を返す。"""
        return "".join(self.chat_stream(model, messages, options, timeout=timeout))

    # ------------------------------------------------------------------
    # 接続確認
    # ------------------------------------------------------------------
    def health(self) -> bool:
        try:
            resp = requests.get(
                f"{self.base_url}/api/tags",
                timeout=(TIMEOUT_CONNECT, 5),
            )
            return resp.status_code == 200
        except Exception:
            return False
