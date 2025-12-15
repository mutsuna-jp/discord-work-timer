import os
import asyncio
import discord
import edge_tts

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

async def speak_in_vc(voice_channel, text, member_id):
    """音声チャネルに入ってテキストを読み上げる"""
    filename = f"voice_{member_id}.mp3"
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

async def safe_message_delete(message):
    """権限がない場合もスキップするメッセージ削除"""
    if message.guild:
        try:
            await message.delete()
        except Exception:
            pass

async def delete_previous_message(channel, message_id):
    """チャネルの前のメッセージを削除"""
    if message_id:
        try:
            # fetch_messageを使わず、get_partial_messageで直接削除APIを叩く
            await channel.get_partial_message(message_id).delete()
        except discord.NotFound:
            pass 
        except Exception as e:
            print(f"メッセージ削除エラー: {e}")

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

    color = config.get("embed_color", 0x808080)

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
                
            if name and value:
                embed.add_field(name=name, value=value, inline=inline)
    
    return embed
