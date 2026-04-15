"""
QuizService
1問ずつ個別にOllamaを呼び出し、品質を均一に保つ問題生成サービス。
スクレイピング完了後、既出トピックを除外しながら順次生成する。
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from app.services.ollama_service import OllamaService
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

# ======================================================================
# 品質保証システムプロンプト
# ======================================================================
SYSTEM_PROMPT = """\
あなたは資格試験問題作成の専門家です。
与えられた学習資料の内容に厳密に基づき、**1問だけ**高品質な4択問題を作成してください。

━━━ 品質基準 ━━━

1. **正確性**: 問題文・選択肢・解説はすべて提供された学習資料の記述に基づくこと。
   資料に記載のない情報を捏造しないこと。
2. **明瞭性**: 問題文は一読で意味が確定する明確な日本語で書くこと。
   二重否定・曖昧な限定詞（「ほとんど」「多くの場合」等）は避ける。
3. **誘引力のある選択肢**: 不正解の選択肢（ディストラクタ）は、
   学習が不十分な受験者が選びそうな「もっともらしい誤り」にすること。
   明らかに関係のない選択肢は含めない。
4. **解説の深さ**: 正解の根拠を資料の該当箇所を引用して説明し、
   さらに各不正解選択肢がなぜ誤りかを個別に解説すること（合計200字以上）。
5. **知識レベルの遵守**:
   - K1（記憶）: 定義・用語の正確な想起を問う
   - K2（理解）: 概念の意味・目的・理由を問う
   - K3（適用）: 具体的なシナリオで正しい行動・判断を問う
   - K4（分析）: 複数の概念を比較・統合・評価させる
6. **図表の活用**: 問題の理解を助けるためにグラフ・フローチャート・表などが
   有効な場合は、`diagram` フィールドにMermaid記法で図を記述してよい。
   不要であれば `diagram` は空文字列 "" にすること。
   利用可能なMermaid記法:
   - `graph TD` / `flowchart LR`: プロセス・分岐・フロー図
   - `sequenceDiagram`: 処理シーケンス・通信手順
   - `classDiagram`: クラス構造・継承関係
   - `stateDiagram-v2`: 状態遷移
   - `erDiagram`: エンティティ関係（DBスキーマ等）
   - `gantt`: スケジュール・ガントチャート
   - `pie`: 割合・円グラフ
   - `gitGraph`: バージョン管理・ブランチ戦略
   - `mindmap`: 概念マップ・階層構造
   - `timeline`: 時系列・歴史的変遷
   - `xychart-beta`: 散布図・折れ線グラフ・棒グラフ
   - `quadrantChart`: 象限分析（重要度×緊急度 等）
   - `journey`: ユーザージャーニー・体験マップ
   - `requirementDiagram`: 要求事項の関連
   - `sankey-beta`: 流量・遷移可視化
   - `C4Context`: アーキテクチャコンテキスト図
   問題内容に最適な記法を1つ選択すること（画一的に同じ記法を使わない）。

━━━ 出力形式（厳守） ━━━

以下のJSONオブジェクト **1つのみ** を出力してください。前後に説明文を付けないこと。

```json
{
  "id": "Q001",
  "level": "K2",
  "topic": "テーマ名",
  "question": "問題文",
  "diagram": "graph TD; A-->B",
  "choices": {
    "a": "選択肢a",
    "b": "選択肢b",
    "c": "選択肢c",
    "d": "選択肢d"
  },
  "answer": "a",
  "explanation": "正解の根拠と各選択肢の解説（200字以上）",
  "source_hint": "根拠となる資料の章・セクション名"
}
```
"""

# ======================================================================
# 1問生成用ユーザープロンプト
# ======================================================================
SINGLE_Q_TEMPLATE = """\
以下の学習資料から模擬問題を **1問だけ** 作成してください。

【条件】
- 問題ID: Q{qnum:03d}
- 知識レベル: {level}
- 難易度: {difficulty}
- 言語: 日本語

{previous_topics_block}

【学習資料】
タイトル: {title}
出典: {source}
収集ページ数: {page_count}
収集ドキュメント種別: {doc_types}

{content}

