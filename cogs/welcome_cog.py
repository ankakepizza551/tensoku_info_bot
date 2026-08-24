import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")


class WelcomePanelView(discord.ui.View):
    """固定custom_idを使うグローバル永続View。再起動後もボタンが機能する"""

    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            label="🎊 ステッカーを受け取る",
            style=discord.ButtonStyle.success,
            custom_id="welcome_panel:sticker",
        )
        btn.callback = self._sticker_callback
        self.add_item(btn)

    async def _sticker_callback(self, interaction: discord.Interaction):
        stickers = interaction.guild.stickers
        if not stickers:
            await interaction.response.send_message(
                "❌ このサーバーにはカスタムステッカーが登録されていません。管理者にご連絡ください。",
                ephemeral=True,
            )
            return

        chosen = random.choice(stickers)
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.channel.send(stickers=[chosen])
            await interaction.followup.send("🎊 ステッカーを送りました！", ephemeral=True)
            logger.info(f"welcome_sticker: user={interaction.user.id} sticker={chosen.name}")
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ ステッカーを送信する権限がありません。管理者にご連絡ください。", ephemeral=True
            )
        except discord.HTTPException as e:
            logger.warning(f"welcome_sticker: 送信失敗 error={e}")
            await interaction.followup.send("❌ ステッカーの送信に失敗しました。", ephemeral=True)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(WelcomePanelView())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        settings = await db_manager.get_welcome_settings(member.guild.id)
        if settings is None:
            return

        channel = member.guild.get_channel(settings["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="🎉 ようこそ！",
            description=(
                f"{member.mention} さん、**{member.guild.name}** へようこそ！\n"
                "下のボタンを押すと、お祝いのステッカーが届きます🎊"
            ),
            color=discord.Color.from_rgb(241, 196, 15),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        try:
            await channel.send(embed=embed, view=WelcomePanelView())
        except discord.Forbidden:
            logger.warning(f"welcome: メッセージ送信失敗（権限不足） guild={member.guild.id}")

    @app_commands.command(
        name="setup_welcome",
        description="入室時のウェルカムメッセージを送るチャンネルを設定します（管理者用）",
    )
    @app_commands.describe(channel="ウェルカムメッセージを送信するチャンネル")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_welcome(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db_manager.save_welcome_settings(interaction.guild_id, channel.id)

        embed = discord.Embed(
            title="✅ ウェルカムメッセージ設定完了",
            description=(
                f"新しいメンバーが参加すると、{channel.mention} にウェルカムメッセージを送ります。\n"
                "サーバーにカスタムステッカーが登録されていれば、ボタンを押した人にランダムで1つ返します。"
            ),
            color=discord.Color.from_rgb(46, 204, 113),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"setup_welcome: guild={interaction.guild_id} channel={channel.id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
