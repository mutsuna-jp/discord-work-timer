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
        c.execute('''CREATE TABLE IF NOT EXISTS personal_timers
                     (user_id INTEGER, end_time TEXT, minutes INTEGER)''')
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

async def speak_in_vc(voice_channel, text, member):
    filename = f"voice_{member.id}.mp3"
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

def is_active(voice_state):
    return voice_state.channel is not None and not voice_state.self_deaf

# ▼▼▼ 追加: タイマー設定の共通処理 ▼▼▼
async def set_personal_timer(message, minutes):
    # メッセージ削除
    if message.guild:
        try:
            await message.delete()
        except:
            pass

    if minutes <= 0:
        await message.author.send(MESSAGES["timer"]["invalid"])
        return
    
    if minutes > 180:
        await message.author.send(MESSAGES["timer"]["too_long"])
        return

    end_time = datetime.now() + timedelta(minutes=minutes)
    end_time_str = end_time.isoformat()
    end_time_disp = end_time.strftime('%H:%M')

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO personal_timers VALUES (?, ?, ?)",
                  (message.author.id, end_time_str, minutes))
        conn.commit()

    await message.author.send(MESSAGES["timer"]["set"].format(minutes=minutes, end_time=end_time_disp))

@bot.event
async def on_ready():
    init_db()
    if not daily_report_task.is_running():
        daily_report_task.start()
    if not check_timers_task.is_running():
        check_timers_task.start()
    
    print(f'ログインしました: {bot.user}')

    print("現在のVC状態を確認中...")
    recovered_count = 0
    
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot and is_active(member.voice):
                    if member.id not in voice_state_log:
                        voice_state_log[member.id] = datetime.now()
                        recovered_count += 1
                        print(f"復旧: {member.display_name} さんの計測を再開しました")
    
    if recovered_count > 0:
        print(f"合計 {recovered_count} 名の作業セッションを復旧しました。")

# ▼▼▼ 追加: メッセージ監視（!数字 の検知） ▼▼▼
@bot.event
async def on_message(message):
    # ボット自身の発言は無視
    if message.author.bot:
        return

    # "!数字" のパターンかどうかチェック (例: !10, !30)
    # message.content[1:] が数字のみで構成されているか
    if message.content.startswith('!') and message.content[1:].isdigit():
        try:
            minutes = int(message.content[1:])
            # タイマー処理を実行
            await set_personal_timer(message, minutes)
            # タイマーだった場合はここで終了（他のコマンドとして処理させない）
            return
        except ValueError:
            pass

    # その他のコマンド(!rankなど)を処理するために必要
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    text_channel = bot.get_channel(LOG_CHANNEL_ID)
    
    if member.id not in message_tracker:
        message_tracker[member.id] = {}

    was_active = is_active(before)
    is_active_now = is_active(after)

    # 1. 作業開始
    if not was_active and is_active_now:
        if text_channel:
            await delete_previous_message(text_channel, message_tracker[member.id].get('leave_msg_id'))

        voice_state_log[member.id] = datetime.now()
        today_sec = get_today_seconds(member.id)
        time_str_text = format_duration(today_sec, for_voice=False)
        time_str_speak = format_duration(today_sec, for_voice=True)

        msg_type = "join" if before.channel is None else "resume"
        
        if text_channel:
            embed = discord.Embed(
                title=MESSAGES[msg_type]["embed_title"],
                color=MESSAGES[msg_type]["embed_color"]
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            embed.add_field(
                name=MESSAGES[msg_type]["field_name"],
                value=MESSAGES[msg_type]["field_value"].format(current_total=time_str_text),
                inline=False
            )
            join_msg = await text_channel.send(embed=embed)
            message_tracker[member.id]['join_msg_id'] = join_msg.id

        if msg_type == "join":
            speak_text = MESSAGES["join"]["voice"].format(name=member.display_name, current_total=time_str_speak)
        else:
            speak_text = MESSAGES["resume"]["voice"].format(name=member.display_name)
            
        asyncio.create_task(speak_in_vc(after.channel, speak_text, member))

    # 2. 作業終了
    elif was_active and not is_active_now:
        if text_channel:
            await delete_previous_message(text_channel, message_tracker[member.id].get('join_msg_id'))

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
            
            del voice_state_log[member.id]
        else:
            total_seconds = 0

        current_str = format_duration(total_seconds, for_voice=False)
        today_sec = get_today_seconds(member.id)
        total_str = format_duration(today_sec, for_voice=False)
        
        msg_type = "leave" if after.channel is None else "break"

        if text_channel:
            embed = discord.Embed(
                title=MESSAGES[msg_type]["embed_title"],
                color=MESSAGES[msg_type]["embed_color"]
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            
            embed.add_field(
                name=MESSAGES[msg_type]["field1_name"],
                value=MESSAGES[msg_type]["field1_value"].format(time=current_str),
                inline=False
            )
            embed.add_field(
                name=MESSAGES[msg_type]["field2_name"],
                value=MESSAGES[msg_type]["field2_value"].format(total=total_str),
                inline=False
            )
            
            leave_msg = await text_channel.send(embed=embed)
            message_tracker[member.id]['leave_msg_id'] = leave_msg.id

# 元のコマンドも一応残しておきます（共通関数を呼ぶだけ）
@bot.command()
async def timer(ctx, minutes: int = 0):
    await set_personal_timer(ctx.message, minutes)

@tasks.loop(seconds=10)
async def check_timers_task():
    now_str = datetime.now().isoformat()
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT rowid, user_id, minutes FROM personal_timers WHERE end_time <= ?", (now_str,))
        expired_timers = c.fetchall()
        
        for rowid, user_id, minutes in expired_timers:
            try:
                user = bot.get_user(user_id)
                if not user:
                    user = await bot.fetch_user(user_id)
                
                if user:
                    await user.send(MESSAGES["timer"]["finish"].format(minutes=minutes))
            except Exception as e:
                print(f"タイマー通知エラー (User ID: {user_id}): {e}")
            
            c.execute("DELETE FROM personal_timers WHERE rowid = ?", (rowid,))
        
        conn.commit()

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

@bot.command()
async def add(ctx, member: discord.Member, minutes: int):
    now = datetime.now()
    total_seconds = minutes * 60
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
                  (member.id, member.display_name, now.isoformat(), total_seconds, now.isoformat()))
        conn.commit()
    
    new_total = get_today_seconds(member.id)
    time_str = format_duration(new_total)
    
    action = "追加" if minutes > 0 else "削除"
    await ctx.send(f"✅ **{member.display_name}** さんの時間を {abs(minutes)}分 {action}しました。\n今日の合計: **{time_str}**")

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
