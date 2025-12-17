import asyncio
import logging
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks

from config import Config
from messages import Colors, MESSAGES
from utils import create_embed_from_config, format_duration

logger = logging.getLogger(__name__)

class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.update_lock = asyncio.Lock()
        self._ranking_message_id = None
        self._daily_message_id = None
        rank_cfg = MESSAGES.get("rank", {})
        self._ranking_embed_title = rank_cfg.get("embed_title", "🏆 今週の作業時間ランキング")
        
        # Debounce制御用
        self._update_event = asyncio.Event()
        # create_task を使う（Bot.loop に依存しない）
        self._update_manager_task = asyncio.create_task(self._status_update_manager())
        
        self.update_status_loop.start()
        self.ranking_task.start()

    def cog_unload(self):
        self.update_status_loop.cancel()
        self.ranking_task.cancel()
        if self._update_manager_task:
            self._update_manager_task.cancel()

    @tasks.loop(minutes=5)
    async def update_status_loop(self):
        await self.update_status_board()

    @update_status_loop.before_loop
    async def before_update_status_loop(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def ranking_task(self):
        # Update both weekly ranking and today's server total every 5 minutes
        await self.update_weekly_ranking()
        await self.update_daily_server_total()

    @ranking_task.before_loop
    async def before_ranking_task(self):
        await self.bot.wait_until_ready()

    async def update_weekly_ranking(self):
        """週次ランキングを投稿または更新する。VCの有無に関わらず実行される。"""
        channel = await self._acquire_status_channel("ランキング更新")
        if not channel:
            return

        if not self._check_channel_permissions(channel, "ランキング更新"):
            return

        try:
            rank_embed = await self._build_ranking_embed()
            await self._upsert_ranking_message(channel, rank_embed)
        except Exception:
            logger.exception("週間ランキング更新エラー")

    async def _status_update_manager(self):
        """更新リクエストを管理し、一定間隔で実行するループ"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                # リクエストが来るまで待機
                await self._update_event.wait()
                self._update_event.clear()
                
                # 実際の更新処理を実行
                await self._update_status_board_impl()
                
                # レートリミットウェイト (デバウンス/スロットリング)
                # ここで待機している間に次のリクエストが来ると、待機明けに即再実行される
                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("ステータス更新マネージャーエラー")
                await asyncio.sleep(5) # エラー時も少し待つ

    async def update_status_board(self):
        """ステータスボードの更新をリクエストする（即時実行ではなくスケジュール）"""
        self._update_event.set()

    async def _update_status_board_impl(self):
        """ステータスボードを更新する"""
        # ロックを取得して、同時実行を防ぐ
        async with self.update_lock:
            channel = await self._acquire_status_channel("ステータスボード更新")
            if not channel:
                return
            if not self._check_channel_permissions(channel, "ステータスボード更新"):
                return

            study_cog = self.bot.get_cog("StudyCog")
            if not study_cog:
                return
                
            active_users = study_cog.voice_state_log
            
            # 1. ゾンビユーザーのチェック (データ消失防止のため削除処理は行わない)
            # ステータスボードは表示のみを担当し、セッション管理はStudyCogのイベントハンドラに任せる
            # 必要であれば StudyCog 側で整合性チェックを行うべき


            # Botの過去のメッセージを検索 (Limitを増やして対応)
            my_messages = []
            try:
                # 新しい順に取得される
                async for message in channel.history(limit=50):
                    if message.author == self.bot.user:
                        my_messages.append(message)
            except Exception:
                logger.exception("メッセージ履歴の取得に失敗")
                return

            # 新しい順 -> 古い順 に並べ替え（上から順に表示するため）
            my_messages.reverse()
            my_messages = self._filter_status_messages(my_messages)

            if not active_users:
                # 作業中のユーザーがいない場合 -> 全てのBotメッセージを削除
                for msg in my_messages:
                    try:
                        await msg.delete()
                        await asyncio.sleep(0.12)  # rate-limit 緩和
                    except discord.NotFound:
                        # 既に削除済み
                        continue
                    except discord.Forbidden:
                        logger.error(f"メッセージ削除権限なし: チャンネルID {channel.id}")
                        return
                    except discord.HTTPException as e:
                        logger.error(f"メッセージ削除失敗: {e}")
                    except Exception:
                        logger.exception("メッセージ削除中に予期せぬエラーが発生しました")
                return

            # --- Embed作成処理 (複数メッセージページネーション対応) ---
            all_embeds = []
            
            # 1. ヘッダー用Embed
            now_str = datetime.now().strftime("%H:%M")
            header_embed = discord.Embed(
                title=f"現在の作業状況 (最終更新 {now_str})", 
                description=f"人数: **{len(active_users)}** 名",
                color=Colors.GREEN
            )
            all_embeds.append(header_embed)
            
            # 2. ユーザーごとのEmbed作成
            # 入室順（実質の開始時間が早い順）にソート
            # オフセットを引くことで、再起動前の開始時刻に相当する時間を算出
            sorted_users = sorted(
                active_users.items(), 
                key=lambda item: item[1] - timedelta(seconds=study_cog.voice_state_offset.get(item[0], 0))
            )

            for user_id, start_time in sorted_users:
                member = channel.guild.get_member(user_id)
                if not member:
                    try:
                        member = await channel.guild.fetch_member(user_id)
                    except discord.NotFound:
                        # メンバーが存在しない（サーバーを抜けた等）
                        continue
                    except discord.HTTPException as e:
                        logger.error(f"メンバ取得エラー: {e}")
                        continue
                    except Exception:
                        logger.exception("予期せぬエラー: メンバ取得中")
                        continue

                # タスクを取得
                task = await self.bot.db.get_user_task(user_id) or "作業"
                
                # 経過時間を計算
                now = datetime.now()
                duration = now - start_time
                # オフセット取得 (再起動前や論理分割前の時間)
                offset = study_cog.voice_state_offset.get(user_id, 0)
                total_seconds = int(duration.total_seconds()) + offset
                
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                
                if hours > 0:
                    time_str = f"{hours}時間{minutes}分"
                else:
                    time_str = f"{minutes}分"
                
                user_embed = discord.Embed(
                    description=f" {task} ({time_str})",
                    color=Colors.GREEN
                )
                user_embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                all_embeds.append(user_embed)

            # 3. ランダムなtipを取得して最後に表示
            tip = await self.bot.db.get_random_tip()
            if tip:
                tip_embed = discord.Embed(
                    title="Tips",
                    description=tip,
                    color=Colors.GOLD
                )
                all_embeds.append(tip_embed)

            # 4. チャンク分け (1メッセージにつきEmbed10個まで)
            chunk_size = 10
            embed_chunks = [all_embeds[i:i + chunk_size] for i in range(0, len(all_embeds), chunk_size)]

            # 5. 既存メッセージとの同期 (更新、新規送信、削除)
            max_len = max(len(embed_chunks), len(my_messages))

            for i in range(max_len):
                # A. 更新または新規送信が必要な場合
                if i < len(embed_chunks):
                    chunk = embed_chunks[i]
                    
                    if i < len(my_messages):
                        # 既存メッセージを更新
                        try:
                            await my_messages[i].edit(embeds=chunk)
                        except discord.Forbidden:
                            logger.error(f"ステータスボード更新エラー: 権限不足 (Channel ID: {channel.id})")
                        except Exception:
                            logger.exception("ステータスボード更新失敗")
                    else:
                        # 新規メッセージを送信
                        try:
                            await channel.send(embeds=chunk)
                        except discord.Forbidden:
                            logger.error(f"ステータスボード送信エラー: 権限不足 (Channel ID: {channel.id})")
                        except Exception:
                            logger.exception("ステータスボード送信失敗")
                
                # B. 不要なメッセージの削除
                else:
                    msg_to_delete = my_messages[i]
                    try:
                        await msg_to_delete.delete()
                    except discord.NotFound:
                        continue
                    except discord.Forbidden:
                        logger.error(f"余剰メッセージ削除権限なし: チャンネルID {channel.id}")
                    except Exception:
                        logger.exception("余剰メッセージ削除失敗")

                # ループ間で短い待機を挟み、レートリミットを緩和
                try:
                    await asyncio.sleep(0.12)
                except Exception:
                    # Sleep が失敗するようなケースは稀、ログだけ残す
                    logger.exception("スリープ中にエラー")
            if not self._check_channel_permissions(channel, "ランキング更新"):
                return

            # 1) 今日のサーバー合計を別カードでアップサート
            try:
                server_embed = await self._build_server_total_embed()
                await self._upsert_server_total_message(channel, server_embed)
            except Exception:
                logger.exception("本日のサーバー合計カードの更新に失敗しました")

            # 2) ランキングを別カードでアップサート
            try:
                rank_embed = await self._build_ranking_embed()
                await self._upsert_ranking_message(channel, rank_embed)
            except Exception:
                logger.exception("ランキングカードの更新に失敗しました")

    async def _build_ranking_embed(self) -> discord.Embed:
        rank_config = MESSAGES.get("rank", {})
        embed = create_embed_from_config(rank_config)
        now = datetime.now()
        # --- サーバー合計 (本日: DBの合計 + 現在作業中のユーザーの経過時間) ---
        try:
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            rows_today = await self.bot.db.get_study_logs_in_range(today_start)
            logged_total = sum(row[2] for row in rows_today) if rows_today else 0

            active_total = 0
            study_cog = self.bot.get_cog("StudyCog")
            if study_cog:
                for user_id, start_time in study_cog.voice_state_log.items():
                    try:
                        offset = study_cog.voice_state_offset.get(user_id, 0)
                        duration = int((now - start_time).total_seconds()) + offset
                        if duration > 0:
                            active_total += duration
                    except Exception:
                        # 取得に失敗したユーザーはスキップ
                        continue

            server_total_seconds = int(logged_total) + int(active_total)
            server_total_str = format_duration(server_total_seconds, for_voice=True)
            embed.add_field(name="本日のサーバー合計作業時間（Server Total）", value=f"**{server_total_str}**", inline=False)
        except Exception:
            logger.exception("サーバー合計の計算に失敗しました")

        monday = now - timedelta(days=now.weekday())
        monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = await self.bot.db.get_weekly_ranking(monday.isoformat())

        # Convert DB rows into a mutable mapping: {username: total_seconds}
        totals_by_name = {username: int(total_seconds) for username, total_seconds in rows} if rows else {}

        # Add currently active users' elapsed seconds to the totals (so ranking reflects live sessions)
        study_cog = self.bot.get_cog("StudyCog")
        if study_cog:
            for user_id, start_time in study_cog.voice_state_log.items():
                try:
                    offset = study_cog.voice_state_offset.get(user_id, 0)
                    duration = int((now - start_time).total_seconds()) + offset
                    if duration <= 0:
                        continue

                    # Try to get a human-readable name for the user
                    member = None
                    try:
                        # Prefer cached user info
                        member = self.bot.get_user(user_id)
                    except Exception:
                        member = None

                    name = None
                    if member:
                        name = getattr(member, "display_name", None) or getattr(member, "name", None) or str(user_id)
                    else:
                        # Fallback to a generic identifier (DB rows usually contain usernames)
                        name = str(user_id)

                    totals_by_name[name] = totals_by_name.get(name, 0) + duration
                except Exception:
                    continue

        if not totals_by_name:
            embed.description = rank_config.get("empty_message", "今週はまだ誰も作業していません...！")
            return embed

        # Sort by total seconds descending and prepare formatted rank lines
        sorted_totals = sorted(totals_by_name.items(), key=lambda kv: kv[1], reverse=True)
        row_fmt = rank_config.get("row", "{icon} **{name}**: {time}\n")
        rank_lines = []
        for idx, (username, total_seconds) in enumerate(sorted_totals, 1):
            time_str = format_duration(total_seconds, for_voice=True)
            icon = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            rank_lines.append(row_fmt.format(icon=icon, name=username, time=time_str))

        embed.add_field(name="Top Members", value="".join(rank_lines), inline=False)
        return embed

    async def _build_server_total_embed(self) -> discord.Embed:
        """本日のサーバー合計作業時間だけを返すEmbedを生成する"""
        cfg = MESSAGES.get("rank", {})
        embed = discord.Embed(
            title=cfg.get("server_total_title", "本日のサーバー合計作業時間"),
            color=Colors.GOLD
        )

        try:
            now = datetime.now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            rows_today = await self.bot.db.get_study_logs_in_range(today_start)
            logged_total = sum(row[2] for row in rows_today) if rows_today else 0

            active_total = 0
            study_cog = self.bot.get_cog("StudyCog")
            if study_cog:
                for user_id, start_time in study_cog.voice_state_log.items():
                    try:
                        offset = study_cog.voice_state_offset.get(user_id, 0)
                        duration = int((now - start_time).total_seconds()) + offset
                        if duration > 0:
                            active_total += duration
                    except Exception:
                        continue

            server_total_seconds = int(logged_total) + int(active_total)
            server_total_str = format_duration(server_total_seconds, for_voice=True)
            embed.add_field(name="本日のサーバー合計作業時間", value=f"**{server_total_str}**", inline=False)
        except Exception:
            logger.exception("サーバー合計の計算に失敗しました")

        return embed

    async def _upsert_server_total_message(self, channel: discord.TextChannel, embed: discord.Embed):
        msg = None
        if self._daily_message_id:
            try:
                msg = await channel.fetch_message(self._daily_message_id)
            except discord.NotFound:
                self._daily_message_id = None
            except Exception:
                logger.exception("サーバー合計メッセージ取得エラー")

        if not msg:
            async for candidate in channel.history(limit=50):
                if candidate.author == self.bot.user and self._is_server_total_message(candidate):
                    msg = candidate
                    self._daily_message_id = candidate.id
                    break

        if msg:
            try:
                await msg.edit(embed=embed)
                return
            except Exception:
                logger.exception("サーバー合計メッセージ更新失敗")

        try:
            new_msg = await channel.send(embed=embed)
            self._daily_message_id = new_msg.id
        except Exception:
            logger.exception("サーバー合計メッセージ送信エラー")

    async def update_daily_server_total(self):
        """Public method to post or update today's server total embed/message."""
        channel = await self._acquire_status_channel("サーバー合計更新")
        if not channel:
            return

        if not self._check_channel_permissions(channel, "サーバー合計更新"):
            return

        try:
            server_embed = await self._build_server_total_embed()
            await self._upsert_server_total_message(channel, server_embed)
        except Exception:
            logger.exception("本日のサーバー合計更新エラー")

    def _is_server_total_message(self, message: discord.Message) -> bool:
        if not message.embeds:
            return False

        first_title = message.embeds[0].title
        return first_title == MESSAGES.get("rank", {}).get("server_total_title", "本日のサーバー合計作業時間")

    async def _upsert_ranking_message(self, channel: discord.TextChannel, embed: discord.Embed):
        rank_msg = None
        if self._ranking_message_id:
            try:
                rank_msg = await channel.fetch_message(self._ranking_message_id)
            except discord.NotFound:
                self._ranking_message_id = None
            except Exception:
                logger.exception("ランキングメッセージ取得エラー")
                rank_msg = None

        if not rank_msg:
            async for candidate in channel.history(limit=50):
                if candidate.author == self.bot.user and self._is_ranking_message(candidate):
                    rank_msg = candidate
                    self._ranking_message_id = candidate.id
                    break

        if rank_msg:
            try:
                await rank_msg.edit(embed=embed)
                return
            except Exception:
                logger.exception("ランキングメッセージ更新失敗")

        try:
            new_msg = await channel.send(embed=embed)
            self._ranking_message_id = new_msg.id
        except Exception:
            logger.exception("ランキングメッセージ送信エラー")

    async def _acquire_status_channel(self, context: str):
        channel_id = Config.STATUS_CHANNEL_ID
        if not channel_id:
            logger.warning(f"{context}: STATUS_CHANNEL_ID が設定されていません。")
            return None

        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                logger.warning(f"{context}: チャンネル取得失敗 (ID: {channel_id}): {e}")
                return None

        return channel

    def _check_channel_permissions(self, channel, context: str) -> bool:
        guild = channel.guild
        if not guild or not guild.me:
            logger.warning(f"{context}: ギルドメンバー情報が取得できません。(Channel ID: {channel.id})")
            return False

        permissions = channel.permissions_for(guild.me)
        if not permissions.view_channel:
            logger.warning(f"{context}: チャンネル {channel.id} を閲覧する権限がありません。")
            return False
        if not permissions.send_messages:
            logger.warning(f"{context}: チャネル {channel.id} にメッセージ送信権限がありません。")
            return False
        if not permissions.read_message_history:
            logger.warning(f"{context}: チャンネル {channel.id} の履歴を読む権限がありません。")
            return False

        return True

    def _is_ranking_message(self, message: discord.Message) -> bool:
        if not message.embeds:
            return False

        first_title = message.embeds[0].title
        return first_title == self._ranking_embed_title

    def _filter_status_messages(self, messages):
        filtered = []
        for msg in messages:
            if self._is_ranking_message(msg):
                self._ranking_message_id = msg.id
                continue
            if self._is_server_total_message(msg):
                self._daily_message_id = msg.id
                continue
            filtered.append(msg)
        return filtered

async def setup(bot):
    await bot.add_cog(StatusCog(bot))
