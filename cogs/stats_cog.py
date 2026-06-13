import discord
from discord import app_commands
from discord.ext import commands
from database import db_manager

class StatsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="stats", description="指定ユーザー（または自分）の戦績詳細を表示します")
    @app_commands.describe(user="戦績を表示したいユーザーを選択してください (指定しない場合は自分)")
    async def stats(self, interaction: discord.Interaction, user: discord.Member = None):
        target_user = user or interaction.user
        
        # レスポンス待機状態にする
        await interaction.response.defer()
        
        try:
            # ユーザー情報の取得（作成）
            await db_manager.get_or_create_user(target_user.id, target_user.display_name)
            
            # 統計データの取得
            stats_data = await db_manager.get_user_stats(target_user.id)
            
            if stats_data["total_matches"] == 0:
                embed = discord.Embed(
                    title=f"📊 {target_user.display_name} 殿の戦績スタッツ",
                    description="まだデータベースに戦績が登録されていません。\n`/report` コマンドで対戦結果を登録してみましょう！",
                    color=discord.Color.from_rgb(52, 152, 219) # 青色
                )
                embed.set_thumbnail(url=target_user.display_avatar.url)
                await interaction.followup.send(embed=embed)
                return
                
            # メインEmbedの作成
            embed = discord.Embed(
                title=f"📊 {target_user.display_name} 殿の戦績スタッツ",
                color=discord.Color.from_rgb(52, 152, 219)
            )
            embed.set_thumbnail(url=target_user.display_avatar.url)
            
            # 1. 総合戦績の表示
            win_rate = stats_data["win_rate"]
            wins = stats_data["wins"]
            losses = stats_data["losses"]
            total = stats_data["total_matches"]
            user_rating = user_info["rating"] if "rating" in user_info.keys() else 1500.0
            
            # ビジュアルゲージの作成 (10文字分)
            bar_length = 10
            filled_length = int(bar_length * (win_rate / 100))
            # 🟢が勝ち、🔴が負け
            gauge = "🟢" * filled_length + "🔴" * (bar_length - filled_length)
            
            embed.add_field(
                name="総合戦績",
                value=f"**レーティング:** `{round(user_rating, 1)}` (初期値: 1500)\n"
                      f"**総対戦数:** `{total}` 戦\n"
                      f"**勝敗数:** `{wins}` 勝 `{losses}` 敗\n"
                      f"**勝率:** `{win_rate}%`\n"
                      f"**ゲージ:** {gauge}",
                inline=False
            )
            
            # 2. キャラクター別戦績 (上位3キャラ)
            char_stats = stats_data["character_stats"]
            if char_stats:
                sorted_chars = sorted(char_stats.items(), key=lambda x: x[1]["played"], reverse=True)
                char_text = ""
                for char_name, c_data in sorted_chars[:3]:
                    c_win_rate = (c_data["wins"] / c_data["played"]) * 100 if c_data["played"] > 0 else 0
                    char_text += f"• **{char_name}**: `{c_data['played']}`戦 `{c_data['wins']}`勝 `{c_data['losses']}`敗 (勝率 `{round(c_win_rate, 1)}%`)\n"
                embed.add_field(name="使用キャラTOP3", value=char_text, inline=True)
            else:
                embed.add_field(name="使用キャラ", value="*データなし*", inline=True)
                
            # 3. 対戦相手別戦績 (上位3名)
            h2h_stats = stats_data["head_to_head"]
            if h2h_stats:
                sorted_h2h = sorted(h2h_stats.values(), key=lambda x: x["played"], reverse=True)
                h2h_text = ""
                for h_data in sorted_h2h[:3]:
                    h_win_rate = (h_data["wins"] / h_data["played"]) * 100 if h_data["played"] > 0 else 0
                    h2h_text += f"• **{h_data['username']}**: `{h_data['played']}`戦 `{h_data['wins']}`勝 `{h_data['losses']}`敗 (勝率 `{round(h_win_rate, 1)}%`)\n"
                embed.add_field(name="よく戦う相手TOP3", value=h2h_text, inline=True)
            else:
                embed.add_field(name="対戦相手", value="*データなし*", inline=True)
                
            # 4. 直近の対戦履歴 (最大5件)
            recent_list = stats_data["recent_history"]
            if recent_list:
                history_text = ""
                for m in recent_list:
                    result_emoji = "🟢" if m["is_win"] else "🔴"
                    my_char_display = f"({m['my_char']})" if m['my_char'] else ""
                    opp_char_display = f"({m['opponent_char']})" if m['opponent_char'] else ""
                    
                    history_text += (
                        f"`ID:{m['match_id']}` {result_emoji} **{m['my_score']} - {m['opponent_score']}** "
                        f"vs **{m['opponent_name']}** {my_char_display} vs {opp_char_display} *({m['date']})*\n"
                    )
                embed.add_field(name="直近の対戦履歴", value=history_text, inline=False)
                
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ 戦績データの取得中にエラーが発生しました: {e}")

    @app_commands.command(name="leaderboard", description="サーバー内の戦績ランキングを表示します")
    @app_commands.describe(min_matches="最低必要対戦数 (デフォルト: 1)")
    async def leaderboard(self, interaction: discord.Interaction, min_matches: int = 1):
        # レスポンス待機状態にする
        await interaction.response.defer()
        
        try:
            leaderboard_data = await db_manager.get_leaderboard(min_matches)
            
            if not leaderboard_data:
                embed = discord.Embed(
                    title="🏆 サーバー戦績リーダーボード",
                    description=f"該当するプレイヤーがいません（最低対戦数: `{min_matches}` 戦）。",
                    color=discord.Color.from_rgb(241, 196, 15) # 金色
                )
                await interaction.followup.send(embed=embed)
                return
                
            embed = discord.Embed(
                title="🏆 サーバー戦績リーダーボード",
                description=f"レーティング（強さの数値）順に並んでいます (最低対戦数: `{min_matches}` 戦)",
                color=discord.Color.from_rgb(241, 196, 15)
            )
            
            leaderboard_text = ""
            for i, p in enumerate(leaderboard_data[:15]): # 上位15名を表示
                # 順位の絵文字
                if i == 0:
                    rank_emoji = "🥇"
                elif i == 1:
                    rank_emoji = "🥈"
                elif i == 2:
                    rank_emoji = "🥉"
                else:
                    rank_emoji = f"`#{i+1}`"
                    
                leaderboard_text += (
                    f"{rank_emoji} **{p['username']}** : "
                    f"レート `{p['rating']}` (勝率 `{p['win_rate']}%` / `{p['wins']}勝-{p['losses']}敗 / 総数 {p['total']})\n"
                )
                
            embed.add_field(name="ランキング", value=leaderboard_text, inline=False)
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            await interaction.followup.send(f"❌ リーダーボードの集計中にエラーが発生しました: {e}")

async def setup(bot):
    await bot.add_cog(StatsCog(bot))
