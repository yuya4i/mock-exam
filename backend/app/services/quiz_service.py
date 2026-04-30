"""
QuizService
1問ずつ個別にOllamaを呼び出し、品質を均一に保つ問題生成サービス。
スクレイピング完了後、既出トピックを除外しながら順次生成する。
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from app.services.ollama_service import OllamaService
from app.services.content_service import ContentService

logger = logging.getLogger(__name__)

# Cap on Mermaid diagram source length (chars). LLM occasionally emits
# absurdly large diagrams (or a prompt-injected source could try to);
# we drop anything over this so the FE parser doesn't get DoS'd and so
# v-html doesn't ship 100KB of attacker-controlled bytes to the DOM
# (SEC-2 mitigation, defense-in-depth atop Mermaid's strict mode).
MAX_DIAGRAM_CHARS = 8_000

# ======================================================================
# LLM 性能チューニング (PERF-B)
# ======================================================================
# Ollama の num_ctx デフォルトは 2048 トークン。 content (~12000 文字 ≈
# 6000+ トークン) を渡すとモデル側で勝手に truncate されて品質劣化する
# ため、content 量に応じて動的に num_ctx を設定する。最大値は GPU/メモリ
# 依存だが、汎用 8B モデルなら 8192 が現実的な上限。OLLAMA_NUM_CTX_MAX
# 環境変数で運用上の上限を引き上げ可能。
NUM_CTX_DEFAULT     = 8192
NUM_CTX_MIN         = 2048
NUM_CTX_MAX         = int(os.getenv("OLLAMA_NUM_CTX_MAX", "8192"))
# 1 文字 ≒ 0.5 token (日本語) の概算 + system_prompt (~600 token) +
# 出力余裕 1024 で逆算。安全側に倒すため 0.6 倍。
CHARS_PER_TOKEN     = 0.6
SYSTEM_PROMPT_TOKENS_EST = 600
OUTPUT_RESERVE_TOKENS    = 1024

# Per-question 試行時間 (連結タイムアウト)。Ollama の (connect, read) で渡す。
# 大きい num_ctx + 重いモデル (20B+) では最初の token までに 30〜60 秒
# かかるので read は十分に取る。
QUESTION_CONNECT_TIMEOUT = int(os.getenv("OLLAMA_CONNECT_TIMEOUT", "5"))
QUESTION_READ_TIMEOUT    = int(os.getenv("OLLAMA_READ_TIMEOUT", "180"))

# モデル自動フォールバック。指定された model が未インストール時に
# OLLAMA_FALLBACK_MODELS (カンマ区切り) を順に試す。空ならエラー。
FALLBACK_MODELS = [
    m.strip() for m in os.getenv("OLLAMA_FALLBACK_MODELS", "").split(",")
    if m.strip()
]


def _compute_num_ctx(content_chars: int) -> int:
    """Pick an Ollama num_ctx that fits this session's content + system
    prompt + output reserve, clamped to the operator's MAX."""
    estimated = (
        int(content_chars * CHARS_PER_TOKEN)
        + SYSTEM_PROMPT_TOKENS_EST
        + OUTPUT_RESERVE_TOKENS
    )
    # Round up to the next power-of-two-ish for cleaner allocation.
    # (Ollama doesn't strictly require this, but it keeps the value
    # human-readable and avoids per-question fluctuation.)
    for tier in (2048, 4096, 6144, 8192, 12288, 16384, 24576, 32768):
        if estimated <= tier:
            return min(tier, max(NUM_CTX_MIN, NUM_CTX_MAX))
    return min(NUM_CTX_MAX, 32768)

