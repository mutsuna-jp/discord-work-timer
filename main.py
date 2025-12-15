import discord
from discord.ext import commands, tasks
import os
import sqlite3
from datetime import datetime, timedelta, time

# 環境変数から設定を読み込む
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
SUMMARY_CHANNEL_ID = int(os.getenv('SUMMARY_CHANNEL_ID', 0))

# 詳細ログを何日分残すか（これより古い詳細ログは削除され、集計データだけが残ります）
KEEP_LOG_DAYS = 30 

# インテント設定
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

voice_state_log = {}
DB_PATH = "/data/study_log.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 詳細ログ用（今まで通り）
    c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                 (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
    
    # 【追加】長期保存用の日次集計テーブル
    # date: YYYY-MM-DD 形式
    c.execute('''CREATE TABLE IF NOT EXISTS daily_summary
                 (user_id INTEGER, username TEXT, date TEXT, total_seconds INTEGER, PRIMARY KEY(user_id, date))''')
    
    conn.commit()
    conn.close()

def get_today_seconds(user_id):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT SUM(duration_seconds)
        FROM study_logs
        WHERE user_id = ? AND created_at >= ?
    ''', (user_id, today_str))
    result = c.fetchone()[0]
    conn.close()
    return result if result else 0

def format_duration(total_seconds):
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}時間 {minutes}分 {seconds}秒"

@bot.event
async def on_ready():
    init_db()
    if not daily_report_task.is_running():
        daily_report_task.start()
    print(f'ログインしました: {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)

    if before.channel is None and after.channel is not None:
        voice_state_log[member.id] = datetime.now()
        today_sec = get_today_seconds(member.id)
        time_str = format_duration(today_sec)
        if channel:
            await channel.send(f"👋 こんにちは **{member.display_name}** さん！\n今日の積み上げ: **{time_str}** からスタートです🔥")

    elif before.channel is not None and after.channel is None:
        if member.id in voice_state_log:
            join_time = voice_state_log[member.id]
            leave_time = datetime.now()
            duration = leave_time - join_time
            total_seconds = int(duration.total_seconds())

            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
                      (member.id, member.display_name, join_time.isoformat(), total_seconds, leave_time.isoformat()))
            conn.commit()
            conn.close()

            current_str = format_duration(total_seconds)
            today_sec = get_today_seconds(member.id)
            total_str = format_duration(today_sec)
            
            if channel:
                msg = (f"🍵 お疲れ様でした！ **{member.display_name}** さん\n"
                       f"今回の作業時間: **{current_str}**\n"
                       f"今日の総作業時間: **{total_str}**")
                await channel.send(msg)
            
            del voice_state_log[member.id]

@bot.command()
async def rank(ctx):
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    monday_str = monday.isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT username, SUM(duration_seconds) as total_time
        FROM study_logs
        WHERE created_at >= ?
        GROUP BY user_id
        ORDER BY total_time DESC
        LIMIT 10
    ''', (monday_str,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await ctx.send("今週はまだ誰も作業していません...！")
        return

    msg = "🏆 **今週の作業時間ランキング** 🏆\n(集計期間: 月曜日〜現在)\n\n"
    for i, (username, total_seconds) in enumerate(rows, 1):
        time_str = format_duration(total_seconds)
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{icon} **{username}**: {time_str}\n"

    await ctx.send(msg)

# ▼▼▼ 毎日23:59に実行：日報送信 ＆ データ整理 ▼▼▼
@tasks.loop(time=time(hour=23, minute=59))
async def daily_report_task():
    # 1. 日報送信機能
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()
    today_date_str = now.strftime('%Y-%m-%d') # YYYY-MM-DD形式

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 今日の集計を取得
    c.execute('''
        SELECT user_id, username, SUM(duration_seconds) as total_time
        FROM study_logs
        WHERE created_at >= ?
        GROUP BY user_id
        ORDER BY total_time DESC
    ''', (today_str,))
    rows = c.fetchall()

    if channel and rows:
        msg = f"📅 **{now.strftime('%Y/%m/%d')} の作業レポート** 📅\nみなさんお疲れ様でした！本日の成果です✨\n\n"
        for _, username, total_seconds in rows:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            msg += f"• **{username}**: {hours}時間 {minutes}分\n"
        await channel.send(msg)
    
    # 2. データの圧縮・保存処理（統計機能用）
    print("日次データの保存とクリーンアップを開始します...")
    
    # 今日の集計結果を daily_summary テーブルに保存（上書き保存）
    for user_id, username, total_seconds in rows:
        c.execute('''
            INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds)
            VALUES (?, ?, ?, ?)
        ''', (user_id, username, today_date_str, total_seconds))
    
    # 3. 古い詳細ログの削除
    # KEEP_LOG_DAYS 日以上前のデータを削除
    cleanup_threshold = now - timedelta(days=KEEP_LOG_DAYS)
    cleanup_threshold_str = cleanup_threshold.isoformat()
    
    c.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold_str,))
    deleted_count = c.rowcount
    
    conn.commit()
    
    # データベースのファイルサイズを最適化（削除した分の容量をOSに返す）
    if deleted_count > 0:
        c.execute("VACUUM")
        print(f"{deleted_count} 件の古いログを削除し、データベースを最適化しました。")
    
    conn.close()

bot.run(TOKEN)
