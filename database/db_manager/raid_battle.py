import aiosqlite

from ._common import DB_PATH

__all__ = [
    "save_raid_battle_settings",
    "get_raid_battle_settings",
    "ensure_raid_advanced_status",
    "toggle_raid_advanced_status",
    "get_raid_advanced_statuses",
    "save_raid_status_board",
    "get_raid_status_board",
]


async def save_raid_battle_settings(guild_id: int, **fields) -> None:
    """指定したフィールドのみを更新する（未指定のフィールドは既存値を保持）"""
    if not fields:
        return
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""INSERT INTO raid_battle_settings (guild_id, {columns})
                VALUES (?, {placeholders})
                ON CONFLICT(guild_id) DO UPDATE SET {updates}""",
            (guild_id, *fields.values()),
        )
        await db.commit()


async def get_raid_battle_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM raid_battle_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def ensure_raid_advanced_status(user_id: int, guild_id: int) -> None:
    """未登録なら「対応可能」状態で作成する。既存の状態は変更しない"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO raid_advanced_status (user_id, guild_id, is_available)
               VALUES (?, ?, 1)""",
            (user_id, guild_id),
        )
        await db.commit()


async def toggle_raid_advanced_status(user_id: int, guild_id: int) -> bool:
    """対応可能/対応不可を反転して保存し、切り替え後の状態(True=対応可能)を返す"""
    await ensure_raid_advanced_status(user_id, guild_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT is_available FROM raid_advanced_status WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        new_value = 0 if row["is_available"] else 1
        await db.execute(
            "UPDATE raid_advanced_status SET is_available = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_value, user_id),
        )
        await db.commit()
        return bool(new_value)


async def get_raid_advanced_statuses(guild_id: int) -> dict:
    """{user_id: is_available(bool)} を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, is_available FROM raid_advanced_status WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return {r["user_id"]: bool(r["is_available"]) for r in rows}


async def save_raid_status_board(guild_id: int, channel_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO raid_status_board (guild_id, channel_id, message_id)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
               channel_id=excluded.channel_id, message_id=excluded.message_id""",
            (guild_id, channel_id, message_id),
        )
        await db.commit()


async def get_raid_status_board(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM raid_status_board WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None
