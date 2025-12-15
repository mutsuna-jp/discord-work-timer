import discord
from discord.ext import commands
from datetime import datetime
from utils import safe_message_delete, format_duration, create_embed_from_config
from messages import MESSAGES

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def help(self, ctx):
        """ヘルプを表示"""
        await safe_message_delete(ctx.message)

        help_config = MESSAGES.get("help", {})
        embed = create_embed_from_config(help_config)
        
        commands_list = help_config.get("commands", [])
        for cmd_item in commands_list:
            if isinstance(cmd_item, (list, tuple)) and len(cmd_item) >= 2:
                embed.add_field(name=cmd_item[0], value=cmd_item[1], inline=False)
        
        await ctx.author.send(embed=embed)

    @commands.command()
    async def add(self, ctx, member: discord.Member, minutes: int):
        """ユーザーの作業時間を追加・削除"""
        now = datetime.now()
        total_seconds = minutes * 60
        
        self.bot.db.add_study_log(
            member.id,
            member.display_name,
            now,
            total_seconds,
            now
        )
        
        new_total = self.bot.db.get_today_seconds(member.id)
        time_str = format_duration(new_total)
        
        action = "追加" if minutes > 0 else "削除"
        await ctx.send(f"✅ **{member.display_name}** さんの時間を {abs(minutes)}分 {action}しました。\n今日の合計: **{time_str}**")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
