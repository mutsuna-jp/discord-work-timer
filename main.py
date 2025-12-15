import discord
from discord.ext import commands
import os
import sqlite3
from datetime import datetime, timedelta

# 環境変数から設定を読み込む
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))

# インテント設定
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

# 入室時間を一時保存する辞書
voice_state_log = {}

# データベースのセットアップ
DB_PATH = "/data/study_log.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                 (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
    conn.commit()
    conn.close()

# 今日の合計秒数を取得する関数
def get_today_seconds(user_id):
    # 今日の0時0分0秒を取得
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # 今日以降(created_at >= today_str)のログを合計する
    c.execute('''
        SELECT SUM(duration_seconds)
        FROM study_logs
        WHERE user_id = ? AND created_at >= ?
    ''', (user_id, today_str))
    result = c.fetchone()[0]
    conn.close()
    
    return result if result else 0

# 秒数を「◯時間◯分」の文字列にする関数
def format_duration(total_seconds):
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}時間 {minutes}分 {seconds}秒"

@bot.event
async def on_ready():
    init_db()
    print(f'ログインしました: {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    channel = bot.get_channel(LOG_CHANNEL_ID)

    # 1. 入室検知
    if before.channel is None and after.channel is not None:
        voice_state_log[member.id] = datetime.now()
        
        # 今日の既存の合計時間を取得して表示
        today_sec = get_today_seconds(member.id)
        time_str = format_duration(today_sec)
        
        if channel:
            await channel.send(f"👋 こんにちは **{member.display_name}** さん！\n今日の積み上げ: **{time_str}** からスタートです🔥")

    # 2. 退室検知
    elif before.channel is not None and after.channel is None:
        if member.id in voice_state_log:
            join_time = voice_state_log[member.id]
            leave_time = datetime.now()
            duration = leave_time - join_time
            total_seconds = int(duration.total_seconds())

            # DBに記録
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
                      (member.id, member.display_name, join_time.isoformat(), total_seconds, leave_time.isoformat()))
            conn.commit()
            conn.close()

            # 今回の時間
            current_str = format_duration(total_seconds)
            
            # 記録後の合計時間（今日）
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
        await ctx.send("今週はまだ誰も作業していません...！一番乗りを目指しましょう！🏃‍♂️")
        return

    msg = "🏆 **今週の作業時間ランキング** 🏆\n(集計期間: 月曜日〜現在)\n\n"
    for i, (username, total_seconds) in enumerate(rows, 1):
        time_str = format_duration(total_seconds)
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{icon} **{username}**: {time_str}\n"

    await ctx.send(msg)

bot.run(TOKEN)
