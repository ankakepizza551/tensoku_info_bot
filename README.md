# 天則インフォメーション管理BOT

東方非想天則の対戦コミュニティ「天則コソ練広場」で動いている Discord Bot です。
レーティング対戦、対戦募集、レイドバトル、陣取り戦、戦績管理、投稿・アンケート・お便りなど、サーバー運営に必要な機能をまとめています。

**ユーザーの操作は、チャンネルに設置された「パネル」のボタンが中心です。** スラッシュコマンドは、ボタンと同じ操作をコマンドで呼び出す手段、または管理者が設定・運営するための手段として用意されています。

紹介ページ: https://kosoren-site.kentatoonimusya.workers.dev/

---

## 目次

- [機能の全体像](#機能の全体像)
- [対戦](#対戦)
  - [有頂天の塔（レーティングマッチ）](#有頂天の塔レーティングマッチ)
  - [対戦募集（フォーラム）](#対戦募集フォーラム)
  - [対戦募集（メッセージ式）](#対戦募集メッセージ式)
  - [戦績の登録・スタッツ・ランキング](#戦績の登録スタッツランキング)
- [企画](#企画)
  - [レイドバトル](#レイドバトル)
  - [陣取り戦](#陣取り戦)
- [交流・投稿](#交流投稿)
  - [メインキャラ登録と分布](#メインキャラ登録と分布)
  - [記事投稿（フォーラム）](#記事投稿フォーラム)
  - [簡易投稿・Embedビルダー](#簡易投稿embedビルダー)
  - [投票・アンケート](#投票アンケート)
  - [お便り](#お便り)
- [イベント・その他](#イベントその他)
- [ランク一覧](#ランク一覧)
- [管理者向けコマンド一覧](#管理者向けコマンド一覧)
- [セットアップ](#セットアップ)
- [フォルダ構成](#フォルダ構成)

---

## 機能の全体像

| 機能 | ユーザーの主な操作 | 主なコマンド |
|---|---|---|
| 有頂天の塔 | パネルのボタン | `/rating_queue_join` `/rating_stats` |
| 対戦募集（フォーラム） | パネルのボタン | `/recruit_register` |
| 対戦募集（メッセージ式） | コマンド → ボタン | `/recruit` |
| 戦績・スタッツ | コマンド | `/report` `/stats` `/leaderboard` |
| 月間MVP | 毎月1日に自動投稿 | `/mvp` `/mvp_setup` |
| レイドバトル | パネルのボタン | （管理者用のみ） |
| 陣取り戦 | パネルのボタン | `/territory_register` `/territory_report` ほか |
| メインキャラ | パネルのボタン | `/main_char` `/main_char_list` |
| 記事投稿 | パネルのボタン | （管理者用のみ） |
| 簡易投稿 | コマンド → モーダル | `/post` `/forum_post` `/embed_builder` |
| 投票・アンケート | ボタン | `/poll` `/survey` |
| お便り | パネルのボタン | `/tegami` |
| イベントカレンダー | パネルのボタン | `/add_event` `/remove_event` |
| リマインダー | コマンド | `/set_reminder` |

---

## 対戦

### 有頂天の塔（レーティングマッチ）

希望するレート差を決めてキューに入ると、お互いの希望範囲に収まる相手と自動でマッチングします。対戦のたびにレートとランク（[全9段階](#ランク一覧)）が更新され、ランクのロールも自動で付与されます。

**操作パネルのボタン**（`/setup_rating_panel` で設置）

| ボタン | 動作 |
|---|---|
| 📝 プロフィール登録/変更 | 1戦目のキャラ、IP/接続情報、オートパンチ有無、giuroll有無、コメントを登録 |
| ⚔️ キューに参加 | 希望する最大レート差をドロップダウンで選んでキューに参加 |
| 🚪 キューから抜ける | キューから離脱 |
| 📋 待機状況を見る | 現在の待機者を表示 |
| 🎚 希望レート差を設定 | 希望する最大レート差を変更 |
| 🏆 レーティングスタッツ | 自分のレート・ランク・戦績を表示 |

**マッチ成立後の流れ**

1. 対戦用のスレッドが作られ、双方のプロフィールと接続情報が表示されます。
2. 対戦後、どちらかが **📝 結果を報告する** を押し、勝利本数を入力します。
3. 報告後は **🔁 結果を修正する** で修正できます。
4. スレッド内には **📊 自分のスタッツ** と **🗑️ スレッドを削除** のボタンもあります。

**コマンド**

| コマンド | 内容 |
|---|---|
| `/rating_register` | プロフィールの登録・変更 |
| `/rating_stats` | スタッツ表示 |
| `/rating_queue_join` | キューに参加 |
| `/rating_queue_leave` | キューから離脱 |
| `/rating_queue_status` | キューの状況表示 |

管理者用: `/setup_rating_room`（対戦スレッドの投稿先設定）、`/setup_rating_panel`（操作パネル設置）、`/setup_rating_queue_board`（待機人数を常時表示するボードを設置）、`/setup_rank_roles`（ランクロールの作成と既存メンバーへの付与）

### 対戦募集（フォーラム）

フォーラムチャンネルに募集スレッドを立てる方式です。申し込みから結果報告までスレッド内のボタンで進みます。

**募集パネルのボタン**（`/setup_recruit_panel` で設置）

| ボタン | 動作 |
|---|---|
| ⚔️ 対戦を募集する | 募集フォームを開く（タイトル、IP or クラ専、対戦設定、使用キャラ、回数/コメント） |
| 📝 プロフィール登録/変更 | フォームの初期値を登録 |
| 📊 自分のスタッツ | 自分の戦績を表示 |

**募集スレッド内のボタン**

| 状況 | ボタン |
|---|---|
| 受付中 | ⚔️ 対戦を申し込む / 📊 自分のスタッツ / 🚫 募集を終了する / 🗑️ スレッドを削除 |
| 対戦中 | 📝 結果を報告する / 📊 自分のスタッツ / 🗑️ スレッドを削除 |

結果を報告すると、戦績の登録とEloレーティングの計算が自動で行われます。

**コマンド**: `/recruit_register`（フォームの初期値を事前登録）／管理者用 `/setup_recruit_panel` `/remove_recruit_panel`

### 対戦募集（メッセージ式）

チャンネルに募集メッセージを投稿する方式です。

- **コマンド**: `/recruit [comment: 募集コメント] [format: 募集形式]`
- 募集メッセージのボタン: 「対戦を申し込む」「募集キャンセル」「募集を締め切る」「再募集する」
- 対戦成立後は「結果を報告する」から、スコアと使用キャラを入力するモーダルで戦績が登録されます。

### 戦績の登録・スタッツ・ランキング

| コマンド | 内容 |
|---|---|
| `/report` | 対戦結果を登録。双方のEloレーティングが自動更新されます |
| `/delete_match` | 戦績をIDで削除。報告者本人または管理者のみ。レート変動も巻き戻されます |
| `/stats [user]` | レーティング、総合戦績、使用キャラTOP3、よく戦う相手TOP3、直近の対戦を表示 |
| `/leaderboard [min_matches]` | レーティング順のサーバーランキング |

---

## 企画

### レイドバトル

初級者が「対応可能」な上級者に挑む1vs1の企画です。

**パネルのボタン**（`/setup_raid_panel` で設置）

| ボタン | 動作 |
|---|---|
| 🔰 初級者として登録 | 初級者として登録 |
| ⚔️ 上級者として登録 | 上級者として登録 |
| 🔄 対応状況を切り替える（上級者用） | いま対戦を受けられるかどうかを切り替え |

上級者の対応状況は、`/setup_raid_status_board` で設置するボードに常時表示されます。

**管理者用**: `/setup_raid_battle`（カテゴリ・ロール・チャンネルの一括作成）、`/setup_raid_panel`、`/setup_raid_status_board`、`/raid_registered_list`（登録者一覧をコピペ用テキストで出力）、`/raid_cleanup`（終了後の片付けとデータリセット）

### 陣取り戦

参加者がチームに分かれ、1対1の勝敗でチームの陣地を広げていく期間限定の団体戦です。

**登録パネル**（`/setup_territory_register_panel`）と**情報パネル**（`/setup_territory_info_panel`）

| ボタン | 動作 |
|---|---|
| 📝 陣取りゲーム プロフィール登録/変更 | 強さ（1:初級 / 2:中級 / 3:上級）、IP/接続情報、オートパンチ、giuroll、コメントを登録 |
| 👤 自分のプロフィール確認 | 自分の登録内容を表示 |
| 📋 登録者一覧 | 登録済みプロフィールを一覧表示 |
| 🗂️ チーム分け結果 | 現在のチーム分けを表示 |

**対戦パネル**（`/setup_territory_battle_panel`）

| ボタン | 動作 |
|---|---|
| ⚔️ 対戦結果を報告 | 対戦相手を選び、結果を入力 |
| 📊 現在の戦況 | 侵略度・出場状況を表示 |
| 🗑️ 対戦結果を削除 | Match IDを指定して削除 |
| 🗺️ 陣地マップ | 現在の陣地マップを表示 |

**コマンド**: `/territory_register` `/territory_profile` `/territory_list` `/territory_teams` `/territory_map` `/territory_report` `/territory_score` `/territory_match_delete`

**管理者用**: `/territory_setup`（ロール・チャンネル・全パネルを一括セットアップ）、`/territory_draw`（チーム分け抽選）、`/territory_new_round`（周回を進め、全員を再出場可能にする）、`/territory_end`（大会終了と最終結果の発表）、`/territory_cleanup`（終了後の片付けとデータリセット）

#### 配信オーバーレイ（OBS）

陣取りマップを配信画面に映すための、OBSブラウザソース用ページです。Bot本体に組み込まれた軽量Webサーバー（`overlay/server.py`）が提供します。

- **URL**: `https://<Railwayで割り当てた公開ドメイン>/territory?guild_id=<サーバーID>`
- 背景は透過で、一定間隔で自動更新されます。
- **公開設定（初回のみ）**: Railwayダッシュボードでこのサービスの「Settings」→「Networking」から Public Domain を発行してください。
- **アクセス制限（任意）**: `.env` に `TERRITORY_OVERLAY_TOKEN=好きな文字列` を設定すると、URLに `&token=同じ文字列` を付けないと表示されなくなります。

---

## 交流・投稿

### メインキャラ登録と分布

メインキャラを1人だけ登録できます（いつでも変更可）。サーバー内の使用率をゲージつきで見られ、キャラを選ぶとそのキャラの使用者一覧が自分にだけ表示されます。

- **パネルのボタン**（`/main_char_panel` で設置。管理者用）: 「メインキャラを登録・変更」「分布を見る」
- **コマンド**: `/main_char`、`/main_char_list`

### 記事投稿（フォーラム）

見出し・引用・画像を使った記事風の投稿を、フォーラムチャンネルへ作成します。

**パネルのボタン**（`/setup_article_panel` で設置）: 📝 記事を投稿する（投稿先のフォーラムを選択）

**エディタのボタン**

| 行 | ボタン |
|---|---|
| 1 | 📝 タイトル・本文 / 🖼️ 画像 / 🎨 カラー |
| 2 | 𝐁 太字 / 𝐼 斜体 / `C` コード / ❝ 引用 / ＃ 見出し |
| 3 | 📤 フォーラムに投稿 / ❌ キャンセル |

投稿後のスレッドには **✏️ 記事を編集** と **🗑️ スレッドを削除** のボタンが付きます。

管理者用: `/setup_article_panel` `/remove_article_panel`

### 簡易投稿・Embedビルダー

| コマンド | 内容 |
|---|---|
| `/post [color]` | モーダルにタイトル・本文・画像URLを入力して、Embed投稿を作成 |
| `/forum_post channel [color]` | フォーラムの最初の投稿をモーダルから作成 |
| `/embed_builder` | ボタンで項目を組み立て、プレビューを見ながら投稿（タイトル・本文、画像、カラー、フィールド追加/削除、投稿、キャンセル） |
| `/format_help` | Discordの文字装飾チートシートを自分にだけ表示 |

### 投票・アンケート

| コマンド | 内容 |
|---|---|
| `/poll question options [channel]` | ボタン式の複数選択投票。選択肢はカンマ区切りで2〜10個。再度押すと取り消し。結果はバーつきで更新 |
| `/close_poll message_id` | 投票を締め切る（作成者または管理者） |
| `/survey [channel]` | 記述式アンケート。モーダルで最大4問を設定し、参加者はボタンから回答（1人1回） |
| `/close_survey message_id` | アンケートを締め切る（作成者または管理者） |
| `/survey_results message_id` | 個別回答を確認（自分にだけ表示。作成者または管理者） |

### お便り

サーバー運営に届けるお便りです。**匿名**と**名前を出して送る**の両方に対応しています。

- **パネルのボタン**（`/setup_letter_panel` で設置）: 「📨 匿名で送る」「🙋 名前を出して送る」
- **コマンド**: `/tegami [anonymous: 既定はTrue]`
- **入力欄**: タイトルと本文
- 送信先チャンネルは環境変数 `LETTER_ADMIN_CHANNEL_ID` で設定します。
- **管理者用**: `/tegami_check`（お便りの確認）、`/tegami_reply`（返信の投稿）、`/tegami_hide` `/tegami_unhide`（非表示にする/再表示）

---

## イベント・その他

| 機能 | 内容 |
|---|---|
| イベントカレンダー | 月表示のカレンダー。ボタンで前月・今月・翌月を切り替え。パネルの「🟢 オン大会を追加」「🔴 オフ大会を追加」「🗑️ イベントを削除」から、日付・大会名・開始時間・場所・詳細URLを登録・削除できます。コマンド: `/add_event` `/remove_event`。**予定の追加・削除は、サーバー管理権限を持つ人だけ**が行えます（`CALENDAR_EDITOR_ROLE_ID` でロールを追加可）。管理者用: `/calendar_setup` `/setup_event_panel` |
| イベントリマインダー | スレッド内で `/set_reminder` を使うと、指定した日時に通知します。`/list_reminders` で一覧、`/cancel_reminder` で削除 |
| スレッド一覧ボード | `/setup_thread_index` で、指定チャンネルのアクティブなスレッド一覧を自動更新するボードを設置。`/remove_thread_index` で削除 |
| サーバー宣伝 | `/promote` でX（旧Twitter）に投稿するためのボタンを表示。投稿はユーザー自身のXから行われます（`SERVER_INVITE_URL` の設定が必要） |
| ダイス | `/roll 2d6`、`/roll 1d100` など |
| ピザメニュー | `/pizza_panel` でパネルを設置。「メニュー追加」「メニュー削除」「メニューを見る」「ピザを焼く」。コマンド: `/pizza_add` `/pizza_random` `/pizza_list` `/pizza_delete` |

#### 公開サイト向けAPI

紹介サイトに「サーバーの今」を表示するための、読み取り専用の集計APIです（`overlay/public_api.py`）。同じWebサーバー上で動きます。

- **URL**: `GET https://<公開ドメイン>/api/public/stats`
- **返す内容**: 有頂天の塔のランク別人数、メインキャラごとの登録人数。ユーザー名・ID・個別のレートは含みません。
- **キャッシュ**: 60秒
- **カレンダー用**: `GET /api/public/events` は、カレンダーの予定一覧（日付・大会名・種別・時間・場所・URL）を返します。Webのカレンダーはこの予定を読んで表示します。`PUBLIC_GUILD_ID` を設定すると、そのサーバーの予定だけに絞れます。
- **CORS**: 既定は全許可。制限する場合は `PUBLIC_API_ORIGINS=https://kosoren-site.xxx.workers.dev`（カンマ区切り）を設定します。

---

## ランク一覧

有頂天の塔のレーティングに対応する全9段階です（定義は `rating_ranks.py`）。

| ランク | レート | 目安 |
|---|---|---|
| 天人・極 | 2000〜 | 神域・最上位勢（全鯖トップクラス・大会上位常連） |
| 天人・熟 | 1900〜 | 猛者（上位層の中でも頭一つ抜けた存在） |
| 天人・初 | 1800〜 | 上級者の入口（基礎〜応用が完璧に仕上がっている） |
| 妖怪・極 | 1700〜 | 中級上位（メインキャラの強みがかなり出せる） |
| 妖怪・熟 | 1600〜 | 中級中位（勝率が安定し始める） |
| 妖怪・初 | 1500〜 | 中央値〜標準（対戦の基本を理解し実戦に慣れた層） |
| 人間・極 | 1400〜 | 初級上位（脱・初心者を目指す段階） |
| 人間・熟 | 1300〜 | 初級中位（コンボや基本的な立ち回りを練習中） |
| 人間・初 | 〜1299 | 初学者・ビギナー（始めたばかり・復帰勢など） |

---

## 管理者向けコマンド一覧

「パネルを設置する」コマンドは、**実行したチャンネルにパネルを置きます**。ボタンはBotの再起動後も動作し続けます。

### Botオーナー専用（プレフィックスコマンド）

| コマンド | 内容 |
|---|---|
| `sync` | スラッシュコマンドをグローバルに同期（反映まで最大1時間） |
| `sync guild` | 現在のサーバーにだけ即時同期 |
| `db_backup` | データベースのバックアップファイルを送信 |
| `bot_status` | 接続サーバー数、レイテンシ、稼働中のCogを表示 |

### スラッシュコマンド（管理者用）

| 用途 | コマンド |
|---|---|
| 有頂天の塔 | `/setup_rating_room` `/setup_rating_panel` `/setup_rating_queue_board` `/setup_rank_roles` |
| 対戦募集 | `/setup_recruit_panel` `/remove_recruit_panel` |
| レイドバトル | `/setup_raid_battle` `/setup_raid_panel` `/setup_raid_status_board` `/raid_registered_list` `/raid_cleanup` |
| 陣取り戦 | `/territory_setup` `/setup_territory_register_panel` `/setup_territory_info_panel` `/setup_territory_battle_panel` `/territory_draw` `/territory_new_round` `/territory_end` `/territory_cleanup` |
| メインキャラ | `/main_char_panel` |
| 記事投稿 | `/setup_article_panel` `/remove_article_panel` |
| お便り | `/setup_letter_panel` `/tegami_check` `/tegami_reply` `/tegami_hide` `/tegami_unhide` |
| カレンダー | `/calendar_setup` `/setup_event_panel` |
| その他 | `/setup_thread_index` `/remove_thread_index` `/pizza_panel` |

---

## セットアップ

### 1. 前提

- Python 3.10 以上
- Discord Bot アカウント（**Message Content Intent** と **Server Members Intent** を有効にしてください）

### 2. インストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数

`.env` をプロジェクトルートに作成します。

```env
DISCORD_TOKEN=Botのトークン
BOT_PREFIX=!
DB_PATH=data/tensoku_stats.db
LETTER_ADMIN_CHANNEL_ID=お便りの送信先チャンネルID（数字）
SERVER_INVITE_URL=https://discord.gg/xxxxxxxx
TERRITORY_OVERLAY_TOKEN=（任意）配信オーバーレイ用のアクセス制限トークン
```

| 変数 | 内容 |
|---|---|
| `DISCORD_TOKEN` | Botのトークン |
| `BOT_PREFIX` | オーナー用プレフィックスコマンドの接頭辞（未設定時は `/`） |
| `DB_PATH` | SQLiteのパス。未設定時は `data/tensoku_stats.db` |
| `LETTER_ADMIN_CHANNEL_ID` | お便りと確認ログの送信先 |
| `SERVER_INVITE_URL` | `/promote` で使う招待リンク |
| `CALENDAR_EDITOR_ROLE_ID` | （任意）カレンダーの予定を編集できる追加ロールのID。未設定ならサーバー管理権限を持つ人だけ |
| `CALENDAR_WEB_URL` | カレンダーの下に出す「Web版を開く」ボタンのURL。未設定ならWeb版カレンダーのURL、空にするとボタンなし |
| `TERRITORY_OVERLAY_TOKEN` | 配信オーバーレイのアクセス制限（任意） |
| `PORT` | オーバーレイのWebサーバーのポート（未設定時は `8080`） |

### 4. 起動

```bash
python main.py
```

起動するとSQLiteのデータベースが自動作成・初期化されます。起動後、オーナーアカウントから `!sync guild` を送信してスラッシュコマンドを同期してください。

### Railway で運用する場合

- `Procfile` は `worker: python main.py` です。
- `RAILWAY_ENVIRONMENT` が設定されている環境では、データベースを `/app/data` のVolumeに置きます。**Volumeが未マウントだと、データが消えるのを防ぐため起動を止めます。** Railwayの Volumes タブで、マウントパス `/app/data` のVolumeを追加してください。

---

## フォルダ構成

```text
tensoku_info_bot/
├── cogs/
│   ├── rating_room_cog.py    # 有頂天の塔（レーティングマッチ）
│   ├── forum_recruit_cog.py  # 対戦募集（フォーラム）
│   ├── recruit_cog.py        # 対戦募集（メッセージ式）
│   ├── report_cog.py         # 戦績の登録・削除
│   ├── stats_cog.py          # スタッツ・リーダーボード
│   ├── raid_battle_cog.py    # レイドバトル
│   ├── territory_cog.py      # 陣取り戦
│   ├── main_char_cog.py      # メインキャラ登録・分布
│   ├── forum_article_cog.py  # 記事投稿（フォーラム）
│   ├── post_cog.py           # 簡易投稿・Embedビルダー
│   ├── poll_cog.py           # 投票・アンケート
│   ├── letter_cog.py         # お便り
│   ├── calendar_cog.py       # イベントカレンダー
│   ├── event_reminder_cog.py # イベントリマインダー
│   ├── thread_index_cog.py   # スレッド一覧ボード
│   ├── promote_cog.py        # サーバー宣伝
│   ├── dice_cog.py           # ダイス
│   └── pizza_cog.py          # ピザメニュー
├── database/
│   └── db_manager.py         # SQLiteの操作・集計・レーティング計算
├── overlay/
│   └── server.py             # 陣取りマップの配信オーバーレイ
├── rating_ranks.py           # ランク（全9段階）の定義
├── rank_roles.py             # ランクロールの作成・付与
├── config.py                 # 環境設定の読み込み
├── main.py                   # エントリーポイント
├── Procfile                  # Railway 用
└── requirements.txt          # 依存ライブラリ
```
