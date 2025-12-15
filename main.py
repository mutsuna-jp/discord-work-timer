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

# 定数
KEEP_LOG_DAYS = 30 
VOICE_NAME = "ja-JP-NanamiNeural"
DB_PATH = "/data/study_log.db"
TIMER_MAX_MINUTES = 180
TIMER_CHECK_INTERVAL = 10
DAILY_REPORT_HOUR = 23
DAILY_REPORT_MINUTE = 59
FFMPEG_CLEANUP_DELAY = 1

# インテント設定
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

# デフォルトのhelpコマンドを無効化（自作するため）
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

voice_state_log = {}
message_tracker = {}

# ================== データベースヘルパー関数 ==================

def get_db_connection():
    """データベース接続を取得"""
    conn = sqlite3.connect(DB_PATH)
    return conn

def execute_db_query(query, params=None, fetch_one=False, fetch_all=False):
    """データベースクエリを実行"""
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            if params:
                c.execute(query, params)
            else:
                c.execute(query)
            
            if fetch_one:
                return c.fetchone()
            elif fetch_all:
                return c.fetchall()
            else:
                conn.commit()
                return None
    except Exception as e:
        print(f"データベースエラー: {e}")
        return None

def init_db():
    """データベースを初期化"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS study_logs
                     (user_id INTEGER, username TEXT, start_time TEXT, duration_seconds INTEGER, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS daily_summary
                     (user_id INTEGER, username TEXT, date TEXT, total_seconds INTEGER, PRIMARY KEY(user_id, date))''')
        c.execute('''CREATE TABLE IF NOT EXISTS personal_timers
                     (user_id INTEGER, end_time TEXT, minutes INTEGER)''')
        
        # パフォーマンスインデックスを作成
        c.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_user_created 
                     ON study_logs(user_id, created_at)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_study_logs_created 
                     ON study_logs(created_at)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_personal_timers_end_time 
                     ON personal_timers(end_time)''')
        c.execute('''CREATE INDEX IF NOT EXISTS idx_daily_summary_date 
                     ON daily_summary(date)''')
        
        conn.commit()

def get_today_seconds(user_id):
    """ユーザーの本日の作業時間を取得"""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()
    
    result = execute_db_query(
        '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ? AND created_at >= ?''',
        (user_id, today_str),
        fetch_one=True
    )
    
    return result[0] if result and result[0] else 0

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
    """音声チャネルに入ってテキストを読み上げる"""
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
                await asyncio.sleep(FFMPEG_CLEANUP_DELAY)
            await vc.disconnect()
            
    except Exception as e:
        print(f"音声読み上げエラー: {e}")
        try:
            if voice_channel.guild.voice_client:
                await voice_channel.guild.voice_client.disconnect()
        except Exception as disconnect_error:
            print(f"VC切断エラー: {disconnect_error}")
    finally:
        if os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception as e:
                print(f"ファイル削除エラー: {e}")

async def delete_previous_message(channel, message_id):
    """チャネルの前のメッセージを削除"""
    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
        except discord.NotFound:
            pass 
        except Exception as e:
            print(f"メッセージ削除エラー: {e}")

def is_active(voice_state):
    """ユーザーが実際にVCで活動中か判定"""
    return voice_state.channel is not None and not voice_state.self_deaf

async def safe_message_delete(message):
    """権限がない場合もスキップするメッセージ削除"""
    if message.guild:
        try:
            await message.delete()
        except Exception:
            pass

# ================== タイマー処理 ==================

async def set_personal_timer(message, minutes):
    """個人タイマーを設定"""
    await safe_message_delete(message)

    if minutes <= 0:
        await message.author.send(MESSAGES["timer"]["invalid"])
        return
    
    if minutes > TIMER_MAX_MINUTES:
        await message.author.send(MESSAGES["timer"]["too_long"])
        return

    end_time = datetime.now() + timedelta(minutes=minutes)
    end_time_str = end_time.isoformat()
    end_time_disp = end_time.strftime('%H:%M')

    execute_db_query(
        "INSERT INTO personal_timers VALUES (?, ?, ?)",
        (message.author.id, end_time_str, minutes)
    )

    await message.author.send(MESSAGES["timer"]["set"].format(minutes=minutes, end_time=end_time_disp))

@bot.event
async def on_ready():
    """ボットが起動時に呼ばれる"""
    init_db()
    if not daily_report_task.is_running():
        daily_report_task.start()
    if not check_timers_task.is_running():
        check_timers_task.start()
    
    print(f'ログインしました: {bot.user}')
    await recover_voice_sessions()

async def recover_voice_sessions():
    """ボット再起動時にVCセッションを復旧"""
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

@bot.event
async def on_message(message):
    """メッセージ受信時の処理"""
    if message.author.bot:
        return

    # !数字 コマンドの処理
    if message.content.startswith('!') and message.content[1:].isdigit():
        try:
            minutes = int(message.content[1:])
            await set_personal_timer(message, minutes)
            return
        except ValueError:
            pass

    await bot.process_commands(message)

# ================== VC状態変更処理 ==================

async def handle_voice_join(member, after, text_channel):
    """ユーザーがVCに参加した場合の処理"""
    if text_channel:
        await delete_previous_message(text_channel, message_tracker[member.id].get('leave_msg_id'))

    voice_state_log[member.id] = datetime.now()
    today_sec = get_today_seconds(member.id)
    time_str_text = format_duration(today_sec, for_voice=False)
    time_str_speak = format_duration(today_sec, for_voice=True)

    msg_type = "join" if after.channel is not None else "resume"
    
    if text_channel:
        embed = discord.Embed(
            title=MESSAGES[msg_type]["embed_title"],
            color=MESSAGES[msg_type]["embed_color"]
        )
        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        embed.add_field(
            name=MESSAGES[msg_type]["fields"][0]["name"],
            value=MESSAGES[msg_type]["fields"][0]["value"].format(current_total=time_str_text),
            inline=False
        )
        join_msg = await text_channel.send(embed=embed)
        message_tracker[member.id]['join_msg_id'] = join_msg.id

    if msg_type == "join":
        speak_text = MESSAGES["join"]["message"].format(name=member.display_name, current_total=time_str_speak)
    else:
        speak_text = MESSAGES["resume"]["message"].format(name=member.display_name)
        
    asyncio.create_task(speak_in_vc(after.channel, speak_text, member))

async def handle_voice_leave(member, after, text_channel):
    """ユーザーがVCを離れた場合の処理"""
    if text_channel:
        await delete_previous_message(text_channel, message_tracker[member.id].get('join_msg_id'))

    if member.id in voice_state_log:
        join_time = voice_state_log[member.id]
        leave_time = datetime.now()
        duration = leave_time - join_time
        total_seconds = int(duration.total_seconds())

        execute_db_query(
            "INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
            (member.id, member.display_name, join_time.isoformat(), total_seconds, leave_time.isoformat())
        )
        
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
            name=MESSAGES[msg_type]["fields"][0]["name"],
            value=MESSAGES[msg_type]["fields"][0]["value"].format(time=current_str),
            inline=False
        )
        embed.add_field(
            name=MESSAGES[msg_type]["fields"][1]["name"],
            value=MESSAGES[msg_type]["fields"][1]["value"].format(total=total_str),
            inline=False
        )
        
        leave_msg = await text_channel.send(embed=embed)
        message_tracker[member.id]['leave_msg_id'] = leave_msg.id

@bot.event
async def on_voice_state_update(member, before, after):
    """ボイスチャネルの状態変更を監視"""
    if member.bot:
        return

    text_channel = bot.get_channel(LOG_CHANNEL_ID)
    
    if member.id not in message_tracker:
        message_tracker[member.id] = {}

    was_active = is_active(before)
    is_active_now = is_active(after)

    # 1. 作業開始
    if not was_active and is_active_now:
        await handle_voice_join(member, after, text_channel)

    # 2. 作業終了
    elif was_active and not is_active_now:
        await handle_voice_leave(member, after, text_channel)

@bot.command()
async def timer(ctx, minutes: int = 0):
    """タイマーコマンド"""
    await set_personal_timer(ctx.message, minutes)

@tasks.loop(seconds=TIMER_CHECK_INTERVAL)
async def check_timers_task():
    """期限切れのタイマーを確認して通知"""
    now_str = datetime.now().isoformat()
    
    expired_timers = execute_db_query(
        "SELECT rowid, user_id, minutes FROM personal_timers WHERE end_time <= ?",
        (now_str,),
        fetch_all=True
    )
    
    if not expired_timers:
        return

    with get_db_connection() as conn:
        c = conn.cursor()
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
    """週間ランキングを表示"""
    await safe_message_delete(ctx.message)
    
    now = datetime.now()
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    monday_str = monday.isoformat()

    rows = execute_db_query(
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
    text_channel = bot.get_channel(LOG_CHANNEL_ID)
    if text_channel and ctx.author.id in message_tracker and 'rank_msg_id' in message_tracker[ctx.author.id]:
        await delete_previous_message(text_channel, message_tracker[ctx.author.id]['rank_msg_id'])
    
    # 新しいランクメッセージを送信して記録
    rank_msg = await ctx.send(embed=embed)
    if ctx.author.id not in message_tracker:
        message_tracker[ctx.author.id] = {}
    message_tracker[ctx.author.id]['rank_msg_id'] = rank_msg.id

@bot.command()
async def stats(ctx):
    """個別統計を表示"""
    await safe_message_delete(ctx.message)

    user_id = ctx.author.id
    
    total_result = execute_db_query(
        '''SELECT SUM(duration_seconds) FROM study_logs WHERE user_id = ?''',
        (user_id,),
        fetch_one=True
    )
    total_seconds = total_result[0] if total_result and total_result[0] else 0
    
    first_date_result = execute_db_query(
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

@bot.command()
async def help(ctx):
    """ヘルプを表示"""
    await safe_message_delete(ctx.message)

    embed = discord.Embed(
        title=MESSAGES["help"]["embed_title"],
        description=MESSAGES["help"]["embed_desc"],
        color=MESSAGES["help"]["embed_color"]
    )
    
    for cmd_name, cmd_desc in MESSAGES["help"]["commands"]:
        embed.add_field(name=cmd_name, value=cmd_desc, inline=False)
    
    await ctx.author.send(embed=embed)

@bot.command()
async def add(ctx, member: discord.Member, minutes: int):
    """ユーザーの作業時間を追加・削除"""
    now = datetime.now()
    total_seconds = minutes * 60
    
    execute_db_query(
        "INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
        (member.id, member.display_name, now.isoformat(), total_seconds, now.isoformat())
    )
    
    new_total = get_today_seconds(member.id)
    time_str = format_duration(new_total)
    
    action = "追加" if minutes > 0 else "削除"
    await ctx.send(f"✅ **{member.display_name}** さんの時間を {abs(minutes)}分 {action}しました。\n今日の合計: **{time_str}**")

@tasks.loop(time=time(hour=DAILY_REPORT_HOUR, minute=DAILY_REPORT_MINUTE))
async def daily_report_task():
    """毎日日報を送信し、ログをクリーンアップ"""
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_str = today_start.isoformat()
    today_date_str = now.strftime('%Y-%m-%d')
    today_disp_str = now.strftime('%Y/%m/%d')

    # 日報データを取得
    rows = execute_db_query(
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
    
    # データベースに日報を保存
    logs_deleted = 0
    summary_deleted = 0
    db_size_mb = 0
    
    with get_db_connection() as conn:
        c = conn.cursor()
        
        if rows:
            for user_id, username, total_seconds in rows:
                c.execute(
                    '''INSERT OR REPLACE INTO daily_summary (user_id, username, date, total_seconds) 
                       VALUES (?, ?, ?, ?)''',
                    (user_id, username, today_date_str, total_seconds)
                )
        
        # 古いDaily Summaryデータを削除（1年以上前）
        cleanup_summary_threshold = now - timedelta(days=365)
        cleanup_summary_threshold_str = cleanup_summary_threshold.strftime('%Y-%m-%d')
        c.execute("DELETE FROM daily_summary WHERE date < ?", (cleanup_summary_threshold_str,))
        summary_deleted = c.rowcount
        
        # 古いログを削除
        cleanup_threshold = now - timedelta(days=KEEP_LOG_DAYS)
        c.execute("DELETE FROM study_logs WHERE created_at < ?", (cleanup_threshold.isoformat(),))
        logs_deleted = c.rowcount
        
        # VACUUM を実行（定期的な断片化防止）
        c.execute("VACUUM")
        conn.commit()
        
        # データベースサイズを監視
        db_size_bytes = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
        db_size_mb = db_size_bytes / (1024 * 1024)
        print(f"📊 DBクリーンアップ完了 - スタディログ削除: {logs_deleted}件, Daily Summary削除: {summary_deleted}件, DB容量: {db_size_mb:.2f} MB")

    # バックアップを送信（クリーンアップ情報を含める）
    await send_database_backup(today_date_str, today_disp_str, logs_deleted, summary_deleted, db_size_mb)

async def send_database_backup(today_date_str, today_disp_str, logs_deleted=0, summary_deleted=0, db_size_mb=0):
    """データベースのバックアップをチャネルに送信"""
    backup_channel = bot.get_channel(BACKUP_CHANNEL_ID)
    if backup_channel and os.path.exists(DB_PATH):
        try:
            # クリーンアップ情報をEmbed形式で送信
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
            
            # バックアップファイルを送信
            backup_filename = f"backup_{today_date_str}.db"
            file = discord.File(DB_PATH, filename=backup_filename)
            await backup_channel.send(embed=embed, file=file)
            print("バックアップ送信完了")
        except Exception as e:
            print(f"バックアップ送信エラー: {e}")


bot.run(TOKEN)
