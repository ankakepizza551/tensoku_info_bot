import datetime
import json
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database.db_manager as db

logger = logging.getLogger("TensokuMatchBot")

JST = datetime.timezone(datetime.timedelta(hours=9))


# ──────────────────────────────────────────────────────────────
# Embed ビルダー
# ──────────────────────────────────────────────────────────────

def build_poll_embed(
    question: str,
    options: list[str],
    vote_rows: list,
    is_active: bool = True,
    creator_name: str = "",
    allow_multiple: bool = True,
    deadline: str | None = None,
    voter_names_per_option: list[list[str]] | None = None,
) -> discord.Embed:
    """ボタン投票アンケートの結果Embedを構築する"""
    option_counts = [0] * len(options)
    voter_ids: set[int] = set()
    for row in vote_rows:
        option_counts[row["option_index"]] += 1
        voter_ids.add(row["user_id"])

    total_participants = len(voter_ids)
    lines = []
    for i, option in enumerate(options):
        count = option_counts[i]
        if total_participants > 0:
            pct = count / total_participants * 100
            filled = round(pct / 100 * 15)
            bar = "█" * filled + "░" * (15 - filled)
            pct_str = f"{pct:.1f}%"
        else:
            bar = "░" * 15
            pct_str = "0.0%"
        line = f"**{i + 1}. {option}**\n`{bar}` {count}票 ({pct_str})"
        if voter_names_per_option and voter_names_per_option[i]:
            line += "\n└ " + "、".join(voter_names_per_option[i])
        lines.append(line)

    description = "\n\n".join(lines) if lines else "選択肢がありません。"
    color = discord.Color.blue() if is_active else discord.Color.from_rgb(120, 120, 120)
    status = "🟢 投票受付中" if is_active else "🔴 終了"
    select_mode = "複数選択可" if allow_multiple else "単一選択"

    footer_parts = [status, select_mode, f"参加者: {total_participants}人"]
    if deadline:
        footer_parts.append(f"期限: {deadline}")

    embed = discord.Embed(title=f"📊 {question}", description=description, color=color)
    embed.set_footer(text=" | ".join(footer_parts))
    if creator_name:
        embed.set_author(name=f"作成: {creator_name}")
    return embed


def build_survey_embed(
    title: str,
    questions: list[str],
    response_count: int,
    is_active: bool = True,
    creator_name: str = "",
) -> discord.Embed:
    """テキスト回答式アンケートのEmbedを構築する"""
    color = discord.Color.green() if is_active else discord.Color.from_rgb(120, 120, 120)
    status = "🟢 回答受付中" if is_active else "🔴 終了"

    lines = [f"**Q{i + 1}. {q}**" for i, q in enumerate(questions)]
    description = "\n".join(lines)

    embed = discord.Embed(title=f"📝 {title}", description=description, color=color)
    embed.set_footer(text=f"{status} | 回答数: {response_count}件 | 下のボタンで回答できます")
    if creator_name:
        embed.set_author(name=f"作成: {creator_name}")
    return embed


# ──────────────────────────────────────────────────────────────
# Poll UI
# ──────────────────────────────────────────────────────────────

