#!/usr/bin/env python3
"""X (Twitter) API v2 への投稿ヘルパー（OAuth 1.0a User Context）。

`run_daily.py` から呼ばれる。認証情報は環境変数（GitHub Secrets）経由で渡され、
このモジュールにはハードコードしない。
"""
from __future__ import annotations

CREATE_TWEET_URL = "https://api.twitter.com/2/tweets"


def post_tweet(text: str, creds: dict) -> str:
    """1件のツイートを投稿し、作成された tweet id を返す。

    creds には consumer_key / consumer_secret / access_token /
    access_token_secret の4つが必要。
    """
    try:
        import requests
        from requests_oauthlib import OAuth1
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "requests と requests_oauthlib が必要です。"
            "`pip install requests requests_oauthlib` を実行してください。"
        ) from exc

    auth = OAuth1(
        creds["consumer_key"],
        creds["consumer_secret"],
        creds["access_token"],
        creds["access_token_secret"],
    )
    resp = requests.post(CREATE_TWEET_URL, json={"text": text}, auth=auth, timeout=30)
    if resp.status_code not in (200, 201):
        raise SystemExit(f"X 投稿に失敗しました (HTTP {resp.status_code}): {resp.text}")
    return resp.json()["data"]["id"]
