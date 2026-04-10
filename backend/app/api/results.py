"""
Results API Blueprint
クイズセッション結果のCRUDエンドポイント。
"""
import json
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from app.database import get_connection

results_bp = Blueprint("results", __name__)


@results_bp.get("/results")
def list_results():
    """
    クイズセッション一覧を返す（generated_at降順）。
    クエリパラメータ ?document_id= でドキュメントIDフィルタが可能。
    """
    document_id = request.args.get("document_id")
    conn = get_connection()
    try:
        if document_id:
            rows = conn.execute(
                """SELECT id, session_id, source_title, category, model,
                          question_count, difficulty, score_correct,
                          score_total, generated_at, answered_at
                   FROM quiz_sessions
                   WHERE document_id = ?
                   ORDER BY generated_at DESC""",
                (int(document_id),),
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
    answers       = body.get("answers", {})
    score_correct = body.get("score_correct")
    score_total   = body.get("score_total")

    if not answers:
        return jsonify({"error": "answers は必須です。"}), 400

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
