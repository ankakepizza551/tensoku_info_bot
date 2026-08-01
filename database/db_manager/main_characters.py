import aiosqlite

from ._common import DB_PATH

__all__ = ["set_main_character", "get_main_character", "get_all_main_characters"]


async def set_main_character(user_id: int, username: str, character: str) -> None:
    """メインキャラクターを登録・変更する（1人1キャラ）"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO main_characters (user_id, username, character, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
               username=excluded.username,
               character=excluded.character,
               updated_at=CURRENT_TIMESTAMP""",
            (user_id, username, character)
        )
        await db.commit()


async def get_main_character(user_id: int) -> dict | None:
    """指定ユーザーのメインキャラクター登録情報を取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM main_characters WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_main_characters() -> list:
    """登録されている全ユーザーのメインキャラクターを取得する（キャラ名順）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM main_characters ORDER BY character, username"
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]
