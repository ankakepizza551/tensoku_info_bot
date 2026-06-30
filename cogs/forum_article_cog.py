import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager
from cogs.post_cog import _auto_decorate

logger = logging.getLogger("TensokuMatchBot")

_COLOR_OPTIONS = [
    discord.SelectOption(label="🔵 ブルー",   value="52,152,219"),
    discord.SelectOption(label="🟢 グリーン", value="46,204,113"),
    discord.SelectOption(label="🔴 レッド",   value="231,76,60"),
    discord.SelectOption(label="🟣 パープル", value="149,117,205"),
    discord.SelectOption(label="🟡 イエロー", value="241,196,15"),
    discord.SelectOption(label="🟠 オレンジ", value="230,126,34"),
    discord.SelectOption(label="⚫ グレー",   value="127,140,141"),
    discord.SelectOption(label="🩷 ピンク",   value="255,105,180"),
    discord.SelectOption(label="🩵 シアン",   value="26,188,156"),
    discord.SelectOption(label="⚪ ホワイト", value="236,240,241"),
]

_FORMAT_CONFIG: dict[str, tuple[str, str, str]] = {
    #            modal title       prefix   suffix
    "bold":    ("𝐁 太字で本文に追記",  "**",   "**"),
    "italic":  ("𝐼 斜体で本文に追記",  "*",    "*"),
    "code":    ("`C` コードで本文に追記", "`",  "`"),
    "quote":   ("❝ 引用で本文に追記",  "> ",   ""),
    "heading": ("＃ 見出しで本文に追記", "## ", ""),
}


# ─────────────────────────────────────────────
#  記事ビルダーView
# ─────────────────────────────────────────────

