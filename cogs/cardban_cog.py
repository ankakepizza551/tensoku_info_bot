"""カードBAN10先

先に規定数（既定10）勝った方が勝ち。1戦ごとに、負けた方が勝った方のカードを規定枚数（既定1枚）使用不可にする。
キャラ変更はなし。BANはスペル・スキル・システムカードすべてが対象で、喜怒哀楽すべてのデッキから取り除く。

流れ
1. パネルの「エントリー」でキャラを決めて対戦待ちに入る
2. 「自動マッチング」で待機中の相手と組むか、「相手を指名」で申し込む（相手が承諾したら成立）
3. 対戦ごとにスレッドが作られ、日程調整（提案→相手がOK）、負けの報告、敗者のBAN選択をスレッド内で行う
"""
import datetime
import io
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from cardban_cards import (
    CATEGORY_LABELS,
    CardImportError,
    card_label,
    cards_to_json,
    parse_cards,
)
from cogs.report_cog import CHARACTERS
from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

JST = datetime.timezone(datetime.timedelta(hours=9))
DB_TIME_FORMAT = "%Y-%m-%d %H:%M"
REMIND_BEFORE_MINUTES = 30
MAX_IMPORT_BYTES = 1_000_000
COLOR = discord.Color.from_rgb(192, 57, 43)

STATUS_LABELS = {
    "pending_accept": "⏳ 承諾待ち",
    "active": "⚔️ 対戦中",
    "finished": "🏁 終了",
    "cancelled": "🛑 中止",
}


# ─────────────────────────────────────────────
#  小さなヘルパー
# ─────────────────────────────────────────────

def _is_admin(member: discord.abc.User) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and perms.manage_guild)


def _opponent_of(match: dict, user_id: int) -> int:
    return match["player2_id"] if user_id == match["player1_id"] else match["player1_id"]


def _char_of(match: dict, user_id: int) -> str:
    return match["char1"] if user_id == match["player1_id"] else match["char2"]


def _is_player(match: dict, user_id: int) -> bool:
    return user_id in (match["player1_id"], match["player2_id"])


def _name(guild: discord.Guild, user_id: int) -> str:
    member = guild.get_member(user_id)
    return member.display_name if member else f"ID:{user_id}"


def _parse_schedule(text: str, now: datetime.datetime) -> datetime.datetime | None:
    """「2026/11/15 21:00」「11/15 21:00」などをJSTの日時にする。年を省いて過去になるときは翌年とみなす"""
    text = text.strip().replace("　", " ")
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=JST)
        except ValueError:
            pass
    for fmt in ("%m/%d %H:%M", "%m-%d %H:%M"):
        try:
            parsed = datetime.datetime.strptime(f"{now.year}/{text}", "%Y/" + fmt).replace(tzinfo=JST)
        except ValueError:
            continue
        if parsed < now - datetime.timedelta(days=1):
            parsed = parsed.replace(year=now.year + 1)
        return parsed
    return None


def _format_schedule(db_value: str | None) -> str:
    if not db_value:
        return "未定"
    dt = datetime.datetime.strptime(db_value, DB_TIME_FORMAT).replace(tzinfo=JST)
    return f"<t:{int(dt.timestamp())}:F>（<t:{int(dt.timestamp())}:R>）"


def _preban_name(card_key: str) -> str:
    return card_key.split("|", 2)[-1]


def _clip(lines: list[str], limit: int = 1024) -> str:
    text = ""
    for i, line in enumerate(lines):
        rest = f"\n…ほか{len(lines) - i}件"
        if len(text) + len(line) + 1 + len(rest) > limit:
            return text + rest
        text += ("\n" if text else "") + line
    return text or "なし"


async def _ban_candidates(match: dict, target_id: int) -> list[dict]:
    """BANされる側（直前の勝者）のキャラのスキル・スペルとシステムカードのうち、最初から除外したものとBAN済みを除いたもの"""
    cards = await db_manager.get_cardban_cards(_char_of(match, target_id))
    excluded = set(match["preban"])
    excluded.update(b["card_key"] for b in await db_manager.get_cardban_bans(match["match_id"])
                    if b["target_id"] == target_id)
    order = {"skill": 0, "spell": 1, "system": 2}
    available = [c for c in cards if c["card_key"] not in excluded]
    available.sort(key=lambda c: order[c["category"]])  # sort は安定なので取り込み順は保たれる
    return available


