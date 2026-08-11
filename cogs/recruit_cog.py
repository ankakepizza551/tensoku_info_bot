import discord
from discord import app_commands
from discord.ext import commands
from database import db_manager
from cogs.report_cog import CHARACTERS

def find_character(input_name: str):
    if not input_name:
        return None
    input_name_clean = input_name.strip()
    if not input_name_clean:
        return None
    for char in CHARACTERS:
        if input_name_clean in char or char in input_name_clean:
            return char
    return None

class MatchReportModal(discord.ui.Modal):
    def __init__(self, view: 'RecruitView'):
        super().__init__(title="対戦結果の報告")
        self.recruit_view = view
        
        self.my_score_input = discord.ui.TextInput(
            label="自分の勝利本数",
            placeholder="例: 2",
            min_length=1,
            max_length=2,
            required=True
        )
        self.opponent_score_input = discord.ui.TextInput(
            label="相手の勝利本数",
            placeholder="例: 1",
            min_length=1,
            max_length=2,
            required=True
        )
        self.my_char_input = discord.ui.TextInput(
            label="自分の使用キャラ (任意)",
            placeholder="例: 霊夢",
            required=False,
            max_length=20
        )
        self.opponent_char_input = discord.ui.TextInput(
            label="相手の使用キャラ (任意)",
            placeholder="例: 魔理沙",
            required=False,
            max_length=20
        )
        
        self.add_item(self.my_score_input)
        self.add_item(self.opponent_score_input)
        self.add_item(self.my_char_input)
        self.add_item(self.opponent_char_input)

    async def on_submit(self, interaction: discord.Interaction):
        # スコア値のバリデーション
        try:
            my_score = int(self.my_score_input.value)
            opp_score = int(self.opponent_score_input.value)
            if my_score < 0 or opp_score < 0:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("❌ スコアには0以上の整数を入力してください。", ephemeral=True)
            return

        reporter = interaction.user
        recruiter = self.recruit_view.recruiter
        challenger = self.recruit_view.challenger
        
        # 報告者が募集者か挑戦者かによって、player1とplayer2への割り当てを切り替える
        if reporter.id == recruiter.id:
            score1 = my_score
            score2 = opp_score
            char1_raw = self.my_char_input.value
            char2_raw = self.opponent_char_input.value
        else:
            score1 = opp_score
            score2 = my_score
            char1_raw = self.opponent_char_input.value
            char2_raw = self.my_char_input.value
            
        char1 = find_character(char1_raw)
        char2 = find_character(char2_raw)
        
        # レスポンス待機
        await interaction.response.defer()
        
        try:
            # 戦績の登録
            result = await db_manager.add_match(
                reporter_id=reporter.id,
                player1_id=recruiter.id,
                player1_name=recruiter.display_name,
                player2_id=challenger.id,
                player2_name=challenger.display_name,
                score1=score1,
                score2=score2,
                char1=char1,
                char2=char2,
                rated=False
            )
            
            # 結果表示用Embedの作成
            embed = discord.Embed(
                title="📊 対戦結果 (募集対戦)",
                description=f"募集した対戦が終了し、戦績が保存されました！\n**対戦ID (Match ID):** `{result['match_id']}`",
                color=discord.Color.from_rgb(46, 204, 113) # 緑色
            )
            
            # 勝敗表示
            if score1 > score2:
                winner_text = f"🏆 **{recruiter.display_name}** の勝利！"
            elif score2 > score1:
                winner_text = f"🏆 **{challenger.display_name}** の勝利！"
            else:
                winner_text = "🤝 **引き分け！**"
                
            embed.add_field(name="結果", value=winner_text, inline=False)
            
            embed.add_field(
                name=recruiter.display_name,
                value=(
                    f"使用キャラ: `{char1 or '未設定'}`\n"
                    f"獲得本数: **{score1}**\n"
                    f"現在のレート: `{round(result['old_rating1'], 1)}` （フリー対戦のためレート変動なし）"
                ),
                inline=True
            )
            embed.add_field(
                name=challenger.display_name,
                value=(
                    f"使用キャラ: `{char2 or '未設定'}`\n"
                    f"獲得本数: **{score2}**\n"
                    f"現在のレート: `{round(result['old_rating2'], 1)}` （フリー対戦のためレート変動なし）"
                ),
                inline=True
            )
            
            # 元の募集メッセージを対戦終了ステータスにして、再募集/締切を選べるボタンに切り替え
            closed_embed = discord.Embed(
                title="⚔️ 対戦終了 (Closed)",
                description=(
                    f"{recruiter.mention} vs {challenger.mention}\n"
                    f"対戦は終了しました。結果はチャンネル内に新規投稿されました。\n\n"
                    f"募集者（{recruiter.mention}）は、続けて再募集するか募集を締め切るか選択してください。"
                ),
                color=discord.Color.from_rgb(127, 140, 141) # 灰色
            )
            post_match_view = PostMatchView(
                recruiter=recruiter,
                comment=self.recruit_view.comment,
                format_str=self.recruit_view.format_str
            )
            await interaction.message.edit(embed=closed_embed, view=post_match_view)
            post_match_view.message = interaction.message

            # 結果をチャンネルに送信
            await interaction.followup.send(embed=embed)
            self.recruit_view.stop()
            
        except Exception as e:
            await interaction.followup.send(f"❌ 戦績の登録中にエラーが発生しました: {e}", ephemeral=True)

