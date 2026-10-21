import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

JST = datetime.timezone(datetime.timedelta(hours=9))

HOT_TIME_NAME = db_manager.HOT_TIME_NAME
HOT_TIME_WEEKDAY = db_manager.HOT_TIME_WEEKDAY
HOT_TIME_COLOR = discord.Color.from_rgb(231, 76, 60)

# 開催日（木曜 0:00 JST）からの経過時間で、各投稿の予定時刻と締め切りを表す。
# 締め切りまでにBotが止まっていて投稿できなかった回は、あとから投稿しない
_SCHEDULE = {
    "morning": (datetime.timedelta(hours=9), datetime.timedelta(hours=21)),   # 朝の予告: 木曜 9:00〜
    "start": (datetime.timedelta(hours=21), datetime.timedelta(hours=24)),    # 開始通知: 木曜 21:00〜
    "summary": (datetime.timedelta(hours=24), datetime.timedelta(hours=36)),  # まとめ: 金曜 0:00〜
}
_HOT_TIME_START = datetime.timedelta(hours=db_manager.HOT_TIME_START_HOUR)
_HOT_TIME_END = datetime.timedelta(hours=24)

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# 開始のお知らせでメンションする「今夜行けます」の人数の上限（メッセージの文字数制限に収めるため）
_RSVP_MENTION_LIMIT = 50


def _session_start(now: datetime.datetime) -> datetime.datetime:
    """now 時点で直近の開催日（今日が木曜なら今日）の 0:00 JST を返す"""
    now = now.astimezone(JST)
    days_back = (now.weekday() - HOT_TIME_WEEKDAY) % 7
    day = now.date() - datetime.timedelta(days=days_back)
    return datetime.datetime(day.year, day.month, day.day, tzinfo=JST)


def is_hot_time(now: datetime.datetime | None = None) -> bool:
    """now（省略時は現在時刻）がHOT TIMEの開催中（木曜 21:00〜24:00 JST）かどうか"""
    now = (now or datetime.datetime.now(JST)).astimezone(JST)
    session = _session_start(now)
    return session + _HOT_TIME_START <= now < session + _HOT_TIME_END


async def hot_time_active(guild_id: int) -> bool:
    """そのサーバーでHOT TIMEが設定されていて、いま開催中かどうか"""
    return is_hot_time() and await db_manager.get_hot_time_setting(guild_id) is not None


def _to_db_time(dt: datetime.datetime) -> str:
    """DBの created_at（UTC）と同じ形式にする"""
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _top3(rows: list[dict], key: str) -> list[dict]:
    """key の降順で上位3位までを返す。同数は同順位とし、その分は3名を超えて載せる。0以下は除く"""
    values = [r[key] for r in rows if r[key] > 0]
    result = []
    for r in sorted(rows, key=lambda r: (-r[key], r["username"])):
        if r[key] <= 0:
            continue
        rank = 1 + sum(1 for v in values if v > r[key])
        if rank > 3:
            break
        result.append({**r, "rank": rank})
    return result


def _rsvp_members(guild: discord.Guild, user_ids: list[int]) -> list[discord.Member]:
    """「今夜行けます」を押した人のうち、まだサーバーにいる人"""
    return [m for m in (guild.get_member(uid) for uid in user_ids) if m is not None]


def build_morning_embed(rsvps: list[discord.Member] | None = None) -> discord.Embed:
    rsvps = rsvps or []
    embed = discord.Embed(
        title=f"🔥 今夜は {HOT_TIME_NAME}！",
        description=(
            "本日 **21:00〜24:00** は HOT TIME です。\n"
            "みんなで集まって対戦しましょう！有頂天の塔や対戦募集をどんどん使ってください。\n"
            "行けそうな人は「🙋 今夜行けます」を押してください。21:00にメンションでお知らせします。"
        ),
        color=HOT_TIME_COLOR,
    )
    if rsvps:
        names = "、".join(m.display_name for m in rsvps)
        if len(names) > 1024:
            names = names[:1021] + "…"
    else:
        names = "まだいません。一番乗りしませんか？"
    embed.add_field(name=f"🙋 今夜行けます: {len(rsvps)}人", value=names, inline=False)
    return embed


async def build_start_embed(guild: discord.Guild, rsvp_count: int = 0) -> discord.Embed:
    queue = await db_manager.get_rating_queue(guild.id)
    recruiting = await db_manager.count_recruiting_threads()
    embed = discord.Embed(
        title=f"🔥 {HOT_TIME_NAME} スタート！",
        description="**24:00** まで開催中です。対戦相手を探している人に声をかけてみましょう！",
        color=HOT_TIME_COLOR,
    )
    embed.add_field(name="🗼 有頂天の塔 待機中", value=f"{len(queue)}人", inline=True)
    embed.add_field(name="📣 対戦募集 募集中", value=f"{recruiting}件", inline=True)
    embed.add_field(name="🙋 今夜行けます", value=f"{rsvp_count}人", inline=True)
    return embed


