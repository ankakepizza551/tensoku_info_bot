import datetime

import aiosqlite

from ._common import DB_PATH

__all__ = [
    "MVP_DAILY_PAIR_CAP",
    "month_bounds_jst",
    "get_monthly_mvp",
    "set_mvp_channel",
    "get_mvp_settings",
    "mark_mvp_posted",
]

JST = datetime.timezone(datetime.timedelta(hours=9))

# 同じ相手との対戦は、1日あたりこの回数までしかカウントしない（身内での回し続けによる水増し防止）
MVP_DAILY_PAIR_CAP = 5

# 確定済みの対戦を「自分視点」で1試合につき2行に展開し、(自分, 相手, 日) ごとに上限までに絞って集計する。
# created_at は UTC 保存なので、日の区切りは JST に直して判定する。
_MVP_SQL = """
WITH m AS (
    SELECT match_id, player1_id AS me, player2_id AS opp,
           CASE WHEN score1 > score2 THEN 1 ELSE 0 END AS win,
           date(created_at, '+9 hours') AS d
    FROM matches
    WHERE is_confirmed = 1 AND player1_id != player2_id
      AND created_at >= ? AND created_at < ?
    UNION ALL
    SELECT match_id, player2_id, player1_id,
           CASE WHEN score2 > score1 THEN 1 ELSE 0 END,
           date(created_at, '+9 hours')
    FROM matches
    WHERE is_confirmed = 1 AND player1_id != player2_id
      AND created_at >= ? AND created_at < ?
),
capped AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY me, opp, d ORDER BY match_id) AS rn
    FROM m
)
SELECT c.me AS user_id, u.username AS username,
       COUNT(*) AS matches, SUM(c.win) AS wins, COUNT(DISTINCT c.opp) AS opponents
FROM capped c JOIN users u ON u.user_id = c.me
WHERE c.rn <= ?
GROUP BY c.me
"""


def month_bounds_jst(month: str) -> tuple[str, str]:
    """'YYYY-MM' を、JSTの月初〜翌月初に相当するUTC文字列（DBのcreated_atと同じ形式）にして返す"""
    year, mon = (int(x) for x in month.split("-"))
    start = datetime.datetime(year, mon, 1, tzinfo=JST)
    end = datetime.datetime(year + (mon == 12), mon % 12 + 1, 1, tzinfo=JST)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (
        start.astimezone(datetime.timezone.utc).strftime(fmt),
        end.astimezone(datetime.timezone.utc).strftime(fmt),
    )


def _top3(rows: list[dict], key: str) -> list[dict]:
    """key の降順で上位3位までを返す。同数は同順位とし、その分は3名を超えて載せる。0は除く"""
    values = [r[key] for r in rows if r[key] > 0]
    result = []
    for r in sorted(rows, key=lambda r: (-r[key], r["username"])):
        if r[key] <= 0:
            continue
        rank = 1 + sum(1 for v in values if v > r[key])
        if rank > 3:
            break
        result.append({"rank": rank, "user_id": r["user_id"], "username": r["username"], "value": r[key]})
    return result


async def get_monthly_mvp(month: str) -> dict:
    """指定月('YYYY-MM', JST)の対戦数・勝利数・対戦相手数の上位3名を返す"""
    start, end = month_bounds_jst(month)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(_MVP_SQL, (start, end, start, end, MVP_DAILY_PAIR_CAP)) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]
    return {
        "month": month,
        "matches": _top3(rows, "matches"),
        "wins": _top3(rows, "wins"),
        "opponents": _top3(rows, "opponents"),
    }


async def _ensure_table(db):
    await db.execute("""
        CREATE TABLE IF NOT EXISTS mvp_settings (
            guild_id INTEGER PRIMARY KEY,
            channel_id INTEGER NOT NULL,
            last_posted_month TEXT
        )
    """)


async def set_mvp_channel(guild_id: int, channel_id: int, last_posted_month: str):
    """月間MVPの自動投稿先を設定する。last_posted_month 以前の月は自動投稿の対象外になる"""
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_table(db)
        await db.execute(
            """INSERT INTO mvp_settings (guild_id, channel_id, last_posted_month) VALUES (?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id""",
            (guild_id, channel_id, last_posted_month),
        )
        await db.commit()


async def get_mvp_settings() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await _ensure_table(db)
        async with db.execute("SELECT * FROM mvp_settings") as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def mark_mvp_posted(guild_id: int, month: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE mvp_settings SET last_posted_month = ? WHERE guild_id = ?", (month, guild_id))
        await db.commit()
