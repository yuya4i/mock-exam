"""
Results API Blueprint
クイズセッション結果のCRUDエンドポイント。
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from app.database import get_connection
from app.api._validation import parse_int

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


@results_bp.get("/results/<session_id>")
def get_result(session_id: str):
    """セッション詳細（questions・answers含む）を返す。"""
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
    body = request.get_json(silent=True) or {}
    answers = body.get("answers", {})
    if not isinstance(answers, dict) or not answers:
        return jsonify({"error": "answers は非空の辞書で指定してください。"}), 400

    # score_correct / score_total are optional, but if present they must be
    # non-negative integers. Reject non-numeric / negative values with 400
    # so the DB never ingests something that later breaks aggregation.
    score_correct, err = parse_int(
        body.get("score_correct"), "score_correct",
        default=0, min_val=0, max_val=1_000_000,
    )
    if err:
        return jsonify({"error": err}), 400
    score_total, err = parse_int(
        body.get("score_total"), "score_total",
        default=0, min_val=0, max_val=1_000_000,
    )
    if err:
        return jsonify({"error": err}), 400

    conn = get_connection()
    try:
        # セッション存在チェック
        row = conn.execute(
            "SELECT id FROM quiz_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "セッションが見つかりません。"}), 404

        answered_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """UPDATE quiz_sessions
               SET user_answers = ?, score_correct = ?, score_total = ?, answered_at = ?
               WHERE session_id = ?""",
            (json.dumps(answers, ensure_ascii=False), score_correct, score_total,
             answered_at, session_id),
        )
        conn.commit()
        return jsonify({"message": "回答を保存しました。", "answered_at": answered_at}), 200
    finally:
        conn.close()


@results_bp.delete("/results/<session_id>")
def delete_result(session_id: str):
    """セッションを削除する。"""
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
