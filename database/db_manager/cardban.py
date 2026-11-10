"""カードBAN10先（先に規定数勝った方が勝ち。1戦ごとに勝者が敗者のカードを使用不可にする企画）"""
import json

import aiosqlite

from ._common import DB_PATH

__all__ = [
    "replace_cardban_cards",
    "get_cardban_cards",
    "count_cardban_cards",
    "get_cardban_settings",
    "save_cardban_settings",
    "upsert_cardban_entry",
    "remove_cardban_entry",
    "get_cardban_entry",
    "get_cardban_entries",
    "create_cardban_match",
    "get_cardban_match",
    "get_cardban_match_by_thread",
    "get_active_cardban_match_for_user",
    "get_open_cardban_matches",
    "update_cardban_match",
    "record_cardban_loss",
    "apply_cardban_bans",
    "undo_last_cardban_game",
    "get_cardban_games",
    "get_cardban_bans",
    "get_due_cardban_reminders",
]

# 対戦が「進行中」とみなす状態（エントリーや新しい対戦を重複させない）
_OPEN_STATUSES = ("pending_accept", "active")


def _row(row) -> dict | None:
    return dict(row) if row else None


# ── カード一覧 ─────────────────────────────────

async def replace_cardban_cards(cards: list[dict]) -> None:
    """カード一覧を丸ごと入れ替える。cards は card_key/category/character/name/cost を持つdictのリスト"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM cardban_cards")
        await db.executemany(
            """INSERT INTO cardban_cards (card_key, category, character, name, cost, sort_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (c["card_key"], c["category"], c["character"], c["name"], c.get("cost"), i)
                for i, c in enumerate(cards)
            ],
        )
        await db.commit()


async def get_cardban_cards(character: str | None = None, include_system: bool = True) -> list[dict]:
    """カードを取り込み順で返す。character を指定するとそのキャラのスキル・スペル（＋システム）だけ"""
    query = "SELECT * FROM cardban_cards"
    params: list = []
    if character is not None:
        if include_system:
            query += " WHERE character = ? OR category = 'system'"
        else:
            query += " WHERE character = ?"
        params.append(character)
    query += " ORDER BY sort_order"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def count_cardban_cards() -> dict:
    """{'system': n, 'skill': n, 'spell': n} を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT category, COUNT(*) FROM cardban_cards GROUP BY category"
        ) as cursor:
            rows = await cursor.fetchall()
    counts = {"system": 0, "skill": 0, "spell": 0}
    counts.update({r[0]: r[1] for r in rows})
    return counts


# ── 設定 ─────────────────────────────────────

async def get_cardban_settings(guild_id: int) -> dict:
    """未設定でも既定値（10先・1戦1枚・最初から抜くカードなし）を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cardban_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
    settings = dict(row) if row else {
        "guild_id": guild_id,
        "panel_channel_id": None,
        "panel_message_id": None,
        "target_wins": 10,
        "bans_per_game": 1,
        "preban": "[]",
    }
    settings["preban"] = json.loads(settings["preban"] or "[]")
    return settings


async def save_cardban_settings(guild_id: int, **fields) -> None:
    """指定したフィールドだけ更新する。preban はリストで渡す"""
    if not fields:
        return
    if "preban" in fields:
        fields["preban"] = json.dumps(fields["preban"], ensure_ascii=False)
    columns = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    updates = ", ".join(f"{k}=excluded.{k}" for k in fields)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"""INSERT INTO cardban_settings (guild_id, {columns})
                VALUES (?, {placeholders})
                ON CONFLICT(guild_id) DO UPDATE SET {updates}""",
            (guild_id, *fields.values()),
        )
        await db.commit()


# ── エントリー（対戦待ち） ───────────────────────