async def build_summary_embed(session: datetime.datetime, until: datetime.datetime | None = None) -> discord.Embed:
    """開催日 session のHOT TIMEの結果。until を渡すと、その時刻までの途中経過にする"""
    start = session + _HOT_TIME_START
    end = session + _HOT_TIME_END
    in_progress = until is not None and until < end
    rows = await db_manager.get_hot_time_summary(_to_db_time(start), _to_db_time(until if in_progress else end))

    label = "途中経過" if in_progress else "結果"
    embed = discord.Embed(
        title=f"🔥 {HOT_TIME_NAME} {label}（{session.month}/{session.day}）",
        color=HOT_TIME_COLOR,
    )
    if not rows:
        embed.description = "この回は対戦の報告がありませんでした。次回もお待ちしています！"
    else:
        total = sum(r["matches"] for r in rows) // 2
        embed.description = f"対戦数 **{total}戦** / 参加人数 **{len(rows)}人**\n参加してくれたみなさん、ありがとうございました！"
        embed.add_field(
            name="⚔️ 対戦数",
            value="\n".join(
                f"{_MEDALS[r['rank']]} **{r['username']}** — {r['matches']}戦" for r in _top3(rows, "matches")
            ),
            inline=False,
        )
        gainers = _top3(rows, "rating_gain")
        embed.add_field(
            name="📈 レート上昇",
            value="\n".join(
                f"{_MEDALS[r['rank']]} **{r['username']}** — +{r['rating_gain']:.1f}" for r in gainers
            ) or "該当者なし",
            inline=False,
        )
    embed.set_footer(text="21:00〜24:00に報告された確定済みの戦績が対象")
    return embed


async def _get_notify_role(interaction: discord.Interaction) -> discord.Role | None:
    setting = await db_manager.get_hot_time_setting(interaction.guild_id)
    role = interaction.guild.get_role(setting["role_id"]) if setting and setting["role_id"] else None
    if role is None:
        await interaction.response.send_message("❌ HOT TIMEの通知ロールが設定されていません。", ephemeral=True)
    return role


