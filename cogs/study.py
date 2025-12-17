import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from utils import format_duration, speak_in_vc, delete_previous_message, create_embed_from_config
from messages import MESSAGES, Colors
from config import Config
import logging

logger = logging.getLogger(__name__)



class CheerView(discord.ui.View):
    def __init__(self, target_member):
        super().__init__(timeout=None) # メッセージが消えるまで有効
        self.target_member = target_member
        self.supporters = set() # 重複防止用のセット

    @discord.ui.button(label="🔥 応援！", style=discord.ButtonStyle.green, custom_id="cheer_button")
    async def cheer(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 自分自身への応援はブロック
        if interaction.user.id == self.target_member.id:
            await interaction.response.send_message("自分自身は応援できません", ephemeral=True)
            return

        # すでに応援済みかチェック
        if interaction.user.id in self.supporters:
            await interaction.response.send_message("すでに応援済みです！", ephemeral=True)
            return

        # 応援者リストに追加
        self.supporters.add(interaction.user.id)
        
        # Embedを更新する処理
        embed = interaction.message.embeds[0]
        
        # 応援者のメンションリストを生成
        supporter_mentions = [f"<@{user_id}>" for user_id in self.supporters]
        text = " ".join(supporter_mentions)
        field_name = f"📣 応援 ({len(self.supporters)})"
        field_value = text

        # 既存の「応援」フィールドを探して更新、なければ追加
        found = False
        for i, field in enumerate(embed.fields):
            if field.name.startswith("📣 応援"):
                embed.set_field_at(i, name=field_name, value=field_value, inline=False)
                found = True
                break

        if not found:
            embed.add_field(name=field_name, value=field_value, inline=False)

        # メッセージを更新
        await interaction.response.edit_message(embed=embed)
        
        # 押した人への確認メッセージ（自分にしか見えない）
        await interaction.followup.send(f"{self.target_member.display_name}さんにエールを送りました！🔥", ephemeral=True)

class StudyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.voice_state_log = {}
        self.voice_state_offset = {} # Bot再起動前や日次集計前の時間を保持するオフセット
        self.break_state_log = {} # 休憩中のユーザーと開始時刻を記録: {user_id: break_start_time}
        self.break_duration_accumulated = {} # 蓄積された休憩時間: {user_id: total_break_seconds}

    @app_commands.command(name="task", description="現在取り組んでいるタスクを設定します")
    @app_commands.describe(content="タスクの内容")
    @app_commands.default_permissions(send_messages=True)
    async def task(self, interaction: discord.Interaction, content: str):
        """タスク設定コマンド"""
        await self.bot.db.set_user_task(interaction.user.id, content)
        await interaction.response.send_message(f"タスクを設定しました: **{content}**", ephemeral=True)
        
        # ステータスボード更新
        status_cog = self.bot.get_cog("StatusCog")
        if status_cog:
            # 更新スケジュールのデバウンス制御に任せつつ、退出時にはランキングも即時更新
            await status_cog.update_status_board()
            try:
                await status_cog.update_weekly_ranking()
            except Exception:
                # ランキング更新は副次的処理なので失敗してもログを残して続行
                logger.exception("退出時のランキング即時更新に失敗しました")

    @app_commands.command(name="reading", description="読み上げ用の名前(読み仮名)を設定します")
    @app_commands.describe(name="読み上げに使用する名前")
    @app_commands.default_permissions(send_messages=True)
    async def reading(self, interaction: discord.Interaction, name: str):
        """読み仮名設定コマンド"""
        await self.bot.db.set_user_reading(interaction.user.id, name)
        await interaction.response.send_message(f"読み上げ名を設定しました: **{name}**", ephemeral=True)

    def is_active(self, voice_state):
        """ユーザーが実際にVCで活動中か判定"""
        return voice_state.channel is not None and not voice_state.self_deaf
    
    def is_on_break(self, voice_state):
        """ユーザーがVCで休憩中（セルフデフ）か判定"""
        return voice_state.channel is not None and voice_state.self_deaf

    @commands.Cog.listener()
    async def on_ready(self):
        await self.recover_voice_sessions()

    async def recover_voice_sessions(self):
        """ボット再起動時にVCセッションを復旧"""
        logger.info("現在のVC状態を確認中...")
        recovered_count = 0
        
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                        if member.bot:
                            continue
                        if member.id not in self.voice_state_log:
                            # デフォルトは現在時刻
                            start_time = datetime.now()
                            self.voice_state_log[member.id] = start_time
                            
                            # 直近の停止前ログがあれば、オフセットとして保持する（開始時間は現在時刻のまま）
                            try:
                                # 10分(600秒)以内の再起動なら引き継ぎ対象とする
                                last_duration = await self.bot.db.get_last_session_duration_if_recent(member.id, threshold_seconds=600)
                                if last_duration > 0:
                                    self.voice_state_offset[member.id] = last_duration
                                    logger.info(f"復旧: {member.display_name} さんの過去セッション({last_duration}秒)を引き継ぎました")
                            except Exception as e:
                                logger.error(f"セッション引き継ぎ計算エラー: {e}")

                            recovered_count += 1
                            logger.info(f"復旧: {member.display_name} さんの計測を再開しました")
        
        if recovered_count > 0:
            logger.info(f"合計 {recovered_count} 名の作業セッションを復旧しました。")

        # ▼ 追加: 停止中に退出したユーザーのパネル整理
        try:
            log_channel_id = Config.LOG_CHANNEL_ID
            channel = self.bot.get_channel(log_channel_id)
            if log_channel_id and not channel:
                try:
                    channel = await self.bot.fetch_channel(log_channel_id)
                except:
                    pass

            if channel:
                active_states = await self.bot.db.get_all_active_users_with_state()
                # 現在復旧されたユーザー(=今もVCにいる人)以外の、パネルが出っぱなしのユーザー
                missing_users = [row for row in active_states if row[0] not in self.voice_state_log]

                if missing_users:
                    logger.info(f"停止中に退出したと思われる {len(missing_users)} 名のパネルを処理します。")

                for user_id, join_msg_id in missing_users:
                    # 1. 古いパネルを削除
                    try:
                        await delete_previous_message(channel, join_msg_id)
                    except:
                        pass # メッセージが既にない場合は無視
                    
                    # 2. メンバーオブジェクトを探す
                    member = None
                    for guild in self.bot.guilds:
                        member = guild.get_member(user_id)
                        if member: break
                    
                    if member:
                        # 3. 退出ログ(Embed)を送信
                        # 時間は停止前に記録済みなので、ここでは「メンテナンス」などを表示
                        today_sec = await self.bot.db.get_today_seconds(member.id)
                        total_str = format_duration(today_sec, for_voice=False)
                        
                        msg_config = MESSAGES.get("leave", {})
                        # create_embed_from_config は utils からインポート済みと仮定
                        embed = create_embed_from_config(
                            msg_config,
                            name=member.display_name,
                            time="-- (保存済)",
                            total=total_str
                        )
                        embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                        
                        leave_msg = await channel.send(embed=embed)
                        
                        # DB更新: join削除, leave設定
                        await self.bot.db.set_message_state(member.id, None, leave_msg.id)
                        logger.info(f"クリーンアップ: {member.display_name} さんのパネルを退出済みへ更新しました。")
                    else:
                        # メンバーが見つからない場合はDBの状態だけクリア（パネルは削除済み）
                        await self.bot.db.set_message_state(user_id, None, None)

        except Exception as e:
            logger.error(f"停止中退出ユーザーのクリーンアップ中にエラー: {e}")

    async def save_all_sessions(self):
        """Bot停止時に現在作業中の全ユーザーのログを保存する"""
        if not self.voice_state_log:
            return

        logger.info("Bot停止に伴い、作業中のセッションを保存します...")
        count = 0
        now = datetime.now()

        # 辞書のコピーでループ（変更中のエラーを防ぐため）
        for user_id, join_time in list(self.voice_state_log.items()):
            try:
                # ユーザー情報を取得（キャッシュから）
                user = self.bot.get_user(user_id)
                if not user:
                    # キャッシュにない場合はIDのみで記録するか、スキップ
                    # DBにはusernameが必要だが、キャッシュ落ちしてる可能性は低い
                    # 万が一の場合は "Unknown User" とする
                    username = "Unknown User"
                else:
                    username = getattr(user, "display_name", None) or getattr(user, "name", "Unknown User")

                # 実際に記録すべき時間（オフセットは含まない）
                duration = now - join_time
                total_seconds = int(duration.total_seconds())

                if total_seconds > 0:
                    await self.bot.db.add_study_log(
                        user_id,
                        username,
                        join_time,
                        total_seconds,
                        now
                    )
                    count += 1
            except Exception as e:
                logger.error(f"セッション保存エラー (User ID: {user_id}): {e}")

        logger.info(f"合計 {count} 件の作業ログを退避保存しました。")
        self.voice_state_log.clear()
        self.voice_state_offset.clear()
        self.break_state_log.clear()
        self.break_duration_accumulated.clear()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """ボイスチャネルの状態変更を監視"""
        if member.bot:
            return

        log_channel_id = Config.LOG_CHANNEL_ID
        text_channel = self.bot.get_channel(log_channel_id)
        
        was_active = self.is_active(before)
        was_on_break = self.is_on_break(before)
        is_active_now = self.is_active(after)
        is_on_break_now = self.is_on_break(after)

        # 1. 作業開始（作業中でも休憩中でもない状態から→作業中）
        if not was_active and not was_on_break and is_active_now:
            await self.handle_voice_join(member, before, after, text_channel)

        # 2. 作業開始 / 復帰（休憩中から→作業中）
        elif was_on_break and is_active_now:
            await self.handle_break_resume(member, after, text_channel)

        # 3. 休憩開始（作業中から→休憩中）
        elif was_active and is_on_break_now:
            await self.handle_break_start(member, after, text_channel)

        # 4. 作業終了（作業中または休憩中から→VCから完全に退出）
        elif (was_active or was_on_break) and not is_active_now and not is_on_break_now:
            await self.handle_voice_leave(member, after, text_channel)

    async def handle_voice_join(self, member, before, after, text_channel):
        """ユーザーがVCに参加した場合の処理"""
        # DBから以前のメッセージ状態を取得
        state = await self.bot.db.get_message_state(member.id)
        # state is (join_msg_id, leave_msg_id) or None
        prev_leave_msg_id = state[1] if state else None

        if text_channel:
            await delete_previous_message(text_channel, prev_leave_msg_id)

        self.voice_state_log[member.id] = datetime.now()
        # オフセットはリセット（新規参加なので）
        if member.id in self.voice_state_offset:
            del self.voice_state_offset[member.id]
            
        today_sec = await self.bot.db.get_today_seconds(member.id)
        time_str_text = format_duration(today_sec, for_voice=False)
        time_str_speak = format_duration(today_sec, for_voice=True)

        # Task and Streak support
        user_task = await self.bot.db.get_user_task(member.id)
        task_name = user_task if user_task else "作業"
        streak_days = await self.bot.db.get_user_streak(member.id)

        # Reading support
        user_reading = await self.bot.db.get_user_reading(member.id)
        speak_name = user_reading if user_reading else member.display_name

        msg_type = "join" if before.channel is None else "resume"
        
        if text_channel:
            # 安全にEmbedを生成
            msg_config = MESSAGES.get(msg_type, {})
            embed = create_embed_from_config(
                msg_config,
                name=member.display_name,
                current_total=time_str_text,
                task=task_name,
                days=streak_days
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            
            view = CheerView(member)
            join_msg = await text_channel.send(embed=embed, view=view)
            # DB更新: join_msg_idを設定、leave_msg_idは削除(None)
            await self.bot.db.set_message_state(member.id, join_msg.id, None)

        if msg_type == "join":
            msg_fmt = MESSAGES.get("join", {}).get("message", "{name}さんが{task}を始めました。現在{days}日継続中")
            
            try:
                speak_text = msg_fmt.format(
                    name=speak_name, 
                    task=task_name, 
                    days=streak_days, 
                    current_total=time_str_speak
                )
            except Exception as e:
                logger.error(f"音声メッセージフォーマットエラー: {e}")
                speak_text = f"{speak_name}さんが作業を始めました。"

            self.bot.loop.create_task(speak_in_vc(after.channel, speak_text, member.id))

        # ステータスボード更新
        status_cog = self.bot.get_cog("StatusCog")
        if status_cog:
            await status_cog.update_status_board()

    async def handle_break_start(self, member, after, text_channel):
        """ユーザーが休憩を開始した場合の処理（作業中→セルフデフ）"""
        # 現在までの作業時間を計算して蓄積
        if member.id in self.voice_state_log:
            work_start = self.voice_state_log[member.id]
            work_duration = datetime.now() - work_start
            work_seconds = int(work_duration.total_seconds())
            
            # 次のセッション用にオフセットとして保持
            self.voice_state_offset[member.id] = self.voice_state_offset.get(member.id, 0) + work_seconds
            
            # voice_state_log の開始時刻をリセット（休憩終了後の新規セッション開始用）
            del self.voice_state_log[member.id]
        
        # 休憩開始時刻を記録
        self.break_state_log[member.id] = datetime.now()
        
        # 初期化されていなければ初期化
        if member.id not in self.break_duration_accumulated:
            self.break_duration_accumulated[member.id] = 0
        
        if text_channel:
            # 「休憩開始」メッセージを表示
            msg_config = MESSAGES.get("break", {})
            embed = create_embed_from_config(
                msg_config,
                name=member.display_name
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            
            leave_msg = await text_channel.send(embed=embed)
            # join_msg_id は保持したまま、leave_msg_id だけ更新
            state = await self.bot.db.get_message_state(member.id)
            prev_join_msg_id = state[0] if state else None
            await self.bot.db.set_message_state(member.id, prev_join_msg_id, leave_msg.id)
        
        # ステータスボード更新
        status_cog = self.bot.get_cog("StatusCog")
        if status_cog:
            await status_cog.update_status_board()

    async def handle_break_resume(self, member, after, text_channel):
        """ユーザーが休憩から復帰した場合の処理（セルフデフ→作業中）"""
        # 休憩時間を計算して蓄積
        if member.id in self.break_state_log:
            break_start = self.break_state_log[member.id]
            break_duration = datetime.now() - break_start
            break_seconds = int(break_duration.total_seconds())
            
            self.break_duration_accumulated[member.id] = self.break_duration_accumulated.get(member.id, 0) + break_seconds
            del self.break_state_log[member.id]
        
        # 作業再開時刻を設定（休憩時間を除外するため、現在の時刻を新しい開始時刻とする）
        self.voice_state_log[member.id] = datetime.now()
        
        # 前回のメッセージ（休憩カード）を削除するだけ
        state = await self.bot.db.get_message_state(member.id)
        prev_join_msg_id = state[0] if state else None
        prev_leave_msg_id = state[1] if state else None
        
        if text_channel:
            await delete_previous_message(text_channel, prev_leave_msg_id)
        
        # メッセージ状態をクリア（join_msg_id は保持、leave_msg_id だけクリア）
        await self.bot.db.set_message_state(member.id, prev_join_msg_id, None)
        
        # ステータスボード更新
        status_cog = self.bot.get_cog("StatusCog")
        if status_cog:
            await status_cog.update_status_board()

    async def handle_voice_leave(self, member, after, text_channel):
        """ユーザーがVCを離れた場合の処理"""
        # 休憩中だった場合：オフセット計算も行う
        was_on_break = member.id in self.break_state_log
        if was_on_break:
            break_start = self.break_state_log[member.id]
            break_duration = datetime.now() - break_start
            break_seconds = int(break_duration.total_seconds())
            
            self.break_duration_accumulated[member.id] = self.break_duration_accumulated.get(member.id, 0) + break_seconds
            del self.break_state_log[member.id]
        
        # DBから以前のメッセージ状態を取得
        state = await self.bot.db.get_message_state(member.id)
        prev_join_msg_id = state[0] if state else None
        prev_leave_msg_id = state[1] if state else None

        if text_channel:
            # 休憩中に退出した場合は開発カード（join）も削除
            # 通常退出の場合は開発カードも削除（常に両方削除）
            await delete_previous_message(text_channel, prev_join_msg_id)
            await delete_previous_message(text_channel, prev_leave_msg_id)

        total_seconds_session = 0 # 今回のセッションで保存すべき時間（DB保存用・休憩時間除外）
        total_seconds_display = 0 # 表示用（オフセット込み・休憩時間除外）

        # 休憩前の作業時間があればそれを使用、なければ 0
        if member.id in self.voice_state_log:
            join_time = self.voice_state_log[member.id]
            leave_time = datetime.now()
            duration = leave_time - join_time
            total_seconds_session = int(duration.total_seconds())
            
            # オフセット取得
            offset = self.voice_state_offset.get(member.id, 0)
            total_seconds_display = total_seconds_session + offset

            await self.bot.db.add_study_log(
                member.id, 
                member.display_name, 
                join_time, 
                total_seconds_session, 
                leave_time
            )
            
            del self.voice_state_log[member.id]
            if member.id in self.voice_state_offset:
                del self.voice_state_offset[member.id]
        elif member.id in self.voice_state_offset:
            # voice_state_log がない場合（休憩開始時に削除されている）、
            # オフセット（休憩前の作業時間）のみをセッション時間として使用
            total_seconds_session = self.voice_state_offset[member.id]
            total_seconds_display = total_seconds_session
            
            # DB記録用に現在時刻を使用（休憩直後の退出など）
            await self.bot.db.add_study_log(
                member.id,
                member.display_name,
                datetime.now(),
                total_seconds_session,
                datetime.now()
            )
            
            del self.voice_state_offset[member.id]
        
        # 蓄積された休憩時間をリセット
        if member.id in self.break_duration_accumulated:
            del self.break_duration_accumulated[member.id]
        
        # 称号バッジ付与チェック
        await self.check_and_award_milestones(member, total_seconds_session, text_channel)

        current_str = format_duration(total_seconds_display, for_voice=False)
        today_sec = await self.bot.db.get_today_seconds(member.id)
        total_str = format_duration(today_sec, for_voice=False)
        
        msg_type = "leave" if after.channel is None else "break"

        if text_channel:
            # 安全にEmbedを生成
            msg_config = MESSAGES.get(msg_type, {})
            embed = create_embed_from_config(
                msg_config,
                name=member.display_name,
                time=current_str,
                total=total_str
            )
            embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
            
            leave_msg = await text_channel.send(embed=embed)
            # DB更新: join_msg_idは削除(None)、leave_msg_idを設定
            await self.bot.db.set_message_state(member.id, None, leave_msg.id)

        # ステータスボード更新
        status_cog = self.bot.get_cog("StatusCog")
        if status_cog:
            await status_cog.update_status_board()

            try:
                await status_cog.update_daily_server_total()
            except Exception:
                logger.exception("退出時の本日のサーバー合計即時更新に失敗しました")
    async def check_and_award_milestones(self, member, total_seconds_session, text_channel):
        """累計時間に基づいて称号ロールを付与する"""
        if total_seconds_session <= 0:
            return

        # 最新の累計時間を取得
        current_total_sec = await self.bot.db.get_total_seconds(member.id)
        current_hours = current_total_sec // 3600
        
        # 今回の作業前の時間
        prev_total_sec = current_total_sec - total_seconds_session
        prev_hours = prev_total_sec // 3600

        # 時間の境界をまたいだかチェック
        if prev_hours < current_hours:
            for hours, role_name in sorted(Config.MILESTONES.items()):
                # 今回の作業で境界を超えた場合
                if prev_hours < hours <= current_hours:
                    # ロールを取得して付与
                    role = discord.utils.get(member.guild.roles, name=role_name)
                    if role:
                        try:
                            await member.add_roles(role)
                            # お祝いメッセージ
                            if text_channel:
                                embed = discord.Embed(
                                    title="🎉 称号獲得！",
                                    description=f"{member.mention}さんが **{role_name}** の称号を獲得しました！\nおめでとうございます！👏👏",
                                    color=Colors.GOLD
                                )
                                await text_channel.send(embed=embed)
                        except discord.Forbidden:
                            logger.error(f"権限エラー: ロール {role_name} を付与できませんでした。Botのロール順位を確認してください。")
                    else:
                        logger.error(f"設定エラー: ロール「{role_name}」がサーバーに見つかりません。")

async def setup(bot):
    await bot.add_cog(StudyCog(bot))