async def _fetch_thread(bot: commands.Bot, thread_id: int | None) -> discord.Thread | None:
    if not thread_id:
        return None
    thread = bot.get_channel(thread_id)
    if thread is None:
        try:
            thread = await bot.fetch_channel(thread_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None
    return thread if isinstance(thread, discord.Thread) else None


# ─────────────────────────────────────────────
#  Embed
# ─────────────────────────────────────────────

async def _build_panel_embed(guild: discord.Guild) -> discord.Embed:
    settings = await db_manager.get_cardban_settings(guild.id)
    entries = await db_manager.get_cardban_entries(guild.id)
    matches = await db_manager.get_open_cardban_matches(guild.id)
    counts = await db_manager.count_cardban_cards()

    embed = discord.Embed(
        title=f"🃏 カードBAN{settings['target_wins']}先",
        description=(
            f"先に **{settings['target_wins']}勝** した方の勝ち！\n"
            f"1戦ごとに、負けた方が勝った方のカードを **{settings['bans_per_game']}枚** 使用不可にします。\n"
            "・スペル・スキル・システムカードすべてが対象（喜怒哀楽すべてのデッキから抜く）\n"
            "・キャラ変更はなし（エントリー時に決めたキャラで最後まで）\n\n"
            "**参加方法**: 「エントリー」でキャラを決める → 「自動マッチング」か「相手を指名」"
        ),
        color=COLOR,
    )
    embed.add_field(
        name=f"🙋 対戦待ち（{len(entries)}人）",
        value=_clip([f"・<@{e['user_id']}>（{e['character']}）" for e in entries]) if entries else "いません",
        inline=False,
    )
    embed.add_field(
        name=f"⚔️ 進行中の対戦（{len(matches)}件）",
        value=_clip([
            f"・<#{m['thread_id']}> <@{m['player1_id']}> **{m['score1']}-{m['score2']}** <@{m['player2_id']}>"
            + ("（承諾待ち）" if m["status"] == "pending_accept" else "")
            for m in matches if m["thread_id"]
        ]) if matches else "ありません",
        inline=False,
    )
    if settings["preban"]:
        embed.add_field(
            name="🚷 最初から使用不可のカード",
            value=_clip([f"・{_preban_name(k)}" for k in settings["preban"]]),
            inline=False,
        )
    if sum(counts.values()) == 0:
        embed.set_footer(text="⚠️ カード一覧が未登録です。管理者が /cardban_import で取り込んでください。")
    else:
        embed.set_footer(
            text=f"登録カード: システム{counts['system']} / スキル{counts['skill']} / スペル{counts['spell']}"
        )
    return embed


async def _build_status_embed(guild: discord.Guild, match: dict) -> discord.Embed:
    bans = await db_manager.get_cardban_bans(match["match_id"])
    p1, p2 = match["player1_id"], match["player2_id"]
    lines = [
        f"<@{p1}>（{match['char1']}）　**{match['score1']} - {match['score2']}**　<@{p2}>（{match['char2']}）",
        "",
        f"状態: {STATUS_LABELS.get(match['status'], match['status'])}",
        f"日程: {_format_schedule(match['scheduled_at'])}",
    ]
    if match["proposed_at"]:
        lines.append(f"日程の提案: {_format_schedule(match['proposed_at'])}（<@{match['proposed_by']}> から・相手のOK待ち）")
    if match["status"] == "active" and match["pending_ban_by"]:
        lines.append(f"🚫 <@{match['pending_ban_by']}> がBANするカードを選ぶ番です")
    if match["status"] == "finished" and match["winner_id"]:
        lines.append(f"🏆 勝者: <@{match['winner_id']}>")

    embed = discord.Embed(
        title=f"🃏 カードBAN{match['target_wins']}先",
        description="\n".join(lines),
        color=COLOR,
    )
    for player in (p1, p2):
        player_bans = [b for b in bans if b["target_id"] == player]
        embed.add_field(
            name=f"🚫 {_name(guild, player)} が使えないカード（{len(player_bans)}枚）",
            value=_clip([
                f"第{b['game_no']}戦: [{CATEGORY_LABELS.get(b['category'], b['category'])}] {b['card_name']}"
                for b in player_bans
            ]),
            inline=False,
        )
    if match["preban"]:
        embed.add_field(
            name="🚷 最初から使用不可（両者共通）",
            value=_clip([f"・{_preban_name(k)}" for k in match["preban"]]),
            inline=False,
        )
    embed.set_footer(text=f"1戦ごとに敗者が勝者のカードを{match['bans_per_game']}枚BAN ・ 対戦ID {match['match_id']}")
    return embed


# ─────────────────────────────────────────────
#  パネル（エントリー・マッチング）
# ─────────────────────────────────────────────

class CharacterSelectView(discord.ui.View):
    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=180)
        self.cog = cog
        select = discord.ui.Select(
            placeholder="使用キャラを選んでください（対戦中は変更できません）",
            options=[discord.SelectOption(label=c, value=c) for c in CHARACTERS],
        )
        select.callback = self._on_select
        self.select = select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        await self.cog._handle_entry(interaction, self.select.values[0])


class ChallengeView(discord.ui.View):
    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=180)
        self.cog = cog
        select = discord.ui.UserSelect(placeholder="対戦を申し込む相手（エントリー済みの人）")
        select.callback = self._on_select
        self.select = select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        await self.cog._handle_challenge(interaction, self.select.values[0])


class CardBanPanelView(discord.ui.View):
    """固定custom_idの永続View（再起動後もボタンが動く）"""

    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=None)
        self.cog = cog
        buttons = [
            ("🙋 エントリー", discord.ButtonStyle.success, "cardban_panel:entry", self._entry),
            ("🎲 自動マッチング", discord.ButtonStyle.primary, "cardban_panel:auto", self._auto),
            ("🤝 相手を指名", discord.ButtonStyle.primary, "cardban_panel:challenge", self._challenge),
            ("👋 エントリー取消", discord.ButtonStyle.secondary, "cardban_panel:leave", self._leave),
        ]
        for label, style, custom_id, callback in buttons:
            button = discord.ui.Button(label=label, style=style, custom_id=custom_id)
            button.callback = callback
            self.add_item(button)

    async def _entry(self, interaction: discord.Interaction):
        if await self.cog._reject_if_in_match(interaction):
            return
        await interaction.response.send_message(
            "使用キャラを選んでください。", view=CharacterSelectView(self.cog), ephemeral=True
        )

    async def _auto(self, interaction: discord.Interaction):
        await self.cog._handle_auto_match(interaction)

    async def _challenge(self, interaction: discord.Interaction):
        if await self.cog._reject_if_in_match(interaction):
            return
        if not await db_manager.get_cardban_entry(interaction.guild.id, interaction.user.id):
            await interaction.response.send_message("❌ 先に「🙋 エントリー」でキャラを決めてください。", ephemeral=True)
            return
        await interaction.response.send_message(
            "申し込む相手を選んでください。", view=ChallengeView(self.cog), ephemeral=True
        )

    async def _leave(self, interaction: discord.Interaction):
        removed = await db_manager.remove_cardban_entry(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            "👋 エントリーを取り消しました。" if removed else "エントリーしていません。", ephemeral=True
        )
        if removed:
            await self.cog._refresh_panel(interaction.guild)


# ─────────────────────────────────────────────
#  対戦スレッド内のView
# ─────────────────────────────────────────────

class AcceptView(discord.ui.View):
    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=None)
        self.cog = cog
        accept = discord.ui.Button(label="✅ 受ける", style=discord.ButtonStyle.success, custom_id="cardban_match:accept")
        accept.callback = self._accept
        decline = discord.ui.Button(label="❌ 断る / 取り下げる", style=discord.ButtonStyle.danger,
                                    custom_id="cardban_match:decline")
        decline.callback = self._decline
        self.add_item(accept)
        self.add_item(decline)

    async def _accept(self, interaction: discord.Interaction):
        await self.cog._handle_accept(interaction)

    async def _decline(self, interaction: discord.Interaction):
        await self.cog._handle_decline(interaction)


