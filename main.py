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
BACKUP_CHANNEL_ID = int(os.getenv('BACKUP_CHANNEL_ID', 0))
KEEP_LOG_DAYS = 30 
VOICE_NAME = "ja-JP-NanamiNeural"

# インテント設定
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

voice_state_log = {}
message_tracker = {} 

DB_PATH = "/data/study_log.db"

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                     (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS daily_summary
                     (user_id INTEGER, username TEXT, date TEXT, total_seconds INTEGER, PRIMARY KEY(user_id, date))''')
        conn.commit()

def get_today_seconds(user_id):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ? AND created_at >= ?''', (user_id, today_str))
        result = c.fetchone()[0]
    
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

async def generate_voice(text, output_path):
    communicate = edge_tts.Communicate(text, VOICE_NAME)
    await communicate.save(output_path)

# ▼▼▼ 修正: ファイル名をユニークにして競合回避 & 削除処理追加 ▼▼▼
async def speak_in_vc(voice_channel, text, member):
    filename = f"voice_{member.id}.mp3"  # ユーザーIDを含めたファイル名
    try:
        vc = voice_channel.guild.voice_client
        if not vc:
            vc = await voice_channel.connect()
        
        await generate_voice(text, filename)
        
        source = discord.FFmpegPCMAudio(filename)
        if not vc.is_playing():
            vc.play(source)
            while vc.is_playing():
                await asyncio.sleep(1)
            await vc.disconnect()
            
    except Exception as e:
        print(f"音声読み上げエラー: {e}")
        if voice_channel.guild.voice_client:
             await voice_channel.guild.voice_client.disconnect()
    finally:
        # 使い終わったファイルを削除
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception as e:
                print(f"ファイル削除エラー: {e}")

async def delete_previous_message(channel, message_id):
    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
        except discord.NotFound:
            pass 
        except Exception as e:
            print(f"メッセージ削除エラー: {e}")

# ▼▼▼ 追加: 「作業中」かどうかを判定する関数（スピーカーミュート対策） ▼▼▼
def is_active(voice_state):
    # VCに参加しており、かつスピーカーミュート(self_deaf)していない場合のみTrue
    return voice_state.channel is not None and not voice_state.self_deaf

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
    
    if member.id not in message_tracker:
        message_tracker[member.id] = {}

    # ▼▼▼ ロジック変更: is_activeを使って判定 ▼▼▼
    was_active = is_active(before)
    is_active_now = is_active(after)

    # 1. 作業開始 (入室、またはミュート解除)
    if not was_active and is_active_now:
        voice_state_log[member.id] = datetime.now()
        today_sec = get_today_seconds(member.id)
        
        time_str_text = format_duration(today_sec, for_voice=False)
        if text_channel:
            await delete_previous_message(text_channel, message_tracker[member.id].get('leave_msg_id'))
            
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
            
            join_msg = await text_channel.send(embed=embed)
            message_tracker[member.id]['join_msg_id'] = join_msg.id

        time_str_speak = format_duration(today_sec, for_voice=True)
        speak_text = MESSAGES["join"]["voice"].format(name=member.display_name, current_total=time_str_speak)
        # 修正: memberを渡す
        asyncio.create_task(speak_in_vc(after.channel, speak_text, member))

    # 2. 作業終了 (退室、またはミュート開始)
    elif was_active and not is_active_now:
        if member.id in voice_state_log:
            join_time = voice_state_log[member.id]
            leave_time = datetime.now()
            duration = leave_time - join_time
            total_seconds = int(duration.total_seconds())

            with sqlite3.connect(DB_PATH) as conn:
                c = conn.cursor()
                c.execute("INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
                          (member.id, member.display_name, join_time.isoformat(), total_seconds, leave_time.isoformat()))
                conn.commit()

            current_str = format_duration(total_seconds, for_voice=False)
            today_sec = get_today_seconds(member.id)
            total_str = format_duration(today_sec, for_voice=False)
            
            if text_channel:
                await delete_previous_message(text_channel, message_tracker[member.id].get('join_msg_id'))

                embed = discord.Embed(
                    title=MESSAGES["leave"]["embed_title"],
                    color=MESSAGES["leave"]["embed_color"]
                )
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                
                embed.add_field(
                    name=MESSAGES["leave"]["field1_name"],
                    value=MESSAGES["leave"]["field1_value"].format(time=current_str),
                    inline=False
                )
                embed.add_field(
                    name=MESSAGES["leave"]["field2_name"],
                    value=MESSAGES["leave"]["field2_value"].format(total=total_str),
                    inline=False
                )
                
                leave_msg = await text_channel.send(embed=embed)
                message_tracker[member.id]['leave_msg_id'] = leave_msg.id
            
            del voice_state_log[member.id]

@bot.command()
async def rank(ctx):
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    monday_str = monday.isoformat()

    with sqlite3.connect(DB_PATH) as conn:
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

    if not rows:
        await ctx.send(MESSAGES["rank"]["empty"])
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
    await ctx.send(embed=embed)

@tasks.loop(time=time(hour=23, minute=59))
async def daily_report_task():
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()
    today_date_str = now.strftime('%Y-%m-%d')
    today_disp_str = now.strftime('%Y/%m/%d')

    with sqlite3.connect(DB_PATH) as conn:
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
        
        if rows:
            for user_id, username, total_seconds in rows:
                c.execute('''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) VALUES (?, ?, ?, ?)''', (user_id, username, today_date_str, total_seconds))
        
        cleanup_threshold = now - timedelta(days=KEEP_LOG_DAYS)
        c.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold.isoformat(),))
        if c.rowcount > 0:
            c.execute("VACUUM")
        conn.commit()

    backup_channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if backup_channel and os.path.exists(DB_PATH):
        try:
            backup_filename = f"backup_{today_date_str}.db"
            file = discord.File(DB_PATH, filename=backup_filename)
            await backup_channel.send(f"🔒 **データベース自動バックアップ** ({today_disp_str})", file=file)
            print("バックアップ送信完了")
        except Exception as e:
            print(f"バックアップ送信エラー: {e}")

bot.run(TOKEN)
