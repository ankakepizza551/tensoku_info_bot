import logging
import urllib.parse

import discord
from discord import app_commands
from discord.ext import commands

import config

logger = logging.getLogger("TensokuMatchBot")

PROMOTE_TWEET_TEXT = (
    "東方非想天則の対戦サーバー、参加者募集中！⚔️\n"
    "#天則コソ練広場 #th123"
)

# Discordのボタン(link component)のurlは512文字までという制約があるため、
# 日本語や絵文字を含む文章をURLエンコードした結果が超過しないよう自動で切り詰める。
_DISCORD_BUTTON_URL_MAX_LENGTH = 512


def _build_intent_url(invite_url: str) -> str:
    """X(Twitter)投稿画面をあらかじめ入力済みの状態で開くURLを組み立てる。"""
    text = PROMOTE_TWEET_TEXT
    while text:
        params = {"text": text, "url": invite_url}
        url = f"https://twitter.com/intent/tweet?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
        if len(url) <= _DISCORD_BUTTON_URL_MAX_LENGTH:
            return url
        text = text[:-1]
    # 招待リンク自体が長すぎてtextなしでも収まらない場合のフォールバック
    return f"https://twitter.com/intent/tweet?{urllib.parse.urlencode({'url': invite_url}, quote_via=urllib.parse.quote)}"


class PromoteCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="promote",
        description="サーバーをX(Twitter)で宣伝できるボタンを表示します",
    )
    async def promote(self, interaction: discord.Interaction):
        try:
            invite_url = config.SERVER_INVITE_URL
            if not invite_url:
                await interaction.response.send_message(
                    "❌ サーバーの招待リンクが設定されていません。\n"
                    "Botの管理者に `.env` の `SERVER_INVITE_URL` 設定を依頼してください。",
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="📣 サーバーを宣伝しよう！",
                description=(
                    "下のボタンを押すと、宣伝用の文章と招待リンクが入力された状態で\n"
                    "X（旧Twitter）の投稿画面が開きます。内容を確認してそのままポストできます。"
                ),
                color=discord.Color.from_rgb(29, 161, 242),
            )
            view = discord.ui.View()
            view.add_item(
                discord.ui.Button(
                    label="🐦 Xで宣伝する",
                    style=discord.ButtonStyle.link,
                    url=_build_intent_url(invite_url),
                )
            )
            await interaction.response.send_message(embed=embed, view=view)
            logger.info(f"/promote: user={interaction.user.id}")
        except Exception as e:
            logger.error(f"/promote エラー: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ コマンドの実行中にエラーが発生しました。", ephemeral=True
                )


async def setup(bot: commands.Bot):
    await bot.add_cog(PromoteCog(bot))
