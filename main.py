import discord
from discord.ext import commands, tasks
import os
import sqlite3
from datetime import datetime, timedelta, time
import asyncio
import edge_tts
from messages import MESSAGES 

# 環境変数
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
LOG_CHANNEL_ID = int(os.getenv('LOG_CHANNEL_ID', 0))
SUMMARY_CHANNEL_ID = int(os.getenv('SUMMARY_CHANNEL_ID', 0))
BACKUP_CHANNEL_ID = int(os.getenv('BACKUP_CHANNEL_ID', 0)) # 追加
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
        if hours > 0:
            return f"{hours}時間{minutes}分"
        else:
            return f"{minutes}分"
    else:
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
        
        # Embedで通知
        time_str_text = format_duration(today_sec, for_voice=False)
        if text_channel:
            embed = discord.Embed(
                title=MESSAGES["join"]["embed_title"],
                color=MESSAGES["join"]["embed_color"]
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(
                name=MESSAGES["join"]["field_name"],
                value=MESSAGES["join"]["field_value"].format(current_total=time_str_text),
                inline=False
            )
            await text_channel.send(embed=embed)

        # 音声読み上げ
        time_str_speak = format_duration(today_sec, for_voice=True)
        speak_text = MESSAGES["join"]["voice"].format(name=member.display_name, current_total=time_str_speak)
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
                embed = discord.Embed(
                    title=MESSAGES["leave"]["embed_title"],
                    color=MESSAGES["leave"]["embed_color"]
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                embed.add_field(name=MESSAGES["leave"]["field1_name"], value=f"**{current_str}**", inline=False)
                embed.add_field(name=MESSAGES["leave"]["field2_name"], value=f"**{total_str}**", inline=False)
                await text_channel.send(embed=embed)
            
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
        await ctx.send(MESSAGES["rank"]["empty"])
        return

    # Embed作成
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
    await ctx.send(embed=embed)

@tasks.loop(time=time(hour=23, minute=59))
async def daily_report_task():
    # 1. 日報送信
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
             await channel.send(MESSAGES["report"]["empty"])
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
    
    # データ保存とクリーンアップ
    if rows:
        for user_id, username, total_seconds in rows:
            c.execute('''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) VALUES (?, ?, ?, ?)''', (user_id, username, today_date_str, total_seconds))
    
    cleanup_threshold = now - timedelta(days=KEEP_LOG_DAYS)
    c.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold.isoformat(),))
    if c.rowcount > 0:
        c.execute("VACUUM")
    
    conn.commit()
    conn.close()

    # ▼▼▼ 追加機能: データベースのバックアップ送信 ▼▼▼
    backup_channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if backup_channel and os.path.exists(DB_PATH):
        try:
            # 今日の日付をファイル名につける
            backup_filename = f"backup_{today_date_str}.db"
            file = discord.File(DB_PATH, filename=backup_filename)
            await backup_channel.send(f"🔒 **データベース自動バックアップ** ({today_disp_str})", file=file)
            print("バックアップ送信完了")
        except Exception as e:
            print(f"バックアップ送信エラー: {e}")


bot.run(TOKEN)
