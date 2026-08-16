"""X（旧Twitter）アナリティクスからエクスポートしたCSVを読み込み、Notionに記録する。

Xの投稿数値は公式APIが有料のため、標準アナリティクス画面からCSVをダウンロードし、
このスクリプトで取り込む運用を想定（ダウンロード作業だけ手動、入力は自動）。

CSVのヘッダー名はエクスポート元・言語設定で変わるため、列マッピングを
x_column_map.json（無ければ既定マップ）で吸収する。実際のCSVの1行目（ヘッダー）を
見て、必要に応じてマッピングを調整すること。

必要な環境変数:
  NOTION_TOKEN
  NOTION_DATABASE_ID

実行:
  python3 import_x_csv.py <path-to-export.csv> [--fetch-date YYYY-MM-DD] [--map x_column_map.json]

--fetch-date を省略した場合は本日を「取得日」として記録する。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os

import notion_client

# CSVヘッダー -> 内部キー の既定マッピング（英語/日本語の代表的な列名を網羅）
DEFAULT_MAP = {
    # 識別・本文
    "Post id": "post_id",
    "Tweet id": "post_id",
    "投稿ID": "post_id",
    "Post text": "content",
    "Tweet text": "content",
    "投稿本文": "content",
    "ポスト本文": "content",
    "Post link": "url",
    "パーマリンク": "url",
    "time": "post_date",
    "Date": "post_date",
    "日付": "post_date",
    "時刻": "post_date",
    # 指標
    "Impressions": "impressions",
    "インプレッション": "impressions",
    "表示回数": "impressions",
    "Likes": "likes",
    "いいね": "likes",
    "Replies": "comments",
    "返信": "comments",
    "Reposts": "shares",
    "Retweets": "shares",
    "リポスト": "shares",
    "リツイート": "shares",
    "Profile visits": "profile_visits",
    "プロフィールへのアクセス": "profile_visits",
    "Url clicks": "link_clicks",
    "URLクリック数": "link_clicks",
    "リンクのクリック数": "link_clicks",
    "Engagements": "engagement",
    "エンゲージメント": "engagement",
    "Engagement rate": "engagement_rate",
    "エンゲージメント率": "engagement_rate",
}

NUMERIC_KEYS = {
    "impressions", "reach", "likes", "comments", "saved",
    "shares", "profile_visits", "link_clicks", "engagement", "engagement_rate",
}


def load_map(path: str | None) -> dict:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user_map = json.load(f)
        merged = dict(DEFAULT_MAP)
        merged.update(user_map)
        return merged
    return DEFAULT_MAP


def parse_number(raw: str):
    if raw is None:
        return None
    s = raw.strip().replace(",", "").replace("%", "")
    if s == "" or s == "-":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_date(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    # よくある形式を順に試す
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw[:19], fmt).date().isoformat()
        except ValueError:
            continue
    # ISO先頭10文字にフォールバック
    return raw[:10] if len(raw) >= 10 else None


def row_to_record(row: dict, colmap: dict, fetch_date: str) -> dict:
    record: dict = {"platform": "X", "fetch_date": fetch_date}
    for header, value in row.items():
        key = colmap.get(header.strip() if header else header)
        if not key:
            continue
        if key in NUMERIC_KEYS:
            record[key] = parse_number(value)
        elif key == "post_date":
            record[key] = normalize_date(value)
        else:
            record[key] = value.strip() if isinstance(value, str) else value

    content = (record.get("content") or "").replace("\n", " ")
    record["title"] = f"{fetch_date} | X | {content[:40]}"
    if not record.get("post_id"):
        # 投稿IDが無い場合は URL か 本文先頭で代替キーを作る
        record["post_id"] = record.get("url") or content[:60] or "unknown"

    notion_client.compute_engagement(record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description="X アナリティクスCSVをNotionに取り込む")
    parser.add_argument("csv_path", help="XからエクスポートしたCSVファイルのパス")
    parser.add_argument("--fetch-date", default=dt.date.today().isoformat(),
                        help="取得日 (YYYY-MM-DD)。既定は本日")
    parser.add_argument("--map", default="x_column_map.json",
                        help="列マッピングJSONのパス（無ければ既定マップを使用）")
    args = parser.parse_args()

    colmap = load_map(args.map)

    if not os.path.exists(args.csv_path):
        raise SystemExit(f"CSVが見つかりません: {args.csv_path}")

    ok = 0
    with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            record = row_to_record(row, colmap, args.fetch_date)
            if not any(record.get(k) is not None for k in NUMERIC_KEYS):
                continue  # 数値が1つも無い行はスキップ
            notion_client.upsert_record(record)
            ok += 1
            print(f"  ✓ {record.get('post_id')}  imp={record.get('impressions')} eng={record.get('engagement')}")

    print(f"完了: {ok} 行をNotionに記録しました（取得日 {args.fetch_date}）。")


if __name__ == "__main__":
    main()
