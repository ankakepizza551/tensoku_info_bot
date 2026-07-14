import datetime
import json

import aiosqlite

from ._common import DB_PATH

__all__ = [
    "create_poll",
    "get_poll",
    "get_active_polls",
    "toggle_poll_vote",
    "get_poll_votes",
    "get_user_poll_votes",
    "set_single_poll_vote",
    "clear_poll_votes",
    "get_expired_polls",
    "close_poll",
]


async def create_poll(poll_id: str, channel_id: int, creator_id: int, question: str, options: list, allow_multiple: bool = True, is_anonymous: bool = True, deadline: str | None = None) -> None:
    """投票アンケートをDBに保存する"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO polls (poll_id, channel_id, creator_id, question, options, allow_multiple, is_anonymous, deadline) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (poll_id, channel_id, creator_id, question, json.dumps(options, ensure_ascii=False), int(allow_multiple), int(is_anonymous), deadline)
        )
        await db.commit()

async def get_poll(poll_id: str):
    """指定IDの投票アンケートを取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM polls WHERE poll_id = ?", (poll_id,)) as cursor:
            return await cursor.fetchone()

async def get_active_polls() -> list:
    """アクティブな投票アンケートを全件取得する（Bot再起動時のView再登録用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM polls WHERE is_active = 1") as cursor:
            return await cursor.fetchall()

async def toggle_poll_vote(poll_id: str, user_id: int, option_index: int) -> bool:
    """投票をトグルする。追加した場合はTrue、取り消した場合はFalseを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM poll_votes WHERE poll_id = ? AND user_id = ? AND option_index = ?",
            (poll_id, user_id, option_index)
        ) as cursor:
            exists = await cursor.fetchone()

        if exists:
            await db.execute(
                "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ? AND option_index = ?",
                (poll_id, user_id, option_index)
            )
            await db.commit()
            return False
        else:
            await db.execute(
                "INSERT INTO poll_votes (poll_id, user_id, option_index) VALUES (?, ?, ?)",
                (poll_id, user_id, option_index)
            )
            await db.commit()
            return True

async def get_poll_votes(poll_id: str) -> list:
    """指定アンケートの全投票レコードを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT user_id, option_index FROM poll_votes WHERE poll_id = ?", (poll_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_user_poll_votes(poll_id: str, user_id: int) -> list:
    """指定ユーザーが投票済みのoption_indexリストを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT option_index FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        ) as cursor:
            rows = await cursor.fetchall()
        return [r[0] for r in rows]

async def set_single_poll_vote(poll_id: str, user_id: int, option_index: int) -> bool:
    """単一選択モード用。既存投票を全削除し指定選択肢に投票。同じ選択肢なら取り消しのみ。"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT option_index FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        ) as cursor:
            existing = await cursor.fetchone()

        already_voted_same = existing is not None and existing[0] == option_index

        await db.execute(
            "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        )
        if not already_voted_same:
            await db.execute(
                "INSERT INTO poll_votes (poll_id, user_id, option_index) VALUES (?, ?, ?)",
                (poll_id, user_id, option_index)
            )
        await db.commit()
        return not already_voted_same

async def clear_poll_votes(poll_id: str, user_id: int) -> int:
    """指定ユーザーのそのアンケートへの投票をすべて取り消す。削除件数を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        )
        await db.commit()
        return cursor.rowcount

async def get_expired_polls() -> list:
    """期限切れかつアクティブな投票アンケートを全件取得する"""
    JST = datetime.timezone(datetime.timedelta(hours=9))
    now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM polls WHERE is_active = 1 AND deadline IS NOT NULL AND deadline <= ?",
            (now_str,)
        ) as cursor:
            return await cursor.fetchall()

async def close_poll(poll_id: str) -> None:
    """投票アンケートを締め切る"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE polls SET is_active = 0 WHERE poll_id = ?", (poll_id,))
        await db.commit()
