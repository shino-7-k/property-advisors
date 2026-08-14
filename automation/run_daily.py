#!/usr/bin/env python3
"""プロパティアドバイザーズ 自動X投稿システム — 日次オーケストレーター。

毎日1回、以下を自動で行う:
  1. JST基準で今日の日付・曜日を確定
  2. 曜日別テーマを決定（automation/brand_framework.md の設計フレームに従う）
  3. Anthropic API で投稿文を生成（暴露×数字のトーン、140〜300字）
  4. 生成物を automation/posts/<日付>.md に保存
  5. スプレッドシート記録用の1行を automation/posts/log.csv に追記
  6. X の認証情報が揃っていれば X へ自動投稿（無ければ生成＋ログまでで正常終了）

環境変数:
  ANTHROPIC_API_KEY   (必須) 投稿文生成に使用
  ANTHROPIC_MODEL     (任意) 既定 claude-sonnet-5
  POST_DATE           (任意) YYYY-MM-DD。テスト用に日付を固定する場合に指定
  DRY_RUN             (任意) "1" のとき X 投稿を行わず生成＋ログのみ

  X への自動投稿を行う場合は以下4つをすべて設定（OAuth 1.0a User Context）:
  X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parent
FRAMEWORK_PATH = ROOT / "brand_framework.md"
POSTS_DIR = ROOT / "posts"
LOG_PATH = POSTS_DIR / "log.csv"

# 曜日(月=0 … 日=6) -> (テーマ名, 生成方針)
WEEKDAY_THEME = {
    0: ("暴露", "元営業だから知る営業トーク・裏側を1つ暴露する。"),
    1: ("数字", "利回り・実質利回り・コストのいずれかを数字で淡々と解説する。"),
    2: ("注意", "危ない物件、または不誠実な営業の見分け方を1つ示す。"),
    3: ("暴露", "営業の設計・成約の裏側を暴露する（月曜とは別ネタ）。"),
    4: ("数字", "空室・家賃下落・出口（売却）の数字のいずれかを解説する。"),
    5: ("スタンス", "投資そのものは否定せず「選び方が大事」というスタンスを示す。"),
    6: ("note告知", "その週のnoteの要点を1〜2行にまとめ、リンクを添えて告知する。"),
}
WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def today_jst() -> dt.date:
    override = os.environ.get("POST_DATE", "").strip()
    if override:
        return dt.date.fromisoformat(override)
    return dt.datetime.now(JST).date()


def build_prompts(date: dt.date) -> tuple[str, str]:
    """(system, user) プロンプトを組み立てる。"""
    framework = FRAMEWORK_PATH.read_text(encoding="utf-8")
    weekday = date.weekday()
    theme_name, direction = WEEKDAY_THEME[weekday]
    weekday_jp = WEEKDAY_JP[weekday]

    system = (
        "あなたは不動産紹介業「プロパティアドバイザーズ」の中の人として、"
        "X（旧Twitter）の投稿文を1本書くコピーライターです。"
        "以下のブランド設計フレームに厳密に従ってください。\n\n" + framework
    )

    if theme_name == "note告知":
        task = (
            f"今日は {date.isoformat()}（{weekday_jp}曜日）。日曜のnote告知フォーマットで1本作ります。\n"
            "自動実行のためnoteのタイトル・URLは不明です。本文中でプレースホルダー "
            "`[note タイトル]` と `[note URL]` を必ず使い、後で人が差し替える前提で書いてください。\n"
            "その週のnoteの要点を1〜2行にまとめ、リンク（プレースホルダー）を添えた告知にします。"
        )
    else:
        task = (
            f"今日は {date.isoformat()}（{weekday_jp}曜日）。今日のテーマは「{theme_name}」です。\n"
            f"方針: {direction}\n"
            "「5. 投稿文の型」（フック→展開→気づき/結論→任意でスタンス）に沿って、"
            "140〜300字で1本書いてください。具体的な数字か実体験を必ず1つ入れ、"
            "特定物件の紹介はしないこと。日曜以外なのでリンクは貼らないこと。"
        )

    user = (
        task
        + "\n\n出力は必ず次のJSONオブジェクトのみ（前後に説明文やコードフェンスを付けない）:\n"
        '{\n'
        '  "post": "投稿本文（改行は\\nで表現、そのままXに貼れる形）",\n'
        '  "aim": "この投稿のターゲット・狙いを1〜2行で",\n'
        '  "needs_manual": true/false （noteタイトル/URL等の手動差し替えが必要ならtrue）\n'
        '}'
    )
    return system, user


def generate_post(system: str, user: str) -> dict:
    try:
        import anthropic
    except ImportError:
        sys.exit("anthropic パッケージが必要です。`pip install anthropic` を実行してください。")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY が未設定です。投稿文を生成できません。")

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5").strip()
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    return parse_json(text)


def parse_json(text: str) -> dict:
    """モデル出力からJSONを取り出す。コードフェンスが付いていても許容する。"""
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        sys.exit(f"生成結果からJSONを取得できませんでした:\n{text}")
    data = json.loads(text[start : end + 1])
    if "post" not in data or not str(data["post"]).strip():
        sys.exit(f"生成結果に post が含まれていません:\n{text}")
    data.setdefault("aim", "")
    data.setdefault("needs_manual", False)
    return data


def save_markdown(date: dt.date, theme_name: str, data: dict, tweet_url: str | None) -> Path:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    weekday_jp = WEEKDAY_JP[date.weekday()]
    path = POSTS_DIR / f"{date.isoformat()}.md"
    lines = [
        f"# {date.isoformat()}（{weekday_jp}）テーマ: {theme_name}",
        "",
        "## 投稿文",
        "",
        "```",
        str(data["post"]).replace("\\n", "\n"),
        "```",
        "",
        "## この投稿の狙い",
        "",
        str(data.get("aim", "")).strip() or "（なし）",
    ]
    if data.get("needs_manual"):
        lines += ["", "> ⚠️ 手動差し替えが必要（note タイトル/URL 等）。X投稿は自動スキップされます。"]
    if tweet_url:
        lines += ["", f"## 投稿結果", "", f"X に投稿済み: {tweet_url}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append_log(date: dt.date, theme_name: str, data: dict, status: str, tweet_url: str | None) -> None:
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    new_file = not LOG_PATH.exists()
    head20 = str(data["post"]).replace("\\n", "").replace("\n", "")[:20]
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(
                ["日付", "媒体", "曜日", "テーマ", "投稿冒頭(20字)", "状態", "URL", "いいね", "インプ"]
            )
        w.writerow(
            [
                date.isoformat(),
                "X",
                WEEKDAY_JP[date.weekday()],
                theme_name,
                head20,
                status,
                tweet_url or "",
                "",
                "",
            ]
        )


def maybe_post_to_x(text: str) -> tuple[str, str | None]:
    """Xへ投稿。認証情報が無い/DRY_RUN/手動差し替え要 の場合はスキップ。"""
    if os.environ.get("DRY_RUN", "").strip() == "1":
        return "生成のみ(DRY_RUN)", None

    creds = {
        "consumer_key": os.environ.get("X_API_KEY", "").strip(),
        "consumer_secret": os.environ.get("X_API_SECRET", "").strip(),
        "access_token": os.environ.get("X_ACCESS_TOKEN", "").strip(),
        "access_token_secret": os.environ.get("X_ACCESS_TOKEN_SECRET", "").strip(),
    }
    if not all(creds.values()):
        return "生成のみ(Xキー未設定)", None

    from post_to_x import post_tweet  # 同ディレクトリ

    tweet_id = post_tweet(text, creds)
    return "投稿済み", f"https://x.com/i/web/status/{tweet_id}"


def main() -> None:
    date = today_jst()
    theme_name, _ = WEEKDAY_THEME[date.weekday()]
    print(f"[run_daily] {date.isoformat()}（{WEEKDAY_JP[date.weekday()]}）テーマ: {theme_name}")

    system, user = build_prompts(date)
    data = generate_post(system, user)
    post_text = str(data["post"]).replace("\\n", "\n")

    if data.get("needs_manual"):
        status, tweet_url = "要手動差し替え(X未投稿)", None
        print("[run_daily] 手動差し替えが必要なため X 投稿はスキップします。")
    else:
        status, tweet_url = maybe_post_to_x(post_text)

    md_path = save_markdown(date, theme_name, data, tweet_url)
    append_log(date, theme_name, data, status, tweet_url)

    print(f"[run_daily] 状態: {status}")
    print(f"[run_daily] 保存: {md_path.relative_to(ROOT.parent)}")
    print("----- 投稿文 -----")
    print(post_text)
    print("------------------")


if __name__ == "__main__":
    main()
