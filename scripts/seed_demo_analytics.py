#!/usr/bin/env python3
"""Seed the quiz_sessions table with consistent demo analytics data.

Goal: an overall score of ~73% that stays internally consistent across
EVERY analytics endpoint. The breakdown / tags / profile endpoints
recompute correct/total from each question's `answer` vs the stored
`user_answers`, so we can't just write score columns — the per-question
answers must actually yield ~73%. This script:

  1. builds ~4 category "mock exams" of real-ish questions (topic, level,
     tags, choices, answer),
  2. marks each question correct/wrong with a level-based probability
     (K1 easiest .. K4 hardest) so the K1>K2>K3>K4 curve looks real,
  3. nudges the global correct count to hit exactly ~73%,
  4. derives user_answers (correct -> answer, wrong -> a distractor) and
     sets score_correct/score_total to match,
  5. spreads answered_at across recent days (active_days + recently_missed
     ordering look real),
  6. REPLACES quiz_sessions (existing rows deleted; a .bak of the DB
     should be taken by the caller first).

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
LEVEL_P = {"K1": 0.90, "K2": 0.80, "K3": 0.66, "K4": 0.55}

# (topic, level, [tags], question, (a,b,c,d), answer_key)
NETWORK = [
    ("OSI参照モデル", "K1", ["osi参照モデル", "プロトコル階層"],
     "OSI参照モデルで第3層(ネットワーク層)に該当するものはどれか。",
     ("IPによる経路選択", "MACアドレスでのフレーム転送", "TCPの再送制御", "HTTPの要求応答"), "a"),
    ("OSI参照モデル", "K2", ["osi参照モデル", "プロトコル階層"],
     "トランスポート層の役割として最も適切なものはどれか。",
     ("エンドツーエンドの信頼性確保", "物理信号の変換", "経路表の管理", "ドメイン名解決"), "a"),
    ("TCP/IP", "K2", ["tcp/ip", "コネクション管理"],
     "TCPの3ウェイハンドシェイクで最初に送られるセグメントはどれか。",
     ("SYN", "ACK", "FIN", "RST"), "a"),
    ("TCP/IP", "K3", ["tcp/ip", "輻輳制御"],
     "TCPの輻輳制御でパケットロス検知後にウィンドウを大きく絞る動作はどれか。",
     ("スロースタートへの復帰", "高速再送の停止", "MSSの増加", "RTTの無視"), "a"),
    ("サブネット", "K3", ["サブネット", "tcp/ip"],
     "192.168.1.0/26 のサブネットで利用可能なホスト数はいくつか。",
     ("62", "64", "126", "30"), "a"),
    ("サブネット", "K4", ["サブネット", "ルーティング"],
     "可変長サブネットマスク(VLSM)導入の主目的として最も適切なものはどれか。",
     ("アドレス空間の効率的割当", "ブロードキャスト廃止", "MACの短縮", "DNS負荷分散"), "a"),
    ("ルーティング", "K2", ["ルーティング"],
     "ディスタンスベクタ型ルーティングの説明として正しいものはどれか。",
     ("隣接ルータと経路情報を交換する", "全トポロジを各ルータが保持する", "経路を手動固定する", "MACで転送する"), "a"),
    ("ルーティング", "K4", ["ルーティング", "輻輳制御"],
     "リンクステート型がディスタンスベクタ型より収束が速い主因はどれか。",
     ("全体トポロジから最短経路を計算するため", "ホップ数を無視するため", "経路を広告しないため", "TTLが長いため"), "a"),
    ("DNS", "K1", ["dns"],
     "DNSで名前からIPアドレスを引くレコード種別はどれか。",
     ("Aレコード", "MXレコード", "PTRレコード", "TXTレコード"), "a"),
    ("DNS", "K3", ["dns", "http"],
     "DNSキャッシュポイズニングの緩和策として適切なものはどれか。",
     ("DNSSECの導入", "TTLを0にする", "UDPを禁止する", "Aレコード廃止"), "a"),
    ("HTTP", "K2", ["http"],
     "HTTPステータス 301 の意味はどれか。",
     ("恒久的なリダイレクト", "認証が必要", "サーバ内部エラー", "リソース未検出"), "a"),
    ("HTTP", "K3", ["http", "tcp/ip"],
     "HTTP/2 が HTTP/1.1 比で遅延を減らす主な仕組みはどれか。",
     ("多重化(ストリーム)", "テキストヘッダ化", "コネクション毎1要求", "TLS廃止"), "a"),
    ("スイッチング", "K2", ["スイッチング"],
     "L2スイッチがフレーム転送先を決めるために使う表はどれか。",
     ("MACアドレステーブル", "ルーティングテーブル", "ARPブラックリスト", "DNSゾーン"), "a"),
    ("スイッチング", "K4", ["スイッチング", "ルーティング"],
     "VLAN間通信に必要な機能はどれか。",
     ("ルーティング(L3)", "ハブの追加", "STPの無効化", "全ポートアクセス化"), "a"),
]

DATABASE = [
    ("正規化", "K1", ["正規化", "設計"],
     "第1正規形が満たすべき条件はどれか。",
     ("繰り返し項目を排除し各列が原子値", "部分関数従属の排除", "推移的従属の排除", "外部キー必須"), "a"),
    ("正規化", "K2", ["正規化", "設計"],
     "第3正規形で排除する従属はどれか。",
     ("推移的関数従属", "完全関数従属", "多値従属", "結合従属"), "a"),
    ("正規化", "K4", ["正規化", "設計"],
     "過度な正規化が招きやすい問題はどれか。",
     ("結合増加による性能低下", "更新不整合の増加", "冗長データの増加", "NULLの完全排除"), "a"),
    ("SQL", "K2", ["sql"],
     "重複を除いて取得するSQL句はどれか。",
     ("SELECT DISTINCT", "SELECT UNIQUE COUNT", "GROUP DISTINCT", "SELECT ONLY"), "a"),
    ("SQL", "K3", ["sql", "結合"],
     "左表の全行と一致する右表行を返す結合はどれか。",
     ("LEFT OUTER JOIN", "INNER JOIN", "CROSS JOIN", "RIGHT ONLY JOIN"), "a"),
    ("SQL", "K3", ["sql", "インデックス"],
     "WHERE句で関数を列に適用するとインデックスが効きにくい理由はどれか。",
     ("非SARGableになり全走査になりがち", "型が変わるため", "ロックが増えるため", "NULLになるため"), "a"),
    ("トランザクション", "K2", ["トランザクション", "acid"],
     "ACIDの「I」が表す性質はどれか。",
     ("分離性(Isolation)", "原子性", "一貫性", "永続性"), "a"),
    ("トランザクション", "K3", ["トランザクション", "ロック"],
     "あるTxが書いた未コミット値を別Txが読む異常はどれか。",
     ("ダーティリード", "ファントムリード", "反復不能読取", "ロストアップデート"), "a"),
    ("トランザクション", "K4", ["トランザクション", "ロック"],
     "ファントムリードを防げる最も強い分離レベルはどれか。",
     ("SERIALIZABLE", "READ COMMITTED", "READ UNCOMMITTED", "REPEATABLE READ"), "a"),
    ("インデックス", "K2", ["インデックス"],
     "B+木インデックスが得意な検索はどれか。",
     ("範囲検索と前方一致", "中間一致(LIKE '%x%')", "全列集計", "乱数照合"), "a"),
    ("インデックス", "K3", ["インデックス", "設計"],
     "複合インデックス(A,B)が効きにくいクエリはどれか。",
     ("Bのみを条件にした検索", "Aのみの検索", "A AND Bの検索", "Aの範囲検索"), "a"),
    ("結合", "K3", ["結合", "sql"],
     "大表同士の等値結合で一般に有利なアルゴリズムはどれか。",
     ("ハッシュ結合", "ネステッドループ", "クロス結合", "ソート無しマージ"), "a"),
    ("設計", "K2", ["設計"],
     "サロゲートキーの利点として適切なものはどれか。",
     ("業務変更の影響を受けにくい", "意味が読み取りやすい", "必ず一意でない", "結合が不要になる"), "a"),
    ("ロック", "K4", ["ロック", "トランザクション"],
     "2相ロック(2PL)が保証するものはどれか。",
     ("直列化可能性", "デッドロック皆無", "ロック不要化", "常に最速"), "a"),
]

SECURITY = [
    ("認証", "K1", ["認証", "アクセス制御"],
     "「知識・所持・生体」を組み合わせる認証方式はどれか。",
     ("多要素認証", "シングルサインオン", "ロールベース認証", "総当たり認証"), "a"),
    ("認証", "K2", ["認証"],
     "OAuth2.0 が主に扱うものはどれか。",
     ("認可(アクセス委譲)", "暗号化方式", "ファイアウォール制御", "物理認証"), "a"),
    ("暗号化", "K2", ["暗号化", "公開鍵"],
     "公開鍵暗号で送信者が暗号化に使う鍵はどれか。",
     ("受信者の公開鍵", "受信者の秘密鍵", "送信者の秘密鍵", "共通鍵"), "a"),
    ("暗号化", "K3", ["暗号化", "公開鍵", "tls"],
     "TLSハンドシェイクで公開鍵暗号が主に使われる目的はどれか。",
     ("共通鍵の安全な共有", "本文の全暗号化", "圧縮", "改ざん検知のみ"), "a"),
    ("ハッシュ", "K2", ["ハッシュ"],
     "パスワード保存で推奨される処理はどれか。",
     ("ソルト付きハッシュ", "可逆暗号で保存", "平文保存", "Base64エンコード"), "a"),
    ("ハッシュ", "K3", ["ハッシュ", "暗号化"],
     "ハッシュの「衝突耐性」が意味するものはどれか。",
     ("同一ハッシュの別入力を作りにくい", "復号できない", "高速計算できる", "鍵が不要"), "a"),
    ("攻撃手法", "K2", ["攻撃手法", "脆弱性"],
     "入力値を悪用してDB操作を行う攻撃はどれか。",
     ("SQLインジェクション", "DoS", "中間者攻撃", "総当たり"), "a"),
    ("攻撃手法", "K3", ["攻撃手法", "脆弱性"],
     "反射型XSSの主な緩和策はどれか。",
     ("出力エスケープ", "DBの暗号化", "ポート閉塞", "DNSSEC"), "a"),
    ("攻撃手法", "K4", ["攻撃手法", "認証"],
     "CSRF対策として最も適切なものはどれか。",
     ("CSRFトークンの検証", "パスワード長の強制", "TLS化のみ", "IP固定のみ"), "a"),
    ("アクセス制御", "K2", ["アクセス制御", "認証"],
     "最小権限の原則の説明として適切なものはどれか。",
     ("必要最小限の権限のみ付与", "全員に管理者権限", "権限を共有", "権限を無効化"), "a"),
    ("アクセス制御", "K4", ["アクセス制御"],
     "RBACの「ロール」が果たす役割はどれか。",
     ("権限の束を利用者にまとめて割当", "暗号鍵の生成", "ログ収集", "通信暗号化"), "a"),
    ("tls", "K3", ["tls", "公開鍵"],
     "サーバ証明書が保証する主な内容はどれか。",
     ("サーバの正当性(なりすまし防止)", "通信速度", "可用性", "保存暗号化"), "a"),
    ("脆弱性", "K1", ["脆弱性"],
     "既知脆弱性に共通の識別子を与える仕組みはどれか。",
     ("CVE", "OWASP", "CSP", "JVN専用ID"), "a"),
    ("脆弱性", "K3", ["脆弱性", "攻撃手法"],
     "ゼロデイ攻撃の特徴として適切なものはどれか。",
     ("修正前の脆弱性を突く", "必ず内部犯行", "DoSに限定", "暗号を解読する"), "a"),
]

LINUX = [
    ("パーミッション", "K1", ["パーミッション"],
     "chmod 644 file のファイル所有者の権限はどれか。",
     ("読み書き", "読み取りのみ", "実行のみ", "なし"), "a"),
    ("パーミッション", "K3", ["パーミッション"],
     "ディレクトリに設定するスティッキービットの効果はどれか。",
     ("所有者以外の削除を制限", "実行を禁止", "読取を全許可", "SUID付与"), "a"),
    ("プロセス", "K2", ["プロセス"],
     "親プロセス終了で残り init に引き取られるプロセスはどれか。",
     ("孤児プロセス", "ゾンビプロセス", "デーモン", "フォアグラウンド"), "a"),
    ("プロセス", "K3", ["プロセス", "シェル"],
     "プロセスに終了を促す既定シグナルはどれか。",
     ("SIGTERM", "SIGKILL", "SIGSTOP", "SIGHUP"), "a"),
    ("シェル", "K2", ["シェル"],
     "標準エラー出力をファイルへリダイレクトする記法はどれか。",
     ("2> file", "> file", "1| file", "&< file"), "a"),
    ("シェル", "K3", ["シェル"],
     "前コマンドの終了コードを参照する変数はどれか。",
     ("$?", "$!", "$$", "$#"), "a"),
    ("systemd", "K2", ["systemd"],
     "サービスを起動かつ自動起動有効化するコマンドはどれか。",
     ("systemctl enable --now svc", "systemctl reload svc", "service svc status", "systemctl mask svc"), "a"),
    ("systemd", "K4", ["systemd", "ログ"],
     "systemd管理サービスのログを見るコマンドはどれか。",
     ("journalctl -u svc", "tail /etc/svc", "dmesg only", "cat /proc/svc"), "a"),
    ("ネットワーク設定", "K3", ["ネットワーク設定"],
     "待ち受けTCPポート一覧を確認するコマンドはどれか。",
     ("ss -tlnp", "ping -c", "traceroute", "nslookup"), "a"),
    ("ネットワーク設定", "K4", ["ネットワーク設定"],
     "デフォルトゲートウェイを確認するコマンドはどれか。",
     ("ip route", "ip addr", "arp -a", "hostnamectl"), "a"),
    ("ログ", "K2", ["ログ"],
     "ログを末尾から追従表示するコマンドはどれか。",
     ("tail -f", "head -n", "less +F のみ", "grep -v"), "a"),
    ("パッケージ管理", "K1", ["パッケージ管理"],
     "Debian系でパッケージを導入するコマンドはどれか。",
     ("apt install", "yum install", "dnf install", "pacman -S"), "a"),
    ("パッケージ管理", "K3", ["パッケージ管理"],
     "インストール済みパッケージの提供ファイルを調べる(dpkg)コマンドはどれか。",
     ("dpkg -L pkg", "dpkg -i pkg", "apt search", "dpkg --purge"), "a"),
    ("プロセス", "K4", ["プロセス", "systemd"],
     "CPU使用率の高い順にプロセスを監視できるものはどれか。",
     ("top / htop", "ls -l", "df -h", "free -m"), "a"),
]

SESSIONS = [
    ("ネットワーク基礎 模試", "ネットワーク基礎", "qwen3.6-27b-abliterated", "medium", NETWORK, "2026-06-03"),
    ("データベース設計 模試", "データベース", "qwen3.6-27b-abliterated", "medium", DATABASE, "2026-06-05"),
    ("情報セキュリティ 模試", "情報セキュリティ", "gemma4-12b-qat-uncensored", "hard",   SECURITY, "2026-06-08"),
    ("Linux 運用 模試",      "Linux運用",       "hermes4-14b-abliterated",  "easy",   LINUX,    "2026-06-10"),
]


def _wrong_choice(answer: str, choices: dict) -> str:
    for k in choices:
        if k != answer:
            return k
    return answer


def build():
    """Return (sessions, total_q, total_correct) with correctness assigned."""
    # First pass: assign correctness by level probability.
    built = []
    flat = []  # references for global tuning: (sess_idx, q_idx, level)
    for s_idx, (title, cat, model, diff, bank, day) in enumerate(SESSIONS):
        qs = []
        for i, (topic, level, tags, qtext, choices4, ans) in enumerate(bank, start=1):
            choices = {"a": choices4[0], "b": choices4[1], "c": choices4[2], "d": choices4[3]}
            correct = random.random() < LEVEL_P[level]
            qs.append({
                "id": f"Q{i:03d}", "level": level, "topic": topic, "tags": tags,
                "question": qtext, "choices": choices, "answer": ans,
                "explanation": f"正解は {ans}。{topic}に関する基本事項。資料の該当章を参照。",
                "source_hint": f"{cat} / {topic}",
                "_correct": correct,
            })
            flat.append((s_idx, len(qs) - 1, level))
        built.append({"title": title, "cat": cat, "model": model, "diff": diff,
                      "day": day, "questions": qs})

    total = len(flat)
    desired = round(total * TARGET_ACCURACY)

    def cur_correct():
        return sum(1 for s in built for q in s["questions"] if q["_correct"])

    # Tune toward desired: flip hardest-first when too high, easiest-first when too low.
    order_hard = sorted(flat, key=lambda f: LEVEL_P[f[2]])          # hard (low p) first
    order_easy = sorted(flat, key=lambda f: -LEVEL_P[f[2]])         # easy (high p) first
    guard = 0
    while cur_correct() > desired and guard < total * 4:
        for s_idx, q_idx, _ in order_hard:
            if cur_correct() <= desired:
                break
            q = built[s_idx]["questions"][q_idx]
            if q["_correct"]:
                q["_correct"] = False
        guard += 1
    guard = 0
    while cur_correct() < desired and guard < total * 4:
        for s_idx, q_idx, _ in order_easy:
            if cur_correct() >= desired:
                break
            q = built[s_idx]["questions"][q_idx]
            if not q["_correct"]:
                q["_correct"] = True
        guard += 1

    return built, total, cur_correct()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "data", "quizgen.db"))
    ap.add_argument("--yes", action="store_true", help="confirm: deletes existing quiz_sessions")
    args = ap.parse_args(argv)

    if not args.yes:
        print("既存 quiz_sessions を全削除してデモを投入します。--yes を付けて実行してください。")
        return 1

    built, total, correct = build()
    conn = sqlite3.connect(args.db)
    try:
        conn.execute("DELETE FROM quiz_sessions")
        for s in built:
            qs = s["questions"]
            user_answers = {}
            sc = 0
            for q in qs:
                if q["_correct"]:
                    user_answers[q["id"]] = q["answer"]
                    sc += 1
                else:
                    user_answers[q["id"]] = _wrong_choice(q["answer"], q["choices"])
            # strip the private _correct flag before persisting
            clean_qs = [{k: v for k, v in q.items() if k != "_correct"} for q in qs]
            levels = sorted({q["level"] for q in qs})
            sid = "demo-" + s["cat"].lower().replace(" ", "-").replace("/", "-")[:40] \
                  + "-" + s["day"].replace("-", "")
            gen_at = f'{s["day"]}T09:00:00+00:00'
            ans_at = f'{s["day"]}T09:40:00+00:00'
            conn.execute(
                """INSERT INTO quiz_sessions
                   (session_id, document_id, model, source_title, source_type,
                    category, question_count, difficulty, levels, questions,
                    user_answers, score_correct, score_total, generated_at, answered_at)
                   VALUES (?, NULL, ?, ?, 'demo', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sid, s["model"], s["title"], s["cat"], len(qs), s["diff"],
                 json.dumps(levels, ensure_ascii=False),
                 json.dumps(clean_qs, ensure_ascii=False),
                 json.dumps(user_answers, ensure_ascii=False),
                 sc, len(qs), gen_at, ans_at),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"投入完了: {len(built)} セッション / {total} 問 / 正答 {correct} "
          f"= 総合 {round(correct/total*100)}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
