import logging
import random

import discord
from discord import app_commands
from discord.ext import commands
from database import db_manager

logger = logging.getLogger("TensokuMatchBot")

STRENGTH_LABELS = {1: "初級者", 2: "中級者", 3: "上級者"}
TEAM_LABELS = ["Aチーム", "Bチーム", "Cチーム", "Dチーム"]
TEAM_EMOJIS = ["🟥", "🟦", "🟨", "🟩"]
TEAM_ROLE_COLORS = [
    discord.Color.from_rgb(231, 76, 60),   # A: 赤
    discord.Color.from_rgb(52, 152, 219),  # B: 青
    discord.Color.from_rgb(241, 196, 15),  # C: 黄
    discord.Color.from_rgb(46, 204, 113),  # D: 緑
]
PARTICIPANT_ROLE_NAME = "陣取り参加者"


def _neighbors(idx: int) -> list:
    """5x5グリッド(行優先インデックス)における上下左右の隣接マスを返す"""
    r, c = divmod(idx, 5)
    result = []
    if r > 0:
        result.append(idx - 5)
    if r < 4:
        result.append(idx + 5)
    if c > 0:
        result.append(idx - 1)
    if c < 4:
        result.append(idx + 1)
    return result


def _compute_frontier(owner_map: dict, team_index: int) -> set:
    """指定チームの陣地に隣接する、まだそのチームが所有していないマスの集合を返す"""
    frontier = set()
    for idx in range(25):
        if owner_map.get(idx) == team_index:
            for n in _neighbors(idx):
                if owner_map.get(n) != team_index:
                    frontier.add(n)
    return frontier


def _strength_label(team_row: dict) -> str:
    if team_row["is_captain"]:
        return "大将 (強さ5)"
    return STRENGTH_LABELS.get(team_row["strength"], str(team_row["strength"]))


def _build_register_confirmation_embed(
    strength: int, ip_info: str, autopunch: str, giuroll: str, comment: str
) -> discord.Embed:
    embed = discord.Embed(
        title="✅ 陣取りゲーム プロフィールを登録しました",
        description="内容を変更したい場合は、再度 `/territory_register` または登録パネルのボタンから実行してください。",
        color=discord.Color.from_rgb(46, 204, 113),
    )
    embed.add_field(name="強さ", value=STRENGTH_LABELS.get(strength, str(strength)), inline=True)
    embed.add_field(name="IP/接続情報", value=ip_info, inline=True)
    embed.add_field(name="オートパンチ", value=autopunch, inline=True)
    embed.add_field(name="giuroll", value=giuroll, inline=True)
    embed.add_field(name="一言", value=comment or "なし", inline=False)
    return embed


def _build_teams_embed(teams: list, channel_map: dict = None, voice_map: dict = None) -> discord.Embed:
    """teams: [[{"user_id","username","strength","is_captain"}, ...], ...]"""
    embed = discord.Embed(
        title="🗺️ 陣取りゲーム チーム分け結果",
        color=discord.Color.from_rgb(52, 152, 219),
    )
    for i, members in enumerate(teams):
        total = sum(m["strength"] for m in members)
        sorted_members = sorted(members, key=lambda m: (not m["is_captain"], -m["strength"]))
        lines = []
        for m in sorted_members:
            if m["is_captain"]:
                lines.append(f"👑 {m['username']} (`大将`)")
            else:
                label = STRENGTH_LABELS.get(m["strength"], str(m["strength"]))
                lines.append(f"　{m['username']} (`{label}`)")
        field_name = f"{TEAM_LABELS[i]}（{len(members)}人 / 合計強さ{total}）"
        extra = []
        if channel_map and channel_map.get(i):
            extra.append(channel_map[i].mention)
        if voice_map and voice_map.get(i):
            extra.append(f"🔊{voice_map[i].mention}")
        if extra:
            field_name += " → " + " ".join(extra)
        embed.add_field(
            name=field_name,
            value="\n".join(lines) or "なし",
            inline=False,
        )
    return embed


class TerritoryCellButton(discord.ui.Button):
    def __init__(self, cell_index: int, label: str, style: discord.ButtonStyle, disabled: bool, row: int):
        super().__init__(style=style, label=label, disabled=disabled, row=row)
        self.cell_index = cell_index

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_click(interaction, self.cell_index)


class TerritoryExpansionView(discord.ui.View):
    """勝利チームが侵略度分だけ隣接マスを自由に選んで塗り替えるための一時View（隣接候補が侵略度を超える場合のみ使用）"""

    def __init__(self, cog: "TerritoryCog", guild_id: int, team_index: int, owner_map: dict, frontier: set, remaining: int):
        super().__init__(timeout=600)
        self.cog = cog
        self.guild_id = guild_id
        self.team_index = team_index
        self.owner_map = dict(owner_map)
        self.frontier = set(frontier)
        self.remaining = remaining
        self.message: discord.Message | None = None
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for idx in range(25):
            r, c = divmod(idx, 5)
            if idx in self.frontier and self.remaining > 0:
                btn = TerritoryCellButton(idx, f"{r + 1}-{c + 1}", discord.ButtonStyle.success, False, r)
            else:
                owner = self.owner_map.get(idx)
                label = TEAM_EMOJIS[owner] if owner is not None else "⬜"
                btn = TerritoryCellButton(idx, label, discord.ButtonStyle.secondary, True, r)
            self.add_item(btn)

    async def handle_click(self, interaction: discord.Interaction, cell_index: int):
        team_row = await db_manager.get_territory_team_of_user(self.guild_id, interaction.user.id)
        if team_row is None or team_row["team_index"] != self.team_index:
            await interaction.response.send_message(
                "❌ 勝利チームのメンバーのみ選択できます。", ephemeral=True
            )
            return

        if cell_index not in self.frontier or self.remaining <= 0:
            await interaction.response.send_message("❌ このマスは選択できません。", ephemeral=True)
            return

        await db_manager.set_territory_grid_cell(self.guild_id, cell_index, self.team_index)
        self.owner_map[cell_index] = self.team_index
        self.frontier.discard(cell_index)
        self.remaining -= 1

        for n in _neighbors(cell_index):
            if self.owner_map.get(n) != self.team_index:
                self.frontier.add(n)
            else:
                self.frontier.discard(n)

        finished = self.remaining <= 0 or not self.frontier
        self._build_buttons()
        embed = await self.cog._build_grid_embed(self.guild_id)

        if finished:
            self.stop()
            content = f"✅ {TEAM_LABELS[self.team_index]} の陣地拡張が完了しました！"
        else:
            content = f"🗺️ 残り{self.remaining}マス選択できます（{TEAM_LABELS[self.team_index]}）"

        await interaction.response.edit_message(content=content, embed=embed, view=self)
        logger.info(
            f"territory_expand: guild={self.guild_id} team={self.team_index} cell={cell_index} "
            f"remaining={self.remaining}"
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⏰ 選択時間が終了しました。残りのマスは選択されませんでした。", view=self
                )
            except discord.HTTPException:
                pass


class TerritoryCleanupConfirmView(discord.ui.View):
    """お片付け(チームロール・チャンネル削除+データリセット)の実行前確認View"""

    def __init__(self, cog: "TerritoryCog", invoker_id: int, team_role_rows: list):
        super().__init__(timeout=120)
        self.cog = cog
        self.invoker_id = invoker_id
        self.team_role_rows = team_role_rows
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
        result_embed = await self.cog._execute_territory_cleanup(interaction.guild, self.team_role_rows)
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


