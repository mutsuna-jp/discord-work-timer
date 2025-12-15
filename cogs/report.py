import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, time
import os
from utils import format_duration, delete_previous_message, safe_message_delete
from messages import MESSAGES

class ReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rank_msg_tracker = {}
        
        # 設定値を読み込み (デフォルト値を使用)
        self.daily_report_hour = getattr(bot, 'DAILY_REPORT_HOUR', 23)
        self.daily_report_minute = getattr(bot, 'DAILY_REPORT_MINUTE', 59)
        self.keep_log_days = getattr(bot, 'KEEP_LOG_DAYS', 30)
        
        # タスクを開始
        self.daily_report_task.change_interval(time=time(hour=self.daily_report_hour, minute=self.daily_report_minute))
        self.daily_report_task.start()

    def cog_unload(self):
        self.daily_report_task.cancel()

    @commands.command()
    async def rank(self, ctx):
        """週間ランキングを表示"""
        await safe_message_delete(ctx.message)
        
        now = datetime.now()
        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        monday_str = monday.isoformat()

        rows = self.bot.db.execute(
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
            await ctx.send(MESSAGES["rank"]["empty_message"])
            return

        embed = discord.Embed(
            title=MESSAGES["rank"]["embed_title"],
            description=MESSAGES["rank"]["embed_desc"],
            color=MESSAGES["rank"]["embed_color"]
        )
        
        rank_text = ""
        for i, (username, total_seconds) in enumerate(rows, 1):
            time_str = format_duration(total_seconds, for_voice=True)
            icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            rank_text += MESSAGES["rank"]["row"].format(icon=icon, name=username, time=time_str)
        
        embed.add_field(name="Top Members", value=rank_text, inline=False)
        
        # 前回のランクメッセージを削除
        log_channel_id = getattr(self.bot, 'LOG_CHANNEL_ID', 0)
        text_channel = self.bot.get_channel(log_channel_id)
        
        if text_channel and ctx.author.id in self.rank_msg_tracker:
            await delete_previous_message(text_channel, self.rank_msg_tracker[ctx.author.id])
        
        # 新しいランクメッセージを送信して記録
        rank_msg = await ctx.send(embed=embed)
        self.rank_msg_tracker[ctx.author.id] = rank_msg.id

    @commands.command()
    async def stats(self, ctx):
        """個別統計を表示"""
        await safe_message_delete(ctx.message)

        user_id = ctx.author.id
        
        total_result = self.bot.db.execute(
            '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ?''',
            (user_id,),
            fetch_one=True
        )
        total_seconds = total_result[0] if total_result and total_result[0] else 0
        
        first_date_result = self.bot.db.execute(
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

        embed = discord.Embed(
            title=MESSAGES["stats"]["embed_title"].format(name=ctx.author.display_name),
            description=MESSAGES["stats"]["embed_desc"],
            color=MESSAGES["stats"]["embed_color"]
        )
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.add_field(
            name=MESSAGES["stats"]["fields"][0]["name"], 
            value=MESSAGES["stats"]["fields"][0]["value"].format(total_time=time_str), 
            inline=False
        )
        embed.add_field(
            name=MESSAGES["stats"]["fields"][1]["name"], 
            value=MESSAGES["stats"]["fields"][1]["value"].format(date=date_disp, days=days_since), 
            inline=False
        )
        
        await ctx.author.send(embed=embed)

    @tasks.loop(time=time(hour=23, minute=59))
    async def daily_report_task(self):
        """毎日日報を送信し、ログをクリーンアップ"""
        summary_channel_id = getattr(self.bot, 'SUMMARY_CHANNEL_ID', 0)
        channel = self.bot.get_channel(summary_channel_id)
        
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = today_start.isoformat()
        today_date_str = now.strftime('%Y-%m-%d')
        today_disp_str = now.strftime('%Y/%m/%d')

        # 日報データを取得
        rows = self.bot.db.execute(
            '''SELECT user_id, username, SUM(duration_seconds) as total_time 
               FROM study_logs 
               WHERE created_at >= ? 
               GROUP BY user_id 
               ORDER BY total_time DESC''',
            (today_start,),
            fetch_all=True
        ) # Note: Passed datetime object, sqlite adapter handles it or needs str? Original used str.
        # DB Execute expects str usually for safe comparison
        rows = self.bot.db.execute(
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
                await channel.send(MESSAGES["report"]["empty_message"])
            else:
                embed = discord.Embed(
                    title=MESSAGES["report"]["embed_title"].format(date=today_disp_str),
                    description=MESSAGES["report"]["embed_desc"],
                    color=MESSAGES["report"]["embed_color"]
                )
                report_text = ""
                for _, username, total_seconds in rows:
                    time_str = format_duration(total_seconds, for_voice=True)
                    report_text += MESSAGES["report"]["row"].format(name=username, time=time_str)
                
                embed.add_field(name="Results", value=report_text, inline=False)
                await channel.send(embed=embed)
        
        # データベースに日報を保存 & クリーンアップ
        logs_deleted = 0
        summary_deleted = 0
        db_size_mb = 0
        
        # Custom DB logic for batch operation
        with self.bot.db.get_connection() as conn:
            c = conn.cursor()
            
            if rows:
                for user_id, username, total_seconds in rows:
                    c.execute(
                        '''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) 
                           VALUES (?, ?, ?, ?)''',
                        (user_id, username, today_date_str, total_seconds)
                    )
            
            # 古いDaily Summaryデータを削除
            cleanup_summary_threshold = now - timedelta(days=365)
            cleanup_summary_threshold_str = cleanup_summary_threshold.strftime('%Y-%m-%d')
            c.execute("DELETE FROM daily_summary WHERE date < ?", (cleanup_summary_threshold_str,))
            summary_deleted = c.rowcount
            
            # 古いログを削除
            cleanup_threshold = now - timedelta(days=self.keep_log_days)
            c.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold.isoformat(),))
            logs_deleted = c.rowcount
            
            # VACUUM を実行
            c.execute("VACUUM")
            conn.commit()
            
            # データベースサイズを監視
            db_path = self.bot.db.db_path
            db_size_bytes = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            db_size_mb = db_size_bytes / (1024 * 1024)
            print(f"📊 DBクリーンアップ完了 - スタディログ削除: {logs_deleted}件, DB容量: {db_size_mb:.2f} MB")

        await self.send_database_backup(today_date_str, today_disp_str, logs_deleted, summary_deleted, db_size_mb)

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

async def setup(bot):
    await bot.add_cog(ReportCog(bot))