【出力】
JSONオブジェクト1つのみを出力してください。"""


def _build_previous_topics_block(topics: list[str]) -> str:
    if not topics:
        return ""
    listing = "\n".join(f"  - {t}" for t in topics)
    return (
        "【既出テーマ（重複禁止）】\n"
        "以下のテーマは既に出題済みです。これらと異なる観点・セクションから出題すること。\n"
        f"{listing}\n"
    )


# ======================================================================
# QuizService
# ======================================================================
class QuizService:
    def __init__(self):
        self.ollama = OllamaService()
        self.content = ContentService()

    # ------------------------------------------------------------------
    # 1問ずつSSEストリーミング生成（メインAPI）
    # ------------------------------------------------------------------
    def generate_incremental(
        self,
        source: str,
        model: str,
        count: int = 5,
        levels: list[str] | None = None,
        difficulty: str = "medium",
        depth: int = 1,
        doc_types: list[str] | None = None,
        ollama_options: dict | None = None,
        session_id: str | None = None,
        existing_topics: list[str] | None = None,
        source_info_override: dict | None = None,
    ):
        """
        スクレイピング→1問ずつ生成のジェネレータ。
        各yieldは (event_type, data_dict) のタプル。

        Append mode (引数 ``session_id`` + ``existing_topics`` で起動):
            - session_id を使い回す (新しい uuid を発行しない)。
            - existing_topics を「既出テーマ」として diversity prompt の
              シードに混ぜ、新しく生成する問題が既存問題と被らないよう
              にする。
            - done イベントで返す ``questions`` は **新規分のみ**。マージは
              呼び出し側 (route handler) が行う。

        ``source_info_override`` (dict):
            スクレイピング結果の shape と同じ辞書を渡すと、ContentService
            の fetch を完全にバイパスする。保存済みセッションの再生成で
            ``documents`` テーブルから content を読み込んでそのまま使う
            ユースケース想定 (再スクレイプ不要)。
        """
        if levels is None:
            levels = ["K2", "K3", "K4"]
        if doc_types is None:
            doc_types = ["table", "csv", "pdf", "png"]

        if session_id is None:
            session_id = str(uuid.uuid4())

        # ── Step 1: コンテンツ取得 ──
        if source_info_override is not None:
            source_info = source_info_override
        else:
            source_info = self.content.fetch(source, depth=depth, doc_types=doc_types)

        yield ("source_info", {
            "session_id":  session_id,
            "title":       source_info["title"],
            "source":      source_info["source"],
            "type":        source_info["type"],
            "depth":       source_info.get("depth", depth),
            "doc_types":   source_info.get("doc_types", doc_types),
            "page_count":  source_info.get("page_count", 1),
            "document_id": source_info.get("document_id"),
        })

        # ── Step 2: 1問ずつ生成 ──
        # Seed diversity prompt with existing topics if append mode.
        generated_topics: list[str] = list(existing_topics) if existing_topics else []
        questions: list[dict] = []

        # レベルを問題数に応じてラウンドロビンで割り当て
        level_cycle = levels * ((count // len(levels)) + 1)

        options = {"temperature": 0.7, "num_predict": 1024}
        if ollama_options:
            options.update(ollama_options)

        for i in range(count):
            qnum = i + 1
            level = level_cycle[i]

            yield ("progress", {
                "current": qnum,
                "total":   count,
                "status":  "generating",
            })

            user_prompt = SINGLE_Q_TEMPLATE.format(
                qnum=qnum,
                level=level,
                difficulty=difficulty,
                previous_topics_block=_build_previous_topics_block(generated_topics),
                title=source_info["title"],
                source=source_info["source"],
                page_count=source_info.get("page_count", 1),
                doc_types=" / ".join(source_info.get("doc_types", doc_types)),
                content=source_info["content"],
            )

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ]

            try:
                question = None
                for attempt in range(2):
                    raw = self.ollama.chat(model, messages, options)
                    question = self._parse_single_question(raw, qnum)
                    if question:
                        break
                    logger.warning(
                        f"Q{qnum:03d}: パース失敗 (attempt {attempt+1}) — "
                        f"raw={raw[:200]}"
                    )

                if question:
                    questions.append(question)
                    generated_topics.append(
                        f"{question['topic']} ({question['level']})"
                    )
                    yield ("question", question)
                else:
                    yield ("question_error", {
                        "qnum": qnum,
                        "error": "問題のパースに失敗しました（2回リトライ済み）",
                    })

            except Exception as e:
                logger.error(f"Q{qnum:03d}: 生成エラー — {e}")
                yield ("question_error", {
                    "qnum": qnum,
                    "error": str(e),
                })

        # ── Step 3: 完了 ──
        yield ("done", {
            "session_id":   session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model":        model,
            "question_count": len(questions),
            "questions":    questions,
            "source_info": {
                "title":       source_info["title"],
                "source":      source_info["source"],
                "type":        source_info["type"],
                "depth":       source_info.get("depth", depth),
                "doc_types":   source_info.get("doc_types", doc_types),
                "page_count":  source_info.get("page_count", 1),
                "pages":       source_info.get("pages", []),
                "document_id": source_info.get("document_id"),
            },
        })

    # ------------------------------------------------------------------
    # 1問だけ生成（差し替え用 — Mermaid SyntaxError 等で使う）
    # ------------------------------------------------------------------
    def generate_single_question(
        self,
        source: str,
        model: str,
        level: str = "K2",
        difficulty: str = "medium",
        depth: int = 1,
        doc_types: list[str] | None = None,
        ollama_options: dict | None = None,
        exclude_topics: list[str] | None = None,
        qnum: int = 1,
        source_info_override: dict | None = None,
    ) -> dict | None:
        """Generate exactly one question. Returns the question dict, or
        None if both attempts fail to parse.

        ``exclude_topics`` are forwarded to the diversity prompt so the
        new question explores a different theme — including the topic
        of the question being replaced. Caller is responsible for
        composing that list (existing topics + failing topic).

        ``source_info_override`` (dict) — same contract as
        ``generate_incremental``: when provided, skips ContentService
        entirely. Used by the saved-session regenerate paths to avoid
        re-scraping content we already have in the ``documents`` table.
        """
        if doc_types is None:
            doc_types = ["table", "csv", "pdf", "png"]

        if source_info_override is not None:
            source_info = source_info_override
        else:
            source_info = self.content.fetch(source, depth=depth, doc_types=doc_types)

        options = {"temperature": 0.7, "num_predict": 1024}
        if ollama_options:
            options.update(ollama_options)

        user_prompt = SINGLE_Q_TEMPLATE.format(
            qnum=qnum,
            level=level,
            difficulty=difficulty,
            previous_topics_block=_build_previous_topics_block(exclude_topics or []),
            title=source_info["title"],
            source=source_info["source"],
            page_count=source_info.get("page_count", 1),
            doc_types=" / ".join(source_info.get("doc_types", doc_types)),
            content=source_info["content"],
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ]

        for attempt in range(2):
            raw = self.ollama.chat(model, messages, options)
            question = self._parse_single_question(raw, qnum)
            if question:
                return question
            logger.warning(
                f"regenerate_single Q{qnum:03d}: パース失敗 (attempt {attempt+1}) — "
                f"raw={raw[:200]}"
            )
        return None

    # ------------------------------------------------------------------
    # 一括生成（後方互換）
    # ------------------------------------------------------------------
    def generate(self, **kwargs) -> dict:
        """generate_incremental のラッパー。全問生成後にまとめて返す。"""
        result = {}
        for event_type, data in self.generate_incremental(**kwargs):
            if event_type == "done":
                result = data
        return result

    # ------------------------------------------------------------------
    # 1問パース（堅牢版）
    # ------------------------------------------------------------------
    def _parse_single_question(self, raw: str, qnum: int) -> dict | None:
        text = re.sub(r"```(?:json)?\s*", "", raw)
        text = text.replace("```", "").strip()

        # JSONオブジェクトを抽出（最外側の {} を見つける）
        start = text.find("{")
        if start == -1:
            return None

        # ブレース対応で正しい終了位置を見つける
        depth = 0
        end = -1
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == '\\' and in_string:
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end == -1:
            return None

        json_str = text[start:end + 1]

        try:
            q = json.loads(json_str)
        except json.JSONDecodeError:
            # 制御文字や不正なエスケープを除去してリトライ
            cleaned = re.sub(r'[\x00-\x1f]', ' ', json_str)
            try:
                q = json.loads(cleaned)
            except json.JSONDecodeError:
                logger.debug(f"JSON parse failed: {json_str[:300]}")
                return None

        if not isinstance(q, dict) or "question" not in q:
            return None

        return self._normalize_question(q, qnum - 1)

    @staticmethod
    def _sanitize_diagram(raw_diagram: str) -> str:
        """Mermaid記法として有効になるようサニタイズする。"""
        if not raw_diagram or not raw_diagram.strip():
            return ""
        d = raw_diagram.strip()
        # HTMLタグ系の改行をLFに置換
        d = re.sub(r'<br\s*/?\s*>', '\n', d, flags=re.IGNORECASE)
        # 残ったHTMLタグを除去
        d = re.sub(r'<[^>]+>', '', d)
        # HTMLエンティティをデコード
        d = d.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        d = d.replace('&quot;', '"').replace('&#39;', "'")
        # Mermaidとして最低限有効か（先頭キーワードチェック）
        first_line = d.split('\n')[0].strip().lower()
        valid_starts = (
            'graph ', 'flowchart ', 'sequencediagram', 'classdiagram',
            'statediagram', 'statediagram-v2', 'erdiagram', 'gantt',
            'pie', 'gitgraph', 'mindmap', 'timeline', 'xychart',
            'xychart-beta', 'block-beta', 'quadrantchart', 'journey',
            'requirementdiagram', 'sankey-beta', 'packet-beta',
            'c4context', 'c4container', 'c4component', 'c4dynamic',
            'architecture-beta',
        )
        if not any(first_line.startswith(s) for s in valid_starts):
            return ""
        return d

    def _normalize_question(self, q: dict, index: int) -> dict:
        return {
            "id":          q.get("id", f"Q{index + 1:03d}"),
            "level":       q.get("level", "K2"),
            "topic":       q.get("topic", "不明"),
            "question":    q.get("question", ""),
            "diagram":     self._sanitize_diagram(q.get("diagram", "")),
            "choices":     q.get("choices", {}),
            "answer":      q.get("answer", ""),
            "explanation": q.get("explanation", ""),
            "source_hint": q.get("source_hint", ""),
        }
