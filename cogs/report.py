import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, time, timezone
import os
from utils import format_duration, delete_previous_message, safe_message_delete, create_embed_from_config
from messages import MESSAGES

# JSTの定義
JST = timezone(timedelta(hours=9))

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rank_msg_tracker = {}
        
        # 設定値を読み込み (デフォルト値を使用)
        self.daily_report_hour = getattr(bot, 'DAILY_REPORT_HOUR', 23)
        self.daily_report_minute = getattr(bot, 'DAILY_REPORT_MINUTE', 59)
        self.keep_log_days = getattr(bot, 'KEEP_LOG_DAYS', 30)
        self.pending_vc_clears = set()
        
        # タスクを開始
        self.daily_report_task.change_interval(time=time(hour=self.daily_report_hour, minute=self.daily_report_minute, tzinfo=JST))
        self.daily_report_task.start()

    def cog_unload(self):
        self.daily_report_task.cancel()

    @app_commands.command(name="rank", description="週間ランキングを表示します")
    async def rank(self, interaction: discord.Interaction):
        """週間ランキングを表示"""
        # インタラクションへの応答はこれで行う（DM送信するので、ここではEphemeralな応答をする）
        await interaction.response.defer(ephemeral=True)
        
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        monday_str = monday.isoformat()

        rows = await self.bot.db.execute(
            '''SELECT username, SUM(duration_seconds) as total_time
               FROM study_logs
               WHERE created_at >= ?
               GROUP BY user_id
               ORDER BY total_time DESC
               LIMIT 10''',
            (monday_str,),
            fetch_all=True
        )

        if not rows:
            msg = MESSAGES.get("rank", {}).get("empty_message", "データがありません")
            # Ephemeral (自分だけに見える) メッセージとして送信
            await interaction.followup.send(msg, ephemeral=True)
            return

        rank_config = MESSAGES.get("rank", {})
        embed = create_embed_from_config(rank_config)
        
        rank_text = ""
        row_fmt = rank_config.get("row", "{icon} **{name}**: {time}\n")
        
        for i, (username, total_seconds) in enumerate(rows, 1):
            time_str = format_duration(total_seconds, for_voice=True)
            icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            rank_text += row_fmt.format(icon=icon, name=username, time=time_str)
        
        embed.add_field(name="Top Members", value=rank_text, inline=False)
        
        # Ephemeral (自分だけに見える) メッセージとして送信
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="あなたの累計作業時間を表示します")
    async def stats(self, interaction: discord.Interaction):
        """個別統計を表示"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        
        total_result = await self.bot.db.execute(
            '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        total_seconds = total_result[0] if total_result and total_result[0] else 0
        
        first_date_result = await self.bot.db.execute(
            '''SELECT MIN(created_at) FROM study_logs WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        first_date_str = first_date_result[0] if first_date_result else None

        time_str = format_duration(total_seconds, for_voice=False)
        
        if first_date_str:
            first_date = datetime.fromisoformat(first_date_str)
            days_since = (datetime.now() - first_date).days
            date_disp = first_date.strftime('%Y/%m/%d')
        else:
            date_disp = "---"
            days_since = 0

        stats_config = MESSAGES.get("stats", {})
        embed = create_embed_from_config(
            stats_config,
            name=interaction.user.display_name,
            total_time=time_str,
            date=date_disp,
            days=days_since
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        # Ephemeral (自分だけに見える) メッセージとして送信
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="daily_report", description="[管理者用] 日報とバックアップを手動実行します")
    @app_commands.describe(days_offset="何日前のデータとして実行するか (例: 1 = 昨日)")
    @app_commands.default_permissions(administrator=True)
    async def manual_daily_report(self, interaction: discord.Interaction, days_offset: int = 0):
        """手動で日報・バックアップを実行"""
        # BACKUP_CHANNEL_ID でのみ実行可能にする
        backup_channel_id = getattr(self.bot, 'BACKUP_CHANNEL_ID', 0)
        if backup_channel_id and interaction.channel_id != backup_channel_id:
            await interaction.response.send_message(
                f"このコマンドはバックアップチャンネル <#{backup_channel_id}> でのみ実行可能です。",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        
        target_date = datetime.now()
        if days_offset > 0:
            target_date = target_date - timedelta(days=days_offset)
            
        await self.execute_daily_report(target_date)
        await interaction.followup.send(f"日報とバックアップの実行が完了しました (対象: {target_date.strftime('%Y/%m/%d')})")

    @tasks.loop(time=time(hour=23, minute=59, tzinfo=JST))
    async def daily_report_task(self):
        """毎日日報を送信し、ログをクリーンアップ"""
        await self.execute_daily_report(datetime.now())

    async def execute_daily_report(self, now: datetime):
        summary_channel_id = getattr(self.bot, 'SUMMARY_CHANNEL_ID', 0)
        channel = self.bot.get_channel(summary_channel_id)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.isoformat()
        today_date_str = now.strftime('%Y-%m-%d')
        today_disp_str = now.strftime('%Y/%m/%d')

        # DB Execute expects str usually for safe comparison
        rows = await self.bot.db.execute(
            '''SELECT user_id, username, SUM(duration_seconds) as total_time 
               FROM study_logs 
               WHERE created_at >= ? 
               GROUP BY user_id 
               ORDER BY total_time DESC''',
            (today_str,),
            fetch_all=True
        )

        if channel:
            if not rows:
                msg = MESSAGES.get("report", {}).get("empty_message", "本日の作業はありませんでした。")
                await channel.send(msg)
            else:
                report_config = MESSAGES.get("report", {})
                embed = create_embed_from_config(
                    report_config,
                    date=today_disp_str
                )
                
                report_text = ""
                row_fmt = report_config.get("row", "• **{name}**: {time}\n")
                
                for _, username, total_seconds in rows:
                    time_str = format_duration(total_seconds, for_voice=True)
                    report_text += row_fmt.format(name=username, time=time_str)
                
                embed.add_field(name="Results", value=report_text, inline=False)
                await channel.send(embed=embed)
        
        # データベースに日報を保存 & クリーンアップ
        logs_deleted = 0
        summary_deleted = 0
        db_size_mb = 0
        
        # Custom DB logic for batch operation
        # Custom DB logic for batch operation
        if rows:
            for user_id, username, total_seconds in rows:
                await self.bot.db.execute(
                    '''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) 
                       VALUES (?, ?, ?, ?)''',
                    (user_id, username, today_date_str, total_seconds)
                )
        
        # 古いDaily Summaryデータを削除
        cleanup_summary_threshold = now - timedelta(days=365)
        cleanup_summary_threshold_str = cleanup_summary_threshold.strftime('%Y-%m-%d')
        summary_deleted = await self.bot.db.execute("DELETE FROM daily_summary WHERE date < ?", (cleanup_summary_threshold_str,))
        if summary_deleted is None:
            summary_deleted = 0
        
        # 古いログを削除
        cleanup_threshold = now - timedelta(days=self.keep_log_days)
        logs_deleted = await self.bot.db.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold.isoformat(),))
        if logs_deleted is None:
            logs_deleted = 0
            
        # VACUUM を実行
        await self.bot.db.execute_script("VACUUM")
        
        # データベースサイズを監視
        db_path = self.bot.db.db_path
        db_size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        db_size_mb = db_size_bytes / (1024 * 1024)
        print(f"📊 DBクリーンアップ完了 - スタディログ削除: {logs_deleted}件, DB容量: {db_size_mb:.2f} MB")

        await self.send_database_backup(today_date_str, today_disp_str, logs_deleted, summary_deleted, db_size_mb)

        # VCチャットのクリーンアップ
        await self.cleanup_vc_chats()

    async def send_database_backup(self, today_date_str, today_disp_str, logs_deleted=0, summary_deleted=0, db_size_mb=0):
        """データベースのバックアップをチャネルに送信"""
        backup_channel_id = getattr(self.bot, 'BACKUP_CHANNEL_ID', 0)
        backup_channel = self.bot.get_channel(backup_channel_id)
        db_path = self.bot.db.db_path

        if backup_channel and os.path.exists(db_path):
            try:
                embed = discord.Embed(
                    title="🔒 データベース自動バックアップ",
                    description=f"{today_disp_str} の日次バックアップとクリーンアップを実行しました",
                    color=0x36393F
                )
                
                cleanup_info = f"""**スタディログ削除:** {logs_deleted}件
