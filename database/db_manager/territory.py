import aiosqlite

from ._common import DB_PATH

__all__ = [
    "save_territory_profile",
    "get_territory_profile",
    "get_all_territory_profiles",
    "delete_territory_profile",
    "clear_territory_teams",
    "add_territory_team_member",
    "get_territory_teams",
    "get_territory_team_of_user",
    "add_territory_match",
    "get_territory_match",
    "delete_territory_match",
    "get_territory_matches",
    "get_territory_fought_user_ids",
    "get_territory_invasion_totals",
    "init_territory_grid",
    "get_territory_grid",
    "set_territory_grid_cell",
    "save_territory_settings",
    "get_territory_settings",
    "save_territory_team_role",
    "get_territory_team_roles",
    "clear_territory_team_roles",
    "clear_territory_matches",
    "clear_territory_grid",
    "clear_all_territory_profiles",
    "clear_territory_participant_channels",
]


async def save_territory_profile(
    user_id: int, username: str, strength: int, ip_info: str,
    autopunch: str, giuroll: str, comment: str = "",
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO territory_profiles
               (user_id, username, strength, ip_info, autopunch, giuroll, comment, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(user_id) DO UPDATE SET
               username=excluded.username,
               strength=excluded.strength,
               ip_info=excluded.ip_info,
               autopunch=excluded.autopunch,
               giuroll=excluded.giuroll,
               comment=excluded.comment,
               updated_at=CURRENT_TIMESTAMP""",
            (user_id, username, strength, ip_info, autopunch, giuroll, comment),
        )
        await db.commit()

async def get_territory_profile(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_profiles WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_territory_profiles() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_profiles ORDER BY strength DESC, username ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def delete_territory_profile(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM territory_profiles WHERE user_id = ?", (user_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def clear_territory_teams(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM territory_teams WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def add_territory_team_member(
    guild_id: int, team_index: int, user_id: int, username: str, strength: int, is_captain: bool
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO territory_teams
               (guild_id, team_index, user_id, username, strength, is_captain)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, team_index, user_id, username, strength, int(is_captain)),
        )
        await db.commit()

async def get_territory_teams(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM territory_teams WHERE guild_id = ?
               ORDER BY team_index, is_captain DESC, strength DESC""",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_territory_team_of_user(guild_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_teams WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def add_territory_match(
    guild_id: int, reporter_id: int, winner_id: int, loser_id: int,
    winner_team: int, loser_team: int, invasion_score: int, captain_defeated: bool,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO territory_matches
               (guild_id, reporter_id, winner_id, loser_id, winner_team, loser_team, invasion_score, captain_defeated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, reporter_id, winner_id, loser_id, winner_team, loser_team,
             invasion_score, int(captain_defeated)),
        )
        await db.commit()
        return cursor.lastrowid

async def get_territory_match(match_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_matches WHERE match_id = ?", (match_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def delete_territory_match(match_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "DELETE FROM territory_matches WHERE match_id = ?", (match_id,)
        ) as cursor:
            await db.commit()
            return cursor.rowcount > 0

async def get_territory_matches(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_matches WHERE guild_id = ? ORDER BY created_at",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_territory_fought_user_ids(guild_id: int) -> set:
    matches = await get_territory_matches(guild_id)
    fought = set()
    for m in matches:
        fought.add(m["winner_id"])
        fought.add(m["loser_id"])
    return fought

async def get_territory_invasion_totals(guild_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT winner_team, SUM(invasion_score) as total
               FROM territory_matches WHERE guild_id = ? GROUP BY winner_team""",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return {r["winner_team"]: r["total"] for r in rows}

def _territory_grid_layout(team_count: int) -> list:
    """5x5グリッド(25マス、行優先インデックス0〜24)の初期配置を返す"""
    if team_count == 2:
        # 上(13マス) / 下(12マス) の分割
        return [0 if i < 13 else 1 for i in range(25)]

    # 4チーム: 四隅から各6マス程度の連結した領域に分割
    layout = []
    for r in range(5):
        for c in range(5):
            if r < 2 and c < 2:
                q = 0
            elif r < 2 and c > 2:
                q = 1
            elif r > 2 and c < 2:
                q = 2
            elif r > 2 and c > 2:
                q = 3
            elif r == 2 and c < 2:
                q = 2 if c == 0 else 0
            elif r == 2 and c > 2:
                q = 1 if c == 3 else 3
            elif c == 2 and r < 2:
                q = 0 if r == 0 else 1
            elif c == 2 and r > 2:
                q = 2 if r == 3 else 3
            else:
                q = 0  # 中央マス(2,2)
            layout.append(q)
    return layout

async def init_territory_grid(guild_id: int, team_count: int) -> None:
    assignment = _territory_grid_layout(team_count)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM territory_grid WHERE guild_id = ?", (guild_id,))
        await db.executemany(
            "INSERT INTO territory_grid (guild_id, cell_index, team_index) VALUES (?, ?, ?)",
            [(guild_id, idx, team) for idx, team in enumerate(assignment)],
        )
        await db.commit()

async def get_territory_grid(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_grid WHERE guild_id = ? ORDER BY cell_index", (guild_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def set_territory_grid_cell(guild_id: int, cell_index: int, team_index: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO territory_grid (guild_id, cell_index, team_index)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id, cell_index) DO UPDATE SET team_index=excluded.team_index""",
            (guild_id, cell_index, team_index),
        )
        await db.commit()

async def save_territory_settings(
    guild_id: int,
    participant_role_id: int = None,
    team_category_id: int = None,
    participant_channel_id: int = None,
    participant_voice_channel_id: int = None,
    reception_channel_id: int = None,
    hq_channel_id: int = None,
) -> None:
    """指定したフィールドのみ更新する。未指定(None)の場合は既存値を維持する"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            existing = await cursor.fetchone()

        new_participant = (
            participant_role_id if participant_role_id is not None
            else (existing["participant_role_id"] if existing else None)
        )
        new_category = (
            team_category_id if team_category_id is not None
            else (existing["team_category_id"] if existing else None)
        )
        new_channel = (
            participant_channel_id if participant_channel_id is not None
            else (existing["participant_channel_id"] if existing else None)
        )
        new_voice_channel = (
            participant_voice_channel_id if participant_voice_channel_id is not None
            else (existing["participant_voice_channel_id"] if existing else None)
        )
        new_reception_channel = (
            reception_channel_id if reception_channel_id is not None
            else (existing["reception_channel_id"] if existing else None)
        )
        new_hq_channel = (
            hq_channel_id if hq_channel_id is not None
            else (existing["hq_channel_id"] if existing else None)
        )

        await db.execute(
            """INSERT INTO territory_settings
               (guild_id, participant_role_id, team_category_id, participant_channel_id,
                participant_voice_channel_id, reception_channel_id, hq_channel_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
               participant_role_id=excluded.participant_role_id,
               team_category_id=excluded.team_category_id,
               participant_channel_id=excluded.participant_channel_id,
               participant_voice_channel_id=excluded.participant_voice_channel_id,
               reception_channel_id=excluded.reception_channel_id,
               hq_channel_id=excluded.hq_channel_id""",
            (guild_id, new_participant, new_category, new_channel, new_voice_channel,
             new_reception_channel, new_hq_channel),
        )
        await db.commit()

async def get_territory_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

async def save_territory_team_role(
    guild_id: int, team_index: int, role_id: int = None, channel_id: int = None, voice_channel_id: int = None
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO territory_team_roles (guild_id, team_index, role_id, channel_id, voice_channel_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id, team_index) DO UPDATE SET
               role_id=excluded.role_id, channel_id=excluded.channel_id, voice_channel_id=excluded.voice_channel_id""",
            (guild_id, team_index, role_id, channel_id, voice_channel_id),
        )
        await db.commit()

async def get_territory_team_roles(guild_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM territory_team_roles WHERE guild_id = ? ORDER BY team_index",
            (guild_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def clear_territory_team_roles(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM territory_team_roles WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def clear_territory_matches(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM territory_matches WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def clear_territory_grid(guild_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM territory_grid WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def clear_all_territory_profiles() -> None:
    """陣取りゲームの登録プロフィールを全件削除する。

    territory_profiles はギルドに紐付いていない（user_idのみで管理）ため、
    このBotが複数サーバーで稼働している場合は全サーバー分がリセットされる点に注意。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM territory_profiles")
        await db.commit()

async def clear_territory_participant_channels(guild_id: int) -> None:
    """参加者共通の雑談ch・VCのIDのみをクリアする（参加者ロール自体は維持）"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE territory_settings
               SET participant_channel_id = NULL, participant_voice_channel_id = NULL
               WHERE guild_id = ?""",
            (guild_id,),
        )
        await db.commit()