# ======================================================================
# 品質保証システムプロンプト
# ======================================================================
SYSTEM_PROMPT = """\
あなたは資格試験問題作成の専門家です。提供された学習資料に厳密に基づき、高品質な4択問題を1問だけ作成してください。

【品質基準】
1. 正確性: 問題・選択肢・解説は全て資料の記述に基づき、捏造しない。
2. 明瞭性: 一読で意味が確定する日本語。二重否定・曖昧な限定詞は禁止。
3. ディストラクタ: 不正解は「学習不足者が選びそうな もっともらしい誤り」に。
4. 解説: 正解の根拠を資料から引用 + 各不正解の誤り理由を個別解説 (合計200字以上)。
5. 知識レベル:
   - K1 記憶: 用語/定義の想起
   - K2 理解: 概念の意味・目的・理由
   - K3 適用: 具体シナリオでの判断
   - K4 分析: 複数概念の比較/統合/評価
6. 図表 (任意): 理解を助けるなら `diagram` に Mermaid 記法で記述。不要なら `""`。
   使える記法: graph TD / flowchart LR / sequenceDiagram / classDiagram /
   stateDiagram-v2 / erDiagram / gantt / pie / mindmap / timeline /
   xychart-beta / quadrantChart / journey / sankey-beta / C4Context
   問題内容に最適なものを 1 つ選ぶ (画一的に同じ記法を使わない)。

【出力】
以下の JSON オブジェクト 1 つだけを返す。前後に説明文を付けない。
```json
{
  "id": "Q001",
  "level": "K2",
  "topic": "テーマ名",
  "question": "問題文",
  "diagram": "graph TD; A-->B",
  "choices": {"a": "...", "b": "...", "c": "...", "d": "..."},
  "answer": "a",
  "explanation": "200字以上の解説",
  "source_hint": "資料の章・セクション名"
}
```
"""

