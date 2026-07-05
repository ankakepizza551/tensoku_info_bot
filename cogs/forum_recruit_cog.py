import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager
from cogs.report_cog import CHARACTERS

logger = logging.getLogger("TensokuMatchBot")


# ─────────────────────────────────────────────
#  ユーティリティ
# ─────────────────────────────────────────────

def find_character(input_name: str):
    if not input_name:
        return None
    s = input_name.strip()
    if not s:
        return None
    for char in CHARACTERS:
        if s in char or char in s:
            return char
    return None


async def _build_stats_embed(user: discord.Member) -> discord.Embed:
    user_info = await db_manager.get_or_create_user(user.id, user.display_name)
    rating = round(user_info["rating"], 1)
    stats = await db_manager.get_user_stats(user.id)

    embed = discord.Embed(
        title=f"📊 {user.display_name} のスタッツ",
        color=discord.Color.from_rgb(149, 117, 205),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="レート", value=f"`{rating}`", inline=True)

    total = stats["total_matches"]
    if total > 0:
        embed.add_field(
            name="通算成績",
            value=f"{stats['wins']}勝 {stats['losses']}敗 ({total}試合)",
            inline=True,
        )
        embed.add_field(name="勝率", value=f"`{stats['win_rate']}%`", inline=True)
        if stats["recent_history"]:
            lines = []
            for h in stats["recent_history"]:
                icon = "✅" if h["is_win"] else "❌"
                lines.append(
                    f"{icon} vs {h['opponent_name']} `{h['my_score']}-{h['opponent_score']}`"
                )
            embed.add_field(name="直近の対戦", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="通算成績", value="対戦記録なし", inline=False)

    return embed


# ─────────────────────────────────────────────
#  共通コールバック（モジュールレベル関数）
# ─────────────────────────────────────────────

async def _stats_callback(interaction: discord.Interaction):
    embed = await _build_stats_embed(interaction.user)
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _delete_callback(interaction: discord.Interaction):
    custom_id = interaction.data.get("custom_id", "")
    try:
        thread_id = int(custom_id.split(":")[1])
    except (IndexError, ValueError):
        await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)
        return

    # DB読み込みより先に応答を確定させ、3秒タイムアウトによる失敗を避ける
    await interaction.response.defer(ephemeral=True)

    thread_info = await db_manager.get_recruit_thread(thread_id)
    recruiter_id = thread_info["recruiter_id"] if thread_info else None

    is_creator = interaction.user.id == recruiter_id
    has_manage = interaction.user.guild_permissions.manage_threads

    if not is_creator and not has_manage:
        await interaction.followup.send(
            "❌ スレッド作成者またはモデレーターのみ削除できます。", ephemeral=True
        )
        return

    thread = interaction.channel
    if not isinstance(thread, discord.Thread):
        await interaction.followup.send("❌ スレッド内でのみ使用できます。", ephemeral=True)
        return

    try:
        if thread_info:
            await db_manager.delete_recruit_thread(thread_id)
        await thread.delete()
        logger.info(f"recruit_thread deleted: thread={thread_id} by user={interaction.user.id}")
    except discord.Forbidden:
        await interaction.followup.send("❌ スレッドを削除する権限がありません。", ephemeral=True)
    except Exception as e:
        logger.error(f"thread delete error: {e}")
        await interaction.followup.send(f"❌ 削除中にエラーが発生しました: {e}", ephemeral=True)


# ─────────────────────────────────────────────
#  対戦結果報告モーダル
# ─────────────────────────────────────────────

