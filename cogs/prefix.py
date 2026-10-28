import re
import uuid
from decimal import Decimal, InvalidOperation
import discord
from discord.ext import commands
from services.ui import embed, money, deposit_status, qr_file, asset_file
from services.emojis import resolve_emoji
from services.components import EmbedPager
from services.apirone import SUPPORTED


async def private_reply(ctx, *, embed_obj, view=None, file=None):
    if not ctx.guild:
        return await ctx.reply(embed=embed_obj,view=view,file=file,mention_author=False)
    try:
        dm=getattr(ctx.author,'dm_channel',None) or await ctx.author.create_dm()
        message=await dm.send(embed=embed_obj,view=view,file=file)
        await ctx.reply(embed=embed('Private response sent','Check your DMs for this account response.',state='info'),mention_author=False)
        return message
    except discord.Forbidden:
        return await ctx.reply(embed=embed('Private message unavailable','Enable direct messages from server members to view this account response.',state='error'),mention_author=False)


def parse_credits(raw, *, allow_suffix=True):
    """Amounts are virtual credits (VC). A trailing $ is accepted as legacy syntax only."""
    value = raw.strip().replace(',', '')
    if allow_suffix and value.endswith('$'):
        value = value[:-1]
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('Enter a positive whole number of VC (for example `1` or `1$`). The `$` suffix is syntax only; no USD conversion is made.')
    amount = int(value)
    if amount <= 0:
        raise ValueError('Amount must be greater than zero.')
    return amount


class DepositSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(placeholder='Choose a supported asset and network', options=[
            discord.SelectOption(label=SUPPORTED[key][0], description=SUPPORTED[key][1], value=key, emoji=resolve_emoji(cog.bot,{'ltc':'ltc','usdt@bnb':'usdt_bep20','usdt@eth':'usdt_erc20'}[key]))
            for key in ('ltc', 'usdt@bnb', 'usdt@eth')
        ], min_values=1, max_values=1)
    async def callback(self, interaction):
        if interaction.user.id != self.view.owner:
            return await interaction.response.send_message(embed=embed('Private deposit menu', 'This menu belongs to another user.'), ephemeral=True)
        if not (self.cog.bot.settings.deposits_enabled and getattr(self.cog.bot.settings,'deposits_live_verified',False) and self.cog.bot.payments and getattr(self.cog.bot.payments,'live_enabled',False)):
            return await interaction.response.send_message(embed=embed('Deposits disabled','New deposit invoices are disabled by default. No address was generated.',state='pending'),ephemeral=True)
        if not self.cog.bot.payments:
            return await interaction.response.send_message(embed=embed('Deposits unavailable', 'Apirone credentials are not configured. No address was generated.',state='error'), ephemeral=True)
        await interaction.response.send_message(embed=embed('Deposit amount', f'Use `{self.cog.bot.settings.min_deposit}` or more in the selected coin, then send `{self.cog.bot.active_prefix}depoamount {self.values[0]} AMOUNT` here in this DM. This amount is the cryptocurrency amount, not VC.'), ephemeral=True)
        self.view.currency = self.values[0]

class DepositMenu(discord.ui.View):
    def __init__(self, cog, owner):
        super().__init__(timeout=300); self.cog=cog; self.owner=owner; self.currency=None; self.message=None
        self.add_item(DepositSelect(cog))
    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner:
            await interaction.response.send_message(embed=embed('Private deposit menu','This menu belongs to another user.'),ephemeral=True); return False
        return True
    async def on_timeout(self):
        for child in self.children: child.disabled=True
        if self.message:
            try: await self.message.edit(view=self)
            except discord.HTTPException: pass

