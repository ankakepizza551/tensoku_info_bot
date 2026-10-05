import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

JST = datetime.timezone(datetime.timedelta(hours=9))

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# (キー, 見出し, 単位)
_CATEGORIES = [
    ("matches", "⚔️ 対戦数MVP", "戦"),
    ("wins", "🏆 勝利数MVP", "勝"),
    ("opponents", "🤝 対戦相手数MVP", "人"),
]


def _previous_month(now: datetime.datetime) -> str:
    last_day_prev = now.replace(day=1) - datetime.timedelta(days=1)
    return last_day_prev.strftime("%Y-%m")


def build_mvp_embed(mvp: dict) -> discord.Embed:
    year, mon = mvp["month"].split("-")
    embed = discord.Embed(
        title=f"🌟 {year}年{int(mon)}月 月間MVP",
        color=discord.Color.from_rgb(241, 196, 15),
    )
    for key, title, unit in _CATEGORIES:
        entries = mvp[key]
        if entries:
            text = "\n".join(
                f"{_MEDALS[e['rank']]} **{e['username']}** — {e['value']}{unit}" for e in entries
            )
        else:
            text = "該当者なし"
        embed.add_field(name=title, value=text, inline=False)
    cap = db_manager.MVP_DAILY_PAIR_CAP
    embed.set_footer(text=f"確定済みの戦績が対象 / 同じ相手との対戦は1日{cap}戦までカウント")
    return embed


async def _send_mvp(interaction: discord.Interaction, month: str):
    await interaction.response.defer(ephemeral=True)
    mvp = await db_manager.get_monthly_mvp(month)
    await interaction.followup.send(embed=build_mvp_embed(mvp), ephemeral=True)


class MvpPanelView(discord.ui.View):
    """月間MVPの確認ボタン（常設パネル・月初の自動投稿に付ける）"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="今月の途中経過", emoji="📈", style=discord.ButtonStyle.primary, custom_id="mvp_panel_current")
    async def current(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_mvp(interaction, datetime.datetime.now(JST).strftime("%Y-%m"))

    @discord.ui.button(label="先月の結果", emoji="🌟", style=discord.ButtonStyle.secondary, custom_id="mvp_panel_previous")
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _send_mvp(interaction, _previous_month(datetime.datetime.now(JST)))


class MvpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Bot起動・再接続時に常設パネルのViewを再登録する"""
        self.bot.add_view(MvpPanelView())

    async def cog_load(self):
        if not self._post_monthly_mvp.is_running():
            self._post_monthly_mvp.start()

    async def cog_unload(self):
        self._post_monthly_mvp.cancel()

    @tasks.loop(minutes=10)
    async def _post_monthly_mvp(self):
        # ここで例外を外に出すとループ自体が止まり、再起動まで投稿されなくなるため必ず握る
        try:
            prev = _previous_month(datetime.datetime.now(JST))
            settings = await db_manager.get_mvp_settings()
        except Exception as e:
            logger.error(f"MVP設定取得失敗: {e}")
            return
        for setting in settings:
            if setting["last_posted_month"] == prev:
                continue
            channel = self.bot.get_channel(setting["channel_id"])
            if channel is None:
                logger.warning(f"MVP投稿スキップ（チャンネルが見つかりません）: guild={setting['guild_id']}")
                continue
            try:
                mvp = await db_manager.get_monthly_mvp(prev)
                await channel.send(embed=build_mvp_embed(mvp), view=MvpPanelView())
                await db_manager.mark_mvp_posted(setting["guild_id"], prev)
            except Exception as e:
                logger.warning(f"MVP投稿失敗 (guild={setting['guild_id']}): {e}")

    @_post_monthly_mvp.before_loop
    async def _before_post_monthly_mvp(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="mvp", description="月間MVP（対戦数・勝利数・対戦相手数）を表示します")
    @app_commands.describe(month="対象の月（例: 2026-09）。省略すると今月")
    async def mvp(self, interaction: discord.Interaction, month: str | None = None):
        if month is None:
            month = datetime.datetime.now(JST).strftime("%Y-%m")
        else:
            try:
                month = datetime.datetime.strptime(month.replace("/", "-"), "%Y-%m").strftime("%Y-%m")
            except ValueError:
                await interaction.response.send_message(
                    "❌ 月は `YYYY-MM` の形式で入力してください。例: `2026-09`", ephemeral=True
                )
                return
        await interaction.response.defer()
        mvp = await db_manager.get_monthly_mvp(month)
        await interaction.followup.send(embed=build_mvp_embed(mvp))

    @app_commands.command(
        name="mvp_setup",
        description="月間MVPを毎月1日に自動投稿するチャンネルを設定します（管理者のみ）",
    )
    @app_commands.describe(channel="投稿先のチャンネル")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def mvp_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        # 設定した時点で前月分は投稿済み扱いにし、次の月初から自動投稿する
        prev = _previous_month(datetime.datetime.now(JST))
        await db_manager.set_mvp_channel(interaction.guild_id, channel.id, prev)
        await interaction.response.send_message(
            f"✅ 毎月1日に前月の月間MVPを {channel.mention} へ投稿します。", ephemeral=True
        )
        logger.info(f"mvp_setup: guild={interaction.guild_id} channel={channel.id}")

    @app_commands.command(
        name="mvp_panel",
        description="月間MVPの確認ボタンのパネルをこのチャンネルに設置します（管理者のみ）",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def mvp_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🌟 月間MVP",
            description="対戦数・勝利数・対戦相手数の上位3名を確認できます。\nボタンを押すと、あなただけに表示されます。",
            color=discord.Color.from_rgb(241, 196, 15),
        )
        await interaction.channel.send(embed=embed, view=MvpPanelView())
        await interaction.response.send_message("✅ パネルを設置しました。", ephemeral=True)
        logger.info(f"mvp_panel: guild={interaction.guild_id} channel={interaction.channel_id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(MvpCog(bot))
