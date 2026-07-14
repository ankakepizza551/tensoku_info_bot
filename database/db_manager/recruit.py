import aiosqlite

from ._common import DB_PATH

__all__ = [
    "add_recruit_panel",
    "get_recruit_panels",
    "delete_recruit_panel",
    "add_recruit_thread",
    "get_recruit_thread",
    "get_active_recruit_threads",
    "update_recruit_thread_status",
    "delete_recruit_thread",
    "save_recruit_defaults",
    "get_recruit_defaults",
]


async def add_recruit_panel(
    message_id: int,
    channel_id: int,
    forum_channel_id: int,
    notify_channel_id: int | None = None,
    mention_role_id: int | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO recruit_panels
               (message_id, channel_id, forum_channel_id, notify_channel_id, mention_role_id)
               VALUES (?, ?, ?, ?, ?)""",
            (message_id, channel_id, forum_channel_id, notify_channel_id, mention_role_id)
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

async def save_recruit_defaults(
    user_id: int,
    connection_type: str,
    match_settings: str,
    character: str,
    comment: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO recruit_defaults (user_id, connection_type, match_settings, character, comment)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
               connection_type=excluded.connection_type,
               match_settings=excluded.match_settings,
               character=excluded.character,
               comment=excluded.comment""",
            (user_id, connection_type, match_settings, character, comment),
        )
        await db.commit()

async def get_recruit_defaults(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recruit_defaults WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None
