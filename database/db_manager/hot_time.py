import aiosqlite

from ._common import DB_PATH

__all__ = [
    "HOT_TIME_KINDS",
    "set_hot_time_settings",
    "get_hot_time_settings",
    "get_hot_time_setting",
    "delete_hot_time_settings",
    "mark_hot_time_posted",
    "get_hot_time_summary",
    "count_recruiting_threads",
]

# 自動投稿の種類（朝の予告・開始通知・終了後のまとめ）。各列には投稿済みのHOT TIME開催日（木曜, YYYY-MM-DD）を入れる
HOT_TIME_KINDS = ("morning", "start", "summary")

# 確定済みの対戦を「自分視点」で1試合につき2行に展開して集計する
_SUMMARY_SQL = """
WITH m AS (
    SELECT player1_id AS me, player2_id AS opp, rating_change1 AS diff
    FROM matches
    WHERE is_confirmed = 1 AND player1_id != player2_id
      AND created_at >= ? AND created_at < ?
    UNION ALL
    SELECT player2_id, player1_id, rating_change2
    FROM matches
    WHERE is_confirmed = 1 AND player1_id != player2_id
      AND created_at >= ? AND created_at < ?
)
SELECT m.me AS user_id, u.username AS username,
       COUNT(*) AS matches, COALESCE(SUM(m.diff), 0) AS rating_gain
FROM m JOIN users u ON u.user_id = m.me
GROUP BY m.me
"""


async def _ensure_table(db):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS hot_time_settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            role_id INTEGER,
            last_morning_date TEXT,
            last_start_date TEXT,
            last_summary_date TEXT
        )
    """)


async def set_hot_time_settings(guild_id: int, channel_id: int, role_id: int | None, posted: dict[str, str | None]):
    """HOT TIMEの投稿先と通知ロールを設定する。posted は種類ごとの「投稿済み扱いにする開催日」"""
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_table(db)
        await db.execute(
            """INSERT INTO hot_time_settings
               (guild_id, channel_id, role_id, last_morning_date, last_start_date, last_summary_date)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
               channel_id = excluded.channel_id,
               role_id = excluded.role_id,
               last_morning_date = MAX(COALESCE(last_morning_date, ''), COALESCE(excluded.last_morning_date, '')),
               last_start_date = MAX(COALESCE(last_start_date, ''), COALESCE(excluded.last_start_date, '')),
               last_summary_date = MAX(COALESCE(last_summary_date, ''), COALESCE(excluded.last_summary_date, ''))""",
            (guild_id, channel_id, role_id, posted.get("morning"), posted.get("start"), posted.get("summary")),
        )
        await db.commit()


async def get_hot_time_settings() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_table(db)
        async with db.execute("SELECT * FROM hot_time_settings") as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_hot_time_setting(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_table(db)
        async with db.execute("SELECT * FROM hot_time_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_hot_time_settings(guild_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_table(db)
        async with db.execute("DELETE FROM hot_time_settings WHERE guild_id = ?", (guild_id,)) as cursor:
            await db.commit()
            return cursor.rowcount > 0


async def mark_hot_time_posted(guild_id: int, kind: str, date: str):
    if kind not in HOT_TIME_KINDS:
        raise ValueError(f"unknown hot time kind: {kind}")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE hot_time_settings SET last_{kind}_date = ? WHERE guild_id = ?", (date, guild_id))
        await db.commit()


async def get_hot_time_summary(start: str, end: str) -> list[dict]:
    """start〜end（UTC, DBのcreated_atと同じ形式）に報告された確定済み戦績を、ユーザーごとに集計して返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(_SUMMARY_SQL, (start, end, start, end)) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def count_recruiting_threads() -> int:
    """対戦募集（フォーラム）で、まだ相手が決まっていない募集の数"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM recruit_threads WHERE status = 'recruiting'") as cursor:
            return (await cursor.fetchone())[0]
