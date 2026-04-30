"""
Results API Blueprint
クイズセッション結果のCRUDエンドポイント。
"""
import json
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from app.database import get_connection
from app.api._validation import parse_int  # query-param int parsing
from app.api._schemas import (
    AnswersRequest,
    ValidationError,
    humanize_first_error,
    is_valid_session_id,
)


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
