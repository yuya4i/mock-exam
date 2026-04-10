# QuizGen - AI模擬問題自動生成アプリ

URLまたはテキストを指定するだけで、ローカルのOllama AIが自動で模擬問題を生成するWebアプリケーションです。

## 特徴

- **camoufox対応スクレイピング**: ボット検出を回避するFirefoxベースのブラウザで安全にコンテンツ取得
- **階層指定スクレイピング（Max 8）**: 指定URLから最大8階層分のリンクを辿って一括収集（1回のみ実行）
- **対象ファイル限定**: CSV / PDF / PNG / HTMLテーブル のみを選択的に参照
- **モデル選択**: Ollamaにインストール済みの任意のモデルを動的選択
- **知識レベル指定**: K1〜K4（記憶・理解・適用・分析）を組み合わせて指定
- **難易度設定**: 易しい / 普通 / 難しい
- **解答・解説表示**: 選択後に正解と詳細な解説を表示
- **生成履歴管理**: 過去の生成セッションを保存・再閲覧・削除
- **拡張可能な設計**: 新しいコンテンツソース（ローカルファイル等）をプラグインとして追加可能

## 技術スタック

| レイヤー | 技術 | バージョン |
|:---|:---|:---|
| フロントエンド | Vue.js 3 + Vite | Vite **6.4.2**（CVE修正済み） |
| HTTPクライアント | axios | **1.15.0**（サプライチェーン攻撃対策済み） |
| バックエンド | Flask | 3.0.3 |
| スクレイピング | **camoufox** | 最新版（Firefox + ボット検出回避） |
| PDF解析 | pypdf | 4.3.1 |
| AI エンジン | Ollama | ローカル（任意バージョン） |
| コンテナ | Docker + Docker Compose | - |
| Webサーバー | nginx | 1.27-alpine |

## セキュリティ対応（重要）

### axios サプライチェーン攻撃（2026年3月30日）

axios `1.14.1` および `0.30.4` はnpmアカウント乗っ取りによるマルウェア混入バージョンです。
本アプリでは **`axios@1.15.0`** を完全固定（キャレットなし）で採用しています。

| バージョン | 状態 |
|:---|:---|
| `1.14.1` | **危険**（RAT混入・npmから削除済み） |
| `0.30.4` | **危険**（RAT混入・npmから削除済み） |
| `1.14.0` | SSRF脆弱性あり（CVE-2025-68613） |
| **`1.15.0`** | **安全**（SSRF・ヘッダインジェクション修正済み） |

## スクレイピング設計（camoufox）

### 階層スクレイピングの動作

```
URL指定 (depth=3, doc_types=["pdf","table"])
  └─ 階層0: 指定URL（HTMLテーブル抽出）
       ├─ 階層1: リンク先ページA（PDFダウンロード）
       ├─ 階層1: リンク先ページB（HTMLテーブル抽出）
       │    └─ 階層2: リンク先ページC（PDFダウンロード）
       │         └─ 階層3: リンク先ページD（HTMLテーブル抽出）
       └─ 階層1: リンク先ページE（スキップ: 対象外）
```

- **BFS（幅優先探索）**: 同一ドメイン内のリンクのみを辿る
- **1回のみ実行**: 指定階層分を一括収集し、結果をキャッシュ（TTL: 1時間）
- **最大訪問ページ数**: 50ページ（過負荷防止）
- **camoufox**: Playwright互換のFirefoxで実行。ボット検出を回避
- **フォールバック**: camoufoxが利用できない場合はrequestsで代替

### 対象ドキュメント種別

| 種別 | 処理内容 |
|:---|:---|
| **テーブル** | HTMLの `<table>` タグをMarkdownテーブルに変換 |
| **CSV** | CSVをMarkdownテーブルに変換（最大50行） |
| **PDF** | テキスト抽出（最大20ページ） |
| **画像（PNG等）** | URLを記録（画像の内容はOllamaに渡さない） |

### プラグイン拡張方法

`backend/app/services/content_service.py` に新しい `SourcePlugin` を実装するだけで拡張可能：

