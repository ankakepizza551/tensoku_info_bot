import asyncio
import datetime
import logging
import os

import discord
from discord.ext import commands, tasks

import config
from database.backup import FILE_PREFIX, JST, create_backup_file

logger = logging.getLogger("TensokuMatchBot.backup")

BACKUP_TIME = datetime.time(hour=4, tzinfo=JST)  # 利用者の少ない時間帯に毎日取る
# 起動時、最後のバックアップがこれより古ければすぐに取る（4:00 に止まっていた日の分を補う）
MAX_AGE = datetime.timedelta(hours=24)


class BackupCog(commands.Cog):
    """データベースを毎日、管理者用チャンネルに自動でバックアップする"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._checked_on_ready = False
        self._lock = asyncio.Lock()
        if config.DB_BACKUP_CHANNEL_ID:
            self.daily_backup.start()
        else:
            logger.info("DB_BACKUP_CHANNEL_ID が未設定のため、自動バックアップは無効です")

    def cog_unload(self):
        self.daily_backup.cancel()

    def _channel(self) -> discord.TextChannel | None:
        channel = self.bot.get_channel(config.DB_BACKUP_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            logger.error(
                f"バックアップ先のチャンネル (DB_BACKUP_CHANNEL_ID={config.DB_BACKUP_CHANNEL_ID}) "
                "が見つからないか、テキストチャンネルではありません"
            )
            return None
        return channel

    @tasks.loop(time=BACKUP_TIME)
    async def daily_backup(self):
        await self.run_backup("定期バックアップ")

    @daily_backup.before_loop
    async def _before_daily_backup(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        # on_readyは再接続でも呼ばれるので初回のみ
        if self._checked_on_ready or not config.DB_BACKUP_CHANNEL_ID:
            return
        self._checked_on_ready = True
        channel = self._channel()
        if channel is None:
            return
        last = await self._last_backup_time(channel)
        if last is None or discord.utils.utcnow() - last > MAX_AGE:
            await self.run_backup("起動時のバックアップ（前回から24時間以上空いたため）")

    async def _last_backup_time(self, channel: discord.TextChannel) -> datetime.datetime | None:
        try:
            async for message in channel.history(limit=50):
                if message.author.id == self.bot.user.id and any(
                    a.filename.startswith(FILE_PREFIX) for a in message.attachments
                ):
                    return message.created_at
        except discord.HTTPException as e:
            logger.warning(f"バックアップ先チャンネルの履歴を読めませんでした: {e}")
        return None

    async def run_backup(self, reason: str) -> bool:
        channel = self._channel()
        if channel is None:
            return False

        # データベースにはメンバーの戦績などが入っているので、誰でも見られるチャンネルには送らない
        if channel.permissions_for(channel.guild.default_role).view_channel:
            logger.error(f"#{channel.name} は @everyone が見られるため、バックアップを送信しませんでした")
            try:
                await channel.send(
                    "⚠️ このチャンネルは @everyone が見られるため、データベースのバックアップを送信しませんでした。"
                    "管理者だけが見られるチャンネルにしてください。"
                )
            except discord.HTTPException:
                pass
            return False

        async with self._lock:
            path = None
            try:
                path = await asyncio.to_thread(create_backup_file, True)
                size = os.path.getsize(path)
                if size > channel.guild.filesize_limit:
                    logger.error(f"バックアップ ({size} bytes) がアップロード上限を超えています")
                    await channel.send(
                        f"❌ バックアップ（{size / 1024 / 1024:.1f} MB）がこのサーバーのアップロード上限"
                        f"（{channel.guild.filesize_limit / 1024 / 1024:.0f} MB）を超えたため、送信できませんでした。"
                    )
                    return False
                await channel.send(
                    f"🗄️ {reason}\n"
                    f"{datetime.datetime.now(JST):%Y-%m-%d %H:%M} JST / {size / 1024:.0f} KB（gzip 圧縮）",
                    file=discord.File(path),
                )
                logger.info(f"自動バックアップ送信: {reason} ({size} bytes)")
                return True
            except Exception as e:
                logger.error(f"自動バックアップ失敗: {type(e).__name__}: {e}")
                try:
                    await channel.send(f"❌ バックアップ中にエラーが発生しました: {type(e).__name__}: {e}")
                except discord.HTTPException:
                    pass
                return False
            finally:
                if path and os.path.exists(path):
                    os.remove(path)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
