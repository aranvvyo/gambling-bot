import discord
from discord import app_commands
from discord.ext import commands
from services.ui import embed, asset_file


def command_groups(bot):
    rows={'Games':[],'Wallet':[],'Deposits':[],'Responsible play':[],'Administration':[],'Fairness':[],'Other':[]}
    games={'mines','blackjack','dragon-tower','crash','limbo','limo','dice','chicken-road','pump'}
    wallet={'balance','transactions','profile','daily','leaderboard','limits'}; deposits={'deposit','deposit-status','deposit-history'}
    responsible={'play-limit','self-exclude','play-status'}
    fairness={'fairness','fair-verify'}
    for command in bot.tree.walk_commands():
        if not isinstance(command,app_commands.Command): continue
        name=command.name
        if name in games: group='Games'
        elif name in wallet: group='Wallet'
        elif name in deposits: group='Deposits'
        elif name in responsible: group='Responsible play'
        elif name.startswith('admin-'): group='Administration'
        elif name in fairness: group='Fairness'
        elif name in {'help','casino'}: continue
        else: group='Other'
        rows[group].append(f'`/{name}` — {command.description or "Casino command"}')
    return {key:sorted(value) for key,value in rows.items() if value}

class CasinoGuideSelect(discord.ui.Select):
    def __init__(self,owner,groups):
        self.owner=owner;self.groups=groups
        super().__init__(placeholder='Browse a command category',min_values=1,max_values=1,options=[discord.SelectOption(label=k,value=k) for k in groups])
    async def callback(self,it):
        if it.user.id!=self.owner:return await it.response.send_message(embed=embed('Private command guide','This menu belongs to another player.',state='error'),ephemeral=True)
        e=embed(f'Command guide · {self.values[0]}','Existing slash commands, grouped from the loaded bot registry.')
        e.add_field(name='Commands',value='\n'.join(self.groups[self.values[0]])[:1024],inline=False)
        await it.response.edit_message(embed=e,view=self.view)

class CasinoGuideView(discord.ui.View):
    def __init__(self,owner,groups):
        super().__init__(timeout=180);self.owner=owner;self.message=None;self.add_item(CasinoGuideSelect(owner,groups))
    async def interaction_check(self,it):
        if it.user.id!=self.owner:
            await it.response.send_message(embed=embed('Private command guide','This menu belongs to another player.',state='error'),ephemeral=True);return False
        return True
    async def on_timeout(self):
        for child in self.children:child.disabled=True
        if self.message:
            try:await self.message.edit(view=self)
            except discord.HTTPException:pass

class Casino(commands.Cog):
 def __init__(self,bot):self.bot=bot
 @app_commands.command(name='casino',description='Open the Emerald Vault casino lobby')
 async def casino(self,it:discord.Interaction):
  e=embed('Emerald Vault','A calm, private-first casino lobby. Choose a game, check your wallet, or open the deposit menu.\n\n**Games use virtual credits** · New deposit invoices are disabled by default. Fairness commitments and play limits remain active.')
  banner=asset_file('welcome');logo=asset_file('logo')
  if banner:e.set_image(url='attachment://welcome.png')
  if logo:e.set_thumbnail(url='attachment://logo.png')
  files=[f for f in (banner,logo) if f]
  view=CasinoGuideView(it.user.id,command_groups(self.bot))
  await it.response.send_message(embed=e,files=files,view=view,ephemeral=True)
  view.message=await it.original_response()
 @app_commands.command(name='help',description='Browse registered commands, wallet, games and play controls')
 async def help(self,it:discord.Interaction):
  groups=command_groups(self.bot)
  if not groups:return await it.response.send_message(embed=embed('Command guide','No commands are currently registered.',state='error'),ephemeral=True)
  key=next(iter(groups));e=embed(f'Command guide · {key}','Browse actual commands from the loaded bot registry. Dot-prefix versions are available for the listed commands.')
  e.add_field(name='Commands',value='\n'.join(groups[key])[:1024],inline=False)
  view=CasinoGuideView(it.user.id,groups)
  await it.response.send_message(embed=e,view=view,ephemeral=True)
  view.message=await it.original_response()
async def setup(bot):await bot.add_cog(Casino(bot))
