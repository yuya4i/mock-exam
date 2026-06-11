#!/usr/bin/env python3
"""Seed quiz_sessions with consistent demo analytics, split by exam type.

Produces >=300 answered questions across 5 certification "exam types"
(JSTQB FL / JSTQB AL / IPA 基本情報 / IPA 応用情報 / IPA 情報処理安全確保
支援士). Each (exam_type, category) becomes one session. Correctness is
assigned per question by a level-based probability scaled to a per-exam-
type target accuracy, then globally nudged so the OVERALL lands ~73% —
and because user_answers are derived from that assignment, every
analytics endpoint (stored-column AND recompute) agrees.

The exam_type dimension lets the analytics tab filter / summarize by
certification family.

Run:  python3 scripts/seed_demo_analytics.py --yes
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys

random.seed(42)

TARGET_ACCURACY = 0.73
VARIANTS_PER_TOPIC = 4   # 91 topics * 4 = 364 questions (>=300)

# level adjustment around the exam-type target (K3/K4 only — K1/K2 are
# forced correct, see ALWAYS_CORRECT_LEVELS)
LEVEL_ADJ = {"K1": 0.12, "K2": 0.04, "K3": -0.06, "K4": -0.14}

# 初級レベルは「明らかに解ける」ので必ず正解にする (ユーザー指定)。
# 中級以上(K3/K4)だけ実力に応じてランダム。
ALWAYS_CORRECT_LEVELS = {"K1", "K2"}

STEMS = [
    "{t}に関する説明として最も適切なものはどれか。",
    "{t}について正しい記述はどれか。",
    "{t}の理解を問う。最も適切な選択肢はどれか。",
    "{t}に関して誤っているものを選んだうえで正しい対処はどれか。",
]

# exam_type -> dict(category -> list of (topic, level, [tags]))
EXAMS = {
    "JSTQB FL": {
        "_model": "qwen3.6-27b-abliterated", "_diff": "easy", "_target": 0.82,
        "_day": "2026-05-20",
        "テストの基礎": [
            ("テストの7原則", "K1", ["テスト原則"]),
            ("テストプロセス", "K2", ["テストプロセス"]),
            ("テストの心理学", "K1", ["テスト心理学"]),
            ("エラー・欠陥・故障", "K1", ["欠陥", "用語"]),
        ],
        "テスト技法": [
            ("同値分割法", "K2", ["同値分割", "ブラックボックス"]),
            ("境界値分析", "K3", ["境界値分析", "ブラックボックス"]),
            ("デシジョンテーブルテスト", "K3", ["デシジョンテーブル", "ブラックボックス"]),
            ("状態遷移テスト", "K3", ["状態遷移", "ブラックボックス"]),
            ("ユースケーステスト", "K2", ["ユースケース", "ブラックボックス"]),
            ("制御フローテスト", "K4", ["ホワイトボックス", "カバレッジ"]),
            ("経験ベースの技法", "K2", ["経験ベース", "探索的テスト"]),
        ],
        "テストマネジメント": [
            ("テスト計画", "K2", ["テスト計画", "マネジメント"]),
            ("リスクベーステスト", "K3", ["リスク", "マネジメント"]),
            ("欠陥マネジメント", "K2", ["欠陥", "マネジメント"]),
            ("テスト見積り", "K3", ["見積り", "マネジメント"]),
        ],
        "静的テスト": [
            ("レビューの種類", "K2", ["レビュー", "静的テスト"]),
            ("静的解析", "K2", ["静的解析", "静的テスト"]),
        ],
        "テストツール": [
            ("テスト自動化", "K2", ["自動化", "ツール"]),
            ("ツール導入のリスク", "K3", ["自動化", "ツール", "リスク"]),
        ],
    },
    "JSTQB AL": {
        "_model": "qwen3.6-35b-claude4.7-thinking", "_diff": "hard", "_target": 0.68,
        "_day": "2026-05-27",
        "テストプロセス": [
            ("テスト分析と設計", "K3", ["テストプロセス"]),
            ("テスト実装と実行", "K3", ["テストプロセス"]),
            ("テスト完了基準", "K4", ["テスト完了基準"]),
        ],
        "テストマネジメント応用": [
            ("テスト戦略", "K4", ["テスト戦略", "マネジメント"]),
            ("テスト進捗の監視と制御", "K3", ["メトリクス", "マネジメント"]),
            ("テスト見積り技法", "K4", ["見積り", "マネジメント"]),
        ],
        "レビュー": [
            ("形式的レビュー", "K3", ["レビュー"]),
            ("レビュー指標", "K4", ["レビュー", "メトリクス"]),
        ],
        "欠陥マネジメント": [
            ("欠陥ライフサイクル", "K3", ["欠陥"]),
            ("根本原因分析", "K4", ["欠陥", "根本原因分析"]),
        ],
        "テスト自動化": [
            ("自動化アーキテクチャ", "K4", ["自動化", "アーキテクチャ"]),
            ("自動化のROI", "K4", ["自動化", "roi"]),
        ],
    },
    "IPA 基本情報": {
        "_model": "gemma4-12b-qat-uncensored", "_diff": "medium", "_target": 0.79,
        "_day": "2026-06-01",
        "基礎理論": [
            ("基数変換", "K2", ["基数変換", "基礎理論"]),
            ("論理演算", "K2", ["論理演算", "基礎理論"]),
            ("補数表現", "K3", ["補数", "基礎理論"]),
            ("確率と統計", "K2", ["確率", "基礎理論"]),
        ],
        "アルゴリズム": [
            ("データ構造", "K2", ["データ構造"]),
            ("整列アルゴリズム", "K3", ["ソート", "アルゴリズム"]),
            ("探索アルゴリズム", "K3", ["探索", "アルゴリズム"]),
            ("計算量", "K3", ["計算量", "アルゴリズム"]),
        ],
        "コンピュータシステム": [
            ("CPUアーキテクチャ", "K2", ["cpu", "ハードウェア"]),
            ("記憶階層", "K2", ["メモリ", "ハードウェア"]),
            ("OSの役割", "K2", ["os"]),
        ],
        "データベース": [
            ("関係モデル", "K2", ["関係モデル", "db"]),
            ("正規化", "K3", ["正規化", "db"]),
            ("SQL基礎", "K2", ["sql", "db"]),
            ("トランザクション", "K3", ["トランザクション", "db"]),
        ],
        "ネットワーク": [
            ("OSIとTCP/IP", "K2", ["tcp/ip", "network"]),
            ("サブネット計算", "K3", ["サブネット", "network"]),
            ("DNSとDHCP", "K2", ["dns", "network"]),
        ],
        "セキュリティ": [
            ("暗号方式", "K2", ["暗号", "security"]),
            ("認証技術", "K3", ["認証", "security"]),
            ("マルウェア対策", "K2", ["マルウェア", "security"]),
        ],
    },
    "IPA 応用情報": {
        "_model": "qwen3.6-35b-a3b-uncensored-hauhaucs-aggressive-q4_k_m",
        "_diff": "hard", "_target": 0.68, "_day": "2026-06-06",
        "システムアーキテクチャ": [
            ("冗長構成と可用性", "K3", ["可用性", "アーキテクチャ"]),
            ("性能設計", "K4", ["性能", "アーキテクチャ"]),
            ("仮想化技術", "K3", ["仮想化", "アーキテクチャ"]),
        ],
        "データベース応用": [
            ("インデックス設計", "K4", ["インデックス", "db"]),
            ("トランザクション分離", "K4", ["トランザクション", "db"]),
            ("分散データベース", "K4", ["分散", "db"]),
        ],
        "ネットワーク応用": [
            ("ルーティングプロトコル", "K4", ["ルーティング", "network"]),
            ("負荷分散", "K3", ["負荷分散", "network"]),
            ("QoS", "K4", ["qos", "network"]),
        ],
        "セキュリティ応用": [
            ("公開鍵基盤(PKI)", "K3", ["pki", "security"]),
            ("セキュアプロトコル", "K3", ["tls", "security"]),
            ("リスクアセスメント", "K4", ["リスク", "security"]),
        ],
        "プロジェクトマネジメント": [
            ("WBS", "K2", ["pm"]),
            ("アローダイアグラム", "K3", ["pm", "スケジュール"]),
            ("EVM", "K4", ["pm", "evm"]),
        ],
        "アルゴリズム応用": [
            ("動的計画法", "K4", ["アルゴリズム", "動的計画法"]),
            ("グラフアルゴリズム", "K4", ["アルゴリズム", "グラフ"]),
        ],
    },
    "IPA 情報処理安全確保支援士": {
        "_model": "qwen3.6-35b-aggressive", "_diff": "hard", "_target": 0.63,
        "_day": "2026-06-09",
        "暗号と認証": [
            ("公開鍵基盤(PKI)", "K3", ["pki", "暗号"]),
            ("デジタル署名", "K3", ["署名", "暗号"]),
            ("鍵管理", "K4", ["鍵管理", "暗号"]),
            ("多要素認証", "K3", ["認証"]),
        ],
        "ネットワークセキュリティ": [
            ("ファイアウォール設計", "K3", ["firewall", "network"]),
            ("IDS/IPS", "K3", ["ids", "network"]),
            ("VPN", "K3", ["vpn", "network"]),
            ("DNSセキュリティ", "K4", ["dnssec", "network"]),
        ],
        "セキュア開発": [
            ("セキュアコーディング", "K3", ["セキュア開発"]),
            ("脆弱性診断", "K4", ["脆弱性診断", "セキュア開発"]),
            ("SAST/DAST", "K4", ["診断", "セキュア開発"]),
        ],
        "攻撃と対策": [
            ("標的型攻撃", "K3", ["攻撃手法"]),
            ("Webアプリ攻撃", "K4", ["攻撃手法", "web"]),
            ("権限昇格", "K4", ["攻撃手法"]),
        ],
        "インシデントと管理": [
            ("インシデント対応", "K3", ["インシデント", "管理"]),
            ("フォレンジック", "K4", ["フォレンジック", "管理"]),
            ("ISMS", "K2", ["isms", "管理"]),
            ("関連法規", "K2", ["法務", "管理"]),
        ],
    },
}


def _choices(topic: str) -> dict:
    return {
        "a": f"{topic}に関する正しい記述",
        "b": f"{topic}についてのよくある誤解(1)",
        "c": f"{topic}についてのよくある誤解(2)",
        "d": f"{topic}とは関係のない記述",
    }


def build():
    """Build all sessions with correctness assigned; return (sessions, total, correct)."""
    sessions = []
    flat = []  # (s_idx, q_idx, level)
    for exam_type, spec in EXAMS.items():
        model = spec["_model"]; diff = spec["_diff"]
        target = spec["_target"]; day = spec["_day"]
        for category, topics in spec.items():
            if category.startswith("_"):
                continue
            qs = []
            qn = 0
            for (topic, level, tags) in topics:
                for v in range(VARIANTS_PER_TOPIC):
                    qn += 1
                    # 正誤ルール (ユーザー指定):
                    #   初級レベル(K1/K2)は「明らかに解ける」→ 必ず正解。
                    #   中級以上(K3/K4)のみ実力に応じてランダム
                    #   (種別ターゲット ± レベル補正)。
                    if level in ALWAYS_CORRECT_LEVELS:
                        correct = True
                    else:
                        p = min(0.95, max(0.05, target + LEVEL_ADJ[level]))
                        correct = random.random() < p
                    # タグ: ジャンル/トピックの tag に加えて K-level を付与し、
                    # 認知レベル別のレーダー分析にも使えるようにする
                    # (JSTQB の ジャンル×K-level 詳細分析向け)。
                    qs.append({
                        "id": f"Q{qn:03d}", "level": level, "topic": topic,
                        "tags": tags + [level.lower()],
                        "question": STEMS[v % len(STEMS)].format(t=topic),
                        "choices": _choices(topic), "answer": "a",
                        "explanation": f"正解は a。{topic}({category})の基本。資料該当章を参照。",
                        "source_hint": f"{exam_type} / {category} / {topic}",
                        "_correct": correct,
                    })
                    flat.append((len(sessions), len(qs) - 1, level))
            sessions.append({
                "exam_type": exam_type, "category": category, "model": model,
                "diff": diff, "day": day,
                "title": f"{exam_type} {category} 模試", "questions": qs,
            })

    total = len(flat)
    # 正誤は上記ルール(K1/K2必正解 + K3/K4ランダム)で確定。全体tuning
    # はしない (初級必正解の指定を上書きしてしまうため)。総合正答率は
    # この分布から自然に決まる (初級が底上げするので概ね高め)。
    correct = sum(1 for s in sessions for q in s["questions"] if q["_correct"])
    return sessions, total, correct


def _ensure_exam_type_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(quiz_sessions)").fetchall()}
    if "exam_type" not in cols:
        conn.execute(
            "ALTER TABLE quiz_sessions ADD COLUMN exam_type TEXT NOT NULL DEFAULT '未分類'"
        )
        conn.commit()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "data", "quizgen.db"))
    ap.add_argument("--yes", action="store_true", help="confirm: deletes existing quiz_sessions")
    args = ap.parse_args(argv)
    if not args.yes:
        print("既存 quiz_sessions を全削除してデモ(種別付き)を投入します。--yes を付けて実行してください。")
        return 1

    sessions, total, correct = build()
    conn = sqlite3.connect(args.db)
    try:
        _ensure_exam_type_column(conn)
        conn.execute("DELETE FROM quiz_sessions")
        for s in sessions:
            qs = s["questions"]
            user_answers = {}
            sc = 0
            for q in qs:
                if q["_correct"]:
                    user_answers[q["id"]] = "a"; sc += 1
                else:
                    user_answers[q["id"]] = "bcd"[(int(q["id"][1:]) % 3)]
            clean = [{k: v for k, v in q.items() if k != "_correct"} for q in qs]
            levels = sorted({q["level"] for q in qs})
            sid = ("demo-" + s["exam_type"] + "-" + s["category"]).lower()
            sid = "".join(ch if ch.isalnum() else "-" for ch in sid)[:60] + "-" + s["day"].replace("-", "")
            conn.execute(
                """INSERT INTO quiz_sessions
                   (session_id, document_id, model, source_title, source_type,
                    category, exam_type, question_count, difficulty, levels,
                    questions, user_answers, score_correct, score_total,
                    generated_at, answered_at)
                   VALUES (?, NULL, ?, ?, 'demo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, s["model"], s["title"], s["category"], s["exam_type"],
                 len(qs), s["diff"], json.dumps(levels, ensure_ascii=False),
                 json.dumps(clean, ensure_ascii=False),
                 json.dumps(user_answers, ensure_ascii=False),
                 sc, len(qs),
                 f'{s["day"]}T09:00:00+00:00', f'{s["day"]}T09:50:00+00:00'),
            )
        conn.commit()
    finally:
        conn.close()

    by_type = {}
    for s in sessions:
        t = s["exam_type"]
        c = sum(1 for q in s["questions"] if q["_correct"])
        n = len(s["questions"])
        by_type.setdefault(t, [0, 0])
        by_type[t][0] += c; by_type[t][1] += n
    print(f"投入: {len(sessions)} セッション / {total} 問 / 正答 {correct} = 総合 {round(correct/total*100)}%")
    for t, (c, n) in by_type.items():
        print(f"  {t:22} {c:3}/{n:3} = {round(c/n*100)}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
