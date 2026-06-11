# 📊 東方非想天則 戦績管理BOT (Tensoku Match Stats Bot)

東方非想天則の対戦結果（戦績）をDiscord上で手軽に記録・集計するための Discord Bot です。
勝率や使用キャラクターごとの統計、サーバー内のリーダーボード（ランキング）機能を提供します。

---

## 🌟 主な機能とコマンド（スラッシュコマンド）

すべての主要機能は Discord の **スラッシュコマンド（`/`）** に対応しており、入力補完（オートコンプリート）を使って素早く入力できます。

### 1. 戦績の登録 (`/report`)
対戦結果をデータベースに登録します。
- **コマンド**: `/report opponent: [ユーザー] my_score: [勝利本数] opponent_score: [相手勝利本数] [my_char]: [自分のキャラ] [opponent_char]: [相手のキャラ]`
- **オプション**: 使用キャラクターは、入力時に非想天則の全20キャラからオートコンプリート選択が可能です。
- **結果**: どちらが勝ったかを示す結果カード（Embed）が送信されます。

### 2. 登録した戦績の削除 (`/delete_match`)
間違えて登録してしまった戦績を削除します。
- **コマンド**: `/delete_match match_id: [対戦ID]`
- **権限**: 報告者本人、またはサーバー管理者のみ削除可能です。

### 3. 個人戦績スタッツ表示 (`/stats`)
自分または他のプレイヤーの戦績データをグラフィカルな Embed で表示します。
- **コマンド**: `/stats [user: ユーザー(任意)]`
- **表示項目**:
  - 総合戦績（総対戦数、勝敗数、勝率、勝率に応じたビジュアルバー `🟢/🔴`）
  - 使用キャラ TOP3（対戦数、勝敗、勝率）
  - よく戦う相手 TOP3（対戦数、勝敗、勝率）
  - 直近の対戦履歴（最大5件）

### 4. サーバーリーダーボード表示 (`/leaderboard`)
サーバー内のプレイヤーの戦績ランキングを表示します。
- **コマンド**: `/leaderboard [min_matches: 最低必要対戦数(任意)]`
- **ソート**: 勝率でソートされ、勝率が同率の場合は勝利数の多い順になります。

---

## 🛠️ 管理者（オーナー）専用コマンド

プレフィックス（デフォルト `/` または `!`）を使用して実行する、Botのオーナー専用コマンドです。

- **`!sync`**: スラッシュコマンドをDiscordサーバーに同期します。Botを導入した後、一番最初に一度だけ実行してください。
- **`!bot_status`**: 接続サーバー数、レイテンシ、稼働中のモジュールの一覧を表示します。

---

## 🚀 導入・セットアップ方法

### 1. 前提要件
- Python 3.8 以上
- SQLite3 (Python標準搭載)
- Discord Bot アカウント（Message Content Intent および Server Members Intent を有効にしてください）

### 2. インストール
必要なパッケージをインストールします。
```bash
pip install -r requirements.txt
```

### 3. 環境設定
`env.example` をコピーして `.env` ファイルを作成し、Botのトークンを記述します。
```env
DISCORD_TOKEN=ここにDiscord_Botのトークンを記入
BOT_PREFIX=!
DB_PATH=data/tensoku_stats.db
```

### 4. 起動
```bash
python main.py
```
起動すると、自動的に `data/` ディレクトリ配下に `tensoku_stats.db` が作成され、テーブルが初期化されます。
起動後、Discord上でBotのオーナーアカウントから `!sync` を送信し、スラッシュコマンドを同期させてください。

---

## 📂 フォルダ構成

```text
tensoku_match_bot/
├── cogs/
│   ├── report_cog.py   # 戦績の登録と削除 (/report, /delete_match)
│   └── stats_cog.py    # スタッツとランキング表示 (/stats, /leaderboard)
├── database/
│   └── db_manager.py   # SQLiteデータベース操作・集計ロジック
├── config.py           # 環境設定の読み込み
├── main.py             # Botのエントリーポイント
├── requirements.txt    # 依存ライブラリ
├── .env                # 設定値ファイル (作成が必要)
└── README.md           # このファイル
```