class ThreadMatchReportModal(discord.ui.Modal):
    def __init__(
        self,
        thread_id: int,
        recruiter: discord.Member,
        challenger: discord.Member,
        panel_message: discord.Message,
    ):
        super().__init__(title="📝 対戦結果の報告")
        self.thread_id = thread_id
        self.recruiter = recruiter
        self.challenger = challenger
        self.panel_message = panel_message

        self.my_score_input = discord.ui.TextInput(
            label="自分の勝利本数", placeholder="例: 2", min_length=1, max_length=2
        )
        self.opponent_score_input = discord.ui.TextInput(
            label="相手の勝利本数", placeholder="例: 1", min_length=1, max_length=2
        )
        self.my_char_input = discord.ui.TextInput(
            label="自分の使用キャラ（任意）",
            placeholder="例: 霊夢",
            required=False,
            max_length=20,
        )
        self.opponent_char_input = discord.ui.TextInput(
            label="相手の使用キャラ（任意）",
            placeholder="例: 魔理沙",
            required=False,
            max_length=20,
        )
        self.add_item(self.my_score_input)
        self.add_item(self.opponent_score_input)
        self.add_item(self.my_char_input)
        self.add_item(self.opponent_char_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            my_score = int(self.my_score_input.value)
            opp_score = int(self.opponent_score_input.value)
            if my_score < 0 or opp_score < 0:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message(
                "❌ スコアには0以上の整数を入力してください。", ephemeral=True
            )
            return

        reporter = interaction.user
        if reporter.id == self.recruiter.id:
            score1, score2 = my_score, opp_score
            char1_raw, char2_raw = self.my_char_input.value, self.opponent_char_input.value
        else:
            score1, score2 = opp_score, my_score
            char1_raw, char2_raw = self.opponent_char_input.value, self.my_char_input.value

        char1 = find_character(char1_raw)
        char2 = find_character(char2_raw)

        await interaction.response.defer()

        try:
            result = await db_manager.add_match(
                reporter_id=reporter.id,
                player1_id=self.recruiter.id,
                player1_name=self.recruiter.display_name,
                player2_id=self.challenger.id,
                player2_name=self.challenger.display_name,
                score1=score1,
                score2=score2,
                char1=char1,
                char2=char2,
                rated=False,
            )

            if score1 > score2:
                winner_text = f"🏆 **{self.recruiter.display_name}** の勝利！"
            elif score2 > score1:
                winner_text = f"🏆 **{self.challenger.display_name}** の勝利！"
            else:
                winner_text = "🤝 **引き分け！**"

            result_embed = discord.Embed(
                title="📊 対戦結果 (募集対戦)",
                description=f"{winner_text}\n**Match ID:** `{result['match_id']}`",
                color=discord.Color.from_rgb(46, 204, 113),
            )
            result_embed.add_field(
                name=self.recruiter.display_name,
                value=(
                    f"使用キャラ: `{char1 or '未設定'}`\n"
                    f"獲得本数: **{score1}**\n"
                    f"現在のレート: `{round(result['old_rating1'], 1)}` （フリー対戦のためレート変動なし）"
                ),
                inline=True,
            )
            result_embed.add_field(
                name=self.challenger.display_name,
                value=(
                    f"使用キャラ: `{char2 or '未設定'}`\n"
                    f"獲得本数: **{score2}**\n"
                    f"現在のレート: `{round(result['old_rating2'], 1)}` （フリー対戦のためレート変動なし）"
                ),
                inline=True,
            )

            # パネルを対戦終了状態に更新
            closed_embed = discord.Embed(
                title="✅ 対戦終了",
                description=f"{self.recruiter.mention} vs {self.challenger.mention}\n対戦が完了しました。",
                color=discord.Color.from_rgb(127, 140, 141),
            )
            completed_view = ThreadCompletedView(self.thread_id)
            await self.panel_message.edit(embed=closed_embed, view=completed_view)
            await db_manager.update_recruit_thread_status(self.thread_id, "completed")

            await interaction.followup.send(embed=result_embed)
            logger.info(
                f"thread_match_report: thread={self.thread_id} match={result['match_id']}"
            )

        except Exception as e:
            logger.error(f"ThreadMatchReportModal エラー: {e}")
            await interaction.followup.send(
                f"❌ 戦績登録中にエラーが発生しました: {e}", ephemeral=True
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"ThreadMatchReportModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)


# ─────────────────────────────────────────────
#  スレッドコントロールView群（永続）
# ─────────────────────────────────────────────

class ThreadRecruitingView(discord.ui.View):
    """募集中状態のコントロールパネル"""

    def __init__(self, thread_id: int, recruiter_id: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id
        self.recruiter_id = recruiter_id

        join_btn = discord.ui.Button(
            label="⚔️ 対戦を申し込む",
            style=discord.ButtonStyle.primary,
            custom_id=f"tr_join:{thread_id}",
        )
        join_btn.callback = self._join_callback

        stats_btn = discord.ui.Button(
            label="📊 自分のスタッツ",
            style=discord.ButtonStyle.secondary,
            custom_id=f"tr_stats:{thread_id}",
        )
        stats_btn.callback = _stats_callback

        end_btn = discord.ui.Button(
            label="🚫 募集を終了する",
            style=discord.ButtonStyle.secondary,
            custom_id=f"tr_end:{thread_id}",
        )
        end_btn.callback = self._end_callback

        delete_btn = discord.ui.Button(
            label="🗑️ スレッドを削除",
            style=discord.ButtonStyle.danger,
            custom_id=f"tr_delete:{thread_id}",
        )
        delete_btn.callback = _delete_callback

        self.add_item(join_btn)
        self.add_item(stats_btn)
        self.add_item(end_btn)
        self.add_item(delete_btn)

    async def _join_callback(self, interaction: discord.Interaction):
        if interaction.user.id == self.recruiter_id:
            await interaction.response.send_message(
                "❌ 自分自身の募集には参加できません！", ephemeral=True
            )
            return

        challenger = interaction.user
        recruiter = interaction.guild.get_member(self.recruiter_id)
        recruiter_mention = recruiter.mention if recruiter else f"<@{self.recruiter_id}>"

        in_progress_embed = discord.Embed(
            title="⚔️ 対戦中 (Match in Progress)",
            description=(
                f"{recruiter_mention} vs {challenger.mention}\n\n"
                "対戦終了後、どちらかのプレイヤーが「結果を報告する」ボタンからスコアを入力してください。"
            ),
            color=discord.Color.from_rgb(241, 196, 15),
        )
        in_progress_view = ThreadInProgressView(self.thread_id, self.recruiter_id, challenger.id)
        await interaction.response.edit_message(embed=in_progress_embed, view=in_progress_view)

        await db_manager.update_recruit_thread_status(
            self.thread_id, "in_progress", challenger_id=challenger.id
        )

        await interaction.channel.send(
            f"⚔️ 対戦開始: {recruiter_mention} vs {challenger.mention} ！\n"
            "対戦が終わったら「結果を報告する」ボタンから結果を入力してください。"
        )

    async def _end_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.recruiter_id:
            await interaction.response.send_message(
                "❌ 募集の終了は募集者本人のみ可能です。", ephemeral=True
            )
            return

        ended_embed = discord.Embed(
            title="🚫 募集終了",
            description=f"<@{self.recruiter_id}> の対戦募集は終了しました。",
            color=discord.Color.from_rgb(127, 140, 141),
        )
        completed_view = ThreadCompletedView(self.thread_id)
        await interaction.response.edit_message(embed=ended_embed, view=completed_view)
        await db_manager.update_recruit_thread_status(self.thread_id, "completed")
        logger.info(f"recruit_ended: thread={self.thread_id} by user={interaction.user.id}")


class ThreadInProgressView(discord.ui.View):
    """対戦中状態のコントロールパネル"""

    def __init__(self, thread_id: int, recruiter_id: int, challenger_id: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id
        self.recruiter_id = recruiter_id
        self.challenger_id = challenger_id

        report_btn = discord.ui.Button(
            label="📝 結果を報告する",
            style=discord.ButtonStyle.success,
            custom_id=f"tr_report:{thread_id}",
        )
        report_btn.callback = self._report_callback

        stats_btn = discord.ui.Button(
            label="📊 自分のスタッツ",
            style=discord.ButtonStyle.secondary,
            custom_id=f"tr_stats:{thread_id}",
        )
        stats_btn.callback = _stats_callback

        delete_btn = discord.ui.Button(
            label="🗑️ スレッドを削除",
            style=discord.ButtonStyle.danger,
            custom_id=f"tr_delete:{thread_id}",
        )
        delete_btn.callback = _delete_callback

        self.add_item(report_btn)
        self.add_item(stats_btn)
        self.add_item(delete_btn)

    async def _report_callback(self, interaction: discord.Interaction):
        if interaction.user.id not in [self.recruiter_id, self.challenger_id]:
            await interaction.response.send_message(
                "❌ 対戦当事者（募集者または挑戦者）のみが結果を報告できます。",
                ephemeral=True,
            )
            return

        recruiter = interaction.guild.get_member(self.recruiter_id)
        challenger = interaction.guild.get_member(self.challenger_id)

        if recruiter is None or challenger is None:
            await interaction.response.send_message(
                "❌ プレイヤー情報の取得に失敗しました。サーバーからの退出が原因の可能性があります。",
                ephemeral=True,
            )
            return

        modal = ThreadMatchReportModal(
            thread_id=self.thread_id,
            recruiter=recruiter,
            challenger=challenger,
            panel_message=interaction.message,
        )
        await interaction.response.send_modal(modal)


class ThreadCompletedView(discord.ui.View):
    """対戦終了後のコントロールパネル（スタッツ確認 + 削除のみ）"""

    def __init__(self, thread_id: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id

        stats_btn = discord.ui.Button(
            label="📊 自分のスタッツ",
            style=discord.ButtonStyle.secondary,
            custom_id=f"tr_stats:{thread_id}",
        )
        stats_btn.callback = _stats_callback

        delete_btn = discord.ui.Button(
            label="🗑️ スレッドを削除",
            style=discord.ButtonStyle.danger,
            custom_id=f"tr_delete:{thread_id}",
        )
        delete_btn.callback = _delete_callback

        self.add_item(stats_btn)
        self.add_item(delete_btn)


# ─────────────────────────────────────────────
#  募集モーダル
# ─────────────────────────────────────────────

class RecruitForumModal(discord.ui.Modal):
    def __init__(
        self,
        forum_channel_id: int,
        notify_channel_id: int | None = None,
        mention_role_id: int | None = None,
        defaults: dict | None = None,
    ):
        super().__init__(title="⚔️ 対戦募集を投稿")
        self.forum_channel_id = forum_channel_id
        self.notify_channel_id = notify_channel_id
        self.mention_role_id = mention_role_id
        d = defaults or {}

        self.thread_title = discord.ui.TextInput(
            label="タイトル（必須）",
            placeholder="例: 先三募集中！気軽にどうぞ",
            required=True,
            max_length=100,
        )
        self.connection_type = discord.ui.TextInput(
            label="IP or クラ専（必須）",
            placeholder="例: IP / クラ専",
            default=d.get("connection_type", ""),
            required=True,
            max_length=30,
        )
        self.match_settings = discord.ui.TextInput(
            label="対戦設定（必須）",
            style=discord.TextStyle.paragraph,
            placeholder="autopunch: あり\nソクロ: なし\ngiu: あり",
            default=d.get("match_settings", ""),
            required=True,
            max_length=200,
        )
        self.character = discord.ui.TextInput(
            label="使用キャラ（任意）",
            placeholder="例: 霊夢、魔理沙",
            default=d.get("character", ""),
            required=False,
            max_length=50,
        )
        self.comment = discord.ui.TextInput(
            label="対戦回数 / その他コメント（任意）",
            style=discord.TextStyle.paragraph,
            placeholder="例: 3回くらい / 初心者歓迎です！",
            default=d.get("comment", ""),
            required=False,
            max_length=400,
        )
        self.add_item(self.thread_title)
        self.add_item(self.connection_type)
        self.add_item(self.match_settings)
        self.add_item(self.character)
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        forum_channel = interaction.guild.get_channel(self.forum_channel_id)
        if not isinstance(forum_channel, discord.ForumChannel):
            await interaction.response.send_message(
                "❌ 投稿先のフォーラムチャンネルが見つかりません。管理者にご連絡ください。",
                ephemeral=True,
            )
            return

        perms = forum_channel.permissions_for(interaction.guild.me)
        if not perms.create_public_threads:
            await interaction.response.send_message(
                f"❌ {forum_channel.mention} にスレッドを作成する権限がありません。\n"
                "管理者にBotの **「公開スレッドを作成」** 権限の付与をお願いしてください。",
                ephemeral=True,
            )
            return

        user_info = await db_manager.get_or_create_user(interaction.user.id, interaction.user.display_name)
        rating = round(user_info["rating"], 1)

        conn = self.connection_type.value.strip()
        settings = self.match_settings.value.strip()
        char = self.character.value.strip() or "未指定"
        comment_val = self.comment.value.strip() or "特になし"

        recruit_embed = discord.Embed(
            title="⚔️ 対戦募集",
            description=(
                f"{interaction.user.mention} が対戦相手を募集しています！\n"
                "コントロールパネルのボタンから参加してください。"
            ),
            color=discord.Color.from_rgb(52, 152, 219),
        )
        recruit_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        recruit_embed.add_field(name="募集者レート", value=f"`{rating}`", inline=True)
        recruit_embed.add_field(name="接続方式", value=conn, inline=True)
        recruit_embed.add_field(name="使用キャラ", value=char, inline=True)
        recruit_embed.add_field(name="対戦設定", value=f"```{settings}```", inline=False)
        recruit_embed.add_field(name="対戦回数 / コメント", value=comment_val, inline=False)
        recruit_embed.set_footer(
            text=f"募集者: {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )

        await interaction.response.defer(ephemeral=True)

        try:
            result = await forum_channel.create_thread(
                name=self.thread_title.value,
                embed=recruit_embed,
            )
            thread = result.thread

            # コントロールパネルをスレッドに投稿
            panel_embed = discord.Embed(
                title="🎮 コントロールパネル",
                description="対戦への参加・スタッツ確認・スレッド削除はこちら",
                color=discord.Color.from_rgb(52, 152, 219),
            )
            panel_view = ThreadRecruitingView(
                thread_id=thread.id,
                recruiter_id=interaction.user.id,
            )
            panel_msg = await thread.send(embed=panel_embed, view=panel_view)

            # DBに保存
            await db_manager.add_recruit_thread(
                thread_id=thread.id,
                panel_message_id=panel_msg.id,
                recruiter_id=interaction.user.id,
            )

            # 次回のために入力内容を保存
            await db_manager.save_recruit_defaults(
                user_id=interaction.user.id,
                connection_type=conn,
                match_settings=settings,
                character=self.character.value.strip(),
                comment=self.comment.value.strip(),
            )

            # 通知チャンネルにメンション付きで告知
            if self.notify_channel_id:
                notify_ch = interaction.guild.get_channel(self.notify_channel_id)
                if isinstance(notify_ch, discord.TextChannel):
                    mention = f"<@&{self.mention_role_id}> " if self.mention_role_id else ""
                    await notify_ch.send(
                        f"{mention}対戦募集が投稿されました！\n"
                        f"**{self.thread_title.value}**\n"
                        f"募集者: {interaction.user.mention} / 接続: {conn}\n"
                        f"→ {thread.mention}"
                    )

            logger.info(
                f"forum_recruit: user={interaction.user.id} "
                f"forum={forum_channel.id} thread={thread.id} panel={panel_msg.id}"
            )
            await interaction.followup.send(
                f"✅ 対戦募集を投稿しました！\n→ {thread.mention}",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ 権限不足で投稿できませんでした。管理者にご連絡ください。", ephemeral=True
            )
        except Exception as e:
            logger.error(f"RecruitForumModal エラー: {e}")
            await interaction.followup.send(
                f"❌ 投稿中にエラーが発生しました: {e}", ephemeral=True
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"RecruitForumModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 送信中にエラーが発生しました。", ephemeral=True)


# ─────────────────────────────────────────────
#  募集ボタンパネルView（フォーラムスレッド入口用）
# ─────────────────────────────────────────────

class RecruitForumPanelView(discord.ui.View):
    """Bot再起動後もボタンが機能するよう timeout=None で定義"""

    def __init__(
        self,
        forum_channel_id: int,
        notify_channel_id: int | None = None,
        mention_role_id: int | None = None,
    ):
        super().__init__(timeout=None)
        self.forum_channel_id = forum_channel_id
        self.notify_channel_id = notify_channel_id
        self.mention_role_id = mention_role_id

        btn = discord.ui.Button(
            label="⚔️ 対戦を募集する",
            style=discord.ButtonStyle.primary,
            custom_id=f"forum_recruit_btn:{forum_channel_id}",
        )
        btn.callback = self._btn_callback
        self.add_item(btn)

    async def _btn_callback(self, interaction: discord.Interaction):
        # send_modal は defer できず3秒以内に直接応答する必要があるため、
        # DB読み込みが遅延してもモーダル表示自体は失敗しないようにタイムアウトを設ける
        try:
            defaults = await asyncio.wait_for(
                db_manager.get_recruit_defaults(interaction.user.id), timeout=2.0
            )
        except Exception as e:
            logger.warning(f"get_recruit_defaults 取得失敗（デフォルト値なしで続行）: {e}")
            defaults = None
        await interaction.response.send_modal(
            RecruitForumModal(
                forum_channel_id=self.forum_channel_id,
                notify_channel_id=self.notify_channel_id,
                mention_role_id=self.mention_role_id,
                defaults=defaults,
            )
        )


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class ForumRecruitCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """起動時に保存済みViewを再登録してボタンを復元する"""
        # 募集パネル（入口ボタン）の復元
        panels = await db_manager.get_recruit_panels()
        for panel in panels:
            view = RecruitForumPanelView(
                forum_channel_id=panel["forum_channel_id"],
                notify_channel_id=panel.get("notify_channel_id"),
                mention_role_id=panel.get("mention_role_id"),
            )
            self.bot.add_view(view, message_id=panel["message_id"])
        if panels:
            logger.info(f"forum_recruit: 募集パネル {len(panels)} 件のViewを再登録")

        # スレッドコントロールパネルの復元
        threads = await db_manager.get_active_recruit_threads()
        restored = 0
        for t in threads:
            thread_id = t["thread_id"]
            panel_message_id = t["panel_message_id"]
            recruiter_id = t["recruiter_id"]
            challenger_id = t.get("challenger_id")
            status = t["status"]

            if status == "recruiting":
                view = ThreadRecruitingView(thread_id, recruiter_id)
            elif status == "in_progress" and challenger_id:
                view = ThreadInProgressView(thread_id, recruiter_id, challenger_id)
            else:
                continue

            self.bot.add_view(view, message_id=panel_message_id)
            restored += 1

        if restored:
            logger.info(f"forum_recruit: スレッドパネル {restored} 件のViewを再登録")

    # ── /setup_recruit_panel ─────────────────────

    @app_commands.command(
        name="setup_recruit_panel",
        description="対戦募集ボタンのパネルをこのチャンネルに設置します（管理者用）",
    )
    @app_commands.describe(
        forum_channel="募集投稿の作成先フォーラムチャンネル",
        notify_channel="新規募集時にメンションを送る通知チャンネル（省略可）",
        mention_role="通知時にメンションするロール（省略可）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_recruit_panel(
        self,
        interaction: discord.Interaction,
        forum_channel: discord.ForumChannel,
        notify_channel: discord.TextChannel | None = None,
        mention_role: discord.Role | None = None,
    ):
        notify_channel_id = notify_channel.id if notify_channel else None
        mention_role_id = mention_role.id if mention_role else None

        desc = (
            "下のボタンを押すと対戦募集フォームが開きます。\n"
            f"入力した内容は {forum_channel.mention} に新規投稿されます。"
        )
        if notify_channel:
            desc += f"\n新規募集時は {notify_channel.mention} に通知されます。"

        embed = discord.Embed(
            title="⚔️ 対戦募集",
            description=desc,
            color=discord.Color.from_rgb(52, 152, 219),
        )
        embed.set_footer(text=f"投稿先: #{forum_channel.name}")

        view = RecruitForumPanelView(forum_channel.id, notify_channel_id, mention_role_id)
        await interaction.response.send_message(embed=embed, view=view)
        message = await interaction.original_response()

        await db_manager.add_recruit_panel(
            message_id=message.id,
            channel_id=interaction.channel_id,
            forum_channel_id=forum_channel.id,
            notify_channel_id=notify_channel_id,
            mention_role_id=mention_role_id,
        )
        logger.info(
            f"setup_recruit_panel: message={message.id} "
            f"channel={interaction.channel_id} forum={forum_channel.id} "
            f"notify={notify_channel_id} role={mention_role_id}"
        )

    # ── /remove_recruit_panel ────────────────────

    @app_commands.command(
        name="remove_recruit_panel",
        description="対戦募集パネルを削除します（管理者用）",
    )
    @app_commands.describe(message_id="削除するパネルのメッセージID")
    @app_commands.default_permissions(manage_guild=True)
    async def remove_recruit_panel(
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

        # DB・メッセージ削除より先に応答を確定させ、3秒タイムアウトによる失敗を避ける
        await interaction.response.defer(ephemeral=True)

        deleted_from_db = await db_manager.delete_recruit_panel(mid)

        message_deleted = False
        try:
            msg = await interaction.channel.fetch_message(mid)
            await msg.delete()
            message_deleted = True
        except (discord.NotFound, discord.Forbidden):
            pass

        if not deleted_from_db and not message_deleted:
            await interaction.followup.send(
                "❌ 指定されたIDのパネルが見つかりませんでした。", ephemeral=True
            )
            return

        await interaction.followup.send("✅ 対戦募集パネルを削除しました。", ephemeral=True)
        logger.info(
            f"remove_recruit_panel: message={mid} by user={interaction.user.id} "
            f"db={deleted_from_db} msg={message_deleted}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ForumRecruitCog(bot))
