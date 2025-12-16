import os
import asyncio
import discord
import edge_tts
import logging
from messages import Colors

logger = logging.getLogger(__name__)

VOICE_NAME = "ja-JP-NanamiNeural"
FFMPEG_CLEANUP_DELAY = 1

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

# 音声再生管理用 {guild_id: {'queue': asyncio.Queue, 'task': asyncio.Task}}
voice_states = {}

async def speak_in_vc(voice_channel, text, member_id):
    """音声チャネルに入ってテキストを読み上げる（キューによる連続再生・チャンネル移動対応）"""
    guild_id = voice_channel.guild.id
    
    # 状態の初期化または取得
    if guild_id not in voice_states or voice_states[guild_id]['task'].done():
        voice_states[guild_id] = {
            'queue': asyncio.Queue(),
            # タスク起動用。初期接続はWorker内で行うため、ここではGuildを渡しておくなどの設計も可能だが
            # 既存維持で最初のチャンネルを渡して起動する
            'task': asyncio.create_task(voice_worker(voice_channel)) 
        }

    # キューに追加 (チャンネル情報も含める)
    await voice_states[guild_id]['queue'].put((voice_channel, text, member_id))

async def voice_worker(initial_voice_channel):
    guild_id = initial_voice_channel.guild.id
    queue = voice_states[guild_id]['queue']
    vc = None

    try:
        # 初期接続
        vc = initial_voice_channel.guild.voice_client
        if not vc:
            try:
                vc = await initial_voice_channel.connect()
            except Exception as e:
                logger.error(f"初期接続失敗: {e}")
                # 接続できない場合でも、ループ内で再試行またはmove_toでリカバリするチャンスを残すか、
                # あるいはここで終了するか。一旦キュー処理へ進む。
        
        while True:
            try:
                # 次のメッセージを待つ（5秒間来なければ切断）
                target_channel, text, member_id = await asyncio.wait_for(queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                break

            # チャンネル移動チェック
            if vc and vc.is_connected():
                if vc.channel.id != target_channel.id:
                    try:
                        await vc.move_to(target_channel)
                        # 移動直後は少し待ったほうが安定する場合がある
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"チャンネル移動失敗 ({target_channel.name}): {e}")
                        # 移動できない場合、再生をあきらめて次に進むべきか、今の場所で流すか。
                        # ここではログを出してスキップ（対象者に聞こえないため）
                        queue.task_done()
                        continue
            else:
                # 切断されていた場合は再接続
                try:
                    vc = await target_channel.connect()
                except Exception as e:
                    logger.error(f"再接続失敗: {e}")
                    queue.task_done()
                    continue

            filename = f"voice_{member_id}_{int(asyncio.get_event_loop().time() * 1000)}.mp3"
            try:
                await generate_voice(text, filename)
                
                if not os.path.exists(filename):
                     logger.error(f"音声ファイル生成失敗: {filename}")
                     queue.task_done()
                     continue

                source = discord.FFmpegPCMAudio(filename)
                
                if not vc.is_playing():
                    vc.play(source)
                    while vc.is_playing():
                        await asyncio.sleep(FFMPEG_CLEANUP_DELAY)
                
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"音声再生プロセスエラー: {e}")
            finally:
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except:
                        pass
                queue.task_done()

    except Exception as e:
        logger.error(f"Voice Worker エラー: {e}")
    finally:
        if vc and vc.is_connected():
            await vc.disconnect()
        
        if guild_id in voice_states and voice_states[guild_id]['queue'] is queue:
            del voice_states[guild_id]

async def safe_message_delete(message):
    """権限がない場合もスキップするメッセージ削除"""
    if message.guild:
        try:
            await message.delete()
        except discord.Forbidden:
            logger.warning(f"メッセージ削除失敗: 権限不足 (Manage Messages) - Channel: {message.channel.name}")
        except discord.NotFound:
            pass
        except Exception as e:
            logger.error(f"メッセージ削除エラー: {e}")

async def delete_previous_message(channel, message_id):
    """チャネルの前のメッセージを削除"""
    if message_id:
        try:
            # fetch_messageを使わず、get_partial_messageで直接削除APIを叩く
            await channel.get_partial_message(message_id).delete()
        except discord.NotFound:
            pass 
        except Exception as e:
            logger.error(f"メッセージ削除エラー: {e}")

def create_embed_from_config(config, **kwargs):
    """設定辞書からEmbedを安全に生成"""
    title = config.get("embed_title", "")
    if title:
        try:
            title = title.format(**kwargs)
        except Exception:
            pass

    desc = config.get("embed_description") or config.get("embed_desc", "")
    if desc:
        try:
            desc = desc.format(**kwargs)
        except Exception:
            pass

    color = config.get("embed_color", Colors.GRAY)

    embed = discord.Embed(title=title, description=desc, color=color)
    
    # 共通フィールド設定がある場合
    if "fields" in config and isinstance(config["fields"], list):
        for field in config["fields"]:
            name = field.get("name", "")
            value = field.get("value", "")
            inline = field.get("inline", False)
            
            try:
                name = name.format(**kwargs)
            except Exception:
                pass
            
            try:
                value = value.format(**kwargs)
            except Exception:
                pass
                
            if value:
                if not name:
                    name = "\u200b"
                embed.add_field(name=name, value=value, inline=inline)
    
    return embed
