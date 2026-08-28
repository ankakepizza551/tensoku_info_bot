import aiosqlite

from ._common import DB_PATH

__all__ = [
    "create_reminder",
    "get_due_reminders",
    "mark_reminder_sent",
    "get_reminders_for_thread",
    "get_reminder",
    "delete_reminder",
]


async def create_reminder(
    thread_id: int,
    guild_id: int,
    creator_id: int,
    fire_at: str,
    message: str,
    role_id: int | None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO event_reminders
               (thread_id, guild_id, creator_id, fire_at, message, role_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (thread_id, guild_id, creator_id, fire_at, message, role_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_due_reminders(now_str: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM event_reminders WHERE is_sent = 0 AND fire_at <= ?", (now_str,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def mark_reminder_sent(reminder_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE event_reminders SET is_sent = 1 WHERE reminder_id = ?", (reminder_id,)
        )
        await db.commit()


async def get_reminders_for_thread(thread_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM event_reminders WHERE thread_id = ? AND is_sent = 0
               ORDER BY fire_at ASC""",
            (thread_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_reminder(reminder_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM event_reminders WHERE reminder_id = ?", (reminder_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_reminder(reminder_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM event_reminders WHERE reminder_id = ?", (reminder_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
