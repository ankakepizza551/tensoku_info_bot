import random
import re
import discord
from discord import app_commands
from discord.ext import commands


class DiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roll", description="ダイスを振ります（例: 2d6、1d100）")
    @app_commands.describe(dice="XdY形式で入力してください（例: 2d6）")
    async def roll(self, interaction: discord.Interaction, dice: str):
        match = re.fullmatch(r"(\d+)[dD](\d+)", dice.strip())
        if not match:
            await interaction.response.send_message(
                "❌ 形式が正しくありません。`2d6` や `1d100` のように入力してください。",
                ephemeral=True,
            )
            return

        count = int(match.group(1))
        sides = int(match.group(2))

        if count < 1 or count > 100:
            await interaction.response.send_message(
                "❌ ダイスの個数は1〜100の範囲で入力してください。",
                ephemeral=True,
            )
            return
        if sides < 2 or sides > 10000:
            await interaction.response.send_message(
                "❌ ダイスの面数は2〜10000の範囲で入力してください。",
                ephemeral=True,
            )
            return

        results = [random.randint(1, sides) for _ in range(count)]
        total = sum(results)

        rolls_str = ", ".join(str(r) for r in results)
        embed = discord.Embed(
            title=f"🎲 {count}d{sides}",
            color=discord.Color.from_rgb(155, 89, 182),
        )
        embed.add_field(name="出目", value=f"`[{rolls_str}]`", inline=False)
        if count > 1:
            embed.add_field(name="合計", value=f"**{total}**", inline=False)
        embed.set_footer(text=f"rolled by {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(DiceCog(bot))
