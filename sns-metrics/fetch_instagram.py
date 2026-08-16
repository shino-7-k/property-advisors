"""Instagram の投稿インサイトを Instagram Graph API から取得し、Notionに日次で記録する。

前提:
  - Instagramアカウントが「プロアカウント（ビジネス/クリエイター）」であること
  - Facebookページと連携していること
  - Meta（Facebook）アプリを作成し、長期アクセストークンを発行していること
  - そのトークンで対象IGビジネスアカウントIDにアクセスできること

必要な環境変数:
  IG_ACCESS_TOKEN     長期アクセストークン
  IG_USER_ID          IGビジネスアカウントID（数値ID）
  NOTION_TOKEN        Notionインテグレーショントークン
  NOTION_DATABASE_ID  記録先DBのID
  IG_MAX_POSTS        （任意）取得対象の最新投稿数。既定 25
  IG_GRAPH_VERSION    （任意）Graph APIバージョン。既定 v21.0

実行:
  python3 fetch_instagram.py

このスクリプトは「実行した日付（取得日）× 投稿」で1行を作成/更新するため、
毎日実行すると数値の推移が時系列で蓄積されていく。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import notion_client

GRAPH_VERSION = os.environ.get("IG_GRAPH_VERSION", "v21.0")
GRAPH_API = f"https://graph.facebook.com/{GRAPH_VERSION}"

# 取得を試みるインサイト指標（メディア種別やAPIバージョンで使えない場合は自動スキップ）
# 参考: reach / views は現行API、impressions は一部で非推奨のため両方試す。
INSIGHT_METRICS = [
    "impressions",
    "reach",
    "saved",
    "likes",
    "comments",
    "shares",
    "profile_visits",
    "profile_activity",
    "total_interactions",
    "views",
]


def _get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(f"{url}?{query}", timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"_error": {"code": e.code, "body": body}}


def fetch_media_list(token: str, ig_user_id: str, limit: int) -> list[dict]:
    res = _get(
        f"{GRAPH_API}/{ig_user_id}/media",
        {
            "fields": "id,caption,permalink,timestamp,media_type,like_count,comments_count",
            "limit": str(limit),
            "access_token": token,
        },
    )
    if "_error" in res:
        raise SystemExit(f"メディア一覧の取得に失敗: {res['_error']}")
    return res.get("data", [])


def fetch_media_insights(token: str, media_id: str) -> dict:
    """指標名 -> 値 の辞書を返す。使えない指標はスキップ。"""
    values: dict[str, float] = {}
    # まとめて要求し、エラーになったら1個ずつ試す（メディア種別で対応指標が違うため）
    res = _get(
        f"{GRAPH_API}/{media_id}/insights",
        {"metric": ",".join(INSIGHT_METRICS), "access_token": token},
    )
    data = res.get("data")
    if data is None:
        for metric in INSIGHT_METRICS:
            single = _get(
                f"{GRAPH_API}/{media_id}/insights",
                {"metric": metric, "access_token": token},
            )
            for item in single.get("data", []) or []:
                _extract_metric(item, values)
        return values

    for item in data:
        _extract_metric(item, values)
    return values


def _extract_metric(item: dict, values: dict) -> None:
    name = item.get("name")
    vals = item.get("values") or []
    if name and vals:
        values[name] = vals[0].get("value")


def to_record(media: dict, insights: dict, fetch_date: str) -> dict:
    caption = media.get("caption") or ""
    post_date = None
    ts = media.get("timestamp")
    if ts:
        post_date = ts[:10]  # ISO文字列の先頭10文字 = YYYY-MM-DD

    impressions = insights.get("impressions")
    if impressions is None:
        impressions = insights.get("views")  # 現行APIでの代替

    record = {
        "platform": "Instagram",
        "post_id": media.get("id"),
        "fetch_date": fetch_date,
        "post_date": post_date,
        "content": caption,
        "url": media.get("permalink"),
        "title": f"{fetch_date} | Instagram | {caption[:40].replace(chr(10), ' ')}",
        "impressions": impressions,
        "reach": insights.get("reach"),
        "likes": insights.get("likes") if insights.get("likes") is not None else media.get("like_count"),
        "comments": insights.get("comments") if insights.get("comments") is not None else media.get("comments_count"),
        "saved": insights.get("saved"),
        "shares": insights.get("shares"),
        "profile_visits": insights.get("profile_visits"),
        "engagement": insights.get("total_interactions"),
    }
    notion_client.compute_engagement(record)
    return record


def main() -> None:
    token = os.environ.get("IG_ACCESS_TOKEN")
    ig_user_id = os.environ.get("IG_USER_ID")
    if not token or not ig_user_id:
        raise SystemExit("IG_ACCESS_TOKEN と IG_USER_ID を環境変数に設定してください。")

    limit = int(os.environ.get("IG_MAX_POSTS", "25"))
    fetch_date = dt.date.today().isoformat()

    media_list = fetch_media_list(token, ig_user_id, limit)
    print(f"取得対象メディア: {len(media_list)} 件（取得日 {fetch_date}）")

    ok = 0
    for media in media_list:
        insights = fetch_media_insights(token, media["id"])
        record = to_record(media, insights, fetch_date)
        notion_client.upsert_record(record)
        ok += 1
        print(f"  ✓ {media.get('id')}  imp={record.get('impressions')} eng={record.get('engagement')}")

    print(f"完了: {ok} 件をNotionに記録しました。")


if __name__ == "__main__":
    main()