class MatchControlView(discord.ui.View):
    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=None)
        self.cog = cog
        buttons = [
            ("🏳️ 負けを報告", discord.ButtonStyle.danger, "cardban_match:lose", cog._handle_report_loss, 0),
            ("🚫 BANするカードを選ぶ", discord.ButtonStyle.primary, "cardban_match:ban", cog._handle_open_ban, 0),
            ("📅 日程を提案", discord.ButtonStyle.secondary, "cardban_match:schedule", cog._handle_open_schedule, 1),
            ("📋 BAN状況", discord.ButtonStyle.secondary, "cardban_match:status", cog._handle_show_status, 1),
            ("↩️ 直前の1戦を取り消す", discord.ButtonStyle.secondary, "cardban_match:undo", cog._handle_undo, 1),
            ("🛑 中止（管理者）", discord.ButtonStyle.secondary, "cardban_match:cancel", cog._handle_cancel, 2),
        ]
        for label, style, custom_id, callback, row in buttons:
            button = discord.ui.Button(label=label, style=style, custom_id=custom_id, row=row)
            button.callback = callback
            self.add_item(button)


class BanPromptView(discord.ui.View):
    """勝利のお知らせに付けるBAN選択ボタン（コントロールパネルのボタンと同じ処理）"""

    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=None)
        button = discord.ui.Button(label="🚫 BANするカードを選ぶ", style=discord.ButtonStyle.primary,
                                   custom_id="cardban_prompt:ban")
        button.callback = cog._handle_open_ban
        self.add_item(button)


class ScheduleOkView(discord.ui.View):
    def __init__(self, cog: "CardBanCog"):
        super().__init__(timeout=None)
        button = discord.ui.Button(label="👍 この日程でOK", style=discord.ButtonStyle.success,
                                   custom_id="cardban_match:schedule_ok")
        button.callback = cog._handle_schedule_ok
        self.add_item(button)


class ScheduleModal(discord.ui.Modal, title="📅 対戦日時を提案"):
    when = discord.ui.TextInput(
        label="日時（日本時間）",
        placeholder="例: 2026/11/15 21:00 または 11/15 21:00",
        max_length=20,
    )

    def __init__(self, cog: "CardBanCog", match_id: int):
        super().__init__()
        self.cog = cog
        self.match_id = match_id

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog._handle_propose_schedule(interaction, self.match_id, str(self.when.value))