GAME_META = {
    'mines':('Mines','Reveal safe tiles, then cash out. `.mines BET [MINES] [16|20]`'),
    'blackjack':('Blackjack','Hit, stand, or double down. `.blackjack BET`'),
    'dragon-tower':('Dragon Tower','Climb safe floors and cash out. `.dragon-tower BET 2 [FLOORS]`'),
    'crash':('Crash','Cash out before the multiplier crashes. `.crash BET [AUTO_CASHOUT]`'),
    'limbo':('Limbo','Pick a target multiplier. `.limbo BET TARGET`'),
    'limo':('Limo','Choose a car count. `.limo BET [CARS]`'),
    'dice':('Dice','Pick over or under. `.dice BET over TARGET`'),
    'chicken-road':('Chicken Road','Advance and cash out. `.chicken-road BET`'),
    'pump':('Pump','Grow the multiplier, then cash out. `.pump BET`'),
}

class GamesSelect(discord.ui.Select):
    def __init__(self, owner, game_names, prefix='.'):
        self.owner=owner; self.prefix=prefix
        icons={'mines':'💎','blackjack':'♠️','dragon-tower':'♜','crash':'↗','limbo':'◎','limo':'▰','dice':'⚄','chicken-road':'♧','pump':'▲'}
        options=[discord.SelectOption(label=GAME_META[name][0],description=GAME_META[name][1].replace('`.','`'+prefix).split('`')[0][:95],value=name,emoji=icons.get(name,'◆')) for name in game_names]
        super().__init__(placeholder='Choose a game to see its command',min_values=1,max_values=1,options=options)
    async def callback(self, interaction):
        if interaction.user.id!=self.owner:
            return await interaction.response.send_message(embed=embed('Game menu','This menu belongs to another player.',state='error'),ephemeral=True)
        label,detail=GAME_META[self.values[0]]; detail=detail.replace('`.','`'+self.prefix)
        await interaction.response.send_message(embed=embed(label,detail+'\n\nWagers use VC. Your daily limit and self-exclusion apply.',state='info'),ephemeral=True)

class GamesView(discord.ui.View):
    def __init__(self,owner,game_names,prefix='.'):
        super().__init__(timeout=180); self.owner=owner; self.message=None
        if game_names:self.add_item(GamesSelect(owner,game_names,prefix))
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message(embed=embed('Game menu','This menu belongs to another player.',state='error'),ephemeral=True); return False
        return True
    async def on_timeout(self):
        for child in self.children: child.disabled=True
        if self.message:
            try: await self.message.edit(view=self)
            except discord.HTTPException: pass

class HelpCategorySelect(discord.ui.Select):
    def __init__(self,owner,categories):
        self.owner=owner; self.categories=categories
        super().__init__(placeholder='Filter commands by category',min_values=1,max_values=1,options=[discord.SelectOption(label=k, value=k) for k in categories])
    async def callback(self,interaction):
        if interaction.user.id!=self.owner:
            return await interaction.response.send_message(embed=embed('Command guide','This menu belongs to another player.',state='error'),ephemeral=True)
        await interaction.response.edit_message(embed=self.categories[self.values[0]],view=self.view)

class HelpView(discord.ui.View):
    def __init__(self,owner,categories):
        super().__init__(timeout=180); self.owner=owner; self.message=None; self.add_item(HelpCategorySelect(owner,categories))
    async def interaction_check(self,interaction):
        if interaction.user.id!=self.owner:
            await interaction.response.send_message(embed=embed('Command guide','This menu belongs to another player.',state='error'),ephemeral=True); return False
        return True
    async def on_timeout(self):
        for child in self.children: child.disabled=True
        if self.message:
            try: await self.message.edit(view=self)
            except discord.HTTPException: pass


