# 自動X投稿システム（プロパティアドバイザーズ）

毎朝、曜日別テーマに沿って X の投稿文を**自律的に生成・記録**し、認証情報が揃っていれば
**X へ自動投稿**する仕組みです。GitHub Actions のスケジュール実行で、このリポジトリ自身の中で動きます。

## 動作の流れ（毎朝 8:00 JST）

```
GitHub Actions (cron)
  → JST基準で今日の曜日を判定
  → brand_framework.md の設計フレームで投稿文を生成（Anthropic API）
  → automation/posts/<日付>.md に保存 ＆ posts/log.csv に1行追記
  → X のキーがあれば X へ投稿（無ければ「生成＋ログ」まで）
  → 生成物を自動コミット
```

## 構成

| ファイル | 役割 |
|---|---|
| `.github/workflows/daily-x-post.yml` | 毎朝の定時実行（cron `0 23 * * *` = 08:00 JST）＋手動実行 |
| `run_daily.py` | オーケストレーター（生成→保存→ログ→投稿） |
| `post_to_x.py` | X API v2 への投稿（OAuth 1.0a） |
| `brand_framework.md` | ブランド設計フレーム。**ここを編集すればトーン・方針を調整できます** |
| `posts/<日付>.md` | 自動生成された各日の投稿（実行時に作成） |
| `posts/log.csv` | スプレッドシート記録用ログ（実行時に作成） |

## 曜日別テーマ

月:暴露 / 火:数字 / 水:注意 / 木:暴露 / 金:数字 / 土:スタンス / 日:note告知

日曜は note 告知フォーマット。note タイトル/URL は自動では分からないため、プレースホルダー
`[note タイトル]` `[note URL]` で生成し、**X 投稿は自動スキップ**（要手動差し替え）します。

## セットアップ（GitHub 側の設定）

リポジトリの **Settings → Secrets and variables → Actions** で以下を登録します。

### 必須（投稿文の生成）
- `ANTHROPIC_API_KEY` … Anthropic API キー（Secret）

### 任意
- `ANTHROPIC_MODEL` … 使用モデル（Variable。既定 `claude-sonnet-5`）

### X へ自動投稿する場合（4つすべて Secret に登録）
- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

> X のキーは X Developer Portal（Read and Write 権限の App）で取得します。
> 4つが揃っていない間は、システムは**生成とログ記録のみ**を安全に続けます。

## 手動で試す

GitHub の **Actions → 「自動X投稿（毎朝）」→ Run workflow** から実行できます。
`dry_run`（既定ON）で X 投稿せず生成のみ、`post_date` で対象日を固定できます。

ローカルでの動作確認:

```bash
cd automation
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
DRY_RUN=1 POST_DATE=2026-08-14 python run_daily.py
```

## 運用メモ

- 投稿文のトーンや曜日方針を変えたいときは `brand_framework.md` と `run_daily.py` の
  `WEEKDAY_THEME` を編集してください。
- 生成物（`posts/`）は毎回自動コミットされるので、過去の投稿履歴がそのまま資産になります。
- いいね・インプレッション数の欄は空で記録されます。手元で数値を追記する運用を想定しています。
