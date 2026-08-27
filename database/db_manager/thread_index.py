import aiosqlite

from ._common import DB_PATH

__all__ = [
    "save_thread_index_board",
    "get_thread_index_board",
    "get_all_thread_index_boards",
    "delete_thread_index_board",
]


async def save_thread_index_board(
    channel_id: int, guild_id: int, message_id: int, board_channel_id: int | None = None
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO thread_index_boards (channel_id, guild_id, message_id, board_channel_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(channel_id) DO UPDATE SET
               guild_id=excluded.guild_id, message_id=excluded.message_id,
               board_channel_id=excluded.board_channel_id""",
            (channel_id, guild_id, message_id, board_channel_id or channel_id),
        )
        await db.commit()


async def get_thread_index_board(channel_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM thread_index_boards WHERE channel_id = ?", (channel_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_thread_index_boards() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM thread_index_boards") as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_thread_index_board(channel_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM thread_index_boards WHERE channel_id = ?", (channel_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
