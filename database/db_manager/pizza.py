import aiosqlite

from ._common import DB_PATH

__all__ = ["add_pizza", "get_random_pizza", "get_all_pizzas", "delete_pizza"]


async def add_pizza(name: str, description: str, rating: int, added_by: int) -> int:
    """ピザを登録し、pizza_id を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO pizzas (name, description, rating, added_by) VALUES (?, ?, ?, ?)",
            (name, description, rating, added_by)
        )
        await db.commit()
        return cursor.lastrowid

async def get_random_pizza() -> dict | None:
    """ランダムにピザを1件取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pizzas ORDER BY RANDOM() LIMIT 1") as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_pizzas() -> list:
    """全ピザを取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM pizzas ORDER BY created_at DESC") as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def delete_pizza(pizza_id: int) -> bool:
    """指定IDのピザを削除する。削除成功ならTrueを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("DELETE FROM pizzas WHERE pizza_id = ?", (pizza_id,)) as cursor:
            await db.commit()
            return cursor.rowcount > 0
