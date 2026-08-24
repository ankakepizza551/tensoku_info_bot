import aiosqlite

from ._common import DB_PATH

__all__ = ["init_db"]


async def init_db():
    """データベースの初期化とマイグレーション"""
    async with aiosqlite.connect(DB_PATH) as db:
        # 同時書き込み耐性のため WAL モード + ビジー待機を有効化
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        # ユーザーテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                rating REAL DEFAULT 1500.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 戦績テーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                player1_id INTEGER NOT NULL,        -- プレイヤー1 (報告した側、あるいは自分)
                player2_id INTEGER NOT NULL,        -- プレイヤー2 (対戦相手)
                score1 INTEGER NOT NULL,            -- プレイヤー1の得点 (勝利本数)
                score2 INTEGER NOT NULL,            -- プレイヤー2の得点 (勝利本数)
                char1 TEXT,                         -- プレイヤー1の使用キャラ
                char2 TEXT,                         -- プレイヤー2の使用キャラ
                is_confirmed INTEGER DEFAULT 1,     -- 承認状態 (1: 確定, 0: 未承認)
                rating_change1 REAL DEFAULT 0.0,    -- プレイヤー1のレート変動量
                rating_change2 REAL DEFAULT 0.0,    -- プレイヤー2のレート変動量
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(player1_id) REFERENCES users(user_id),
                FOREIGN KEY(player2_id) REFERENCES users(user_id)
            )
        """)
        await db.commit()

        # 陣取りゲーム プロフィールテーブル
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS territory_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                strength INTEGER NOT NULL,
                ip_info TEXT,
                autopunch TEXT,
                giuroll TEXT,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()

        # 陣取りゲーム チーム抽選結果テーブル
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS territory_teams (
                guild_id INTEGER NOT NULL,
                team_index INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                strength INTEGER NOT NULL,
                is_captain INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.commit()

        # 陣取りゲーム 対戦結果テーブル
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS territory_matches (
                match_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                reporter_id INTEGER NOT NULL,
                winner_id INTEGER NOT NULL,
                loser_id INTEGER NOT NULL,
                winner_team INTEGER NOT NULL,
                loser_team INTEGER NOT NULL,
                invasion_score INTEGER NOT NULL,
                captain_defeated INTEGER DEFAULT 0,
                round INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()

        # territory_matches に round が存在しない場合は追加（周回機能）
        async with db.execute("PRAGMA table_info(territory_matches)") as cursor:
            tm_columns = [row[1] for row in await cursor.fetchall()]
        if "round" not in tm_columns:
            await db.execute("ALTER TABLE territory_matches ADD COLUMN round INTEGER NOT NULL DEFAULT 1")
            await db.commit()

        # 陣取りゲーム 陣地マップ(5x5グリッド)テーブル
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS territory_grid (
                guild_id INTEGER NOT NULL,
                cell_index INTEGER NOT NULL,
                team_index INTEGER NOT NULL,
                PRIMARY KEY (guild_id, cell_index)
            )
            """
        )
        await db.commit()

        # 陣取りゲーム ギルド設定（参加者ロール・チームチャンネル設置先カテゴリ）
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS territory_settings (
                guild_id INTEGER PRIMARY KEY,
                participant_role_id INTEGER,
                team_category_id INTEGER,
                participant_channel_id INTEGER,
                participant_voice_channel_id INTEGER,
                reception_channel_id INTEGER,
                hq_channel_id INTEGER,
                current_round INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await db.commit()

        # territory_settings に current_round が存在しない場合は追加（周回機能）
        async with db.execute("PRAGMA table_info(territory_settings)") as cursor:
            ts_columns_round = [row[1] for row in await cursor.fetchall()]
        if "current_round" not in ts_columns_round:
            await db.execute("ALTER TABLE territory_settings ADD COLUMN current_round INTEGER NOT NULL DEFAULT 1")
            await db.commit()

        # territory_settings に participant_channel_id が存在しない場合は追加
        async with db.execute("PRAGMA table_info(territory_settings)") as cursor:
            ts_columns = [row[1] for row in await cursor.fetchall()]
        if "participant_channel_id" not in ts_columns:
            await db.execute("ALTER TABLE territory_settings ADD COLUMN participant_channel_id INTEGER")
            await db.commit()

        # territory_settings に participant_voice_channel_id が存在しない場合は追加
        async with db.execute("PRAGMA table_info(territory_settings)") as cursor:
            ts_columns = [row[1] for row in await cursor.fetchall()]
        if "participant_voice_channel_id" not in ts_columns:
            await db.execute("ALTER TABLE territory_settings ADD COLUMN participant_voice_channel_id INTEGER")
            await db.commit()

        # territory_settings に reception_channel_id / hq_channel_id が存在しない場合は追加
        async with db.execute("PRAGMA table_info(territory_settings)") as cursor:
            ts_columns = [row[1] for row in await cursor.fetchall()]
        if "reception_channel_id" not in ts_columns:
            await db.execute("ALTER TABLE territory_settings ADD COLUMN reception_channel_id INTEGER")
            await db.commit()
        if "hq_channel_id" not in ts_columns:
            await db.execute("ALTER TABLE territory_settings ADD COLUMN hq_channel_id INTEGER")
            await db.commit()

        # 陣取りゲーム チームロール・チームチャンネル対応表
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS territory_team_roles (
                guild_id INTEGER NOT NULL,
                team_index INTEGER NOT NULL,
                role_id INTEGER,
                channel_id INTEGER,
                voice_channel_id INTEGER,
                PRIMARY KEY (guild_id, team_index)
            )
            """
        )
        await db.commit()

        # territory_team_roles に voice_channel_id が存在しない場合は追加
        async with db.execute("PRAGMA table_info(territory_team_roles)") as cursor:
            ttr_columns = [row[1] for row in await cursor.fetchall()]
        if "voice_channel_id" not in ttr_columns:
            await db.execute("ALTER TABLE territory_team_roles ADD COLUMN voice_channel_id INTEGER")
            await db.commit()

        # --- 既存データベースへのマイグレーション処理 ---
        # users テーブルに rating カラムが存在しない場合は追加
        async with db.execute("PRAGMA table_info(users)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "rating" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN rating REAL DEFAULT 1500.0")
            await db.commit()

        # matches テーブルに rating_change1, rating_change2 が存在しない場合は追加
        async with db.execute("PRAGMA table_info(matches)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "rating_change1" not in columns:
            await db.execute("ALTER TABLE matches ADD COLUMN rating_change1 REAL DEFAULT 0.0")
        if "rating_change2" not in columns:
            await db.execute("ALTER TABLE matches ADD COLUMN rating_change2 REAL DEFAULT 0.0")
        await db.commit()

        # matches テーブルに is_rated（レーティングルーム対戦かどうか）が存在しない場合は追加
        async with db.execute("PRAGMA table_info(matches)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "is_rated" not in columns:
            await db.execute("ALTER TABLE matches ADD COLUMN is_rated INTEGER DEFAULT 0")
            await db.commit()

        # 匿名お便りテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS letters (
                letter_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # letters テーブルに admin_message_id（管理チャンネル投稿のメッセージID）、
        # is_hidden（非表示フラグ）が存在しない場合は追加
        async with db.execute("PRAGMA table_info(letters)") as cursor:
            letter_columns = [row[1] for row in await cursor.fetchall()]
        if "admin_message_id" not in letter_columns:
            await db.execute("ALTER TABLE letters ADD COLUMN admin_message_id INTEGER")
            await db.commit()
        if "is_hidden" not in letter_columns:
            await db.execute("ALTER TABLE letters ADD COLUMN is_hidden INTEGER DEFAULT 0")
            await db.commit()

        # 投票アンケートテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                poll_id TEXT PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                allow_multiple INTEGER DEFAULT 1,
                is_anonymous INTEGER DEFAULT 1,
                deadline TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # polls テーブルに is_anonymous カラムが存在しない場合は追加
        async with db.execute("PRAGMA table_info(polls)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "is_anonymous" not in columns:
            await db.execute("ALTER TABLE polls ADD COLUMN is_anonymous INTEGER DEFAULT 1")
            await db.commit()

        await db.execute("""
            CREATE TABLE IF NOT EXISTS poll_votes (
                poll_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                option_index INTEGER NOT NULL,
                PRIMARY KEY (poll_id, user_id, option_index),
                FOREIGN KEY (poll_id) REFERENCES polls(poll_id)
            )
        """)
        # テキスト回答式アンケートテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS surveys (
                survey_id TEXT PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                questions TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS survey_responses (
                response_id INTEGER PRIMARY KEY AUTOINCREMENT,
                survey_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                answers TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (survey_id) REFERENCES surveys(survey_id)
            )
        """)
        # カレンダーイベントテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                time TEXT,
                location TEXT,
                url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # カレンダーメッセージ管理テーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS calendar_messages (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id TEXT NOT NULL,
                display_year INTEGER NOT NULL,
                display_month INTEGER NOT NULL
            )
        """)
        await db.commit()

        # polls テーブルに allow_multiple, deadline カラムが存在しない場合は追加
        async with db.execute("PRAGMA table_info(polls)") as cursor:
            poll_columns = [row[1] for row in await cursor.fetchall()]
        if "allow_multiple" not in poll_columns:
            await db.execute("ALTER TABLE polls ADD COLUMN allow_multiple INTEGER DEFAULT 1")
        if "deadline" not in poll_columns:
            await db.execute("ALTER TABLE polls ADD COLUMN deadline TEXT DEFAULT NULL")
        await db.commit()

        # ピザテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pizzas (
                pizza_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                rating INTEGER DEFAULT 3,
                added_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 対戦募集パネルテーブル（再起動後もボタンを復元するため）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recruit_panels (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                forum_channel_id INTEGER NOT NULL,
                notify_channel_id INTEGER,
                mention_role_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # recruit_panels テーブルに notify_channel_id, mention_role_id が存在しない場合は追加
        async with db.execute("PRAGMA table_info(recruit_panels)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "notify_channel_id" not in columns:
            await db.execute("ALTER TABLE recruit_panels ADD COLUMN notify_channel_id INTEGER")
        if "mention_role_id" not in columns:
            await db.execute("ALTER TABLE recruit_panels ADD COLUMN mention_role_id INTEGER")
        await db.commit()

        # 募集入力デフォルト値テーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recruit_defaults (
                user_id INTEGER PRIMARY KEY,
                connection_type TEXT NOT NULL,
                match_settings TEXT NOT NULL,
                character TEXT DEFAULT '',
                comment TEXT DEFAULT ''
            )
        """)
        # 募集スレッドコントロールパネルテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recruit_threads (
                thread_id INTEGER PRIMARY KEY,
                panel_message_id INTEGER NOT NULL,
                recruiter_id INTEGER NOT NULL,
                status TEXT DEFAULT 'recruiting',
                challenger_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 記事投稿パネルテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS article_panels (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                forum_channel_id INTEGER NOT NULL,
                category_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 記事スレッドコントロールパネルテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS article_threads (
                thread_id INTEGER PRIMARY KEY,
                post_message_id INTEGER NOT NULL,
                control_message_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # article_panels に category_id カラムが存在しない場合は追加
        async with db.execute("PRAGMA table_info(article_panels)") as cursor:
            ap_columns = [row[1] for row in await cursor.fetchall()]
        if "category_id" not in ap_columns:
            await db.execute("ALTER TABLE article_panels ADD COLUMN category_id INTEGER")
            await db.commit()

        # レーティングルーム: ユーザープロフィール（1戦目のキャラ・接続情報など）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rating_profiles (
                user_id INTEGER PRIMARY KEY,
                main_character TEXT NOT NULL,
                ip_info TEXT DEFAULT '',
                autopunch TEXT DEFAULT '',
                giuroll TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                max_rating_diff REAL DEFAULT 100.0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # rating_profiles に max_rating_diff（希望マッチング範囲）が存在しない場合は追加
        async with db.execute("PRAGMA table_info(rating_profiles)") as cursor:
            rp_columns = [row[1] for row in await cursor.fetchall()]
        if "max_rating_diff" not in rp_columns:
            await db.execute("ALTER TABLE rating_profiles ADD COLUMN max_rating_diff REAL DEFAULT 100.0")
            await db.commit()
        # レーティングルーム: マッチングキュー
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rating_queue (
                user_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # レーティングルーム: 対戦スレッドコントロールパネル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rating_threads (
                thread_id INTEGER PRIMARY KEY,
                panel_message_id INTEGER NOT NULL,
                player1_id INTEGER NOT NULL,
                player2_id INTEGER NOT NULL,
                status TEXT DEFAULT 'in_progress',
                last_match_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

        # rating_threads に last_match_id（直近に登録した戦績のID。結果修正時の巻き戻しに使用）が存在しない場合は追加
        async with db.execute("PRAGMA table_info(rating_threads)") as cursor:
            rt_columns = [row[1] for row in await cursor.fetchall()]
        if "last_match_id" not in rt_columns:
            await db.execute("ALTER TABLE rating_threads ADD COLUMN last_match_id INTEGER")
            await db.commit()

        # レーティングルーム: ギルドごとの設定（投稿先フォーラム・通知先）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rating_settings (
                guild_id INTEGER PRIMARY KEY,
                forum_channel_id INTEGER NOT NULL,
                notify_channel_id INTEGER,
                mention_role_id INTEGER
            )
        """)
        # レーティングルーム: キュー可視化ボード（常設メッセージを編集して更新）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rating_queue_board (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )
        """)
        await db.commit()

        # レイドバトル（初級者vs上級者）: ギルドごとの設定（カテゴリ・ロール・各チャンネル）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS raid_battle_settings (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER,
                beginner_role_id INTEGER,
                advanced_role_id INTEGER,
                recruit_channel_id INTEGER,
                beginner_channel_id INTEGER,
                advanced_channel_id INTEGER,
                common_channel_id INTEGER
            )
        """)
        await db.commit()

        # レイドバトル: 上級者の対応状況（自己申告トグル）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS raid_advanced_status (
                user_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                is_available INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # レイドバトル: 上級者対応状況ボード（常設メッセージを編集して更新）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS raid_status_board (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )
        """)
        await db.commit()

        # 普段のメインキャラクター登録（1人1キャラ、変更可）
        await db.execute("""
            CREATE TABLE IF NOT EXISTS main_characters (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                character TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()