# ======================================================================
# 1問生成用ユーザープロンプト
# ======================================================================
SINGLE_Q_TEMPLATE = """\
【学習資料】
タイトル: {title}
出典: {source}
収集ページ数: {page_count}
収集ドキュメント種別: {doc_types}

{content}

━━━ ここから出題条件 (問題ごとに変化) ━━━

【条件】
- 問題ID: Q{qnum:03d}
- 知識レベル: {level}
- 難易度: {difficulty}
- 言語: 日本語

{previous_topics_block}

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


def _is_valid_question_shape(q) -> bool:
    """Strict structural check on a JSON object the LLM returned as a
    single quiz question (SEC-1).

    Hard failures (return False so the caller retries):
        - not a dict
        - ``question`` missing or empty / whitespace-only
        - ``choices`` missing, not a dict, or has fewer than 2 entries
        - any choice value isn't a non-empty string
        - any choice key isn't a non-empty string
        - ``answer`` missing or doesn't equal one of the choice keys
          (case-insensitive)

    Soft issues (level/topic/explanation/source_hint missing or wrong
    type) are left for ``_normalize_question`` to default.
    """
    if not isinstance(q, dict):
        return False
    question = q.get("question")
    if not isinstance(question, str) or not question.strip():
        return False
    choices = q.get("choices")
    if not isinstance(choices, dict) or len(choices) < 2:
        return False
    keys_lower: set[str] = set()
    for k, v in choices.items():
        if not isinstance(k, str) or not k.strip():
            return False
        if not isinstance(v, str) or not v.strip():
            return False
        keys_lower.add(k.strip().lower())
    answer = q.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return False
    if answer.strip().lower() not in keys_lower:
        return False
    return True


def _normalize_question_text(text: str) -> str:
    """Normalize a question body for duplicate detection.

    Collapses whitespace, lowercases, and trims trailing punctuation so
    minor wording differences ("... か？" vs " ...か") that don't change
    semantic meaning still match. Not a semantic dedupe (we're not
    embedding) — just a cheap post-generation filter to catch the
    obvious "LLM echoed the same question again" case.
    """
    if not text or not isinstance(text, str):
        return ""
    t = re.sub(r"\s+", " ", text.strip()).lower()
    t = re.sub(r"[。？?！!、,.\s]+$", "", t)
    return t


# ======================================================================
# QuizService
# ======================================================================
class QuizService:
    def __init__(self):
        self.ollama = OllamaService()
        self.content = ContentService()

    # ------------------------------------------------------------------
    # PERF-B Phase 5: モデル解決 + 自動フォールバック
    # ------------------------------------------------------------------
    def _resolve_model(self, requested: str) -> str:
        """Return the actual model name to send to Ollama.

        Resolution order:
          1. ``requested`` is installed → use as-is.
          2. ``OLLAMA_FALLBACK_MODELS`` (env, comma-separated) — first
             one that's installed wins, logged so the operator notices.
          3. ``requested`` is unknown AND no fallback → return ``requested``
             unchanged so Ollama can either auto-pull it (the default
             behavior since v0.1.x) or surface its own clear "model not
             found" error. We don't pre-empt that case because:
               - tests mock ``self.ollama`` and shouldn't need to also
                 mock ``list_models``,
               - some operators rely on Ollama's auto-pull on first use,
               - the upstream error message is more actionable than
                 our pre-flight one when the listing itself fails.
          4. ``ConnectionError`` from list_models propagates so the API
             layer maps it to 503 (Ollama unreachable, distinct from
             "model missing").
        """
        try:
            installed = [m["name"] for m in self.ollama.list_models()]
        except ConnectionError:
            raise
        except Exception as e:
            logger.warning(
                f"_resolve_model: list_models 失敗 ({e}) — "
                f"指定 model={requested!r} のまま継続"
            )
            return requested

        if requested in installed:
            return requested

        for fallback in FALLBACK_MODELS:
            if fallback in installed:
                logger.warning(
                    f"[QuizService] model={requested!r} 未インストール — "
                    f"フォールバック {fallback!r} に切替"
                )
                return fallback

        if installed:
            logger.warning(
                f"[QuizService] model={requested!r} 未インストール (installed={installed[:5]}...) — "
                f"そのまま Ollama に投げる (auto-pull or error 任せ)"
            )
        return requested

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
        qnum_start: int = 1,
        exclude_question_texts: list[str] | None = None,
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

        # PERF-B Phase 5: モデル解決をループ前に 1 回だけ。指定 model が
        # 未インストールでも、FALLBACK_MODELS にインストール済みのものが
        # あれば自動切替。20 問生成中に毎回 fail するのを防ぐ。
        try:
            model = self._resolve_model(model)
        except ConnectionError:
            # Ollama 自体に届かない (起動してない等)。upstream に流す。
            raise

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

        # Duplicate-text guard. Normalized forms of the existing questions
        # plus every new question we generate, so the LLM can't echo back
        # a theme we've already covered. The set grows as we stream.
        seen_texts: set[str] = {
            _normalize_question_text(t) for t in (exclude_question_texts or []) if t
        }
        # Remove the empty string (from questions that had no "question" field).
        seen_texts.discard("")

        # レベルを問題数に応じてラウンドロビンで割り当て
        level_cycle = levels * ((count // len(levels)) + 1)

        # PERF-B Phase 4: content 量から num_ctx を動的に決める。Ollama
        # default 2048 のままだと 12000 文字 (~7000 token) の content が
        # モデル側で truncate されて品質劣化する。
        num_ctx = _compute_num_ctx(len(source_info.get("content", "")))
        options = {
            "temperature": 0.7,
            "num_predict": 1024,
            "num_ctx":     num_ctx,
        }
        if ollama_options:
            options.update(ollama_options)
        timeout = (QUESTION_CONNECT_TIMEOUT, QUESTION_READ_TIMEOUT)
        logger.info(
            f"[QuizService] model={model} num_ctx={num_ctx} "
            f"timeout={timeout} count={count}"
        )

        for i in range(count):
            # qnum は append モードで既存件数の続きから振る。
            # 既存が Q001-Q010 で count=20 の append なら Q011-Q030。
            # ID 衝突によって新問題がユーザーの既存回答を継承する
            # (= 回答済み扱いになる) バグを防ぐ。
            qnum = qnum_start + i
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
                for attempt in range(3):
                    raw = self.ollama.chat(model, messages, options, timeout=timeout)
                    parsed = self._parse_single_question(raw, qnum)
                    if not parsed:
                        logger.warning(
                            f"Q{qnum:03d}: パース失敗 (attempt {attempt+1}) — "
                            f"raw={raw[:200]}"
                        )
                        continue
                    # Duplicate-body guard: if the question text matches
                    # one we've already emitted (or one from the existing
                    # session), skip and retry with the same prompt —
                    # diversity preamble should nudge the next attempt.
                    q_text_norm = _normalize_question_text(parsed.get("question", ""))
                    if q_text_norm and q_text_norm in seen_texts:
                        logger.info(
                            f"Q{qnum:03d}: 重複 question body 検出 — retry "
                            f"(attempt {attempt+1})"
                        )
                        continue
                    question = parsed
                    if q_text_norm:
                        seen_texts.add(q_text_norm)
                    break

                if question:
                    questions.append(question)
                    generated_topics.append(
                        f"{question['topic']} ({question['level']})"
                    )
                    yield ("question", question)
                else:
                    yield ("question_error", {
                        "qnum": qnum,
                        "error": "問題のパースに失敗しました、または重複を解消できませんでした（3回リトライ済み）",
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
        exclude_question_texts: list[str] | None = None,
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

        # PERF-B Phase 5: model resolve + fallback (same path as
        # generate_incremental). Single-question regenerate also benefits
        # from the auto-fallback if the originally chosen model has been
        # uninstalled since the parent session was created.
        model = self._resolve_model(model)

        if source_info_override is not None:
            source_info = source_info_override
        else:
            source_info = self.content.fetch(source, depth=depth, doc_types=doc_types)

        # PERF-B Phase 4: dynamic num_ctx + per-call timeout.
        num_ctx = _compute_num_ctx(len(source_info.get("content", "")))
        options = {
            "temperature": 0.7,
            "num_predict": 1024,
            "num_ctx":     num_ctx,
        }
        if ollama_options:
            options.update(ollama_options)
        timeout = (QUESTION_CONNECT_TIMEOUT, QUESTION_READ_TIMEOUT)

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

        seen_texts: set[str] = {
            _normalize_question_text(t) for t in (exclude_question_texts or []) if t
        }
        seen_texts.discard("")

        for attempt in range(3):
            raw = self.ollama.chat(model, messages, options, timeout=timeout)
            parsed = self._parse_single_question(raw, qnum)
            if not parsed:
                logger.warning(
                    f"regenerate_single Q{qnum:03d}: パース失敗 (attempt {attempt+1}) — "
                    f"raw={raw[:200]}"
                )
                continue
            norm = _normalize_question_text(parsed.get("question", ""))
            if norm and norm in seen_texts:
                logger.info(
                    f"regenerate_single Q{qnum:03d}: 重複検出 — retry "
                    f"(attempt {attempt+1})"
                )
                continue
            return parsed
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

        # SEC-1: structural validation BEFORE normalize. Without this,
        # the LLM could return {"question": "x"} with no choices/answer
        # and we'd happily render a dead-end card with no answerable
        # buttons. Each "hard" failure here returns None so the caller's
        # retry loop produces another candidate; "soft" defaults are
        # left to _normalize_question.
        if not _is_valid_question_shape(q):
            return None

        return self._normalize_question(q, qnum - 1)

    @staticmethod
    def _sanitize_diagram(raw_diagram: str) -> str:
        """Mermaid記法として有効になるようサニタイズし、XSSになり得る
        危険トークンを除去する。

        Mermaid (>=11) は default ``securityLevel='strict'`` で v-html
        sink に流す前に DOMPurify を通すので一次防御は FE 側にあるが、
        将来 mermaid のデフォルトが緩和されたり LLM が巨大な diagram を
        吐いた時に v-html 経由で 100KB クラスのバイト列が DOM に流れ込む
        のは避けたい。バックエンド境界で:
            1. 長さ上限 MAX_DIAGRAM_CHARS を超えたら丸ごと棄却。
            2. 完全な HTML タグ ``<...>`` を除去。
            3. 閉じ ``>`` 無し の ``<scriptxxx`` 形 (regex 1 がスキップする)
               も dangling-tag-opener として剝がす。
            4. HTML エンティティをデコード (Mermaid syntax compat)。
            5. 先頭キーワードが mermaid の図種でなければ空文字。
        """
        if not raw_diagram or not raw_diagram.strip():
            return ""
        # 1. Length cap (DoS / v-html flooding guard, SEC-2)
        if len(raw_diagram) > MAX_DIAGRAM_CHARS:
            return ""

        d = raw_diagram.strip()
        # HTMLタグ系の改行をLFに置換
        d = re.sub(r'<br\s*/?\s*>', '\n', d, flags=re.IGNORECASE)
        # 完全なタグを除去
        d = re.sub(r'<[^>]+>', '', d)
        # 閉じ ``>`` 無しの危険な opener (例: `<scripthello`) も剝がす。
        # 旧実装は `<[^>]+>` だけだったため `<` で始まり `>` で閉じない
        # 文字列をすり抜けていた (SEC-2 bypass surface)。
        d = re.sub(
            r'<\s*(script|iframe|object|embed|svg|foreignObject|img|video|audio|source|link|style|meta|base|form|input|button|frame|frameset)\b[^>]*',
            '',
            d,
            flags=re.IGNORECASE,
        )
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