class HotTimeRoleView(discord.ui.View):
    """HOT TIMEの通知ロールを自分で付け外しするボタン（常設パネル・朝の予告に付ける）"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="通知を受け取る", emoji="🔔", style=discord.ButtonStyle.primary, custom_id="hot_time_role_add", row=1)
    async def add_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = await _get_notify_role(interaction)
        if role is None:
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(f"すでに {role.mention} が付いています。", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="HOT TIME 通知の登録")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Botにロールを付ける権限がありません。管理者に連絡してください。", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔔 {role.mention} を付けました。毎週木曜の朝と21:00にお知らせします。", ephemeral=True
        )

    @discord.ui.button(label="通知をやめる", emoji="🔕", style=discord.ButtonStyle.secondary, custom_id="hot_time_role_remove", row=1)
    async def remove_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = await _get_notify_role(interaction)
        if role is None:
            return
        if role not in interaction.user.roles:
            await interaction.response.send_message(f"{role.mention} は付いていません。", ephemeral=True)
            return
        try:
            await interaction.user.remove_roles(role, reason="HOT TIME 通知の解除")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Botにロールを外す権限がありません。管理者に連絡してください。", ephemeral=True
            )
            return
        await interaction.response.send_message(f"🔕 {role.mention} を外しました。", ephemeral=True)


class HotTimeMorningView(HotTimeRoleView):
    """朝の予告に付けるボタン。「今夜行けます」の登録・取り消しと、通知ロールの付け外し"""

    def __init__(self, include_role: bool = True):
        super().__init__()
        if not include_role:
            self.remove_item(self.add_role)
            self.remove_item(self.remove_role)

    async def _session_date(self, interaction: discord.Interaction) -> str | None:
        """押された予告の開催日。その回の受付が終わっていれば、その旨を返信して None を返す"""
        now = datetime.datetime.now(JST)
        session = _session_start(interaction.message.created_at)
        if session != _session_start(now) or now >= session + _HOT_TIME_END:
            await interaction.response.send_message("この回のHOT TIMEの受付は終了しました。", ephemeral=True)
            return None
        return session.strftime("%Y-%m-%d")

    async def _update_message(self, interaction: discord.Interaction, session_date: str):
        user_ids = await db_manager.get_hot_time_rsvps(interaction.guild_id, session_date)
        try:
            await interaction.message.edit(embed=build_morning_embed(_rsvp_members(interaction.guild, user_ids)))
        except discord.HTTPException as e:
            logger.warning(f"HOT TIME予告の更新失敗 (message={interaction.message.id}): {e}")

    @discord.ui.button(label="今夜行けます", emoji="🙋", style=discord.ButtonStyle.success, custom_id="hot_time_rsvp_add", row=0)
    async def add_rsvp(self, interaction: discord.Interaction, button: discord.ui.Button):
        session_date = await self._session_date(interaction)
        if session_date is None:
            return
        added = await db_manager.add_hot_time_rsvp(interaction.guild_id, session_date, interaction.user.id)
        if not added:
            await interaction.response.send_message("すでに「今夜行けます」を登録しています。", ephemeral=True)
            return
        await interaction.response.send_message("🙋 登録しました！21:00にメンションでお知らせします。", ephemeral=True)
        await self._update_message(interaction, session_date)

    @discord.ui.button(label="取り消す", style=discord.ButtonStyle.secondary, custom_id="hot_time_rsvp_remove", row=0)
    async def remove_rsvp(self, interaction: discord.Interaction, button: discord.ui.Button):
        session_date = await self._session_date(interaction)
        if session_date is None:
            return
        removed = await db_manager.remove_hot_time_rsvp(interaction.guild_id, session_date, interaction.user.id)
        if not removed:
            await interaction.response.send_message("「今夜行けます」は登録していません。", ephemeral=True)
            return
        await interaction.response.send_message("取り消しました。", ephemeral=True)
        await self._update_message(interaction, session_date)


class HotTimeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Bot起動・再接続時に常設パネルのViewを再登録する。
        HotTimeMorningView は通知ロールのボタンも含むので、常設パネルのボタンもこれで動く"""
        self.bot.add_view(HotTimeMorningView())

    async def cog_load(self):
        if not self._post_hot_time.is_running():
            self._post_hot_time.start()

    async def cog_unload(self):
        self._post_hot_time.cancel()

    @tasks.loop(minutes=1)
    async def _post_hot_time(self):
        # ここで例外を外に出すとループ自体が止まり、再起動まで投稿されなくなるため必ず握る
        try:
            now = datetime.datetime.now(JST)
            session = _session_start(now)
            settings = await db_manager.get_hot_time_settings()
        except Exception as e:
            logger.error(f"HOT TIME設定取得失敗: {e}")
            return
        session_date = session.strftime("%Y-%m-%d")
        for setting in settings:
            for kind, (due, deadline) in _SCHEDULE.items():
                if not (session + due <= now < session + deadline):
                    continue
                if setting[f"last_{kind}_date"] == session_date:
                    continue
                if kind in ("start", "summary"):
                    # 開始・終了に合わせて、有頂天の塔のパネルと待機状況ボードの見た目を切り替える
                    await self._refresh_rating_display(setting["guild_id"])
                try:
                    await self._post(setting, kind, session)
                    await db_manager.mark_hot_time_posted(setting["guild_id"], kind, session_date)
                except Exception as e:
                    logger.warning(f"HOT TIME投稿失敗 (guild={setting['guild_id']}, kind={kind}): {e}")

    @_post_hot_time.before_loop
    async def _before_post_hot_time(self):
        await self.bot.wait_until_ready()

    async def _refresh_rating_display(self, guild_id: int):
        """有頂天の塔のパネルと待機状況ボードを、HOT TIMEの開催状況に合わせて描き直す"""
        cog = self.bot.cogs.get("RatingRoomCog")
        guild = self.bot.get_guild(guild_id)
        if cog is None or guild is None:
            return
        try:
            await cog.refresh_hot_time_display(guild)
        except Exception as e:
            logger.warning(f"HOT TIMEの有頂天の塔表示更新失敗 (guild={guild_id}): {e}")

    async def _refresh_calendar(self, guild_id: int):
        """カレンダーにHOT TIMEの予定を出し入れするため、設置済みのカレンダーを描き直す"""
        cog = self.bot.cogs.get("CalendarCog")
        if cog is None:
            return
        try:
            await cog._refresh_calendar(guild_id)
        except Exception as e:
            logger.warning(f"HOT TIME設定後のカレンダー更新失敗 (guild={guild_id}): {e}")

    async def _post(self, setting: dict, kind: str, session: datetime.datetime):
        channel = self.bot.get_channel(setting["channel_id"])
        if channel is None:
            raise RuntimeError(f"チャンネルが見つかりません: {setting['channel_id']}")
        role = channel.guild.get_role(setting["role_id"]) if setting["role_id"] else None

        if kind == "summary":
            await channel.send(embed=await build_summary_embed(session))
            return

        kwargs = {}
        if role is not None:
            kwargs["content"] = role.mention
            kwargs["allowed_mentions"] = discord.AllowedMentions(roles=[role])
        if kind == "morning":
            embed = build_morning_embed()
            kwargs["view"] = HotTimeMorningView(include_role=role is not None)
        else:
            # 「今夜行けます」を押した人には、通知ロールの有無にかかわらずメンションで知らせる
            user_ids = await db_manager.get_hot_time_rsvps(channel.guild.id, session.strftime("%Y-%m-%d"))
            members = _rsvp_members(channel.guild, user_ids)
            embed = await build_start_embed(channel.guild, len(members))
            mentioned = members[:_RSVP_MENTION_LIMIT]
            if mentioned:
                kwargs["content"] = " ".join(filter(None, [kwargs.get("content"), *(m.mention for m in mentioned)]))
                kwargs["allowed_mentions"] = discord.AllowedMentions(
                    roles=[role] if role is not None else False, users=mentioned
                )
        await channel.send(embed=embed, **kwargs)

    @app_commands.command(
        name="hot_time_setup",
        description="HOT TIME（毎週木曜21:00〜24:00）のお知らせを投稿するチャンネルを設定します（管理者のみ）",
    )
    @app_commands.describe(channel="お知らせの投稿先", role="お知らせでメンションする通知ロール（省略するとメンションしない）")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hot_time_setup(
        self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role | None = None
    ):
        # 設定した時点で予定時刻を過ぎている投稿は投稿済み扱いにし、まとめて投稿されないようにする
        now = datetime.datetime.now(JST)
        session = _session_start(now)
        session_date = session.strftime("%Y-%m-%d")
        posted = {kind: session_date if now >= session + due else None for kind, (due, _) in _SCHEDULE.items()}
        await db_manager.set_hot_time_settings(interaction.guild_id, channel.id, role.id if role else None, posted)
        role_text = f"{role.mention} をメンションして" if role else ""
        await interaction.response.send_message(
            f"✅ 毎週木曜の朝に予告、21:00に開始のお知らせ、24:00に結果のまとめを、{role_text}{channel.mention} へ投稿します。",
            ephemeral=True,
        )
        await self._refresh_calendar(interaction.guild_id)
        await self._refresh_rating_display(interaction.guild_id)
        logger.info(f"hot_time_setup: guild={interaction.guild_id} channel={channel.id} role={role.id if role else None}")

    @app_commands.command(
        name="hot_time_stop",
        description="HOT TIMEのお知らせの自動投稿を止めます（管理者のみ）",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hot_time_stop(self, interaction: discord.Interaction):
        deleted = await db_manager.delete_hot_time_settings(interaction.guild_id)
        if deleted:
            await interaction.response.send_message("✅ HOT TIMEのお知らせを止めました。", ephemeral=True)
        else:
            await interaction.response.send_message("HOT TIMEのお知らせは設定されていません。", ephemeral=True)
        await self._refresh_calendar(interaction.guild_id)
        await self._refresh_rating_display(interaction.guild_id)
        logger.info(f"hot_time_stop: guild={interaction.guild_id} deleted={deleted}")

    @app_commands.command(
        name="hot_time_panel",
        description="HOT TIMEの通知ロールを付け外しするパネルをこのチャンネルに設置します（管理者のみ）",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hot_time_panel(self, interaction: discord.Interaction):
        setting = await db_manager.get_hot_time_setting(interaction.guild_id)
        if not setting or not setting["role_id"]:
            await interaction.response.send_message(
                "❌ 先に `/hot_time_setup` で通知ロールを設定してください。", ephemeral=True
            )
            return
        embed = discord.Embed(
            title=f"🔥 {HOT_TIME_NAME}",
            description=(
                "毎週木曜 **21:00〜24:00** はHOT TIMEです。\n"
                "通知を受け取ると、木曜の朝と21:00にお知らせが届きます。"
            ),
            color=HOT_TIME_COLOR,
        )
        await interaction.channel.send(embed=embed, view=HotTimeRoleView())
        await interaction.response.send_message("✅ パネルを設置しました。", ephemeral=True)
        logger.info(f"hot_time_panel: guild={interaction.guild_id} channel={interaction.channel_id}")

    @app_commands.command(
        name="hot_time_result",
        description="HOT TIMEの結果を表示します（開催中なら途中経過）",
    )
    async def hot_time_result(self, interaction: discord.Interaction):
        now = datetime.datetime.now(JST)
        session = _session_start(now)
        if now < session + _HOT_TIME_START:
            # 今週の開始前なら前回分
            session -= datetime.timedelta(days=7)
        await interaction.response.defer()
        await interaction.followup.send(embed=await build_summary_embed(session, until=now))


async def setup(bot: commands.Bot):
    await bot.add_cog(HotTimeCog(bot))
