import json

import aiosqlite

from ._common import DB_PATH

__all__ = [
    "create_survey",
    "get_survey",
    "get_active_surveys",
    "add_survey_response",
    "get_survey_responses",
    "has_survey_responded",
    "close_survey",
]


async def create_survey(survey_id: str, channel_id: int, creator_id: int, title: str, questions: list) -> None:
    """テキスト回答式アンケートをDBに保存する"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO surveys (survey_id, channel_id, creator_id, title, questions) VALUES (?, ?, ?, ?, ?)",
            (survey_id, channel_id, creator_id, title, json.dumps(questions, ensure_ascii=False))
        )
        await db.commit()

async def get_survey(survey_id: str):
    """指定IDのアンケートを取得する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM surveys WHERE survey_id = ?", (survey_id,)) as cursor:
            return await cursor.fetchone()

async def get_active_surveys() -> list:
    """アクティブなアンケートを全件取得する（Bot再起動時のView再登録用）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM surveys WHERE is_active = 1") as cursor:
            return await cursor.fetchall()

async def add_survey_response(survey_id: str, user_id: int, answers: list) -> None:
    """アンケートへの回答を保存する"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO survey_responses (survey_id, user_id, answers) VALUES (?, ?, ?)",
            (survey_id, user_id, json.dumps(answers, ensure_ascii=False))
        )
        await db.commit()

async def get_survey_responses(survey_id: str) -> list:
    """アンケートの全回答を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM survey_responses WHERE survey_id = ? ORDER BY created_at",
            (survey_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def has_survey_responded(survey_id: str, user_id: int) -> bool:
    """指定ユーザーがすでに回答済みかどうかを返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM survey_responses WHERE survey_id = ? AND user_id = ?",
            (survey_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None

async def close_survey(survey_id: str) -> None:
    """アンケートを締め切る"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE surveys SET is_active = 0 WHERE survey_id = ?", (survey_id,))
        await db.commit()
