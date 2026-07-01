from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import database.db_manager as db

DEFAULT_WELCOME_MESSAGE = "🎉 {member} さん、ようこそ **{guild}** へ！（{count}人目のメンバーです）"
ALLOWED_PLACEHOLDERS = {"member": "", "guild": "", "count": 0}


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send_welcome(self, member: discord.Member):
        settings = await db.get_welcome_settings(member.guild.id)
        if not settings:
            return
        channel = member.guild.get_channel(settings["channel_id"])
        if not channel:
            return
        text = settings["message"].format(
            member=member.mention,
            guild=member.guild.name,
            count=member.guild.member_count,
        )
        try:
            await channel.send(text)
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # メンバーシップ・スクリーニング（認証）が無効、またはBot参加時などは
        # pending が最初から False なのでそのまま送信する
        if member.pending:
            return
        await self._send_welcome(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # 参加認証（メンバーシップ・スクリーニング）が完了した瞬間にのみ送信する
        if before.pending and not after.pending:
            await self._send_welcome(after)

    @app_commands.command(
        name="welcome_setup",
        description="参加認証完了後に送るウェルカムメッセージを設定します（管理者のみ）",
    )
    @app_commands.describe(
        channel="ウェルカムメッセージを送信するチャンネル",
        message="メッセージ本文（省略時はデフォルト文）。{member}=メンション / {guild}=サーバー名 / {count}=現在のメンバー数",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: Optional[str] = None,
    ):
        text = message or DEFAULT_WELCOME_MESSAGE
        try:
            preview = text.format(**ALLOWED_PLACEHOLDERS)
        except (KeyError, IndexError):
            await interaction.response.send_message(
                "❌ メッセージ内のプレースホルダーが正しくありません。"
                "使用できるのは `{member}` `{guild}` `{count}` のみです。",
                ephemeral=True,
            )
            return

        await db.set_welcome_settings(interaction.guild_id, channel.id, text)
        await interaction.response.send_message(
            f"✅ 参加認証完了後のウェルカムメッセージを {channel.mention} に設定しました。\n"
            f"プレビュー:\n{text.format(member=interaction.user.mention, guild=interaction.guild.name, count=interaction.guild.member_count)}",
            ephemeral=True,
        )

    @app_commands.command(
        name="welcome_disable",
        description="ウェルカムメッセージ機能を無効にします（管理者のみ）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_disable(self, interaction: discord.Interaction):
        deleted = await db.delete_welcome_settings(interaction.guild_id)
        if deleted:
            await interaction.response.send_message(
                "✅ ウェルカムメッセージ機能を無効にしました。", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ ウェルカムメッセージは設定されていません。", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
