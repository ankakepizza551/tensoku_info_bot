import aiosqlite
import datetime
import os
import config

DB_PATH = config.DB_PATH

async def init_db():
    """データベースの初期化とマイグレーション"""
    async with aiosqlite.connect(DB_PATH) as db:
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

        # polls テーブルに is_anonymous カラムが存在しない場合は追加
        async with db.execute("PRAGMA table_info(polls)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "is_anonymous" not in columns:
            await db.execute("ALTER TABLE polls ADD COLUMN is_anonymous INTEGER DEFAULT 1")
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        await db.commit()

async def get_or_create_user(user_id: int, username: str):
    """ユーザー情報を取得、なければ新規登録。ユーザー名が変わっている場合は更新"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
        if user is None:
            await db.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                (user_id, username)
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                user = await cursor.fetchone()
        elif user["username"] != username:
            await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                user = await cursor.fetchone()
                
        return user

async def add_match(reporter_id: int, player1_id: int, player1_name: str,
                    player2_id: int, player2_name: str,
                    score1: int, score2: int, char1: str = None, char2: str = None) -> dict:
    """戦績をデータベースに登録し、Eloレーティング計算・更新を行って結果を返す"""
    # 双方のユーザーをDBに作成/更新
    p1 = await get_or_create_user(player1_id, player1_name)
    p2 = await get_or_create_user(player2_id, player2_name)
    
    old_r1 = p1["rating"]
    old_r2 = p2["rating"]
    
    # Eloレーティング期待値の計算
    expected1 = 1.0 / (1.0 + 10.0 ** ((old_r2 - old_r1) / 400.0))
    expected2 = 1.0 / (1.0 + 10.0 ** ((old_r1 - old_r2) / 400.0))
    
    # 勝敗判定 (S1, S2)
    if score1 > score2:
        s1, s2 = 1.0, 0.0
    elif score2 > score1:
        s1, s2 = 0.0, 1.0
    else:
        s1, s2 = 0.5, 0.5
        
    k_factor = 32.0
    change1 = k_factor * (s1 - expected1)
    change2 = k_factor * (s2 - expected2)
    
    new_r1 = old_r1 + change1
    new_r2 = old_r2 + change2
    
    async with aiosqlite.connect(DB_PATH) as db:
        # トランザクション処理
        await db.execute("BEGIN TRANSACTION")
        try:
            cursor = await db.execute("""
                INSERT INTO matches (reporter_id, player1_id, player2_id, score1, score2, char1, char2, rating_change1, rating_change2)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (reporter_id, player1_id, player2_id, score1, score2, char1, char2, change1, change2))
            match_id = cursor.lastrowid
            
            # ユーザーのレーティング更新
            await db.execute("UPDATE users SET rating = ? WHERE user_id = ?", (new_r1, player1_id))
            await db.execute("UPDATE users SET rating = ? WHERE user_id = ?", (new_r2, player2_id))
            await db.commit()
        except Exception as e:
            await db.execute("ROLLBACK")
            raise e
            
    return {
        "match_id": match_id,
        "old_rating1": old_r1,
        "new_rating1": new_r1,
        "change1": change1,
        "old_rating2": old_r2,
        "new_rating2": new_r2,
        "change2": change2
    }

async def delete_match(match_id: int) -> bool:
    """指定されたIDの戦績を削除し、レーティング変動を巻き戻す。削除成功ならTrueを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)) as cursor:
            match_data = await cursor.fetchone()
        if not match_data:
            return False
            
        p1_id = match_data["player1_id"]
        p2_id = match_data["player2_id"]
        change1 = match_data["rating_change1"] or 0.0
        change2 = match_data["rating_change2"] or 0.0
        
        await db.execute("BEGIN TRANSACTION")
        try:
            # マッチの削除
            await db.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
            
            # レーティングの巻き戻し (引く)
            await db.execute("UPDATE users SET rating = rating - ? WHERE user_id = ?", (change1, p1_id))
            await db.execute("UPDATE users SET rating = rating - ? WHERE user_id = ?", (change2, p2_id))
            await db.commit()
        except Exception as e:
            await db.execute("ROLLBACK")
            raise e
            
        return True

async def get_match(match_id: int):
    """指定されたIDの戦績を取得"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)) as cursor:
            return await cursor.fetchone()

