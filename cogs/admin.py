import discord
from discord.ext import commands
from datetime import datetime
from utils import safe_message_delete, format_duration
from messages import MESSAGES

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def help(self, ctx):
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

    @commands.command()
    async def add(self, ctx, member: discord.Member, minutes: int):
        """ユーザーの作業時間を追加・削除"""
        now = datetime.now()
        total_seconds = minutes * 60
        
        self.bot.db.execute(
            "INSERT INTO study_logs VALUES (?, ?, ?, ?, ?)",
            (member.id, member.display_name, now.isoformat(), total_seconds, now.isoformat())
        )
        
        new_total = self.bot.db.get_today_seconds(member.id)
        time_str = format_duration(new_total)
        
        action = "追加" if minutes > 0 else "削除"
        await ctx.send(f"✅ **{member.display_name}** さんの時間を {abs(minutes)}分 {action}しました。\n今日の合計: **{time_str}**")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