class BanSelectView(discord.ui.View):
    """BANする人（直前の敗者）だけに見えるBAN選択。カードが多いので区分ごとに最大25枚ずつのセレクトに分ける"""

    def __init__(self, cog: "CardBanCog", match: dict, banner_id: int, candidates: list[dict], ban_count: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.match_id = match["match_id"]
        self.banner_id = banner_id
        self.ban_count = ban_count
        self.cards = {c["card_key"]: c for c in candidates}
        self.selected: dict[int, list[str]] = {}

        chunks: list[tuple[str, list[dict]]] = []
        for category in ("skill", "spell", "system"):
            group = [c for c in candidates if c["category"] == category]
            for i in range(0, len(group), 25):
                chunks.append((CATEGORY_LABELS[category], group[i:i + 25]))
        if len(chunks) > 4:
            # セレクトは1メッセージに4つまで（残り1行はボタン）なので、区分をまたいで詰める
            chunks = [("カード", candidates[i:i + 25]) for i in range(0, len(candidates), 25)][:4]

        for index, (label, group) in enumerate(chunks):
            select = discord.ui.Select(
                placeholder=f"{label}カードから選ぶ（{len(group)}枚）",
                min_values=0,
                max_values=min(ban_count, len(group)),
                options=[
                    discord.SelectOption(
                        label=card_label(c)[:100],
                        value=c["card_key"],
                        description=CATEGORY_LABELS[c["category"]] + (f" / {c['character']}" if c["character"] else ""),
                    )
                    for c in group
                ],
                row=index,
            )
            select.callback = self._make_select_callback(index, select)
            self.add_item(select)

        confirm = discord.ui.Button(label=f"✅ {ban_count}枚をBANする", style=discord.ButtonStyle.danger, row=4)
        confirm.callback = self._confirm
        self.add_item(confirm)

    def _make_select_callback(self, index: int, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            self.selected[index] = list(select.values)
            await interaction.response.defer()
        return callback

    async def _confirm(self, interaction: discord.Interaction):
        keys = [k for values in self.selected.values() for k in values]
        if len(keys) != self.ban_count:
            await interaction.response.send_message(
                f"❌ ちょうど **{self.ban_count}枚** 選んでください（いま {len(keys)}枚）。", ephemeral=True
            )
            return
        await self.cog._handle_confirm_ban(interaction, self, [self.cards[k] for k in keys])


class CancelConfirmView(discord.ui.View):
    def __init__(self, cog: "CardBanCog", match_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.match_id = match_id

    @discord.ui.button(label="🛑 中止する", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._execute_cancel(interaction, self.match_id)

    @discord.ui.button(label="やめる", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="中止しませんでした。", view=None)


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class CardBanCog(commands.Cog):
    """カードBAN10先: エントリー・マッチング・対戦スレッド・BAN記録・日程調整"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(CardBanPanelView(self))
        self.bot.add_view(AcceptView(self))
        self.bot.add_view(MatchControlView(self))
        self.bot.add_view(BanPromptView(self))
        self.bot.add_view(ScheduleOkView(self))
        if not self._remind_loop.is_running():
            self._remind_loop.start()

    async def cog_unload(self):
        self._remind_loop.cancel()

    # ── 共通 ──────────────────────────────────

    async def _refresh_panel(self, guild: discord.Guild):
        settings = await db_manager.get_cardban_settings(guild.id)
        channel = guild.get_channel(settings["panel_channel_id"] or 0)
        if not isinstance(channel, discord.TextChannel) or not settings["panel_message_id"]:
            return
        try:
            message = await channel.fetch_message(settings["panel_message_id"])
            await message.edit(embed=await _build_panel_embed(guild))
        except (discord.NotFound, discord.Forbidden):
            pass
        except discord.HTTPException as e:
            logger.warning(f"cardban パネル更新失敗: {e}")

    async def _refresh_status(self, guild: discord.Guild, match_id: int):
        match = await db_manager.get_cardban_match(match_id)
        if match is None or not match["status_message_id"]:
            return
        thread = await _fetch_thread(self.bot, match["thread_id"])
        if thread is None:
            return
        view = MatchControlView(self) if match["status"] in ("pending_accept", "active") else None
        try:
            message = await thread.fetch_message(match["status_message_id"])
            await message.edit(embed=await _build_status_embed(guild, match), view=view)
        except (discord.NotFound, discord.Forbidden):
            pass
        except discord.HTTPException as e:
            logger.warning(f"cardban 状況メッセージ更新失敗 (match_id={match_id}): {e}")

    async def _match_here(self, interaction: discord.Interaction) -> dict | None:
        """ボタンが押されたスレッドの対戦。無ければエラーを返信して None"""
        match = await db_manager.get_cardban_match_by_thread(interaction.channel_id)
        if match is None:
            await interaction.response.send_message("❌ このスレッドの対戦が見つかりません。", ephemeral=True)
        return match

    async def _reject_if_in_match(self, interaction: discord.Interaction) -> bool:
        match = await db_manager.get_active_cardban_match_for_user(interaction.guild.id, interaction.user.id)
        if match:
            await interaction.response.send_message(
                f"❌ 進行中の対戦があります（<#{match['thread_id']}>）。終わってからエントリーしてください。",
                ephemeral=True,
            )
            return True
        return False

    # ── エントリー・マッチング ─────────────────────

    async def _handle_entry(self, interaction: discord.Interaction, character: str):
        if sum((await db_manager.count_cardban_cards()).values()) == 0:
            await interaction.response.edit_message(
                content="❌ カード一覧がまだ登録されていません。管理者に `/cardban_import` を依頼してください。",
                view=None,
            )
            return
        if await db_manager.get_active_cardban_match_for_user(interaction.guild.id, interaction.user.id):
            await interaction.response.edit_message(content="❌ 進行中の対戦があります。", view=None)
            return
        await db_manager.upsert_cardban_entry(interaction.guild.id, interaction.user.id, character)
        await interaction.response.edit_message(
            content=f"✅ **{character}** でエントリーしました。「🎲 自動マッチング」か「🤝 相手を指名」で対戦相手を探せます。",
            view=None,
        )
        await self._refresh_panel(interaction.guild)
        logger.info(f"cardban_entry: user={interaction.user.id} char={character}")

    async def _handle_auto_match(self, interaction: discord.Interaction):
        guild = interaction.guild
        if await self._reject_if_in_match(interaction):
            return
        me = await db_manager.get_cardban_entry(guild.id, interaction.user.id)
        if me is None:
            await interaction.response.send_message("❌ 先に「🙋 エントリー」でキャラを決めてください。", ephemeral=True)
            return
        others = [e for e in await db_manager.get_cardban_entries(guild.id) if e["user_id"] != interaction.user.id]
        if not others:
            await interaction.response.send_message(
                "いま対戦待ちの人がほかにいません。エントリーしたまま待っていれば、"
                "次に誰かが「🎲 自動マッチング」を押したときに組まれます。",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        opponent = others[0]  # いちばん長く待っている人
        thread = await self._open_match(
            interaction, me, opponent, status="active",
        )
        if thread:
            await interaction.followup.send(f"✅ マッチしました！ {thread.mention}", ephemeral=True)

    async def _handle_challenge(self, interaction: discord.Interaction, target: discord.abc.User):
        guild = interaction.guild
        if target.id == interaction.user.id or target.bot:
            await interaction.response.edit_message(content="❌ その相手には申し込めません。", view=None)
            return
        me = await db_manager.get_cardban_entry(guild.id, interaction.user.id)
        opponent = await db_manager.get_cardban_entry(guild.id, target.id)
        if me is None:
            await interaction.response.edit_message(content="❌ 先にエントリーしてください。", view=None)
            return
        if opponent is None:
            await interaction.response.edit_message(
                content=f"❌ {target.mention} はエントリーしていません。先にパネルからエントリーしてもらってください。",
                view=None,
            )
            return
        await interaction.response.edit_message(content="スレッドを作成中...", view=None)
        thread = await self._open_match(interaction, me, opponent, status="pending_accept")
        if thread:
            await interaction.edit_original_response(content=f"✅ 申し込みました！ {thread.mention}")

    async def _open_match(
        self, interaction: discord.Interaction, entry1: dict, entry2: dict, status: str
    ) -> discord.Thread | None:
        """対戦を作ってスレッドを立てる。失敗したらユーザーに伝えて None"""
        guild = interaction.guild
        settings = await db_manager.get_cardban_settings(guild.id)
        channel = guild.get_channel(settings["panel_channel_id"] or 0) or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("❌ スレッドを作れるチャンネルがありません。管理者にご連絡ください。", ephemeral=True)
            return None

        p1, p2 = entry1["user_id"], entry2["user_id"]
        match_id = await db_manager.create_cardban_match(
            guild.id, p1, p2, entry1["character"], entry2["character"],
            settings["target_wins"], settings["bans_per_game"], settings["preban"], status,
        )
        if match_id is None:
            await interaction.followup.send("❌ どちらかがすでに対戦中です。", ephemeral=True)
            return None

        try:
            thread = await channel.create_thread(
                name=f"🃏 カードBAN{settings['target_wins']}先｜{_name(guild, p1)} vs {_name(guild, p2)}"[:100],
                type=discord.ChannelType.public_thread,
                auto_archive_duration=10080,
            )
        except discord.HTTPException as e:
            await db_manager.update_cardban_match(match_id, status="cancelled")
            await interaction.followup.send(f"❌ スレッドを作れませんでした: {e}", ephemeral=True)
            logger.error(f"cardban スレッド作成失敗: {e}")
            await self._refresh_panel(guild)
            return None

        await db_manager.update_cardban_match(match_id, thread_id=thread.id)
        for user_id in (p1, p2):
            try:
                await thread.add_user(discord.Object(id=user_id))
            except discord.HTTPException:
                pass

        match = await db_manager.get_cardban_match(match_id)
        status_message = await thread.send(embed=await _build_status_embed(guild, match), view=MatchControlView(self))
        await db_manager.update_cardban_match(match_id, status_message_id=status_message.id)
        try:
            await status_message.pin()
        except discord.HTTPException:
            pass

        if status == "pending_accept":
            await thread.send(
                f"<@{p2}> <@{p1}> さんから **カードBAN{settings['target_wins']}先** の申し込みです！\n"
                f"（<@{p1}>: {entry1['character']} / <@{p2}>: {entry2['character']}）\n"
                "受けるなら「✅ 受ける」を押してください。",
                view=AcceptView(self),
            )
        else:
            await thread.send(self._start_message(match))

        await self._refresh_panel(guild)
        logger.info(f"cardban_match_open: match={match_id} p1={p1} p2={p2} status={status}")
        return thread

    @staticmethod
    def _start_message(match: dict) -> str:
        return (
            f"<@{match['player1_id']}> <@{match['player2_id']}> 対戦成立です！\n"
            "1. 「📅 日程を提案」で日時を決めましょう（相手がOKすると確定し、30分前と開始時刻にお知らせします）\n"
            "2. 1戦ごとに、**負けた人が**「🏳️ 負けを報告」を押してください\n"
            "3. 続けて負けた人が「🚫 BANするカードを選ぶ」で、勝った人のカードをBANします（BANが済むまで次の報告はできません）"
        )

    # ── 申し込みへの返事 ───────────────────────

    async def _handle_accept(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if interaction.user.id != match["player2_id"]:
            await interaction.response.send_message("❌ 申し込まれた本人だけが受けられます。", ephemeral=True)
            return
        if not await db_manager.update_cardban_match(match["match_id"], expected_status="pending_accept", status="active"):
            await interaction.response.send_message("この申し込みはもう締め切られています。", ephemeral=True)
            return
        await interaction.response.edit_message(view=None)
        match = await db_manager.get_cardban_match(match["match_id"])
        await interaction.channel.send(self._start_message(match))
        await self._refresh_status(interaction.guild, match["match_id"])
        await self._refresh_panel(interaction.guild)

    async def _handle_decline(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if not _is_player(match, interaction.user.id) and not _is_admin(interaction.user):
            await interaction.response.send_message("❌ 対戦する2人だけが操作できます。", ephemeral=True)
            return
        if not await db_manager.update_cardban_match(match["match_id"], expected_status="pending_accept", status="cancelled"):
            await interaction.response.send_message("この申し込みはもう締め切られています。", ephemeral=True)
            return
        await interaction.response.edit_message(view=None)
        await interaction.channel.send(
            f"🙇 {interaction.user.mention} が申し込みを取りやめました。"
            "また対戦する場合は、パネルからもう一度エントリーしてください。"
        )
        await self._refresh_status(interaction.guild, match["match_id"])
        await self._refresh_panel(interaction.guild)

    # ── 勝敗報告とBAN ─────────────────────────

    async def _handle_report_loss(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if not _is_player(match, interaction.user.id):
            await interaction.response.send_message("❌ 対戦している本人だけが報告できます。", ephemeral=True)
            return
        if match["status"] != "active":
            await interaction.response.send_message(
                f"❌ いまは報告できません（{STATUS_LABELS.get(match['status'], match['status'])}）。", ephemeral=True
            )
            return
        if match["pending_ban_by"]:
            await interaction.response.send_message(
                f"❌ <@{match['pending_ban_by']}> のBAN選択が終わるまで、次の結果は報告できません。", ephemeral=True
            )
            return

        result = await db_manager.record_cardban_loss(match["match_id"], interaction.user.id)
        if result is None:
            await interaction.response.send_message("❌ 報告できませんでした。もう一度お試しください。", ephemeral=True)
            return
        await interaction.response.defer()

        guild = interaction.guild
        winner_id, loser_id = result["winner_id"], interaction.user.id
        match = await db_manager.get_cardban_match(match["match_id"])
        score = f"{match['score1']}-{match['score2']}"

        if result["finished"]:
            await interaction.channel.send(
                f"🏆 **決着！** 第{result['game_no']}戦は <@{winner_id}> の勝利（{score}）。\n"
                f"<@{winner_id}> が **カードBAN{match['target_wins']}先** を制しました！お疲れさまでした！"
            )
        else:
            candidates = await _ban_candidates(match, winner_id)
            ban_count = min(match["bans_per_game"], len(candidates))
            if ban_count == 0:
                await db_manager.apply_cardban_bans(match["match_id"], loser_id, [])
                await interaction.channel.send(
                    f"⚔️ 第{result['game_no']}戦は <@{winner_id}> の勝利（{score}）。\n"
                    f"<@{winner_id}> にはBANできるカードが残っていないため、BANなしで次の対戦へ進みます。"
                )
            else:
                await interaction.channel.send(
                    f"⚔️ 第{result['game_no']}戦は <@{winner_id}> の勝利（{score}）。\n"
                    f"<@{loser_id}> は <@{winner_id}>（{_char_of(match, winner_id)}）のカードを "
                    f"**{ban_count}枚** BANしてください。",
                    view=BanPromptView(self),
                )
        await self._refresh_status(guild, match["match_id"])
        await self._refresh_panel(guild)
        logger.info(f"cardban_loss: match={match['match_id']} game={result['game_no']} loser={loser_id}")

    async def _handle_open_ban(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if match["status"] != "active" or not match["pending_ban_by"]:
            await interaction.response.send_message("いまはBANを選ぶ場面ではありません。", ephemeral=True)
            return
        if interaction.user.id != match["pending_ban_by"]:
            await interaction.response.send_message(
                f"❌ BANを選ぶのは直前に負けた人（<@{match['pending_ban_by']}>）です。", ephemeral=True
            )
            return
        target_id = _opponent_of(match, interaction.user.id)
        candidates = await _ban_candidates(match, target_id)
        ban_count = min(match["bans_per_game"], len(candidates))
        if ban_count == 0:
            await db_manager.apply_cardban_bans(match["match_id"], interaction.user.id, [])
            await interaction.response.send_message("BANできるカードが残っていないため、BANなしで進めます。")
            await self._refresh_status(interaction.guild, match["match_id"])
            return
        await interaction.response.send_message(
            f"<@{target_id}>（{_char_of(match, target_id)}）のカードから **{ban_count}枚** 選んで、最後に下のボタンを押してください。\n"
            "（BAN済み・最初から使用不可のカードは出てきません）",
            view=BanSelectView(self, match, interaction.user.id, candidates, ban_count),
            ephemeral=True,
        )

    async def _handle_confirm_ban(self, interaction: discord.Interaction, view: BanSelectView, cards: list[dict]):
        ok = await db_manager.apply_cardban_bans(view.match_id, view.banner_id, cards)
        if not ok:
            await interaction.response.edit_message(
                content="❌ BANできませんでした（もう選び終わっているか、記録が取り消されています）。", view=None
            )
            return
        view.stop()
        names = "、".join(f"**{c['name']}**" for c in cards)
        await interaction.response.edit_message(content=f"✅ {names} をBANしました。", view=None)

        match = await db_manager.get_cardban_match(view.match_id)
        target_id = _opponent_of(match, view.banner_id)
        lines = [f"・[{CATEGORY_LABELS[c['category']]}] {c['name']}" for c in cards]
        await interaction.channel.send(
            f"🚫 <@{view.banner_id}> が <@{target_id}> のカードをBANしました。\n" + "\n".join(lines)
            + f"\n<@{target_id}> は喜怒哀楽すべてのデッキからこのカードを抜いてください。次の対戦へどうぞ！"
        )
        await self._refresh_status(interaction.guild, view.match_id)
        logger.info(f"cardban_ban: match={view.match_id} by={view.banner_id} cards={[c['card_key'] for c in cards]}")

    async def _handle_show_status(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        await interaction.response.send_message(embed=await _build_status_embed(interaction.guild, match), ephemeral=True)

    async def _handle_undo(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        games = await db_manager.get_cardban_games(match["match_id"])
        if not games:
            await interaction.response.send_message("取り消せる結果がありません。", ephemeral=True)
            return
        last = games[-1]
        if not _is_admin(interaction.user):
            # 管理者以外は、報告した本人（負けた人）が、自分のBAN選択前に限って取り消せる
            if interaction.user.id != last["loser_id"] or match["pending_ban_by"] is None or match["status"] != "active":
                await interaction.response.send_message(
                    "❌ 取り消せるのは「負けを報告した本人が、BANを選ぶ前に」押したときだけです。"
                    "それ以外は管理者に依頼してください。",
                    ephemeral=True,
                )
                return
        undone = await db_manager.undo_last_cardban_game(match["match_id"])
        if undone is None:
            await interaction.response.send_message("❌ 取り消せませんでした。", ephemeral=True)
            return
        await interaction.response.send_message(
            f"↩️ {interaction.user.mention} が第{undone['game_no']}戦（<@{undone['winner_id']}> の勝利）の記録を取り消しました。"
            + (f"この戦のBAN {undone['bans']}枚も取り消しています。" if undone["bans"] else "")
        )
        await self._refresh_status(interaction.guild, match["match_id"])
        await self._refresh_panel(interaction.guild)
        logger.info(f"cardban_undo: match={match['match_id']} game={undone['game_no']} by={interaction.user.id}")

    async def _handle_cancel(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if not _is_admin(interaction.user):
            await interaction.response.send_message("❌ 対戦の中止は管理者だけができます。", ephemeral=True)
            return
        if match["status"] not in ("pending_accept", "active"):
            await interaction.response.send_message("この対戦はもう終わっています。", ephemeral=True)
            return
        await interaction.response.send_message(
            "この対戦を中止しますか？記録は残りますが、続きの報告はできなくなります。",
            view=CancelConfirmView(self, match["match_id"]),
            ephemeral=True,
        )

    async def _execute_cancel(self, interaction: discord.Interaction, match_id: int):
        match = await db_manager.get_cardban_match(match_id)
        if match is None or match["status"] not in ("pending_accept", "active"):
            await interaction.response.edit_message(content="この対戦はもう終わっています。", view=None)
            return
        await db_manager.update_cardban_match(match_id, status="cancelled", pending_ban_by=None)
        await interaction.response.edit_message(content="🛑 中止しました。", view=None)
        await interaction.channel.send(f"🛑 {interaction.user.mention} がこの対戦を中止しました。")
        await self._refresh_status(interaction.guild, match_id)
        await self._refresh_panel(interaction.guild)
        logger.info(f"cardban_cancel: match={match_id} by={interaction.user.id}")

    # ── 日程調整 ─────────────────────────────

    async def _handle_open_schedule(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if not _is_player(match, interaction.user.id):
            await interaction.response.send_message("❌ 対戦する2人だけが日程を提案できます。", ephemeral=True)
            return
        if match["status"] not in ("pending_accept", "active"):
            await interaction.response.send_message("この対戦はもう終わっています。", ephemeral=True)
            return
        await interaction.response.send_modal(ScheduleModal(self, match["match_id"]))

    async def _handle_propose_schedule(self, interaction: discord.Interaction, match_id: int, text: str):
        now = datetime.datetime.now(JST)
        when = _parse_schedule(text, now)
        if when is None:
            await interaction.response.send_message(
                "❌ 日時の形式が読めません。`2026/11/15 21:00` か `11/15 21:00` の形で入力してください。", ephemeral=True
            )
            return
        if when <= now:
            await interaction.response.send_message("❌ 過去の日時は指定できません。", ephemeral=True)
            return
        match = await db_manager.get_cardban_match(match_id)
        if match is None or match["status"] not in ("pending_accept", "active"):
            await interaction.response.send_message("この対戦はもう終わっています。", ephemeral=True)
            return
        await db_manager.update_cardban_match(
            match_id, proposed_at=when.strftime(DB_TIME_FORMAT), proposed_by=interaction.user.id
        )
        opponent = _opponent_of(match, interaction.user.id)
        ts = int(when.timestamp())
        await interaction.response.send_message(
            f"📅 {interaction.user.mention} が対戦日時を提案しました: **<t:{ts}:F>**（<t:{ts}:R>）\n"
            f"<@{opponent}> 都合が良ければ「👍 この日程でOK」を押してください。"
            "合わなければ「📅 日程を提案」から別の日時を出し直せます。",
            view=ScheduleOkView(self),
        )
        await self._refresh_status(interaction.guild, match_id)

    async def _handle_schedule_ok(self, interaction: discord.Interaction):
        match = await self._match_here(interaction)
        if match is None:
            return
        if not _is_player(match, interaction.user.id):
            await interaction.response.send_message("❌ 対戦する2人だけが操作できます。", ephemeral=True)
            return
        if not match["proposed_at"]:
            await interaction.response.send_message("いま返事待ちの日程の提案はありません。", ephemeral=True)
            return
        if match["proposed_by"] == interaction.user.id:
            await interaction.response.send_message("❌ 自分の提案にはOKできません。相手の返事を待ってください。", ephemeral=True)
            return
        await db_manager.update_cardban_match(
            match["match_id"], scheduled_at=match["proposed_at"], proposed_at=None, proposed_by=None,
            reminded_before=0, reminded_start=0,
        )
        await interaction.response.edit_message(view=None)
        await interaction.channel.send(
            f"✅ 日程が決まりました: {_format_schedule(match['proposed_at'])}\n"
            f"<@{match['player1_id']}> <@{match['player2_id']}> {REMIND_BEFORE_MINUTES}分前と開始時刻にお知らせします。"
        )
        await self._refresh_status(interaction.guild, match["match_id"])

    @tasks.loop(minutes=1)
    async def _remind_loop(self):
        # 例外を外に出すとループが止まり、再起動まで通知されなくなるため必ず握る
        try:
            now = datetime.datetime.now(JST)
            soon = now + datetime.timedelta(minutes=REMIND_BEFORE_MINUTES)
            due = await db_manager.get_due_cardban_reminders(soon.strftime(DB_TIME_FORMAT), now.strftime(DB_TIME_FORMAT))
        except Exception as e:
            logger.error(f"cardban リマインダー取得失敗: {e}")
            return
        now_str = now.strftime(DB_TIME_FORMAT)
        for match in due:
            try:
                thread = await _fetch_thread(self.bot, match["thread_id"])
                started = match["scheduled_at"] <= now_str
                if thread is not None:
                    mentions = f"<@{match['player1_id']}> <@{match['player2_id']}>"
                    if started:
                        await thread.send(f"⏰ {mentions} 対戦の時間です！準備ができたら始めましょう。")
                    else:
                        await thread.send(
                            f"⏰ {mentions} もうすぐ対戦です（{_format_schedule(match['scheduled_at'])}）。"
                        )
                if started:
                    await db_manager.update_cardban_match(match["match_id"], reminded_before=1, reminded_start=1)
                else:
                    await db_manager.update_cardban_match(match["match_id"], reminded_before=1)
            except discord.DiscordServerError as e:
                logger.warning(f"cardban リマインダー送信失敗・次回再試行 (match={match['match_id']}): {e}")
            except Exception as e:
                logger.error(f"cardban リマインダー処理失敗 (match={match['match_id']}): {e}")

    @_remind_loop.before_loop
    async def _before_remind_loop(self):
        await self.bot.wait_until_ready()

    # ── スラッシュコマンド ─────────────────────

    async def _character_autocomplete(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=c, value=c) for c in CHARACTERS if current in c][:25]

    async def _card_autocomplete(self, interaction: discord.Interaction, current: str):
        cards = await db_manager.get_cardban_cards()
        choices = []
        for c in cards:
            label = f"[{CATEGORY_LABELS[c['category']]}{'/' + c['character'] if c['character'] else ''}] {c['name']}"
            if current in label:
                choices.append(app_commands.Choice(name=label[:100], value=c["card_key"]))
            if len(choices) >= 25:
                break
        return choices

    @app_commands.command(name="setup_cardban_panel", description="カードBAN10先のパネルをこのチャンネルに設置します（管理者用）")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_cardban_panel(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ 対戦ごとのスレッドを作るため、通常のテキストチャンネルで実行してください。", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        message = await interaction.channel.send(
            embed=await _build_panel_embed(interaction.guild), view=CardBanPanelView(self)
        )
        await db_manager.save_cardban_settings(
            interaction.guild.id, panel_channel_id=interaction.channel.id, panel_message_id=message.id
        )
        note = ""
        if sum((await db_manager.count_cardban_cards()).values()) == 0:
            note = "\n⚠️ カード一覧がまだありません。`/cardban_import` で取り込んでください（ひな形は `/cardban_export`）。"
        await interaction.followup.send(
            "✅ パネルを設置しました。対戦スレッドはこのチャンネルに作られます。" + note, ephemeral=True
        )

    @app_commands.command(name="cardban_import", description="カードBAN用のカード一覧をJSON/CSVファイルから取り込みます（管理者用・全件入れ替え）")
    @app_commands.describe(file="カード一覧のファイル（.json または .csv）。形式は /cardban_export のひな形を参照")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def cardban_import(self, interaction: discord.Interaction, file: discord.Attachment):
        if file.size > MAX_IMPORT_BYTES:
            await interaction.response.send_message("❌ ファイルが大きすぎます（1MBまで）。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            raw = await file.read()
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            await interaction.followup.send("❌ 文字コードはUTF-8で保存してください。", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ ファイルを読めませんでした: {e}", ephemeral=True)
            return
        try:
            cards = parse_cards(text, file.filename, CHARACTERS)
        except CardImportError as e:
            await interaction.followup.send(f"❌ 取り込めませんでした。\n{e}"[:1900], ephemeral=True)
            return

        await db_manager.replace_cardban_cards(cards)
        counts = await db_manager.count_cardban_cards()
        missing = [ch for ch in CHARACTERS if not any(c["character"] == ch for c in cards)]
        msg = (
            f"✅ {len(cards)}枚を取り込みました（システム{counts['system']} / スキル{counts['skill']} / スペル{counts['spell']}）。"
        )
        if missing:
            msg += "\n⚠️ カードが無いキャラ: " + "、".join(missing)
        await interaction.followup.send(msg, ephemeral=True)
        await self._refresh_panel(interaction.guild)
        logger.info(f"cardban_import: by={interaction.user.id} cards={len(cards)}")

    @app_commands.command(name="cardban_export", description="登録中のカード一覧をJSONで出力します（未登録なら取り込み用のひな形）（管理者用）")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def cardban_export(self, interaction: discord.Interaction):
        cards = await db_manager.get_cardban_cards()
        data = cards_to_json(cards, CHARACTERS).encode("utf-8")
        await interaction.response.send_message(
            "現在のカード一覧です。編集して `/cardban_import` で取り込めます。" if cards
            else "ひな形です。各キャラの skill / spell と system にカードを書いて `/cardban_import` で取り込んでください。",
            file=discord.File(io.BytesIO(data), filename="cardban_cards.json"),
            ephemeral=True,
        )

    @app_commands.command(name="cardban_cards", description="カードBANの対象になるカード一覧を表示します")
    @app_commands.describe(character="キャラ（省略するとシステムカード）")
    @app_commands.guild_only()
    async def cardban_cards(self, interaction: discord.Interaction, character: str | None = None):
        if character is not None and character not in CHARACTERS:
            await interaction.response.send_message("❌ そのキャラは登録されていません。", ephemeral=True)
            return
        if character is None:
            cards = [c for c in await db_manager.get_cardban_cards() if c["category"] == "system"]
            title = "システムカード"
        else:
            cards = await db_manager.get_cardban_cards(character, include_system=False)
            title = f"{character} のカード"
        settings = await db_manager.get_cardban_settings(interaction.guild.id)
        embed = discord.Embed(title=f"🃏 {title}", color=COLOR)
        for category in ("skill", "spell", "system"):
            group = [c for c in cards if c["category"] == category]
            if group:
                embed.add_field(
                    name=f"{CATEGORY_LABELS[category]}（{len(group)}枚）",
                    value=_clip([
                        f"・{card_label(c)}" + (" 🚷最初から使用不可" if c["card_key"] in settings["preban"] else "")
                        for c in group
                    ]),
                    inline=False,
                )
        if not cards:
            embed.description = "登録されているカードがありません。"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @cardban_cards.autocomplete("character")
    async def _cardban_cards_character_ac(self, interaction: discord.Interaction, current: str):
        return await self._character_autocomplete(interaction, current)

    @app_commands.command(name="cardban_preban", description="最初から使用不可にするカード（例: 銭）を追加・解除します（管理者用・次の対戦から反映）")
    @app_commands.describe(card="追加・解除するカード（もう一度指定すると解除）")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def cardban_preban(self, interaction: discord.Interaction, card: str):
        known = {c["card_key"]: c for c in await db_manager.get_cardban_cards()}
        settings = await db_manager.get_cardban_settings(interaction.guild.id)
        preban = list(settings["preban"])
        if card in preban:
            preban.remove(card)
            msg = f"✅ **{_preban_name(card)}** を「最初から使用不可」から外しました。"
        elif card in known:
            preban.append(card)
            msg = f"✅ **{known[card]['name']}** を「最初から使用不可」にしました。"
        else:
            await interaction.response.send_message("❌ 候補の中からカードを選んでください。", ephemeral=True)
            return
        await db_manager.save_cardban_settings(interaction.guild.id, preban=preban)
        await interaction.response.send_message(msg + "\n（すでに始まっている対戦には反映されません）", ephemeral=True)
        await self._refresh_panel(interaction.guild)

    @cardban_preban.autocomplete("card")
    async def _cardban_preban_ac(self, interaction: discord.Interaction, current: str):
        return await self._card_autocomplete(interaction, current)

    @app_commands.command(name="cardban_config", description="先取数と1戦あたりのBAN枚数を設定します（管理者用・次の対戦から反映）")
    @app_commands.describe(target_wins="何勝先取か（既定10）", bans_per_game="1戦ごとにBANする枚数（既定1）")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def cardban_config(
        self,
        interaction: discord.Interaction,
        target_wins: app_commands.Range[int, 1, 50] | None = None,
        bans_per_game: app_commands.Range[int, 0, 10] | None = None,
    ):
        fields = {}
        if target_wins is not None:
            fields["target_wins"] = target_wins
        if bans_per_game is not None:
            fields["bans_per_game"] = bans_per_game
        await db_manager.save_cardban_settings(interaction.guild.id, **fields)
        settings = await db_manager.get_cardban_settings(interaction.guild.id)
        preban = "、".join(_preban_name(k) for k in settings["preban"]) or "なし"
        await interaction.response.send_message(
            ("✅ 設定を変更しました（次の対戦から反映）。\n" if fields else "現在の設定です。\n")
            + f"・先取数: **{settings['target_wins']}**\n"
            f"・1戦ごとのBAN枚数: **{settings['bans_per_game']}**\n"
            f"・最初から使用不可: {preban}",
            ephemeral=True,
        )
        if fields:
            await self._refresh_panel(interaction.guild)

    @app_commands.command(name="cardban_status", description="このスレッドのカードBAN対戦の状況（スコア・BAN済みカード）を表示します")
    @app_commands.guild_only()
    async def cardban_status(self, interaction: discord.Interaction):
        match = await db_manager.get_cardban_match_by_thread(interaction.channel_id)
        if match is None:
            match = await db_manager.get_active_cardban_match_for_user(interaction.guild.id, interaction.user.id)
        if match is None:
            await interaction.response.send_message(
                "❌ 対戦が見つかりません。対戦スレッドの中で実行してください。", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=await _build_status_embed(interaction.guild, match), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CardBanCog(bot))
