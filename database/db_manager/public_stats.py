import aiosqlite

from ._common import DB_PATH

__all__ = ["get_rated_player_ratings", "get_main_character_counts"]


async def get_rated_player_ratings() -> list[float]:
    """有頂天の塔にプロフィール登録済みのプレイヤーのレート一覧を返す（個人を特定できる情報は含めない）"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT u.rating FROM users u
               JOIN rating_profiles p ON p.user_id = u.user_id"""
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]


async def get_main_character_counts() -> list[tuple[str, int]]:
    """メインキャラクターごとの登録人数を、人数の多い順に返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT character, COUNT(*) AS n FROM main_characters
               GROUP BY character ORDER BY n DESC, character"""
        ) as cursor:
            return [(row[0], row[1]) for row in await cursor.fetchall()]
