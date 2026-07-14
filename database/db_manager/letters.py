import aiosqlite

from ._common import DB_PATH

__all__ = ["add_letter", "get_letter"]


async def add_letter(sender_id: int, title: str, body: str) -> int:
    """匿名お便りをDBに保存し、letter_id を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO letters (sender_id, title, body) VALUES (?, ?, ?)",
            (sender_id, title, body)
        )
        await db.commit()
        return cursor.lastrowid

async def get_letter(letter_id: int):
    """指定IDのお便りを取得（管理者用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM letters WHERE letter_id = ?", (letter_id,)) as cursor:
            return await cursor.fetchone()
