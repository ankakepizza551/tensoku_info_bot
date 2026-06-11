import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import db_manager

CHARACTERS = [
    "博麗霊夢", "霧雨魔理沙", "十六夜咲夜", "アリス", "パチュリー",
    "魂魄妖夢", "レミリア", "西行寺幽々子", "八雲紫", "伊吹萃香",
    "鈴仙", "射命丸文", "小野塚小町", "比那名居天子", "永江衣玖",
    "東風谷早苗", "チルノ", "紅美鈴", "霊烏路空", "洩矢諏訪子"
]

async def character_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """キャラクター名のオートコンプリート"""
    return [
        app_commands.Choice(name=char, value=char)
        for char in CHARACTERS if current.lower() in char.lower()
    ][:25]

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="report", description="対戦結果（戦績）を報告・記録します")
    @app_commands.describe(
        opponent="対戦相手のユーザーを選択してください",
        my_score="自分の勝利本数",
        opponent_score="相手の勝利本数",
        my_char="あなたの使用キャラクター (任意)",
        opponent_char="相手の使用キャラクター (任意)"
    )
    @app_commands.autocomplete(my_char=character_autocomplete, opponent_char=character_autocomplete)
    async def report(self, interaction: discord.Interaction, 
                     opponent: discord.Member, 
                     my_score: int, 
                     opponent_score: int, 
                     my_char: str = None, 
                     opponent_char: str = None):
        
        # 基本入力値チェック
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("❌ 自分自身との戦績は報告できません！", ephemeral=True)
            return
            
        if my_score < 0 or opponent_score < 0:
            await interaction.response.send_message("❌ スコアに負の数値は入力できません！", ephemeral=True)
            return

        # 自分の情報を取得/作成
        player1_id = interaction.user.id
        player1_name = interaction.user.display_name
        
        # 相手の情報を取得/作成
        player2_id = opponent.id
        player2_name = opponent.display_name
        
        # データベースに登録
        try:
            match_id = await db_manager.add_match(
                reporter_id=player1_id,
                player1_id=player1_id,
                player1_name=player1_name,
                player2_id=player2_id,
                player2_name=player2_name,
                score1=my_score,
                score2=opponent_score,
                char1=my_char,
                char2=opponent_char
            )
            
            # 結果表示用Embedの作成
            embed = discord.Embed(
                title="📊 戦績登録完了",
                description=f"対戦結果がデータベースに保存されました！\n**対戦ID (Match ID):** `{match_id}`",
                color=discord.Color.from_rgb(46, 204, 113) # 緑色
            )
            
            # 勝敗のテキスト表示
            if my_score > opponent_score:
                winner_text = f"🏆 **{player1_name}** の勝利！"
            elif opponent_score > my_score:
                winner_text = f"🏆 **{player2_name}** の勝利！"
            else:
                winner_text = "🤝 **引き分け！**"
                
            embed.add_field(name="結果", value=winner_text, inline=False)
            
            # 詳細スコアの表示
            char1_display = f" ({my_char})" if my_char else ""
            char2_display = f" ({opponent_char})" if opponent_char else ""
            
            embed.add_field(
                name=player1_name,
                value=f"使用キャラ: `{my_char or '未設定'}`\n獲得本数: **{my_score}**",
                inline=True
            )
            embed.add_field(
                name=player2_name,
                value=f"使用キャラ: `{opponent_char or '未設定'}`\n獲得本数: **{opponent_score}**",
                inline=True
            )
            
            # 報告者情報の表示
            embed.set_footer(text=f"報告者: {interaction.user.name} | 間違えた場合は /delete_match で削除できます")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ 戦績の登録中にエラーが発生しました: {e}", ephemeral=True)

    @app_commands.command(name="delete_match", description="間違えて登録した戦績をID指定で削除します")
    @app_commands.describe(match_id="削除する対戦のIDを入力してください")
    async def delete_match(self, interaction: discord.Interaction, match_id: int):
        try:
            # 該当の試合があるか、および報告者か管理者かを確認
            match_data = await db_manager.get_match(match_id)
            if not match_data:
                await interaction.response.send_message(f"❌ 対戦ID `{match_id}` の戦績が見つかりませんでした。", ephemeral=True)
                return
                
            # 権限チェック (報告者本人、またはサーバーの管理者)
            is_reporter = (match_data["reporter_id"] == interaction.user.id)
            is_admin = interaction.user.guild_permissions.administrator
            
            if not (is_reporter or is_admin):
                await interaction.response.send_message("❌ この戦績を削除する権限がありません（報告者本人または管理者のみ削除可能です）。", ephemeral=True)
                return
                
            # 削除の実行
            success = await db_manager.delete_match(match_id)
            if success:
                # 削除完了Embed
                embed = discord.Embed(
                    title="🗑️ 戦績削除完了",
                    description=f"対戦ID `{match_id}` の戦績をデータベースから削除しました。",
                    color=discord.Color.from_rgb(231, 76, 60) # 赤色
                )
                
                # 詳細情報の埋め込み
                async with aiosqlite.connect(db_manager.DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    # 既に削除されているので詳細は簡易表示
                    p1_id = match_data["player1_id"]
                    p2_id = match_data["player2_id"]
                    async with db.execute("SELECT username FROM users WHERE user_id = ?", (p1_id,)) as c1:
                        u1 = await c1.fetchone()
                    async with db.execute("SELECT username FROM users WHERE user_id = ?", (p2_id,)) as c2:
                        u2 = await c2.fetchone()
                        
                    name1 = u1["username"] if u1 else f"User {p1_id}"
                    name2 = u2["username"] if u2 else f"User {p2_id}"
                    
                embed.add_field(name="削除された対戦", value=f"{name1} `{match_data['score1']}` vs `{match_data['score2']}` {name2}", inline=False)
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message(f"❌ 対戦ID `{match_id}` の戦績削除に失敗しました。", ephemeral=True)
                
        except Exception as e:
            await interaction.response.send_message(f"❌ 削除中にエラーが発生しました: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
