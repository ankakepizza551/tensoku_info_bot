import logging
import discord
from discord import app_commands
from discord.ext import commands

import config
from database.db_manager import (
    add_letter,
    get_letter,
    hide_letter,
    set_letter_admin_message,
    unhide_letter,
)

logger = logging.getLogger("TensokuMatchBot")


def _build_letter_embed(letter_id: int, title: str, body: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"📨 お便り No.{letter_id}",
        color=discord.Color.from_rgb(149, 117, 205),
    )
    embed.add_field(name="件名", value=title, inline=False)
    embed.add_field(name="内容", value=body, inline=False)
    embed.set_footer(text="送信者：匿名　　/tegami_check で送信者を確認できます")
    return embed


def _build_hidden_embed(letter_id: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"📨 お便り No.{letter_id}",
        description="🚫 このお便りは管理者により非表示にされました。",
        color=discord.Color.from_rgb(100, 100, 100),
    )
    embed.set_footer(text="内容は /tegami_check で確認できます")
    return embed


class LetterModal(discord.ui.Modal, title="📨 匿名お便りを送る"):
    letter_title = discord.ui.TextInput(
        label="タイトル",
        placeholder="件名を入力してください",
        max_length=100,
        required=True,
    )
    letter_body = discord.ui.TextInput(
        label="本文",
        placeholder="内容を自由に書いてください（誰が送ったかは表示されません）",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        admin_channel_id = config.LETTER_ADMIN_CHANNEL_ID
        if not admin_channel_id:
            await interaction.response.send_message(
                "❌ 送信先チャンネルが設定されていません。管理者にお知らせください。",
                ephemeral=True,
            )
            return

        admin_channel = interaction.client.get_channel(admin_channel_id)
        if admin_channel is None:
            await interaction.response.send_message(
                "❌ 送信先チャンネルが見つかりません。管理者にお知らせください。",
                ephemeral=True,
            )
            return

        letter_id = await add_letter(
            sender_id=interaction.user.id,
            title=self.letter_title.value,
            body=self.letter_body.value,
        )

        embed = _build_letter_embed(letter_id, self.letter_title.value, self.letter_body.value)

        message = await admin_channel.send(embed=embed)
        await set_letter_admin_message(letter_id, message.id)
        logger.info(f"匿名お便り投稿 letter_id={letter_id} sender={interaction.user.id}")

        await interaction.response.send_message(
            f"✅ お便りを送信しました！",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"LetterModal エラー: {error}")
        await interaction.response.send_message(
            "❌ 送信中にエラーが発生しました。しばらくしてから再試行してください。",
            ephemeral=True,
        )


class LetterPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            label="📨 匿名お便りを送る",
            style=discord.ButtonStyle.primary,
            custom_id="letter_panel",
        )
        btn.callback = self._btn_callback
        self.add_item(btn)

    async def _btn_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LetterModal())


class LetterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(LetterPanelView())

    @app_commands.command(name="tegami", description="匿名でお便りを送ります（送信者名は表示されません）")
    async def tegami(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LetterModal())

    @app_commands.command(name="setup_letter_panel", description="匿名お便りボタンをこのチャンネルに設置します（管理者用）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_letter_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📨 匿名お便り",
            description=(
                "下のボタンを押すとお便り送信フォームが開きます。\n"
                "送信者名は管理者にも **表示されません**（完全匿名）。"
            ),
            color=discord.Color.from_rgb(149, 117, 205),
        )
        view = LetterPanelView()
        await interaction.response.send_message(embed=embed, view=view)
        logger.info(f"setup_letter_panel: channel={interaction.channel_id} by user={interaction.user.id}")

    @app_commands.command(name="tegami_check", description="【管理者専用】お便りの送信者を確認します")
    @app_commands.describe(letter_id="確認したいお便りのNo.")
    @app_commands.default_permissions(administrator=True)
    async def tegami_check(self, interaction: discord.Interaction, letter_id: int):
        letter = await get_letter(letter_id)
        if letter is None:
            await interaction.response.send_message(
                f"❌ No.{letter_id} のお便りは見つかりませんでした。",
                ephemeral=True,
            )
            return

        sender = interaction.guild.get_member(letter["sender_id"])
        if sender:
            sender_info = f"{sender.display_name}（{sender}）ID: `{sender.id}`"
        else:
            sender_info = f"ID: `{letter['sender_id']}`（サーバーに存在しないユーザー）"

        embed = discord.Embed(
            title=f"📋 お便り No.{letter_id} の送信者情報",
            color=discord.Color.from_rgb(231, 76, 60),
        )
        embed.add_field(name="送信者", value=sender_info, inline=False)
        embed.add_field(name="タイトル", value=letter["title"], inline=False)
        embed.add_field(name="本文", value=letter["body"], inline=False)
        embed.add_field(name="送信日時", value=letter["created_at"], inline=False)
        embed.set_footer(text="この情報は管理者のみに表示されています")

        await interaction.response.send_message(embed=embed, ephemeral=True)

        # 管理用チャンネルにも記録を残す
        admin_channel_id = config.LETTER_ADMIN_CHANNEL_ID
        if admin_channel_id:
            admin_channel = interaction.client.get_channel(admin_channel_id)
            if admin_channel:
                log_embed = discord.Embed(
                    title=f"📋 お便り No.{letter_id} 確認ログ",
                    color=discord.Color.from_rgb(231, 76, 60),
                )
                log_embed.add_field(name="確認した管理者", value=f"{interaction.user.display_name}（{interaction.user}）", inline=False)
                log_embed.add_field(name="送信者", value=sender_info, inline=False)
                log_embed.add_field(name="タイトル", value=letter["title"], inline=False)
                log_embed.add_field(name="本文", value=letter["body"], inline=False)
                log_embed.add_field(name="送信日時", value=letter["created_at"], inline=False)
                await admin_channel.send(embed=log_embed)

        logger.info(
            f"tegami_check: admin={interaction.user.id} letter_id={letter_id} sender={letter['sender_id']}"
        )

    @app_commands.command(name="tegami_reply", description="【管理者専用】お便りに返信を投稿します")
    @app_commands.describe(
        letter_id="返信したいお便りのNo.",
        reply="返信内容",
        quote="元のお便りの内容を引用するか（既定：引用する）",
    )
    @app_commands.default_permissions(administrator=True)
    async def tegami_reply(self, interaction: discord.Interaction, letter_id: int, reply: str, quote: bool = True):
        letter = await get_letter(letter_id)
        if letter is None:
            await interaction.response.send_message(
                f"❌ No.{letter_id} のお便りは見つかりませんでした。",
                ephemeral=True,
            )
            return

        # 非表示にしたお便りは、たとえ引用を指定されても内容を出さない
        show_quote = quote and not letter["is_hidden"]

        embed = discord.Embed(
            title=f"💬 お便り No.{letter_id} への返信",
            color=discord.Color.from_rgb(88, 101, 242),
        )
        if show_quote:
            quoted_title = "\n".join(f"> {line}" for line in letter["title"].splitlines())
            quoted_body = "\n".join(f"> {line}" for line in letter["body"].splitlines())
            embed.add_field(name="引用（件名）", value=quoted_title, inline=False)
            embed.add_field(name="引用（内容）", value=quoted_body, inline=False)
        elif letter["is_hidden"]:
            embed.description = "（このお便りは非表示のため、内容は伏せています）"
        embed.add_field(name="返信", value=reply, inline=False)
        embed.set_footer(text=f"返信者：{interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)
        logger.info(
            f"tegami_reply: admin={interaction.user.id} letter_id={letter_id} quoted={show_quote}"
        )

    @app_commands.command(name="tegami_hide", description="【管理者専用】不適切なお便りを非表示にします")
    @app_commands.describe(letter_id="非表示にしたいお便りのNo.")
    @app_commands.default_permissions(administrator=True)
    async def tegami_hide(self, interaction: discord.Interaction, letter_id: int):
        letter = await get_letter(letter_id)
        if letter is None:
            await interaction.response.send_message(
                f"❌ No.{letter_id} のお便りは見つかりませんでした。",
                ephemeral=True,
            )
            return

        if letter["is_hidden"]:
            await interaction.response.send_message(
                f"⚠️ No.{letter_id} のお便りは既に非表示になっています。",
                ephemeral=True,
            )
            return

        await hide_letter(letter_id)

        await self._sync_admin_message(interaction, letter_id, letter["admin_message_id"], hidden=True)

        await interaction.response.send_message(
            f"✅ お便り No.{letter_id} を非表示にしました。",
            ephemeral=True,
        )
        logger.info(f"tegami_hide: admin={interaction.user.id} letter_id={letter_id}")

    @app_commands.command(name="tegami_unhide", description="【管理者専用】非表示にしたお便りを再表示します")
    @app_commands.describe(letter_id="再表示したいお便りのNo.")
    @app_commands.default_permissions(administrator=True)
    async def tegami_unhide(self, interaction: discord.Interaction, letter_id: int):
        letter = await get_letter(letter_id)
        if letter is None:
            await interaction.response.send_message(
                f"❌ No.{letter_id} のお便りは見つかりませんでした。",
                ephemeral=True,
            )
            return

        if not letter["is_hidden"]:
            await interaction.response.send_message(
                f"⚠️ No.{letter_id} のお便りは非表示になっていません。",
                ephemeral=True,
            )
            return

        await unhide_letter(letter_id)

        await self._sync_admin_message(interaction, letter_id, letter["admin_message_id"], hidden=False, letter=letter)

        await interaction.response.send_message(
            f"✅ お便り No.{letter_id} を再表示しました。",
            ephemeral=True,
        )
        logger.info(f"tegami_unhide: admin={interaction.user.id} letter_id={letter_id}")

    async def _sync_admin_message(self, interaction, letter_id, admin_message_id, hidden, letter=None):
        """管理チャンネルに投稿済みのお便りEmbedを非表示/再表示状態に合わせて編集する"""
        admin_channel_id = config.LETTER_ADMIN_CHANNEL_ID
        if not admin_channel_id or not admin_message_id:
            return

        admin_channel = interaction.client.get_channel(admin_channel_id)
        if admin_channel is None:
            return

        try:
            message = await admin_channel.fetch_message(admin_message_id)
        except discord.NotFound:
            return

        if hidden:
            embed = _build_hidden_embed(letter_id)
        else:
            embed = _build_letter_embed(letter_id, letter["title"], letter["body"])

        await message.edit(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(LetterCog(bot))