class ArticleBuilderView(discord.ui.View):
    def __init__(self, forum_channel_id: int, author: discord.Member):
        super().__init__(timeout=600)
        self.forum_channel_id = forum_channel_id
        self.author = author
        self.data: dict = {
            "title": "",
            "body": "",
            "image": "",
            "color": discord.Color.from_rgb(52, 152, 219),
        }

    def _build_embed(self, is_preview: bool = False) -> discord.Embed:
        embed = discord.Embed(
            title=self.data["title"] or ("(タイトルなし)" if is_preview else None),
            description=self.data["body"] or ("(本文なし)" if is_preview else None),
            color=self.data["color"],
        )
        if self.data["image"]:
            embed.set_image(url=self.data["image"])
        if is_preview:
            embed.set_footer(text=f"[下書き] 投稿者: {self.author.display_name}")
        return embed

    def _guard(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author.id

    async def _refresh(self, interaction: discord.Interaction):
        preview = self._build_embed(is_preview=True)
        try:
            await interaction.message.edit(embed=preview, view=self)
            await interaction.response.send_message("✅ 更新しました！", ephemeral=True)
        except discord.errors.NotFound:
            await interaction.response.defer()

    # ── Row 0: コンテンツ ────────────────────────

    @discord.ui.button(label="📝 タイトル・本文", style=discord.ButtonStyle.primary, row=0)
    async def btn_content(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(ArticleContentModal(self))

    @discord.ui.button(label="🖼️ 画像", style=discord.ButtonStyle.secondary, row=0)
    async def btn_image(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(ArticleImageModal(self))

    @discord.ui.button(label="🎨 カラー", style=discord.ButtonStyle.secondary, row=0)
    async def btn_color(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        view = ArticleColorPickerView(self, interaction.message)
        await interaction.response.send_message("🎨 カラーを選択してください：", view=view, ephemeral=True)

    # ── Row 1: 装飾追記 ──────────────────────────

    @discord.ui.button(label="𝐁 太字", style=discord.ButtonStyle.secondary, row=1)
    async def btn_bold(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(FormatAppendModal(self, "bold"))

    @discord.ui.button(label="𝐼 斜体", style=discord.ButtonStyle.secondary, row=1)
    async def btn_italic(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(FormatAppendModal(self, "italic"))

    @discord.ui.button(label="`C` コード", style=discord.ButtonStyle.secondary, row=1)
    async def btn_code(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(FormatAppendModal(self, "code"))

    @discord.ui.button(label="❝ 引用", style=discord.ButtonStyle.secondary, row=1)
    async def btn_quote(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(FormatAppendModal(self, "quote"))

    @discord.ui.button(label="＃ 見出し", style=discord.ButtonStyle.secondary, row=1)
    async def btn_heading(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await interaction.response.send_modal(FormatAppendModal(self, "heading"))

    # ── Row 2: アクション ─────────────────────────

    @discord.ui.button(label="📤 フォーラムに投稿", style=discord.ButtonStyle.success, row=2)
    async def btn_post(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        if not self.data["title"]:
            await interaction.response.send_message(
                "❌ タイトルが未入力です。「📝 タイトル・本文」から入力してください。", ephemeral=True
            )
            return

        forum_channel = interaction.guild.get_channel(self.forum_channel_id)
        if not isinstance(forum_channel, discord.ForumChannel):
            await interaction.response.send_message(
                "❌ 投稿先フォーラムチャンネルが見つかりません。", ephemeral=True
            )
            return

        perms = forum_channel.permissions_for(interaction.guild.me)
        if not perms.create_public_threads:
            await interaction.response.send_message(
                f"❌ {forum_channel.mention} にスレッドを作成する権限がありません。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        final_embed = self._build_embed(is_preview=False)
        final_embed.set_footer(
            text=f"投稿者: {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        try:
            try:
                await interaction.message.delete()
            except (discord.errors.NotFound, discord.Forbidden):
                pass

            result = await forum_channel.create_thread(
                name=self.data["title"],
                embed=final_embed,
            )
            thread = result.thread
            post_message = result.message

            control_view = ArticleControlView(
                thread_id=thread.id,
                author_id=interaction.user.id,
                post_message_id=post_message.id,
            )
            control_msg = await thread.send(
                "投稿者のみ編集できます。モデレーターも削除可能です。",
                view=control_view,
            )

            await db_manager.add_article_thread(
                thread_id=thread.id,
                post_message_id=post_message.id,
                control_message_id=control_msg.id,
                author_id=interaction.user.id,
            )
            logger.info(
                f"article_post: user={interaction.user.id} "
                f"forum={forum_channel.id} thread={thread.id}"
            )
            await interaction.followup.send(
                f"✅ 記事を投稿しました！\n→ {thread.mention}", ephemeral=True
            )
            self.stop()

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ 権限不足で投稿できませんでした。", ephemeral=True
            )
        except Exception as e:
            logger.error(f"ArticleBuilderView post error: {e}")
            await interaction.followup.send(
                f"❌ 投稿中にエラーが発生しました: {e}", ephemeral=True
            )

    @discord.ui.button(label="❌ キャンセル", style=discord.ButtonStyle.danger, row=2)
    async def btn_cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._guard(interaction):
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        try:
            await interaction.message.delete()
        except (discord.errors.NotFound, discord.Forbidden):
            pass
        await interaction.response.send_message("❌ 記事作成をキャンセルしました。", ephemeral=True)
        self.stop()


# ─────────────────────────────────────────────
#  ビルダー用モーダル群
# ─────────────────────────────────────────────

class ArticleContentModal(discord.ui.Modal):
    def __init__(self, builder: ArticleBuilderView):
        super().__init__(title="📝 タイトル・本文の編集")
        self.builder = builder

        self.title_input = discord.ui.TextInput(
            label="スレッドタイトル（必須）",
            placeholder="例: 天則攻略メモ / キャラ対策まとめ",
            default=builder.data["title"],
            required=True,
            max_length=100,
        )
        self.body_input = discord.ui.TextInput(
            label="本文（省略可）",
            style=discord.TextStyle.paragraph,
            placeholder="**太字** *斜体* `コード` ## 見出し > 引用",
            default=builder.data["body"],
            required=False,
            max_length=4000,
        )
        self.add_item(self.title_input)
        self.add_item(self.body_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.data["title"] = self.title_input.value
        self.builder.data["body"] = _auto_decorate(self.body_input.value)
        await self.builder._refresh(interaction)


class ArticleImageModal(discord.ui.Modal):
    def __init__(self, builder: ArticleBuilderView):
        super().__init__(title="🖼️ 画像URLの設定")
        self.builder = builder

        self.image_input = discord.ui.TextInput(
            label="画像URL（省略可）",
            placeholder="https://example.com/image.png",
            default=builder.data["image"],
            required=False,
            max_length=500,
        )
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.data["image"] = self.image_input.value.strip()
        await self.builder._refresh(interaction)


class FormatAppendModal(discord.ui.Modal):
    def __init__(self, builder: ArticleBuilderView, format_type: str):
        modal_title, self.pre, self.post = _FORMAT_CONFIG[format_type]
        super().__init__(title=modal_title)
        self.builder = builder

        self.text_input = discord.ui.TextInput(
            label="テキスト",
            style=discord.TextStyle.paragraph,
            placeholder="入力したテキストが装飾されて本文末尾に追記されます。",
            required=True,
            max_length=500,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: discord.Interaction):
        formatted = f"{self.pre}{self.text_input.value}{self.post}"
        if self.builder.data["body"]:
            self.builder.data["body"] += f"\n{formatted}"
        else:
            self.builder.data["body"] = formatted
        await self.builder._refresh(interaction)


# ─────────────────────────────────────────────
#  カラーピッカー（ビルダー用）
# ─────────────────────────────────────────────

class ArticleColorPickerView(discord.ui.View):
    def __init__(self, builder: ArticleBuilderView, preview_msg: discord.Message):
        super().__init__(timeout=60)
        self.add_item(ArticleColorSelect(builder, preview_msg))


class ArticleColorSelect(discord.ui.Select):
    def __init__(self, builder: ArticleBuilderView, preview_msg: discord.Message):
        super().__init__(placeholder="カラーを選んでください...", options=_COLOR_OPTIONS)
        self.builder = builder
        self.preview_msg = preview_msg

    async def callback(self, interaction: discord.Interaction):
        r, g, b = map(int, self.values[0].split(","))
        self.builder.data["color"] = discord.Color.from_rgb(r, g, b)
        preview = self.builder._build_embed(is_preview=True)
        try:
            await self.preview_msg.edit(embed=preview, view=self.builder)
        except discord.errors.NotFound:
            pass
        await interaction.response.send_message("✅ カラーを変更しました！", ephemeral=True)
        self.view.stop()


# ─────────────────────────────────────────────
#  記事編集モーダル（投稿後の編集用）
# ─────────────────────────────────────────────

class ArticleEditModal(discord.ui.Modal):
    def __init__(self, post_message: discord.Message):
        super().__init__(title="✏️ 記事を編集")
        self.post_message = post_message

        embed = post_message.embeds[0] if post_message.embeds else None
        current_title = (embed.title or "") if embed else ""
        current_body = (embed.description or "") if embed else ""
        current_image = (embed.image.url if embed and embed.image else "") if embed else ""

        self.article_title = discord.ui.TextInput(
            label="スレッドタイトル",
            default=current_title,
            required=True,
            max_length=100,
        )
        self.article_body = discord.ui.TextInput(
            label="本文（省略可）",
            style=discord.TextStyle.paragraph,
            default=current_body,
            required=False,
            max_length=4000,
        )
        self.image_url = discord.ui.TextInput(
            label="画像URL（省略可）",
            default=current_image,
            required=False,
            max_length=500,
        )
        self.add_item(self.article_title)
        self.add_item(self.article_body)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: discord.Interaction):
        orig_embed = self.post_message.embeds[0] if self.post_message.embeds else None
        color = orig_embed.color if orig_embed else discord.Color.from_rgb(52, 152, 219)
        orig_footer = orig_embed.footer if orig_embed else None

        body = _auto_decorate(self.article_body.value or "")
        image = self.image_url.value.strip() or None

        new_embed = discord.Embed(color=color)
        new_embed.title = self.article_title.value
        if body:
            new_embed.description = body
        if image:
            new_embed.set_image(url=image)
        if orig_footer:
            new_embed.set_footer(text=orig_footer.text, icon_url=orig_footer.icon_url)

        await self.post_message.edit(embed=new_embed)

        thread = interaction.channel
        if isinstance(thread, discord.Thread):
            try:
                await thread.edit(name=self.article_title.value)
            except discord.Forbidden:
                pass

        await interaction.response.send_message("✅ 記事を編集しました。", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"ArticleEditModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)


# ─────────────────────────────────────────────
#  スレッドコントロールView（編集 + 削除）
# ─────────────────────────────────────────────

class ArticleControlView(discord.ui.View):
    def __init__(self, thread_id: int, author_id: int, post_message_id: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id
        self.author_id = author_id
        self.post_message_id = post_message_id

        edit_btn = discord.ui.Button(
            label="✏️ 記事を編集",
            style=discord.ButtonStyle.primary,
            custom_id=f"ap_edit:{thread_id}",
        )
        edit_btn.callback = self._edit_callback

        delete_btn = discord.ui.Button(
            label="🗑️ スレッドを削除",
            style=discord.ButtonStyle.danger,
            custom_id=f"ap_delete:{thread_id}",
        )
        delete_btn.callback = self._delete_callback

        self.add_item(edit_btn)
        self.add_item(delete_btn)

    async def _edit_callback(self, interaction: discord.Interaction):
        thread_info = await db_manager.get_article_thread(self.thread_id)
        author_id = thread_info["author_id"] if thread_info else self.author_id

        if interaction.user.id != author_id:
            await interaction.response.send_message(
                "❌ 記事の編集は投稿者本人のみ可能です。", ephemeral=True
            )
            return

        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.response.send_message("❌ スレッド内でのみ使用できます。", ephemeral=True)
            return

        try:
            post_msg = await thread.fetch_message(self.post_message_id)
        except discord.NotFound:
            await interaction.response.send_message("❌ 投稿メッセージが見つかりません。", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"❌ 投稿の取得に失敗しました: {e}", ephemeral=True)
            return

        await interaction.response.send_modal(ArticleEditModal(post_msg))

    async def _delete_callback(self, interaction: discord.Interaction):
        thread_info = await db_manager.get_article_thread(self.thread_id)
        author_id = thread_info["author_id"] if thread_info else self.author_id

        is_author = interaction.user.id == author_id
        has_manage = interaction.user.guild_permissions.manage_threads

        if not is_author and not has_manage:
            await interaction.response.send_message(
                "❌ 投稿者またはモデレーターのみ削除できます。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.followup.send("❌ スレッド内でのみ使用できます。", ephemeral=True)
            return

        try:
            if thread_info:
                await db_manager.delete_article_thread(self.thread_id)
            await thread.delete()
            logger.info(f"article_thread deleted: thread={self.thread_id} by user={interaction.user.id}")
        except discord.Forbidden:
            await interaction.followup.send("❌ スレッドを削除する権限がありません。", ephemeral=True)
        except Exception as e:
            logger.error(f"article thread delete error: {e}")
            await interaction.followup.send(f"❌ 削除中にエラーが発生しました: {e}", ephemeral=True)


# ─────────────────────────────────────────────
#  フォーラム選択View（パネルボタン押下後）
# ─────────────────────────────────────────────

async def _open_builder(interaction: discord.Interaction, forum_channel_id: int) -> None:
    """選択されたフォーラムのビルダーをチャンネルに展開する共通処理"""
    view = ArticleBuilderView(forum_channel_id=forum_channel_id, author=interaction.user)
    preview = view._build_embed(is_preview=True)
    channel = interaction.guild.get_channel(forum_channel_id)
    mention = channel.mention if channel else f"<#{forum_channel_id}>"
    await interaction.response.edit_message(content=f"投稿先: {mention}", view=None)
    await interaction.followup.send(embed=preview, view=view)


class ArticleChannelSelectView(discord.ui.View):
    """カテゴリー絞り込みなし：Discord ネイティブの ChannelSelect を使用"""

    def __init__(self, author: discord.Member):
        super().__init__(timeout=120)
        self.author = author
        self._select = discord.ui.ChannelSelect(
            placeholder="投稿先のフォーラムチャンネルを選択...",
            channel_types=[discord.ChannelType.forum],
        )
        self._select.callback = self._select_callback
        self.add_item(self._select)

    async def _select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await _open_builder(interaction, self._select.values[0].id)
        self.stop()


class ArticleFilteredSelectView(discord.ui.View):
    """カテゴリー絞り込みあり：対象フォーラムのみ Select に列挙"""

    def __init__(self, author: discord.Member, forums: list[discord.ForumChannel]):
        super().__init__(timeout=120)
        self.author = author
        options = [
            discord.SelectOption(label=f"# {ch.name}", value=str(ch.id))
            for ch in forums[:25]
        ]
        self._select = discord.ui.Select(
            placeholder="投稿先のフォーラムチャンネルを選択...",
            options=options,
        )
        self._select.callback = self._select_callback
        self.add_item(self._select)

    async def _select_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ 操作権限がありません。", ephemeral=True)
            return
        await _open_builder(interaction, int(self._select.values[0]))
        self.stop()


# ─────────────────────────────────────────────
#  記事投稿パネルView（入口ボタン）
# ─────────────────────────────────────────────

class ArticlePanelView(discord.ui.View):
    def __init__(self, category_id: int | None = None):
        super().__init__(timeout=None)
        self.category_id = category_id

        btn = discord.ui.Button(
            label="📝 記事を投稿する",
            style=discord.ButtonStyle.primary,
            custom_id="ap_panel",
        )
        btn.callback = self._btn_callback
        self.add_item(btn)

    async def _btn_callback(self, interaction: discord.Interaction):
        if self.category_id:
            forums = [
                ch for ch in interaction.guild.channels
                if isinstance(ch, discord.ForumChannel) and ch.category_id == self.category_id
            ]
            if not forums:
                await interaction.response.send_message(
                    "❌ 指定カテゴリー内にフォーラムチャンネルが見つかりません。", ephemeral=True
                )
                return
            view = ArticleFilteredSelectView(author=interaction.user, forums=forums)
        else:
            view = ArticleChannelSelectView(author=interaction.user)

        await interaction.response.send_message(
            "📝 投稿先のフォーラムチャンネルを選択してください：",
            view=view,
            ephemeral=True,
        )


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class ForumArticleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        panels = await db_manager.get_article_panels()
        for panel in panels:
            view = ArticlePanelView(category_id=panel.get("category_id"))
            self.bot.add_view(view, message_id=panel["message_id"])
        if panels:
            logger.info(f"forum_article: 記事パネル {len(panels)} 件のViewを再登録")

        threads = await db_manager.get_article_threads()
        for t in threads:
            view = ArticleControlView(
                thread_id=t["thread_id"],
                author_id=t["author_id"],
                post_message_id=t["post_message_id"],
            )
            self.bot.add_view(view, message_id=t["control_message_id"])
        if threads:
            logger.info(f"forum_article: スレッドコントロール {len(threads)} 件のViewを再登録")

    # ── /setup_article_panel ─────────────────────

    @app_commands.command(
        name="setup_article_panel",
        description="記事投稿ボタンのパネルをこのチャンネルに設置します（管理者用）",
    )
    @app_commands.describe(category="フォーラムを絞り込むカテゴリー（省略時は全フォーラムを表示）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_article_panel(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
    ):
        category_id = category.id if category else None
        desc = (
            "下のボタンを押すと投稿先のフォーラムチャンネルを選択できます。\n"
            "選択後にビルダーが開き、タイトル・本文・画像・カラーを\n"
            "ボタンで設定しながらプレビューを確認して投稿できます。"
        )
        if category:
            desc += f"\n表示フォーラム: **{category.name}** カテゴリーのみ"

        embed = discord.Embed(
            title="📝 記事投稿",
            description=desc,
            color=discord.Color.from_rgb(52, 152, 219),
        )

        view = ArticlePanelView(category_id=category_id)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        await db_manager.add_article_panel(
            message_id=message.id,
            channel_id=interaction.channel_id,
            forum_channel_id=0,
            category_id=category_id,
        )
        logger.info(
            f"setup_article_panel: message={message.id} "
            f"channel={interaction.channel_id} category={category_id}"
        )

    # ── /remove_article_panel ────────────────────

    @app_commands.command(
        name="remove_article_panel",
        description="記事投稿パネルを削除します（管理者用）",
    )
    @app_commands.describe(message_id="削除するパネルのメッセージID")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_article_panel(
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

        deleted = await db_manager.delete_article_panel(mid)
        if not deleted:
            await interaction.response.send_message(
                "❌ 指定されたIDのパネルが見つかりませんでした。", ephemeral=True
            )
            return

        try:
            msg = await interaction.channel.fetch_message(mid)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        await interaction.response.send_message("✅ 記事投稿パネルを削除しました。", ephemeral=True)
        logger.info(f"remove_article_panel: message={mid} by user={interaction.user.id}")


async def setup(bot: commands.Bot):
    await bot.add_cog(ForumArticleCog(bot))
