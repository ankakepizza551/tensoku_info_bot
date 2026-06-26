import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database.db_manager as db

JST = datetime.timezone(datetime.timedelta(hours=9))
WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def build_calendar_embed(year: int, month: int, events: list) -> discord.Embed:
    now = datetime.datetime.now(JST)
    month_events = [
        e for e in events
        if e["date"].startswith(f"{year:04d}-{month:02d}-")
    ]
    month_events.sort(key=lambda e: (e["date"], e["time"] or ""))

    lines = []
    for e in month_events:
        dt = datetime.datetime.strptime(e["date"], "%Y-%m-%d")
        wd = WEEKDAYS_JP[dt.weekday()]
        icon = "🟢" if e["type"] == "online" else "🔴"
        line = f"{icon} **{month}/{dt.day}({wd})"
        if e["time"]:
            line += f" {e['time']}"
        line += f"** {e['name']}"
        if e["location"]:
            line += f"\n　📍 {e['location']}"
        if e["url"]:
            line += f"\n　🔗 [詳細]({e['url']})"
        lines.append(line)

    description = "\n\n".join(lines) if lines else "今月のイベントはありません。"
    embed = discord.Embed(
        title=f"📅 {year}年{month}月 イベントカレンダー",
        description=description,
        color=discord.Color.from_rgb(52, 152, 219),
    )
    embed.set_footer(text=f"最終更新: {now.strftime('%Y-%m-%d %H:%M')} JST")
    return embed


class CalendarView(discord.ui.View):
    def __init__(self, year: int, month: int, guild_id: int):
        super().__init__(timeout=None)
        self.year = year
        self.month = month
        self.guild_id = guild_id

        prev_btn = discord.ui.Button(
            label="◀ 前月",
            style=discord.ButtonStyle.secondary,
            custom_id=f"calendar_prev_{guild_id}",
        )
        today_btn = discord.ui.Button(
            label="今月",
            style=discord.ButtonStyle.primary,
            custom_id=f"calendar_today_{guild_id}",
        )
        next_btn = discord.ui.Button(
            label="翌月 ▶",
            style=discord.ButtonStyle.secondary,
            custom_id=f"calendar_next_{guild_id}",
        )
        prev_btn.callback = self._prev_month
        today_btn.callback = self._this_month
        next_btn.callback = self._next_month
        self.add_item(prev_btn)
        self.add_item(today_btn)
        self.add_item(next_btn)

    async def _refresh(self, interaction: discord.Interaction, year: int, month: int):
        self.year = year
        self.month = month
        await db.update_calendar_display(self.guild_id, year, month)
        events = await db.get_events(self.guild_id)
        embed = build_calendar_embed(year, month, events)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _prev_month(self, interaction: discord.Interaction):
        y, m = (self.year - 1, 12) if self.month == 1 else (self.year, self.month - 1)
        await self._refresh(interaction, y, m)

    async def _this_month(self, interaction: discord.Interaction):
        now = datetime.datetime.now(JST)
        await self._refresh(interaction, now.year, now.month)

    async def _next_month(self, interaction: discord.Interaction):
        y, m = (self.year + 1, 1) if self.month == 12 else (self.year, self.month + 1)
        await self._refresh(interaction, y, m)


class CalendarCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        records = await db.get_all_calendar_messages()
        for r in records:
            view = CalendarView(
                year=r["display_year"],
                month=r["display_month"],
                guild_id=r["guild_id"],
            )
            self.bot.add_view(view)

    async def _refresh_calendar(self, guild_id: int):
        record = await db.get_calendar_message(guild_id)
        if not record:
            return
        ch = self.bot.get_channel(record["channel_id"])
        if not ch:
            return
        try:
            msg = await ch.fetch_message(int(record["message_id"]))
        except Exception:
            return
        events = await db.get_events(guild_id)
        embed = build_calendar_embed(record["display_year"], record["display_month"], events)
        view = CalendarView(record["display_year"], record["display_month"], guild_id)
        await msg.edit(embed=embed, view=view)

    @app_commands.command(name="calendar_setup", description="カレンダーをチャンネルに設置します（管理者のみ）")
    @app_commands.describe(channel="設置するチャンネル（省略時は現在のチャンネル）")
    @app_commands.default_permissions(manage_guild=True)
    async def calendar_setup(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        target = channel or interaction.channel
        now = datetime.datetime.now(JST)
        events = await db.get_events(interaction.guild_id)
        embed = build_calendar_embed(now.year, now.month, events)
        view = CalendarView(now.year, now.month, interaction.guild_id)

        await interaction.response.defer(ephemeral=True)
        msg = await target.send(embed=embed, view=view)
        self.bot.add_view(view)

        await db.set_calendar_message(
            guild_id=interaction.guild_id,
            channel_id=target.id,
            message_id=str(msg.id),
            year=now.year,
            month=now.month,
        )
        await interaction.followup.send(
            f"✅ カレンダーを {target.mention} に設置しました！", ephemeral=True
        )

    @app_commands.command(name="add_event", description="カレンダーにイベントを追加します")
    @app_commands.describe(
        date="日付（例: 2026-06-15 または 2026/06/15）",
        name="大会名",
        type="種別",
        time="開始時間（例: 14:00）省略可",
        location="場所 省略可",
        url="詳細URL 省略可",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="オン大会 🟢", value="online"),
        app_commands.Choice(name="オフ大会 🔴", value="offline"),
    ])
    async def add_event(
        self,
        interaction: discord.Interaction,
        date: str,
        name: str,
        type: str,
        time: Optional[str] = None,
        location: Optional[str] = None,
        url: Optional[str] = None,
    ):
        parsed_date = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed_date = datetime.datetime.strptime(date, fmt)
                break
            except ValueError:
                continue
        if not parsed_date:
            await interaction.response.send_message(
                "❌ 日付の形式が正しくありません。`YYYY-MM-DD` の形式で入力してください。", ephemeral=True
            )
            return

        if time:
            try:
                datetime.datetime.strptime(time, "%H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "❌ 時間の形式が正しくありません。`HH:MM` の形式で入力してください。", ephemeral=True
                )
                return

        date_str = parsed_date.strftime("%Y-%m-%d")
        await db.add_event(
            guild_id=interaction.guild_id,
            date=date_str,
            name=name,
            type=type,
            time=time,
            location=location,
            url=url,
        )
        await self._refresh_calendar(interaction.guild_id)
        await interaction.response.send_message(
            f"✅ **{date_str} {name}** を追加しました。", ephemeral=True
        )

    @app_commands.command(name="remove_event", description="カレンダーからイベントを削除します")
    @app_commands.describe(event_id="削除するイベント（一覧から選択）")
    async def remove_event(self, interaction: discord.Interaction, event_id: int):
        success = await db.delete_event(event_id, interaction.guild_id)
        if not success:
            await interaction.response.send_message(
                "❌ 指定されたイベントが見つかりません。", ephemeral=True
            )
            return
        await self._refresh_calendar(interaction.guild_id)
        await interaction.response.send_message("✅ イベントを削除しました。", ephemeral=True)

    @remove_event.autocomplete("event_id")
    async def remove_event_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        events = await db.get_events(interaction.guild_id)
        choices = []
        for e in events:
            label = f"{e['date']} {e['name']}"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=e["event_id"]))
        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(CalendarCog(bot))
