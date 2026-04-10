# QuizGen - AI Quiz Generator / AI模擬問題自動生成アプリ

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

A web application that generates high-quality quiz questions from any URL or text using a local Ollama LLM. Scrapes web content with bot-detection evasion, then generates questions **one at a time** with consistent quality and optional Mermaid diagrams.

### Features

- **Camoufox Scraping** - Firefox-based browser with bot-detection evasion (Playwright-compatible)
- **Deep Crawling (Max 8 levels)** - BFS traversal of same-domain links with selective document extraction
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
Browser (localhost:3000)
  │
  ├─ GET  /api/content/scrape-stream  →  SSE scraping progress
  │
  └─ POST /api/quiz/generate          →  SSE (1 question per event)
       │
       │  For each question (1..N):
       │    ┌──────────────────────┐
       │    │ System Prompt        │  Quality rubric (6 criteria)
       │    │ + Source Material     │  Full scraped content
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

# 2. Start (development mode with hot reload)
docker compose up -d --build

# 3. Open browser
open http://localhost:3000
```

> **Note**: First build downloads the camoufox Firefox binary (~200MB), which may take several minutes.

### Production Deployment

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Production uses nginx to serve the built frontend and Flask without debug mode.

### Environment Variables

| Variable | Default | Description |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API endpoint |
| `FLASK_ENV` | `development` | Flask environment (`production` in prod compose) |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `HISTORY_FILE` | `/app/.cache/history.json` | Legacy history file path |

#### Linux Host

On Linux, `host.docker.internal` may not resolve. Use:

```bash
OLLAMA_BASE_URL=http://172.17.0.1:11434 docker compose up -d
```

### Project Structure

```
quiz-app/
├── docker-compose.yml          # Dev (hot reload, Vite dev server)
├── docker-compose.prod.yml     # Production (nginx, no debug)
├── docker-compose.dev.yml      # Dev explicit (alternative)
├── backend/
│   ├── Dockerfile              # Production (camoufox + Xvfb)
│   ├── Dockerfile.dev          # Dev (Flask --reload --debug)
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py         # Flask app factory
│       ├── database.py         # SQLite setup (documents, quiz_sessions)
│       ├── api/
│       │   ├── health.py       # GET  /api/health
│       │   ├── models.py       # GET  /api/models
│       │   ├── content.py      # GET  /api/content/scrape-stream (SSE)
│       │   │                   # POST /api/content/preview
│       │   │                   # POST /api/content/fetch
│       │   ├── quiz.py         # POST /api/quiz/generate (SSE)
│       │   ├── documents.py    # CRUD /api/documents
│       │   └── results.py      # CRUD /api/results
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
| GET | `/api/health` | Ollama connectivity check |
| GET | `/api/models` | List installed Ollama models |
| POST | `/api/content/preview` | Preview content (title, excerpt) |
| POST | `/api/content/fetch` | Fetch full content |
| GET | `/api/content/scrape-stream` | SSE: Scraping progress events |
| POST | `/api/quiz/generate` | SSE: Incremental question generation |
| GET | `/api/documents` | List saved documents |
| GET | `/api/results` | List quiz sessions |
| POST | `/api/results/:id/answers` | Save user answers and score |

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
- **Scraping**: Max 50 pages per crawl. Stays within the same domain. Results are cached (content hash dedup in SQLite).
- **WSL2**: Vite is configured with `usePolling: true` for Docker volume file watching to work correctly.
- **axios security**: Version 1.15.0 is pinned exactly (no caret) to avoid the 1.14.1 supply chain attack (March 2026).

### License

MIT License

---

## 日本語

URLまたはテキストを入力するだけで、ローカルのOllama AIが **1問ずつ** 高品質な模擬問題を生成するWebアプリケーションです。

### 特徴

- **camoufox対応スクレイピング** - ボット検出を回避するFirefoxベースのブラウザで安全にコンテンツ取得
- **階層指定スクレイピング（最大8階層）** - 同一ドメイン内のリンクをBFSで辿り、ドキュメントを選択的に収集
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
ブラウザ (localhost:3000)
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

# 2. 起動（開発モード・ホットリロード対応）
docker compose up -d --build

# 3. ブラウザで開く
open http://localhost:3000
```

> **注意**: 初回ビルド時にcamoufox（Firefoxバイナリ、約200MB）をダウンロードするため、数分かかります。

### 本番デプロイ

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

本番環境ではnginxでビルド済みフロントエンドを配信し、Flaskはデバッグモードなしで動作します。

### 環境変数

| 変数名 | デフォルト値 | 説明 |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | OllamaのAPIエンドポイント |
| `FLASK_ENV` | `development` | Flask実行環境（本番では`production`） |
| `CORS_ORIGINS` | `http://localhost:3000` | CORSを許可するオリジン |
| `HISTORY_FILE` | `/app/.cache/history.json` | レガシー履歴ファイルパス |

#### Linux環境でのOllama接続

Linuxでは `host.docker.internal` が解決できない場合があります:

```bash
OLLAMA_BASE_URL=http://172.17.0.1:11434 docker compose up -d
```

### ディレクトリ構成

```
quiz-app/
├── docker-compose.yml          # 開発用（ホットリロード、Vite dev server）
├── docker-compose.prod.yml     # 本番用（nginx、デバッグなし）
├── docker-compose.dev.yml      # 開発用（明示的な代替構成）
├── backend/
│   ├── Dockerfile              # 本番用（camoufox + Xvfb）
│   ├── Dockerfile.dev          # 開発用（Flask --reload --debug）
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py         # Flaskアプリファクトリ
│       ├── database.py         # SQLite設定（documents, quiz_sessions）
│       ├── api/
│       │   ├── health.py       # GET  /api/health
│       │   ├── models.py       # GET  /api/models
│       │   ├── content.py      # GET  /api/content/scrape-stream (SSE)
│       │   │                   # POST /api/content/preview
│       │   │                   # POST /api/content/fetch
│       │   ├── quiz.py         # POST /api/quiz/generate (SSE)
│       │   ├── documents.py    # CRUD /api/documents
│       │   └── results.py      # CRUD /api/results
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
| GET | `/api/health` | Ollama接続確認 |
| GET | `/api/models` | インストール済みモデル一覧 |
| POST | `/api/content/preview` | コンテンツプレビュー（タイトル・抜粋） |
| POST | `/api/content/fetch` | フルコンテンツ取得 |
| GET | `/api/content/scrape-stream` | SSE: スクレイピング進捗イベント |
| POST | `/api/quiz/generate` | SSE: 1問ずつ逐次生成 |
| GET | `/api/documents` | 保存済みドキュメント一覧 |
| GET | `/api/results` | クイズセッション一覧 |
| POST | `/api/results/:id/answers` | 解答・スコアの保存 |

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
- **スクレイピング制限** - 1回のクロールで最大50ページ。同一ドメイン内のみ。結果はSQLiteにコンテンツハッシュで重複排除してキャッシュされます。
- **WSL2環境** - Dockerボリュームのファイル変更検知のため、Viteは `usePolling: true` で設定済みです。
- **axiosセキュリティ** - バージョン1.15.0を完全固定（キャレットなし）。1.14.1のサプライチェーン攻撃（2026年3月）を回避しています。

### ライセンス

MIT License
