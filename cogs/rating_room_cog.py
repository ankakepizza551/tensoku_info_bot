import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import db_manager
from rating_ranks import get_rank
from cogs.report_cog import CHARACTERS
from cogs.forum_recruit_cog import find_character, _stats_callback

logger = logging.getLogger("TensokuMatchBot")

BEST_OF = "2先 (2本先取)"


# ─────────────────────────────────────────────
#  共通ユーティリティ
# ─────────────────────────────────────────────

def _profile_summary(profile: dict, rating: float) -> str:
    rank = get_rank(rating)
    return (
        f"固定キャラ: **{profile['main_character']}**\n"
        f"IP/接続: `{profile['ip_info'] or '未設定'}`\n"
        f"オートパンチ: `{profile['autopunch'] or '未設定'}`\n"
        f"giuroll: `{profile['giuroll'] or '未設定'}`\n"
        f"コメント: {profile['comment'] or 'なし'}\n"
        f"レート: `{round(rating, 1)}` (ランク: `{rank}`)"
    )


def _build_queue_board_embed(guild: discord.Guild, queue: list) -> discord.Embed:
    embed = discord.Embed(
        title="⏳ レーティングルーム 待機状況",
        color=discord.Color.from_rgb(155, 89, 182),
    )
    if not queue:
        embed.description = "現在、待機中のプレイヤーはいません。\n`/rating_queue_join` で参加できます。"
    else:
        lines = []
        for q in queue:
            member = guild.get_member(q["user_id"])
            name = member.display_name if member else f"User {q['user_id']}"
            lines.append(f"• {name}")
        embed.description = "\n".join(lines)
    embed.set_footer(text=f"現在の待機人数: {len(queue)}人")
    return embed


async def _sync_queue_board(bot: commands.Bot, guild: discord.Guild):
    """待機人数の可視化ボードを最新の状態に更新する（未設置なら何もしない）"""
    board = await db_manager.get_rating_queue_board(guild.id)
    if board is None:
        return

    channel = guild.get_channel(board["channel_id"])
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        message = await channel.fetch_message(board["message_id"])
    except (discord.NotFound, discord.Forbidden):
        return

    queue = await db_manager.get_rating_queue(guild.id)
    try:
        await message.edit(embed=_build_queue_board_embed(guild, queue))
    except discord.HTTPException as e:
        logger.warning(f"rating_queue_board 更新失敗: {e}")


async def _user_in_active_rating_thread(user_id: int) -> bool:
    threads = await db_manager.get_active_rating_threads()
    for t in threads:
        if t["status"] == "in_progress" and user_id in (t["player1_id"], t["player2_id"]):
            return True
    return False


async def _delete_rating_callback(interaction: discord.Interaction):
    custom_id = interaction.data.get("custom_id", "")
    try:
        thread_id = int(custom_id.split(":")[1])
    except (IndexError, ValueError):
        await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    thread_info = await db_manager.get_rating_thread(thread_id)
    is_participant = thread_info is not None and interaction.user.id in (
        thread_info["player1_id"], thread_info["player2_id"]
    )
    has_manage = interaction.user.guild_permissions.manage_threads

    if not is_participant and not has_manage:
        await interaction.followup.send(
            "❌ 対戦者本人またはモデレーターのみ削除できます。", ephemeral=True
        )
        return

    thread = interaction.channel
    if not isinstance(thread, discord.Thread):
        await interaction.followup.send("❌ スレッド内でのみ使用できます。", ephemeral=True)
        return

    try:
        if thread_info:
            await db_manager.delete_rating_thread(thread_id)
        await thread.delete()
        logger.info(f"rating_thread deleted: thread={thread_id} by user={interaction.user.id}")
    except discord.Forbidden:
        await interaction.followup.send("❌ スレッドを削除する権限がありません。", ephemeral=True)
    except Exception as e:
        logger.error(f"rating thread delete error: {e}")
        await interaction.followup.send(f"❌ 削除中にエラーが発生しました: {e}", ephemeral=True)


# ─────────────────────────────────────────────
#  対戦結果報告モーダル
# ─────────────────────────────────────────────

