# SNS投稿メトリクス自動記録（プロパティアドバイザーズ）

X・Instagram などの投稿インプレッション／エンゲージメントを、**毎回手入力せず**に
Notionへ日次で蓄積するための仕組みです。数値は日々変わるため、**「取得日 × 投稿」で
1行**を作り、毎日実行することで推移を時系列で記録します。

- **Instagram** … Instagram Graph API から**自動取得**（無料）
- **X（旧Twitter）** … 公式APIが有料のため、標準アナリティクスの**CSVを取り込み**

記録先Notion DB: **「SNS投稿メトリクス（プロパティアドバイザーズ）」**（shingo.soccer713 ワークスペース）
`https://app.notion.com/p/611cc18feb1743f89eb739845cbc6a74`

---

## 全体像

```
[毎日 定時実行]
  ├─ Instagram: fetch_instagram.py  → Graph APIから取得 → Notionへupsert
  └─ X:         import_x_csv.py      → DLしたCSVを取込   → Notionへupsert
                                   ↓
                Notion DB（取得日×投稿で時系列蓄積 → グラフ/集計）
```

同じ「投稿ID × 取得日」の行があれば**更新**、無ければ**新規作成**（upsert）するので、
1日に複数回実行しても行が重複しません。

---

## 1. 事前準備（共通：Notion）

1. https://www.notion.so/my-integrations で **内部インテグレーション**を作成し、
   **Internal Integration Token**（`secret_...` または `ntn_...`）を取得。
2. 対象DBページを開き、右上「•••」→「コネクト」→ 作成したインテグレーションを追加して
   **DBを共有**（これを忘れるとAPIが403になります）。
3. 環境変数を設定（`.env.example` をコピーして `.env` を作成）。
   - `NOTION_TOKEN` … 上記トークン
   - `NOTION_DATABASE_ID` … `611cc18feb1743f89eb739845cbc6a74`

> 追加ライブラリのインストールは不要です（Python標準ライブラリのみで動作）。Python 3.9+。

---

## 2. Instagram（自動取得）のセットアップ

**前提**：IGアカウントが「プロアカウント（ビジネス/クリエイター）」で、Facebookページと
連携済みであること。

1. [Meta for Developers](https://developers.facebook.com/) でアプリを作成。
2. 「Instagram Graph API」を有効化し、権限
   `instagram_basic` / `instagram_manage_insights` / `pages_read_engagement` を付与。
3. **長期アクセストークン**（Long-Lived Token、約60日有効）を発行。
4. **IGビジネスアカウントID**（数値）を取得
   （例：`GET /me/accounts` → ページ → `instagram_business_account`）。
5. 環境変数に設定：
   - `IG_ACCESS_TOKEN`
   - `IG_USER_ID`

実行：

```bash
cd sns-metrics
python3 fetch_instagram.py
```

> トークンは約60日で失効します。定期的な更新、または長期トークンの自動リフレッシュ運用を
> 推奨します（`GET /refresh_access_token`）。

---

## 3. X（CSV取込）の運用

Xは公式APIが有料のため、標準アナリティクスからCSVをダウンロードして取り込みます。

1. Xの **アナリティクス** 画面で対象期間のポストデータを **CSVエクスポート**。
2. 取り込み：

```bash
cd sns-metrics
python3 import_x_csv.py /path/to/export.csv
# 取得日を指定したい場合:
python3 import_x_csv.py /path/to/export.csv --fetch-date 2026-08-16
```

### 列名が合わない場合

CSVのヘッダー名はエクスポート元・言語で変わります。`x_column_map.example.json` を
`x_column_map.json` にコピーし、実際のCSVの1行目に合わせて
「CSVの列名 → 内部キー」を追記してください（既定マップとマージされます）。

内部キー：`post_id, content, url, post_date, impressions, reach, likes, comments,
saved, shares, profile_visits, link_clicks, engagement, engagement_rate`

> `engagement` / `engagement_rate` はCSVに無くても、いいね等から自動計算します。

---

## 4. 毎日自動で走らせる方法

### 方法A：サーバ/PCの cron（Instagram完全自動）

```cron
# 毎朝9時にInstagramを取得（.envを読み込んでから実行）
0 9 * * *  cd /path/to/property-advisors/sns-metrics && set -a && . ./.env && set +a && python3 fetch_instagram.py >> ig.log 2>&1
```

### 方法B：Claude Code のスケジュール実行

このセッション環境に認証情報（環境変数）を設定すれば、定期トリガーで
`fetch_instagram.py` を毎日自動実行させることも可能です（別途設定）。

### X（CSV）について

CSVのダウンロードだけは手動になります（Xの仕様上）。完全自動にするには
X APIの有料プラン（Basic $200/月〜）契約が必要です。運用としては
「週1回まとめてCSVを取り込む」でも推移は十分追えます。

---

## 5. Notion DB の構造

| プロパティ | 型 | 内容 |
|---|---|---|
| 名称 | タイトル | `取得日 \| 媒体 \| 本文冒頭` |
| 取得日 | 日付 | その数値を取得した日（時系列の軸） |
| プラットフォーム | セレクト | Instagram / X / YouTube / TikTok / Facebook |
| 投稿ID | テキスト | 各媒体の投稿ID（重複判定キー） |
| 投稿日 | 日付 | 投稿された日 |
| 投稿内容 | テキスト | 本文・キャプション |
| URL | URL | 投稿への直リンク |
| インプレッション / リーチ / いいね / コメント / 保存 / シェア・リポスト / プロフィールアクセス / リンククリック / エンゲージメント | 数値 | 各指標 |
| エンゲージメント率(%) | 数値 | 自動算出（エンゲージメント ÷ インプレッション × 100） |

> DBには動作確認用の「【サンプル・削除可】」行が1件入っています。不要なら削除してください。

### おすすめの見せ方

- Notionの**ビュー**で「プラットフォームでグループ化」「取得日で降順ソート」。
- **リンクドビュー＋グラフ**（Notionのチャート）で、取得日ごとのインプレッション推移を可視化。
- 「投稿IDでフィルタ」すれば、特定投稿の数値がどう伸びたかを日次で追えます。

---

## 6. トラブルシュート

| 症状 | 原因 / 対処 |
|---|---|
| Notion 403 / object_not_found | DBをインテグレーションに**共有**していない |
| Notion 401 | `NOTION_TOKEN` が誤り／失効 |
| IGで指標が空 | メディア種別で対応指標が異なる（自動スキップ）。`impressions`非対応時は`views`で代替 |
| IG 190 (OAuthException) | アクセストークン失効。長期トークンを再発行 |
| X CSVで数値が入らない | 列名不一致。`x_column_map.json` を実CSVに合わせて調整 |
