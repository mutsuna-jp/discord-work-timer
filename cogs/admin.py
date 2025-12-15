import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from utils import safe_message_delete, format_duration, create_embed_from_config
from messages import MESSAGES

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Botの使い方を表示します")
    async def help(self, interaction: discord.Interaction):
        """ヘルプを表示"""
        # await safe_message_delete(ctx.message) <- インタラクションなので削除不要
        await interaction.response.defer(ephemeral=True)

        help_config = MESSAGES.get("help", {})
        embed = create_embed_from_config(help_config)
        
        commands_list = help_config.get("commands", [])
        for cmd_item in commands_list:
            if isinstance(cmd_item, (list, tuple)) and len(cmd_item) >= 2:
                embed.add_field(name=cmd_item[0], value=cmd_item[1], inline=False)
        
        # Ephemeral (自分だけに見える) メッセージとして送信
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="[管理者用] ユーザーの作業時間を追加/削除します")
    @app_commands.describe(member="対象ユーザー", minutes="追加する分数（マイナスで削減）")
    @app_commands.default_permissions(administrator=True) 
    async def add(self, interaction: discord.Interaction, member: discord.Member, minutes: int):
        """ユーザーの作業時間を追加・削除"""
        # BACKUP_CHANNEL_ID でのみ実行可能にする
        backup_channel_id = getattr(self.bot, 'BACKUP_CHANNEL_ID', 0)
        if backup_channel_id and interaction.channel_id != backup_channel_id:
            await interaction.response.send_message(
                f"このコマンドはバックアップチャンネル <#{backup_channel_id}> でのみ実行可能です。",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        now = datetime.now()
        total_seconds = minutes * 60
        
        await self.bot.db.add_study_log(
            member.id,
            member.display_name,
            now,
            total_seconds,
            now
        )
        
        new_total = await self.bot.db.get_today_seconds(member.id)
        time_str = format_duration(new_total)
        
        action = "追加" if minutes > 0 else "削除"
        await interaction.followup.send(f"✅ **{member.display_name}** さんの時間を {abs(minutes)}分 {action}しました。\n今日の合計: **{time_str}**")

    @app_commands.command(name="clear_log", description="[管理者用] ログチャンネルのメッセージを全て削除します")
    @app_commands.default_permissions(administrator=True)
    async def clear_log(self, interaction: discord.Interaction):
        """ログチャンネルのクリーンアップ"""
        # BACKUP_CHANNEL_ID でのみ実行可能にする
        backup_channel_id = getattr(self.bot, 'BACKUP_CHANNEL_ID', 0)
        if backup_channel_id and interaction.channel_id != backup_channel_id:
            await interaction.response.send_message(
                f"このコマンドはバックアップチャンネル <#{backup_channel_id}> でのみ実行可能です。",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        
        log_channel_id = getattr(self.bot, 'LOG_CHANNEL_ID', 0)
        log_channel = self.bot.get_channel(log_channel_id)
        
        if not log_channel:
            await interaction.followup.send("エラー: ログチャンネルが見つかりません。", ephemeral=True)
            return

        try:
            deleted = await log_channel.purge(limit=None)
            await interaction.followup.send(f"ログチャンネル <#{log_channel_id}> のメッセージを全て削除しました。({len(deleted)}件)", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"削除中にエラーが発生しました: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
