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

# コマンドプレフィックスを '!' に設定 (例: !rank)
bot = commands.Bot(command_prefix='!', intents=intents)

# 入室時間を一時保存する辞書
voice_state_log = {}

# データベースのセットアップ
DB_PATH = "/data/study_log.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # ログ保存用テーブル
    c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                 (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
    conn.commit()
    conn.close()

@bot.event
async def on_ready():
    init_db()
    print(f'ログインしました: {bot.user}')

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    # 入室
    if before.channel is None and after.channel is not None:
        voice_state_log[member.id] = datetime.now()
        print(f'{member.name} 入室')

    # 退室
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

            # 時間計算
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60

            # 通知
            channel = bot.get_channel(LOG_CHANNEL_ID)
            if channel:
                msg = (f"お疲れ様でした！🍵\n"
                       f"**{member.display_name}** さんの作業時間: "
                       f"**{hours}時間 {minutes}分 {seconds}秒**")
                await channel.send(msg)
            
            del voice_state_log[member.id]

# !rank コマンドの実装
@bot.command()
async def rank(ctx):
    # 今週の月曜日を取得（月曜始まり）
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    monday_str = monday.isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 今週のデータを集計して降順に並べるSQL
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

    # ランキング表示の作成
    msg = "🏆 **今週の作業時間ランキング** 🏆\n(集計期間: 月曜日〜現在)\n\n"
    for i, (username, total_seconds) in enumerate(rows, 1):
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += f"{icon} **{username}**: {hours}時間 {minutes}分\n"

    await ctx.send(msg)

bot.run(TOKEN)
