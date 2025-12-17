import os
import asyncio
import discord
import edge_tts
import logging
import traceback
from config import Config
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
            source = None
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
                if source:
                    source.cleanup()
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


async def notify_backup(bot, title: str, content: str = None, exc: Exception = None, max_tb_chars: int = 1500):
    """バックアップチャンネルにエラーメッセージを送信する（失敗しても例外を投げない）。

    - `bot` は discord bot インスタンス
    - `title` は要約タイトル
    - `content` は文字列本文
    - `exc` に Exception を渡すとトレースバックを送信します
    """
    channel_id = Config.BACKUP_CHANNEL_ID
    if not channel_id:
        logger.warning("BACKUP_CHANNEL_ID が設定されていません。エラー通知をスキップします。")
        return

    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception as e:
                logger.error(f"バックアップチャンネル取得失敗 (ID: {channel_id}): {e}")
                return

        # トレースバックを整形
        tb_text = None
        if exc:
            tb_text = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        elif content and isinstance(content, str) and '\n' in content and len(content) > max_tb_chars:
            # content が長い場合に末尾を切り出す（ログの多くは末尾が重要）
            pass

        # Discord のメッセージ長制限に合わせて切り詰め
        message = f"**{title}**\n"
        if content:
            message += content

        if tb_text:
            if len(tb_text) > max_tb_chars:
                tb_text = "...(truncated)\n" + tb_text[-max_tb_chars:]
            message += f"\n```py\n{tb_text}\n```"

        # 送信（長すぎる場合は分割）
        if len(message) <= 1900:
            await channel.send(message)
        else:
            # 大きい場合は先頭のみ送る
            await channel.send(message[:1900] + "\n...(truncated)")

    except Exception as e:
        logger.error(f"バックアップ送信エラー: {e}")


def generate_7day_graph(daily_stats: dict, username: str) -> str:
    """
    過去7日間の作業時間推移グラフを生成（Discordダークテーマ風）
    """
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import japanize_matplotlib
    from datetime import datetime
    
    # Discordカラーパレット
    BG_COLOR = '#2f3136'      # 背景色
    TEXT_COLOR = '#dcddde'    # 文字色
    BAR_COLOR = '#5865F2'     # バーの色 (Blurple)
    GRID_COLOR = '#40444b'    # グリッド色

    # データを抽出
    dates = sorted(daily_stats.keys())
    hours = [daily_stats[d] / 3600 for d in dates]
    date_objs = [datetime.fromisoformat(d) for d in dates]
    
    # グラフ設定
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(BG_COLOR) # 外枠の背景
    ax.set_facecolor(BG_COLOR)        # グラフ内の背景

    # バーの描画（zorderでグリッドの手前に表示）
    bars = ax.bar(date_objs, hours, color=BAR_COLOR, width=0.6, zorder=3)
    
    # X軸設定
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.tick_params(axis='x', colors=TEXT_COLOR, labelsize=10)
    
    # Y軸設定
    ax.set_ylabel('作業時間 (時間)', fontsize=12, color=TEXT_COLOR)
    ax.tick_params(axis='y', colors=TEXT_COLOR, labelsize=10)
    
    # 枠線（スパイン）の整理
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(GRID_COLOR)
    ax.spines['bottom'].set_color(GRID_COLOR)
    
    # グリッド（点線）
    ax.grid(axis='y', color=GRID_COLOR, linestyle='--', linewidth=1, alpha=0.7, zorder=0)
    
    # タイトル
    ax.set_title(f'{username} - 過去7日間の推移', fontsize=14, fontweight='bold', color=TEXT_COLOR, pad=15)
    
    # バーの上に数値を表示
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{height:.1f}h',
                    ha='center', va='bottom', color=TEXT_COLOR, fontsize=10, fontweight='bold')
    
    # レイアウト調整
    fig.tight_layout()
    
    # 保存
    output_path = 'temp_7day_graph.png'
    fig.savefig(output_path, dpi=100, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    
    return output_path


def generate_hourly_graph(hourly_stats: dict, username: str) -> str:
    """
    時間帯別の集中度グラフを生成（Discordダークテーマ風）
    """
    import matplotlib.pyplot as plt
    import japanize_matplotlib
    
    # カラーパレット
    BG_COLOR = '#2f3136'
    TEXT_COLOR = '#dcddde'
    BAR_COLOR = '#5865F2'
    BAR_COLOR_INACTIVE = '#40444b' # 作業していない時間帯の色
    GRID_COLOR = '#40444b'

    # データ抽出
    hours = [int(h) for h in sorted(hourly_stats.keys())]
    values = [hourly_stats[str(h).zfill(2)] / 3600 for h in hours]
    
    # グラフ設定
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    
    # バーの色分け（値がある場所を目立たせる）
    colors = [BAR_COLOR if v > 0 else BAR_COLOR_INACTIVE for v in values]
    bars = ax.bar([f'{h:02d}' for h in hours], values, color=colors, width=0.7, zorder=3)
    
    # 軸ラベル
    ax.set_ylabel('作業時間 (時間)', fontsize=12, color=TEXT_COLOR)
    ax.set_xlabel('時刻', fontsize=12, color=TEXT_COLOR)
    
    # 目盛り設定
    ax.tick_params(axis='x', colors=TEXT_COLOR, labelsize=9)
    ax.tick_params(axis='y', colors=TEXT_COLOR, labelsize=10)
    ax.set_xticks(range(0, 24, 2)) # 2時間おきに表示ですっきりさせる
    
    # 枠線とグリッド
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(GRID_COLOR)
    ax.spines['bottom'].set_color(GRID_COLOR)
    ax.grid(axis='y', color=GRID_COLOR, linestyle='--', linewidth=1, alpha=0.7, zorder=0)
    
    # タイトル
    ax.set_title(f'{username} - 時間帯別の集中度', fontsize=14, fontweight='bold', color=TEXT_COLOR, pad=15)
    
    # 数値ラベル（0より大きい場合のみ表示）
    for bar in bars:
        height = bar.get_height()
        if height > 0.1: # 小さすぎる値は被るので表示しない
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{height:.1f}',
                    ha='center', va='bottom', color=TEXT_COLOR, fontsize=9)
    
    fig.tight_layout()
    
    output_path = 'temp_hourly_graph.png'
    fig.savefig(output_path, dpi=100, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    
    return output_path