class HomeView(discord.ui.View):
    def __init__(self,cog,owner):
        super().__init__(timeout=180);self.cog=cog;self.bot=cog.bot;self.owner=owner;self.message=None
    async def interaction_check(self,it):
        if it.user.id!=self.owner:
            await it.response.send_message(embed=embed('Private player home','This menu belongs to another player.',state='error'),ephemeral=True);return False
        return True
    @discord.ui.button(label='Claim daily',style=discord.ButtonStyle.success,emoji='🎁')
    async def claim_daily(self,it,b):
        try:result=await self.bot.db.daily_claim(it.user.id,int(self.bot.settings.daily_reward))
        except ValueError as exc:return await it.response.send_message(embed=embed('Daily reward unavailable',str(exc),state='pending' if 'cooldown' in str(exc).lower() else 'error'),ephemeral=True)
        await it.response.send_message(embed=embed('Daily reward claimed',f'Added **{money(result["amount"])}**. New balance: **{money(result["balance"])}**. Next claim <t:{result["next_claim_at"]}:R>.',state='success'),ephemeral=True)
    @discord.ui.button(label='Wallet',style=discord.ButtonStyle.secondary,emoji='💼')
    async def wallet(self,it,b):
        balance=await self.bot.db.balance(it.user.id);spent=await self.bot.db.daily_wagered(it.user.id)
        await it.response.send_message(embed=embed('Your wallet',f'Available: **{money(balance)}**\nWagered today: **{money(spent)}**',state='info'),ephemeral=True)
    @discord.ui.button(label='Games',style=discord.ButtonStyle.primary,emoji='🎮')
    async def games(self,it,b):
        names=[]
        for name in ('mines','blackjack','dragon_tower','crash','limbo','limo','dice','chicken-road','pump'):
            if (await self.bot.db.get_config('game_enabled:'+name,'true')).lower()=='true':names.append(name.replace('_','-'))
        await it.response.send_message(embed=embed('Available games',(' · '.join(f'`{self.bot.active_prefix}{n}`' for n in names) if names else 'Games are currently paused.'),state='info'),ephemeral=True)
    @discord.ui.button(label='Deposits',style=discord.ButtonStyle.secondary,emoji='💳')
    async def deposits(self,it,b):
        if self.bot.settings.maintenance:return await it.response.send_message(embed=embed('Deposits paused',self.bot.maintenance_notice,state='pending'),ephemeral=True)
        if not (self.bot.settings.deposits_enabled and getattr(self.bot.settings,'deposits_live_verified',False) and self.bot.payments and self.bot.payments.live_enabled):
            return await it.response.send_message(embed=embed('Deposits unavailable','New invoices are disabled pending provider configuration and live verification. No address was generated.',state='pending'),ephemeral=True)
        view=DepositMenu(self.cog,self.owner)
        await it.response.send_message(embed=embed('Private deposit menu','Select one of the supported assets. The invoice uses the provider returned address and exact amount.'),view=view,ephemeral=True)
        try:view.message=await it.original_response()
        except (AttributeError,discord.HTTPException):pass
    @discord.ui.button(label='Play safe',style=discord.ButtonStyle.secondary,emoji='🛡️')
    async def play_safe(self,it,b):
        from cogs.wallet import limits_text
        controls=await self.bot.db.play_controls(it.user.id)
        await it.response.send_message(embed=embed('Responsible play',f'{limits_text(self.bot,it.user.id,controls)}\n\nSet limits with `{self.bot.active_prefix}play-limit AMOUNT`, pause play with `{self.bot.active_prefix}self-exclude DAYS`, or review `{self.bot.active_prefix}play-status`.',state='info'),ephemeral=True)
    async def on_error(self,it,error,item):
        self.bot.logger.error('Player home component failed type=%s',type(error).__name__)
        try:
            if it.response.is_done():await it.followup.send(embed=embed('Home action unavailable','The account view could not complete this action. Check the displayed balance and try again.',state='error'),ephemeral=True)
            else:await it.response.send_message(embed=embed('Home action unavailable','The account view could not complete this action. Check the displayed balance and try again.',state='error'),ephemeral=True)
        except discord.HTTPException:pass
    async def on_timeout(self):
        for item in self.children:item.disabled=True
        if self.message:
            try:await self.message.edit(view=self)
            except discord.HTTPException:pass

