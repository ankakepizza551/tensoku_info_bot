import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

CATEGORY_NAME = "レイドバトル"
BEGINNER_ROLE_NAME = "初級者"
ADVANCED_ROLE_NAME = "上級者"

RECRUIT_CHANNEL_NAME = "レイド募集"
BEGINNER_CHANNEL_NAME = "レイド-初級者専用"
ADVANCED_CHANNEL_NAME = "レイド-上級者専用"
COMMON_CHANNEL_NAME = "レイド-共通"


async def _resolve_role(guild: discord.Guild, role_id: int | None) -> discord.Role | None:
    """キャッシュに無ければAPIへ直接問い合わせて、削除漏れを防ぐ"""
    if not role_id:
        return None
    role = guild.get_role(role_id)
    if role is not None:
        return role
    try:
        roles = await guild.fetch_roles()
        return discord.utils.get(roles, id=role_id)
    except discord.HTTPException:
        return None


async def _resolve_channel(guild: discord.Guild, channel_id: int | None):
    """キャッシュに無ければAPIへ直接問い合わせて、削除漏れを防ぐ"""
    if not channel_id:
        return None
    channel = guild.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await guild.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _build_status_board_embed(guild: discord.Guild, advanced_role: discord.Role) -> discord.Embed:
    statuses = await db_manager.get_raid_advanced_statuses(guild.id)
    available, unavailable = [], []
    for member in advanced_role.members:
        (available if statuses.get(member.id, True) else unavailable).append(member)

    embed = discord.Embed(
        title="⚔️ 上級者 対応状況",
        description="初級者は「対応可能」な上級者を選んで挑戦してください（1vs1）。",
        color=discord.Color.from_rgb(230, 126, 34),
    )
    embed.add_field(
        name=f"✅ 対応可能 ({len(available)}人)",
        value="\n".join(f"・{m.mention}" for m in available) or "現在いません",
        inline=False,
    )
    embed.add_field(
        name=f"🛌 対応不可 ({len(unavailable)}人)",
        value="\n".join(f"・{m.mention}" for m in unavailable) or "なし",
        inline=False,
    )
    embed.set_footer(text="上級者本人が「対応状況を切り替える」ボタンで更新できます。")
    return embed


async def _sync_status_board(guild: discord.Guild):
    """上級者対応状況ボードを最新の状態に更新する（未設置なら何もしない）"""
    board = await db_manager.get_raid_status_board(guild.id)
    if board is None:
        return

    channel = guild.get_channel_or_thread(board["channel_id"])
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return

    settings = await db_manager.get_raid_battle_settings(guild.id) or {}
    advanced_role = await _resolve_role(guild, settings.get("advanced_role_id"))
    if advanced_role is None:
        return

    try:
        message = await channel.fetch_message(board["message_id"])
    except (discord.NotFound, discord.Forbidden):
        return

    try:
        await message.edit(embed=await _build_status_board_embed(guild, advanced_role))
    except discord.HTTPException as e:
        logger.warning(f"raid_status_board 更新失敗: {e}")


# ─────────────────────────────────────────────
#  お片付け（レイド終了後のクリーンアップ）
# ─────────────────────────────────────────────

class RaidCleanupConfirmView(discord.ui.View):
    """お片付け(カテゴリ・チャンネル・ロールの削除+データリセット)の実行前確認View"""

    def __init__(self, cog: "RaidBattleCog", invoker_id: int, settings: dict):
        super().__init__(timeout=120)
        self.cog = cog
        self.invoker_id = invoker_id
        self.settings = settings
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ コマンドを実行した本人または管理者のみ操作できます。", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="🗑️ 削除を実行", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🧹 削除処理を実行中...", embed=None, view=self)
        result_embed = await self.cog._execute_raid_cleanup(interaction.guild, self.settings)
        await interaction.edit_original_response(content=None, embed=result_embed, view=None)
        self.stop()

    @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="キャンセルしました。", embed=None, view=self)
        self.stop()

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="⏰ 確認時間が終了しました。お片付けは実行されていません。", view=self)
            except discord.HTTPException:
                pass