class PollButton(discord.ui.Button):
    def __init__(self, poll_id: str, option_index: int, label: str):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label[:80],
            custom_id=f"poll_vote_{poll_id}_{option_index}",
        )
        self.poll_id = poll_id
        self.option_index = option_index

    async def callback(self, interaction: discord.Interaction):
        poll = await db.get_poll(self.poll_id)
        if not poll or not poll["is_active"]:
            await interaction.response.send_message(
                "⚠️ このアンケートはすでに終了しています。", ephemeral=True
            )
            return

        # 期限チェック
        deadline = poll["deadline"]
        if deadline:
            now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
            if now_str >= deadline:
                await db.close_poll(self.poll_id)
                await interaction.response.send_message(
                    "⚠️ このアンケートの期限が過ぎています。", ephemeral=True
                )
                return

        allow_multiple = bool(poll["allow_multiple"])
        options = json.loads(poll["options"])

        if allow_multiple:
            toggled = await db.toggle_poll_vote(self.poll_id, interaction.user.id, self.option_index)
        else:
            toggled = await db.set_single_poll_vote(self.poll_id, interaction.user.id, self.option_index)

        vote_rows = await db.get_poll_votes(self.poll_id)
        is_anonymous = bool(poll["is_anonymous"]) if "is_anonymous" in poll.keys() else True
        voter_names = None if is_anonymous else build_voter_names(vote_rows, options, interaction.client)
        embed = build_poll_embed(
            question=poll["question"],
            options=options,
            vote_rows=vote_rows,
            is_active=True,
            allow_multiple=allow_multiple,
            deadline=deadline,
            voter_names_per_option=voter_names,
        )
        await interaction.response.edit_message(embed=embed, view=self.view)

        action = (
            f"✅ 「{options[self.option_index]}」に投票しました！"
            if toggled
            else f"↩️ 「{options[self.option_index]}」の投票を取り消しました。"
        )
        await interaction.followup.send(action, ephemeral=True)


class PollCancelButton(discord.ui.Button):
    def __init__(self, poll_id: str):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="投票を取り消す",
            emoji="🗑️",
            custom_id=f"poll_cancel_{poll_id}",
            row=4,
        )
        self.poll_id = poll_id

    async def callback(self, interaction: discord.Interaction):
        poll = await db.get_poll(self.poll_id)
        if not poll or not poll["is_active"]:
            await interaction.response.send_message(
                "⚠️ このアンケートはすでに終了しています。", ephemeral=True
            )
            return

        # 期限チェック
        deadline = poll["deadline"]
        if deadline:
            now_str = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M")
            if now_str >= deadline:
                await db.close_poll(self.poll_id)
                await interaction.response.send_message(
                    "⚠️ このアンケートの期限が過ぎています。", ephemeral=True
                )
                return

        removed = await db.clear_poll_votes(self.poll_id, interaction.user.id)
        if removed == 0:
            await interaction.response.send_message(
                "ℹ️ まだこのアンケートに投票していません。", ephemeral=True
            )
            return

        options = json.loads(poll["options"])
        vote_rows = await db.get_poll_votes(self.poll_id)
        is_anonymous = bool(poll["is_anonymous"]) if "is_anonymous" in poll.keys() else True
        voter_names = None if is_anonymous else build_voter_names(vote_rows, options, interaction.client)
        embed = build_poll_embed(
            question=poll["question"],
            options=options,
            vote_rows=vote_rows,
            is_active=True,
            allow_multiple=bool(poll["allow_multiple"]),
            deadline=deadline,
            voter_names_per_option=voter_names,
        )
        await interaction.response.edit_message(embed=embed, view=self.view)
        await interaction.followup.send("↩️ 投票をすべて取り消しました。", ephemeral=True)


class PollView(discord.ui.View):
    def __init__(self, poll_id: str, options: list[str]):
        super().__init__(timeout=None)
        for i, option in enumerate(options):
            self.add_item(PollButton(poll_id=poll_id, option_index=i, label=option))
        self.add_item(PollCancelButton(poll_id=poll_id))


# ──────────────────────────────────────────────────────────────
# Survey UI
# ──────────────────────────────────────────────────────────────

