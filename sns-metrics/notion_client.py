"""Notion への書き込み共通モジュール（標準ライブラリのみ・追加インストール不要）。

SNS投稿メトリクスDB（1行 = 「取得日 × 投稿」）に対して upsert（同じ投稿ID×取得日が
あれば更新、無ければ新規作成）を行う。Instagram取得スクリプトとX CSV取込スクリプトの
両方から利用する。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# DB のプロパティ名（Notion側の表示名と完全一致させること）
PROP_TITLE = "名称"
PROP_FETCH_DATE = "取得日"
PROP_PLATFORM = "プラットフォーム"
PROP_POST_ID = "投稿ID"
PROP_POST_DATE = "投稿日"
PROP_CONTENT = "投稿内容"
PROP_URL = "URL"

# 数値系プロパティ（キー = 内部名, 値 = Notionプロパティ名）
NUMBER_PROPS = {
    "impressions": "インプレッション",
    "reach": "リーチ",
    "likes": "いいね",
    "comments": "コメント",
    "saved": "保存",
    "shares": "シェア・リポスト",
    "profile_visits": "プロフィールアクセス",
    "link_clicks": "リンククリック",
    "engagement": "エンゲージメント",
    "engagement_rate": "エンゲージメント率(%)",
}


def _token() -> str:
    tok = os.environ.get("NOTION_TOKEN")
    if not tok:
        raise SystemExit(
            "環境変数 NOTION_TOKEN が未設定です。Notionのインテグレーション"
            "（内部）トークンを設定し、対象DBをそのインテグレーションに共有してください。"
        )
    return tok


def _database_id() -> str:
    db = os.environ.get("NOTION_DATABASE_ID")
    if not db:
        raise SystemExit("環境変数 NOTION_DATABASE_ID が未設定です。")
    return db


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{NOTION_API}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_token()}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"Notion APIエラー {e.code}: {body}") from e


def _find_existing_page(platform: str, post_id: str, fetch_date: str) -> str | None:
    """同じ プラットフォーム×投稿ID×取得日 のページがあればそのIDを返す。"""
    payload = {
        "filter": {
            "and": [
                {"property": PROP_PLATFORM, "select": {"equals": platform}},
                {"property": PROP_POST_ID, "rich_text": {"equals": post_id}},
                {"property": PROP_FETCH_DATE, "date": {"equals": fetch_date}},
            ]
        },
        "page_size": 1,
    }
    res = _request("POST", f"/databases/{_database_id()}/query", payload)
    results = res.get("results", [])
    return results[0]["id"] if results else None


def _build_properties(record: dict) -> dict:
    """内部レコード（dict）をNotionのproperties構造に変換する。"""
    props: dict = {}

    title = record.get("title") or f"{record.get('platform', '')} {record.get('post_id', '')}"
    props[PROP_TITLE] = {"title": [{"text": {"content": title[:2000]}}]}

    if record.get("platform"):
        props[PROP_PLATFORM] = {"select": {"name": record["platform"]}}
    if record.get("fetch_date"):
        props[PROP_FETCH_DATE] = {"date": {"start": record["fetch_date"]}}
    if record.get("post_id"):
        props[PROP_POST_ID] = {"rich_text": [{"text": {"content": str(record["post_id"])[:2000]}}]}
    if record.get("post_date"):
        props[PROP_POST_DATE] = {"date": {"start": record["post_date"]}}
    if record.get("content"):
        props[PROP_CONTENT] = {"rich_text": [{"text": {"content": str(record["content"])[:2000]}}]}
    if record.get("url"):
        props[PROP_URL] = {"url": record["url"]}

    for key, prop_name in NUMBER_PROPS.items():
        val = record.get(key)
        if val is not None:
            props[prop_name] = {"number": float(val)}

    return props


def upsert_record(record: dict) -> str:
    """1レコードを upsert する。作成/更新したページIDを返す。

    record の想定キー:
      platform, post_id, fetch_date(YYYY-MM-DD), post_date, content, url, title,
      impressions, reach, likes, comments, saved, shares, profile_visits,
      link_clicks, engagement, engagement_rate
    """
    platform = record.get("platform", "")
    post_id = str(record.get("post_id", ""))
    fetch_date = record.get("fetch_date", "")

    props = _build_properties(record)

    existing = None
    if platform and post_id and fetch_date:
        existing = _find_existing_page(platform, post_id, fetch_date)

    if existing:
        _request("PATCH", f"/pages/{existing}", {"properties": props})
        return existing

    created = _request(
        "POST",
        "/pages",
        {"parent": {"database_id": _database_id()}, "properties": props},
    )
    return created["id"]


def compute_engagement(record: dict) -> None:
    """engagement / engagement_rate が未設定なら算出して record を補完する（in-place）。"""
    if record.get("engagement") is None:
        parts = [
            record.get("likes"),
            record.get("comments"),
            record.get("saved"),
            record.get("shares"),
        ]
        vals = [p for p in parts if p is not None]
        if vals:
            record["engagement"] = sum(vals)

    if record.get("engagement_rate") is None:
        eng = record.get("engagement")
        imp = record.get("impressions") or record.get("reach")
        if eng is not None and imp:
            record["engagement_rate"] = round(eng / imp * 100, 2)
