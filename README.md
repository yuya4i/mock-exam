# QuizGen - AI Quiz Generator / AI模擬問題自動生成アプリ

[![CI](https://github.com/yuya4i/mock-exam/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/yuya4i/mock-exam/actions/workflows/ci.yml)
[![Vue.js](https://img.shields.io/badge/Vue.js_3-4FC08D?logo=vuedotjs&logoColor=fff)](https://vuejs.org/)
[![Vite](https://img.shields.io/badge/Vite_6-646CFF?logo=vite&logoColor=fff)](https://vite.dev/)
[![Flask](https://img.shields.io/badge/Flask_3-000?logo=flask&logoColor=fff)](https://flask.palletsprojects.com/)
[![Ollama](https://img.shields.io/badge/Ollama-000?logo=ollama&logoColor=fff)](https://ollama.com/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff)](https://www.docker.com/)
[![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=fff)](https://www.sqlite.org/)
[![Mermaid](https://img.shields.io/badge/Mermaid-FF3670?logo=mermaid&logoColor=fff)](https://mermaid.js.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> [English](#english) | [日本語](#日本語)

---

## English

A web application that generates high-quality quiz questions from any URL or text using a local Ollama LLM. Scrapes web content, then generates questions **one at a time** with consistent quality and optional Mermaid diagrams.

> **Security note**: this project is intended for **trusted local / LAN use only**.
> See [`SECURITY.md`](SECURITY.md) for the full policy, trust boundaries, and
> the hardening opt-in env vars (`ALLOW_HTTP`, `ALLOW_PRIVATE_NETWORKS`,
> `MAX_FETCH_BYTES`, `MAX_REDIRECTS`). Do **not** expose to the public
> internet without the additional controls listed there.

### Features

- **Camoufox Scraping** - Firefox-based browser (Playwright-compatible); falls back to `requests` when Camoufox is unavailable
- **Deep Crawling (Max 8 levels)** - BFS traversal of same-domain links with selective document extraction. Outbound fetches are gated by the SSRF policy in `SECURITY.md`
- **Document Type Filtering** - Target only CSV / PDF / PNG / HTML tables
- **Incremental Generation** - Questions generated one-by-one via SSE streaming, displayed in real-time
- **Quality-Consistent Prompting** - Each question uses a full system prompt with quality rubric; previously generated topics are excluded to ensure diversity
- **Mermaid Diagrams** - LLM can output flowcharts, sequence diagrams, etc. rendered client-side
- **Knowledge Levels** - K1 (Recall), K2 (Understanding), K3 (Application), K4 (Analysis)
- **Difficulty Settings** - Easy / Medium / Hard
- **Answer & Explanation** - Detailed explanations with source references for each question
- **Session History** - SQLite-backed storage of all generated quiz sessions and scores
- **Hot Reload Development** - Docker Compose dev setup with Vite HMR + Flask auto-reload

### Tech Stack

| Layer | Technology | Version |
|:---|:---|:---|
| Frontend | [![Vue.js](https://img.shields.io/badge/Vue.js-4FC08D?logo=vuedotjs&logoColor=fff)](https://vuejs.org/) [![Vite](https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=fff)](https://vite.dev/) [![Pinia](https://img.shields.io/badge/Pinia-FFD859?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMiIgaGVpZ2h0PSIzMiI+PHRleHQgeT0iMjQiIGZvbnQtc2l6ZT0iMjQiPvCfjI8PC90ZXh0Pjwvc3ZnPg==&logoColor=000)](https://pinia.vuejs.org/) | Vue 3.4 / Vite 6.4.2 |
| HTTP Client | [![Axios](https://img.shields.io/badge/Axios-5A29E4?logo=axios&logoColor=fff)](https://axios-http.com/) | 1.15.0 (pinned) |
| Diagrams | [![Mermaid](https://img.shields.io/badge/Mermaid-FF3670?logo=mermaid&logoColor=fff)](https://mermaid.js.org/) | 11.x (CDN) |
| Backend | [![Flask](https://img.shields.io/badge/Flask-000?logo=flask&logoColor=fff)](https://flask.palletsprojects.com/) | 3.0.3 |
| Scraping | [![Camoufox](https://img.shields.io/badge/Camoufox-FF6A00?logo=firefox&logoColor=fff)](https://camoufox.com/) | Latest |
| PDF Parsing | [![pypdf](https://img.shields.io/badge/pypdf-306998?logo=python&logoColor=fff)](https://pypdf.readthedocs.io/) | 4.3.1 |
| AI Engine | [![Ollama](https://img.shields.io/badge/Ollama-000?logo=ollama&logoColor=fff)](https://ollama.com/) | Any |
| Database | [![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=fff)](https://www.sqlite.org/) | WAL mode |
| Container | [![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff)](https://www.docker.com/) | - |
| Web Server (prod) | [![nginx](https://img.shields.io/badge/nginx-009639?logo=nginx&logoColor=fff)](https://nginx.org/) | 1.27-alpine |

### Architecture

```
Browser (localhost:1234)
  │
  ├─ GET  /api/content/scrape-stream  →  SSE scraping progress
  │
  └─ POST /api/quiz/generate          →  SSE (1 question per event)
       │
       │  For each question (1..N):
       │    ┌──────────────────────┐
       │    │ System Prompt        │  Quality rubric (6 criteria)
       │    │ + Source Material    │  Full scraped content
       │    │ + Previous Topics    │  Dedup exclusion list
       │    └──────────┬───────────┘
       │               ▼
       │         Ollama /api/chat  →  1 JSON question object
       │               │
       │    event: question ──────→  Real-time display
       │
       └─ event: done ────────────→  Session saved to SQLite
```

### Prerequisites

- **Docker** & **Docker Compose**
- **Ollama** running on the host machine

```bash
# Install and verify Ollama
ollama serve
ollama list    # Check installed models
```

### Quick Start

```bash
# 1. Clone or unzip
cd quiz-app

# 2. Copy the env sample and edit if needed (CORS_ORIGINS, OLLAMA_BASE_URL, ...)
cp .env.sample .env

# 3a. Start in production mode (nginx-served SPA, no debug)
docker compose up -d --build

# -- OR --

# 3b. Start in development mode (Vite HMR + Flask --reload --debug)
docker compose -f docker-compose.dev.yml up -d --build

# 4. Open browser
open http://localhost:1234
```

> **Note**: First build downloads the camoufox Firefox binary (~200MB), which may take several minutes.

The default `docker-compose.yml` is **production-oriented**: it builds the
nginx-served SPA and runs Flask without debug mode. Use
`docker-compose.dev.yml` during development for hot reload.

Ports:

| Service  | Host port | Container port | Notes                       |
|----------|-----------|----------------|-----------------------------|
| Frontend | `1234`    | `1234`         | nginx (prod) or Vite (dev)  |
| Backend  | `4321`    | `4321`         | Flask; proxied via frontend |

### Environment Variables

| Variable | Default | Description |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API endpoint |
| `FLASK_ENV` | `production` (default compose) / `development` (dev compose) | Flask environment |
| `CORS_ORIGINS` | `http://localhost:1234` | Comma-separated allowed CORS origins |
| `HISTORY_FILE` | `/app/.cache/history.json` | Legacy JSON history file path |
| `DB_PATH` | `/app/.cache/quizgen.db` | SQLite file path |
| `ALLOW_HTTP` | *(unset — `https` only)* | Set to `1` to allow `http://` URLs. See `SECURITY.md`. |
| `ALLOW_PRIVATE_NETWORKS` | *(unset — public IPs only)* | Set to `1` to allow RFC1918/loopback/link-local targets. Cloud metadata IPs remain denied. |
| `MAX_FETCH_BYTES` | `10485760` (10 MiB) | Per-request response body cap for outbound fetches |
| `MAX_REDIRECTS` | `3` | Per-request redirect cap (`0` disables redirects) |

#### Linux Host

On Linux, `host.docker.internal` may not resolve. Use:

```bash
OLLAMA_BASE_URL=http://172.17.0.1:11434 docker compose up -d
```

### Project Structure

```
quiz-app/
├── docker-compose.yml          # Production-oriented (nginx, no debug) — default
├── docker-compose.dev.yml      # Development (Vite HMR + Flask --reload)
├── SECURITY.md                 # Trust boundaries + SSRF policy + disclosure
├── backend/
│   ├── Dockerfile              # Production (camoufox + Xvfb)
│   ├── Dockerfile.dev          # Dev (Flask --reload --debug)
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py         # Flask app factory
│       ├── database.py         # SQLite setup (documents, quiz_sessions)
│       ├── api/
│       │   ├── health.py       # GET  /api/health, GET /api/system/specs
│       │   ├── models.py       # GET  /api/models
│       │   ├── content.py      # GET  /api/content/scrape-stream (SSE)
│       │   │                   # POST /api/content/preview, /api/content/fetch
│       │   ├── quiz.py         # POST /api/quiz/generate (SSE)
│       │   ├── history.py      # CRUD /api/history (legacy JSON-backed)
│       │   ├── documents.py    # CRUD /api/documents
│       │   └── results.py      # CRUD /api/results (+ category aggregations)
│       └── services/
│           ├── ollama_service.py     # Ollama REST API client
│           ├── content_service.py    # Camoufox BFS scraper (plugin arch)
│           ├── quiz_service.py       # Incremental question generation
│           └── history_service.py    # Legacy history (JSON file)
├── frontend/
│   ├── Dockerfile              # Multi-stage build (nginx)
│   ├── Dockerfile.dev          # Vite dev server
│   ├── nginx.conf              # SPA routing + API proxy
│   ├── package.json            # axios@1.15.0, vite@6.4.2 (pinned)
│   ├── vite.config.js          # Proxy + WSL2 polling watch
│   └── src/
│       ├── views/
│       │   ├── GeneratePage.vue    # Main quiz generation page
│       │   ├── DatabasePage.vue    # Saved documents browser
│       │   ├── ResultsPage.vue     # Quiz session history & scores
│       │   └── SettingsPage.vue    # Ollama URL configuration
│       ├── components/
│       │   └── QuestionCard.vue    # Question display + Mermaid rendering
│       ├── stores/
│       │   └── index.js            # Pinia stores (quiz, scrape, etc.)
│       └── composables/
│           └── useApi.js           # Axios instance
└── docs/
```

### API Reference

| Method | Endpoint | Description |
|:---|:---|:---|
| GET  | `/api/health` | Ollama connectivity check |
| GET  | `/api/system/specs` | Host RAM/CPU hints for model capability warnings |
| GET  | `/api/models` | List installed Ollama models |
| POST | `/api/content/preview` | Preview content (title, excerpt) |
| POST | `/api/content/fetch` | Fetch full content |
| GET  | `/api/content/scrape-stream` | SSE: Scraping progress events |
| POST | `/api/quiz/generate` | SSE: Incremental question generation |
| GET  | `/api/documents` | List saved documents (`?search=` for title/URL substring) |
| GET  | `/api/documents/by-url` | Lookup a saved document by exact URL |
| GET  | `/api/documents/<id>` | Document detail (incl. content) |
| GET  | `/api/documents/<id>/content-preview` | First 500 chars of a document |
| POST | `/api/documents` | Create a document (dedup by content hash) |
| DELETE | `/api/documents/<id>` | Delete a document |
| GET  | `/api/results` | List quiz sessions (`?document_id=` filter) |
| GET  | `/api/results/categories` | Per-category aggregation (radar chart) |
| GET  | `/api/results/categories/breakdown` | Per-category K1–K4 × difficulty × topic breakdown |
| GET  | `/api/results/<session_id>` | Session detail |
| POST | `/api/results/<session_id>/answers` | Save user answers and score |
| DELETE | `/api/results/<session_id>` | Delete a session |
| GET  | `/api/history` | Legacy JSON-backed history list (`?limit=&offset=`) |
| GET  | `/api/history/<session_id>` | Legacy JSON-backed history detail |
| DELETE | `/api/history/<session_id>` | Delete a legacy history entry |

SSE endpoints emit named events. The current contract is:

| Endpoint | Events |
|:---|:---|
| `/api/content/scrape-stream` | `progress`, `done`, `error` |
| `/api/quiz/generate` | `source_info`, `progress`, `question`, `question_error`, `done`, `error` |

#### POST /api/quiz/generate

**Request:**
```json
{
  "source": "https://example.com/docs",
  "model": "qwen2.5:7b",
  "count": 10,
  "levels": ["K2", "K3"],
  "difficulty": "medium",
  "depth": 3,
  "doc_types": ["table", "pdf"]
}
```

**SSE Response Events:**
```
event: source_info    → Scraping complete, content metadata
event: progress       → { "current": 1, "total": 10, "status": "generating" }
event: question       → Complete question JSON object
event: question_error → Parse/generation failure for one question
event: done           → Final session summary with all questions
event: error          → Fatal error
```

### Important Notes

- **Ollama must be running** on the host before starting the app. The backend health check will fail otherwise.
- **Ollama version**: Models using newer architectures (e.g., qwen3.5) require an up-to-date Ollama. Run `curl -fsSL https://ollama.com/install.sh | sh` to update.
- **Memory**: Large models (70B+) require significant RAM. Check model requirements with `ollama show <model>`.
- **Scraping**: Max 50 pages per crawl. BFS stays within the same domain. Results are cached (content hash dedup in SQLite). Outbound fetches are restricted by the SSRF policy (public IPs only by default — see `SECURITY.md`).
- **WSL2**: Vite is configured with `usePolling: true` for Docker volume file watching to work correctly.
- **Dependency pinning**: runtime deps (`axios`, `chart.js`, `vue-chartjs`, `vite`) are pinned to exact versions to keep Docker builds reproducible. `vue`, `vue-router`, `pinia`, and `@vitejs/plugin-vue` currently use a caret range; Phase 1 of the hardening roadmap tightens this.

### License

MIT License

---

## 日本語

URLまたはテキストを入力するだけで、ローカルのOllama AIが **1問ずつ** 高品質な模擬問題を生成するWebアプリケーションです。

> **セキュリティ注意**: 本プロジェクトは **信頼できるローカル / LAN 環境** での利用を想定しています。
> 信頼境界・SSRFポリシー・オプトインの環境変数（`ALLOW_HTTP` / `ALLOW_PRIVATE_NETWORKS` /
> `MAX_FETCH_BYTES` / `MAX_REDIRECTS`）の詳細は [`SECURITY.md`](SECURITY.md) を参照してください。
> 追加の対策なしにインターネットへ公開**しないで**ください。

### 特徴

- **camoufox対応スクレイピング** - Firefoxベースのブラウザでコンテンツを取得。利用不可時は `requests` にフォールバック
- **階層指定スクレイピング（最大8階層）** - 同一ドメイン内のリンクをBFSで辿り、ドキュメントを選択的に収集。外部フェッチは `SECURITY.md` のSSRFポリシーに従う
- **対象ドキュメント種別フィルタ** - CSV / PDF / PNG / HTMLテーブルのみを対象
- **1問ずつ逐次生成** - SSEストリーミングで問題が1問完成するごとにリアルタイム表示
- **品質均一化プロンプト** - 各問題に品質基準6項目のシステムプロンプトを適用。既出テーマを自動除外し、多様なトピックをカバー
- **Mermaid図表対応** - フローチャート・シーケンス図などをLLMが生成し、クライアント側でレンダリング
- **知識レベル指定** - K1（記憶）/ K2（理解）/ K3（適用）/ K4（分析）を組み合わせ
- **難易度設定** - 易しい / 普通 / 難しい
- **解答・解説表示** - 正解根拠と各不正解選択肢の解説付き
- **セッション履歴管理** - SQLiteに全セッション・スコアを保存
- **ホットリロード開発環境** - Vite HMR + Flask auto-reloadのDocker Compose開発構成

### 技術スタック

| レイヤー | 技術 | バージョン |
|:---|:---|:---|
| フロントエンド | [![Vue.js](https://img.shields.io/badge/Vue.js-4FC08D?logo=vuedotjs&logoColor=fff)](https://vuejs.org/) [![Vite](https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=fff)](https://vite.dev/) [![Pinia](https://img.shields.io/badge/Pinia-FFD859?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMiIgaGVpZ2h0PSIzMiI+PHRleHQgeT0iMjQiIGZvbnQtc2l6ZT0iMjQiPvCfjI8PC90ZXh0Pjwvc3ZnPg==&logoColor=000)](https://pinia.vuejs.org/) | Vue 3.4 / Vite 6.4.2 |
| HTTPクライアント | [![Axios](https://img.shields.io/badge/Axios-5A29E4?logo=axios&logoColor=fff)](https://axios-http.com/) | 1.15.0（完全固定） |
| 図表レンダリング | [![Mermaid](https://img.shields.io/badge/Mermaid-FF3670?logo=mermaid&logoColor=fff)](https://mermaid.js.org/) | 11.x (CDN) |
| バックエンド | [![Flask](https://img.shields.io/badge/Flask-000?logo=flask&logoColor=fff)](https://flask.palletsprojects.com/) | 3.0.3 |
| スクレイピング | [![Camoufox](https://img.shields.io/badge/Camoufox-FF6A00?logo=firefox&logoColor=fff)](https://camoufox.com/) | 最新版 |
| PDF解析 | [![pypdf](https://img.shields.io/badge/pypdf-306998?logo=python&logoColor=fff)](https://pypdf.readthedocs.io/) | 4.3.1 |
| AIエンジン | [![Ollama](https://img.shields.io/badge/Ollama-000?logo=ollama&logoColor=fff)](https://ollama.com/) | 任意 |
| データベース | [![SQLite](https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=fff)](https://www.sqlite.org/) | WALモード |
| コンテナ | [![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=fff)](https://www.docker.com/) | - |
| Webサーバー（本番） | [![nginx](https://img.shields.io/badge/nginx-009639?logo=nginx&logoColor=fff)](https://nginx.org/) | 1.27-alpine |

### アーキテクチャ

```
ブラウザ (localhost:1234)
  │
  ├─ GET  /api/content/scrape-stream  →  SSE スクレイピング進捗
  │
  └─ POST /api/quiz/generate          →  SSE（1問ずつイベント送信）
       │
       │  各問題 (1..N) ごとに:
       │    ┌────────────────────────┐
       │    │ システムプロンプト      │  品質基準（6項目）
       │    │ + 資料全文              │  スクレイピング結果
       │    │ + 既出テーマリスト      │  重複回避用
       │    └──────────┬─────────────┘
       │               ▼
       │         Ollama /api/chat  →  JSONオブジェクト1問
       │               │
       │    event: question ──────→  リアルタイム表示
       │
       └─ event: done ────────────→  SQLiteにセッション保存
```

### 必要な環境

- **Docker** および **Docker Compose**
- **Ollama** がホストマシン上で起動済みであること

```bash
# Ollamaのインストールと起動確認
ollama serve
ollama list    # インストール済みモデルを確認
```

### クイックスタート

```bash
# 1. 展開
cd quiz-app

# 2. .env サンプルをコピーし必要なら編集（CORS_ORIGINS, OLLAMA_BASE_URL など）
cp .env.sample .env

# 3a. 本番モードで起動（nginx配信、デバッグなし）
docker compose up -d --build

# -- または --

# 3b. 開発モードで起動（Vite HMR + Flask --reload --debug）
docker compose -f docker-compose.dev.yml up -d --build

# 4. ブラウザで開く
open http://localhost:1234
```

> **注意**: 初回ビルド時にcamoufox（Firefoxバイナリ、約200MB）をダウンロードするため、数分かかります。

既定の `docker-compose.yml` は **本番向け** 構成です（nginx + Flask非デバッグ）。
開発時はホットリロード対応の `docker-compose.dev.yml` を使ってください。

ポート:

| サービス | ホストポート | コンテナポート | 備考 |
|----------|-------------|----------------|------|
| フロントエンド | `1234` | `1234` | nginx（本番） / Vite（開発） |
| バックエンド   | `4321` | `4321` | Flask（フロント経由プロキシ）|

### 環境変数

| 変数名 | デフォルト値 | 説明 |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | OllamaのAPIエンドポイント |
| `FLASK_ENV` | `production`（default compose）/ `development`（dev compose） | Flask実行環境 |
| `CORS_ORIGINS` | `http://localhost:1234` | CORSを許可するオリジン（カンマ区切り） |
| `HISTORY_FILE` | `/app/.cache/history.json` | レガシーJSON履歴ファイルパス |
| `DB_PATH` | `/app/.cache/quizgen.db` | SQLiteファイルパス |
| `ALLOW_HTTP` | *(未設定＝`https`のみ許可)* | `1` にすると `http://` も許可。`SECURITY.md` 参照 |
| `ALLOW_PRIVATE_NETWORKS` | *(未設定＝パブリックIPのみ)* | `1` にするとRFC1918/ループバック/リンクローカルも許可。クラウドメタデータIPは常に拒否 |
| `MAX_FETCH_BYTES` | `10485760` (10 MiB) | 外部フェッチのレスポンス最大サイズ |
| `MAX_REDIRECTS` | `3` | リダイレクト回数上限（`0` で無効化）|

#### Linux環境でのOllama接続

Linuxでは `host.docker.internal` が解決できない場合があります:

```bash
OLLAMA_BASE_URL=http://172.17.0.1:11434 docker compose up -d
```

### ディレクトリ構成

```
quiz-app/
├── docker-compose.yml          # 本番向け（nginx、デバッグなし）— 既定
├── docker-compose.dev.yml      # 開発用（Vite HMR + Flask --reload）
├── SECURITY.md                 # 信頼境界・SSRFポリシー・開示手順
├── backend/
│   ├── Dockerfile              # 本番用（camoufox + Xvfb）
│   ├── Dockerfile.dev          # 開発用（Flask --reload --debug）
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py         # Flaskアプリファクトリ
│       ├── database.py         # SQLite設定（documents, quiz_sessions）
│       ├── api/
│       │   ├── health.py       # GET /api/health, GET /api/system/specs
│       │   ├── models.py       # GET /api/models
│       │   ├── content.py      # GET /api/content/scrape-stream (SSE)
│       │   │                   # POST /api/content/preview, /api/content/fetch
│       │   ├── quiz.py         # POST /api/quiz/generate (SSE)
│       │   ├── history.py      # CRUD /api/history（レガシーJSONバック）
│       │   ├── documents.py    # CRUD /api/documents
│       │   └── results.py      # CRUD /api/results（カテゴリ集計含む）
│       └── services/
│           ├── ollama_service.py     # Ollama REST API通信
│           ├── content_service.py    # camoufox BFSスクレイパー（プラグイン構造）
│           ├── quiz_service.py       # 1問ずつ逐次生成ロジック
│           └── history_service.py    # レガシー履歴管理（JSONファイル）
├── frontend/
│   ├── Dockerfile              # マルチステージビルド（nginx配信）
│   ├── Dockerfile.dev          # Vite dev server
│   ├── nginx.conf              # SPAルーティング + APIプロキシ
│   ├── package.json            # axios@1.15.0, vite@6.4.2（完全固定）
│   ├── vite.config.js          # プロキシ + WSL2ポーリングwatch設定
│   └── src/
│       ├── views/
│       │   ├── GeneratePage.vue    # メイン問題生成ページ
│       │   ├── DatabasePage.vue    # 保存済みドキュメント一覧
│       │   ├── ResultsPage.vue     # クイズセッション履歴・スコア
│       │   └── SettingsPage.vue    # Ollama URL設定
│       ├── components/
│       │   └── QuestionCard.vue    # 問題表示 + Mermaid図表レンダリング
│       ├── stores/
│       │   └── index.js            # Piniaストア（quiz, scrape等）
│       └── composables/
│           └── useApi.js           # Axiosインスタンス
└── docs/
```

### API仕様

| メソッド | エンドポイント | 説明 |
|:---|:---|:---|
| GET  | `/api/health` | Ollama接続確認 |
| GET  | `/api/system/specs` | ホストRAM/CPU情報（モデル適合警告用）|
| GET  | `/api/models` | インストール済みモデル一覧 |
| POST | `/api/content/preview` | コンテンツプレビュー（タイトル・抜粋） |
| POST | `/api/content/fetch` | フルコンテンツ取得 |
| GET  | `/api/content/scrape-stream` | SSE: スクレイピング進捗イベント |
| POST | `/api/quiz/generate` | SSE: 1問ずつ逐次生成 |
| GET  | `/api/documents` | 保存済みドキュメント一覧（`?search=` で部分一致）|
| GET  | `/api/documents/by-url` | URL完全一致でドキュメント取得 |
| GET  | `/api/documents/<id>` | ドキュメント詳細（content含む） |
| GET  | `/api/documents/<id>/content-preview` | 先頭500文字プレビュー |
| POST | `/api/documents` | ドキュメント作成（content_hashで重複排除） |
| DELETE | `/api/documents/<id>` | ドキュメント削除 |
| GET  | `/api/results` | セッション一覧（`?document_id=` フィルタ可）|
| GET  | `/api/results/categories` | カテゴリ別集計（レーダーチャート用） |
| GET  | `/api/results/categories/breakdown` | カテゴリ×K1-K4×難易度×トピック 内訳 |
| GET  | `/api/results/<session_id>` | セッション詳細 |
| POST | `/api/results/<session_id>/answers` | 解答・スコアの保存 |
| DELETE | `/api/results/<session_id>` | セッション削除 |
| GET  | `/api/history` | レガシーJSON履歴一覧（`?limit=&offset=`）|
| GET  | `/api/history/<session_id>` | レガシー履歴詳細 |
| DELETE | `/api/history/<session_id>` | レガシー履歴削除 |

SSEエンドポイントは名前付きイベントを送信します。現時点の契約:

| エンドポイント | イベント |
|:---|:---|
| `/api/content/scrape-stream` | `progress`, `done`, `error` |
| `/api/quiz/generate` | `source_info`, `progress`, `question`, `question_error`, `done`, `error` |

#### POST /api/quiz/generate

**リクエスト例:**
```json
{
  "source": "https://example.com/docs",
  "model": "qwen2.5:7b",
  "count": 10,
  "levels": ["K2", "K3"],
  "difficulty": "medium",
  "depth": 3,
  "doc_types": ["table", "pdf"]
}
```

**SSEレスポンスイベント:**
```
event: source_info    → スクレイピング完了、コンテンツメタ情報
event: progress       → { "current": 1, "total": 10, "status": "generating" }
event: question       → 完成した問題のJSONオブジェクト
event: question_error → 個別問題の生成/パース失敗
event: done           → 全問題を含む最終セッションサマリー
event: error          → 致命的エラー
```

### 注意事項

- **Ollamaの起動が必須** - アプリ起動前にホストマシンでOllamaが動作している必要があります。ヘルスチェックが失敗します。
- **Ollamaのバージョン** - 新しいモデルアーキテクチャ（qwen3.5等）は最新のOllamaが必要です。`curl -fsSL https://ollama.com/install.sh | sh` で更新してください。
- **メモリ** - 大規模モデル（70B+）は大量のRAMが必要です。`ollama show <model>` で要件を確認してください。
- **スクレイピング制限** - 1回のクロールで最大50ページ。BFSは同一ドメイン内のみ。結果はSQLiteにcontent_hashで重複排除してキャッシュされます。外部フェッチは既定でパブリックIPのみ許可（`SECURITY.md` 参照）。
- **WSL2環境** - Dockerボリュームのファイル変更検知のため、Viteは `usePolling: true` で設定済みです。
- **依存バージョン** - 実行時依存（`axios` / `chart.js` / `vue-chartjs` / `vite`）は完全固定。`vue` / `vue-router` / `pinia` / `@vitejs/plugin-vue` は現時点でキャレット範囲。Phase 1 で厳格化予定。

### ライセンス

MIT License