async def get_user_stats(user_id: int) -> dict:
    """ユーザーの戦績統計情報を集計して辞書で返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. ユーザーが関わった全対戦を取得
        # player1_id または player2_id が本人である試合
        async with db.execute("""
            SELECT * FROM matches 
            WHERE (player1_id = ? OR player2_id = ?) AND is_confirmed = 1
            ORDER BY created_at DESC
        """, (user_id, user_id)) as cursor:
            rows = await cursor.fetchall()
            
        if not rows:
            return {
                "total_matches": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "recent_history": [],
                "character_stats": {},
                "head_to_head": {}
            }
            
        total_matches = len(rows)
        wins = 0
        losses = 0
        
        # キャラ別・対戦相手別の戦績集計用辞書
        char_stats = {}  # { char_name: { "wins": 0, "losses": 0, "played": 0 } }
        h2h_stats = {}   # { opp_id: { "username": "", "wins": 0, "losses": 0, "played": 0 } }
        recent_history = []
        
        for row in rows:
            is_p1 = (row["player1_id"] == user_id)
            my_score = row["score1"] if is_p1 else row["score2"]
            opp_score = row["score2"] if is_p1 else row["score1"]
            my_char = row["char1"] if is_p1 else row["char2"]
            opp_char = row["char2"] if is_p1 else row["char1"]
            opp_id = row["player2_id"] if is_p1 else row["player1_id"]
            
            # 勝敗判定
            is_win = my_score > opp_score
            if is_win:
                wins += 1
            else:
                losses += 1
                
            # 直近履歴 (最大5件)
            if len(recent_history) < 5:
                # 相手のユーザー名を取得
                async with db.execute("SELECT username FROM users WHERE user_id = ?", (opp_id,)) as u_cursor:
                    opp_user = await u_cursor.fetchone()
                opp_name = opp_user["username"] if opp_user else f"User {opp_id}"
                
                recent_history.append({
                    "match_id": row["match_id"],
                    "opponent_name": opp_name,
                    "my_score": my_score,
                    "opponent_score": opp_score,
                    "my_char": my_char,
                    "opponent_char": opp_char,
                    "is_win": is_win,
                    "date": row["created_at"].split()[0] if row["created_at"] else ""
                })
                
            # 使用キャラ統計の更新
            if my_char:
                if my_char not in char_stats:
                    char_stats[my_char] = {"wins": 0, "losses": 0, "played": 0}
                char_stats[my_char]["played"] += 1
                if is_win:
                    char_stats[my_char]["wins"] += 1
                else:
                    char_stats[my_char]["losses"] += 1
                    
            # 対戦相手別統計の更新
            if opp_id not in h2h_stats:
                async with db.execute("SELECT username FROM users WHERE user_id = ?", (opp_id,)) as u_cursor:
                    opp_user = await u_cursor.fetchone()
                opp_name = opp_user["username"] if opp_user else f"User {opp_id}"
                h2h_stats[opp_id] = {"username": opp_name, "wins": 0, "losses": 0, "played": 0}
                
            h2h_stats[opp_id]["played"] += 1
            if is_win:
                h2h_stats[opp_id]["wins"] += 1
            else:
                h2h_stats[opp_id]["losses"] += 1
                
        win_rate = (wins / total_matches) * 100 if total_matches > 0 else 0.0
        
        return {
            "total_matches": total_matches,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "recent_history": recent_history,
            "character_stats": char_stats,
            "head_to_head": h2h_stats
        }

async def add_letter(sender_id: int, title: str, body: str) -> int:
    """匿名お便りをDBに保存し、letter_id を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO letters (sender_id, title, body) VALUES (?, ?, ?)",
            (sender_id, title, body)
        )
        await db.commit()
        return cursor.lastrowid

async def get_letter(letter_id: int):
    """指定IDのお便りを取得（管理者用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM letters WHERE letter_id = ?", (letter_id,)) as cursor:
            return await cursor.fetchone()

async def get_leaderboard(min_matches: int = 1) -> list:
    """ランキング（リーダーボード）を取得。試合数が min_matches 以上のユーザーが対象"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # 全ユーザーの対戦を取得し、プログラム側で集計してソートする
        # （ユーザー数が非常に多くない限り、この手法が最も柔軟に勝率などを計算できます）
        async with db.execute("SELECT * FROM users") as cursor:
            users = await cursor.fetchall()
            
        leaderboard_data = []
        
        for user in users:
            uid = user["user_id"]
            uname = user["username"]
            urating = user["rating"] if "rating" in user.keys() else 1500.0
            
            # 各ユーザーの戦績を簡易集集計する
            async with db.execute("""
                SELECT 
                    SUM(CASE WHEN player1_id = ? AND score1 > score2 THEN 1 
                             WHEN player2_id = ? AND score2 > score1 THEN 1 ELSE 0 END) as wins,
                    COUNT(*) as total
                FROM matches
                WHERE (player1_id = ? OR player2_id = ?) AND is_confirmed = 1
            """, (uid, uid, uid, uid)) as m_cursor:
                res = await m_cursor.fetchone()
                
            total = res["total"] or 0
            wins = res["wins"] or 0
            losses = total - wins
            
            if total >= min_matches:
                win_rate = (wins / total) * 100 if total > 0 else 0.0
                leaderboard_data.append({
                    "user_id": uid,
                    "username": uname,
                    "wins": wins,
                    "losses": losses,
                    "total": total,
                    "win_rate": round(win_rate, 1),
                    "rating": round(urating, 1)
                })
                
        # レーティング（Elo）で降順ソート、同率なら勝率でソート
        leaderboard_data.sort(key=lambda x: (x["rating"], x["win_rate"]), reverse=True)
        return leaderboard_data