**Daily Summary削除:** {summary_deleted}件
**DB容量:** {db_size_mb:.2f} MB"""
                
                embed.add_field(name="📊 クリーンアップ情報", value=cleanup_info, inline=False)
                embed.set_footer(text="自動実行")
                
                backup_filename = f"backup_{today_date_str}.db"
                file = discord.File(db_path, filename=backup_filename)
                await backup_channel.send(embed=embed, file=file)
                print("バックアップ送信完了")
            except Exception as e:
                print(f"バックアップ送信エラー: {e}")

    async def cleanup_vc_chats(self):
        """全てのVCチャットをクリーンアップ（人がいる場合は待機）"""
        print("VCチャットのクリーンアップを開始します...")
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                # 権限チェック
                permissions = vc.permissions_for(guild.me)
                if not permissions.manage_messages or not permissions.read_messages:
                    continue
                
                if len(vc.members) == 0:
                    try:
                        await vc.purge(limit=None)
                        # pendingにあれば削除
                        self.pending_vc_clears.discard(vc.id)
                    except Exception as e:
                        print(f"VCチャット削除エラー ({vc.name}): {e}")
                else:
                    self.pending_vc_clears.add(vc.id)
                    print(f"VCチャット削除待機 ({vc.name}): {len(vc.members)}名が参加中")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # 退出時にペンディングリストにあるか確認
        if before.channel and before.channel.id in self.pending_vc_clears:
             if len(before.channel.members) == 0:
                 try:
                     print(f"参加者がいなくなったため、チャットを削除します: {before.channel.name}")
                     await before.channel.purge(limit=None)
                 except Exception as e:
                     print(f"VCチャット削除エラー ({before.channel.name}): {e}")
                 finally:
                     self.pending_vc_clears.discard(before.channel.id)

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
