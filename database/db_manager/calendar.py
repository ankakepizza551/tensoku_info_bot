import aiosqlite

from ._common import DB_PATH

__all__ = [
    "add_event",
    "get_events",
    "delete_event",
    "set_calendar_message",
    "get_calendar_message",
    "get_all_calendar_messages",
    "update_calendar_display",
]


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