async def home_embed(bot,user):
    balance=await bot.db.balance(user.id);spent=await bot.db.daily_wagered(user.id)
    cooldown=await bot.db.daily_claim_status(user.id)
    recent=await bot.db.history(user.id,3)
    deposits=await bot.db.deposit_history(user.id,1)
    ctl=await bot.db.play_controls(user.id)
    cap=min(bot.settings.daily_bet_limit,ctl['daily_limit']) if ctl and ctl['daily_limit'] else bot.settings.daily_bet_limit
    recent_text='\n'.join(f"{row['kind'].replace('_',' ').title()} · {money(int(row['amount']))}" for row in recent) or 'No recent activity'
    deposit_text=f"{deposits[0]['currency']} · {deposits[0]['status']}" if deposits else 'No deposit invoices'
    excluded=bool(ctl and ctl['excluded_until'] and int(ctl['excluded_until'])>int(__import__('time').time()))
    daily=('Disabled' if bot.settings.daily_reward<=0 else (f'Available in {cooldown//3600}h {(cooldown%3600)//60}m' if cooldown else f'Available · {money(bot.settings.daily_reward)}'))
    e=embed(f'{resolve_emoji(bot,"achievement")} Player home',f'Welcome, {user.mention}. Your account summary is private.')
    e.add_field(name='Wallet',value=f'**{money(balance)}**\nToday: {money(spent)} / {money(cap)}',inline=True)
    e.add_field(name='Daily reward',value=daily,inline=True)
    e.add_field(name='Play status',value='Self-excluded' if excluded else 'Ready',inline=True)
    e.add_field(name='Recent activity',value=recent_text,inline=False)
    e.add_field(name='Deposits',value=deposit_text,inline=True)
    e.add_field(name='Games',value=f'Use `{bot.active_prefix}games` to browse available games.',inline=True)
    return e