class TerritoryRegisterModal(discord.ui.Modal):
    def __init__(self, cog: "TerritoryCog", existing: dict | None = None):
        super().__init__(title="🗺️ 陣取りゲーム プロフィール登録")
        self.cog = cog
        e = existing or {}

        self.strength_input = discord.ui.TextInput(
            label="強さ（1:初級者 / 2:中級者 / 3:上級者）",
            placeholder="1〜3の数字を入力",
            default=str(e["strength"]) if e.get("strength") else "",
            required=True,
            max_length=1,
        )
        self.ip_input = discord.ui.TextInput(
            label="IP/接続情報",
            placeholder="例: IP対応可 / クラ専のみ",
            default=e.get("ip_info", ""),
            required=True,
            max_length=100,
        )
        self.autopunch_input = discord.ui.TextInput(
            label="オートパンチ有無",
            placeholder="あり / なし",
            default=e.get("autopunch", ""),
            required=True,
            max_length=10,
        )
        self.giuroll_input = discord.ui.TextInput(
            label="giuroll有無",
            placeholder="あり / なし",
            default=e.get("giuroll", ""),
            required=True,
            max_length=10,
        )
        self.comment_input = discord.ui.TextInput(
            label="一言コメント（任意）",
            style=discord.TextStyle.paragraph,
            default=e.get("comment", ""),
            required=False,
            max_length=200,
        )

        self.add_item(self.strength_input)
        self.add_item(self.ip_input)
        self.add_item(self.autopunch_input)
        self.add_item(self.giuroll_input)
        self.add_item(self.comment_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw_strength = self.strength_input.value.strip()
        if raw_strength not in ("1", "2", "3"):
            await interaction.response.send_message(
                "❌ 強さは1〜3の数字で入力してください（1:初級者 / 2:中級者 / 3:上級者）。",
                ephemeral=True,
            )
            return

        strength = int(raw_strength)
        ip_clean = self.ip_input.value.strip()
        autopunch_clean = self.autopunch_input.value.strip()
        giuroll_clean = self.giuroll_input.value.strip()
        comment_clean = self.comment_input.value.strip()

        await db_manager.save_territory_profile(
            user_id=interaction.user.id,
            username=interaction.user.display_name,
            strength=strength,
            ip_info=ip_clean,
            autopunch=autopunch_clean,
            giuroll=giuroll_clean,
            comment=comment_clean,
        )

        embed = _build_register_confirmation_embed(
            strength, ip_clean, autopunch_clean, giuroll_clean, comment_clean
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self.cog._grant_participant_role(interaction.user)
        logger.info(f"territory_register(modal): user={interaction.user.id} strength={strength}")

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"TerritoryRegisterModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 登録中にエラーが発生しました。", ephemeral=True)


class TerritoryRegisterPanelView(discord.ui.View):
    """固定custom_idを使うグローバル永続View。再起動後もボタンが機能する"""

    def __init__(self, cog: "TerritoryCog"):
        super().__init__(timeout=None)
        self.cog = cog
        btn = discord.ui.Button(
            label="📝 陣取りゲーム プロフィール登録/変更",
            style=discord.ButtonStyle.primary,
            custom_id="territory_panel:register",
        )
        btn.callback = self._register_callback
        self.add_item(btn)

    async def _register_callback(self, interaction: discord.Interaction):
        existing = await db_manager.get_territory_profile(interaction.user.id)
        await interaction.response.send_modal(TerritoryRegisterModal(self.cog, existing))


class TerritoryInfoPanelView(discord.ui.View):
    """プロフィール確認・登録者一覧・チーム分け結果をまとめた固定custom_idの永続View"""

    def __init__(self, cog: "TerritoryCog"):
        super().__init__(timeout=None)
        self.cog = cog

        profile_btn = discord.ui.Button(
            label="👤 自分のプロフィール確認",
            style=discord.ButtonStyle.primary,
            custom_id="territory_panel:profile",
        )
        profile_btn.callback = self._profile_callback
        self.add_item(profile_btn)

        list_btn = discord.ui.Button(
            label="📋 登録者一覧",
            style=discord.ButtonStyle.secondary,
            custom_id="territory_panel:list",
        )
        list_btn.callback = self._list_callback
        self.add_item(list_btn)

        teams_btn = discord.ui.Button(
            label="🗂️ チーム分け結果",
            style=discord.ButtonStyle.secondary,
            custom_id="territory_panel:teams",
        )
        teams_btn.callback = self._teams_callback
        self.add_item(teams_btn)

    async def _profile_callback(self, interaction: discord.Interaction):
        embed = await self.cog._build_profile_embed(interaction.user)
        if embed is None:
            await interaction.response.send_message(
                "❌ まだプロフィールを登録していません。先に登録ボタンから登録してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _list_callback(self, interaction: discord.Interaction):
        embed = await self.cog._build_list_embed()
        if embed is None:
            await interaction.response.send_message("まだ誰も登録していません。", ephemeral=True)
            return
        await interaction.response.send_message(embed=embed)

    async def _teams_callback(self, interaction: discord.Interaction):
        embed = await self.cog._build_current_teams_embed(interaction.guild_id)
        if embed is None:
            await interaction.response.send_message(
                "まだチーム分けが行われていません。管理者に `/territory_draw` の実施を依頼してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed)


class TerritoryOpponentSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="対戦相手を選択してください", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        view: "TerritoryReportSetupView" = self.view
        view.opponent = self.values[0]
        for child in view.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = False
        await interaction.response.edit_message(
            content=f"対戦相手: **{view.opponent.display_name}**\nあなたから見た結果を選んでください。",
            view=view,
        )


class TerritoryResultButton(discord.ui.Button):
    def __init__(self, result_value: str, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, disabled=True)
        self.result_value = result_value

    async def callback(self, interaction: discord.Interaction):
        view: "TerritoryReportSetupView" = self.view
        if view.opponent is None:
            await interaction.response.send_message("❌ 先に対戦相手を選択してください。", ephemeral=True)
            return

        guild_id = interaction.guild_id
        outcome = await view.cog._process_territory_report(
            guild_id, interaction.user, view.opponent, self.result_value
        )

        if not outcome["ok"]:
            await interaction.response.send_message(outcome["error"], ephemeral=True)
            return

        await interaction.response.edit_message(content="✅ 対戦結果を送信しました。", view=None)
        await interaction.followup.send(embed=outcome["embed"])
        await view.cog._expand_territory(interaction, guild_id, outcome["winner_team_index"], outcome["invasion"])
        await view.cog._check_game_finished(
            interaction, guild_id, outcome["fought_before"], outcome["winner_id"], outcome["loser_id"]
        )
        view.stop()


class TerritoryReportSetupView(discord.ui.View):
    """対戦相手をUserSelectで選び、勝ち/負けボタンで確定する一時View（モーダルはユーザー選択に非対応のため）"""

    def __init__(self, cog: "TerritoryCog"):
        super().__init__(timeout=120)
        self.cog = cog
        self.opponent: discord.Member | None = None
        self.add_item(TerritoryOpponentSelect())
        self.add_item(TerritoryResultButton("win", "✅ 勝ち", discord.ButtonStyle.success))
        self.add_item(TerritoryResultButton("lose", "❌ 負け", discord.ButtonStyle.danger))


class TerritoryMatchDeleteModal(discord.ui.Modal):
    def __init__(self, cog: "TerritoryCog"):
        super().__init__(title="🗑️ 陣取りゲーム 対戦結果の削除")
        self.cog = cog
        self.match_id_input = discord.ui.TextInput(
            label="削除する対戦ID (Match ID)",
            placeholder="例: 12",
            required=True,
            max_length=10,
        )
        self.add_item(self.match_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.match_id_input.value.strip()
        if not raw.isdigit():
            await interaction.response.send_message("❌ 対戦IDは数字で入力してください。", ephemeral=True)
            return
        await self.cog._process_match_delete(interaction, int(raw))

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"TerritoryMatchDeleteModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 削除中にエラーが発生しました。", ephemeral=True)


class TerritoryBattlePanelView(discord.ui.View):
    """対戦結果報告・戦況表示・対戦削除・陣地マップをまとめた固定custom_idの永続View"""

    def __init__(self, cog: "TerritoryCog"):
        super().__init__(timeout=None)
        self.cog = cog

        report_btn = discord.ui.Button(
            label="⚔️ 対戦結果を報告",
            style=discord.ButtonStyle.success,
            custom_id="territory_panel:report",
        )
        report_btn.callback = self._report_callback
        self.add_item(report_btn)

        score_btn = discord.ui.Button(
            label="📊 現在の戦況",
            style=discord.ButtonStyle.primary,
            custom_id="territory_panel:score",
        )
        score_btn.callback = self._score_callback
        self.add_item(score_btn)

        delete_btn = discord.ui.Button(
            label="🗑️ 対戦結果を削除",
            style=discord.ButtonStyle.danger,
            custom_id="territory_panel:match_delete",
        )
        delete_btn.callback = self._delete_callback
        self.add_item(delete_btn)

        map_btn = discord.ui.Button(
            label="🗺️ 陣地マップ",
            style=discord.ButtonStyle.secondary,
            custom_id="territory_panel:map",
        )
        map_btn.callback = self._map_callback
        self.add_item(map_btn)

    async def _report_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "対戦相手と結果を選択してください:",
            view=TerritoryReportSetupView(self.cog),
            ephemeral=True,
        )

    async def _score_callback(self, interaction: discord.Interaction):
        embed = await self.cog._build_score_embed(interaction.guild_id)
        if embed is None:
            await interaction.response.send_message(
                "まだチーム分けが行われていません。管理者に `/territory_draw` の実施を依頼してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed)

    async def _delete_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TerritoryMatchDeleteModal(self.cog))

    async def _map_callback(self, interaction: discord.Interaction):
        embed = await self.cog._build_grid_embed(interaction.guild_id)
        if embed is None:
            await interaction.response.send_message(
                "まだ陣地マップが初期化されていません。管理者に `/territory_draw` の実施を依頼してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed)


class TerritoryCog(commands.Cog):
    """陣取りゲーム用のプロフィール登録・チーム分け・対戦報告・陣地マップ機能"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(TerritoryRegisterPanelView(self))
        self.bot.add_view(TerritoryInfoPanelView(self))
        self.bot.add_view(TerritoryBattlePanelView(self))

    async def _ensure_participant_role(self, guild: discord.Guild) -> discord.Role | None:
        """陣取りゲーム参加者ロールを取得する。存在しなければ自動作成する"""
        settings = await db_manager.get_territory_settings(guild.id)
        role = None
        if settings and settings.get("participant_role_id"):
            role = guild.get_role(settings["participant_role_id"])

        if role is None:
            try:
                role = await guild.create_role(
                    name=PARTICIPANT_ROLE_NAME,
                    color=discord.Color.from_rgb(149, 165, 166),
                    mentionable=True,
                    reason="陣取りゲーム参加者ロールの自動作成",
                )
            except discord.Forbidden:
                logger.warning(f"territory: 参加者ロール作成失敗（権限不足） guild={guild.id}")
                return None
            await db_manager.save_territory_settings(guild.id, participant_role_id=role.id)

        return role

    async def _ensure_participant_channel(
        self, guild: discord.Guild, role: discord.Role, category: discord.CategoryChannel | None = None
    ) -> discord.TextChannel | None:
        """参加者ロール共通の雑談チャンネルを取得する。存在しなければ自動作成する"""
        settings = await db_manager.get_territory_settings(guild.id)
        channel = None
        if settings and settings.get("participant_channel_id"):
            channel = guild.get_channel(settings["participant_channel_id"])

        if channel is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            }
            try:
                channel = await guild.create_text_channel(
                    name="陣取り-参加者雑談",
                    category=category,
                    overwrites=overwrites,
                    reason="陣取りゲーム 参加者共通チャンネルの自動作成",
                )
            except discord.Forbidden:
                logger.warning(f"territory: 参加者雑談チャンネル作成失敗（権限不足） guild={guild.id}")
                return None
            await db_manager.save_territory_settings(guild.id, participant_channel_id=channel.id)

        return channel

    async def _ensure_participant_voice_channel(
        self, guild: discord.Guild, role: discord.Role, category: discord.CategoryChannel | None = None
    ) -> discord.VoiceChannel | None:
        """参加者ロール共通のボイスチャンネルを取得する。存在しなければ自動作成する"""
        settings = await db_manager.get_territory_settings(guild.id)
        channel = None
        if settings and settings.get("participant_voice_channel_id"):
            channel = guild.get_channel(settings["participant_voice_channel_id"])

        if channel is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False),
                role: discord.PermissionOverwrite(view_channel=True, connect=True, speak=True),
            }
            try:
                channel = await guild.create_voice_channel(
                    name="陣取り-参加者VC",
                    category=category,
                    overwrites=overwrites,
                    reason="陣取りゲーム 参加者共通ボイスチャンネルの自動作成",
                )
            except discord.Forbidden:
                logger.warning(f"territory: 参加者VC作成失敗（権限不足） guild={guild.id}")
                return None
            await db_manager.save_territory_settings(guild.id, participant_voice_channel_id=channel.id)

        return channel

    async def _grant_participant_role(self, member: discord.Member):
        role = await self._ensure_participant_role(member.guild)
        if role is None:
            return

        await self._ensure_participant_channel(member.guild, role)
        await self._ensure_participant_voice_channel(member.guild, role)

        if role in member.roles:
            return
        try:
            await member.add_roles(role, reason="陣取りゲーム プロフィール登録")
        except discord.Forbidden:
            logger.warning(f"territory: 参加者ロール付与失敗（権限不足） user={member.id}")

    async def _sync_team_roles_and_channels(
        self, guild: discord.Guild, teams: list, category: discord.CategoryChannel | None
    ) -> tuple:
        """チームロール・チームチャンネルを取得/作成し、メンバーへのロール付け替えまで行う"""
        n_teams = len(teams)
        existing_roles = {r["team_index"]: r for r in await db_manager.get_territory_team_roles(guild.id)}

        team_roles: list[discord.Role | None] = []
        team_channels: list[discord.TextChannel | None] = []
        team_voice_channels: list[discord.VoiceChannel | None] = []

        for i in range(n_teams):
            existing = existing_roles.get(i)

            role = guild.get_role(existing["role_id"]) if existing and existing.get("role_id") else None
            if role is None:
                try:
                    role = await guild.create_role(
                        name=TEAM_LABELS[i],
                        color=TEAM_ROLE_COLORS[i % len(TEAM_ROLE_COLORS)],
                        mentionable=True,
                        reason="陣取りゲーム チームロール自動作成",
                    )
                except discord.Forbidden:
                    logger.warning(f"territory: チームロール作成失敗（権限不足） guild={guild.id} team={i}")
                    role = None

            channel = guild.get_channel(existing["channel_id"]) if existing and existing.get("channel_id") else None
            if channel is None:
                overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
                if role is not None:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                try:
                    channel = await guild.create_text_channel(
                        name=f"陣取り-{TEAM_LABELS[i]}",
                        category=category,
                        overwrites=overwrites,
                        reason="陣取りゲーム チームチャンネル自動作成",
                    )
                except discord.Forbidden:
                    logger.warning(f"territory: チームチャンネル作成失敗（権限不足） guild={guild.id} team={i}")
                    channel = None
            elif role is not None:
                try:
                    await channel.set_permissions(guild.default_role, view_channel=False)
                    await channel.set_permissions(role, view_channel=True, send_messages=True)
                except discord.Forbidden:
                    logger.warning(f"territory: チームチャンネル権限更新失敗（権限不足） guild={guild.id} team={i}")

            voice_channel = (
                guild.get_channel(existing["voice_channel_id"])
                if existing and existing.get("voice_channel_id") else None
            )
            if voice_channel is None:
                voice_overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False, connect=False)}
                if role is not None:
                    voice_overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True
                    )
                try:
                    voice_channel = await guild.create_voice_channel(
                        name=f"陣取り-{TEAM_LABELS[i]}-VC",
                        category=category,
                        overwrites=voice_overwrites,
                        reason="陣取りゲーム チームボイスチャンネル自動作成",
                    )
                except discord.Forbidden:
                    logger.warning(f"territory: チームVC作成失敗（権限不足） guild={guild.id} team={i}")
                    voice_channel = None
            elif role is not None:
                try:
                    await voice_channel.set_permissions(guild.default_role, view_channel=False, connect=False)
                    await voice_channel.set_permissions(role, view_channel=True, connect=True, speak=True)
                except discord.Forbidden:
                    logger.warning(f"territory: チームVC権限更新失敗（権限不足） guild={guild.id} team={i}")

            if role is not None or channel is not None or voice_channel is not None:
                await db_manager.save_territory_team_role(
                    guild.id, i,
                    role_id=role.id if role else None,
                    channel_id=channel.id if channel else None,
                    voice_channel_id=voice_channel.id if voice_channel else None,
                )

            team_roles.append(role)
            team_channels.append(channel)
            team_voice_channels.append(voice_channel)

        all_team_role_ids = {r.id for r in team_roles if r is not None}

        for i, members_in_team in enumerate(teams):
            role = team_roles[i]
            if role is None:
                continue
            for md in members_in_team:
                member = guild.get_member(md["user_id"])
                if member is None:
                    continue
                stale = [r for r in member.roles if r.id in all_team_role_ids and r.id != role.id]
                try:
                    if stale:
                        await member.remove_roles(*stale, reason="陣取りゲーム 再抽選によるチーム変更")
                    if role not in member.roles:
                        await member.add_roles(role, reason="陣取りゲーム チーム分け")
                except discord.Forbidden:
                    logger.warning(f"territory: チームロール付け替え失敗（権限不足） user={member.id}")

        return team_roles, team_channels, team_voice_channels

    # ── プロフィール登録 ──────────────────────────────────────────

    @app_commands.command(
        name="territory_register",
        description="陣取りゲーム用のプロフィールを登録・更新します"
    )
    @app_commands.describe(
        strength="自己申告の強さ",
        ip="IP対応可否や接続情報",
        autopunch="オートパンチの有無",
        giu="giuroll(遅延判定)の有無",
        comment="一言コメント（任意）",
    )
    @app_commands.choices(
        strength=[
            app_commands.Choice(name="初級者", value=1),
            app_commands.Choice(name="中級者", value=2),
            app_commands.Choice(name="上級者", value=3),
        ],
        autopunch=[
            app_commands.Choice(name="あり", value="あり"),
            app_commands.Choice(name="なし", value="なし"),
        ],
        giu=[
            app_commands.Choice(name="あり", value="あり"),
            app_commands.Choice(name="なし", value="なし"),
        ],
    )
    async def territory_register(
        self,
        interaction: discord.Interaction,
        strength: app_commands.Choice[int],
        ip: str,
        autopunch: app_commands.Choice[str],
        giu: app_commands.Choice[str],
        comment: str = None,
    ):
        ip_clean = ip.strip()
        comment_clean = (comment or "").strip()

        await db_manager.save_territory_profile(
            user_id=interaction.user.id,
            username=interaction.user.display_name,
            strength=strength.value,
            ip_info=ip_clean,
            autopunch=autopunch.value,
            giuroll=giu.value,
            comment=comment_clean,
        )

        embed = _build_register_confirmation_embed(
            strength.value, ip_clean, autopunch.value, giu.value, comment_clean
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await self._grant_participant_role(interaction.user)

    @app_commands.command(
        name="setup_territory_register_panel",
        description="陣取りゲームのプロフィール登録ボタンをこのチャンネルに設置します（管理者用）"
    )
    @app_commands.describe(channel="設置するチャンネル（スレッドも指定可）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_territory_register_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | discord.Thread
    ):
        embed = discord.Embed(
            title="🗺️ 陣取りゲーム プロフィール登録",
            description="下のボタンから強さ・接続情報などを登録/変更できます。",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        try:
            await channel.send(embed=embed, view=TerritoryRegisterPanelView(self))
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {channel.mention} にメッセージを送信する権限がありません。", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ プロフィール登録ボタンを {channel.mention} に設置しました。", ephemeral=True
        )
        logger.info(f"setup_territory_register_panel: guild={interaction.guild_id} channel={channel.id}")

    # ── 情報パネル（プロフィール確認・一覧・チーム分け） ────────────

    @app_commands.command(
        name="setup_territory_info_panel",
        description="陣取りゲームの情報確認パネル（プロフィール・登録者一覧・チーム分け）をこのチャンネルに設置します（管理者用）"
    )
    @app_commands.describe(channel="設置するチャンネル（スレッドも指定可）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_territory_info_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | discord.Thread
    ):
        embed = discord.Embed(
            title="🗺️ 陣取りゲーム 情報パネル",
            description=(
                "・👤 自分のプロフィール確認\n"
                "・📋 登録者一覧\n"
                "・🗂️ チーム分け結果"
            ),
            color=discord.Color.from_rgb(52, 152, 219),
        )
        try:
            await channel.send(embed=embed, view=TerritoryInfoPanelView(self))
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {channel.mention} にメッセージを送信する権限がありません。", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ 情報パネルを {channel.mention} に設置しました。", ephemeral=True
        )
        logger.info(f"setup_territory_info_panel: guild={interaction.guild_id} channel={channel.id}")

    async def _build_profile_embed(self, target: discord.Member) -> discord.Embed | None:
        profile = await db_manager.get_territory_profile(target.id)
        if profile is None:
            return None

        embed = discord.Embed(
            title=f"🗺️ {target.display_name} さんの陣取りプロフィール",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        embed.add_field(
            name="強さ", value=STRENGTH_LABELS.get(profile["strength"], "不明"), inline=True
        )
        embed.add_field(name="IP/接続情報", value=profile["ip_info"] or "未設定", inline=True)
        embed.add_field(name="オートパンチ", value=profile["autopunch"] or "未設定", inline=True)
        embed.add_field(name="giuroll", value=profile["giuroll"] or "未設定", inline=True)
        embed.add_field(name="一言", value=profile["comment"] or "なし", inline=False)
        return embed

    @app_commands.command(
        name="territory_profile",
        description="陣取りゲームのプロフィールを確認します"
    )
    @app_commands.describe(user="確認したいユーザー（省略時は自分）")
    async def territory_profile(
        self, interaction: discord.Interaction, user: discord.Member = None
    ):
        target = user or interaction.user
        embed = await self._build_profile_embed(target)
        if embed is None:
            await interaction.response.send_message(
                f"❌ {target.display_name} さんはまだ陣取りゲームのプロフィールを登録していません。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _build_list_embed(self) -> discord.Embed | None:
        profiles = await db_manager.get_all_territory_profiles()
        if not profiles:
            return None

        embed = discord.Embed(
            title="🗺️ 陣取りゲーム 登録者一覧",
            description=f"登録者数: {len(profiles)}人",
            color=discord.Color.from_rgb(52, 152, 219),
        )

        # 強さ別(上級者→初級者の順)にまとめて表示
        for level in (3, 2, 1):
            label = STRENGTH_LABELS[level]
            members = [p["username"] for p in profiles if p["strength"] == level]
            if members:
                embed.add_field(
                    name=f"{label}（{len(members)}人）",
                    value="\n".join(members),
                    inline=False,
                )
        return embed

    @app_commands.command(
        name="territory_list",
        description="陣取りゲームに登録済みの全プロフィールを一覧表示します"
    )
    async def territory_list(self, interaction: discord.Interaction):
        embed = await self._build_list_embed()
        if embed is None:
            await interaction.response.send_message(
                "まだ誰も登録していません。", ephemeral=True
            )
            return
        await interaction.response.send_message(embed=embed)

    # ── チーム抽選 ────────────────────────────────────────────────

    @app_commands.command(
        name="territory_draw",
        description="陣取りゲームのチーム分け抽選を行います（管理者用）"
    )
    @app_commands.describe(
        team_count="チーム数",
        role="参加者を示すロール（省略時は `/territory_register` で自動付与される参加者ロールを使用）",
        category="チームチャンネルを作成するカテゴリ（省略時は前回指定したカテゴリ、なければカテゴリなし）",
    )
    @app_commands.choices(
        team_count=[
            app_commands.Choice(name="2チーム", value=2),
            app_commands.Choice(name="4チーム", value=4),
        ]
    )
    @app_commands.default_permissions(manage_guild=True)
    async def territory_draw(
        self,
        interaction: discord.Interaction,
        team_count: app_commands.Choice[int],
        role: discord.Role = None,
        category: discord.CategoryChannel = None,
    ):
        guild = interaction.guild
        settings = await db_manager.get_territory_settings(interaction.guild_id) or {}

        target_role = role
        if target_role is None:
            participant_role_id = settings.get("participant_role_id")
            target_role = guild.get_role(participant_role_id) if participant_role_id else None

        if target_role is None:
            await interaction.response.send_message(
                "❌ 参加者ロールが見つかりません。`role` を指定するか、参加者に先に "
                "`/territory_register` を実行してもらってください。",
                ephemeral=True,
            )
            return

        if category is not None:
            await db_manager.save_territory_settings(interaction.guild_id, team_category_id=category.id)
            target_category = category
        else:
            cat_id = settings.get("team_category_id")
            target_category = guild.get_channel(cat_id) if cat_id else None

        n_teams = team_count.value
        candidates = [m for m in target_role.members if not m.bot]

        profiles = {}
        missing = []
        for m in candidates:
            p = await db_manager.get_territory_profile(m.id)
            if p is None:
                missing.append(m)
            else:
                profiles[m.id] = p

        participants = [m for m in candidates if m.id in profiles]

        if len(participants) < n_teams:
            await interaction.response.send_message(
                f"❌ {target_role.mention} の登録済み参加者が{n_teams}人未満です（現在{len(participants)}人）。",
                ephemeral=True,
            )
            return

        captain_pool = [m for m in participants if profiles[m.id]["strength"] == 3]
        if len(captain_pool) < n_teams:
            await interaction.response.send_message(
                f"❌ 大将候補（上級者）が{n_teams}人未満です（現在{len(captain_pool)}人）。"
                "上級者の登録者を増やしてから再度実行してください。",
                ephemeral=True,
            )
            return

        random.shuffle(captain_pool)
        captains = captain_pool[:n_teams]
        captain_ids = {c.id for c in captains}

        remaining = [m for m in participants if m.id not in captain_ids]
        random.shuffle(remaining)
        remaining.sort(key=lambda m: profiles[m.id]["strength"], reverse=True)

        teams = [[] for _ in range(n_teams)]
        team_totals = [0] * n_teams
        team_counts = [0] * n_teams

        for i, c in enumerate(captains):
            teams[i].append({"user_id": c.id, "username": c.display_name, "strength": 5, "is_captain": True})
            team_totals[i] += 5
            team_counts[i] += 1

        for m in remaining:
            s = profiles[m.id]["strength"]
            idx = min(range(n_teams), key=lambda i: (team_totals[i], team_counts[i]))
            teams[idx].append({"user_id": m.id, "username": m.display_name, "strength": s, "is_captain": False})
            team_totals[idx] += s
            team_counts[idx] += 1

        await db_manager.clear_territory_teams(interaction.guild_id)
        for i, members_in_team in enumerate(teams):
            for md in members_in_team:
                await db_manager.add_territory_team_member(
                    guild_id=interaction.guild_id,
                    team_index=i,
                    user_id=md["user_id"],
                    username=md["username"],
                    strength=md["strength"],
                    is_captain=md["is_captain"],
                )

        await db_manager.init_territory_grid(interaction.guild_id, n_teams)

        await interaction.response.defer()

        team_roles, team_channels, team_voice_channels = await self._sync_team_roles_and_channels(
            guild, teams, target_category
        )
        channel_map = {i: ch for i, ch in enumerate(team_channels) if ch is not None}
        voice_map = {i: ch for i, ch in enumerate(team_voice_channels) if ch is not None}

        embed = _build_teams_embed(teams, channel_map, voice_map)
        if missing:
            names = "、".join(m.display_name for m in missing)
            embed.set_footer(text=f"未登録のため除外: {names}")

        await interaction.followup.send(embed=embed)
        logger.info(
            f"territory_draw: guild={interaction.guild_id} teams={n_teams} "
            f"participants={len(participants)} captains={[c.id for c in captains]}"
        )

    async def _build_current_teams_embed(self, guild_id: int) -> discord.Embed | None:
        rows = await db_manager.get_territory_teams(guild_id)
        if not rows:
            return None

        n_teams = max(r["team_index"] for r in rows) + 1
        teams = [[] for _ in range(n_teams)]
        for r in rows:
            teams[r["team_index"]].append({
                "user_id": r["user_id"],
                "username": r["username"],
                "strength": r["strength"],
                "is_captain": bool(r["is_captain"]),
            })

        channel_map = {}
        voice_map = {}
        guild = self.bot.get_guild(guild_id)
        if guild is not None:
            for tr in await db_manager.get_territory_team_roles(guild_id):
                ch = guild.get_channel(tr["channel_id"]) if tr.get("channel_id") else None
                if ch is not None:
                    channel_map[tr["team_index"]] = ch
                vc = guild.get_channel(tr["voice_channel_id"]) if tr.get("voice_channel_id") else None
                if vc is not None:
                    voice_map[tr["team_index"]] = vc

        return _build_teams_embed(teams, channel_map, voice_map)

    @app_commands.command(
        name="territory_teams",
        description="陣取りゲームの現在のチーム分け結果を表示します"
    )
    async def territory_teams(self, interaction: discord.Interaction):
        embed = await self._build_current_teams_embed(interaction.guild_id)
        if embed is None:
            await interaction.response.send_message(
                "まだチーム分けが行われていません。管理者に `/territory_draw` の実行を依頼してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed)

    # ── 陣地マップ ────────────────────────────────────────────────

    async def _build_grid_embed(self, guild_id: int) -> discord.Embed | None:
        grid = await db_manager.get_territory_grid(guild_id)
        if not grid:
            return None

        owner_map = {g["cell_index"]: g["team_index"] for g in grid}
        n_teams = max(owner_map.values()) + 1

        rows_lines = [
            " ".join(TEAM_EMOJIS[owner_map[r * 5 + c]] for c in range(5))
            for r in range(5)
        ]

        counts = [0] * n_teams
        for v in owner_map.values():
            counts[v] += 1

        embed = discord.Embed(
            title="🗺️ 陣取りゲーム 陣地マップ (5×5)",
            description="\n".join(rows_lines),
            color=discord.Color.from_rgb(52, 152, 219),
        )
        embed.set_footer(
            text=" / ".join(f"{TEAM_LABELS[i]} {counts[i]}マス" for i in range(n_teams))
        )
        return embed

    async def _expand_territory(
        self, interaction: discord.Interaction, guild_id: int, team_index: int, invasion_score: int
    ):
        grid = await db_manager.get_territory_grid(guild_id)
        if not grid:
            return  # マップ未初期化（旧チーム分けなど）の場合は何もしない

        owner_map = {g["cell_index"]: g["team_index"] for g in grid}
        frontier = _compute_frontier(owner_map, team_index)

        if not frontier:
            await interaction.followup.send(
                f"🗺️ {TEAM_LABELS[team_index]} はこれ以上隣接する陣地がないため、拡張できませんでした。"
            )
            return

        if len(frontier) <= invasion_score:
            for idx in frontier:
                await db_manager.set_territory_grid_cell(guild_id, idx, team_index)
            embed = await self._build_grid_embed(guild_id)
            await interaction.followup.send(
                content=f"🗺️ {TEAM_LABELS[team_index]} が侵略度{invasion_score}分の隣接陣地を全て獲得しました！",
                embed=embed,
            )
            return

        view = TerritoryExpansionView(self, guild_id, team_index, owner_map, frontier, invasion_score)
        embed = await self._build_grid_embed(guild_id)
        msg = await interaction.followup.send(
            content=(
                f"🗺️ {TEAM_LABELS[team_index]} は侵略度{invasion_score}分、"
                f"下のボタンから塗り替えるマスを{invasion_score}個選んでください。"
            ),
            embed=embed,
            view=view,
        )
        view.message = msg

    @app_commands.command(
        name="territory_map",
        description="陣取りゲームの現在の陣地マップを表示します"
    )
    async def territory_map(self, interaction: discord.Interaction):
        embed = await self._build_grid_embed(interaction.guild_id)
        if embed is None:
            await interaction.response.send_message(
                "まだ陣地マップが初期化されていません。管理者に `/territory_draw` の実施を依頼してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed)

    # ── 対戦報告・戦況・削除 ──────────────────────────────────────

    async def _build_score_embed(self, guild_id: int) -> discord.Embed | None:
        rows = await db_manager.get_territory_teams(guild_id)
        if not rows:
            return None

        n_teams = max(r["team_index"] for r in rows) + 1
        totals = await db_manager.get_territory_invasion_totals(guild_id)
        fought = await db_manager.get_territory_fought_user_ids(guild_id)

        teams_members = [[] for _ in range(n_teams)]
        for r in rows:
            teams_members[r["team_index"]].append(r)

        embed = discord.Embed(
            title="⚔️ 陣取りゲーム 現在の戦況",
            color=discord.Color.from_rgb(230, 126, 34),
        )
        for i, members in enumerate(teams_members):
            score = totals.get(i, 0)
            remaining = [m["username"] for m in members if m["user_id"] not in fought]
            done = len(members) - len(remaining)
            value = f"侵略度合計: **{score}**\n出場済み: {done}/{len(members)}人"
            if remaining:
                value += f"\n未出場: {', '.join(remaining)}"
            embed.add_field(name=TEAM_LABELS[i], value=value, inline=False)
        return embed

    async def _process_territory_report(
        self, guild_id: int, reporter: discord.Member, opponent: discord.Member, result_value: str
    ) -> dict:
        """対戦結果の検証・侵略度計算・DB登録を行い、結果を辞書で返す（Discord応答は呼び出し元が行う）"""
        if opponent.id == reporter.id:
            return {"ok": False, "error": "❌ 自分自身を対戦相手に指定できません。"}

        reporter_team = await db_manager.get_territory_team_of_user(guild_id, reporter.id)
        opponent_team = await db_manager.get_territory_team_of_user(guild_id, opponent.id)

        if reporter_team is None or opponent_team is None:
            return {
                "ok": False,
                "error": "❌ 両者ともチーム分け済みである必要があります。`/territory_draw` の実施後に対戦してください。",
            }

        if reporter_team["team_index"] == opponent_team["team_index"]:
            return {"ok": False, "error": "❌ 同じチームのメンバー同士は対戦できません。"}

        fought = await db_manager.get_territory_fought_user_ids(guild_id)
        if reporter.id in fought:
            return {"ok": False, "error": "❌ あなたはすでに出場済みです（1人1回までの出場です）。"}
        if opponent.id in fought:
            return {
                "ok": False,
                "error": f"❌ {opponent.display_name} さんはすでに出場済みです（1人1回までの出場です）。",
            }

        if result_value == "win":
            winner, loser = reporter, opponent
            winner_team, loser_team = reporter_team, opponent_team
        else:
            winner, loser = opponent, reporter
            winner_team, loser_team = opponent_team, reporter_team

        winner_strength = winner_team["strength"]
        loser_strength = loser_team["strength"]
        base = loser_strength
        bonus = max(0, loser_strength - winner_strength)
        captain_defeated = bool(loser_team["is_captain"])
        invasion = base + bonus + (2 if captain_defeated else 0)

        match_id = await db_manager.add_territory_match(
            guild_id=guild_id,
            reporter_id=reporter.id,
            winner_id=winner.id,
            loser_id=loser.id,
            winner_team=winner_team["team_index"],
            loser_team=loser_team["team_index"],
            invasion_score=invasion,
            captain_defeated=captain_defeated,
        )

        bonus_parts = [f"基礎点 {base}"]
        if bonus > 0:
            bonus_parts.append(f"下剋上ボーナス +{bonus}")
        if captain_defeated:
            bonus_parts.append("大将撃破ボーナス +2")

        embed = discord.Embed(
            title="⚔️ 陣取りゲーム 対戦結果",
            description=f"{TEAM_LABELS[winner_team['team_index']]} **{winner.display_name}** の勝利！\n"
                        f"**Match ID:** `{match_id}`",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.add_field(
            name=f"勝者: {winner.display_name} ({TEAM_LABELS[winner_team['team_index']]})",
            value=_strength_label(winner_team),
            inline=True,
        )
        loser_value = _strength_label(loser_team) + (" 👑撃破" if captain_defeated else "")
        embed.add_field(
            name=f"敗者: {loser.display_name} ({TEAM_LABELS[loser_team['team_index']]})",
            value=loser_value,
            inline=True,
        )
        embed.add_field(
            name="侵略度",
            value=f"**{invasion}** ({' + '.join(bonus_parts)})",
            inline=False,
        )
        embed.set_footer(
            text=f"報告者: {reporter.display_name} | 間違えた場合は /territory_match_delete で削除できます"
        )

        logger.info(
            f"territory_report: guild={guild_id} match={match_id} winner={winner.id} loser={loser.id} "
            f"invasion={invasion} captain_defeated={captain_defeated}"
        )

        return {
            "ok": True,
            "embed": embed,
            "winner_team_index": winner_team["team_index"],
            "invasion": invasion,
            "fought_before": fought,
            "winner_id": winner.id,
            "loser_id": loser.id,
        }

    async def _check_game_finished(
        self, interaction: discord.Interaction, guild_id: int, fought_before: set, winner_id: int, loser_id: int
    ):
        all_rows = await db_manager.get_territory_teams(guild_id)
        new_fought = fought_before | {winner_id, loser_id}
        if len(new_fought) < len(all_rows):
            return

        totals = await db_manager.get_territory_invasion_totals(guild_id)
        n_teams = max(r["team_index"] for r in all_rows) + 1
        lines = [f"{TEAM_LABELS[i]}: 侵略度 **{totals.get(i, 0)}**" for i in range(n_teams)]
        best_score = max(totals.get(i, 0) for i in range(n_teams))
        winners = [TEAM_LABELS[i] for i in range(n_teams) if totals.get(i, 0) == best_score]
        final_embed = discord.Embed(
            title="🏁 全員出場完了！陣取りゲーム終了",
            description="\n".join(lines) + f"\n\n🏆 勝利チーム: **{'・'.join(winners)}**",
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=final_embed)
        logger.info(f"territory_game_finished: guild={guild_id} winners={winners}")

    @app_commands.command(
        name="territory_report",
        description="陣取りゲームの1対1対戦結果を登録します"
    )
    @app_commands.describe(
        opponent="対戦相手",
        result="自分から見た結果",
    )
    @app_commands.choices(
        result=[
            app_commands.Choice(name="勝ち", value="win"),
            app_commands.Choice(name="負け", value="lose"),
        ]
    )
    async def territory_report(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        result: app_commands.Choice[str],
    ):
        guild_id = interaction.guild_id
        outcome = await self._process_territory_report(guild_id, interaction.user, opponent, result.value)

        if not outcome["ok"]:
            await interaction.response.send_message(outcome["error"], ephemeral=True)
            return

        await interaction.response.send_message(embed=outcome["embed"])
        await self._expand_territory(interaction, guild_id, outcome["winner_team_index"], outcome["invasion"])
        await self._check_game_finished(
            interaction, guild_id, outcome["fought_before"], outcome["winner_id"], outcome["loser_id"]
        )

    @app_commands.command(
        name="territory_score",
        description="陣取りゲームの現在の戦況（侵略度・出場状況）を表示します"
    )
    async def territory_score(self, interaction: discord.Interaction):
        embed = await self._build_score_embed(interaction.guild_id)
        if embed is None:
            await interaction.response.send_message(
                "まだチーム分けが行われていません。管理者に `/territory_draw` の実施を依頼してください。",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=embed)

    async def _process_match_delete(self, interaction: discord.Interaction, match_id: int):
        match_data = await db_manager.get_territory_match(match_id)
        if not match_data:
            await interaction.response.send_message(
                f"❌ 対戦ID `{match_id}` の記録が見つかりませんでした。", ephemeral=True
            )
            return

        is_reporter = match_data["reporter_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.administrator
        if not (is_reporter or is_admin):
            await interaction.response.send_message(
                "❌ この記録を削除する権限がありません（報告者本人または管理者のみ削除可能です）。",
                ephemeral=True,
            )
            return

        await db_manager.delete_territory_match(match_id)
        await interaction.response.send_message(
            f"🗑️ 対戦ID `{match_id}` の記録を削除しました。該当メンバーは再度出場可能になります。"
        )
        logger.info(f"territory_match_delete: match={match_id} by user={interaction.user.id}")

    @app_commands.command(
        name="territory_match_delete",
        description="間違えて登録した陣取りゲームの対戦結果をID指定で削除します"
    )
    @app_commands.describe(match_id="削除する対戦のID")
    async def territory_match_delete(self, interaction: discord.Interaction, match_id: int):
        await self._process_match_delete(interaction, match_id)

    # ── 対戦パネル（報告・戦況・削除・マップ） ────────────────────

    @app_commands.command(
        name="setup_territory_battle_panel",
        description="陣取りゲームの対戦パネル（結果報告・戦況・削除・マップ）をこのチャンネルに設置します（管理者用）"
    )
    @app_commands.describe(channel="設置するチャンネル（スレッドも指定可）")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_territory_battle_panel(
        self, interaction: discord.Interaction, channel: discord.TextChannel | discord.Thread
    ):
        embed = discord.Embed(
            title="⚔️ 陣取りゲーム 対戦パネル",
            description=(
                "・⚔️ 対戦結果を報告\n"
                "・📊 現在の戦況\n"
                "・🗑️ 対戦結果を削除\n"
                "・🗺️ 陣地マップ"
            ),
            color=discord.Color.from_rgb(230, 126, 34),
        )
        try:
            await channel.send(embed=embed, view=TerritoryBattlePanelView(self))
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {channel.mention} にメッセージを送信する権限がありません。", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ 対戦パネルを {channel.mention} に設置しました。", ephemeral=True
        )
        logger.info(f"setup_territory_battle_panel: guild={interaction.guild_id} channel={channel.id}")

    # ── 一括セットアップ ──────────────────────────────────────────

    @app_commands.command(
        name="territory_setup",
        description="陣取りゲームの初期セットアップ（ロール・チャンネル・全パネル）を一括で行います（管理者用）"
    )
    @app_commands.describe(category="使用するカテゴリ（省略時は新規作成）")
    @app_commands.default_permissions(manage_guild=True)
    async def territory_setup(
        self, interaction: discord.Interaction, category: discord.CategoryChannel = None
    ):
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True)

        if category is None:
            try:
                category = await guild.create_category(
                    "陣取りゲーム", reason="陣取りゲーム 初期セットアップ"
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "❌ カテゴリを作成する権限がありません。", ephemeral=True
                )
                return

        await db_manager.save_territory_settings(guild.id, team_category_id=category.id)

        role = await self._ensure_participant_role(guild)
        if role is None:
            await interaction.followup.send(
                "❌ 参加者ロールを作成する権限がありません。", ephemeral=True
            )
            return

        participant_channel = await self._ensure_participant_channel(guild, role, category=category)
        participant_voice_channel = await self._ensure_participant_voice_channel(guild, role, category=category)

        try:
            reception_channel = await guild.create_text_channel(
                name="陣取り-受付", category=category, reason="陣取りゲーム 初期セットアップ"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ チャンネルを作成する権限がありません。", ephemeral=True
            )
            return

        register_embed = discord.Embed(
            title="🗺️ 陣取りゲーム プロフィール登録",
            description="下のボタンから強さ・接続情報などを登録/変更できます。",
            color=discord.Color.from_rgb(52, 152, 219),
        )
        await reception_channel.send(embed=register_embed, view=TerritoryRegisterPanelView(self))

        info_embed = discord.Embed(
            title="🗺️ 陣取りゲーム 情報パネル",
            description=(
                "・👤 自分のプロフィール確認\n"
                "・📋 登録者一覧\n"
                "・🗂️ チーム分け結果"
            ),
            color=discord.Color.from_rgb(52, 152, 219),
        )
        await reception_channel.send(embed=info_embed, view=TerritoryInfoPanelView(self))

        hq_channel = await guild.create_text_channel(
            name="陣取り-本部", category=category, reason="陣取りゲーム 初期セットアップ"
        )
        battle_embed = discord.Embed(
            title="⚔️ 陣取りゲーム 対戦パネル",
            description=(
                "・⚔️ 対戦結果を報告\n"
                "・📊 現在の戦況\n"
                "・🗑️ 対戦結果を削除\n"
                "・🗺️ 陣地マップ"
            ),
            color=discord.Color.from_rgb(230, 126, 34),
        )
        await hq_channel.send(embed=battle_embed, view=TerritoryBattlePanelView(self))

        summary = discord.Embed(
            title="✅ 陣取りゲーム 初期セットアップ完了",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        summary.add_field(name="カテゴリ", value=category.name, inline=False)
        summary.add_field(name="受付チャンネル", value=reception_channel.mention, inline=True)
        summary.add_field(name="本部チャンネル", value=hq_channel.mention, inline=True)
        if participant_channel:
            summary.add_field(name="参加者雑談チャンネル", value=participant_channel.mention, inline=True)
        if participant_voice_channel:
            summary.add_field(name="参加者VC", value=participant_voice_channel.mention, inline=True)
        summary.add_field(name="参加者ロール", value=role.mention, inline=True)
        summary.set_footer(
            text="チーム分け(/territory_draw)を実行すると、チームごとのロール・チャンネル・VCも自動作成されます。"
        )

        await interaction.followup.send(embed=summary, ephemeral=True)
        logger.info(f"territory_setup: guild={guild.id} category={category.id}")

    # ── お片付け（大会終了時のクリーンアップ） ────────────────────

    async def _resolve_role(self, guild: discord.Guild, role_id: int | None) -> discord.Role | None:
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

    async def _resolve_channel(self, guild: discord.Guild, channel_id: int | None):
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

    async def _execute_territory_cleanup(self, guild: discord.Guild, team_role_rows: list) -> discord.Embed:
        deleted_roles = 0
        deleted_channels = 0
        deleted_voice = 0
        unassigned_members = 0
        errors = []

        for tr in team_role_rows:
            role = await self._resolve_role(guild, tr.get("role_id"))
            if role is not None:
                try:
                    await role.delete(reason="陣取りゲーム 大会終了によるお片付け")
                    deleted_roles += 1
                except discord.Forbidden:
                    errors.append(f"ロール {role.name} の削除に失敗（権限不足）")

            channel = await self._resolve_channel(guild, tr.get("channel_id"))
            if channel is not None:
                try:
                    await channel.delete(reason="陣取りゲーム 大会終了によるお片付け")
                    deleted_channels += 1
                except discord.Forbidden:
                    errors.append(f"チャンネル {channel.name} の削除に失敗（権限不足）")

            voice = await self._resolve_channel(guild, tr.get("voice_channel_id"))
            if voice is not None:
                try:
                    await voice.delete(reason="陣取りゲーム 大会終了によるお片付け")
                    deleted_voice += 1
                except discord.Forbidden:
                    errors.append(f"VC {voice.name} の削除に失敗（権限不足）")

        settings = await db_manager.get_territory_settings(guild.id) or {}

        # 参加者ロールは残し、現在のメンバーから外すだけ
        participant_role = await self._resolve_role(guild, settings.get("participant_role_id"))
        if participant_role is not None:
            for member in list(participant_role.members):
                try:
                    await member.remove_roles(participant_role, reason="陣取りゲーム 大会終了によるお片付け")
                    unassigned_members += 1
                except discord.Forbidden:
                    errors.append(f"{member.display_name} からの参加者ロール解除に失敗（権限不足）")

        # 全体雑談ch・VCは削除する
        participant_channel = await self._resolve_channel(guild, settings.get("participant_channel_id"))
        if participant_channel is not None:
            try:
                await participant_channel.delete(reason="陣取りゲーム 大会終了によるお片付け")
                deleted_channels += 1
            except discord.Forbidden:
                errors.append(f"チャンネル {participant_channel.name} の削除に失敗（権限不足）")

        participant_voice = await self._resolve_channel(guild, settings.get("participant_voice_channel_id"))
        if participant_voice is not None:
            try:
                await participant_voice.delete(reason="陣取りゲーム 大会終了によるお片付け")
                deleted_voice += 1
            except discord.Forbidden:
                errors.append(f"VC {participant_voice.name} の削除に失敗（権限不足）")

        await db_manager.clear_territory_participant_channels(guild.id)
        await db_manager.clear_territory_team_roles(guild.id)
        await db_manager.clear_territory_teams(guild.id)
        await db_manager.clear_territory_matches(guild.id)
        await db_manager.clear_territory_grid(guild.id)
        await db_manager.clear_all_territory_profiles()

        embed = discord.Embed(
            title="🧹 陣取りゲーム お片付け完了",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.add_field(name="削除したロール", value=str(deleted_roles), inline=True)
        embed.add_field(name="削除したチャンネル", value=str(deleted_channels), inline=True)
        embed.add_field(name="削除したVC", value=str(deleted_voice), inline=True)
        embed.add_field(name="参加者ロールを外した人数", value=str(unassigned_members), inline=True)
        embed.add_field(
            name="リセットしたデータ",
            value="登録プロフィール・チーム分け・対戦履歴・陣地マップ",
            inline=False,
        )
        if errors:
            embed.add_field(name="⚠️ 一部失敗", value="\n".join(errors)[:1024], inline=False)
        embed.set_footer(text="参加者ロール自体は維持されています（次回はメンバーへの再付与のみで使えます）")

        logger.info(
            f"territory_cleanup: guild={guild.id} roles={deleted_roles} channels={deleted_channels} "
            f"voice={deleted_voice} unassigned={unassigned_members} errors={len(errors)}"
        )
        return embed

    @app_commands.command(
        name="territory_cleanup",
        description="陣取りゲーム終了後のお片付け（チームロール・チャンネル削除+データリセット）を行います（管理者用）"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def territory_cleanup(self, interaction: discord.Interaction):
        guild = interaction.guild
        team_role_rows = await db_manager.get_territory_team_roles(interaction.guild_id)
        settings = await db_manager.get_territory_settings(interaction.guild_id) or {}

        participant_role = await self._resolve_role(guild, settings.get("participant_role_id"))
        participant_channel = await self._resolve_channel(guild, settings.get("participant_channel_id"))
        participant_voice = await self._resolve_channel(guild, settings.get("participant_voice_channel_id"))

        if not team_role_rows and participant_role is None and participant_channel is None and participant_voice is None:
            await interaction.response.send_message(
                "削除対象のロール・チャンネルが見つかりませんでした。", ephemeral=True
            )
            return

        lines = []
        for tr in team_role_rows:
            role = await self._resolve_role(guild, tr.get("role_id"))
            channel = await self._resolve_channel(guild, tr.get("channel_id"))
            voice = await self._resolve_channel(guild, tr.get("voice_channel_id"))
            parts = [p for p in (
                role.mention if role else None,
                channel.mention if channel else None,
                f"🔊{voice.mention}" if voice else None,
            ) if p]
            label = TEAM_LABELS[tr["team_index"]] if tr["team_index"] < len(TEAM_LABELS) else f"チーム{tr['team_index']}"
            lines.append(f"{label}: " + (" / ".join(parts) if parts else "(すでに存在しません)"))

        embed = discord.Embed(
            title="⚠️ 陣取りゲーム お片付け確認",
            description=(
                "以下のチームロール・チャンネル・VCを削除し、登録プロフィール・チーム分け・"
                "対戦履歴・陣地マップをリセットします。\n"
                "**この操作は取り消せません。**\n\n"
                "参加者ロールは残し、現在のメンバーから外すだけです（全体雑談ch・VCは削除します）。"
            ),
            color=discord.Color.from_rgb(230, 126, 34),
        )
        embed.add_field(name="削除対象（チーム）", value="\n".join(lines) if lines else "なし", inline=False)

        participant_parts = [p for p in (
            f"{participant_role.mention}（メンバーから解除）" if participant_role else None,
            participant_channel.mention if participant_channel else None,
            f"🔊{participant_voice.mention}" if participant_voice else None,
        ) if p]
        embed.add_field(
            name="参加者関連",
            value="\n".join(participant_parts) if participant_parts else "なし",
            inline=False,
        )

        view = TerritoryCleanupConfirmView(self, interaction.user.id, team_role_rows)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()


async def setup(bot):
    await bot.add_cog(TerritoryCog(bot))