async def upsert_cardban_entry(guild_id: int, user_id: int, character: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO cardban_entries (guild_id, user_id, character) VALUES (?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET character=excluded.character""",
            (guild_id, user_id, character),
        )
        await db.commit()


async def remove_cardban_entry(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM cardban_entries WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_cardban_entry(guild_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cardban_entries WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ) as cursor:
            return _row(await cursor.fetchone())


async def get_cardban_entries(guild_id: int) -> list[dict]:
    """エントリーの古い順"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cardban_entries WHERE guild_id = ? ORDER BY created_at, rowid", (guild_id,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


# ── 対戦 ─────────────────────────────────────

async def create_cardban_match(
    guild_id: int,
    player1_id: int,
    player2_id: int,
    char1: str,
    char2: str,
    target_wins: int,
    bans_per_game: int,
    preban: list[str],
    status: str,
) -> int | None:
    """対戦を作り、2人のエントリーを外す。どちらかが進行中の対戦を持っていれば作らずに None を返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            f"""SELECT 1 FROM cardban_matches
                WHERE guild_id = ? AND status IN ({",".join("?" for _ in _OPEN_STATUSES)})
                  AND (player1_id IN (?, ?) OR player2_id IN (?, ?))""",
            (guild_id, *_OPEN_STATUSES, player1_id, player2_id, player1_id, player2_id),
        ) as cursor:
            if await cursor.fetchone():
                await db.rollback()
                return None
        cursor = await db.execute(
            """INSERT INTO cardban_matches
               (guild_id, player1_id, player2_id, char1, char2, target_wins, bans_per_game, preban, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, player1_id, player2_id, char1, char2, target_wins, bans_per_game,
             json.dumps(preban, ensure_ascii=False), status),
        )
        match_id = cursor.lastrowid
        await db.execute(
            "DELETE FROM cardban_entries WHERE guild_id = ? AND user_id IN (?, ?)",
            (guild_id, player1_id, player2_id),
        )
        await db.commit()
        return match_id


def _decode_match(row) -> dict | None:
    if not row:
        return None
    match = dict(row)
    match["preban"] = json.loads(match["preban"] or "[]")
    return match


async def get_cardban_match(match_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cardban_matches WHERE match_id = ?", (match_id,)) as cursor:
            return _decode_match(await cursor.fetchone())


async def get_cardban_match_by_thread(thread_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cardban_matches WHERE thread_id = ?", (thread_id,)) as cursor:
            return _decode_match(await cursor.fetchone())


async def get_active_cardban_match_for_user(guild_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT * FROM cardban_matches
                WHERE guild_id = ? AND status IN ({",".join("?" for _ in _OPEN_STATUSES)})
                  AND (player1_id = ? OR player2_id = ?)
                ORDER BY match_id DESC LIMIT 1""",
            (guild_id, *_OPEN_STATUSES, user_id, user_id),
        ) as cursor:
            return _decode_match(await cursor.fetchone())


async def get_open_cardban_matches(guild_id: int) -> list[dict]:
    """承諾待ち・進行中の対戦（古い順）"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT * FROM cardban_matches
                WHERE guild_id = ? AND status IN ({",".join("?" for _ in _OPEN_STATUSES)})
                ORDER BY match_id""",
            (guild_id, *_OPEN_STATUSES),
        ) as cursor:
            return [_decode_match(r) for r in await cursor.fetchall()]


_UPDATABLE = {
    "thread_id", "status", "status_message_id", "proposed_at", "proposed_by", "scheduled_at",
    "reminded_before", "reminded_start", "pending_ban_by", "winner_id", "finished_at",
}


async def update_cardban_match(match_id: int, expected_status: str | None = None, **fields) -> bool:
    """指定フィールドを更新する。expected_status を渡すと、その状態のときだけ更新する（二重押し対策）"""
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError(f"更新できない列です: {unknown}")
    sets = ", ".join(f"{k} = ?" for k in fields)
    query = f"UPDATE cardban_matches SET {sets} WHERE match_id = ?"
    params = [*fields.values(), match_id]
    if expected_status is not None:
        query += " AND status = ?"
        params.append(expected_status)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.rowcount > 0


async def record_cardban_loss(match_id: int, loser_id: int) -> dict | None:
    """敗者の自己申告で1戦を記録する。

    BAN待ちが残っている・進行中でないなどで記録できなければ None。
    記録できたら {'game_id', 'game_no', 'winner_id', 'finished'} を返す。
    先取数に届いたら対戦を終了にし、届かなければ勝者をBAN待ちにする。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT * FROM cardban_matches WHERE match_id = ?", (match_id,)) as cursor:
            match = await cursor.fetchone()
        if (
            match is None
            or match["status"] != "active"
            or match["pending_ban_by"] is not None
            or loser_id not in (match["player1_id"], match["player2_id"])
        ):
            await db.rollback()
            return None

        if loser_id == match["player1_id"]:
            winner_id = match["player2_id"]
            score1, score2 = match["score1"], match["score2"] + 1
            winner_score = score2
        else:
            winner_id = match["player1_id"]
            score1, score2 = match["score1"] + 1, match["score2"]
            winner_score = score1
        game_no = match["score1"] + match["score2"] + 1
        cursor = await db.execute(
            "INSERT INTO cardban_games (match_id, game_no, winner_id, loser_id) VALUES (?, ?, ?, ?)",
            (match_id, game_no, winner_id, loser_id),
        )
        game_id = cursor.lastrowid

        finished = winner_score >= match["target_wins"]
        if finished:
            await db.execute(
                """UPDATE cardban_matches SET score1 = ?, score2 = ?, status = 'finished',
                   winner_id = ?, pending_ban_by = NULL, finished_at = CURRENT_TIMESTAMP
                   WHERE match_id = ?""",
                (score1, score2, winner_id, match_id),
            )
        else:
            await db.execute(
                "UPDATE cardban_matches SET score1 = ?, score2 = ?, pending_ban_by = ? WHERE match_id = ?",
                (score1, score2, winner_id, match_id),
            )
        await db.commit()
        return {"game_id": game_id, "game_no": game_no, "winner_id": winner_id, "finished": finished}


async def apply_cardban_bans(match_id: int, banned_by: int, cards: list[dict]) -> bool:
    """BAN待ちの勝者が選んだカードを記録し、BAN待ちを解除する。

    cards が空ならBANなし（敗者に抜けるカードが残っていないとき）で解除だけする。
    もう解除済み・BANする番の人ではない・選んだカードが既にBAN済みなら False。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT * FROM cardban_matches WHERE match_id = ?", (match_id,)) as cursor:
            match = await cursor.fetchone()
        if match is None or match["status"] != "active" or match["pending_ban_by"] != banned_by:
            await db.rollback()
            return False
        target_id = match["player2_id"] if banned_by == match["player1_id"] else match["player1_id"]

        async with db.execute(
            "SELECT card_key FROM cardban_bans WHERE match_id = ? AND target_id = ?", (match_id, target_id)
        ) as cursor:
            already = {r["card_key"] for r in await cursor.fetchall()}
        if any(c["card_key"] in already for c in cards):
            await db.rollback()
            return False

        async with db.execute(
            "SELECT game_id FROM cardban_games WHERE match_id = ? ORDER BY game_no DESC LIMIT 1", (match_id,)
        ) as cursor:
            game = await cursor.fetchone()
        await db.executemany(
            """INSERT INTO cardban_bans (match_id, game_id, banned_by, target_id, card_key, category, card_name)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (match_id, game["game_id"], banned_by, target_id, c["card_key"], c["category"], c["name"])
                for c in cards
            ],
        )
        await db.execute("UPDATE cardban_matches SET pending_ban_by = NULL WHERE match_id = ?", (match_id,))
        await db.commit()
        return True


async def undo_last_cardban_game(match_id: int) -> dict | None:
    """最後の1戦の記録と、その戦で選ばれたBANを取り消す。終了済みの対戦なら進行中に戻す。

    取り消した試合 {'game_no', 'winner_id', 'loser_id', 'bans': n} を返す。取り消すものが無ければ None。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute("SELECT * FROM cardban_matches WHERE match_id = ?", (match_id,)) as cursor:
            match = await cursor.fetchone()
        if match is None or match["status"] not in ("active", "finished"):
            await db.rollback()
            return None
        async with db.execute(
            "SELECT * FROM cardban_games WHERE match_id = ? ORDER BY game_no DESC LIMIT 1", (match_id,)
        ) as cursor:
            game = await cursor.fetchone()
        if game is None:
            await db.rollback()
            return None

        cursor = await db.execute("DELETE FROM cardban_bans WHERE game_id = ?", (game["game_id"],))
        removed_bans = cursor.rowcount
        await db.execute("DELETE FROM cardban_games WHERE game_id = ?", (game["game_id"],))
        score1 = match["score1"] - (1 if game["winner_id"] == match["player1_id"] else 0)
        score2 = match["score2"] - (1 if game["winner_id"] == match["player2_id"] else 0)
        await db.execute(
            """UPDATE cardban_matches SET score1 = ?, score2 = ?, status = 'active',
               pending_ban_by = NULL, winner_id = NULL, finished_at = NULL
               WHERE match_id = ?""",
            (score1, score2, match_id),
        )
        await db.commit()
        return {
            "game_no": game["game_no"],
            "winner_id": game["winner_id"],
            "loser_id": game["loser_id"],
            "bans": removed_bans,
        }


async def get_cardban_games(match_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM cardban_games WHERE match_id = ? ORDER BY game_no", (match_id,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_cardban_bans(match_id: int) -> list[dict]:
    """BANを古い順で、何戦目のBANかも付けて返す"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT b.*, g.game_no FROM cardban_bans b
               JOIN cardban_games g ON g.game_id = b.game_id
               WHERE b.match_id = ? ORDER BY g.game_no, b.ban_id""",
            (match_id,),
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]


async def get_due_cardban_reminders(soon_str: str, now_str: str) -> list[dict]:
    """日程が決まった進行中の対戦のうち、事前通知（soon_str 以前に開始）か開始通知（now_str 以前に開始）が未送信のもの"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM cardban_matches
               WHERE status = 'active' AND scheduled_at IS NOT NULL AND thread_id IS NOT NULL
                 AND ((reminded_before = 0 AND scheduled_at <= ?)
                   OR (reminded_start = 0 AND scheduled_at <= ?))""",
            (soon_str, now_str),
        ) as cursor:
            return [_decode_match(r) for r in await cursor.fetchall()]
