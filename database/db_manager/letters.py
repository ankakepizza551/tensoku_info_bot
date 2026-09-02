import aiosqlite

from ._common import DB_PATH

__all__ = [
    "add_letter",
    "get_letter",
    "set_letter_admin_message",
    "hide_letter",
    "unhide_letter",
]


async def add_letter(sender_id: int, title: str, body: str, is_anonymous: bool = True) -> int:
    """お便りをDBに保存し、letter_id を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO letters (sender_id, title, body, is_anonymous) VALUES (?, ?, ?, ?)",
            (sender_id, title, body, int(is_anonymous))
        )
        await db.commit()
        return cursor.lastrowid

async def get_letter(letter_id: int):
    """指定IDのお便りを取得（管理者用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM letters WHERE letter_id = ?", (letter_id,)) as cursor:
            return await cursor.fetchone()

async def set_letter_admin_message(letter_id: int, message_id: int) -> None:
    """管理チャンネルに投稿したお便りのメッセージIDを記録する"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE letters SET admin_message_id = ? WHERE letter_id = ?",
            (message_id, letter_id)
        )
        await db.commit()

async def hide_letter(letter_id: int) -> None:
    """お便りを非表示状態にする"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE letters SET is_hidden = 1 WHERE letter_id = ?",
            (letter_id,)
        )
        await db.commit()

async def unhide_letter(letter_id: int) -> None:
    """お便りの非表示状態を解除する"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE letters SET is_hidden = 0 WHERE letter_id = ?",
            (letter_id,)
        )
        await db.commit()
