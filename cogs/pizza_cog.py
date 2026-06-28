import random
import discord
from discord import app_commands
from discord.ext import commands
from database import db_manager

STAR_MAX = 5

def rating_stars(rating: int) -> str:
    return "⭐" * rating + "☆" * (STAR_MAX - rating)


class PizzaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="pizza_add", description="ピザをリストに登録します")
    @app_commands.describe(
        name="ピザの名前",
        description="ピザの説明・感想（任意）",
        rating="おすすめ度 1〜5（デフォルト: 3）"
    )
    @app_commands.choices(rating=[
        app_commands.Choice(name="⭐ 1", value=1),
        app_commands.Choice(name="⭐⭐ 2", value=2),
        app_commands.Choice(name="⭐⭐⭐ 3", value=3),
        app_commands.Choice(name="⭐⭐⭐⭐ 4", value=4),
        app_commands.Choice(name="⭐⭐⭐⭐⭐ 5", value=5),
    ])
    async def pizza_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str = None,
        rating: int = 3,
    ):
        await interaction.response.defer()

        pizza_id = await db_manager.add_pizza(
            name=name,
            description=description or "",
            rating=rating,
            added_by=interaction.user.id,
        )

        embed = discord.Embed(
            title="🍕 ピザを登録しました！",
            color=discord.Color.from_rgb(231, 76, 60),
        )
        embed.add_field(name="名前", value=name, inline=True)
        embed.add_field(name="おすすめ度", value=rating_stars(rating), inline=True)
        if description:
            embed.add_field(name="説明", value=description, inline=False)
        embed.set_footer(text=f"ID: {pizza_id} | 登録者: {interaction.user.display_name}")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pizza_random", description="登録済みのピザをランダムに1つ紹介します")
    async def pizza_random(self, interaction: discord.Interaction):
        await interaction.response.defer()

        pizza = await db_manager.get_random_pizza()

        if pizza is None:
            await interaction.followup.send(
                "❌ まだピザが登録されていません。`/pizza_add` で登録してみましょう！",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"🍕 今日のおすすめピザ: **{pizza['name']}**",
            color=discord.Color.from_rgb(230, 126, 34),
        )
        embed.add_field(name="おすすめ度", value=rating_stars(pizza["rating"]), inline=True)
        if pizza.get("description"):
            embed.add_field(name="コメント", value=pizza["description"], inline=False)

        # 登録者名を取得
        member = interaction.guild.get_member(pizza["added_by"]) if interaction.guild else None
        registrant = member.display_name if member else f"ID:{pizza['added_by']}"
        embed.set_footer(text=f"登録者: {registrant} | Pizza ID: {pizza['pizza_id']}")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pizza_list", description="登録済みのピザ一覧を表示します")
    async def pizza_list(self, interaction: discord.Interaction):
        await interaction.response.defer()

        pizzas = await db_manager.get_all_pizzas()

        if not pizzas:
            await interaction.followup.send(
                "❌ まだピザが登録されていません。`/pizza_add` で登録してみましょう！",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🍕 ピザリスト",
            description=f"合計 {len(pizzas)} 種類のピザが登録されています",
            color=discord.Color.from_rgb(231, 76, 60),
        )

        for pizza in pizzas[:20]:
            val = rating_stars(pizza["rating"])
            if pizza.get("description"):
                val += f"\n{pizza['description']}"
            embed.add_field(
                name=f"[ID:{pizza['pizza_id']}] {pizza['name']}",
                value=val,
                inline=False,
            )

        if len(pizzas) > 20:
            embed.set_footer(text=f"※ 先頭20件のみ表示しています（全{len(pizzas)}件）")

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="pizza_delete", description="ピザをリストから削除します（登録者または管理者のみ）")
    @app_commands.describe(pizza_id="削除するピザのID（/pizza_list で確認）")
    async def pizza_delete(self, interaction: discord.Interaction, pizza_id: int):
        await interaction.response.defer(ephemeral=True)

        pizzas = await db_manager.get_all_pizzas()
        target = next((p for p in pizzas if p["pizza_id"] == pizza_id), None)

        if target is None:
            await interaction.followup.send(f"❌ ID `{pizza_id}` のピザが見つかりません。", ephemeral=True)
            return

        is_admin = interaction.user.guild_permissions.manage_guild if interaction.guild else False
        if target["added_by"] != interaction.user.id and not is_admin:
            await interaction.followup.send("❌ 削除できるのは登録者またはサーバー管理者のみです。", ephemeral=True)
            return

        await db_manager.delete_pizza(pizza_id)
        await interaction.followup.send(
            f"🗑️ **{target['name']}**（ID: {pizza_id}）をリストから削除しました。",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(PizzaCog(bot))
