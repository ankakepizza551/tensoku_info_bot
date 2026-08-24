import aiosqlite

from ._common import DB_PATH

__all__ = [
    "save_welcome_settings",
    "get_welcome_settings",
]


async def save_welcome_settings(guild_id: int, channel_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO welcome_settings (guild_id, channel_id)
               VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id""",
            (guild_id, channel_id),
        )
        await db.commit()


async def get_welcome_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM welcome_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None
