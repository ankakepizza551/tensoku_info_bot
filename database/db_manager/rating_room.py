import aiosqlite

from ._common import DB_PATH

__all__ = [
    "save_rating_profile",
    "save_rating_max_diff",
    "get_rating_profile",
    "join_rating_queue",
    "leave_rating_queue",
    "get_rating_queue",
    "find_rating_match",
    "add_rating_thread",
    "get_rating_thread",
    "get_active_rating_threads",
    "get_all_rating_threads",
    "update_rating_thread_status",
    "update_rating_thread_match_id",
    "delete_rating_thread",
    "save_rating_settings",
    "get_rating_settings",
    "save_rating_queue_board",
    "get_rating_queue_board",
]


async def save_rating_profile(
    user_id: int, main_character: str, ip_info: str, autopunch: str, giuroll: str, comment: str,
    max_rating_diff: float = 100.0,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO rating_profiles
               (user_id, main_character, ip_info, autopunch, giuroll, comment, max_rating_diff, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
               main_character=excluded.main_character,
               ip_info=excluded.ip_info,
               autopunch=excluded.autopunch,
               giuroll=excluded.giuroll,
               comment=excluded.comment,
               max_rating_diff=excluded.max_rating_diff,
               updated_at=CURRENT_TIMESTAMP""",
            (user_id, main_character, ip_info, autopunch, giuroll, comment, max_rating_diff),
        )
        await db.commit()

async def save_rating_max_diff(user_id: int, max_rating_diff: float) -> bool:
    """既存プロフィールの希望レート差のみを更新する。プロフィール未登録ならFalseを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """UPDATE rating_profiles SET max_rating_diff = ?, updated_at = CURRENT_TIMESTAMP
               WHERE user_id = ?""",
            (max_rating_diff, user_id),
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def get_rating_profile(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rating_profiles WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def join_rating_queue(user_id: int, guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO rating_queue (user_id, guild_id, joined_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
               guild_id=excluded.guild_id, joined_at=CURRENT_TIMESTAMP""",
            (user_id, guild_id),
        )
        await db.commit()

async def leave_rating_queue(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM rating_queue WHERE user_id = ?", (user_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def get_rating_queue(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rating_queue WHERE guild_id = ? ORDER BY joined_at", (guild_id,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def find_rating_match(guild_id: int, user_id: int, rating: float, max_diff: float = 100.0) -> dict | None:
    """キュー内から自分以外の相手を探す。レート差が自分と相手、双方の希望範囲内に収まり、
    かつ差が最小の相手を返す（片方だけが許容していてもマッチしない）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT q.user_id as user_id, u.rating as rating, p.max_rating_diff as max_rating_diff
               FROM rating_queue q
               JOIN users u ON u.user_id = q.user_id
               JOIN rating_profiles p ON p.user_id = q.user_id
               WHERE q.guild_id = ? AND q.user_id != ?
               ORDER BY q.joined_at""",
            (guild_id, user_id),
        ) as cursor:
            candidates = await cursor.fetchall()

    best = None
    best_diff = None
    for c in candidates:
        diff = abs(c["rating"] - rating)
        candidate_max_diff = c["max_rating_diff"] if c["max_rating_diff"] is not None else 100.0
        effective_max = min(max_diff, candidate_max_diff)
        if diff <= effective_max and (best_diff is None or diff < best_diff):
            best = c
            best_diff = diff
    return dict(best) if best else None

async def add_rating_thread(thread_id: int, panel_message_id: int, player1_id: int, player2_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO rating_threads
               (thread_id, panel_message_id, player1_id, player2_id) VALUES (?, ?, ?, ?)""",
            (thread_id, panel_message_id, player1_id, player2_id),
        )
        await db.commit()

async def get_rating_thread(thread_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rating_threads WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def get_active_rating_threads() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rating_threads WHERE status != 'completed'"
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def get_all_rating_threads() -> list:
    """状態を問わず全ての対戦スレッドを取得する（再起動時のView再登録用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM rating_threads") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def update_rating_thread_status(thread_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rating_threads SET status = ? WHERE thread_id = ?", (status, thread_id)
        )
        await db.commit()

async def update_rating_thread_match_id(thread_id: int, match_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE rating_threads SET last_match_id = ? WHERE thread_id = ?", (match_id, thread_id)
        )
        await db.commit()

async def delete_rating_thread(thread_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM rating_threads WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def save_rating_settings(
    guild_id: int, forum_channel_id: int, notify_channel_id: int | None, mention_role_id: int | None
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO rating_settings (guild_id, forum_channel_id, notify_channel_id, mention_role_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
               forum_channel_id=excluded.forum_channel_id,
               notify_channel_id=excluded.notify_channel_id,
               mention_role_id=excluded.mention_role_id""",
            (guild_id, forum_channel_id, notify_channel_id, mention_role_id),
        )
        await db.commit()

async def get_rating_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rating_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def save_rating_queue_board(guild_id: int, channel_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO rating_queue_board (guild_id, channel_id, message_id)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
               channel_id=excluded.channel_id, message_id=excluded.message_id""",
            (guild_id, channel_id, message_id),
        )
        await db.commit()

async def get_rating_queue_board(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM rating_queue_board WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None