class RecruitView(discord.ui.View):
    def __init__(self, recruiter: discord.Member, recruiter_rating: float, comment: str, format_str: str):
        super().__init__(timeout=86400) # 24時間でタイムアウト
        self.recruiter = recruiter
        self.recruiter_rating = recruiter_rating
        self.comment = comment
        self.format_str = format_str
        self.challenger = None

    @discord.ui.button(label="対戦を申し込む", style=discord.ButtonStyle.primary)
    async def join_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.recruiter.id:
            await interaction.response.send_message("❌ 自分自身の募集には参加できません！", ephemeral=True)
            return
            
        self.challenger = interaction.user
        
        # 対戦中ステータスのEmbedに更新
        embed = discord.Embed(
            title="⚔️ 対戦中 (Match in Progress)",
            description=f"{self.recruiter.mention} (レート: `{round(self.recruiter_rating, 1)}`) vs {self.challenger.mention}\n\n対戦終了後、どちらかのプレイヤーが「結果を報告する」ボタンからスコアを入力してください。",
            color=discord.Color.from_rgb(241, 196, 15) # 黄色
        )
        embed.add_field(name="募集形式", value=self.format_str, inline=True)
        embed.add_field(name="コメント", value=self.comment, inline=True)
        
        # ボタンを変更（結果報告ボタンのみにする）
        self.clear_items()
        
        report_button = discord.ui.Button(label="結果を報告する", style=discord.ButtonStyle.success)
        async def report_callback(report_inter: discord.Interaction):
            if report_inter.user.id not in [self.recruiter.id, self.challenger.id]:
                await report_inter.response.send_message("❌ 対戦当事者（募集者または挑戦者）のみが結果を報告できます。", ephemeral=True)
                return
            modal = MatchReportModal(self)
            await report_inter.response.send_modal(modal)
            
        report_button.callback = report_callback
        self.add_item(report_button)
        
        await interaction.response.edit_message(embed=embed, view=self)
        
        # チャンネルに対戦開始アナウンス
        await interaction.channel.send(
            f"⚔️ 対戦開始: {self.recruiter.mention} vs {self.challenger.mention} ！ 対戦が終わったら、上のメッセージのボタンから結果を報告してください。"
        )

    @discord.ui.button(label="募集キャンセル", style=discord.ButtonStyle.danger)
    async def cancel_match(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.recruiter.id:
            await interaction.response.send_message("❌ 募集のキャンセルは募集者本人のみ可能です。", ephemeral=True)
            return
            
        embed = discord.Embed(
            title="❌ 募集キャンセル (Cancelled)",
            description=f"{self.recruiter.mention} の対戦募集はキャンセルされました。",
            color=discord.Color.from_rgb(231, 76, 60) # 赤色
        )
        await interaction.response.edit_message(embed=embed, view=None)
        self.stop()

class PostMatchView(discord.ui.View):
    def __init__(self, recruiter: discord.Member, comment: str, format_str: str):
        super().__init__(timeout=600) # 10分以内に選択がなければ自動的に募集を締め切る
        self.recruiter = recruiter
        self.comment = comment
        self.format_str = format_str
        self.message = None

    async def on_timeout(self):
        if self.message is None:
            return
        embed = discord.Embed(
            title="⏱️ 募集締切 (Closed)",
            description=f"{self.recruiter.mention} の対戦募集は時間経過のため自動的に締め切られました。",
            color=discord.Color.from_rgb(127, 140, 141) # 灰色
        )
        try:
            await self.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="再募集する", style=discord.ButtonStyle.primary)
    async def re_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.recruiter.id:
            await interaction.response.send_message("❌ 再募集の選択は募集者本人のみ可能です。", ephemeral=True)
            return

        # 最新のレートを取得して再募集を作成
        user_info = await db_manager.get_or_create_user(self.recruiter.id, self.recruiter.display_name)
        rating = user_info["rating"] if "rating" in user_info.keys() else 1500.0

        embed = discord.Embed(
            title="⚔️ 対戦相手募集 (LFG)",
            description=f"{self.recruiter.mention} が対戦相手を再募集しています！\n「対戦を申し込む」ボタンを押すとマッチングが成立します。",
            color=discord.Color.from_rgb(52, 152, 219) # 青色
        )
        embed.set_thumbnail(url=self.recruiter.display_avatar.url)
        embed.add_field(name="募集者レート", value=f"`{round(rating, 1)}`", inline=True)
        embed.add_field(name="募集形式", value=self.format_str, inline=True)
        embed.add_field(name="コメント", value=self.comment, inline=False)

        new_view = RecruitView(
            recruiter=self.recruiter,
            recruiter_rating=rating,
            comment=self.comment,
            format_str=self.format_str
        )

        self.stop()
        await interaction.response.edit_message(embed=embed, view=new_view)

    @discord.ui.button(label="募集を締め切る", style=discord.ButtonStyle.secondary)
    async def close_recruit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.recruiter.id:
            await interaction.response.send_message("❌ 募集の締め切りは募集者本人のみ可能です。", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔒 募集締切 (Closed)",
            description=f"{self.recruiter.mention} の対戦募集は締め切られました。ありがとうございました！",
            color=discord.Color.from_rgb(127, 140, 141) # 灰色
        )
        self.stop()
        await interaction.response.edit_message(embed=embed, view=None)

class RecruitCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="recruit", description="対戦相手を募集します（マッチング自動化）")
    @app_commands.describe(
        comment="募集時のコメントや条件（任意）",
        format="対戦形式（例: 先二、先三、フリーなど。任意）"
    )
    async def recruit(self, interaction: discord.Interaction, comment: str = None, format: str = None):
        # 募集者の情報を取得/作成してレートを取得
        user_info = await db_manager.get_or_create_user(interaction.user.id, interaction.user.display_name)
        rating = user_info["rating"] if "rating" in user_info.keys() else 1500.0
        
        comment_val = comment or "募集中！お気軽にどうぞ！"
        format_val = format or "先二 (2本先取)"
        
        embed = discord.Embed(
            title="⚔️ 対戦相手募集 (LFG)",
            description=f"{interaction.user.mention} が対戦相手を募集しています！\n「対戦を申し込む」ボタンを押すとマッチングが成立します。",
            color=discord.Color.from_rgb(52, 152, 219) # 青色
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.add_field(name="募集者レート", value=f"`{round(rating, 1)}`", inline=True)
        embed.add_field(name="募集形式", value=format_val, inline=True)
        embed.add_field(name="コメント", value=comment_val, inline=False)
        
        view = RecruitView(
            recruiter=interaction.user,
            recruiter_rating=rating,
            comment=comment_val,
            format_str=format_val
        )
        
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(RecruitCog(bot))