# ── 投票アンケート (Poll) ──────────────────────────────────────

async def create_poll(poll_id: str, channel_id: int, creator_id: int, question: str, options: list, allow_multiple: bool = True, is_anonymous: bool = True, deadline: str | None = None) -> None:
    """投票アンケートをDBに保存する"""
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO polls (poll_id, channel_id, creator_id, question, options, allow_multiple, is_anonymous, deadline) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (poll_id, channel_id, creator_id, question, json.dumps(options, ensure_ascii=False), int(allow_multiple), int(is_anonymous), deadline)
        )
        await db.commit()

async def get_poll(poll_id: str):
    """指定IDの投票アンケートを取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM polls WHERE poll_id = ?", (poll_id,)) as cursor:
            return await cursor.fetchone()

async def get_active_polls() -> list:
    """アクティブな投票アンケートを全件取得する（Bot再起動時のView再登録用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM polls WHERE is_active = 1") as cursor:
            return await cursor.fetchall()

async def toggle_poll_vote(poll_id: str, user_id: int, option_index: int) -> bool:
    """投票をトグルする。追加した場合はTrue、取り消した場合はFalseを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM poll_votes WHERE poll_id = ? AND user_id = ? AND option_index = ?",
            (poll_id, user_id, option_index)
        ) as cursor:
            exists = await cursor.fetchone()

        if exists:
            await db.execute(
                "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ? AND option_index = ?",
                (poll_id, user_id, option_index)
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO poll_votes (poll_id, user_id, option_index) VALUES (?, ?, ?)",
                (poll_id, user_id, option_index)
            )
            await db.commit()
            return True

async def get_poll_votes(poll_id: str) -> list:
    """指定アンケートの全投票レコードを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, option_index FROM poll_votes WHERE poll_id = ?", (poll_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_user_poll_votes(poll_id: str, user_id: int) -> list:
    """指定ユーザーが投票済みのoption_indexリストを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT option_index FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
        return [r[0] for r in rows]

async def set_single_poll_vote(poll_id: str, user_id: int, option_index: int) -> bool:
    """単一選択モード用。既存投票を全削除し指定選択肢に投票。同じ選択肢なら取り消しのみ。"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT option_index FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        ) as cursor:
            existing = await cursor.fetchone()

        already_voted_same = existing is not None and existing[0] == option_index

        await db.execute(
            "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        )
        if not already_voted_same:
            await db.execute(
                "INSERT INTO poll_votes (poll_id, user_id, option_index) VALUES (?, ?, ?)",
                (poll_id, user_id, option_index)
            )
        await db.commit()
        return not already_voted_same

async def get_expired_polls() -> list:
    """期限切れかつアクティブな投票アンケートを全件取得する"""
    import datetime
    JST = datetime.timezone(datetime.timedelta(hours=9))
    now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM polls WHERE is_active = 1 AND deadline IS NOT NULL AND deadline <= ?",
            (now_str,)
        ) as cursor:
            return await cursor.fetchall()

async def close_poll(poll_id: str) -> None:
    """投票アンケートを締め切る"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE polls SET is_active = 0 WHERE poll_id = ?", (poll_id,))
        await db.commit()

# ── テキスト回答式アンケート (Survey) ──────────────────────────

async def create_survey(survey_id: str, channel_id: int, creator_id: int, title: str, questions: list) -> None:
    """テキスト回答式アンケートをDBに保存する"""
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO surveys (survey_id, channel_id, creator_id, title, questions) VALUES (?, ?, ?, ?, ?)",
            (survey_id, channel_id, creator_id, title, json.dumps(questions, ensure_ascii=False))
        )
        await db.commit()

async def get_survey(survey_id: str):
    """指定IDのアンケートを取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM surveys WHERE survey_id = ?", (survey_id,)) as cursor:
            return await cursor.fetchone()

