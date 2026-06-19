import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("TensokuMatchBot")

# ─────────────────────────────────────────────
#  /post  シンプル投稿モーダル
# ─────────────────────────────────────────────

class PostModal(discord.ui.Modal, title="📝 投稿を作成"):
    """タイトル・本文・画像URLをまとめて入力して1発投稿"""

    post_title = discord.ui.TextInput(
        label="タイトル（省略可）",
        placeholder="投稿のタイトルを入力...",
        required=False,
        max_length=256,
    )
    post_body = discord.ui.TextInput(
        label="本文",
        style=discord.TextStyle.paragraph,
        placeholder=(
            "内容を入力...\n"
            "書式: **太字** *斜体* __下線__ ~~打消し~~ `コード`\n"
            "見出し: # H1 / ## H2 / ### H3 / -# 小テキスト\n"
            "引用: > テキスト   リスト: - 項目 / 1. 項目\n"
            "末尾に画像URLを貼ると自動で埋め込まれます"
        ),
        required=True,
        max_length=4000,
    )
    image_url = discord.ui.TextInput(
        label="画像URL（省略可）",
        placeholder="https://example.com/image.png",
        required=False,
        max_length=500,
    )

    def __init__(self, color: discord.Color):
        super().__init__()
        self.color = color

    async def on_submit(self, interaction: discord.Interaction):
        body = self.post_body.value
        image = self.image_url.value.strip() if self.image_url.value else None

        # 本文末尾の画像URLを自動検出
        if not image:
            url_pattern = r"(https?://\S+\.(?:png|jpg|jpeg|gif|webp))\s*$"
            m = re.search(url_pattern, body, re.IGNORECASE | re.MULTILINE)
            if m:
                image = m.group(1)
                body = body[: m.start()].rstrip()

        embed = discord.Embed(description=body, color=self.color)
        if self.post_title.value:
            embed.title = self.post_title.value
        if image:
            embed.set_image(url=image)
        embed.set_footer(
            text=f"投稿者: {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.send_message(embed=embed)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"PostModal エラー: {error}")
        await interaction.response.send_message(
            "❌ 投稿中にエラーが発生しました。", ephemeral=True
        )


# ─────────────────────────────────────────────
#  /embed_builder  インタラクティブ Embed ビルダー
# ─────────────────────────────────────────────

class EmbedBuilderView(discord.ui.View):
    """ボタン操作でステップ式に Embed を組み立てるビュー"""

    def __init__(self, author: discord.Member):
        super().__init__(timeout=600)
        self.author = author
        self.data: dict = {
            "title": "",
            "description": "",
            "color": discord.Color.from_rgb(52, 152, 219),
            "image": "",
            "thumbnail": "",
            "footer": "",
            "fields": [],
        }

    # ── ユーティリティ ──────────────────────────

    def build_embed(self, is_preview: bool = False) -> discord.Embed:
        embed = discord.Embed(
            title=self.data["title"] or ("(タイトルなし)" if is_preview else None),
            description=self.data["description"] or ("(本文なし)" if is_preview else None),
            color=self.data["color"],
        )
        for f in self.data["fields"]:
            embed.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
        if self.data["image"]:
            embed.set_image(url=self.data["image"])
        if self.data["thumbnail"]:
            embed.set_thumbnail(url=self.data["thumbnail"])
        footer = self.data["footer"]
        if is_preview:
            footer = f"[下書き] {footer}" if footer else "[下書き]"
        if footer:
            embed.set_footer(text=footer)
        return embed

    async def _refresh(self, interaction: discord.Interaction):
        """プレビューメッセージを更新してからエフェメラル通知を返す"""
        preview = self.build_embed(is_preview=True)
        try:
            await interaction.message.edit(embed=preview, view=self)
            await interaction.response.send_message("✅ プレビューを更新しました！", ephemeral=True)
        except discord.errors.NotFound:
            await interaction.response.defer()

    def _guard(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    # ── ボタン ──────────────────────────────────

    @discord.ui.button(label="📝 タイトル・本文", style=discord.ButtonStyle.primary, row=0)
    async def btn_content(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(ContentModal(self))

    @discord.ui.button(label="🖼️ 画像", style=discord.ButtonStyle.secondary, row=0)
    async def btn_image(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(ImageModal(self))

    @discord.ui.button(label="🎨 カラー", style=discord.ButtonStyle.secondary, row=0)
    async def btn_color(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        view = ColorPickerView(self, interaction.message)
        await interaction.response.send_message("🎨 カラーを選択してください：", view=view, ephemeral=True)

    @discord.ui.button(label="➕ フィールド追加", style=discord.ButtonStyle.secondary, row=1)
    async def btn_field(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        if len(self.data["fields"]) >= 10:
            await interaction.response.send_message("❌ フィールドは最大10個までです。", ephemeral=True)
            return
        await interaction.response.send_modal(FieldModal(self))

    @discord.ui.button(label="🗑️ フィールド削除", style=discord.ButtonStyle.secondary, row=1)
    async def btn_remove_field(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        if not self.data["fields"]:
            await interaction.response.send_message("❌ 削除できるフィールドがありません。", ephemeral=True)
            return
        self.data["fields"].pop()
        await self._refresh(interaction)

    @discord.ui.button(label="📤 投稿する", style=discord.ButtonStyle.success, row=2)
    async def btn_post(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        final = self.build_embed(is_preview=False)
        # フッターに投稿者名を付ける
        footer_text = f"投稿者: {interaction.user.display_name}"
        if self.data["footer"]:
            footer_text = f"{self.data['footer']}　|　投稿者: {interaction.user.display_name}"
        final.set_footer(
            text=footer_text,
            icon_url=interaction.user.display_avatar.url,
        )
        try:
            await interaction.message.delete()
        except discord.errors.NotFound:
            pass
        await interaction.channel.send(embed=final)
        await interaction.response.send_message("✅ 投稿しました！", ephemeral=True)
        self.stop()

    @discord.ui.button(label="❌ キャンセル", style=discord.ButtonStyle.danger, row=2)
    async def btn_cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        try:
            await interaction.message.delete()
        except discord.errors.NotFound:
            pass
        await interaction.response.send_message("❌ 投稿をキャンセルしました。", ephemeral=True)
        self.stop()


# ── モーダル群 ─────────────────────────────────

class ContentModal(discord.ui.Modal, title="📝 タイトル・本文の編集"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        # 既存の値を初期値として反映
        self.title_input = discord.ui.TextInput(
            label="タイトル（省略可）",
            placeholder="タイトルを入力...",
            default=builder.data["title"],
            required=False,
            max_length=256,
        )
        self.body_input = discord.ui.TextInput(
            label="本文",
            style=discord.TextStyle.paragraph,
            placeholder="**太字** *斜体* __下線__ `コード` > 引用 # 見出し",
            default=builder.data["description"],
            required=False,
            max_length=4000,
        )
        self.footer_input = discord.ui.TextInput(
            label="フッター（省略可）",
            placeholder="フッターテキスト（投稿者名は自動付与）",
            default=builder.data["footer"],
            required=False,
            max_length=200,
        )
        self.add_item(self.title_input)
        self.add_item(self.body_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.data["title"] = self.title_input.value
        self.builder.data["description"] = self.body_input.value
        self.builder.data["footer"] = self.footer_input.value
        await self.builder._refresh(interaction)


class ImageModal(discord.ui.Modal, title="🖼️ 画像の設定"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.image_input = discord.ui.TextInput(
            label="メイン画像URL（大きく表示）",
            placeholder="https://example.com/image.png",
            default=builder.data["image"],
            required=False,
            max_length=500,
        )
        self.thumb_input = discord.ui.TextInput(
            label="サムネイルURL（右上に小さく）",
            placeholder="https://example.com/thumb.png",
            default=builder.data["thumbnail"],
            required=False,
            max_length=500,
        )
        self.add_item(self.image_input)
        self.add_item(self.thumb_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.data["image"] = self.image_input.value.strip()
        self.builder.data["thumbnail"] = self.thumb_input.value.strip()
        await self.builder._refresh(interaction)


class FieldModal(discord.ui.Modal, title="➕ フィールドの追加"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.f_name = discord.ui.TextInput(
            label="フィールド名",
            placeholder="フィールドのタイトル",
            max_length=256,
        )
        self.f_value = discord.ui.TextInput(
            label="フィールドの内容",
            style=discord.TextStyle.paragraph,
            placeholder="内容を入力...",
            max_length=1024,
        )
        self.f_inline = discord.ui.TextInput(
            label="横並び表示？（yes / no）",
            placeholder="yes または no（デフォルト: no）",
            required=False,
            max_length=3,
        )
        self.add_item(self.f_name)
        self.add_item(self.f_value)
        self.add_item(self.f_inline)

    async def on_submit(self, interaction: discord.Interaction):
        inline = self.f_inline.value.lower().strip() in ("yes", "y", "true", "はい")
        self.builder.data["fields"].append({
            "name": self.f_name.value,
            "value": self.f_value.value,
            "inline": inline,
        })
        await self.builder._refresh(interaction)


# ── カラーピッカー ─────────────────────────────

_COLOR_OPTIONS = [
    discord.SelectOption(label="🔵 ブルー",   value="52,152,219",  description="落ち着いた青"),
    discord.SelectOption(label="🟢 グリーン", value="46,204,113",  description="さわやかな緑"),
    discord.SelectOption(label="🔴 レッド",   value="231,76,60",   description="情熱的な赤"),
    discord.SelectOption(label="🟣 パープル", value="149,117,205", description="上品な紫"),
    discord.SelectOption(label="🟡 イエロー", value="241,196,15",  description="明るい黄色"),
    discord.SelectOption(label="🟠 オレンジ", value="230,126,34",  description="活気あるオレンジ"),
    discord.SelectOption(label="⚫ グレー",   value="127,140,141", description="シンプルなグレー"),
    discord.SelectOption(label="🩷 ピンク",   value="255,105,180", description="かわいいピンク"),
    discord.SelectOption(label="🩵 シアン",   value="26,188,156",  description="爽やかな水色"),
    discord.SelectOption(label="⚪ ホワイト", value="236,240,241", description="クリーンなホワイト"),
]


class ColorPickerView(discord.ui.View):
    def __init__(self, builder: EmbedBuilderView, preview_msg: discord.Message):
        super().__init__(timeout=60)
        self.add_item(ColorSelect(builder, preview_msg))


class ColorSelect(discord.ui.Select):
    def __init__(self, builder: EmbedBuilderView, preview_msg: discord.Message):
        super().__init__(placeholder="カラーを選んでください...", options=_COLOR_OPTIONS)
        self.builder = builder
        self.preview_msg = preview_msg

    async def callback(self, interaction: discord.Interaction):
        r, g, b = map(int, self.values[0].split(","))
        self.builder.data["color"] = discord.Color.from_rgb(r, g, b)
        # プレビューメッセージのカラーも即時反映
        preview = self.builder.build_embed(is_preview=True)
        try:
            await self.preview_msg.edit(embed=preview, view=self.builder)
        except discord.errors.NotFound:
            pass
        await interaction.response.send_message("✅ カラーを変更しました！", ephemeral=True)
        self.view.stop()


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /post ───────────────────────────────────

    @app_commands.command(name="post", description="モーダルを開いて記事風の投稿を作成します")
    @app_commands.describe(color="投稿の色テーマ（省略可、デフォルト: ブルー）")
    @app_commands.choices(color=[
        app_commands.Choice(name="🔵 ブルー",   value="52,152,219"),
        app_commands.Choice(name="🟢 グリーン", value="46,204,113"),
        app_commands.Choice(name="🔴 レッド",   value="231,76,60"),
        app_commands.Choice(name="🟣 パープル", value="149,117,205"),
        app_commands.Choice(name="🟡 イエロー", value="241,196,15"),
        app_commands.Choice(name="🟠 オレンジ", value="230,126,34"),
        app_commands.Choice(name="🩷 ピンク",   value="255,105,180"),
        app_commands.Choice(name="🩵 シアン",   value="26,188,156"),
        app_commands.Choice(name="⚪ ホワイト", value="236,240,241"),
    ])
    async def post(self, interaction: discord.Interaction, color: str = "52,152,219"):
        r, g, b = map(int, color.split(","))
        await interaction.response.send_modal(PostModal(color=discord.Color.from_rgb(r, g, b)))

    # ── /embed_builder ──────────────────────────

    @app_commands.command(
        name="embed_builder",
        description="ボタン操作でステップ式に Embed 投稿を組み立てるビルダーを開きます",
    )
    async def embed_builder(self, interaction: discord.Interaction):
        view = EmbedBuilderView(author=interaction.user)
        preview = view.build_embed(is_preview=True)
        await interaction.response.send_message(embed=preview, view=view)

    # ── /format_help ────────────────────────────

    @app_commands.command(
        name="format_help",
        description="Discord で使える文字装飾・書式の一覧を表示します（自分にだけ見えます）",
    )
    async def format_help(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="✍️ Discord 文字装飾チートシート",
            description="メッセージや `/post` の本文欄で使える書式まとめです。",
            color=discord.Color.from_rgb(149, 117, 205),
        )
        embed.add_field(
            name="インライン装飾",
            value=(
                "**\\*\\*太字\\*\\*** → **太字**\n"
                "*\\*斜体\\** → *斜体*\n"
                "__\\_\\_下線\\_\\___ → __下線__\n"
                "~~\\~\\~打ち消し\\~\\~~~ → ~~打ち消し~~\n"
                "\\|\\|スポイラー\\|\\| → ||スポイラー||\n"
                "\\`インラインコード\\` → `コード`"
            ),
            inline=True,
        )
        embed.add_field(
            name="見出し・引用",
            value=(
                "`# 見出し1`\n"
                "`## 見出し2`\n"
                "`### 見出し3`\n"
                "`-# 小テキスト`\n"
                "`> 引用テキスト`\n"
                "`>>> 複数行引用`"
            ),
            inline=True,
        )
        embed.add_field(
            name="リスト",
            value=(
                "`- 項目` → 箇条書き\n"
                "`1. 項目` → 番号付きリスト\n"
                "（2スペースでネスト可）"
            ),
            inline=False,
        )
        embed.add_field(
            name="コードブロック",
            value=(
                "\\`\\`\\`\n"
                "コードブロック\n"
                "\\`\\`\\`\n\n"
                "\\`\\`\\`python\n"
                "# 言語名でシンタックスハイライト\n"
                "\\`\\`\\`"
            ),
            inline=True,
        )
        embed.add_field(
            name="画像埋め込みのコツ",
            value=(
                "• 画像URLをそのまま貼り付け → 自動埋め込み\n"
                "• `/post` の「画像URL」欄に入力\n"
                "• ファイルを直接添付でも埋め込み\n"
                "• GIF/WebP/PNG/JPG/JPEG 対応"
            ),
            inline=True,
        )
        embed.add_field(
            name="絵文字・メンション",
            value=(
                "`:smile:` → 😄 （Discordの絵文字）\n"
                "`@ユーザー名` → メンション\n"
                "`@here` / `@everyone`\n"
                "`#チャンネル名` → チャンネルリンク"
            ),
            inline=False,
        )
        embed.set_footer(text="💡 /post や /embed_builder を使うとより簡単に綺麗な投稿が作れます！")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