class PrefixCommands(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.command(name='bal', aliases=['balance'], help='View your available VC balance.')
    @commands.cooldown(3, 5, commands.BucketType.user)
    async def balance(self, ctx):
        balance=await self.bot.db.balance(ctx.author.id)
        e=embed(f'{resolve_emoji(self.bot,"outcome")} Wallet balance','Your available virtual-credit balance.')
        e.add_field(name='Available',value=f'**{money(balance)}**',inline=True)
        banner=asset_file('wallet')
        if banner:e.set_image(url='attachment://wallet.png')
        e.add_field(name='Currency',value=f'`{self.bot.settings.currency_symbol}` · virtual credits',inline=True)
        await private_reply(ctx,embed_obj=e,file=banner)

    @commands.command(name='tip',help='Send whole VC to another human user. Example: `.tip @user 25`.')
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def tip(self, ctx, target: discord.User, amount: str):
        try: value = parse_credits(amount)
        except ValueError as exc: return await ctx.reply(embed=embed('Tip not sent',str(exc),state='error'),mention_author=False)
        if target.id == ctx.author.id or target.bot:
            return await ctx.reply(embed=embed('Tip not sent','Choose another human user; self tips and bot tips are disabled.',state='error'),mention_author=False)
        if value > self.bot.settings.max_payout:
            return await ctx.reply(embed=embed('Tip not sent',f'Tip limit is {money(self.bot.settings.max_payout)}.',state='error'),mention_author=False)
        try: await self.bot.db.transfer(ctx.author.id,target.id,value,f'tip:{uuid.uuid4().hex}')
        except ValueError: return await ctx.reply(embed=embed('Tip not sent','Insufficient balance or transfer rejected. Your balance was not changed.',state='error'),mention_author=False)
        await ctx.reply(embed=embed('Tip sent',f'**{money(value)}** was transferred to {target.mention}.',state='success'),mention_author=False)

    @commands.command(name='add',help='Add audited VC. Owner/admin only. Example: `.add @user 100`.')
    async def add(self, ctx, target: discord.User, amount: str):
        if not self._admin(ctx): return await ctx.reply(embed=embed('Access denied','Only configured owners/admins or server Administrators may create credits.',state='error'),mention_author=False)
        if target.bot:return await ctx.reply(embed=embed('Credit rejected','Credit adjustments cannot target bot accounts.',state='error'),mention_author=False)
        try: value=parse_credits(amount)
        except ValueError as exc: return await ctx.reply(embed=embed('Credit rejected',str(exc),state='error'),mention_author=False)
        if value>self.bot.settings.max_payout: return await ctx.reply(embed=embed('Credit rejected',f'Maximum adjustment is {money(self.bot.settings.max_payout)}.',state='error'),mention_author=False)
        if ctx.guild:
            try:
                dm=getattr(ctx.author,'dm_channel',None) or await ctx.author.create_dm()
                probe=await dm.send(embed=embed('Private admin check','Preparing your audited adjustment response.',state='info'));await probe.delete()
            except discord.Forbidden:
                return await ctx.reply(embed=embed('Enable direct messages','No credit was added. Enable DMs before using `.add`.',state='error'),mention_author=False)
        try: bal=await self.bot.db.change_balance(target.id,value,'admin_adjustment',f'prefix-add:{uuid.uuid4().hex}',f'by {ctx.author.id}: .add command')
        except ValueError as exc: return await ctx.reply(embed=embed('Credit rejected',str(exc),state='error'),mention_author=False)
        await self.bot.db.audit_admin(ctx.author.id,'wallet_adjustment',f'target={target.id},amount={value},via=prefix')
        result=embed('Credit adjustment recorded',f'Added **{money(value)}** to {target.mention}.\nNew balance: **{money(bal)}**\n\nThe adjustment is recorded in the admin and wallet ledgers.',state='success')
        await private_reply(ctx,embed_obj=result)

    def _admin(self,ctx):
        if ctx.author.id in self.bot.settings.owners or ctx.author.id in self.bot.settings.admins:return True
        return bool(ctx.guild and ctx.author.guild_permissions.administrator)

    @commands.command(name='home',help='Open your private player dashboard with wallet, rewards, activity, games and safety controls.')
    async def home(self,ctx):
        view=HomeView(self,ctx.author.id)
        view.message=await private_reply(ctx,embed_obj=await home_embed(self.bot,ctx.author),view=view)

    @commands.command(name='games',help='Open the game directory.')
    async def games(self,ctx):
        game_ids={'mines':'mines','blackjack':'blackjack','dragon-tower':'dragon_tower','crash':'crash','limbo':'limbo','limo':'limo','dice':'dice','chicken-road':'chicken-road','pump':'pump'}
        available=[]
        if not self.bot.settings.maintenance:
            for name,game_id in game_ids.items():
                if (await self.bot.db.get_config('game_enabled:'+game_id,'true')).lower()=='true':available.append(name)
        e=embed(f'{resolve_emoji(self.bot,"outcome")} The game room','Select an available game for its syntax. Each launch uses the existing fairness and wager controls.' if available else 'Games are temporarily paused or disabled. Wallet and safety commands remain available.',state='info' if available else 'pending')
        for title,names in (('Table games',('mines','blackjack','dragon-tower')),('Arcade games',('crash','limbo','limo','dice')),('Live rounds',('chicken-road','pump'))):
            shown=[GAME_META[x][0] for x in names if x in available]
            if shown:e.add_field(name=title,value=' · '.join(shown),inline=False)
        banner=asset_file('games')
        file=asset_file('games')
        if file:e.set_image(url='attachment://games.png')
        view=GamesView(ctx.author.id,available,getattr(ctx,'prefix',getattr(self.bot,'active_prefix','.')))
        view.message=await ctx.reply(embed=e,file=file,view=view,mention_author=False)

    @commands.command(name='help',help='Show the automatically discovered prefix commands and examples.')
    async def help_menu(self,ctx):
        pfx=getattr(ctx,'prefix',getattr(self.bot,'active_prefix','.'))
        def category(name):
            if name in GAME_META:return 'Games'
            if name in {'bal','tip','transactions','profile','daily','leaderboard','limits','home'}:return 'Wallet'
            if name in {'depo','depoamount','deposit','deposit-status','deposit-history'}:return 'Deposits'
            if name.startswith('admin-') or name=='add':return 'Administration'
            if name in {'play-limit','self-exclude','play-status'}:return 'Responsible play'
            return 'Guide and fairness'
        groups={key:[] for key in ('Wallet','Games','Deposits','Responsible play','Administration','Guide and fairness')}
        for command in sorted(ctx.bot.commands,key=lambda c:c.name):
            if command.hidden:continue
            cat=category(command.name)
            aliases=f" · aliases: {', '.join(pfx+a for a in command.aliases)}" if command.aliases else ''
            if command.name in {'admin-rate','admin-log-channel','admin-withdrawals'}: access='Owner only'
            elif command.name=='add': access='Configured owner/admin or server Administrator'
            elif cat=='Administration': access='Owner/admin or server Administrator'
            else: access='Player'
            syntax=pfx+command.name+((' '+command.signature) if command.signature else '')
            desc=(command.help or command.brief or 'Available command.')[:100]
            desc=re.sub(r'(?<!\w)\.([A-Za-z][A-Za-z0-9-]*)',lambda m:pfx+m.group(1),desc)
            groups[cat].append(f'`{syntax}` — {desc}{aliases} · {access}')
        categories={}
        for title,lines in groups.items():
            if not lines:continue
            e=embed(f'{resolve_emoji(self.bot,"info")} Help · {title}',f'Prefix is `{pfx}`. Amounts use **{self.bot.settings.currency_symbol} virtual credits**; `$` is accepted as syntax only, never as USD conversion.')
            chunks=[];current=''
            for line in lines:
                if current and len(current)+len(line)+1>950: chunks.append(current);current=''
                current=(current+'\n' if current else '')+line
            if current:chunks.append(current)
            for index,chunk in enumerate(chunks[:24],1): e.add_field(name=f'Commands · {index}/{len(chunks)}',value=chunk,inline=False)
            p=pfx
            examples={'Wallet':f'`{p}home` · `{p}bal` · `{p}daily` · `{p}leaderboard` · `{p}limits`','Games':f'`{p}mines 25 3 16` · `{p}dice 25 over 65`','Deposits':f'`{p}depo` · `{p}depoamount ltc 0.05`','Administration':f'`{p}admin-dashboard` · `{p}add @user 100`','Responsible play':f'`{p}play-limit 500` · `{p}self-exclude 7`','Guide and fairness':f'`{p}games` · `{p}fairness`'}
            e.add_field(name='Example',value=examples.get(title,'Use the full command shown above.'),inline=False)
            categories[title]=e
        if not categories:return await ctx.reply(embed=embed('Help unavailable','No commands are currently registered.',state='error'),mention_author=False)
        first=next(iter(categories.values()))
        view=HelpView(ctx.author.id,categories)
        view.message=await ctx.reply(embed=first,view=view,mention_author=False)

    @commands.command(name='depo')
    @commands.cooldown(2, 15, commands.BucketType.user)
    async def depo(self, ctx):
        try:
            dm=ctx.author.dm_channel or await ctx.author.create_dm()
            banner=asset_file('wallet')
            menu=embed('Private deposit menu','Select a supported coin and network. New invoices require credentials, fresh sourced rates, and the live verification review flag.',state='pending')
            if banner:menu.set_image(url='attachment://wallet.png')
            view=DepositMenu(self,ctx.author.id)
            view.message=await dm.send(embed=menu,file=banner,view=view)
            await ctx.reply(embed=embed('Check your DMs','I sent your private deposit menu.'),mention_author=False)
        except discord.Forbidden:
            await ctx.reply(embed=embed('Could not send a DM',f'Enable direct messages from server members, then try `{self.bot.active_prefix}depo` again. No invoice was created.'),mention_author=False)

    @commands.command(name='depoamount')
    async def depoamount(self, ctx, currency: str, amount: str):
        if not (self.bot.settings.deposits_enabled and getattr(self.bot.settings,'deposits_live_verified',False) and self.bot.payments and getattr(self.bot.payments,'live_enabled',False)):return await ctx.reply(embed=embed('Deposits disabled','New invoices are disabled by default; no address was generated.',state='pending'),mention_author=False)
        if self.bot.settings.maintenance:return await ctx.reply(embed=embed('Deposits paused','Maintenance mode is active. No invoice was created.',state='pending'),mention_author=False)
        if not isinstance(ctx.channel,discord.DMChannel): return await ctx.reply(embed=embed('Use your deposit DM',f'Run `{self.bot.active_prefix}depo` first, then use this command in the private bot DM.'),mention_author=False)
        if currency not in SUPPORTED or not self.bot.payments: return await ctx.reply(embed=embed('Deposits unavailable','That asset is unsupported or Apirone is not configured. No address was generated.'),mention_author=False)
        try:
            coin=Decimal(amount)
            if not coin.is_finite() or coin<=0: raise ValueError()
            inv=await self.bot.payments.create(ctx.author.id,currency,coin,self.bot.settings.invoice_lifetime)
        except (InvalidOperation,ValueError): return await ctx.reply(embed=embed('Invalid deposit amount','Enter a positive coin amount that meets configured limits.'),mention_author=False)
        except Exception as exc:
            self.bot.logger.error('Apirone prefix invoice creation failed (exception_type=%s)', type(exc).__name__)
            return await ctx.reply(embed=embed('Invoice unavailable','The provider could not create an invoice. No funds were credited.'),mention_author=False)
        from cogs.deposits import deposit_card,DepositAddressView
        from services.emojis import resolve_emoji
        asset,network,_=SUPPORTED[currency]
        e=deposit_card(self.bot,f'{resolve_emoji(self.bot, {"ltc":"ltc","usdt@bnb":"usdt_bep20","usdt@eth":"usdt_erc20"}[currency])} {asset} deposit invoice','Use the exact asset, network, and amount below. Payment is checked with Apirone.','pending',currency,str(inv['amount_coin']),inv['address'],inv['invoice'],inv.get('expire'),inv.get('status','created'))
        qr=qr_file(inv['address']);e.set_thumbnail(url='attachment://deposit-qr.png')
        view=DepositAddressView(self.bot,ctx.author.id,inv['address'],inv['invoice'],currency,str(inv['amount_coin']),inv.get('expire'))
        view.message=await ctx.reply(embed=e,file=qr,view=view,mention_author=False)
        if getattr(self.bot,'event_logger',None):self.bot.event_logger.emit('deposit','Deposit invoice created',user_id=ctx.author.id,invoice=inv['invoice'],asset=currency,amount=str(inv['amount_coin']),status=inv['status'],reference='invoice:'+inv['invoice'])


    @commands.command(name='transactions',help='View recent wallet ledger entries with pagination.')
    async def transactions(self,ctx):
        rows=await self.bot.db.history(ctx.author.id,50)
        def render(r):
            amount=int(r['amount']); sign='+' if amount>0 else '−'
            created=str(r['created_at'])[:16]
            return f"`{created}` · **{r['kind'].replace('_',' ').title()}** · {sign}{money(abs(amount))} · balance {money(r['balance_after'])}"
        pages=history_pages('Wallet activity',rows,ctx.author.id,render)
        view=EmbedPager(ctx.author.id,pages)
        view.message=await private_reply(ctx,embed_obj=pages[0],view=view)

    @commands.command(name='deposit-history',help='View private deposit invoices with pagination.')
    async def deposit_history(self,ctx):
        rows=await self.bot.db.deposit_history(ctx.author.id,20)
        def render(r):
            return f"**{r['currency']}** · `{r['status']}` · invoice `{r['invoice_id']}`" + (f" · expires {r['expires_at']}" if r['expires_at'] else '')
        pages=history_pages('Deposit history',rows,ctx.author.id,render)
        try:
            dm=ctx.author.dm_channel or await ctx.author.create_dm()
            view=EmbedPager(ctx.author.id,pages)
            view.message=await dm.send(embed=pages[0],view=view)
            await ctx.reply(embed=embed('Private history sent','Check your DMs for deposit records.',state='info'),mention_author=False)
        except discord.Forbidden:
            await ctx.reply(embed=embed('Could not send a DM','Enable direct messages to view private deposit history.',state='error'),mention_author=False)

    @commands.command(name='deposit-status')
    async def deposit_status(self,ctx,invoice_id:str):
        row=await self.bot.db.deposit(invoice_id)
        if not row or row['discord_id']!=ctx.author.id: return await ctx.reply(embed=embed('Invoice not found','That invoice does not belong to your account.',state='error'),mention_author=False)
        if not self.bot.payments: return await ctx.reply(embed=embed('Verification unavailable','Apirone is not configured.'),mention_author=False)
        try: result=await self.bot.payments.reconcile(invoice_id)
        except Exception as exc:
            self.bot.logger.error('Prefix deposit verification failed (exception_type=%s)', type(exc).__name__)
            return await ctx.reply(embed=embed('Verification delayed','The provider could not verify this invoice. Balance unchanged.'),mention_author=False)
        title,msg,state=deposit_status(result)
        try:
            dm=ctx.author.dm_channel or await ctx.author.create_dm()
            await dm.send(embed=embed(title,msg,state=state))
            await ctx.reply(embed=embed('Private status sent','Check your DMs for invoice status.',state='info'),mention_author=False)
        except discord.Forbidden:
            await ctx.reply(embed=embed('Could not send a DM','Enable direct messages to view invoice status. No invoice details were posted here.',state='error'),mention_author=False)

    @commands.command(name='profile')
    async def profile(self,ctx):
        stats=await self.bot.db.player_game_stats(ctx.author.id)
        e=embed('Player profile',f'{ctx.author.mention} · Account created <t:{int(ctx.author.created_at.timestamp())}:D>')
        e.set_thumbnail(url=ctx.author.display_avatar.url)
        e.add_field(name='Wallet balance',value=f'**{money(await self.bot.db.balance(ctx.author.id))}**',inline=True)
        today=await self.bot.db.daily_wagered(ctx.author.id)
        e.add_field(name='Wagered today',value=f'{money(today)} / {money(self.bot.settings.daily_bet_limit)}',inline=True)
        e.add_field(name='Settled games',value=f'{stats["rounds"]} rounds · {stats["wins"]} wins · net {money(int(stats["net"]))}',inline=False)
        e.add_field(name='Fairness',value=f'Server generated outcomes · seed commitments available with `{self.bot.active_prefix}fairness`',inline=False)
        await private_reply(ctx,embed_obj=e)

async def setup(bot): await bot.add_cog(PrefixCommands(bot))

def history_pages(title,rows,owner,formatter):
    chunk=5; pages=[]
    for start in range(0,max(1,len(rows)),chunk):
        e=embed(title,'Private account history · newest first')
        text='\n'.join(formatter(row) for row in rows[start:start+chunk]) or 'No records yet.'
        e.add_field(name='Entries',value=text[:1024],inline=False)
        e.set_footer(text=f'{settings.casino_name}  •  Page {len(pages)+1}/{max(1,(len(rows)+chunk-1)//chunk)}  •  Private account history')
        pages.append(e)
    return pages
