import aiosqlite
import datetime
import os
import config

DB_PATH = config.DB_PATH

async def init_db():
    """データベースの初期化"""
    async with aiosqlite.connect(DB_PATH) as db:
        # ユーザーテーブル
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(player1_id) REFERENCES users(user_id),
                FOREIGN KEY(player2_id) REFERENCES users(user_id)
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
                    score1: int, score2: int, char1: str = None, char2: str = None) -> int:
    """戦績をデータベースに登録し、新規追加された match_id を返す"""
    # 双方のユーザーをDBに作成/更新
    await get_or_create_user(player1_id, player1_name)
    await get_or_create_user(player2_id, player2_name)
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO matches (reporter_id, player1_id, player2_id, score1, score2, char1, char2)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (reporter_id, player1_id, player2_id, score1, score2, char1, char2))
        await db.commit()
        return cursor.lastrowid

async def delete_match(match_id: int) -> bool:
    """指定されたIDの戦績を削除。削除成功ならTrueを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM matches WHERE match_id = ?", (match_id,)) as cursor:
            exists = await cursor.fetchone()
        if not exists:
            return False
            
        await db.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
        await db.commit()
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
                    "win_rate": round(win_rate, 1)
                })
                
        # 勝率で降順ソート、同率なら勝利数でソート
        leaderboard_data.sort(key=lambda x: (x["win_rate"], x["wins"]), reverse=True)
        return leaderboard_data
