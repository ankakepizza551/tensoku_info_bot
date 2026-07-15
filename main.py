import asyncio
import datetime
import logging
import os
import sqlite3
import tempfile
import discord
from discord.ext import commands
import config

# ロギング設定
os.makedirs("data", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("TensokuMatchBot")

# ロードするCogの定義
COGS = [
    "cogs.report_cog",
    "cogs.stats_cog",
    "cogs.recruit_cog",
    "cogs.letter_cog",
    "cogs.post_cog",
    "cogs.poll_cog",
    "cogs.calendar_cog",
    "cogs.dice_cog",
    "cogs.pizza_cog",
    "cogs.forum_recruit_cog",
    "cogs.forum_article_cog",
    "cogs.rating_room_cog",
    "cogs.territory_cog",
]

# インテントの設定
intents = discord.Intents.default()
intents.message_content = True  # プレフィックスコマンド用
intents.guilds = True
intents.members = True          # メンバー情報取得用
intents.guild_messages = True   # スレッド内メッセージを含むギルドメッセージ

# Botオブジェクトの作成
bot = commands.Bot(command_prefix=config.PREFIX, intents=intents)

@bot.event
async def on_ready():
    logger.info(f"Bot起動完了: {bot.user} (ID: {bot.user.id})")
    
    # ステータスメッセージの設定
    activity = discord.Game(name="東方非想天則 | /report")
    await bot.change_presence(status=discord.Status.online, activity=activity)

@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx, target: str = None):
    """スラッシュコマンドを同期します (Botのオーナーのみ実行可能)
    引数なし: グローバル同期 (反映まで最大1時間)
    guild: このサーバーのみに即時同期
    """
    if target == "guild":
        await ctx.send("このサーバー限定でスラッシュコマンドを同期中... (即時反映)")
        try:
            bot.tree.copy_global_to(guild=ctx.guild)
            synced = await bot.tree.sync(guild=ctx.guild)
            await ctx.send(f"✅ このサーバーに {len(synced)} 件のスラッシュコマンドを即時同期しました！")
            logger.info(f"ギルド同期完了: {len(synced)} 件")
        except Exception as e:
            await ctx.send(f"❌ 同期中にエラーが発生しました: {e}")
            logger.error(f"ギルド同期失敗: {e}")
    else:
        await ctx.send("グローバル（全サーバー）にスラッシュコマンドを同期中... (反映まで時間がかかる場合があります)")
        try:
            synced = await bot.tree.sync()
            await ctx.send(f"✅ グローバルで {len(synced)} 件のスラッシュコマンドを同期しました！")
            logger.info(f"グローバル同期完了: {len(synced)} 件")
        except Exception as e:
            await ctx.send(f"❌ 同期中にエラーが発生しました: {e}")
            logger.error(f"グローバル同期失敗: {e}")

@bot.command(name="db_backup")
@commands.is_owner()
async def db_backup(ctx):
    """データベースのバックアップファイルをこのチャンネルに送信します (Botのオーナー専用)"""
    def make_backup() -> str:
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"tensoku_stats_backup_{datetime.datetime.now():%Y%m%d_%H%M%S}.db",
        )
        src = sqlite3.connect(config.DB_PATH)
        try:
            dst = sqlite3.connect(tmp_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return tmp_path

    await ctx.send("バックアップを作成中...")
    tmp_path = None
    try:
        tmp_path = await asyncio.to_thread(make_backup)
        await ctx.send(file=discord.File(tmp_path, filename="tensoku_stats_backup.db"))
        logger.info(f"db_backup: by user={ctx.author.id}")
    except Exception as e:
        await ctx.send(f"❌ バックアップ中にエラーが発生しました: {e}")
        logger.error(f"db_backup失敗: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

@bot.command(name="bot_status")
async def bot_status(ctx):
    """Botの現在のステータスを表示"""
    embed = discord.Embed(title="東方非想天則 戦績管理Bot ステータス", color=discord.Color.from_rgb(52, 152, 219))
    embed.add_field(name="接続中のサーバー数", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="応答速度 (Latency)", value=f"{round(bot.latency * 1000)}ms", inline=True)
    embed.add_field(name="稼働中のCogs", value="\n".join(f"✅ {cog.replace('cogs.', '')}" for cog in COGS), inline=False)
    await ctx.send(embed=embed)

async def main():
    async with bot:
        # データベースの初期化
        from database.db_manager import init_db
        await init_db()
        logger.info("データベース初期化完了。")
        
        # Cogsのロード
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                logger.info(f"Cogロード成功: {cog}")
            except Exception as e:
                logger.error(f"Cogロード失敗 {cog}: {e}")
                
        # Botの起動
        logger.info("Bot接続開始...")
        await bot.start(config.TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
