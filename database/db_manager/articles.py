import aiosqlite

from ._common import DB_PATH

__all__ = [
    "add_article_panel",
    "get_article_panels",
    "delete_article_panel",
    "add_article_thread",
    "get_article_thread",
    "get_article_threads",
    "delete_article_thread",
]


async def add_article_panel(
    message_id: int,
    channel_id: int,
    forum_channel_id: int,
    category_id: int | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO article_panels
               (message_id, channel_id, forum_channel_id, category_id) VALUES (?, ?, ?, ?)""",
            (message_id, channel_id, forum_channel_id, category_id)
        )
        await db.commit()

async def get_article_panels() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM article_panels") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def delete_article_panel(message_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM article_panels WHERE message_id = ?", (message_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def add_article_thread(
    thread_id: int, post_message_id: int, control_message_id: int, author_id: int
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO article_threads
               (thread_id, post_message_id, control_message_id, author_id) VALUES (?, ?, ?, ?)""",
            (thread_id, post_message_id, control_message_id, author_id)
        )
        await db.commit()

async def get_article_thread(thread_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM article_threads WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def get_article_threads() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM article_threads") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def delete_article_thread(thread_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM article_threads WHERE thread_id = ?", (thread_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0
