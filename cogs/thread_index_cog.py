import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

_MAX_LISTED_THREADS = 30


def _sort_key(thread: discord.Thread):
    return thread.created_at or discord.utils.snowflake_time(thread.id)


def _build_thread_index_embed(channel: discord.TextChannel) -> discord.Embed:
    threads = sorted(channel.threads, key=_sort_key, reverse=True)

    embed = discord.Embed(
        title="🧵 進行中のスレッド一覧",
        color=discord.Color.from_rgb(52, 152, 219),
    )

    if not threads:
        embed.description = "現在アクティブなスレッドはありません。"
    else:
        lines = []
        for thread in threads[:_MAX_LISTED_THREADS]:
            created = discord.utils.format_dt(_sort_key(thread), style="d")
            lines.append(f"• {thread.mention}（{created}）")
        if len(threads) > _MAX_LISTED_THREADS:
            lines.append(f"\n…ほか {len(threads) - _MAX_LISTED_THREADS} 件")
        embed.description = "\n".join(lines)

    embed.set_footer(text="新しい順・自動更新（終了/アーカイブされたスレッドは一覧から消えます）")
    return embed


class ThreadIndexCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        boards = await db_manager.get_all_thread_index_boards()
        for board in boards:
            await self._sync_board(board)
        if boards:
            logger.info(f"thread_index: 起動時に {len(boards)} 件のボードを同期しました")

    async def _sync_board(self, board: dict) -> None:
        source_channel = self.bot.get_channel(board["channel_id"])
        if not isinstance(source_channel, discord.TextChannel):
            return
        board_channel = self.bot.get_channel(board["board_channel_id"] or board["channel_id"])
        if not isinstance(board_channel, discord.TextChannel):
            return
        try:
            message = await board_channel.fetch_message(board["message_id"])
        except (discord.NotFound, discord.Forbidden):
            await db_manager.delete_thread_index_board(board["channel_id"])
            return
        try:
            await message.edit(embed=_build_thread_index_embed(source_channel))
        except discord.HTTPException as e:
            logger.warning(f"thread_index_board 更新失敗: {e}")

    async def _sync_channel(self, channel_id: int) -> None:
        board = await db_manager.get_thread_index_board(channel_id)
        if board is None:
            return
        await self._sync_board(board)

    # ── スレッドのライフサイクルに応じて一覧を再同期 ──────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent_id is not None:
            await self._sync_channel(thread.parent_id)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if after.parent_id is not None:
            await self._sync_channel(after.parent_id)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        if thread.parent_id is not None:
            await self._sync_channel(thread.parent_id)

    # ── /setup_thread_index ────────────────────────

    @app_commands.command(
        name="setup_thread_index",
        description="指定チャンネルのアクティブなスレッド一覧を自動更新するボードを設置します（管理者用）",
    )
    @app_commands.describe(
        channel="スレッドを追跡する対象チャンネル（省略時はこのチャンネル）",
        board_channel="一覧を表示するチャンネル（省略時は追跡対象と同じチャンネル）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_thread_index(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        board_channel: discord.TextChannel | None = None,
    ):
        source = channel or interaction.channel
        if not isinstance(source, discord.TextChannel):
            await interaction.response.send_message(
                "❌ 通常のテキストチャンネルを指定してください。", ephemeral=True
            )
            return
        target = board_channel or source

        perms = target.permissions_for(interaction.guild.me)
        if not perms.send_messages or not perms.embed_links:
            await interaction.response.send_message(
                f"❌ {target.mention} にメッセージ送信/埋め込みの権限がありません。", ephemeral=True
            )
            return

        embed = _build_thread_index_embed(source)
        try:
            board_msg = await target.send(embed=embed)
            if perms.manage_messages:
                await board_msg.pin(reason="スレッド一覧ボード設置")
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ 権限不足でボードを設置できませんでした。", ephemeral=True
            )
            return

        await db_manager.save_thread_index_board(
            channel_id=source.id,
            guild_id=interaction.guild_id,
            message_id=board_msg.id,
            board_channel_id=target.id,
        )
        note = "" if target.id == source.id else f"（{source.mention} のスレッドを追跡）"
        await interaction.response.send_message(
            f"✅ {target.mention} にスレッド一覧ボードを設置しました{note}。", ephemeral=True
        )
        logger.info(
            f"setup_thread_index: guild={interaction.guild_id} source={source.id} "
            f"board_channel={target.id} message={board_msg.id}"
        )

    # ── /remove_thread_index ───────────────────────

    @app_commands.command(
        name="remove_thread_index",
        description="スレッド一覧ボードを削除します（管理者用）",
    )
    @app_commands.describe(channel="追跡を解除するチャンネル（省略時はこのチャンネル）")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_thread_index(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        source = channel or interaction.channel
        board = await db_manager.get_thread_index_board(source.id)
        if board is None:
            await interaction.response.send_message(
                f"❌ {source.mention} にはボードが設置されていません。", ephemeral=True
            )
            return

        await db_manager.delete_thread_index_board(source.id)
        board_channel = self.bot.get_channel(board["board_channel_id"] or source.id)
        try:
            msg = await board_channel.fetch_message(board["message_id"])
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, AttributeError):
            pass

        await interaction.response.send_message(
            f"✅ {source.mention} のスレッド一覧ボードを削除しました。", ephemeral=True
        )
        logger.info(f"remove_thread_index: guild={interaction.guild_id} channel={source.id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ThreadIndexCog(bot))
