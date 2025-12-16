import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, time, timezone
import os
import asyncio
import logging
from config import Config
from utils import format_duration, delete_previous_message, safe_message_delete, create_embed_from_config
from messages import MESSAGES, Colors

logger = logging.getLogger(__name__)

# JSTの定義
JST = timezone(timedelta(hours=9))

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rank_msg_tracker = {}
        self.pending_vc_clears = set()
        
        # タスクを開始
        # 日報: 翌朝 7:00
        self.daily_report_task.change_interval(time=time(hour=7, minute=0, tzinfo=JST))
        self.daily_report_task.start()

        # バックアップ: 設定時刻 (23:59)
        self.backup_task.change_interval(time=time(hour=Config.DAILY_REPORT_HOUR, minute=Config.DAILY_REPORT_MINUTE, tzinfo=JST))
        self.backup_task.start()

        # 警告: バックアップ5分前 (23:54)
        warn_time = time(hour=Config.DAILY_REPORT_HOUR, minute=max(0, Config.DAILY_REPORT_MINUTE - 5), tzinfo=JST)
        self.warning_task.change_interval(time=warn_time)
        self.warning_task.start()

    def cog_unload(self):
        self.daily_report_task.cancel()
        self.backup_task.cancel()
        self.warning_task.cancel()

    @app_commands.command(name="rank", description="週間ランキングを表示します")
    @app_commands.default_permissions(send_messages=True)
    async def rank(self, interaction: discord.Interaction):
        """週間ランキングを表示"""
        await interaction.response.defer(ephemeral=True)
        
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        monday_str = monday.isoformat()

        rows = await self.bot.db.get_weekly_ranking(monday_str)

        if not rows:
            msg = MESSAGES.get("rank", {}).get("empty_message", "データがありません")
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
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="あなたの累計作業時間を表示します")
    @app_commands.default_permissions(send_messages=True)
    async def stats(self, interaction: discord.Interaction):
        """個別統計を表示"""
        await interaction.response.defer(ephemeral=True)

        user_id = interaction.user.id
        
        total_seconds = await self.bot.db.get_total_seconds(user_id)
        first_date_str = await self.bot.db.get_first_log_date(user_id)

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
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="daily_report", description="[管理者用] 日報を手動送信します")
    @app_commands.describe(days_offset="何日前のデータとして実行するか (例: 1 = 昨日)")
    @app_commands.default_permissions(administrator=True)
    async def manual_daily_report(self, interaction: discord.Interaction, days_offset: int = 1):
        """手動で日報を実行"""
        backup_channel_id = Config.BACKUP_CHANNEL_ID
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
            
        await self.send_daily_report(target_date)
        await interaction.followup.send(f"日報の送信が完了しました (対象: {target_date.strftime('%Y/%m/%d')})")

    @app_commands.command(name="backup", description="[管理者用] バックアップとクリーンアップを手動実行します")
    @app_commands.default_permissions(administrator=True)
    async def manual_backup(self, interaction: discord.Interaction):
        """手動でバックアップを実行"""
        backup_channel_id = Config.BACKUP_CHANNEL_ID
        if backup_channel_id and interaction.channel_id != backup_channel_id:
            await interaction.response.send_message(
                f"このコマンドはバックアップチャンネル <#{backup_channel_id}> でのみ実行可能です。",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        await self.perform_backup(datetime.now())
        await interaction.followup.send("バックアップとクリーンアップが完了しました。")

    @tasks.loop(time=time(hour=7, minute=0, tzinfo=JST))
    async def daily_report_task(self):
        """毎朝7時に前日の日報を送信"""
        yesterday = datetime.now() - timedelta(days=1)
        await self.send_daily_report(yesterday)

    @tasks.loop(time=time(hour=23, minute=54, tzinfo=JST))
    async def warning_task(self):
        """23:54にVC参加ユーザーへ通知"""
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        try:
                            embed = discord.Embed(
                                title="🕒 日次集計のお知らせ",
                                description="まもなく (23:59) 本日の作業時間の集計が行われます。\n通話はそのまま継続してご利用いただけます。",
                                color=Colors.YELLOW
                            )
                            await member.send(embed=embed)
                        except Exception as e:
                            logger.error(f"DM送信失敗 ({member.display_name}): {e}")

    @tasks.loop(time=time(hour=23, minute=59, tzinfo=JST))
    async def backup_task(self):
        """毎日バックアップを実行し、ログをクリーンアップ (ソフトメンテナンス)"""
        logger.info("日次メンテナンス: 日次集計処理を開始...")
        
        study_cog = self.bot.get_cog("StudyCog")
        log_channel = self.bot.get_channel(Config.LOG_CHANNEL_ID)
        now = datetime.now()
        processed_count = 0

        if study_cog:
            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    for member in vc.members:
                        if member.bot:
                            continue
                        
                        # 記録中のユーザーのみ処理
                        if member.id in study_cog.voice_state_log:
                            try:
                                join_time = study_cog.voice_state_log[member.id]
                                duration = now - join_time
                                total_seconds = int(duration.total_seconds())
                                
                                # セッション保存
                                await self.bot.db.add_study_log(
                                    member.id,
                                    member.display_name,
                                    join_time,
                                    total_seconds,
                                    now
                                )
                                
                                # 称号チェック
                                await study_cog.check_and_award_milestones(member, total_seconds, log_channel)

                                # 論理分割: 保存した分をオフセットに追加し、開始時間を現在に更新
                                # これにより表示上の「継続時間」は途切れない
                                current_offset = study_cog.voice_state_offset.get(member.id, 0)
                                study_cog.voice_state_offset[member.id] = current_offset + total_seconds
                                study_cog.voice_state_log[member.id] = now
                                
                                processed_count += 1
                                
                            except Exception as e:
                                logger.error(f"日次集計エラー ({member.display_name}): {e}")
            
            if processed_count > 0:
                logger.info(f"{processed_count}名のセッションを分割しました。")
        else:
            logger.error("StudyCogが見つかりません。セッション分割をスキップします。")

        await self.perform_backup(datetime.now())

    async def send_daily_report(self, target_date: datetime):
        """日報Embedを作成して送信"""
        channel = self.bot.get_channel(Config.SUMMARY_CHANNEL_ID)
        
        start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
        start_str = start_of_day.isoformat()
        
        end_of_day = start_of_day + timedelta(days=1)
        end_str = end_of_day.isoformat()

        rows = await self.bot.db.get_study_logs_in_range(start_str, end_str)
        today_disp_str = target_date.strftime('%Y/%m/%d')

        if channel:
            if not rows:
                msg = MESSAGES.get("report", {}).get("empty_message", "本日の作業はありませんでした。")
                await channel.send(f"**[{today_disp_str}]** {msg}")
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

    async def perform_backup(self, now: datetime):
        """バックアップとメンテナンス実行"""
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.isoformat()
        today_date_str = now.strftime('%Y-%m-%d')
        today_disp_str = now.strftime('%Y/%m/%d')

        # 集計
        rows = await self.bot.db.get_study_logs_in_range(today_str)
        
        if rows:
            for user_id, username, total_seconds in rows:
                await self.bot.db.save_daily_summary(user_id, username, today_date_str, total_seconds)
        
        # 削除閾値
        cleanup_summary_threshold = now - timedelta(days=365)
        cleanup_summary_threshold_str = cleanup_summary_threshold.strftime('%Y-%m-%d')
        
        cleanup_threshold = now - timedelta(days=Config.KEEP_LOG_DAYS)
        cleanup_threshold_str = cleanup_threshold.isoformat()

        # クリーンアップ実行
        logs_deleted, summary_deleted = await self.bot.db.cleanup_old_data(cleanup_threshold_str, cleanup_summary_threshold_str)

        # データベースサイズ
        db_path = self.bot.db.db_path
        db_size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        db_size_mb = db_size_bytes / (1024 * 1024)
        logger.info(f"📊 DBクリーンアップ完了 - スタディログ削除: {logs_deleted}件, DB容量: {db_size_mb:.2f} MB")

        await self.send_database_backup(today_date_str, today_disp_str, logs_deleted, summary_deleted, db_size_mb)

        await self.cleanup_vc_chats()
        
        # ログチャンネルのクリーンアップ
        log_channel = self.bot.get_channel(Config.LOG_CHANNEL_ID)
        if log_channel:
            try:
                await log_channel.purge(limit=None)
                logger.info(f"ログチャンネル {log_channel.name} をクリーンアップしました。")
            except Exception as e:
                logger.error(f"ログチャンネル削除エラー: {e}")

    async def send_database_backup(self, today_date_str, today_disp_str, logs_deleted=0, summary_deleted=0, db_size_mb=0):
        """データベースのバックアップをチャネルに送信"""
        backup_channel = self.bot.get_channel(Config.BACKUP_CHANNEL_ID)
        db_path = self.bot.db.db_path

        if backup_channel and os.path.exists(db_path):
            try:
                embed = discord.Embed(
                    title="🔒 データベース自動バックアップ",
                    description=f"{today_disp_str} の日次バックアップとクリーンアップを実行しました",
                    color=Colors.DARK_GRAY
                )
                
                cleanup_info = f"""**スタディログ削除:** {logs_deleted}件
**Daily Summary削除:** {summary_deleted}件
**DB容量:** {db_size_mb:.2f} MB"""
                
                embed.add_field(name="📊 クリーンアップ情報", value=cleanup_info, inline=False)
                embed.set_footer(text="自動実行")
                
                backup_filename = f"backup_{today_date_str}.db"
                file = discord.File(db_path, filename=backup_filename)
                await backup_channel.send(embed=embed, file=file)
                logger.info("バックアップ送信完了")
            except Exception as e:
                logger.error(f"バックアップ送信エラー: {e}")

    async def cleanup_vc_chats(self):
        """全てのVCチャットをクリーンアップ（人がいる場合は待機）"""
        logger.info("VCチャットのクリーンアップを開始します...")
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                permissions = vc.permissions_for(guild.me)
                if not permissions.manage_messages or not permissions.read_messages:
                    continue
                
                if len(vc.members) == 0:
                    try:
                        await vc.purge(limit=None)
                        self.pending_vc_clears.discard(vc.id)
                    except Exception as e:
                        logger.error(f"VCチャット削除エラー ({vc.name}): {e}")
                else:
                    self.pending_vc_clears.add(vc.id)
                    logger.info(f"VCチャット削除待機 ({vc.name}): {len(vc.members)}名が参加中")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and before.channel.id in self.pending_vc_clears:
             if len(before.channel.members) == 0:
                 try:
                     logger.info(f"参加者がいなくなったため、チャットを削除します: {before.channel.name}")
                     await before.channel.purge(limit=None)
                 except Exception as e:
                     logger.error(f"VCチャット削除エラー ({before.channel.name}): {e}")
                 finally:
                     self.pending_vc_clears.discard(before.channel.id)

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