class RatingMatchReportModal(discord.ui.Modal):
    def __init__(
        self,
        thread_id: int,
        player1: discord.Member,
        player2: discord.Member,
        profile1: dict,
        profile2: dict,
        panel_message: discord.Message,
    ):
        super().__init__(title="📝 レーティング対戦結果の報告")
        self.thread_id = thread_id
        self.player1 = player1
        self.player2 = player2
        self.profile1 = profile1
        self.profile2 = profile2
        self.panel_message = panel_message

        self.my_score_input = discord.ui.TextInput(
            label="自分の勝利本数", placeholder="例: 2", min_length=1, max_length=2
        )
        self.opponent_score_input = discord.ui.TextInput(
            label="相手の勝利本数", placeholder="例: 1", min_length=1, max_length=2
        )
        self.add_item(self.my_score_input)
        self.add_item(self.opponent_score_input)

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
        if reporter.id == self.player1.id:
            score1, score2 = my_score, opp_score
        else:
            score1, score2 = opp_score, my_score

        char1 = self.profile1["main_character"]
        char2 = self.profile2["main_character"]

        await interaction.response.defer()

        try:
            old_rank1 = get_rank((await db_manager.get_or_create_user(self.player1.id, self.player1.display_name))["rating"])
            old_rank2 = get_rank((await db_manager.get_or_create_user(self.player2.id, self.player2.display_name))["rating"])

            result = await db_manager.add_match(
                reporter_id=reporter.id,
                player1_id=self.player1.id,
                player1_name=self.player1.display_name,
                player2_id=self.player2.id,
                player2_name=self.player2.display_name,
                score1=score1,
                score2=score2,
                char1=char1,
                char2=char2,
                rated=True,
            )

            if score1 > score2:
                winner_text = f"🏆 **{self.player1.display_name}** の勝利！"
            elif score2 > score1:
                winner_text = f"🏆 **{self.player2.display_name}** の勝利！"
            else:
                winner_text = "🤝 **引き分け！**"

            new_rank1 = get_rank(result["new_rating1"])
            new_rank2 = get_rank(result["new_rating2"])
            sign1 = "+" if result["change1"] >= 0 else ""
            sign2 = "+" if result["change2"] >= 0 else ""

            def rank_note(old_rank, new_rank):
                if old_rank == new_rank:
                    return ""
                return f" 🎉 ランク変動: `{old_rank}` → `{new_rank}`"

            result_embed = discord.Embed(
                title="📊 対戦結果 (レーティングルーム)",
                description=f"{winner_text}\n**Match ID:** `{result['match_id']}`",
                color=discord.Color.from_rgb(155, 89, 182),
            )
            result_embed.add_field(
                name=self.player1.display_name,
                value=(
                    f"使用キャラ: `{char1}`\n"
                    f"獲得本数: **{score1}**\n"
                    f"レート: `{round(result['old_rating1'], 1)}` → `{round(result['new_rating1'], 1)}` "
                    f"({sign1}{round(result['change1'], 1)})\n"
                    f"ランク: `{new_rank1}`{rank_note(old_rank1, new_rank1)}"
                ),
                inline=True,
            )
            result_embed.add_field(
                name=self.player2.display_name,
                value=(
                    f"使用キャラ: `{char2}`\n"
                    f"獲得本数: **{score2}**\n"
                    f"レート: `{round(result['old_rating2'], 1)}` → `{round(result['new_rating2'], 1)}` "
                    f"({sign2}{round(result['change2'], 1)})\n"
                    f"ランク: `{new_rank2}`{rank_note(old_rank2, new_rank2)}"
                ),
                inline=True,
            )

            closed_embed = discord.Embed(
                title="✅ レーティング対戦終了",
                description=f"{self.player1.mention} vs {self.player2.mention}\n対戦が完了しました。",
                color=discord.Color.from_rgb(127, 140, 141),
            )
            completed_view = RatingThreadCompletedView(self.thread_id)
            await self.panel_message.edit(embed=closed_embed, view=completed_view)
            await db_manager.update_rating_thread_status(self.thread_id, "completed")

            await interaction.followup.send(embed=result_embed)
            logger.info(
                f"rating_match_report: thread={self.thread_id} match={result['match_id']}"
            )

        except Exception as e:
            logger.error(f"RatingMatchReportModal エラー: {e}")
            await interaction.followup.send(
                f"❌ 戦績登録中にエラーが発生しました: {e}", ephemeral=True
            )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"RatingMatchReportModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ エラーが発生しました。", ephemeral=True)


# ─────────────────────────────────────────────
#  スレッドコントロールパネル（永続View）
# ─────────────────────────────────────────────

