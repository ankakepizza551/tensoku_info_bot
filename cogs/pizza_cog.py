import logging
import discord
from discord import app_commands
from discord.ext import commands
from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

STAR_MAX = 5


def rating_stars(rating: int) -> str:
    return "⭐" * rating + "☆" * (STAR_MAX - rating)


async def do_pizza_add(interaction: discord.Interaction, name: str, description: str, rating: int):
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


async def do_pizza_random(interaction: discord.Interaction):
    pizza = await db_manager.get_random_pizza()

    if pizza is None:
        await interaction.followup.send(
            "❌ まだピザが登録されていません。「メニュー追加」から登録してみましょう！",
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

    member = interaction.guild.get_member(pizza["added_by"]) if interaction.guild else None
    registrant = member.display_name if member else f"ID:{pizza['added_by']}"
    embed.set_footer(text=f"登録者: {registrant} | Pizza ID: {pizza['pizza_id']}")

    await interaction.followup.send(embed=embed)


async def do_pizza_list(interaction: discord.Interaction):
    pizzas = await db_manager.get_all_pizzas()

    if not pizzas:
        await interaction.followup.send(
            "❌ まだピザが登録されていません。「メニュー追加」から登録してみましょう！",
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


async def do_pizza_delete(interaction: discord.Interaction, pizza_id: int):
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


class PizzaAddModal(discord.ui.Modal, title="🍕 ピザを登録"):
    name = discord.ui.TextInput(
        label="ピザの名前",
        max_length=100,
        required=True,
    )
    description = discord.ui.TextInput(
        label="説明・感想（任意）",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )
    rating = discord.ui.TextInput(
        label="おすすめ度 1〜5",
        default="3",
        max_length=1,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            rating_value = int(self.rating.value)
            if not 1 <= rating_value <= 5:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "❌ おすすめ度は1〜5の数字で入力してください。",
                ephemeral=True,
            )
            return

        await interaction.response.defer()
        await do_pizza_add(interaction, self.name.value, self.description.value, rating_value)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"PizzaAddModal エラー: {error}")
        await interaction.response.send_message(
            "❌ 登録中にエラーが発生しました。しばらくしてから再試行してください。",
            ephemeral=True,
        )


class PizzaDeleteModal(discord.ui.Modal, title="🗑️ ピザを削除"):
    pizza_id = discord.ui.TextInput(
        label="削除するピザのID（「メニューを見る」で確認）",
        max_length=10,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            pizza_id_value = int(self.pizza_id.value)
        except ValueError:
            await interaction.response.send_message(
                "❌ IDは数字で入力してください。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await do_pizza_delete(interaction, pizza_id_value)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"PizzaDeleteModal エラー: {error}")
        await interaction.response.send_message(
            "❌ 削除中にエラーが発生しました。しばらくしてから再試行してください。",
            ephemeral=True,
        )


class PizzaPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="メニュー追加", style=discord.ButtonStyle.success, custom_id="pizza_panel_add", emoji="🍕")
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PizzaAddModal())

    @discord.ui.button(label="メニュー削除", style=discord.ButtonStyle.danger, custom_id="pizza_panel_delete", emoji="🗑️")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PizzaDeleteModal())

    @discord.ui.button(label="メニューを見る", style=discord.ButtonStyle.primary, custom_id="pizza_panel_list", emoji="📋")
    async def list_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await do_pizza_list(interaction)

    @discord.ui.button(label="ピザを焼く", style=discord.ButtonStyle.secondary, custom_id="pizza_panel_random", emoji="🔥")
    async def random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await do_pizza_random(interaction)


class PizzaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PizzaPanelView())

    @app_commands.command(name="pizza_panel", description="ピザメニューのボタンパネルをこのチャンネルに設置します（管理者用）")
    @app_commands.default_permissions(manage_guild=True)
    async def pizza_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🍕 ピザメニュー",
            description=(
                "下のボタンからピザメニューを操作できます。\n"
                "🍕 メニュー追加 / 🗑️ メニュー削除 / 📋 メニューを見る / 🔥 ピザを焼く"
            ),
            color=discord.Color.from_rgb(231, 76, 60),
        )
        await interaction.response.send_message(embed=embed, view=PizzaPanelView())
        logger.info(f"pizza_panel: channel={interaction.channel_id} by user={interaction.user.id}")

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
        await do_pizza_add(interaction, name, description or "", rating)

    @app_commands.command(name="pizza_random", description="登録済みのピザをランダムに1つ紹介します")
    async def pizza_random(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await do_pizza_random(interaction)

    @app_commands.command(name="pizza_list", description="登録済みのピザ一覧を表示します")
    async def pizza_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await do_pizza_list(interaction)

    @app_commands.command(name="pizza_delete", description="ピザをリストから削除します（登録者または管理者のみ）")
    @app_commands.describe(pizza_id="削除するピザのID（/pizza_list で確認）")
    async def pizza_delete(self, interaction: discord.Interaction, pizza_id: int):
        await interaction.response.defer(ephemeral=True)
        await do_pizza_delete(interaction, pizza_id)


async def setup(bot):
    await bot.add_cog(PizzaCog(bot))