class SurveyAnswerModal(discord.ui.Modal):
    def __init__(self, survey_id: str, title: str, questions: list[str]):
        super().__init__(title=title[:45])
        self.survey_id = survey_id
        for i, q in enumerate(questions[:4]):
            self.add_item(
                discord.ui.TextInput(
                    label=q[:45],
                    placeholder="回答を入力してください...",
                    required=True,
                    max_length=500,
                    style=discord.TextStyle.paragraph,
                    row=i,
                )
            )

    async def on_submit(self, interaction: discord.Interaction):
        answers = [item.value for item in self.children]
        await db.add_survey_response(
            survey_id=self.survey_id,
            user_id=interaction.user.id,
            answers=answers,
        )
        await interaction.response.send_message(
            "✅ 回答を送信しました！ありがとうございます。", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message(
            f"⚠️ エラーが発生しました: {error}", ephemeral=True
        )


class SurveyAnswerButton(discord.ui.Button):
    def __init__(self, survey_id: str):
        super().__init__(
            style=discord.ButtonStyle.success,
            label="回答する",
            emoji="📝",
            custom_id=f"survey_answer_{survey_id}",
        )
        self.survey_id = survey_id

    async def callback(self, interaction: discord.Interaction):
        survey = await db.get_survey(self.survey_id)
        if not survey or not survey["is_active"]:
            await interaction.response.send_message(
                "⚠️ このアンケートはすでに終了しています。", ephemeral=True
            )
            return

        if await db.has_survey_responded(self.survey_id, interaction.user.id):
            await interaction.response.send_message(
                "⚠️ すでに回答済みです。", ephemeral=True
            )
            return

        questions = json.loads(survey["questions"])
        modal = SurveyAnswerModal(
            survey_id=self.survey_id,
            title=survey["title"],
            questions=questions,
        )
        await interaction.response.send_modal(modal)


class SurveyAnswerView(discord.ui.View):
    def __init__(self, survey_id: str):
        super().__init__(timeout=None)
        self.add_item(SurveyAnswerButton(survey_id=survey_id))


class SurveyCreateModal(discord.ui.Modal, title="アンケートを作成"):
    survey_title_field = discord.ui.TextInput(
        label="アンケートタイトル",
        placeholder="例: 大会スケジュールアンケート2026",
        required=True,
        max_length=100,
    )
    q1 = discord.ui.TextInput(
        label="質問1（必須）",
        placeholder="質問を入力してください",
        required=True,
        max_length=100,
    )
    q2 = discord.ui.TextInput(
        label="質問2（任意）",
        placeholder="質問を入力してください",
        required=False,
        max_length=100,
    )
    q3 = discord.ui.TextInput(
        label="質問3（任意）",
        placeholder="質問を入力してください",
        required=False,
        max_length=100,
    )
    q4 = discord.ui.TextInput(
        label="質問4（任意）",
        placeholder="質問を入力してください",
        required=False,
        max_length=100,
    )

    def __init__(self, target_channel: discord.TextChannel, bot_instance: commands.Bot):
        super().__init__()
        self.target_channel = target_channel
        self.bot_instance = bot_instance

    async def on_submit(self, interaction: discord.Interaction):
        questions = [
            q.value.strip()
            for q in [self.q1, self.q2, self.q3, self.q4]
            if q.value.strip()
        ]
        if not questions:
            await interaction.response.send_message(
                "❌ 質問が入力されていません。", ephemeral=True
            )
            return

        title = self.survey_title_field.value.strip()
        embed = build_survey_embed(
            title=title,
            questions=questions,
            response_count=0,
            is_active=True,
            creator_name=interaction.user.display_name,
        )

        await interaction.response.defer(ephemeral=True)
        msg = await self.target_channel.send(embed=embed)
        survey_id = str(msg.id)

        await db.create_survey(
            survey_id=survey_id,
            channel_id=self.target_channel.id,
            creator_id=interaction.user.id,
            title=title,
            questions=questions,
        )

        view = SurveyAnswerView(survey_id=survey_id)
        self.bot_instance.add_view(view)
        await msg.edit(view=view)

        await interaction.followup.send(
            f"✅ アンケートを {self.target_channel.mention} に作成しました！\n"
            f"メッセージID: `{survey_id}`\n"
            f"結果確認・締め切りに使用するので控えておいてください。",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message(
            f"⚠️ エラーが発生しました: {error}", ephemeral=True
        )


# ──────────────────────────────────────────────────────────────
# 作成パネル（ボタンからアンケートを作成）
# ──────────────────────────────────────────────────────────────

def _parse_bool(text: str, default: bool = True) -> bool:
    """「はい/いいえ」形式のテキストをboolに変換する"""
    value = text.strip()
    if not value:
        return default
    return value not in ("いいえ", "no", "No", "NO", "0", "false", "False")


class PollCreateModal(discord.ui.Modal, title="投票アンケートを作成"):
    question_field = discord.ui.TextInput(
        label="質問",
        placeholder="例: 次回大会の開催日程は？",
        required=True,
        max_length=200,
    )
    options_field = discord.ui.TextInput(
        label="選択肢（カンマ区切り・2〜10個）",
        placeholder="例: 霊夢,魔理沙,チルノ",
        required=True,
        max_length=300,
    )
    allow_multiple_field = discord.ui.TextInput(
        label="複数選択を許可する？（はい/いいえ）",
        default="はい",
        required=False,
        max_length=10,
    )
    anonymous_field = discord.ui.TextInput(
        label="匿名にする？（はい/いいえ）",
        default="はい",
        required=False,
        max_length=10,
    )
    deadline_field = discord.ui.TextInput(
        label="締め切り（任意・YYYY-MM-DD HH:MM）",
        placeholder="例: 2026-06-30 23:59",
        required=False,
        max_length=20,
    )

    def __init__(self, target_channel: discord.TextChannel, bot_instance: commands.Bot):
        super().__init__()
        self.target_channel = target_channel
        self.bot_instance = bot_instance

    async def on_submit(self, interaction: discord.Interaction):
        question = self.question_field.value.strip()
        option_list = [o.strip() for o in self.options_field.value.split(",") if o.strip()]

        if len(option_list) < 2:
            await interaction.response.send_message(
                "❌ 選択肢は2個以上をカンマ区切りで入力してください。\n例: `霊夢,魔理沙,チルノ`",
                ephemeral=True,
            )
            return
        if len(option_list) > 10:
            await interaction.response.send_message(
                "❌ 選択肢は最大10個です。", ephemeral=True
            )
            return

        allow_multiple = _parse_bool(self.allow_multiple_field.value, default=True)
        anonymous = _parse_bool(self.anonymous_field.value, default=True)

        deadline_str: str | None = None
        deadline_input = self.deadline_field.value.strip()
        if deadline_input:
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
                try:
                    parsed = datetime.datetime.strptime(deadline_input, fmt).replace(tzinfo=JST)
                    break
                except ValueError:
                    continue
            if parsed is None:
                await interaction.response.send_message(
                    "❌ 期限の形式が正しくありません。`YYYY-MM-DD HH:MM` の形式で入力してください。\n例: `2026-06-30 23:59`",
                    ephemeral=True,
                )
                return
            if parsed <= datetime.datetime.now(JST):
                await interaction.response.send_message(
                    "❌ 期限は現在より未来の日時を指定してください。", ephemeral=True
                )
                return
            deadline_str = parsed.strftime("%Y-%m-%d %H:%M")

        embed = build_poll_embed(
            question=question,
            options=option_list,
            vote_rows=[],
            is_active=True,
            creator_name=interaction.user.display_name,
            allow_multiple=allow_multiple,
            deadline=deadline_str,
        )

        await interaction.response.defer(ephemeral=True)
        msg = await self.target_channel.send(embed=embed)
        poll_id = str(msg.id)

        await db.create_poll(
            poll_id=poll_id,
            channel_id=self.target_channel.id,
            creator_id=interaction.user.id,
            question=question,
            options=option_list,
            allow_multiple=allow_multiple,
            is_anonymous=anonymous,
            deadline=deadline_str,
        )

        view = PollView(poll_id=poll_id, options=option_list)
        self.bot_instance.add_view(view)
        await msg.edit(view=view)

        await interaction.followup.send(
            f"✅ 投票アンケートを {self.target_channel.mention} に作成しました！\n"
            f"メッセージID: `{poll_id}`",
            ephemeral=True,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await interaction.response.send_message(
            f"⚠️ エラーが発生しました: {error}", ephemeral=True
        )


class PollTypeChoiceView(discord.ui.View):
    """パネルの「アンケートを作る」ボタンを押した後に出す種類選択"""

    def __init__(self, target_channel: discord.TextChannel, bot_instance: commands.Bot):
        super().__init__(timeout=60)
        self.target_channel = target_channel
        self.bot_instance = bot_instance

    @discord.ui.button(label="投票アンケート", emoji="🗳️", style=discord.ButtonStyle.primary)
    async def create_poll(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            PollCreateModal(target_channel=self.target_channel, bot_instance=self.bot_instance)
        )

    @discord.ui.button(label="テキストアンケート", emoji="📝", style=discord.ButtonStyle.success)
    async def create_survey(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            SurveyCreateModal(target_channel=self.target_channel, bot_instance=self.bot_instance)
        )


class PollPanelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="アンケートを作成",
            emoji="➕",
            custom_id="poll_panel_create",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "作成するアンケートの種類を選んでください。",
            view=PollTypeChoiceView(target_channel=interaction.channel, bot_instance=interaction.client),
            ephemeral=True,
        )


class PollPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(PollPanelButton())


def build_voter_names(vote_rows: list, options: list[str], bot: commands.Bot) -> list[list[str]]:
    """選択肢ごとの投票者表示名リストを返す"""
    names_per_option: list[list[str]] = [[] for _ in options]
    for row in vote_rows:
        idx = row["option_index"]
        if 0 <= idx < len(options):
            user = bot.get_user(row["user_id"])
            name = user.display_name if user else f"User {row['user_id']}"
            names_per_option[idx].append(name)
    return names_per_option


# ──────────────────────────────────────────────────────────────
# PollCog
# ──────────────────────────────────────────────────────────────

class PollCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Bot起動・再接続時にアクティブなPoll/SurveyのViewを再登録する"""
        active_polls = await db.get_active_polls()
        for poll in active_polls:
            options = json.loads(poll["options"])
            self.bot.add_view(PollView(poll_id=poll["poll_id"], options=options))

        active_surveys = await db.get_active_surveys()
        for survey in active_surveys:
            self.bot.add_view(SurveyAnswerView(survey_id=survey["survey_id"]))

        self.bot.add_view(PollPanelView())

        if not self._check_expired_polls.is_running():
            self._check_expired_polls.start()

    @tasks.loop(minutes=1)
    async def _check_expired_polls(self):
        """期限切れの投票アンケートを自動締め切りする"""
        expired = await db.get_expired_polls()
        for poll in expired:
            await db.close_poll(poll["poll_id"])
            try:
                ch = self.bot.get_channel(poll["channel_id"])
                if ch:
                    msg = await ch.fetch_message(int(poll["poll_id"]))
                    options = json.loads(poll["options"])
                    vote_rows = await db.get_poll_votes(poll["poll_id"])
                    is_anonymous = bool(poll["is_anonymous"]) if "is_anonymous" in poll.keys() else True
                    voter_names = None if is_anonymous else build_voter_names(vote_rows, options, self.bot)
                    embed = build_poll_embed(
                        question=poll["question"],
                        options=options,
                        vote_rows=vote_rows,
                        is_active=False,
                        allow_multiple=bool(poll["allow_multiple"]),
                        deadline=poll["deadline"],
                        voter_names_per_option=voter_names,
                    )
                    await msg.edit(embed=embed, view=None)
                    await ch.send("⏰ 投票アンケートの時間が終了しました。\n**最終結果:**", embed=embed)
            except Exception as e:
                logger.warning(f"投票アンケートの自動締め切りに失敗しました (poll_id={poll['poll_id']}): {e}")

    # ── /poll ────────────────────────────────────────────────

    @app_commands.command(
        name="poll",
        description="ボタン式の投票アンケートを作成します",
    )
    @app_commands.describe(
        question="アンケートの質問",
        options="選択肢をカンマ区切りで入力（2〜10個）例: 霊夢,魔理沙,チルノ",
        allow_multiple="複数選択を許可するか（デフォルト: はい）",
        anonymous="投票を匿名にするか（デフォルト: はい）終了時に非匿名なら誰が何に投票したか表示",
        deadline="締め切り日時（例: 2026-06-30 23:59）省略可",
        channel="投稿するチャンネル（省略時は現在のチャンネル）",
    )
    async def poll(
        self,
        interaction: discord.Interaction,
        question: str,
        options: str,
        allow_multiple: bool = True,
        anonymous: bool = True,
        deadline: Optional[str] = None,
        channel: Optional[discord.TextChannel] = None,
    ):
        target_channel = channel or interaction.channel
        option_list = [o.strip() for o in options.split(",") if o.strip()]

        if len(option_list) < 2:
            await interaction.response.send_message(
                "❌ 選択肢は2個以上をカンマ区切りで入力してください。\n例: `霊夢,魔理沙,チルノ`",
                ephemeral=True,
            )
            return
        if len(option_list) > 10:
            await interaction.response.send_message(
                "❌ 選択肢は最大10個です。", ephemeral=True
            )
            return

        # deadline のバリデーション
        deadline_str: str | None = None
        if deadline:
            parsed = None
            for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
                try:
                    parsed = datetime.datetime.strptime(deadline, fmt).replace(tzinfo=JST)
                    break
                except ValueError:
                    continue
            if parsed is None:
                await interaction.response.send_message(
                    "❌ 期限の形式が正しくありません。`YYYY-MM-DD HH:MM` の形式で入力してください。\n例: `2026-06-30 23:59`",
                    ephemeral=True,
                )
                return
            if parsed <= datetime.datetime.now(JST):
                await interaction.response.send_message(
                    "❌ 期限は現在より未来の日時を指定してください。", ephemeral=True
                )
                return
            deadline_str = parsed.strftime("%Y-%m-%d %H:%M")

        embed = build_poll_embed(
            question=question,
            options=option_list,
            vote_rows=[],
            is_active=True,
            creator_name=interaction.user.display_name,
            allow_multiple=allow_multiple,
            deadline=deadline_str,
        )

        await interaction.response.defer(ephemeral=True)
        msg = await target_channel.send(embed=embed)
        poll_id = str(msg.id)

        await db.create_poll(
            poll_id=poll_id,
            channel_id=target_channel.id,
            creator_id=interaction.user.id,
            question=question,
            options=option_list,
            allow_multiple=allow_multiple,
            is_anonymous=anonymous,
            deadline=deadline_str,
        )

        view = PollView(poll_id=poll_id, options=option_list)
        self.bot.add_view(view)
        await msg.edit(view=view)

        detail = ""
        if not allow_multiple:
            detail += "\n・単一選択モード"
        if not anonymous:
            detail += "\n・非匿名モード（終了時に投票者名を表示）"
        if deadline_str:
            detail += f"\n・期限: {deadline_str}"

        await interaction.followup.send(
            f"✅ 投票アンケートを {target_channel.mention} に作成しました！\n"
            f"メッセージID: `{poll_id}`{detail}",
            ephemeral=True,
        )

    # ── /close_poll ──────────────────────────────────────────

    @app_commands.command(
        name="close_poll",
        description="投票アンケートを締め切ります（作成者またはサーバー管理者のみ）",
    )
    @app_commands.describe(message_id="締め切る投票メッセージのID")
    async def close_poll(self, interaction: discord.Interaction, message_id: str):
        poll = await db.get_poll(message_id)
        if not poll:
            await interaction.response.send_message(
                "❌ 指定されたIDの投票アンケートが見つかりません。", ephemeral=True
            )
            return

        is_creator = poll["creator_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not is_creator and not is_admin:
            await interaction.response.send_message(
                "❌ 締め切れるのは作成者またはサーバー管理者のみです。", ephemeral=True
            )
            return

        if not poll["is_active"]:
            await interaction.response.send_message(
                "⚠️ このアンケートはすでに終了しています。", ephemeral=True
            )
            return

        await db.close_poll(message_id)

        options = json.loads(poll["options"])
        vote_rows = await db.get_poll_votes(message_id)
        is_anonymous = bool(poll["is_anonymous"]) if "is_anonymous" in poll.keys() else True
        voter_names = None if is_anonymous else build_voter_names(vote_rows, options, self.bot)
        result_embed = build_poll_embed(
            question=poll["question"],
            options=options,
            vote_rows=vote_rows,
            is_active=False,
            allow_multiple=bool(poll["allow_multiple"]),
            deadline=poll["deadline"],
            voter_names_per_option=voter_names,
        )

        try:
            ch = self.bot.get_channel(poll["channel_id"])
            if ch:
                msg = await ch.fetch_message(int(message_id))
                await msg.edit(embed=result_embed, view=None)
        except Exception as e:
            logger.warning(f"投票アンケートメッセージの更新に失敗しました (poll_id={poll['poll_id']}): {e}")

        await interaction.response.send_message(
            "✅ 投票アンケートを締め切りました。\n**最終結果:**",
            embed=result_embed,
        )

    # ── /poll_refresh ────────────────────────────────────────

    @app_commands.command(
        name="poll_refresh",
        description="投票アンケートの表示を最新の状態に更新します（作成者またはサーバー管理者のみ）",
    )
    @app_commands.describe(message_id="更新する投票メッセージのID")
    async def poll_refresh(self, interaction: discord.Interaction, message_id: str):
        poll = await db.get_poll(message_id)
        if not poll:
            await interaction.response.send_message(
                "❌ 指定されたIDの投票アンケートが見つかりません。", ephemeral=True
            )
            return

        is_creator = poll["creator_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not is_creator and not is_admin:
            await interaction.response.send_message(
                "❌ 更新できるのは作成者またはサーバー管理者のみです。", ephemeral=True
            )
            return

        if not poll["is_active"]:
            await interaction.response.send_message(
                "⚠️ このアンケートはすでに終了しています。", ephemeral=True
            )
            return

        options = json.loads(poll["options"])
        vote_rows = await db.get_poll_votes(message_id)
        is_anonymous = bool(poll["is_anonymous"]) if "is_anonymous" in poll.keys() else True
        voter_names = None if is_anonymous else build_voter_names(vote_rows, options, self.bot)
        embed = build_poll_embed(
            question=poll["question"],
            options=options,
            vote_rows=vote_rows,
            is_active=True,
            allow_multiple=bool(poll["allow_multiple"]),
            deadline=poll["deadline"],
            voter_names_per_option=voter_names,
        )

        try:
            ch = self.bot.get_channel(poll["channel_id"])
            if ch:
                msg = await ch.fetch_message(int(message_id))
                await msg.edit(embed=embed)
        except Exception as e:
            logger.warning(f"投票アンケートメッセージの更新に失敗しました (poll_id={message_id}): {e}")
            await interaction.response.send_message(
                "❌ メッセージの更新に失敗しました。", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ 投票アンケートの表示を更新しました。", ephemeral=True
        )

    # ── /poll_panel ──────────────────────────────────────────

    @app_commands.command(
        name="poll_panel",
        description="ボタンからアンケートを作成できるパネルを設置します（サーバー管理者のみ）",
    )
    @app_commands.describe(channel="設置するチャンネル（省略時は現在のチャンネル）")
    async def poll_panel(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ このコマンドはサーバー管理者のみ使用できます。", ephemeral=True
            )
            return

        target_channel = channel or interaction.channel
        embed = discord.Embed(
            title="📋 アンケート作成パネル",
            description=(
                "下のボタンから、投票アンケート（🗳️選択肢に投票）\n"
                "またはテキストアンケート（📝自由記述で回答）を作成できます。"
            ),
            color=discord.Color.blue(),
        )
        await target_channel.send(embed=embed, view=PollPanelView())
        await interaction.response.send_message(
            f"✅ アンケート作成パネルを {target_channel.mention} に設置しました。",
            ephemeral=True,
        )

    # ── /survey ──────────────────────────────────────────────

    @app_commands.command(
        name="survey",
        description="テキスト回答式のアンケートを作成します（モーダルで質問を設定）",
    )
    @app_commands.describe(channel="投稿するチャンネル（省略時は現在のチャンネル）")
    async def survey(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        target_channel = channel or interaction.channel
        modal = SurveyCreateModal(target_channel=target_channel, bot_instance=self.bot)
        await interaction.response.send_modal(modal)

    # ── /close_survey ────────────────────────────────────────

    @app_commands.command(
        name="close_survey",
        description="アンケートフォームを締め切ります（作成者またはサーバー管理者のみ）",
    )
    @app_commands.describe(message_id="締め切るアンケートメッセージのID")
    async def close_survey(self, interaction: discord.Interaction, message_id: str):
        survey = await db.get_survey(message_id)
        if not survey:
            await interaction.response.send_message(
                "❌ 指定されたIDのアンケートが見つかりません。", ephemeral=True
            )
            return

        is_creator = survey["creator_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not is_creator and not is_admin:
            await interaction.response.send_message(
                "❌ 締め切れるのは作成者またはサーバー管理者のみです。", ephemeral=True
            )
            return

        if not survey["is_active"]:
            await interaction.response.send_message(
                "⚠️ このアンケートはすでに終了しています。", ephemeral=True
            )
            return

        await db.close_survey(message_id)

        try:
            ch = self.bot.get_channel(survey["channel_id"])
            if ch:
                msg = await ch.fetch_message(int(message_id))
                questions = json.loads(survey["questions"])
                responses = await db.get_survey_responses(message_id)
                embed = build_survey_embed(
                    title=survey["title"],
                    questions=questions,
                    response_count=len(responses),
                    is_active=False,
                )
                await msg.edit(embed=embed, view=None)
        except Exception as e:
            logger.warning(f"アンケートメッセージの更新に失敗しました (survey_id={message_id}): {e}")

        await interaction.response.send_message(
            "✅ アンケートを締め切りました。", ephemeral=True
        )

    # ── /survey_results ──────────────────────────────────────

    @app_commands.command(
        name="survey_results",
        description="アンケートの回答結果を確認します（作成者またはサーバー管理者のみ）",
    )
    @app_commands.describe(message_id="結果を確認するアンケートメッセージのID")
    async def survey_results(self, interaction: discord.Interaction, message_id: str):
        survey = await db.get_survey(message_id)
        if not survey:
            await interaction.response.send_message(
                "❌ 指定されたIDのアンケートが見つかりません。", ephemeral=True
            )
            return

        is_creator = survey["creator_id"] == interaction.user.id
        is_admin = interaction.user.guild_permissions.manage_guild
        if not is_creator and not is_admin:
            await interaction.response.send_message(
                "❌ 結果を確認できるのは作成者またはサーバー管理者のみです。", ephemeral=True
            )
            return

        responses = await db.get_survey_responses(message_id)
        questions = json.loads(survey["questions"])

        if not responses:
            await interaction.response.send_message(
                f"📝 **{survey['title']}** — まだ回答がありません。", ephemeral=True
            )
            return

        embeds: list[discord.Embed] = []

        summary_embed = discord.Embed(
            title=f"📊 アンケート結果: {survey['title']}",
            description=(
                f"回答数: **{len(responses)}件**\n\n"
                + "\n".join(f"Q{i + 1}. {q}" for i, q in enumerate(questions))
            ),
            color=discord.Color.gold(),
        )
        embeds.append(summary_embed)

        # 最大9件の個別回答を表示（合計10 Embed まで）
        for i, row in enumerate(responses[:9]):
            answers = json.loads(row["answers"])
            user = self.bot.get_user(row["user_id"])
            user_name = user.display_name if user else f"User {row['user_id']}"

            resp_embed = discord.Embed(
                title=f"回答 #{i + 1} — {user_name}",
                color=discord.Color.light_grey(),
            )
            for j, (q, a) in enumerate(zip(questions, answers)):
                resp_embed.add_field(
                    name=f"Q{j + 1}. {q}", value=a or "（未入力）", inline=False
                )
            resp_embed.set_footer(text=str(row.get("created_at", "")))
            embeds.append(resp_embed)

        if len(responses) > 9:
            note_embed = discord.Embed(
                description=f"※ 表示は9件まで。残り {len(responses) - 9} 件は省略しました。",
                color=discord.Color.light_grey(),
            )
            embeds.append(note_embed)

        await interaction.response.send_message(embeds=embeds, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PollCog(bot))