class RatingThreadInProgressView(discord.ui.View):
    def __init__(self, thread_id: int, player1_id: int, player2_id: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id
        self.player1_id = player1_id
        self.player2_id = player2_id

        report_btn = discord.ui.Button(
            label="📝 結果を報告する",
            style=discord.ButtonStyle.success,
            custom_id=f"rt_report:{thread_id}",
        )
        report_btn.callback = self._report_callback

        stats_btn = discord.ui.Button(
            label="📊 自分のスタッツ",
            style=discord.ButtonStyle.secondary,
            custom_id=f"rt_stats:{thread_id}",
        )
        stats_btn.callback = _stats_callback

        delete_btn = discord.ui.Button(
            label="🗑️ スレッドを削除",
            style=discord.ButtonStyle.danger,
            custom_id=f"rt_delete:{thread_id}",
        )
        delete_btn.callback = _delete_rating_callback

        self.add_item(report_btn)
        self.add_item(stats_btn)
        self.add_item(delete_btn)

    async def _report_callback(self, interaction: discord.Interaction):
        if interaction.user.id not in (self.player1_id, self.player2_id):
            await interaction.response.send_message(
                "❌ 対戦当事者のみが結果を報告できます。", ephemeral=True
            )
            return

        player1 = interaction.guild.get_member(self.player1_id)
        player2 = interaction.guild.get_member(self.player2_id)
        if player1 is None or player2 is None:
            await interaction.response.send_message(
                "❌ プレイヤー情報の取得に失敗しました。サーバーからの退出が原因の可能性があります。",
                ephemeral=True,
            )
            return

        profile1 = await db_manager.get_rating_profile(self.player1_id)
        profile2 = await db_manager.get_rating_profile(self.player2_id)
        if profile1 is None or profile2 is None:
            await interaction.response.send_message(
                "❌ プロフィール情報が見つかりません。管理者にご連絡ください。", ephemeral=True
            )
            return

        modal = RatingMatchReportModal(
            thread_id=self.thread_id,
            player1=player1,
            player2=player2,
            profile1=profile1,
            profile2=profile2,
            panel_message=interaction.message,
        )
        await interaction.response.send_modal(modal)


class RatingThreadCompletedView(discord.ui.View):
    def __init__(self, thread_id: int):
        super().__init__(timeout=None)
        self.thread_id = thread_id

        stats_btn = discord.ui.Button(
            label="📊 自分のスタッツ",
            style=discord.ButtonStyle.secondary,
            custom_id=f"rt_stats:{thread_id}",
        )
        stats_btn.callback = _stats_callback

        delete_btn = discord.ui.Button(
            label="🗑️ スレッドを削除",
            style=discord.ButtonStyle.danger,
            custom_id=f"rt_delete:{thread_id}",
        )
        delete_btn.callback = _delete_rating_callback

        self.add_item(stats_btn)
        self.add_item(delete_btn)


# ─────────────────────────────────────────────
#  プロフィール登録モーダル
# ─────────────────────────────────────────────

class RatingRegisterModal(discord.ui.Modal):
    def __init__(self, existing: dict | None = None):
        super().__init__(title="⚔️ レーティングルーム プロフィール登録")
        e = existing or {}

        self.main_character = discord.ui.TextInput(
            label="固定キャラ（必須・変更不可の対戦キャラ）",
            placeholder="例: 霊夢",
            default=e.get("main_character", ""),
            required=True,
            max_length=20,
        )
        self.ip_info = discord.ui.TextInput(
            label="IP/接続情報（必須）",
            placeholder="例: IP対応可 / クラ専のみ",
            default=e.get("ip_info", ""),
            required=True,
            max_length=100,
        )
        self.autopunch = discord.ui.TextInput(
            label="オートパンチ有無（必須）",
            placeholder="あり / なし",
            default=e.get("autopunch", ""),
            required=True,
            max_length=10,
        )
        self.giuroll = discord.ui.TextInput(
            label="giuroll有無（必須）",
            placeholder="あり / なし",
            default=e.get("giuroll", ""),
            required=True,
            max_length=10,
        )
        self.comment = discord.ui.TextInput(
            label="コメント（任意）",
            style=discord.TextStyle.paragraph,
            default=e.get("comment", ""),
            required=False,
            max_length=300,
        )

        self.add_item(self.main_character)
        self.add_item(self.ip_info)
        self.add_item(self.autopunch)
        self.add_item(self.giuroll)
        self.add_item(self.comment)

    async def on_submit(self, interaction: discord.Interaction):
        char = find_character(self.main_character.value)
        if char is None:
            await interaction.response.send_message(
                f"❌ 固定キャラが認識できませんでした。以下から近い名前で入力してください:\n"
                f"`{'`, `'.join(CHARACTERS)}`",
                ephemeral=True,
            )
            return

        await db_manager.save_rating_profile(
            user_id=interaction.user.id,
            main_character=char,
            ip_info=self.ip_info.value.strip(),
            autopunch=self.autopunch.value.strip(),
            giuroll=self.giuroll.value.strip(),
            comment=self.comment.value.strip(),
        )

        embed = discord.Embed(
            title="✅ プロフィールを登録しました",
            description="この内容でレーティングルームの対戦に参加できます。\n"
                        "変更したい場合は再度 `/rating_register` を実行してください。",
            color=discord.Color.from_rgb(46, 204, 113),
        )
        embed.add_field(name="固定キャラ", value=char, inline=True)
        embed.add_field(name="IP/接続情報", value=self.ip_info.value.strip(), inline=True)
        embed.add_field(name="オートパンチ", value=self.autopunch.value.strip(), inline=True)
        embed.add_field(name="giuroll", value=self.giuroll.value.strip(), inline=True)
        embed.add_field(name="コメント", value=self.comment.value.strip() or "なし", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"rating_register: user={interaction.user.id} char={char}")

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(f"RatingRegisterModal on_error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 登録中にエラーが発生しました。", ephemeral=True)


# ─────────────────────────────────────────────
#  Cog 本体
# ─────────────────────────────────────────────

class RatingRoomCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        threads = await db_manager.get_active_rating_threads()
        restored = 0
        for t in threads:
            if t["status"] != "in_progress":
                continue
            view = RatingThreadInProgressView(t["thread_id"], t["player1_id"], t["player2_id"])
            self.bot.add_view(view, message_id=t["panel_message_id"])
            restored += 1
        if restored:
            logger.info(f"rating_room: スレッドパネル {restored} 件のViewを再登録")

    # ── /rating_register ─────────────────────────

    @app_commands.command(
        name="rating_register",
        description="レーティングルーム用のプロフィール（固定キャラ・接続情報など）を登録/変更します",
    )
    async def rating_register(self, interaction: discord.Interaction):
        existing = await db_manager.get_rating_profile(interaction.user.id)
        await interaction.response.send_modal(RatingRegisterModal(existing))

    # ── /rating_queue_join ───────────────────────

    @app_commands.command(
        name="rating_queue_join",
        description="レーティングルームのマッチングキューに参加します（レート差100以内で自動マッチング）",
    )
    async def rating_queue_join(self, interaction: discord.Interaction):
        profile = await db_manager.get_rating_profile(interaction.user.id)
        if profile is None:
            await interaction.response.send_message(
                "❌ 先に `/rating_register` でプロフィールを登録してください。", ephemeral=True
            )
            return

        settings = await db_manager.get_rating_settings(interaction.guild_id)
        if settings is None:
            await interaction.response.send_message(
                "❌ このサーバーではレーティングルームが未設定です。管理者に `/setup_rating_room` の実行を依頼してください。",
                ephemeral=True,
            )
            return

        if await _user_in_active_rating_thread(interaction.user.id):
            await interaction.response.send_message(
                "❌ すでに進行中のレーティング対戦があります。終了してから再度お試しください。",
                ephemeral=True,
            )
            return

        queue = await db_manager.get_rating_queue(interaction.guild_id)
        if any(q["user_id"] == interaction.user.id for q in queue):
            await interaction.response.send_message(
                "⏳ すでにキューに参加しています。`/rating_queue_leave` でキャンセルできます。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        user_info = await db_manager.get_or_create_user(interaction.user.id, interaction.user.display_name)
        rating = user_info["rating"]

        candidate = await db_manager.find_rating_match(interaction.guild_id, interaction.user.id, rating, max_diff=100.0)

        if candidate is None:
            await db_manager.join_rating_queue(interaction.user.id, interaction.guild_id)
            await _sync_queue_board(self.bot, interaction.guild)
            await interaction.followup.send(
                "⏳ マッチングキューに参加しました。レート差100以内の相手が見つかり次第、対戦スレッドを作成します。",
                ephemeral=True,
            )
            logger.info(f"rating_queue_join: user={interaction.user.id} rating={rating} (待機)")
            return

        opponent_id = candidate["user_id"]
        opponent = interaction.guild.get_member(opponent_id)
        if opponent is None:
            # 相手がサーバーにいない場合はキューから除去して自分は待機に回す
            await db_manager.leave_rating_queue(opponent_id)
            await db_manager.join_rating_queue(interaction.user.id, interaction.guild_id)
            await _sync_queue_board(self.bot, interaction.guild)
            await interaction.followup.send(
                "⏳ マッチングキューに参加しました。レート差100以内の相手が見つかり次第、対戦スレッドを作成します。",
                ephemeral=True,
            )
            return

        opponent_profile = await db_manager.get_rating_profile(opponent_id)
        forum_channel = interaction.guild.get_channel(settings["forum_channel_id"])
        if not isinstance(forum_channel, discord.ForumChannel):
            await db_manager.join_rating_queue(interaction.user.id, interaction.guild_id)
            await interaction.followup.send(
                "❌ 投稿先のフォーラムチャンネルが見つかりません。管理者に `/setup_rating_room` の再設定を依頼してください。",
                ephemeral=True,
            )
            return

        perms = forum_channel.permissions_for(interaction.guild.me)
        if not perms.create_public_threads:
            await db_manager.join_rating_queue(interaction.user.id, interaction.guild_id)
            await interaction.followup.send(
                f"❌ {forum_channel.mention} にスレッドを作成する権限がありません。管理者にご連絡ください。",
                ephemeral=True,
            )
            return

        await db_manager.leave_rating_queue(opponent_id)
        await _sync_queue_board(self.bot, interaction.guild)

        player1, player2 = opponent, interaction.user
        profile1, profile2 = opponent_profile, profile
        rating1 = candidate["rating"]
        rating2 = rating

        thread_embed = discord.Embed(
            title="⚔️ レーティング対戦マッチ成立",
            description=f"{player1.mention} vs {player2.mention}\n"
                        f"形式: {BEST_OF} / 使用キャラは固定です。\n"
                        "対戦終了後、どちらかが「結果を報告する」ボタンからスコアを入力してください。",
            color=discord.Color.from_rgb(155, 89, 182),
        )
        thread_embed.add_field(name=player1.display_name, value=_profile_summary(profile1, rating1), inline=True)
        thread_embed.add_field(name=player2.display_name, value=_profile_summary(profile2, rating2), inline=True)

        try:
            result = await forum_channel.create_thread(
                name=f"レーティング対戦: {player1.display_name} vs {player2.display_name}",
                embed=thread_embed,
            )
            thread = result.thread

            panel_embed = discord.Embed(
                title="🎮 コントロールパネル",
                description="結果報告・スタッツ確認・スレッド削除はこちら",
                color=discord.Color.from_rgb(155, 89, 182),
            )
            panel_view = RatingThreadInProgressView(thread.id, player1.id, player2.id)
            panel_msg = await thread.send(embed=panel_embed, view=panel_view)

            await db_manager.add_rating_thread(
                thread_id=thread.id,
                panel_message_id=panel_msg.id,
                player1_id=player1.id,
                player2_id=player2.id,
            )

            # スレッド内で実際にメンション通知が飛ぶよう、embed とは別にテキストメッセージを送る
            await thread.send(
                f"{player1.mention} {player2.mention} マッチが成立しました！準備ができ次第、対戦を開始してください。"
            )

            # すでに待機していた側（player1）はこのインタラクションの応答を受け取れないため、DMで通知する
            try:
                await player1.send(
                    f"⚔️ レーティング対戦のマッチが成立しました！\n"
                    f"相手: {player2.display_name}\n→ {thread.jump_url}"
                )
            except (discord.Forbidden, discord.HTTPException) as e:
                logger.info(f"rating_match DM通知失敗（DM閉鎖の可能性）: user={player1.id} error={e}")

            if settings.get("notify_channel_id"):
                notify_ch = interaction.guild.get_channel(settings["notify_channel_id"])
                if isinstance(notify_ch, discord.TextChannel):
                    mention = f"<@&{settings['mention_role_id']}> " if settings.get("mention_role_id") else ""
                    await notify_ch.send(
                        f"{mention}レーティング対戦が成立しました！\n"
                        f"{player1.mention} vs {player2.mention} → {thread.mention}"
                    )

            logger.info(
                f"rating_match_created: thread={thread.id} p1={player1.id} p2={player2.id}"
            )
            await interaction.followup.send(
                f"✅ マッチが成立しました！ → {thread.mention}", ephemeral=True
            )

        except discord.Forbidden:
            await db_manager.join_rating_queue(interaction.user.id, interaction.guild_id)
            await _sync_queue_board(self.bot, interaction.guild)
            await interaction.followup.send(
                "❌ 権限不足でスレッドを作成できませんでした。管理者にご連絡ください。", ephemeral=True
            )
        except Exception as e:
            await db_manager.join_rating_queue(interaction.user.id, interaction.guild_id)
            await _sync_queue_board(self.bot, interaction.guild)
            logger.error(f"rating_queue_join エラー: {e}")
            await interaction.followup.send(f"❌ マッチ作成中にエラーが発生しました: {e}", ephemeral=True)

    # ── /rating_queue_leave ──────────────────────

    @app_commands.command(
        name="rating_queue_leave",
        description="レーティングルームのマッチングキューから抜けます",
    )
    async def rating_queue_leave(self, interaction: discord.Interaction):
        removed = await db_manager.leave_rating_queue(interaction.user.id)
        if removed:
            await _sync_queue_board(self.bot, interaction.guild)
            await interaction.response.send_message("✅ キューから抜けました。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ キューに参加していません。", ephemeral=True)

    # ── /rating_queue_status ─────────────────────

    @app_commands.command(
        name="rating_queue_status",
        description="レーティングルームのマッチングキューの状況を表示します",
    )
    async def rating_queue_status(self, interaction: discord.Interaction):
        queue = await db_manager.get_rating_queue(interaction.guild_id)
        embed = discord.Embed(
            title="⏳ レーティングルーム キュー状況",
            color=discord.Color.from_rgb(155, 89, 182),
        )
        if not queue:
            embed.description = "現在、待機中のプレイヤーはいません。"
        else:
            lines = []
            for q in queue:
                member = interaction.guild.get_member(q["user_id"])
                name = member.display_name if member else f"User {q['user_id']}"
                marker = " (あなた)" if q["user_id"] == interaction.user.id else ""
                lines.append(f"• {name}{marker}")
            embed.description = "\n".join(lines)
        embed.set_footer(text=f"現在の待機人数: {len(queue)}人")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /setup_rating_room ───────────────────────

    @app_commands.command(
        name="setup_rating_room",
        description="レーティングルームの投稿先フォーラム・通知先を設定します（管理者用）",
    )
    @app_commands.describe(
        forum_channel="マッチ成立時にスレッドを作成するフォーラムチャンネル",
        notify_channel="マッチ成立時に通知を送るチャンネル（省略可）",
        mention_role="通知時にメンションするロール（省略可）",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_rating_room(
        self,
        interaction: discord.Interaction,
        forum_channel: discord.ForumChannel,
        notify_channel: discord.TextChannel | None = None,
        mention_role: discord.Role | None = None,
    ):
        await db_manager.save_rating_settings(
            guild_id=interaction.guild_id,
            forum_channel_id=forum_channel.id,
            notify_channel_id=notify_channel.id if notify_channel else None,
            mention_role_id=mention_role.id if mention_role else None,
        )

        desc = f"マッチ成立時、{forum_channel.mention} に対戦スレッドを作成します。"
        if notify_channel:
            desc += f"\n通知は {notify_channel.mention} に送信されます。"

        embed = discord.Embed(
            title="✅ レーティングルーム設定完了",
            description=desc,
            color=discord.Color.from_rgb(46, 204, 113),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(
            f"setup_rating_room: guild={interaction.guild_id} forum={forum_channel.id}"
        )

    # ── /setup_rating_queue_board ────────────────

    @app_commands.command(
        name="setup_rating_queue_board",
        description="現在の待機人数を常時表示するボードをこのチャンネルに設置します（管理者用）",
    )
    @app_commands.describe(channel="待機状況ボードを設置するチャンネル")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_rating_queue_board(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        queue = await db_manager.get_rating_queue(interaction.guild_id)
        embed = _build_queue_board_embed(interaction.guild, queue)

        try:
            board_msg = await channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                f"❌ {channel.mention} にメッセージを送信する権限がありません。", ephemeral=True
            )
            return

        await db_manager.save_rating_queue_board(
            guild_id=interaction.guild_id, channel_id=channel.id, message_id=board_msg.id
        )
        await interaction.response.send_message(
            f"✅ 待機状況ボードを {channel.mention} に設置しました。", ephemeral=True
        )
        logger.info(
            f"setup_rating_queue_board: guild={interaction.guild_id} channel={channel.id} message={board_msg.id}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RatingRoomCog(bot))
