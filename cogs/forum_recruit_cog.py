import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")


# ─────────────────────────────────────────────
#  募集モーダル
# ─────────────────────────────────────────────

class RecruitForumModal(discord.ui.Modal, title="⚔️ 対戦募集を投稿"):
    """フォーラムチャンネルに対戦募集スレッドを作成するモーダル"""

    thread_title = discord.ui.TextInput(
        label="タイトル（必須）",
        placeholder="例: 先三募集中！気軽にどうぞ",
        required=True,
        max_length=100,
    )
    match_format = discord.ui.TextInput(
        label="対戦形式（任意）",
        placeholder="例: 先三、先二、フリーなど",
        required=False,
        max_length=50,
    )
    character = discord.ui.TextInput(
        label="使用キャラ（任意）",
        placeholder="例: 霊夢、魔理沙",
        required=False,
        max_length=50,
    )
    comment = discord.ui.TextInput(
        label="コメント（任意）",
        style=discord.TextStyle.paragraph,
        placeholder="条件や一言コメントなど",
        required=False,
        max_length=500,
    )

    def __init__(self, forum_channel_id: int):
        super().__init__()
        self.forum_channel_id = forum_channel_id

    async def on_submit(self, interaction: discord.Interaction):
        forum_channel = interaction.guild.get_channel(self.forum_channel_id)
        if not isinstance(forum_channel, discord.ForumChannel):
            await interaction.response.send_message(
                "❌ 投稿先のフォーラムチャンネルが見つかりません。管理者にご連絡ください。",
                ephemeral=True,
            )
            return

        perms = forum_channel.permissions_for(interaction.guild.me)
        if not perms.create_public_threads:
            await interaction.response.send_message(
                f"❌ {forum_channel.mention} にスレッドを作成する権限がありません。\n"
                "管理者にBotの **「公開スレッドを作成」** 権限の付与をお願いしてください。",
                ephemeral=True,
            )
            return

        fmt = self.match_format.value.strip() or "未指定"
        char = self.character.value.strip() or "未指定"
        comment_val = self.comment.value.strip() or "特になし"

        embed = discord.Embed(
            title="⚔️ 対戦募集",
            description=f"{interaction.user.mention} が対戦相手を募集しています！\nこのスレッドに返信するか、DMでお声がけください。",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="対戦形式", value=fmt, inline=True)
        embed.add_field(name="使用キャラ", value=char, inline=True)
        embed.add_field(name="コメント", value=comment_val, inline=False)
        embed.set_footer(
            text=f"募集者: {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.defer(ephemeral=True)

        try:
            result = await forum_channel.create_thread(
                name=self.thread_title.value,
                embed=embed,
            )
            thread = result.thread
            logger.info(
                f"forum_recruit: user={interaction.user.id} "
                f"forum={forum_channel.id} thread={thread.id}"
            )
            await interaction.followup.send(
                f"✅ 対戦募集を投稿しました！\n→ {thread.mention}",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ 権限不足で投稿できませんでした。管理者にご連絡ください。",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"RecruitForumModal エラー: {e}")
            await interaction.followup.send(
                f"❌ 投稿中にエラーが発生しました: {e}",
                ephemeral=True,
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"RecruitForumModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ 送信中にエラーが発生しました。", ephemeral=True
            )


# ─────────────────────────────────────────────
#  永続的なパネル View
# ─────────────────────────────────────────────

class RecruitForumPanelView(discord.ui.View):
    """Bot再起動後もボタンが機能するよう timeout=None で定義"""

    def __init__(self, forum_channel_id: int):
        super().__init__(timeout=None)
        self.forum_channel_id = forum_channel_id

        btn = discord.ui.Button(
            label="⚔️ 対戦を募集する",
            style=discord.ButtonStyle.primary,
            custom_id=f"forum_recruit_btn:{forum_channel_id}",
        )
        btn.callback = self._btn_callback
        self.add_item(btn)

    async def _btn_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RecruitForumModal(self.forum_channel_id))


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class ForumRecruitCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """起動時に保存済みパネルの View を再登録してボタンを復元する"""
        panels = await db_manager.get_recruit_panels()
        for panel in panels:
            view = RecruitForumPanelView(panel["forum_channel_id"])
            self.bot.add_view(view, message_id=panel["message_id"])
        if panels:
            logger.info(f"forum_recruit: {len(panels)} 件のパネルViewを再登録しました")

    @app_commands.command(
        name="setup_recruit_panel",
        description="対戦募集ボタンのパネルをこのチャンネルに設置します（管理者用）",
    )
    @app_commands.describe(
        forum_channel="募集投稿の作成先フォーラムチャンネル",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_recruit_panel(
        self,
        interaction: discord.Interaction,
        forum_channel: discord.ForumChannel,
    ):
        embed = discord.Embed(
            title="⚔️ 対戦募集",
            description=(
                "下のボタンを押すと対戦募集フォームが開きます。\n"
                f"入力した内容は {forum_channel.mention} に新規投稿されます。"
            ),
            color=discord.Color.from_rgb(52, 152, 219),
        )
        embed.set_footer(text=f"投稿先: #{forum_channel.name}")

        view = RecruitForumPanelView(forum_channel.id)

        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        await db_manager.add_recruit_panel(
            message_id=message.id,
            channel_id=interaction.channel_id,
            forum_channel_id=forum_channel.id,
        )
        logger.info(
            f"setup_recruit_panel: message={message.id} "
            f"channel={interaction.channel_id} forum={forum_channel.id}"
        )

    @app_commands.command(
        name="remove_recruit_panel",
        description="対戦募集パネルを削除します（管理者用）",
    )
    @app_commands.describe(message_id="削除するパネルのメッセージID")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_recruit_panel(
        self,
        interaction: discord.Interaction,
        message_id: str,
    ):
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message(
                "❌ メッセージIDには数値を入力してください。", ephemeral=True
            )
            return

        deleted = await db_manager.delete_recruit_panel(mid)
        if not deleted:
            await interaction.response.send_message(
                "❌ 指定されたIDのパネルが見つかりませんでした。", ephemeral=True
            )
            return

        # メッセージ本体の削除を試みる
        try:
            msg = await interaction.channel.fetch_message(mid)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        await interaction.response.send_message(
            "✅ 対戦募集パネルを削除しました。", ephemeral=True
        )
        logger.info(f"remove_recruit_panel: message={mid} by user={interaction.user.id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ForumRecruitCog(bot))
