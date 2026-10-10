import aiosqlite

from ._common import DB_PATH

__all__ = ["get_rated_player_ratings", "get_main_character_counts", "get_public_events"]


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


async def get_public_events(guild_id: int | None = None) -> list[dict]:
    """公開カレンダー用の予定一覧を日付順に返す。guild_id を指定するとそのサーバーだけに絞る"""
    query = "SELECT event_id, date, name, type, time, location, url, hosted FROM events"
    params: tuple = ()
    if guild_id:
        query += " WHERE guild_id = ?"
        params = (guild_id,)
    query += " ORDER BY date, time"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            return [dict(r) for r in await cursor.fetchall()]
