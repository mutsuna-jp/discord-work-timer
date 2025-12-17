import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import logging
from config import Config
from utils import format_duration, create_embed_from_config
from messages import Colors

logger = logging.getLogger(__name__)

# JSTの定義
JST = timezone(timedelta(hours=9))

class ContributionCog(commands.Cog):
    """GitHub風のコントリビューションカレンダーを表示するCog"""
    
    def __init__(self, bot):
        self.bot = bot

    def _get_color_block(self, seconds: int) -> str:
        """作業時間に応じて色ブロック（絵文字）を返す
        
        Args:
            seconds: 秒単位の作業時間
            
        Returns:
            色ブロック絵文字
        """
        if seconds == 0:
            return "⬜"  # 灰色（作業なし）
        elif seconds < 3600:  # 1時間未満
            return "🟩"  # 薄緑（少しの作業）
        elif seconds < 7200:  # 2時間未満
            return "🟦"  # 薄青（やや多い）
        elif seconds < 14400:  # 4時間未満
            return "🟪"  # 紫（さらに多い）
        else:
            return "🟥"  # 赤（多い）

    def _create_contribution_graph(self, data: dict) -> str:
        """過去7日間のコントリビューショングラフ（縦軸：4時間ごと）を作成
        
        Args:
            data: {date_str: total_seconds, ...} の辞書
            
        Returns:
            グラフを表現する文字列
        """
        graph_lines = []

        # 7日間の日付を取得
        today = datetime.now().date()
        start_date = today - timedelta(days=6)

        # 日付ヘッダー（MM/DD）
        date_labels = []
        for i in range(7):
            date = start_date + timedelta(days=i)
            date_labels.append(date.strftime('%m/%d'))

        # 行ラベル幅に合わせてヘッダをパディング
        bins = [ (20,24), (16,20), (12,16), (8,12), (4,8), (0,4) ]
        sample_label = f"{bins[0][0]:02d}-{bins[0][1]:02d}h |"
        label_width = len(sample_label) + 1
        header = " " * label_width + " " + " ".join(date_labels)
        graph_lines.append(header)

        # 縦軸: 4時間ごとのレンジ（上から表示）
        for start_h, end_h in bins:
            # ラベル幅を揃える
            row_label = f"{start_h:02d}-{end_h:02d}h |"
            row_cells = []
            for i in range(7):
                date = start_date + timedelta(days=i)
                seconds = data.get(date.isoformat(), 0)
                hours = seconds / 3600.0
                # その日の合計がこの行の開始時間以上なら塗りつぶす
                filled = hours >= start_h
                cell = "⬛" if filled else "⬜"
                row_cells.append(cell)

            graph_lines.append(f"{row_label} {' '.join(row_cells)}")

        # 凡例
        legend = (
            "```\n"
            "⬛ = その日の合計がその行の開始時間(以上)を満たす\n"
            "⬜ = 未満\n"
            "(行は4時間ごとの区間: 00-04, 04-08, ..., 20-24)\n"
            "```"
        )
        graph_lines.append(legend)

        return "\n".join(graph_lines)

    def _create_detailed_stats(self, data: dict) -> str:
        """詳細統計情報を作成
        
        Args:
            data: {date_str: total_seconds, ...} の辞書
            
        Returns:
            詳細統計を表現する文字列
        """
        today = datetime.now().date()
        start_date = today - timedelta(days=6)
        
        stats = []
        total_seconds = 0
        max_seconds = 0
        days_with_work = 0
        
        for i in range(7):
            date = start_date + timedelta(days=i)
            date_str = date.isoformat()
            seconds = data.get(date_str, 0)

            total_seconds += seconds
            if seconds > max_seconds:
                max_seconds = seconds
            if seconds > 0:
                days_with_work += 1

            # 日付と時間を表示（曜日表記を削除）
            time_str = format_duration(seconds, for_voice=False) if seconds > 0 else "0分"
            stats.append(f"  {date_str}: {time_str}")
        
        result = "\n".join(stats)
        result += f"\n\n**統計情報:**\n"
        result += f"  • 合計作業時間: {format_duration(total_seconds, for_voice=False)}\n"
        result += f"  • 最大1日の作業時間: {format_duration(max_seconds, for_voice=False)}\n"
        result += f"  • 作業した日数: {days_with_work}/7日"
        
        return result

    @app_commands.command(name="contribution", description="過去7日間のコントリビューショングラフを表示します")
    @app_commands.default_permissions(send_messages=True)
    async def contribution(self, interaction: discord.Interaction):
        """GitHub風のコントリビューショングラフを表示"""
        await interaction.response.defer(ephemeral=True)
        
        try:
            user_id = interaction.user.id
            
            # 過去7日間のデータを取得
            data = await self.bot.db.get_last_7_days_summary(user_id)
            
            # グラフを作成
            graph = self._create_contribution_graph(data)
            stats = self._create_detailed_stats(data)
            
            # Embedを作成
            embed = discord.Embed(
                title="📊 過去7日間のコントリビューション",
                description=f"**{interaction.user.display_name}さんの作業ログ**",
                color=Colors.BLUE
            )
            
            embed.add_field(
                name="グラフ",
                value=graph,
                inline=False
            )
            
            embed.add_field(
                name="詳細",
                value=stats,
                inline=False
            )
            
            embed.set_footer(text="📅は過去7日間（本日を含む）です")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"Contribution graph shown for user {user_id}")
            
        except Exception as e:
            logger.error(f"コントリビューション表示エラー: {e}")
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(ContributionCog(bot))
