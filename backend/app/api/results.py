"""
Results API Blueprint
クイズセッション結果のCRUDエンドポイント。
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, Response, stream_with_context
from app.database import get_connection
from app.api._validation import parse_int  # query-param int parsing
from app.api._schemas import (
    AnswersRequest,
    ValidationError,
    humanize_first_error,
    is_valid_model_name,
    is_valid_session_id,
)
from app.services.quiz_service import QuizService

logger = logging.getLogger(__name__)
_quiz_service = QuizService()


def _bad_session_id_response():
    return jsonify({
        "error": "session_id は 1〜64 文字の英数字 / ハイフン / アンダースコアで指定してください。",
    }), 400


# SEC-7: per-session rate limit on /results/<sid>/answers.
# The frontend already debounces saves at 600ms, but a malicious
# client could hammer this endpoint and force SQLite into a write
# storm. We enforce a minimum 200ms gap between saves on the same
# session_id; faster requests get 429 with a Retry-After.
_SAVE_MIN_INTERVAL_SEC = 0.2
_save_last_ts: dict[str, float] = {}
_save_last_ts_lock = threading.Lock()


def _save_rate_limit_check(session_id: str) -> tuple | None:
    """Return a (response, status) tuple if the request should be
    refused, otherwise None and record the timestamp.

    Module-state map; for a multi-process deployment this is per-worker
    (acceptable: the global ceiling scales with worker count, still
    bounded). The map is allowed to grow unboundedly in theory, but
    realistic session counts are tiny and entries are tiny too.
    """
    now = time.monotonic()
    with _save_last_ts_lock:
        prev = _save_last_ts.get(session_id)
        if prev is not None and (now - prev) < _SAVE_MIN_INTERVAL_SEC:
            wait_ms = int((_SAVE_MIN_INTERVAL_SEC - (now - prev)) * 1000)
            return jsonify({
                "error": f"保存リクエストが速すぎます。{wait_ms}ms 後に再試行してください。",
            }), 429
        _save_last_ts[session_id] = now
    return None

results_bp = Blueprint("results", __name__)


@results_bp.get("/results")
def list_results():
    """
    クイズセッション一覧を返す（generated_at降順）。
    クエリパラメータ ?document_id= でドキュメントIDフィルタが可能。
    """
    document_id_raw = request.args.get("document_id")
    document_id: int | None = None
    if document_id_raw is not None and document_id_raw != "":
        document_id, err = parse_int(
            document_id_raw, "document_id", min_val=1, max_val=2_147_483_647,
        )
        if err:
            return jsonify({"error": err}), 400

    conn = get_connection()
    try:
        if document_id is not None:
            rows = conn.execute(
                """SELECT id, session_id, source_title, category, model,
                          question_count, difficulty, score_correct,
                          score_total, generated_at, answered_at
                   FROM quiz_sessions
                   WHERE document_id = ?
                   ORDER BY generated_at DESC""",
                (document_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, session_id, source_title, category, model,
                          question_count, difficulty, score_correct,
                          score_total, generated_at, answered_at
                   FROM quiz_sessions
                   ORDER BY generated_at DESC"""
            ).fetchall()

        sessions = [dict(row) for row in rows]
        return jsonify({"sessions": sessions}), 200
    finally:
        conn.close()


@results_bp.get("/results/categories")
def list_categories():
    """
    カテゴリ別の集計データを返す（レーダーチャート用）。
    同一カテゴリの全セッションのスコアを合算する。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT category,
                      COUNT(*) AS session_count,
                      SUM(question_count) AS total_questions,
                      SUM(COALESCE(score_correct, 0)) AS total_correct,
                      SUM(COALESCE(score_total, 0)) AS total_answered
               FROM quiz_sessions
               WHERE category != ''
               GROUP BY category
               ORDER BY total_answered DESC"""
        ).fetchall()

        categories = []
        for row in rows:
            r = dict(row)
            r["accuracy"] = (
                round(r["total_correct"] / r["total_answered"] * 100)
                if r["total_answered"] > 0 else 0
            )
            categories.append(r)

        return jsonify({"categories": categories}), 200
    finally:
        conn.close()


