import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

JST = datetime.timezone(datetime.timedelta(hours=9))


def _parse_datetime(text: str) -> datetime.datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.datetime.strptime(text, fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


class EventReminderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        if not self._check_due_reminders.is_running():
            self._check_due_reminders.start()

    async def cog_unload(self):
        self._check_due_reminders.cancel()

    @tasks.loop(minutes=1)
    async def _check_due_reminders(self):
        now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
        due = await db_manager.get_due_reminders(now_str)
        for reminder in due:
            await db_manager.mark_reminder_sent(reminder["reminder_id"])
            thread = self.bot.get_channel(reminder["thread_id"])
            if not isinstance(thread, discord.Thread):
                logger.warning(
                    f"reminder送信スキップ（スレッドが見つかりません）: reminder_id={reminder['reminder_id']}"
                )
                continue
            content = f"⏰ **リマインダー**\n{reminder['message']}"
            if reminder["role_id"]:
                content = f"<@&{reminder['role_id']}>\n{content}"
            try:
                await thread.send(content)
            except discord.HTTPException as e:
                logger.warning(f"reminder送信失敗 (reminder_id={reminder['reminder_id']}): {e}")

    @_check_due_reminders.before_loop
    async def _before_check_due_reminders(self):
        await self.bot.wait_until_ready()

    # ── /set_reminder ────────────────────────────

    @app_commands.command(
        name="set_reminder",
        description="このスレッドにイベントのリマインダーを登録します（1スレッドに複数件登録可）",
    )
    @app_commands.describe(
        date_time="通知する日時（例: 2026-09-12 20:00）",
        message="通知メッセージ",
        role="通知時にメンションするロール（省略可）",
    )
    async def set_reminder(
        self,
        interaction: discord.Interaction,
        date_time: str,
        message: str,
        role: discord.Role | None = None,
    ):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "❌ このコマンドはイベントのスレッド内で実行してください。", ephemeral=True
            )
            return

        parsed = _parse_datetime(date_time)
        if parsed is None:
            await interaction.response.send_message(
                "❌ 日時の形式が正しくありません。`YYYY-MM-DD HH:MM` の形式で入力してください。\n例: `2026-09-12 20:00`",
                ephemeral=True,
            )
            return
        if parsed <= datetime.datetime.now(JST):
            await interaction.response.send_message(
                "❌ 日時は現在より未来を指定してください。", ephemeral=True
            )
            return

        fire_at = parsed.strftime("%Y-%m-%d %H:%M")
        reminder_id = await db_manager.create_reminder(
            thread_id=interaction.channel.id,
            guild_id=interaction.guild_id,
            creator_id=interaction.user.id,
            fire_at=fire_at,
            message=message,
            role_id=role.id if role else None,
        )

        role_note = f"\n通知先: {role.mention}" if role else ""
        await interaction.response.send_message(
            f"✅ リマインダーを登録しました。（ID: `{reminder_id}`）\n"
            f"日時: {fire_at}{role_note}",
            ephemeral=True,
        )
        logger.info(
            f"set_reminder: thread={interaction.channel.id} reminder_id={reminder_id} fire_at={fire_at}"
        )

    # ── /list_reminders ───────────────────────────

    @app_commands.command(
        name="list_reminders",
        description="このスレッドに登録されている未通知のリマインダー一覧を表示します",
    )
    async def list_reminders(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "❌ このコマンドはイベントのスレッド内で実行してください。", ephemeral=True
            )
            return

        reminders = await db_manager.get_reminders_for_thread(interaction.channel.id)
        if not reminders:
            await interaction.response.send_message(
                "このスレッドに登録中のリマインダーはありません。", ephemeral=True
            )
            return

        lines = []
        for r in reminders:
            role_note = f" → <@&{r['role_id']}>" if r["role_id"] else ""
            lines.append(f"`ID {r['reminder_id']}` {r['fire_at']} — {r['message']}{role_note}")

        embed = discord.Embed(
            title="⏰ 登録中のリマインダー",
            description="\n".join(lines),
            color=discord.Color.from_rgb(52, 152, 219),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /cancel_reminder ──────────────────────────

    @app_commands.command(
        name="cancel_reminder",
        description="登録したリマインダーを削除します（登録者またはサーバー管理者のみ）",
    )
    @app_commands.describe(reminder_id="削除するリマインダー（一覧から選択）")
    async def cancel_reminder(self, interaction: discord.Interaction, reminder_id: int):
        reminder = await db_manager.get_reminder(reminder_id)
        if not reminder or not isinstance(interaction.channel, discord.Thread) or reminder["thread_id"] != interaction.channel.id:
            await interaction.response.send_message(
                "❌ このスレッドに該当するリマインダーが見つかりません。", ephemeral=True
            )
            return

        is_creator = reminder["creator_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not is_creator and not is_admin:
            await interaction.response.send_message(
                "❌ 削除できるのは登録者またはサーバー管理者のみです。", ephemeral=True
            )
            return

        await db_manager.delete_reminder(reminder_id)
        await interaction.response.send_message(
            f"✅ リマインダー（ID: `{reminder_id}`）を削除しました。", ephemeral=True
        )
        logger.info(f"cancel_reminder: reminder_id={reminder_id} by user={interaction.user.id}")

    @cancel_reminder.autocomplete("reminder_id")
    async def cancel_reminder_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        if not isinstance(interaction.channel, discord.Thread):
            return []
        reminders = await db_manager.get_reminders_for_thread(interaction.channel.id)
        choices = []
        for r in reminders:
            label = f"{r['fire_at']} {r['message']}"
            if current.lower() in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=r["reminder_id"]))
        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(EventReminderCog(bot))