```python
class LocalFilePlugin(SourcePlugin):
    def can_handle(self, source: str) -> bool:
        return source.startswith('/') or source.startswith('file://')

    def fetch(self, source: str, **kwargs) -> dict:
        # ローカルファイル読み取りロジック
        ...

# ContentService.__init__() に追加（CamoufoxPluginより前に登録）
self.register(LocalFilePlugin())
```

## 必要な環境

- Docker & Docker Compose
- Ollama（ホストマシン上で起動済み）

```bash
# Ollamaのインストールと起動確認
ollama serve
ollama list   # インストール済みモデルを確認
```

## セットアップ

### 1. リポジトリの展開

```bash
unzip quiz-app.zip
cd quiz-app
```

### 2. 環境変数の設定（任意）

```bash
cp .env.example .env
# .envを編集してOllama URLを設定
```

### 3. 起動

```bash
docker compose up -d --build
```

> **注意**: 初回ビルド時にcamoufox（Firefoxバイナリ）をダウンロードするため、数分かかります。

### 4. アクセス

ブラウザで http://localhost:3000 を開く

## 環境変数

| 変数名 | デフォルト値 | 説明 |
|:---|:---|:---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | OllamaのベースURL |
| `FLASK_ENV` | `production` | Flask実行環境 |
| `CORS_ORIGINS` | `http://localhost:3000` | CORSを許可するオリジン |

### Linux環境でのOllama接続

```bash
OLLAMA_BASE_URL=http://172.17.0.1:11434
```

## ディレクトリ構成

```
quiz-app/
├── docker-compose.yml
├── .env.example
├── README.md
├── backend/
│   ├── Dockerfile               # camoufox・Xvfb対応
│   ├── requirements.txt         # camoufox[geoip]・pypdf含む
│   └── app/
│       ├── __init__.py
│       ├── api/
│       │   ├── health.py        # GET  /api/health
│       │   ├── models.py        # GET  /api/models
│       │   ├── content.py       # POST /api/content/preview
│       │   │                    # POST /api/content/fetch
│       │   ├── quiz.py          # POST /api/quiz/generate
│       │   └── history.py       # GET/DELETE /api/history
│       └── services/
│           ├── ollama_service.py    # Ollama API通信
│           ├── content_service.py   # camoufox BFSスクレイピング（プラグイン構造）
│           ├── quiz_service.py      # 問題生成ロジック（depth/doc_types対応）
│           └── history_service.py   # 履歴管理
└── frontend/
    ├── Dockerfile               # マルチステージビルド（nginx配信）
    ├── nginx.conf               # SPA対応 + APIプロキシ
    ├── package.json             # axios@1.15.0・vite@6.4.2 完全固定
    └── src/
        ├── views/
        │   ├── GeneratePage.vue # 階層数指定・ドキュメント種別選択UI
        │   ├── HistoryPage.vue
        │   └── SettingsPage.vue
        └── services/
            └── content_service.py  # ← プラグイン追加はここ
```

## API仕様

| メソッド | エンドポイント | 説明 |
|:---|:---|:---|
| GET | `/api/health` | Ollama接続確認 |
| GET | `/api/models` | モデル一覧取得 |
| POST | `/api/content/preview` | コンテンツプレビュー（depth・doc_types対応） |
| POST | `/api/content/fetch` | フルコンテンツ取得（depth・doc_types対応） |
| POST | `/api/quiz/generate` | 問題生成（depth・doc_types対応） |
| POST | `/api/quiz/generate/stream` | 問題生成（SSEストリーミング） |
| GET | `/api/history` | 履歴一覧 |
| GET | `/api/history/:id` | 履歴詳細 |
| DELETE | `/api/history/:id` | 履歴削除 |

### POST /api/quiz/generate リクエスト例

```json
{
  "source":     "https://jstqb.jp/syllabus.html",
  "model":      "llama3",
  "count":      5,
  "levels":     ["K2", "K3", "K4"],
  "difficulty": "medium",
  "depth":      3,
  "doc_types":  ["table", "pdf", "csv"]
}
```

## ライセンス

MIT License