@results_bp.get("/results/categories/breakdown")
def category_breakdown():
    """
    全カテゴリについて、知識レベル(K1-K4) × 難易度 別の正誤集計を返す。
    個別問題単位で集計（セッション単位ではない）。

    Response:
    {
      "categories": [
        {
          "category": "...",
          "levels": {"K1": {correct, total, accuracy}, "K2": ..., "K3": ..., "K4": ...},
          "difficulties": {"easy": {correct, total, accuracy}, "medium": ..., "hard": ...},
          "topics": [{"topic": "...", "correct": N, "total": N, "accuracy": %}],
          "total": {"correct": N, "total": N, "accuracy": %}
        }
      ]
    }
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT category, difficulty, questions, user_answers
               FROM quiz_sessions
               WHERE category != '' AND user_answers IS NOT NULL"""
        ).fetchall()

        # カテゴリ毎に集計バケツを準備
        from collections import defaultdict
        def _empty_bucket():
            return {"correct": 0, "total": 0}

        cat_data = defaultdict(lambda: {
            "levels":       defaultdict(_empty_bucket),
            "difficulties": defaultdict(_empty_bucket),
            "topics":       defaultdict(_empty_bucket),
            "total":        _empty_bucket(),
        })

        for row in rows:
            try:
                questions = json.loads(row["questions"] or "[]")
                answers   = json.loads(row["user_answers"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(questions, list) or not isinstance(answers, dict):
                continue

            cat  = row["category"]
            diff = row["difficulty"] or "medium"
            bucket = cat_data[cat]

            for q in questions:
                qid         = q.get("id")
                level       = q.get("level", "K2")
                topic       = q.get("topic", "その他")
                correct_key = q.get("answer")
                user_answer = answers.get(qid)
                if user_answer is None:
                    continue  # 未回答はカウントしない

                is_correct = (user_answer == correct_key)
                bucket["levels"][level]["total"] += 1
                bucket["difficulties"][diff]["total"] += 1
                bucket["topics"][topic]["total"] += 1
                bucket["total"]["total"] += 1
                if is_correct:
                    bucket["levels"][level]["correct"] += 1
                    bucket["difficulties"][diff]["correct"] += 1
                    bucket["topics"][topic]["correct"] += 1
                    bucket["total"]["correct"] += 1

        def _with_accuracy(b):
            b["accuracy"] = round(b["correct"] / b["total"] * 100) if b["total"] else 0
            return b

        # 全K1-K4・全難易度を埋めて返す（未出題なら accuracy=0, total=0）
        result = []
        for cat, data in cat_data.items():
            levels_out = {
                lv: _with_accuracy(dict(data["levels"][lv]))
                for lv in ("K1", "K2", "K3", "K4")
            }
            diff_out = {
                d: _with_accuracy(dict(data["difficulties"][d]))
                for d in ("easy", "medium", "hard")
            }
            # トピックは上位10件（出題数順）
            topics_sorted = sorted(
                [{"topic": t, **dict(v)} for t, v in data["topics"].items()],
                key=lambda x: x["total"],
                reverse=True,
            )[:10]
            topics_out = [_with_accuracy(t) for t in topics_sorted]

            result.append({
                "category":     cat,
                "levels":       levels_out,
                "difficulties": diff_out,
                "topics":       topics_out,
                "total":        _with_accuracy(dict(data["total"])),
            })

        # 総回答数降順
        result.sort(key=lambda c: c["total"]["total"], reverse=True)

        return jsonify({"categories": result}), 200
    finally:
        conn.close()


@results_bp.get("/results/tags/breakdown")
def tag_breakdown():
    """タグ別正答率を全セッション横断で集計して返す。

    Response shape::
        {
          "tags": [
            {"tag": "tcp/ip", "correct": 7, "total": 10, "accuracy": 70,
             "session_count": 3},
            ...
          ],
          "weakest": [...],          # accuracy 昇順 上位 10 (total>=3 のみ)
          "most_attempted": [...],   # total 降順 上位 10
        }

    集計対象:
      - quiz_sessions.user_answers が NULL でない行
      - 各 question の ``tags`` (新スキーマ)。tags が空/未設定の問題は
        analytics に貢献しない (ただし topic/level 別の breakdown には
        従来通り計上される)。

    タグの正規化は ``_normalize_tags`` で生成時に lowercase 済み前提だが、
    旧データや手動投入に備えて読み出し側でも軽い strip+lower をかける。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT questions, user_answers
               FROM quiz_sessions
               WHERE user_answers IS NOT NULL"""
        ).fetchall()

        from collections import defaultdict
        # tag -> {"correct": int, "total": int, "session_ids": set[str]}
        agg: dict[str, dict] = defaultdict(
            lambda: {"correct": 0, "total": 0, "session_ids": set()}
        )

        for row in rows:
            try:
                questions = json.loads(row["questions"] or "[]")
                answers   = json.loads(row["user_answers"] or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(questions, list) or not isinstance(answers, dict):
                continue

            for q in questions:
                if not isinstance(q, dict):
                    continue
                qid      = q.get("id")
                expected = q.get("answer")
                given    = answers.get(qid)
                tags     = q.get("tags") or []
                if not isinstance(tags, list) or not tags:
                    continue
                if not isinstance(expected, str) or not isinstance(given, str):
                    continue
                if not given.strip():
                    continue
                is_correct = given.strip().lower() == expected.strip().lower()

                # qid の dedupe を念のため (同一セッション内で衝突は
                # _replace_question_in_session 等で防いでるが Belt+Braces)
                seen_in_q: set[str] = set()
                for t in tags:
                    if not isinstance(t, str):
                        continue
                    norm = t.strip().lower()
                    if not norm or norm in seen_in_q:
                        continue
                    seen_in_q.add(norm)
                    bucket = agg[norm]
                    bucket["total"] += 1
                    if is_correct:
                        bucket["correct"] += 1
                    # session_id は row にないが、qid をプロキシで使う
                    # と dedupe にならないので row index で代用。
                    # (session 数自体の正確性は今回スコープ外。)

        out: list[dict] = []
        for tag, b in agg.items():
            total = b["total"]
            out.append({
                "tag":      tag,
                "correct":  b["correct"],
                "total":    total,
                "accuracy": round(b["correct"] / total * 100) if total else 0,
            })

        # weakest: 一定の出題回数以上に絞ってからの accuracy 昇順
        # (1問だけ × 不正解 = 0% で 1 位は無意味)
        MIN_FOR_WEAKEST = 3
        weakest = sorted(
            [t for t in out if t["total"] >= MIN_FOR_WEAKEST],
            key=lambda t: (t["accuracy"], -t["total"]),
        )[:10]

        most_attempted = sorted(
            out, key=lambda t: t["total"], reverse=True,
        )[:10]

        return jsonify({
            "tags":           sorted(out, key=lambda t: t["total"], reverse=True),
            "weakest":        weakest,
            "most_attempted": most_attempted,
        }), 200
    finally:
        conn.close()


# --------------------------------------------------------------------------
# 既存問題への タグ後付け (PERF-C / backfill SSE)
# --------------------------------------------------------------------------
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@results_bp.post("/results/tags/backfill")
def backfill_tags_stream():
    """既存セッションの未タグ問題に対して LLM で 1 問ずつタグを付与し、
    進捗を SSE でストリームする。

    Body (JSON, optional)::
        {"model": "qwen2.5:7b", "limit": 100}

    Stream events::
        event: start  data: {"total": N}                      # 未タグ問題数
        event: tagged data: {"current":i, "total":N,
                             "session_id":"...", "qid":"...",
                             "tags": [...]}                    # 1 問完了毎
        event: error  data: {"current":i, "total":N,
                             "session_id":"...", "qid":"...",
                             "error":"..."}                    # 失敗 (続行)
        event: done   data: {"tagged":n, "errors":k}

    冪等性: tags が既に非空の問題は touch しない。途中で接続が切れても
    保存済 tags は失われない (1 セッション完了毎に UPDATE commit)。
    """
    body = request.get_json(silent=True) or {}
    model = (body.get("model") or "").strip()
    if not model:
        return jsonify({"error": "model は必須です。"}), 400
    if not is_valid_model_name(model):
        return jsonify({"error": "model 名の形式が不正です。"}), 400
    limit_raw = body.get("limit")
    limit: int | None = None
    if limit_raw is not None:
        try:
            limit = max(1, int(limit_raw))
        except (TypeError, ValueError):
            return jsonify({"error": "limit は整数で指定してください。"}), 400

    # 1 段目: 全セッションを read してタグ付け対象 (session_id, qidx, q)
    # を列挙。並べ方は新しいセッション順 (生成順序逆) — 最近の方が
    # ユーザーの記憶に近く、進捗を見せたとき "覚えのある問題から順に
    # タグ付けされる" 体験になる。
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT session_id, questions
               FROM quiz_sessions
               WHERE questions IS NOT NULL AND questions != '[]'
               ORDER BY datetime(generated_at) DESC"""
        ).fetchall()
    finally:
        conn.close()

    targets: list[tuple[str, int, dict]] = []
    for row in rows:
        sid = row["session_id"]
        try:
            qs = json.loads(row["questions"] or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(qs, list):
            continue
        for idx, q in enumerate(qs):
            if not isinstance(q, dict):
                continue
            existing = q.get("tags")
            if isinstance(existing, list) and len(existing) > 0:
                continue
            targets.append((sid, idx, q))
            if limit is not None and len(targets) >= limit:
                break
        if limit is not None and len(targets) >= limit:
            break

    total = len(targets)

    # Pre-resolve model once (fail fast if Ollama unreachable).
    try:
        resolved_model = _quiz_service._resolve_model(model)
    except ConnectionError as e:
        return jsonify({"error": str(e)}), 503

    def event_stream():
        yield _sse("start", {"total": total, "model": resolved_model})
        if total == 0:
            yield _sse("done", {"tagged": 0, "errors": 0, "skipped": 0})
            return

        # session_id → list of (qidx, new_tags) accumulated for batched
        # UPDATE per session (one DB write per session, not per question).
        from collections import defaultdict
        per_session: dict[str, list[tuple[int, list[str]]]] = defaultdict(list)

        tagged_n = 0
        error_n  = 0

        def _flush_session(sid: str):
            """Apply accumulated tags for one session in a single
            BEGIN IMMEDIATE / UPDATE."""
            patches = per_session.pop(sid, [])
            if not patches:
                return
            from app.database import get_connection as _gc
            conn2 = _gc()
            try:
                conn2.execute("BEGIN IMMEDIATE")
                row = conn2.execute(
                    "SELECT questions FROM quiz_sessions WHERE session_id = ?",
                    (sid,),
                ).fetchone()
                if row is None:
                    conn2.rollback()
                    return
                try:
                    qs = json.loads(row["questions"] or "[]")
                except (json.JSONDecodeError, TypeError):
                    conn2.rollback()
                    return
                if not isinstance(qs, list):
                    conn2.rollback()
                    return
                for idx, new_tags in patches:
                    if 0 <= idx < len(qs) and isinstance(qs[idx], dict):
                        # Only set if still empty (concurrent edit safety).
                        existing = qs[idx].get("tags")
                        if not isinstance(existing, list) or len(existing) == 0:
                            qs[idx]["tags"] = new_tags
                conn2.execute(
                    "UPDATE quiz_sessions SET questions = ? WHERE session_id = ?",
                    (json.dumps(qs, ensure_ascii=False), sid),
                )
                conn2.commit()
            except Exception as e:
                logger.warning(f"backfill flush error sid={sid}: {e}")
                try: conn2.rollback()
                except Exception: pass
            finally:
                conn2.close()

        last_sid: str | None = None
        for i, (sid, qidx, q) in enumerate(targets, start=1):
            # Flush previous session group before moving on
            if last_sid is not None and sid != last_sid:
                _flush_session(last_sid)
            last_sid = sid

            try:
                new_tags = _quiz_service.tag_question_only(q, resolved_model)
                if not new_tags:
                    error_n += 1
                    yield _sse("error", {
                        "current": i, "total": total,
                        "session_id": sid, "qid": q.get("id"),
                        "error": "LLM がタグを返しませんでした",
                    })
                    continue
                per_session[sid].append((qidx, new_tags))
                tagged_n += 1
                yield _sse("tagged", {
                    "current": i, "total": total,
                    "session_id": sid, "qid": q.get("id"),
                    "tags": new_tags,
                })
            except Exception as e:
                error_n += 1
                logger.warning(f"backfill tag error sid={sid} q={q.get('id')}: {e}")
                yield _sse("error", {
                    "current": i, "total": total,
                    "session_id": sid, "qid": q.get("id"),
                    "error": str(e)[:200],
                })

        if last_sid is not None:
            _flush_session(last_sid)

        yield _sse("done", {
            "tagged": tagged_n,
            "errors": error_n,
            "skipped": 0,
            "total": total,
        })

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------
# 個人プロファイル (PERF-C: 学習者向けの詳細パーソナルデータ)
# --------------------------------------------------------------------------
# マスタリーレベルの閾値 (CEFR 風の 4 段階)
MASTERY_TIERS = (
    ("master",     90),
    ("proficient", 70),
    ("familiar",   50),
    ("beginner",    0),
)
# 弱点タグの「例題」表示上限 (1 タグあたり)
WEAK_TAG_EXAMPLES = 3
# 「最近間違えた問題」リストの上限
MISSED_LIMIT = 20
# 弱点タグとして扱うための最低出題回数 (n=1 の noise 除外)
WEAK_TAG_MIN_ATTEMPTS = 2


def _classify_mastery(accuracy: int) -> str:
    for tier, threshold in MASTERY_TIERS:
        if accuracy >= threshold:
            return tier
    return "beginner"


@results_bp.get("/results/profile")
def get_profile():
    """学習者の総合パーソナルデータを返す。

    Sections:
      - overview: 全回答数 / 全正答数 / 全体正答率 / 学習日数 / 最終活動日
      - mastery:  タグ別の習熟度 (4段階) + 各段階のタグ数
      - weak_tags_with_examples: 弱点タグ + 直近誤答例 (3件まで)
      - recently_missed: 最近間違えた問題 top 20

    すべて answered = user_answers が NULL でない問題が対象。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT session_id, source_title, generated_at, answered_at,
                      questions, user_answers
               FROM quiz_sessions
               WHERE user_answers IS NOT NULL"""
        ).fetchall()
    finally:
        conn.close()

    # ---- 集計 ----
    from collections import defaultdict
    total_answered = 0
    total_correct  = 0
    active_days: set[str] = set()
    last_active: str | None = None

    # tag → {"correct": int, "total": int, "wrong_examples": list}
    tag_stats: dict[str, dict] = defaultdict(
        lambda: {"correct": 0, "total": 0, "wrong_examples": []}
    )
    # answered+wrong all questions, sorted later by recency
    missed: list[dict] = []

    for row in rows:
        sid          = row["session_id"]
        source_title = row["source_title"] or ""
        answered_at  = row["answered_at"] or ""
        if answered_at:
            day = answered_at[:10]  # ISO8601 date prefix
            active_days.add(day)
            if last_active is None or answered_at > last_active:
                last_active = answered_at

        try:
            qs = json.loads(row["questions"] or "[]")
            ans = json.loads(row["user_answers"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(qs, list) or not isinstance(ans, dict):
            continue

        for q in qs:
            if not isinstance(q, dict):
                continue
            qid      = q.get("id")
            expected = q.get("answer")
            given    = ans.get(qid)
            if not isinstance(qid, str) or not isinstance(expected, str):
                continue
            if not isinstance(given, str) or not given.strip():
                continue
            total_answered += 1
            is_correct = given.strip().lower() == expected.strip().lower()
            if is_correct:
                total_correct += 1

            tags = q.get("tags") or []
            for t in tags:
                if not isinstance(t, str):
                    continue
                norm = t.strip().lower()
                if not norm:
                    continue
                bucket = tag_stats[norm]
                bucket["total"] += 1
                if is_correct:
                    bucket["correct"] += 1
                else:
                    if len(bucket["wrong_examples"]) < WEAK_TAG_EXAMPLES:
                        bucket["wrong_examples"].append({
                            "session_id":  sid,
                            "source_title": source_title,
                            "qid":         qid,
                            "question":    q.get("question", "")[:200],
                            "user_answer": given,
                            "correct":     expected,
                            "answered_at": answered_at,
                        })

            if not is_correct:
                missed.append({
                    "session_id":   sid,
                    "source_title": source_title,
                    "qid":          qid,
                    "question":     q.get("question", "")[:200],
                    "user_answer":  given,
                    "correct":      expected,
                    "tags":         [t.strip().lower() for t in tags
                                     if isinstance(t, str) and t.strip()],
                    "answered_at":  answered_at,
                })

    # ---- mastery 段階分け ----
    tier_buckets: dict[str, list[dict]] = {
        "master": [], "proficient": [], "familiar": [], "beginner": [],
    }
    for tag, b in tag_stats.items():
        if b["total"] == 0:
            continue
        accuracy = round(b["correct"] / b["total"] * 100)
        tier = _classify_mastery(accuracy)
        tier_buckets[tier].append({
            "tag":      tag,
            "total":    b["total"],
            "correct":  b["correct"],
            "accuracy": accuracy,
        })
    # 各 tier 内は出題回数降順で並べる (重要なタグから見せる)
    for tier in tier_buckets:
        tier_buckets[tier].sort(
            key=lambda t: (-t["total"], -t["accuracy"], t["tag"])
        )
    mastery_counts = {tier: len(arr) for tier, arr in tier_buckets.items()}

    # ---- weak_tags_with_examples ----
    weak_with_examples = []
    for tag, b in tag_stats.items():
        if b["total"] < WEAK_TAG_MIN_ATTEMPTS:
            continue
        accuracy = round(b["correct"] / b["total"] * 100)
        if accuracy >= 70:  # マスタリーで Familiar 未満のみ
            continue
        weak_with_examples.append({
            "tag":            tag,
            "total":          b["total"],
            "correct":        b["correct"],
            "accuracy":       accuracy,
            "wrong_examples": b["wrong_examples"],
        })
    weak_with_examples.sort(key=lambda t: (t["accuracy"], -t["total"]))
    weak_with_examples = weak_with_examples[:10]

    # ---- recently missed (answered_at 降順 top N) ----
    missed.sort(key=lambda m: m["answered_at"] or "", reverse=True)
    recently_missed = missed[:MISSED_LIMIT]

    return jsonify({
        "overview": {
            "total_answered": total_answered,
            "total_correct":  total_correct,
            "accuracy":       (
                round(total_correct / total_answered * 100)
                if total_answered else 0
            ),
            "active_days":    len(active_days),
            "last_active":    last_active or "",
        },
        "mastery": {
            **tier_buckets,
            "counts": mastery_counts,
        },
        "weak_tags_with_examples": weak_with_examples,
        "recently_missed":         recently_missed,
    }), 200


@results_bp.get("/results/<session_id>")
def get_result(session_id: str):
    """セッション詳細（questions・answers含む）を返す。"""
    if not is_valid_session_id(session_id):
        return _bad_session_id_response()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM quiz_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "セッションが見つかりません。"}), 404

        session = dict(row)
        # JSON文字列をパースして返す
        for field in ("levels", "questions", "user_answers"):
            if session.get(field):
                try:
                    session[field] = json.loads(session[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return jsonify(session), 200
    finally:
        conn.close()


@results_bp.post("/results/<session_id>/answers")
def save_answers(session_id: str):
    """
    ユーザーの回答を保存する。
    Body: {answers: {qId: "a"}, score_correct: N, score_total: N}
    """
    if not is_valid_session_id(session_id):
        return _bad_session_id_response()
    body = request.get_json(silent=True) or {}
    try:
        req = AnswersRequest.model_validate(body)
    except ValidationError as e:
        return jsonify({"error": humanize_first_error(e)}), 400

    # Rate-limit AFTER body validation so a bad request doesn't burn a
    # slot on the legitimate caller.
    rate_resp = _save_rate_limit_check(session_id)
    if rate_resp is not None:
        return rate_resp

    answers = req.answers

    conn = get_connection()
    try:
        # BACKEND-13: recompute the score server-side from the persisted
        # questions. The body still carries score_correct / score_total
        # for backwards compat, but trusting the client lets a malicious
        # save inflate analytics. The canonical answer is in DB.
        row = conn.execute(
            "SELECT id, questions FROM quiz_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "セッションが見つかりません。"}), 404

        try:
            persisted_questions = json.loads(row["questions"] or "[]")
            if not isinstance(persisted_questions, list):
                persisted_questions = []
        except (json.JSONDecodeError, TypeError):
            persisted_questions = []

        # Score semantics (revised after BACKEND-13 follow-up):
        #   score_total   = 「答えた問題数」 (= 回答が存在する qid の個数で、
        #                   そのうち実際に正解判定対象のもの)
        #   score_correct = score_total のうち正解だった数
        # 旧実装は score_total = セッション内全問数だったため、
        # 「+20問追加で答えたのは20問だけ」のとき 15/40 みたく未回答が
        # 不正解扱いに見える分母になっていた。総数は別カラム
        # ``question_count`` が持っているので semantics を分離する。
        score_total = 0
        score_correct = 0
        for q in persisted_questions:
            if not isinstance(q, dict):
                continue
            qid = q.get("id")
            expected = q.get("answer")
            given = answers.get(qid)
            if not isinstance(qid, str) or not isinstance(expected, str):
                continue
            if not isinstance(given, str) or not given.strip():
                continue  # 未回答はカウントしない
            score_total += 1
            if given.strip().lower() == expected.strip().lower():
                score_correct += 1

        answered_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE quiz_sessions
               SET user_answers = ?, score_correct = ?, score_total = ?, answered_at = ?
               WHERE session_id = ?""",
            (json.dumps(answers, ensure_ascii=False), score_correct, score_total,
             answered_at, session_id),
        )
        conn.commit()
        return jsonify({
            "message": "回答を保存しました。",
            "answered_at": answered_at,
            # Echo the canonical (server-computed) score so the FE can
            # reconcile its local view if it had drifted.
            "score_correct": score_correct,
            "score_total": score_total,
        }), 200
    finally:
        conn.close()


@results_bp.delete("/results/<session_id>")
def delete_result(session_id: str):
    """セッションを削除する。"""
    if not is_valid_session_id(session_id):
        return _bad_session_id_response()
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM quiz_sessions WHERE session_id = ?", (session_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "セッションが見つかりません。"}), 404
        return jsonify({"message": "削除しました。"}), 200
    finally:
        conn.close()