async def get_active_surveys() -> list:
    """アクティブなアンケートを全件取得する（Bot再起動時のView再登録用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM surveys WHERE is_active = 1") as cursor:
            return await cursor.fetchall()

async def add_survey_response(survey_id: str, user_id: int, answers: list) -> None:
    """アンケートへの回答を保存する"""
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO survey_responses (survey_id, user_id, answers) VALUES (?, ?, ?)",
            (survey_id, user_id, json.dumps(answers, ensure_ascii=False))
        )
        await db.commit()

async def get_survey_responses(survey_id: str) -> list:
    """アンケートの全回答を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM survey_responses WHERE survey_id = ? ORDER BY created_at",
            (survey_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def has_survey_responded(survey_id: str, user_id: int) -> bool:
    """指定ユーザーがすでに回答済みかどうかを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM survey_responses WHERE survey_id = ? AND user_id = ?",
            (survey_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None

# ── カレンダーイベント ─────────────────────────────────────────

async def add_event(guild_id: int, date: str, name: str, type: str, time: str | None, location: str | None, url: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO events (guild_id, date, name, type, time, location, url) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, date, name, type, time, location, url)
        )
        await db.commit()

async def get_events(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM events WHERE guild_id = ? ORDER BY date, time",
            (guild_id,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def delete_event(event_id: int, guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM events WHERE event_id = ? AND guild_id = ?",
            (event_id, guild_id)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def set_calendar_message(guild_id: int, channel_id: int, message_id: str, year: int, month: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO calendar_messages (guild_id, channel_id, message_id, display_year, display_month)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
               channel_id=excluded.channel_id,
               message_id=excluded.message_id,
               display_year=excluded.display_year,
               display_month=excluded.display_month""",
            (guild_id, channel_id, message_id, year, month)
        )
        await db.commit()

async def get_calendar_message(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM calendar_messages WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def get_all_calendar_messages() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM calendar_messages") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def update_calendar_display(guild_id: int, year: int, month: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE calendar_messages SET display_year = ?, display_month = ? WHERE guild_id = ?",
            (year, month, guild_id)
        )
        await db.commit()

async def close_survey(survey_id: str) -> None:
    """アンケートを締め切る"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE surveys SET is_active = 0 WHERE survey_id = ?", (survey_id,))
        await db.commit()

# ── ピザ管理 ─────────────────────────────────────────────────────

async def add_pizza(name: str, description: str, rating: int, added_by: int) -> int:
    """ピザを登録し、pizza_id を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO pizzas (name, description, rating, added_by) VALUES (?, ?, ?, ?)",
            (name, description, rating, added_by)
        )
        await db.commit()
        return cursor.lastrowid

async def get_random_pizza() -> dict | None:
    """ランダムにピザを1件取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pizzas ORDER BY RANDOM() LIMIT 1") as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_pizzas() -> list:
    """全ピザを取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pizzas ORDER BY created_at DESC") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def delete_pizza(pizza_id: int) -> bool:
    """指定IDのピザを削除する。削除成功ならTrueを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("DELETE FROM pizzas WHERE pizza_id = ?", (pizza_id,)) as cursor:
            await db.commit()
            return cursor.rowcount > 0

# ── 対戦募集パネル ────────────────────────────────────────────────

async def add_recruit_panel(message_id: int, channel_id: int, forum_channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO recruit_panels (message_id, channel_id, forum_channel_id) VALUES (?, ?, ?)",
            (message_id, channel_id, forum_channel_id)
        )
        await db.commit()

async def get_recruit_panels() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recruit_panels") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def delete_recruit_panel(message_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("DELETE FROM recruit_panels WHERE message_id = ?", (message_id,)) as cursor:
            await db.commit()
            return cursor.rowcount > 0

# ── 募集スレッドコントロールパネル ───────────────────────────────

async def add_recruit_thread(thread_id: int, panel_message_id: int, recruiter_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO recruit_threads (thread_id, panel_message_id, recruiter_id) VALUES (?, ?, ?)",
            (thread_id, panel_message_id, recruiter_id)
        )
        await db.commit()

async def get_recruit_thread(thread_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recruit_threads WHERE thread_id = ?", (thread_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def get_active_recruit_threads() -> list:
    """recruiting / in_progress 状態のスレッドを取得（再起動時のView再登録用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recruit_threads WHERE status != 'completed'"
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def update_recruit_thread_status(
    thread_id: int, status: str, challenger_id: int | None = None
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        if challenger_id is not None:
            await db.execute(
                "UPDATE recruit_threads SET status = ?, challenger_id = ? WHERE thread_id = ?",
                (status, challenger_id, thread_id)
            )
        else:
            await db.execute(
                "UPDATE recruit_threads SET status = ? WHERE thread_id = ?",
                (status, thread_id)
            )
        await db.commit()

async def delete_recruit_thread(thread_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM recruit_threads WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0