# ─────────────────────────────────────────────
#  常設操作パネル（登録・対応状況切り替え）
# ─────────────────────────────────────────────

class RaidPanelView(discord.ui.View):
    """固定custom_idを使うグローバル永続View。メッセージ単位の紐付け不要で再起動後も機能する"""

    def __init__(self, cog: "RaidBattleCog"):
        super().__init__(timeout=None)
        self.cog = cog

        beginner_btn = discord.ui.Button(
            label="🔰 初級者として登録",
            style=discord.ButtonStyle.success,
            custom_id="raid_panel:register_beginner",
        )
        beginner_btn.callback = self._register_beginner

        advanced_btn = discord.ui.Button(
            label="⚔️ 上級者として登録",
            style=discord.ButtonStyle.primary,
            custom_id="raid_panel:register_advanced",
        )
        advanced_btn.callback = self._register_advanced

        toggle_btn = discord.ui.Button(
            label="🔄 対応状況を切り替える（上級者用）",
            style=discord.ButtonStyle.secondary,
            custom_id="raid_panel:toggle_status",
        )
        toggle_btn.callback = self._toggle_status

        self.add_item(beginner_btn)
        self.add_item(advanced_btn)
        self.add_item(toggle_btn)

    async def _register_beginner(self, interaction: discord.Interaction):
        await self.cog._handle_register(interaction, as_advanced=False)

    async def _register_advanced(self, interaction: discord.Interaction):
        await self.cog._handle_register(interaction, as_advanced=True)

    async def _toggle_status(self, interaction: discord.Interaction):
        await self.cog._handle_toggle_status(interaction)


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class RaidBattleCog(commands.Cog):
    """初級者vs上級者レイドバトル用のカテゴリ・ロール・チャンネルの一括セットアップと登録/対応状況管理"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(RaidPanelView(self))

    # ── 登録処理 ──────────────────────────────────

    async def _handle_register(self, interaction: discord.Interaction, as_advanced: bool):
        guild = interaction.guild
        settings = await db_manager.get_raid_battle_settings(guild.id)
        if not settings or not settings.get("beginner_role_id") or not settings.get("advanced_role_id"):
            await interaction.response.send_message(
                "❌ このサーバーではレイドバトルが未設定です。管理者に `/setup_raid_battle` の実行を依頼してください。",
                ephemeral=True,
            )
            return

        beginner_role = await _resolve_role(guild, settings["beginner_role_id"])
        advanced_role = await _resolve_role(guild, settings["advanced_role_id"])
        if beginner_role is None or advanced_role is None:
            await interaction.response.send_message(
                "❌ ロールが見つかりません。管理者にご連絡ください。", ephemeral=True
            )
            return

        member = interaction.user
        try:
            if as_advanced:
                if beginner_role in member.roles:
                    await member.remove_roles(beginner_role, reason="レイドバトル 上級者へ再登録")
                if advanced_role not in member.roles:
                    await member.add_roles(advanced_role, reason="レイドバトル 上級者登録")
                await db_manager.ensure_raid_advanced_status(member.id, guild.id)
                await _sync_status_board(guild)
                await interaction.response.send_message(
                    f"✅ {advanced_role.mention} として登録しました（デフォルトは「対応可能」です）。",
                    ephemeral=True,
                )
            else:
                if advanced_role in member.roles:
                    await member.remove_roles(advanced_role, reason="レイドバトル 初級者へ再登録")
                    await _sync_status_board(guild)
                if beginner_role not in member.roles:
                    await member.add_roles(beginner_role, reason="レイドバトル 初級者登録")
                await interaction.response.send_message(
                    f"✅ {beginner_role.mention} として登録しました。", ephemeral=True
                )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ ロールを付与する権限がありません。管理者にご連絡ください。", ephemeral=True
            )
            return

        logger.info(f"raid_register: user={member.id} as_advanced={as_advanced}")

    # ── 対応状況の切り替え ────────────────────────

    async def _handle_toggle_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        settings = await db_manager.get_raid_battle_settings(guild.id)
        if not settings or not settings.get("advanced_role_id"):
            await interaction.response.send_message(
                "❌ このサーバーではレイドバトルが未設定です。", ephemeral=True
            )
            return

        advanced_role = await _resolve_role(guild, settings["advanced_role_id"])
        if advanced_role is None or advanced_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ 上級者ロールを持つユーザーのみ切り替えられます。「⚔️ 上級者として登録」から登録してください。",
                ephemeral=True,
            )
            return

        new_status = await db_manager.toggle_raid_advanced_status(interaction.user.id, guild.id)
        await _sync_status_board(guild)
        label = "✅ 対応可能" if new_status else "🛌 対応不可"
        await interaction.response.send_message(f"状態を {label} に切り替えました。", ephemeral=True)
        logger.info(f"raid_toggle_status: user={interaction.user.id} available={new_status}")

    # ── チャンネル作成ヘルパー ────────────────────

    async def _ensure_role(
        self, guild: discord.Guild, settings: dict, key: str, name: str, color: discord.Color
    ) -> discord.Role:
        role = await _resolve_role(guild, settings.get(key))
        if role is None:
            role = discord.utils.get(guild.roles, name=name)
        if role is None:
            role = await guild.create_role(
                name=name, color=color, mentionable=True,
                reason="レイドバトル 初期セットアップ",
            )
        await db_manager.save_raid_battle_settings(guild.id, **{key: role.id})
        return role

    async def _ensure_channel(
        self,
        guild: discord.Guild,
        settings: dict,
        key: str,
        name: str,
        category: discord.CategoryChannel,
        overwrites: dict,
    ) -> tuple[discord.TextChannel, bool]:
        channel = await _resolve_channel(guild, settings.get(key))
        if channel is None:
            channel = discord.utils.get(category.text_channels, name=name)
        is_new = channel is None
        if is_new:
            channel = await guild.create_text_channel(
                name=name, category=category, overwrites=overwrites,
                reason="レイドバトル 初期セットアップ",
            )
        await db_manager.save_raid_battle_settings(guild.id, **{key: channel.id})
        return channel, is_new

    # ── /setup_raid_battle ───────────────────────

    @app_commands.command(
        name="setup_raid_battle",
        description="初級者vs上級者レイドバトル用のカテゴリ・ロール・チャンネルを一括で作成します（管理者用）",
    )
    @app_commands.describe(category="使用するカテゴリ（省略時は新規作成）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_raid_battle(
        self, interaction: discord.Interaction, category: discord.CategoryChannel | None = None
    ):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        try:
            settings = await db_manager.get_raid_battle_settings(guild.id) or {}

            if category is None:
                category = await _resolve_channel(guild, settings.get("category_id"))
            if category is None:
                category = discord.utils.get(guild.categories, name=CATEGORY_NAME)
            if category is None:
                category = await guild.create_category(
                    CATEGORY_NAME, reason="レイドバトル 初期セットアップ"
                )
            await db_manager.save_raid_battle_settings(guild.id, category_id=category.id)
            settings = await db_manager.get_raid_battle_settings(guild.id) or {}

            beginner_role = await self._ensure_role(
                guild, settings, "beginner_role_id", BEGINNER_ROLE_NAME, discord.Color.from_rgb(46, 204, 113)
            )
            advanced_role = await self._ensure_role(
                guild, settings, "advanced_role_id", ADVANCED_ROLE_NAME, discord.Color.from_rgb(231, 76, 60)
            )
            settings = await db_manager.get_raid_battle_settings(guild.id) or {}

            recruit_channel, recruit_is_new = await self._ensure_channel(
                guild, settings, "recruit_channel_id", RECRUIT_CHANNEL_NAME, category,
                overwrites={},
            )
            settings = await db_manager.get_raid_battle_settings(guild.id) or {}

            beginner_channel, beginner_is_new = await self._ensure_channel(
                guild, settings, "beginner_channel_id", BEGINNER_CHANNEL_NAME, category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    beginner_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    advanced_role: discord.PermissionOverwrite(view_channel=False),
                },
            )
            settings = await db_manager.get_raid_battle_settings(guild.id) or {}

            advanced_channel, advanced_is_new = await self._ensure_channel(
                guild, settings, "advanced_channel_id", ADVANCED_CHANNEL_NAME, category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    advanced_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    beginner_role: discord.PermissionOverwrite(view_channel=False),
                },
            )
            settings = await db_manager.get_raid_battle_settings(guild.id) or {}

            common_channel, common_is_new = await self._ensure_channel(
                guild, settings, "common_channel_id", COMMON_CHANNEL_NAME, category,
                overwrites={
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    beginner_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    advanced_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                },
            )

            if recruit_is_new:
                panel_embed = discord.Embed(
                    title="⚔️ レイドバトル 登録パネル",
                    description=(
                        "下のボタンから初級者/上級者どちらかを選んで登録してください。\n"
                        "・🔰 初級者として登録\n"
                        "・⚔️ 上級者として登録（デフォルトで「対応可能」状態になります）\n"
                        "・🔄 対応状況を切り替える（上級者用、撃破された/休憩したいときなどに）"
                    ),
                    color=discord.Color.from_rgb(155, 89, 182),
                )
                await recruit_channel.send(embed=panel_embed, view=RaidPanelView(self))

            if common_is_new:
                board_embed = await _build_status_board_embed(guild, advanced_role)
                board_msg = await common_channel.send(embed=board_embed)
                await db_manager.save_raid_status_board(
                    guild_id=guild.id, channel_id=common_channel.id, message_id=board_msg.id
                )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ ロール/カテゴリ/チャンネルを作成する権限がありません。", ephemeral=True
            )
            return
        except discord.HTTPException as e:
            logger.error(f"setup_raid_battle エラー: {e}")
            await interaction.followup.send(f"❌ セットアップ中にエラーが発生しました: {e}", ephemeral=True)
            return

        def note(is_new: bool) -> str:
            return "" if is_new else "（既存を再利用）"

        summary = discord.Embed(
            title="✅ レイドバトル 初期セットアップ完了",
            description="初級者/上級者の登録は募集チャンネルの登録パネルから行えます。",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        summary.add_field(name="カテゴリ", value=category.name, inline=False)
        summary.add_field(name="募集チャンネル", value=f"{recruit_channel.mention}{note(recruit_is_new)}", inline=True)
        summary.add_field(name="共通チャンネル", value=f"{common_channel.mention}{note(common_is_new)}", inline=True)
        summary.add_field(name="初級者専用チャンネル", value=f"{beginner_channel.mention}{note(beginner_is_new)}", inline=True)
        summary.add_field(name="上級者専用チャンネル", value=f"{advanced_channel.mention}{note(advanced_is_new)}", inline=True)
        summary.add_field(name="初級者ロール", value=beginner_role.mention, inline=True)
        summary.add_field(name="上級者ロール", value=advanced_role.mention, inline=True)

        await interaction.followup.send(embed=summary, ephemeral=True)
        logger.info(f"setup_raid_battle: guild={guild.id} category={category.id}")

    # ── /setup_raid_panel ─────────────────────────

    @app_commands.command(
        name="setup_raid_panel",
        description="レイドバトルの登録・対応状況切り替えパネルをこのチャンネルに設置します（管理者用）",
    )
    @app_commands.describe(channel="設置するチャンネル（スレッドも指定可）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_raid_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | discord.Thread
    ):
        embed = discord.Embed(
            title="⚔️ レイドバトル 登録パネル",
            description=(
                "・🔰 初級者として登録\n"
                "・⚔️ 上級者として登録（デフォルトで「対応可能」状態になります）\n"
                "・🔄 対応状況を切り替える（上級者用）"
            ),
            color=discord.Color.from_rgb(155, 89, 182),
        )
        try:
            await channel.send(embed=embed, view=RaidPanelView(self))
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {channel.mention} にメッセージを送信する権限がありません。", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ 登録パネルを {channel.mention} に設置しました。", ephemeral=True
        )
        logger.info(f"setup_raid_panel: guild={interaction.guild_id} channel={channel.id}")

    # ── /setup_raid_status_board ─────────────────

    @app_commands.command(
        name="setup_raid_status_board",
        description="上級者の対応状況を常時表示するボードをこのチャンネルに設置します（管理者用）",
    )
    @app_commands.describe(channel="設置するチャンネル（スレッドも指定可）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_raid_status_board(
        self, interaction: discord.Interaction, channel: discord.TextChannel | discord.Thread
    ):
        guild = interaction.guild
        settings = await db_manager.get_raid_battle_settings(guild.id)
        advanced_role = await _resolve_role(guild, settings.get("advanced_role_id")) if settings else None
        if advanced_role is None:
            await interaction.response.send_message(
                "❌ 上級者ロールが未設定です。先に `/setup_raid_battle` を実行してください。", ephemeral=True
            )
            return

        embed = await _build_status_board_embed(guild, advanced_role)
        try:
            board_msg = await channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {channel.mention} にメッセージを送信する権限がありません。", ephemeral=True
            )
            return

        await db_manager.save_raid_status_board(
            guild_id=guild.id, channel_id=channel.id, message_id=board_msg.id
        )
        await interaction.response.send_message(
            f"✅ 対応状況ボードを {channel.mention} に設置しました。", ephemeral=True
        )
        logger.info(f"setup_raid_status_board: guild={guild.id} channel={channel.id} message={board_msg.id}")

    # ── /raid_registered_list ─────────────────────

    @app_commands.command(
        name="raid_registered_list",
        description="現在登録されている初級者/上級者の一覧をコピペ用テキストで出力します（管理者用）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def raid_registered_list(self, interaction: discord.Interaction):
        guild = interaction.guild
        settings = await db_manager.get_raid_battle_settings(guild.id)
        if not settings or not settings.get("beginner_role_id") or not settings.get("advanced_role_id"):
            await interaction.response.send_message(
                "❌ このサーバーではレイドバトルが未設定です。", ephemeral=True
            )
            return

        beginner_role = await _resolve_role(guild, settings.get("beginner_role_id"))
        advanced_role = await _resolve_role(guild, settings.get("advanced_role_id"))

        lines = []
        if beginner_role:
            for m in beginner_role.members:
                lines.append(f"{m.display_name} - 初級者")
        if advanced_role:
            for m in advanced_role.members:
                lines.append(f"{m.display_name} - 上級者")

        if not lines:
            await interaction.response.send_message("登録者がいません。", ephemeral=True)
            return

        # Discordのメッセージ長制限(2000文字)対策で複数チャンクに分割する
        chunks = []
        current = ""
        for line in lines:
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) > 1900:
                chunks.append(current)
                current = line
            else:
                current = candidate
        if current:
            chunks.append(current)

        await interaction.response.send_message(f"```\n{chunks[0]}\n```", ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(f"```\n{chunk}\n```", ephemeral=True)

        logger.info(f"raid_registered_list: guild={guild.id} count={len(lines)}")

    # ── お片付け（レイド終了後のクリーンアップ） ──

    async def _execute_raid_cleanup(self, guild: discord.Guild, settings: dict) -> discord.Embed:
        deleted_channels = 0
        deleted_roles = 0
        errors = []

        for key in ("recruit_channel_id", "beginner_channel_id", "advanced_channel_id", "common_channel_id"):
            channel = await _resolve_channel(guild, settings.get(key))
            if channel is not None:
                try:
                    await channel.delete(reason="レイドバトル 終了によるお片付け")
                    deleted_channels += 1
                except discord.Forbidden:
                    errors.append(f"チャンネル {channel.name} の削除に失敗（権限不足）")

        category = await _resolve_channel(guild, settings.get("category_id"))
        if category is not None:
            try:
                await category.delete(reason="レイドバトル 終了によるお片付け")
            except discord.Forbidden:
                errors.append(f"カテゴリ {category.name} の削除に失敗（権限不足）")

        for key in ("beginner_role_id", "advanced_role_id"):
            role = await _resolve_role(guild, settings.get(key))
            if role is not None:
                try:
                    await role.delete(reason="レイドバトル 終了によるお片付け")
                    deleted_roles += 1
                except discord.Forbidden:
                    errors.append(f"ロール {role.name} の削除に失敗（権限不足）")

        await db_manager.clear_raid_battle_settings(guild.id)
        await db_manager.clear_raid_advanced_statuses(guild.id)
        await db_manager.clear_raid_status_board(guild.id)

        embed = discord.Embed(
            title="🧹 レイドバトル お片付け完了",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.add_field(name="削除したチャンネル/カテゴリ", value=str(deleted_channels + (1 if category else 0)), inline=True)
        embed.add_field(name="削除したロール", value=str(deleted_roles), inline=True)
        embed.add_field(
            name="リセットしたデータ",
            value="設定・対応状況ボードの紐付け・上級者の対応状況",
            inline=False,
        )
        if errors:
            embed.add_field(name="⚠️ 一部失敗", value="\n".join(errors)[:1024], inline=False)
        embed.set_footer(text="次回は /setup_raid_battle で最初から作り直せます。")

        logger.info(
            f"raid_cleanup: guild={guild.id} channels={deleted_channels} roles={deleted_roles} errors={len(errors)}"
        )
        return embed

    @app_commands.command(
        name="raid_cleanup",
        description="レイドバトル終了後のお片付け（カテゴリ・チャンネル・ロールの削除+データリセット）を行います（管理者用）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def raid_cleanup(self, interaction: discord.Interaction):
        guild = interaction.guild
        settings = await db_manager.get_raid_battle_settings(guild.id) or {}

        category = await _resolve_channel(guild, settings.get("category_id"))
        channels = {
            "募集チャンネル": await _resolve_channel(guild, settings.get("recruit_channel_id")),
            "初級者専用チャンネル": await _resolve_channel(guild, settings.get("beginner_channel_id")),
            "上級者専用チャンネル": await _resolve_channel(guild, settings.get("advanced_channel_id")),
            "共通チャンネル": await _resolve_channel(guild, settings.get("common_channel_id")),
        }
        beginner_role = await _resolve_role(guild, settings.get("beginner_role_id"))
        advanced_role = await _resolve_role(guild, settings.get("advanced_role_id"))

        if category is None and not any(channels.values()) and beginner_role is None and advanced_role is None:
            await interaction.response.send_message(
                "削除対象のカテゴリ・チャンネル・ロールが見つかりませんでした。", ephemeral=True
            )
            return

        lines = [f"カテゴリ: {category.name}" if category else "カテゴリ: (すでに存在しません)"]
        for label, ch in channels.items():
            lines.append(f"{label}: {ch.mention if ch else '(すでに存在しません)'}")
        lines.append(f"初級者ロール: {beginner_role.mention if beginner_role else '(すでに存在しません)'}")
        lines.append(f"上級者ロール: {advanced_role.mention if advanced_role else '(すでに存在しません)'}")

        embed = discord.Embed(
            title="⚠️ レイドバトル お片付け確認",
            description=(
                "以下のカテゴリ・チャンネル・ロールをすべて削除し、登録・対応状況データをリセットします。\n"
                "**この操作は取り消せません。**\n\n"
                "登録者リストが必要な場合は、先に `/raid_registered_list` で出力しておいてください。"
            ),
            color=discord.Color.from_rgb(230, 126, 34),
        )
        embed.add_field(name="削除対象", value="\n".join(lines), inline=False)

        view = RaidCleanupConfirmView(self, interaction.user.id, settings)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(RaidBattleCog(bot))
