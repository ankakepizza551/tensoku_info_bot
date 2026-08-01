import discord
from discord import app_commands
from discord.ext import commands
from database import db_manager
from cogs.report_cog import CHARACTERS

_DISTRIBUTION_COLOR = discord.Color.from_rgb(52, 152, 219)
_REGISTER_COLOR = discord.Color.from_rgb(46, 204, 113)


def _build_distribution_embed(records: list) -> discord.Embed:
    """登録済みデータからキャラ分布Embedを作成する"""
    by_character: dict[str, list[str]] = {}
    for r in records:
        by_character.setdefault(r["character"], []).append(r["username"])

    total = len(records)
    sorted_chars = sorted(by_character.items(), key=lambda x: len(x[1]), reverse=True)

    bar_length = 10
    distribution_text = ""
    for char_name, users in sorted_chars:
        count = len(users)
        ratio = count / total
        filled = round(bar_length * ratio)
        gauge = "🟩" * filled + "⬜" * (bar_length - filled)
        distribution_text += f"**{char_name}**: `{count}`人 / 全体`{total}`人 ({round(ratio * 100, 1)}%) {gauge}\n"

    embed = discord.Embed(
        title="🎮 メインキャラクター分布",
        description=f"登録人数: `{total}`人\nキャラクターを選ぶと使用者一覧を確認できます。",
        color=_DISTRIBUTION_COLOR
    )
    embed.add_field(name="分布", value=distribution_text, inline=False)
    return embed


class MainCharSelect(discord.ui.Select):
    """メインキャラクター登録用のドロップダウン"""

    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        options = [discord.SelectOption(label=char) for char in CHARACTERS]
        super().__init__(placeholder="メインキャラクターを選択してください", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ このメニューはコマンドを実行した本人のみ操作できます。", ephemeral=True)
            return

        character = self.values[0]
        previous = await db_manager.get_main_character(self.owner_id)
        await db_manager.set_main_character(
            self.owner_id, interaction.user.display_name, character
        )

        if previous and previous["character"] != character:
            description = f"メインキャラクターを **{previous['character']}** から **{character}** に変更しました！"
        else:
            description = f"メインキャラクターを **{character}** に登録しました！"

        embed = discord.Embed(
            title="🎮 メインキャラクター登録完了",
            description=description,
            color=_REGISTER_COLOR
        )
        self.view.stop()
        await interaction.response.edit_message(embed=embed, view=None)


class MainCharView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=60)
        self.add_item(MainCharSelect(owner_id))


class MainCharListSelect(discord.ui.Select):
    """キャラクター別の使用者一覧を確認するドロップダウン"""

    def __init__(self, by_character: dict[str, list[str]]):
        self.by_character = by_character
        sorted_chars = sorted(by_character.items(), key=lambda x: len(x[1]), reverse=True)
        options = [
            discord.SelectOption(label=char_name, description=f"{len(users)}人が使用中")
            for char_name, users in sorted_chars
        ]
        super().__init__(placeholder="使用者一覧を見たいキャラクターを選択...", options=options)

    async def callback(self, interaction: discord.Interaction):
        character = self.values[0]
        users = self.by_character[character]
        embed = discord.Embed(
            title=f"🎮 {character} の使用者一覧",
            description=f"`{len(users)}`人が登録しています。\n\n{chr(10).join(f'・{u}' for u in users)}",
            color=_DISTRIBUTION_COLOR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MainCharListView(discord.ui.View):
    def __init__(self, by_character: dict[str, list[str]]):
        super().__init__(timeout=180)
        self.add_item(MainCharListSelect(by_character))


async def _build_list_response(records: list) -> tuple[discord.Embed, discord.ui.View | None]:
    """分布Embedと一覧選択Viewをまとめて作成する"""
    if not records:
        embed = discord.Embed(
            title="🎮 メインキャラクター分布",
            description="まだ誰も登録していません。`/main_char` で登録してみましょう！",
            color=_DISTRIBUTION_COLOR
        )
        return embed, None

    by_character: dict[str, list[str]] = {}
    for r in records:
        by_character.setdefault(r["character"], []).append(r["username"])

    embed = _build_distribution_embed(records)
    return embed, MainCharListView(by_character)


# ─────────────────────────────────────────────
#  常設パネル（ボタン式）
# ─────────────────────────────────────────────

class MainCharPanelRegisterButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="メインキャラを登録・変更",
            emoji="🎮",
            custom_id="main_char_panel_register",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "登録するメインキャラクターを選んでください。",
            view=MainCharView(interaction.user.id),
            ephemeral=True,
        )


class MainCharPanelListButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="分布を見る",
            emoji="📊",
            custom_id="main_char_panel_list",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        records = await db_manager.get_all_main_characters()
        embed, view = await _build_list_response(records)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class MainCharPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MainCharPanelRegisterButton())
        self.add_item(MainCharPanelListButton())


class MainCharCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Bot起動・再接続時に常設パネルのViewを再登録する"""
        self.bot.add_view(MainCharPanelView())

    @app_commands.command(name="main_char", description="あなたの普段のメインキャラクターを登録・変更します")
    async def main_char(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "登録するメインキャラクターを選んでください。",
            view=MainCharView(interaction.user.id),
            ephemeral=True
        )

    @app_commands.command(name="main_char_list", description="サーバー内のメインキャラクター分布と一覧を表示します")
    async def main_char_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        records = await db_manager.get_all_main_characters()
        embed, view = await _build_list_response(records)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(
        name="main_char_panel",
        description="メインキャラ登録・分布表示を行える常設パネルを設置します（サーバー管理者のみ）",
    )
    @app_commands.describe(channel="設置するチャンネル（省略時は現在のチャンネル）")
    async def main_char_panel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("❌ このコマンドはサーバー管理者のみ使用できます。", ephemeral=True)
            return

        target_channel = channel or interaction.channel
        embed = discord.Embed(
            title="🎮 メインキャラクター登録パネル",
            description=(
                "下のボタンから、普段のメインキャラクターの登録・変更や、\n"
                "サーバー内のメインキャラクター分布の確認ができます。"
            ),
            color=_DISTRIBUTION_COLOR,
        )
        await target_channel.send(embed=embed, view=MainCharPanelView())
        await interaction.response.send_message(
            f"✅ メインキャラ登録パネルを {target_channel.mention} に設置しました。",
            ephemeral=True,
        )

async def setup(bot):
    await bot.add_cog(MainCharCog(bot))
