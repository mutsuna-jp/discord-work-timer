import discord
from discord.ext import commands, tasks
import os
import sqlite3
from datetime import datetime, timedelta, time
import asyncio
import edge_tts
# メッセージ定義ファイルをインポート
from messages import MESSAGES 

# 環境変数
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
SUMMARY_CHANNEL_ID = int(os.getenv('SUMMARY_CHANNEL_ID', 0))
KEEP_LOG_DAYS = 30 
VOICE_NAME = "ja-JP-NanamiNeural"

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
    c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                 (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
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
    c.execute('''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ? AND created_at >= ?''', (user_id, today_str))
    result = c.fetchone()[0]
    conn.close()
    return result if result else 0

def format_duration(total_seconds, for_voice=False):
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if for_voice:
        # 音声用: 短く（0時間の時は言わない）
        if hours > 0:
            return f"{hours}時間{minutes}分"
        else:
            return f"{minutes}分"
    else:
        # テキスト用: 秒まで
        return f"{hours}時間 {minutes}分 {seconds}秒"

async def generate_voice(text, output_path='voice.mp3'):
    communicate = edge_tts.Communicate(text, VOICE_NAME)
    await communicate.save(output_path)

async def speak_in_vc(voice_channel, text):
    try:
        vc = voice_channel.guild.voice_client
        if not vc:
            vc = await voice_channel.connect()
        
        await generate_voice(text)
        
        source = discord.FFmpegPCMAudio("voice.mp3")
        if not vc.is_playing():
            vc.play(source)
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
            
    except Exception as e:
        print(f"音声読み上げエラー: {e}")
        if voice_channel.guild.voice_client:
             await voice_channel.guild.voice_client.disconnect()

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

    text_channel = bot.get_channel(LOG_CHANNEL_ID)

    # 1. 入室検知
    if before.channel is None and after.channel is not None:
        voice_state_log[member.id] = datetime.now()
        today_sec = get_today_seconds(member.id)
        
        # テキスト通知
        time_str_text = format_duration(today_sec, for_voice=False)
        if text_channel:
            msg = MESSAGES["join_text"].format(name=member.display_name, current_total=time_str_text)
            await text_channel.send(msg)

        # 音声読み上げ
        time_str_speak = format_duration(today_sec, for_voice=True)
        speak_text = MESSAGES["join_voice"].format(name=member.display_name, current_total=time_str_speak)
        
        asyncio.create_task(speak_in_vc(after.channel, speak_text))

    # 2. 退室検知
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

            current_str = format_duration(total_seconds, for_voice=False)
            today_sec = get_today_seconds(member.id)
            total_str = format_duration(today_sec, for_voice=False)
            
            if text_channel:
                msg = MESSAGES["leave_text"].format(
                    name=member.display_name,
                    duration=current_str,
                    daily_total=total_str
                )
                await text_channel.send(msg)
            
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
        await ctx.send(MESSAGES["rank_empty"])
        return

    msg = MESSAGES["rank_header"]
    for i, (username, total_seconds) in enumerate(rows, 1):
        time_str = format_duration(total_seconds, for_voice=True) # ランキングは短め表記で
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        msg += MESSAGES["rank_row"].format(icon=icon, name=username, time=time_str)

    await ctx.send(msg)

@tasks.loop(time=time(hour=23, minute=59))
async def daily_report_task():
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()
    today_date_str = now.strftime('%Y-%m-%d')
    today_disp_str = now.strftime('%Y/%m/%d')

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''SELECT user_id, username, SUM(duration_seconds) as total_time FROM study_logs WHERE created_at >= ? GROUP BY user_id ORDER BY total_time DESC''', (today_str,))
    rows = c.fetchall()

    if channel:
        if not rows:
             await channel.send(MESSAGES["report_empty"])
        else:
            msg = MESSAGES["report_header"].format(date=today_disp_str)
            for _, username, total_seconds in rows:
                time_str = format_duration(total_seconds, for_voice=True)
                msg += MESSAGES["report_row"].format(name=username, time=time_str)
            await channel.send(msg)
    
    # データ保存とクリーンアップ（変更なし）
    if rows:
        for user_id, username, total_seconds in rows:
            c.execute('''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) VALUES (?, ?, ?, ?)''', (user_id, username, today_date_str, total_seconds))
    
    cleanup_threshold = now - timedelta(days=KEEP_LOG_DAYS)
    c.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold.isoformat(),))
    if c.rowcount > 0:
        c.execute("VACUUM")
    
    conn.commit()
    conn.close()

bot.run(TOKEN)
