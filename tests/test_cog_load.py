import pytest
import discord
from discord.ext import commands

@pytest.mark.asyncio
async def test_all_extensions_load_and_slash_command_names_are_unique():
    bot=commands.Bot(command_prefix='!',intents=discord.Intents.none(),help_command=None)
    modules=('wallet','deposits','mines','dragon_tower','blackjack','crash','limbo','limo','admin','responsible','casino','new_games','dashboard','prefix','prefix_bridge')
    try:
        for module in modules: await bot.load_extension('cogs.'+module)
        names=[command.name for command in bot.tree.get_commands()]
        assert len(names)==len(set(names))
        required={'mines','blackjack','dragon-tower','crash','limo','limbo','dice','chicken-road','pump','fairness','fair-verify','admin-dashboard','admin-prefix','admin-emoji','admin-logs','admin-deposits','admin-branding','admin-economy','daily','limits','leaderboard'}
        assert required.issubset(names)
        assert {'home','daily','limits','leaderboard','admin-economy'}.issubset(bot.all_commands)
    finally:
        await bot.close()
