"""
ContentService
camoufoxを使ったボット検出回避スクレイピングに対応した
コンテンツ取得サービス。

設計方針:
- SourcePlugin 基底クラスによるプラグイン構造（拡張容易）
- camoufox（Playwright互換）でボット検出を回避
- 階層指定BFS（Max 8階層）で対象ドキュメントを再帰収集
- 対象ファイル: CSV / PDF / PNG / HTMLテーブル のみ
- 1回の fetch 呼び出しで指定階層分を一括取得（再呼び出し不要）
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from cachetools import TTLCache

from app.services.safe_fetch import (
    FetchPolicy,
    ResponseTooLargeError,
    UnsafeURLError,
    check_url,
    is_url_allowed,
    safe_get,
)

logger = logging.getLogger(__name__)

# ======================================================================
# 定数
# ======================================================================
MAX_DEPTH         = 8          # 最大階層数（ユーザー指定の上限）
MAX_PAGES_PER_RUN = 50         # 1回の実行で訪問するページ上限
MAX_CONTENT_CHARS = 12000      # Ollamaに渡すコンテキスト上限文字数
CACHE_TTL         = 3600       # キャッシュTTL（秒）
CACHE_MAXSIZE     = 50

# ----- パーサ側のdefensive limits (P1-F) -----
# 敵意ある/壊れた入力で RAM を食い潰されないよう、各抽出段階で
# 個別に上限を設ける。ネットワーク側は safe_fetch が 10 MiB を
# キャップするので、ここでは「1 URL あたりのバイトはきても OK、
# ただしメモリ上に展開する文字列はこれ以内に収める」という粒度。
MAX_HTML_TABLES         = 50                   # 1 ページあたり抽出するテーブル数
MAX_TABLE_ROWS_PER_TAB  = 200                  # 1 テーブルあたりの行数
MAX_CELL_LEN            = 1024                 # 1 セルあたりの文字数（HTML/CSV 共通）
MAX_CSV_ROWS            = 50                   # CSV 側の行数
MAX_PDF_PAGES           = 20                   # PDF 側のページ数
MAX_PDF_TEXT_PER_PAGE   = 50 * 1024            # PDF 1 ページあたり抽出する文字数
MAX_PAGE_TEXT_CHARS     = 1 * 1024 * 1024      # HTML 1 ページの本文テキスト上限

# 対象ファイル拡張子
TARGET_EXTENSIONS = {".csv", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _truncate(text: str, max_len: int, marker: str = "…") -> str:
    """Return ``text`` truncated to ``max_len`` characters with a trailing marker.

    The marker is appended iff truncation actually happened.
    """
    if text is None:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + marker

# camoufoxが利用可能かどうかのフラグ（起動時に確認）
_CAMOUFOX_AVAILABLE: bool | None = None

# キャッシュ（URL → 取得結果）
_cache: TTLCache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) "
        "Gecko/20100101 Firefox/135.0"
    )
}


# ======================================================================
# camoufox 利用可否チェック
# ======================================================================
def _is_camoufox_available() -> bool:
    global _CAMOUFOX_AVAILABLE
    if _CAMOUFOX_AVAILABLE is not None:
        return _CAMOUFOX_AVAILABLE
    try:
        import camoufox  # noqa: F401
        _CAMOUFOX_AVAILABLE = True
    except ImportError:
        _CAMOUFOX_AVAILABLE = False
        logger.warning("camoufox が見つかりません。requestsフォールバックを使用します。")
    return _CAMOUFOX_AVAILABLE


# ======================================================================
# ドキュメント抽出ユーティリティ
# ======================================================================
class DocumentExtractor:
    """
    HTMLページからCSV・PDF・PNG・テーブルのコンテンツを抽出する。
    """

    @staticmethod
    def extract_tables(soup: BeautifulSoup) -> str:
        """HTMLテーブルをMarkdown形式のテキストに変換する。

        Defensive limits (P1-F):
          - 抽出するテーブル数は ``MAX_HTML_TABLES`` まで
          - 1 テーブルあたりの行数は ``MAX_TABLE_ROWS_PER_TAB`` まで
          - 1 セルの文字数は ``MAX_CELL_LEN`` でトランケート
        """
        tables = soup.find_all("table")
        if not tables:
            return ""

        results = []
        for i, table in enumerate(tables[:MAX_HTML_TABLES], 1):
            rows = table.find_all("tr")
            if not rows:
                continue

            md_rows = []
            for j, row in enumerate(rows[:MAX_TABLE_ROWS_PER_TAB]):
                cells = row.find_all(["th", "td"])
                cell_texts = [
                    _truncate(c.get_text(strip=True).replace("|", "｜"), MAX_CELL_LEN)
                    for c in cells
                ]
                md_rows.append("| " + " | ".join(cell_texts) + " |")
                if j == 0:
                    md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")

            results.append(f"\n### テーブル {i}\n" + "\n".join(md_rows))

        if len(tables) > MAX_HTML_TABLES:
            results.append(
                f"\n_(HTML テーブルが {len(tables)} 件ありました。"
                f"先頭 {MAX_HTML_TABLES} 件のみを抽出しています。)_"
            )

        return "\n".join(results)

    @staticmethod
    def extract_csv_content(url: str, content: bytes) -> str:
        """CSVバイト列をMarkdownテーブル形式に変換する。

        Defensive limits (P1-F):
          - 行数は ``MAX_CSV_ROWS`` まで
          - 各セルは ``MAX_CELL_LEN`` でトランケート
        """
        try:
            text = content.decode("utf-8-sig", errors="replace")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            if not rows:
                return ""

            md = []
            for i, row in enumerate(rows[:MAX_CSV_ROWS]):
                escaped = [
                    _truncate(c.replace("|", "｜"), MAX_CELL_LEN)
                    for c in row
                ]
                md.append("| " + " | ".join(escaped) + " |")
                if i == 0:
                    md.append("| " + " | ".join(["---"] * len(row)) + " |")

            if len(rows) > MAX_CSV_ROWS:
                md.append(
                    f"_(CSV は {len(rows)} 行ありました。"
                    f"先頭 {MAX_CSV_ROWS} 行のみを抽出しています。)_"
                )

            return f"\n### CSV: {url}\n" + "\n".join(md)
        except Exception as e:
            logger.warning(f"CSV解析エラー ({url}): {e}")
            return ""

    @staticmethod
    def extract_pdf_content(url: str, content: bytes) -> str:
        """PDFバイト列からテキストを抽出する。

        Defensive limits (P1-F):
          - 処理するページ数は ``MAX_PDF_PAGES`` まで
          - 1 ページあたり抽出する文字数は ``MAX_PDF_TEXT_PER_PAGE`` でトランケート
          - さらに結果全体を ``MAX_CONTENT_CHARS`` に切り詰める (従来動作)
        """
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            texts = []
            for page in reader.pages[:MAX_PDF_PAGES]:
                t = page.extract_text() or ""
                t = t.strip()
                if t:
                    texts.append(_truncate(t, MAX_PDF_TEXT_PER_PAGE))
            if not texts:
                return ""
            combined = "\n".join(texts)[:MAX_CONTENT_CHARS]
            return f"\n### PDF: {url}\n{combined}"
        except Exception as e:
            logger.warning(f"PDF解析エラー ({url}): {e}")
            return ""

    @staticmethod
    def extract_page_text(soup: BeautifulSoup) -> str:
        """ページ本文テキストを抽出する（テーブルは別途処理）。

        Defensive limit (P1-F): 1 ページの本文テキストは ``MAX_PAGE_TEXT_CHARS``
        でトランケートする。HTML そのもののバイト数は safe_fetch 側で既に
        ``MAX_FETCH_BYTES`` に制限されているが、そこから展開された
        テキスト表現は数倍のメモリを食うことがあるので別層で抑える。
        """
        for tag in soup(["script", "style", "nav", "footer", "header",
                          "aside", "form", "noscript", "iframe"]):
            tag.decompose()

        body = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", {"id": re.compile(r"content|main", re.I)})
            or soup.body
        )
        raw = body.get_text(separator="\n") if body else soup.get_text("\n")
        lines = [ln.strip() for ln in raw.splitlines()]
        joined = "\n".join(ln for ln in lines if ln)
        return _truncate(joined, MAX_PAGE_TEXT_CHARS)


# ======================================================================
# SourcePlugin 基底クラス
# ======================================================================
class SourcePlugin(ABC):
    """コンテンツソースのインターフェース。新しいソースはこれを継承する。"""

    @abstractmethod
    def can_handle(self, source: str) -> bool:
        """このプラグインが source を処理できるか判定する。"""

    @abstractmethod
    def fetch(self, source: str, **kwargs) -> dict:
        """
        コンテンツを取得して返す。
        Returns:
            {
                "title":    str,
                "content":  str,
                "source":   str,
                "type":     str,
                "pages":    list[dict],  # 収集したページ情報
                "depth":    int,
                "doc_types": list[str],  # 実際に取得したドキュメント種別
            }
        """


# ======================================================================
# camoufox BFS スクレイピングプラグイン
# ======================================================================
class CamoufoxPlugin(SourcePlugin):
    """
    camoufoxを使ったボット検出回避スクレイピング。
    BFS（幅優先探索）で指定階層分のリンクを辿り、
    CSV / PDF / PNG / HTMLテーブル のみを収集する。
    """

    def can_handle(self, source: str) -> bool:
        return source.startswith("http://") or source.startswith("https://")

    def fetch(self, source: str, **kwargs) -> dict:
        depth     = min(int(kwargs.get("depth", 1)), MAX_DEPTH)
        doc_types = set(kwargs.get("doc_types", ["table", "csv", "pdf", "png"]))

        # Entry-point SSRF validation. If the user-supplied URL is rejected,
        # surface a ValueError (UnsafeURLError) so the API layer can map it
        # to a 422 with a user-safe message instead of a 500. This is the
        # first layer of the deny-by-default policy — see safe_fetch.py and
        # SECURITY.md.
        policy = FetchPolicy()
        check_url(source, policy)

        cache_key = hashlib.md5(
            f"{source}|{depth}|{sorted(doc_types)}".encode()
        ).hexdigest()
        if cache_key in _cache:
            return _cache[cache_key]

        if _is_camoufox_available():
            result = self._fetch_with_camoufox(source, depth, doc_types, policy)
        else:
            result = self._fetch_with_requests(source, depth, doc_types, policy)

        _cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # camoufox実装
    # ------------------------------------------------------------------
    def _fetch_with_camoufox(
        self, start_url: str, depth: int, doc_types: set,
        policy: FetchPolicy | None = None,
    ) -> dict:
        from camoufox.sync_api import Camoufox

        policy = policy or FetchPolicy()
        extractor = DocumentExtractor()
        visited   = set()
        pages     = []
        contents  = []
        found_types = set()

        # BFSキュー: (url, current_depth)
        queue = deque([(start_url, 0)])
        base_domain = urlparse(start_url).netloc

        with Camoufox(headless="virtual", os="linux") as browser:
            page = browser.new_page()

            while queue and len(visited) < MAX_PAGES_PER_RUN:
                url, current_depth = queue.popleft()
                if url in visited:
                    continue
                visited.add(url)

                # Pre-flight SSRF check. Firefox does its own DNS so this is
                # best-effort (see SECURITY.md) but it immediately rejects
                # the common cases (literal metadata IPs, localhost, etc.)
                # before Firefox even gets involved.
                try:
                    check_url(url, policy)
                except UnsafeURLError as e:
                    logger.warning(f"[camoufox] URL拒否: {e}")
                    continue

                try:
                    logger.info(f"[camoufox] 訪問 (depth={current_depth}): {url}")
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(0.5)  # レート制限対策

                    html  = page.content()
                    title = page.title() or url
                    soup  = BeautifulSoup(html, "lxml")

                    page_content = []
                    page_types   = []

                    # HTMLテーブル抽出
                    if "table" in doc_types:
                        table_text = extractor.extract_tables(soup)
                        if table_text:
                            page_content.append(table_text)
                            page_types.append("table")
                            found_types.add("table")

                    # ページ本文（テーブル以外）
                    if not page_content:
                        page_content.append(extractor.extract_page_text(soup))

                    # リンクを収集してBFSキューに追加
                    if current_depth < depth:
                        links = self._collect_links(soup, url, base_domain, doc_types)
                        for link_url, link_type in links:
                            if link_url in visited:
                                continue
                            # Every queued URL must pass the SSRF policy;
                            # reject early so we don't waste a Camoufox page.
                            if not is_url_allowed(link_url, policy):
                                logger.debug(f"[camoufox] リンク拒否 (policy): {link_url}")
                                continue
                            if link_type in ("csv", "pdf", "png") and link_type in doc_types:
                                # ファイルは直接ダウンロード
                                file_content = self._download_file(
                                    link_url, link_type, extractor, policy=policy,
                                )
                                if file_content:
                                    contents.append(file_content)
                                    found_types.add(link_type)
                                    visited.add(link_url)
                            else:
                                # HTMLページはBFSキューに追加
                                queue.append((link_url, current_depth + 1))

                    if page_content:
                        combined = "\n".join(page_content)
                        contents.append(f"## ページ: {title}\n{combined}")
                        pages.append({
                            "url":   url,
                            "title": title,
                            "depth": current_depth,
                            "types": page_types,
                        })

                except Exception as e:
                    logger.warning(f"[camoufox] エラー ({url}): {e}")
                    continue

        return self._build_result(start_url, contents, pages, depth, found_types)

    # ------------------------------------------------------------------
    # requestsフォールバック実装
    # ------------------------------------------------------------------
    def _fetch_with_requests(
        self, start_url: str, depth: int, doc_types: set,
        policy: FetchPolicy | None = None,
    ) -> dict:
        policy = policy or FetchPolicy()
        extractor   = DocumentExtractor()
        visited     = set()
        pages       = []
        contents    = []
        found_types = set()

        queue       = deque([(start_url, 0)])
        base_domain = urlparse(start_url).netloc
        session     = requests.Session()
        session.headers.update(HEADERS)

        while queue and len(visited) < MAX_PAGES_PER_RUN:
            url, current_depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            try:
                logger.info(f"[requests] 訪問 (depth={current_depth}): {url}")
                try:
                    resp = safe_get(url, policy=policy, session=session, timeout=(5, 30))
                except UnsafeURLError as e:
                    logger.warning(f"[requests] URL拒否: {e}")
                    continue
                except ResponseTooLargeError as e:
                    logger.warning(f"[requests] レスポンス過大: {e}")
                    continue
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"

                content_type = resp.headers.get("Content-Type", "")

                # ファイルの直接処理
                ext = Path(urlparse(url).path).suffix.lower()
                if ext == ".csv" and "csv" in doc_types:
                    fc = extractor.extract_csv_content(url, resp.content)
                    if fc:
                        contents.append(fc)
                        found_types.add("csv")
                    continue
                elif ext == ".pdf" and "pdf" in doc_types:
                    fc = extractor.extract_pdf_content(url, resp.content)
                    if fc:
                        contents.append(fc)
                        found_types.add("pdf")
                    continue
                elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"} and "png" in doc_types:
                    contents.append(f"\n### 画像: {url}")
                    found_types.add("png")
                    continue

                # HTMLページ処理
                if "text/html" not in content_type:
                    continue

                soup  = BeautifulSoup(resp.text, "lxml")
                title = soup.title.string.strip() if soup.title else url

                page_content = []
                page_types   = []

                if "table" in doc_types:
                    table_text = extractor.extract_tables(soup)
                    if table_text:
                        page_content.append(table_text)
                        page_types.append("table")
                        found_types.add("table")

                if not page_content:
                    page_content.append(extractor.extract_page_text(soup))

                if current_depth < depth:
                    links = self._collect_links(soup, url, base_domain, doc_types)
                    for link_url, link_type in links:
                        if link_url in visited:
                            continue
                        if not is_url_allowed(link_url, policy):
                            logger.debug(f"[requests] リンク拒否 (policy): {link_url}")
                            continue
                        queue.append((link_url, current_depth + 1))

                if page_content:
                    combined = "\n".join(page_content)
                    contents.append(f"## ページ: {title}\n{combined}")
                    pages.append({
                        "url":   url,
                        "title": title,
                        "depth": current_depth,
                        "types": page_types,
                    })

            except Exception as e:
                logger.warning(f"[requests] エラー ({url}): {e}")
                continue

        return self._build_result(start_url, contents, pages, depth, found_types)

    # ------------------------------------------------------------------
    # リンク収集
    # ------------------------------------------------------------------
    def _collect_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        base_domain: str,
        doc_types: set,
    ) -> list[tuple[str, str]]:
        """
        ページ内のリンクを収集し、対象ファイル種別のみを返す。
        Returns: [(url, type), ...]  type: "html" | "csv" | "pdf" | "png"
        """
        results = []
        seen    = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            abs_url = urljoin(base_url, href)
            parsed  = urlparse(abs_url)

            # 同一ドメインのみ
            if parsed.netloc != base_domain:
                continue

            if abs_url in seen:
                continue
            seen.add(abs_url)

            ext = Path(parsed.path).suffix.lower()

            if ext == ".csv" and "csv" in doc_types:
                results.append((abs_url, "csv"))
            elif ext == ".pdf" and "pdf" in doc_types:
                results.append((abs_url, "pdf"))
            elif ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"} and "png" in doc_types:
                results.append((abs_url, "png"))
            elif ext in {"", ".html", ".htm", ".php", ".asp", ".aspx"}:
                results.append((abs_url, "html"))

        return results

    # ------------------------------------------------------------------
    # ファイルダウンロード（camoufox経由ではなくrequestsで取得）
    # ------------------------------------------------------------------
    def _download_file(
        self,
        url: str,
        file_type: str,
        extractor: DocumentExtractor,
        *,
        policy: FetchPolicy | None = None,
    ) -> str:
        policy = policy or FetchPolicy()
        try:
            resp = safe_get(url, policy=policy, headers=HEADERS, timeout=(5, 30))
            resp.raise_for_status()
            if file_type == "csv":
                return extractor.extract_csv_content(url, resp.content)
            elif file_type == "pdf":
                return extractor.extract_pdf_content(url, resp.content)
            elif file_type == "png":
                return f"\n### 画像: {url}"
        except UnsafeURLError as e:
            logger.warning(f"ファイルダウンロード URL拒否 ({url}): {e}")
        except ResponseTooLargeError as e:
            logger.warning(f"ファイルダウンロード 過大 ({url}): {e}")
        except Exception as e:
            logger.warning(f"ファイルダウンロードエラー ({url}): {e}")
        return ""

    # ------------------------------------------------------------------
    # 結果オブジェクト構築
    # ------------------------------------------------------------------
    def _build_result(
        self,
        source: str,
        contents: list[str],
        pages: list[dict],
        depth: int,
        found_types: set,
    ) -> dict:
        full_content = "\n\n".join(contents)
        # コンテキスト上限でトリミング
        if len(full_content) > MAX_CONTENT_CHARS:
            full_content = full_content[:MAX_CONTENT_CHARS] + "\n...(省略)"

        title = pages[0]["title"] if pages else source

        return {
            "title":     title,
            "content":   full_content,
            "source":    source,
            "type":      "url_deep",
            "pages":     pages,
            "depth":     depth,
            "doc_types": sorted(found_types),
            "page_count": len(pages),
        }


# ======================================================================
# プレーンテキスト プラグイン（フォールバック）
# ======================================================================
class PlainTextPlugin(SourcePlugin):
    def can_handle(self, source: str) -> bool:
        return True

    def fetch(self, source: str, **kwargs) -> dict:
        content = source[:MAX_CONTENT_CHARS]
        return {
            "title":     "直接入力テキスト",
            "content":   content,
            "source":    "plain_text",
            "type":      "text",
            "pages":     [],
            "depth":     0,
            "doc_types": ["text"],
            "page_count": 1,
        }


# ======================================================================
# ContentService（プラグインディスパッチャ）
# ======================================================================
class ContentService:
    """
    登録された SourcePlugin を順に試し、最初に処理できたものを使う。
    新しいプラグイン（ローカルファイル等）は register() で追加するだけで拡張可能。
    """

    def __init__(self):
        self._plugins: list[SourcePlugin] = []
        self.register(CamoufoxPlugin())
        self.register(PlainTextPlugin())  # フォールバック

    def register(self, plugin: SourcePlugin) -> None:
        self._plugins.append(plugin)

    def fetch(self, source: str, *, persist: bool = True, **kwargs) -> dict:
        """
        kwargs:
            depth     (int):  スクレイピング階層数（1〜8）
            doc_types (list): 対象ドキュメント種別 ["table","csv","pdf","png"]
            persist   (bool): True なら documents テーブルに保存。
                              preview 経由 (read-only) は False で呼ぶ。
                              BACKEND-3: 以前は preview も常に保存していた。
        """
        for plugin in self._plugins:
            if plugin.can_handle(source):
                result = plugin.fetch(source, **kwargs)
                if persist:
                    # スクレイピング結果をdocumentsテーブルに保存（重複時はスキップ）
                    doc_id = self._save_to_db(result)
                    if doc_id is not None:
                        result["document_id"] = doc_id
                return result
        raise ValueError("対応するコンテンツソースが見つかりません。")

    def preview(self, source: str, max_chars: int = 500, **kwargs) -> dict:
        """UIプレビュー用に先頭のみ返す（depth=1固定、DBには保存しない）。

        ``persist=False`` で fetch を呼ぶことで documents テーブルへの
        side-effect を持たない read-only な経路にする。実保存は明示的な
        /api/content/fetch (= generate flow) に限定する。
        """
        kwargs["depth"] = 1  # プレビューは1階層のみ
        result = self.fetch(source, persist=False, **kwargs)
        result["preview"] = result["content"][:max_chars] + (
            "..." if len(result["content"]) > max_chars else ""
        )
        return result

    # ------------------------------------------------------------------
    # ドキュメントDB自動保存
    # ------------------------------------------------------------------
    @staticmethod
    def _save_to_db(result: dict) -> int | None:
        """
        スクレイピング結果をdocumentsテーブルに保存する。
        重複（content_hash一致）の場合は既存IDを返す。
        """
        import json as _json
        from datetime import datetime, timezone
        try:
            from app.database import get_connection
        except Exception:
            logger.warning("データベースモジュールが利用できません。DB保存をスキップします。")
            return None

        title       = result.get("title", "")
        url         = result.get("source", "")
        content     = result.get("content", "")
        source_type = result.get("type", "text")
        page_count  = result.get("page_count", 1)
        doc_types   = result.get("doc_types", [])

        if not content:
            return None

        hash_source  = (url or "") + content
        content_hash = hashlib.md5(hash_source.encode("utf-8")).hexdigest()

        try:
            conn = get_connection()
            # 既存チェック
            existing = conn.execute(
                "SELECT id FROM documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if existing:
                conn.close()
                return existing["id"]

            scraped_at = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """INSERT INTO documents
                   (title, url, content, source_type, page_count, doc_types, scraped_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, url if url != "plain_text" else None, content, source_type,
                 page_count, _json.dumps(doc_types, ensure_ascii=False),
                 scraped_at, content_hash),
            )
            conn.commit()
            doc_id = cursor.lastrowid
            conn.close()
            logger.info(f"ドキュメントをDBに保存しました (id={doc_id})")
            return doc_id
        except Exception as e:
            logger.warning(f"ドキュメントDB保存エラー: {e}")
            return None
