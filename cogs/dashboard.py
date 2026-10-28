"""Permission-checked, persistent casino administration dashboard."""
from datetime import datetime, timezone
import re, time, logging
from decimal import Decimal
import discord
from discord import app_commands
from discord.ext import commands
from config import settings
from services.emojis import DEFAULT_EMOJIS, FALLBACKS, validate_emoji, resolve_emoji
from services.ui import embed, money
from services.apirone import SUPPORTED

ROUTES=('general','wins','loss','withdrawal','deposit','admin','fairness','error')
PREFIX_RE=re.compile(r'^[^\s@`]{1,5}$')

async def send_view(it,card,view):
    await it.response.send_message(embed=card,view=view,ephemeral=True)
    try:view.message=await it.original_response()
    except (AttributeError,discord.HTTPException):pass
    return view


class SafeDashboardView(discord.ui.View):
    async def on_timeout(self):
        for child in self.children:child.disabled=True
        message=getattr(self,'message',None)
        if message:
            try:await message.edit(view=self)
            except discord.HTTPException:pass
    async def on_error(self,interaction,error,item):
        logging.getLogger('casino.dashboard').error('Dashboard component failed type=%s',type(error).__name__)
        card=embed('Action unavailable','The dashboard could not complete this action. Review the current setting before retrying.',state='error')
        try:
            if interaction.response.is_done():await interaction.followup.send(embed=card,ephemeral=True)
            else:await interaction.response.send_message(embed=card,ephemeral=True)
        except discord.HTTPException:pass


async def allowed(bot, user, guild, channel):
    if user.id not in bot.settings.owners and user.id not in bot.settings.admins:
        if not guild or not getattr(getattr(user,'guild_permissions',None),'administrator',False): return False
    if guild and bot.settings.admin_channel_id and getattr(channel,'id',None)!=bot.settings.admin_channel_id: return False
    return True

async def deny(it):
    try: await it.response.send_message(embed=embed('Access denied','This control is restricted to configured casino administrators.',state='error'),ephemeral=True)
    except discord.HTTPException: pass

class DashboardView(SafeDashboardView):
    def __init__(self,bot,owner): super().__init__(timeout=300); self.bot=bot; self.owner=owner
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): await deny(it); return False
        return True
    @discord.ui.button(label='Overview',style=discord.ButtonStyle.secondary,emoji='📊')
    async def overview(self,it,b): await it.response.edit_message(embed=overview_embed(self.bot),view=self)
    @discord.ui.button(label='Prefix',style=discord.ButtonStyle.primary,emoji='⌨️')
    async def prefix(self,it,b): await it.response.send_modal(PrefixModal(self.bot,self.owner))
    @discord.ui.button(label='Maintenance',style=discord.ButtonStyle.danger,emoji='🛠️')
    async def maintenance(self,it,b): await send_view(it,maintenance_embed(self.bot),MaintenanceView(self.bot,self.owner))
    @discord.ui.button(label='Emoji mappings',style=discord.ButtonStyle.secondary,emoji='✨')
    async def emojis(self,it,b):
        view=EmojiView(self.bot,self.owner); await send_view(it,emoji_list_embed(self.bot),view)
    @discord.ui.button(label='Log channels',style=discord.ButtonStyle.secondary,emoji='🧾',row=1)
    async def channels(self,it,b):
        view=ChannelRouteView(self.bot,self.owner); await send_view(it,routes_embed(self.bot),view)
    @discord.ui.button(label='Deposit readiness',style=discord.ButtonStyle.success,emoji='💳',row=1)
    async def deposits(self,it,b):
        view=DepositControlView(self.bot,self.owner); await send_view(it,deposit_readiness(self.bot),view)
    @discord.ui.button(label='Branding',style=discord.ButtonStyle.secondary,emoji='🎨',row=1)
    async def branding(self,it,b): await it.response.send_modal(BrandingModal(self.bot,self.owner))
    @discord.ui.button(label='Economy & games',style=discord.ButtonStyle.secondary,emoji='🪙',row=2)
    async def economy(self,it,b): await send_view(it,economy_embed(self.bot),EconomyView(self.bot,self.owner))
    async def on_timeout(self):
        for child in self.children: child.disabled=True


def overview_embed(bot):
    uptime=max(0,int(time.time()-getattr(bot,'started_at',time.time())))
    return embed('Casino control dashboard',f"**Service:** {'Maintenance' if bot.settings.maintenance else 'Online'}\n**Uptime:** {uptime//3600}h {(uptime%3600)//60}m\n**Active prefix:** `{bot.active_prefix}`\n**Extra aliases:** {', '.join(f'`{x}`' for x in bot.prefix_aliases) or 'None'}\n**Casino:** {bot.settings.casino_name}\n**Withdrawals:** Disabled (no secure payout provider)\n**Deposits:** {'Enabled' if bot.settings.deposits_enabled and bot.settings.deposits_live_verified else 'Disabled'}",state='info')

def maintenance_embed(bot):
    return embed('Maintenance controls',f"Current status: **{'ON' if bot.settings.maintenance else 'OFF'}**\nNotice: {bot.maintenance_notice}\nNew wagers, tips, and deposit invoices are blocked while maintenance is active. Existing game rounds may settle normally so users are not stranded.",state='pending' if bot.settings.maintenance else 'info')

class PrefixModal(discord.ui.Modal,title='Preview command prefix'):
    value=discord.ui.TextInput(label='New prefix',placeholder='! or ?',min_length=1,max_length=5,required=True)
    def __init__(self,bot,owner): super().__init__(); self.bot=bot; self.owner=owner
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): return await deny(it)
        value=str(self.value).strip()
        if not PREFIX_RE.fullmatch(value): return await it.response.send_message(embed=embed('Invalid prefix','Use 1–5 non-space characters. Mentions and backticks are not allowed.',state='error'),ephemeral=True)
        view=PrefixConfirmView(self.bot,self.owner,value)
        await send_view(it,embed('Prefix preview',f"Commands will use `{value}`. Current prefix: `{self.bot.active_prefix}`. The old prefix will stop working unless explicitly configured as an alias."),view)

class PrefixConfirmView(SafeDashboardView):
    def __init__(self,bot,owner,value): super().__init__(timeout=90); self.bot=bot; self.owner=owner; self.value=value
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): await deny(it); return False
        return True
    @discord.ui.button(label='Apply prefix',style=discord.ButtonStyle.success)
    async def apply(self,it,b):
        await self.bot.db.set_config('command_prefix',self.value,it.user.id); self.bot.active_prefix=self.value
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Command prefix changed',admin_id=it.user.id,prefix=self.value,reference=f'prefix:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Prefix updated',f"Active prefix: `{self.value}`. Extra aliases: {', '.join(self.bot.prefix_aliases) or 'none'}.",state='success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Prefix unchanged','The active prefix was not changed.'),view=self)

class MaintenanceConfirmView(SafeDashboardView):
    def __init__(self,bot,owner,enabled): super().__init__(timeout=90); self.bot=bot; self.owner=owner; self.enabled=bool(enabled)
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): await deny(it); return False
        return True
    @discord.ui.button(label='Confirm maintenance change',style=discord.ButtonStyle.danger)
    async def confirm(self,it,b):
        value=str(self.enabled).lower(); await self.bot.db.set_config('maintenance',value,it.user.id)
        self.bot.settings.maintenance=self.enabled; self.bot.db.maintenance_mode=self.enabled
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Maintenance changed',admin_id=it.user.id,enabled=self.enabled,reference=f'maintenance:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Maintenance updated',f"Maintenance is now **{'ON' if self.enabled else 'OFF'}**. The change is in the admin audit ledger.",state='pending' if self.enabled else 'success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Maintenance status was not changed.'),view=self)

class MaintenanceView(SafeDashboardView):
    def __init__(self,bot,owner): super().__init__(timeout=180); self.bot=bot; self.owner=owner
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): await deny(it); return False
        return True
    @discord.ui.button(label='Enable',style=discord.ButtonStyle.danger)
    async def enable(self,it,b): await send_view(it,embed('Confirm maintenance',f'New wagers and money-affecting actions will pause. Existing rounds can settle. Notice: {self.bot.maintenance_notice}'),MaintenanceConfirmView(self.bot,self.owner,True))
    @discord.ui.button(label='Disable',style=discord.ButtonStyle.success)
    async def disable(self,it,b): await send_view(it,embed('Confirm resume','New wagers, tips, and deposits will follow their configured safety gates.'),MaintenanceConfirmView(self.bot,self.owner,False))
    @discord.ui.button(label='Set notice',style=discord.ButtonStyle.secondary)
    async def notice(self,it,b): await it.response.send_modal(MaintenanceNoticeModal(self.bot,self.owner))

class MaintenanceNoticeModal(discord.ui.Modal,title='Set maintenance notice'):
    notice=discord.ui.TextInput(label='Public maintenance notice',style=discord.TextStyle.paragraph,max_length=500,required=True)
    def __init__(self,bot,owner): super().__init__(); self.bot=bot; self.owner=owner
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): return await deny(it)
        value=str(self.notice).strip()
        if not value: return await it.response.send_message(embed=embed('Invalid notice','Enter a short notice.'),ephemeral=True)
        await send_view(it,embed('Maintenance notice preview',value),NoticeConfirmView(self.bot,self.owner,value))

class NoticeConfirmView(SafeDashboardView):
    def __init__(self,bot,owner,value): super().__init__(timeout=90); self.bot=bot; self.owner=owner; self.value=value
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): await deny(it); return False
        return True
    @discord.ui.button(label='Save notice',style=discord.ButtonStyle.success)
    async def save(self,it,b):
        await self.bot.db.set_config('maintenance_notice',self.value,it.user.id); self.bot.maintenance_notice=self.value
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Notice saved','The maintenance notice was updated.'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','The notice was not changed.'),view=self)

class EmojiView(SafeDashboardView):
    def __init__(self,bot,owner):
        super().__init__(timeout=300); self.bot=bot; self.owner=owner; self.key=None
        self.add_item(EmojiKeySelect())
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel): await deny(it); return False
        return True
    @discord.ui.button(label='Edit / preview',style=discord.ButtonStyle.primary)
    async def edit(self,it,b):
        if not self.key:return await it.response.send_message(embed=embed('Select an emoji key','Choose a mapping first.'),ephemeral=True)
        await it.response.send_modal(EmojiModal(self.bot,self.owner,self.key))
    @discord.ui.button(label='Reset selected',style=discord.ButtonStyle.secondary)
    async def reset(self,it,b):
        if not self.key:return await it.response.send_message(embed=embed('Select an emoji key','Choose a mapping first.'),ephemeral=True)
        await send_view(it,embed('Reset preview',f"Restore **{self.key}** to its supplied default {DEFAULT_EMOJIS[self.key]}?"),EmojiSaveView(self.bot,self.owner,self.key,DEFAULT_EMOJIS[self.key],'reset'))
    @discord.ui.button(label='Remove override',style=discord.ButtonStyle.secondary)
    async def remove(self,it,b):
        if not self.key:return await it.response.send_message(embed=embed('Select an emoji key','Choose a mapping first.'),ephemeral=True)
        await send_view(it,embed('Fallback preview',f"Remove the configured override for **{self.key}**? Messages will use a Unicode fallback when the supplied default is unavailable."),EmojiSaveView(self.bot,self.owner,self.key,'','remove'))
    @discord.ui.button(label='Restore all defaults',style=discord.ButtonStyle.danger,row=1)
    async def restore(self,it,b):
        await send_view(it,embed('Restore all emoji defaults','All 14 mappings will be restored. Confirm to save this change.'),EmojiSaveView(self.bot,self.owner,'*','*','restore'))

class EmojiKeySelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=k.replace('_',' ').title(),value=k,description=f'Current: {str(DEFAULT_EMOJIS[k])[:90]}') for k in DEFAULT_EMOJIS]
        super().__init__(placeholder='Choose emoji mapping',min_values=1,max_values=1,options=options)
    async def callback(self,it):
        self.view.key=self.values[0]
        await it.response.edit_message(embed=emoji_list_embed(self.view.bot,selected=self.view.key),view=self.view)

class EmojiModal(discord.ui.Modal,title='Preview emoji mapping'):
    value=discord.ui.TextInput(label='Emoji (Discord custom or Unicode)',placeholder='✅ or <:name:12345678901234567>',min_length=1,max_length=64)
    def __init__(self,bot,owner,key): super().__init__(); self.bot=bot; self.owner=owner; self.key=key
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        value=str(self.value).strip()
        if not validate_emoji(value):return await it.response.send_message(embed=embed('Invalid emoji','Use one emoji or a Discord custom emoji in `<:name:id>` / `<a:name:id>` format.'),ephemeral=True)
        old=self.bot.emoji_map.get(self.key); self.bot.emoji_map[self.key]=value
        preview=resolve_emoji(self.bot,self.key)
        if old is None:self.bot.emoji_map.pop(self.key,None)
        else:self.bot.emoji_map[self.key]=old
        await send_view(it,embed('Emoji preview',f"Key: **{self.key}**\nPreview: {preview}\nConfigured value: `{value}`"),EmojiSaveView(self.bot,self.owner,self.key,value,'set'))

class EmojiSaveView(SafeDashboardView):
    def __init__(self,bot,owner,key,value,action): super().__init__(timeout=90); self.bot=bot; self.owner=owner; self.key=key; self.value=value; self.action=action
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Save mapping',style=discord.ButtonStyle.success)
    async def save(self,it,b):
        if self.action=='restore':
            for key,value in DEFAULT_EMOJIS.items(): await self.bot.db.set_config('emoji:'+key,value,it.user.id)
            self.bot.emoji_map=DEFAULT_EMOJIS.copy()
        elif self.action=='reset':
            await self.bot.db.set_config('emoji:'+self.key,DEFAULT_EMOJIS[self.key],it.user.id); self.bot.emoji_map[self.key]=DEFAULT_EMOJIS[self.key]
        elif self.action=='remove':
            await self.bot.db.set_config('emoji:'+self.key,'',it.user.id); self.bot.emoji_map[self.key]=''
        else:
            await self.bot.db.set_config('emoji:'+self.key,self.value,it.user.id); self.bot.emoji_map[self.key]=self.value
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Emoji mapping changed',admin_id=it.user.id,key=self.key,action=self.action,reference=f'emoji:{self.key}:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Emoji mapping saved','Configuration is stored persistently. Unavailable server emojis automatically render as Unicode fallbacks.',state='success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Emoji configuration was not changed.'),view=self)

def emoji_list_embed(bot,selected=None):
    rows=[f"**{key}** · {resolve_emoji(bot,key)} · `{bot.emoji_map.get(key,DEFAULT_EMOJIS[key])}`" for key in DEFAULT_EMOJIS]
    return embed('Emoji configuration','Configured Discord emoji mappings. Missing or inaccessible custom emoji use Unicode fallbacks.'+(f'\nSelected: **{selected}**' if selected else '')+'\n\n'+'\n'.join(rows))

class ChannelRouteView(SafeDashboardView):
    def __init__(self,bot,owner):
        super().__init__(timeout=300); self.bot=bot; self.owner=owner; self.category=ROUTES[0]; self.selected=None
        self.add_item(RouteSelect()); self.add_item(AdminChannelSelect())
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Save route',style=discord.ButtonStyle.success,row=2)
    async def save(self,it,b):
        channel=self.selected
        if not channel:return await it.response.send_message(embed=embed('Choose a channel','Select a log category and destination first.'),ephemeral=True)
        me=it.guild.me if it.guild else None; perms=channel.permissions_for(me) if me else None
        if not perms or not perms.view_channel or not perms.send_messages or not perms.embed_links:
            return await it.response.send_message(embed=embed('Channel unavailable','The bot needs View Channel, Send Messages, and Embed Links in the destination.',state='error'),ephemeral=True)
        await self.bot.db.set_config('log_channel:'+self.category,str(channel.id),it.user.id)
        self.bot.settings.log_channels[self.category]=channel.id; self.bot.event_logger.channels=self.bot.settings.log_channels
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Log route changed',admin_id=it.user.id,category=self.category,channel_id=channel.id,reference=f'route:{self.category}:{it.id}')
        await it.response.send_message(embed=embed('Log route saved',f'{self.category.title()} events route to {channel.mention}. Configuration is audited.',state='success'),ephemeral=True)
    @discord.ui.button(label='Test embed',style=discord.ButtonStyle.primary,row=2)
    async def test(self,it,b):
        channel=self.selected
        if not channel:return await it.response.send_message(embed=embed('Choose a channel','Select a destination first.'),ephemeral=True)
        perms=channel.permissions_for(it.guild.me) if it.guild else None
        if not perms or not perms.send_messages or not perms.embed_links:return await it.response.send_message(embed=embed('Channel unavailable','The bot cannot send embeds in that channel.',state='error'),ephemeral=True)
        await channel.send(embed=embed('Casino log test',f'Route: **{self.category}** · Requested by {it.user.mention} · <t:{int(time.time())}:F>'),allowed_mentions=discord.AllowedMentions.none())
        await it.response.send_message(embed=embed('Test sent',f'A test embed was sent to {channel.mention}.',state='success'),ephemeral=True)

class RouteSelect(discord.ui.Select):
    def __init__(self):super().__init__(placeholder='Choose log category',min_values=1,max_values=1,options=[discord.SelectOption(label=x.replace('_',' ').title(),value=x) for x in ROUTES])
    async def callback(self,it):self.view.category=self.values[0];await it.response.edit_message(embed=routes_embed(self.view.bot,selected=self.values[0]),view=self.view)
class AdminChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):super().__init__(placeholder='Select a destination channel',min_values=1,max_values=1,channel_types=[discord.ChannelType.text,discord.ChannelType.news],row=1)
    async def callback(self,it):self.view.selected=self.values[0];await it.response.send_message(embed=embed('Channel selected',f'{self.values[0].mention} selected for **{self.view.category}**. Validate permissions, then save or test.'),ephemeral=True)
def routes_embed(bot,selected=None):
    rows=[]
    for key in ROUTES:
        cid=bot.settings.log_channels.get(key,0); channel=bot.get_channel(cid) if cid else None
        rows.append(f"**{key.title()}** · {channel.mention if channel else 'Not configured'}")
    return embed('Log channel routes','Select a category and text channel. The bot validates permissions before saving. Sensitive payment credentials and private addresses are never included.'+(f'\nSelected: **{selected}**' if selected else '')+'\n\n'+'\n'.join(rows))

class DepositControlView(SafeDashboardView):
    def __init__(self,bot,owner):super().__init__(timeout=180);self.bot=bot;self.owner=owner
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Disable deposits',style=discord.ButtonStyle.danger)
    async def disable(self,it,b):
        await self.bot.db.set_config('deposits_enabled','false',it.user.id)
        self.bot.settings.deposits_enabled=False
        if self.bot.payments:self.bot.payments.live_enabled=False
        await it.response.edit_message(embed=deposit_readiness(self.bot),view=self)
    @discord.ui.button(label='Enable deposits',style=discord.ButtonStyle.success)
    async def enable(self,it,b):
        if not self.bot.settings.deposits_live_verified:
            return await it.response.send_message(embed=embed('Live verification required','Set `DEPOSITS_LIVE_VERIFIED=true` only after you have reviewed credentials, all supported rates, and safely verified Apirone payment behavior. This build has not performed live verification.'),ephemeral=True)
        if not self.bot.payments:return await it.response.send_message(embed=embed('Provider unavailable','Apirone credentials are not configured.'),ephemeral=True)
        if self.bot.settings.maintenance:return await it.response.send_message(embed=embed('Maintenance active','Deposits cannot be enabled during maintenance.'),ephemeral=True)
        issues=[f'{k}: {self.bot.payments.rate_readiness(k)}' for k in SUPPORTED if self.bot.payments.rate_readiness(k)]
        if issues:return await it.response.send_message(embed=embed('Rates not ready','\n'.join(issues),state='error'),ephemeral=True)
        view=DepositEnableConfirm(self.bot,self.owner)
        await send_view(it,embed('Confirm live deposits','This enables real Apirone invoice creation. Confirm only after reviewing provider verification, rates, and crediting rules.'),view)
    @discord.ui.button(label='Set deposit limits',style=discord.ButtonStyle.secondary,row=1)
    async def limits(self,it,b):await it.response.send_modal(DepositLimitsModal(self.bot,self.owner))

class DepositLimitsModal(discord.ui.Modal,title='Preview deposit amount limits'):
    minimum=discord.ui.TextInput(label='Minimum coin amount',min_length=1,max_length=40)
    maximum=discord.ui.TextInput(label='Maximum coin amount',min_length=1,max_length=40)
    def __init__(self,bot,owner):super().__init__();self.bot=bot;self.owner=owner;self.minimum.default=str(bot.settings.min_deposit);self.maximum.default=str(bot.settings.max_deposit)
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        from decimal import Decimal,InvalidOperation
        try:minimum=Decimal(str(self.minimum).strip());maximum=Decimal(str(self.maximum).strip())
        except InvalidOperation:return await it.response.send_message(embed=embed('Invalid deposit limits','Enter finite positive decimal amounts.',state='error'),ephemeral=True)
        if not minimum.is_finite() or not maximum.is_finite() or minimum<=0 or maximum<minimum:return await it.response.send_message(embed=embed('Invalid deposit limits','The maximum must be at least the positive minimum.',state='error'),ephemeral=True)
        await send_view(it,embed('Deposit limits preview',f'Minimum: **{minimum} coin units**\nMaximum: **{maximum} coin units**. Applied to each supported asset; no exchange rate is implied.'),DepositLimitsConfirm(self.bot,self.owner,minimum,maximum))

class DepositLimitsConfirm(SafeDashboardView):
    def __init__(self,bot,owner,minimum,maximum):super().__init__(timeout=90);self.bot=bot;self.owner=owner;self.minimum=minimum;self.maximum=maximum
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Save deposit limits',style=discord.ButtonStyle.danger)
    async def save(self,it,b):
        await self.bot.db.set_config('deposit_limits',f'{self.minimum},{self.maximum}',it.user.id)
        self.bot.settings.min_deposit=self.minimum;self.bot.settings.max_deposit=self.maximum
        if self.bot.payments:self.bot.payments.minimum=self.minimum;self.bot.payments.maximum=self.maximum
        await self.bot.db.audit_admin(it.user.id,'deposit_limits',f'min={self.minimum},max={self.maximum}')
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Deposit limits changed',admin_id=it.user.id,minimum=str(self.minimum),maximum=str(self.maximum),reference=f'deposit-limits:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Deposit limits saved',f'Minimum: {self.minimum} · Maximum: {self.maximum}. New invoice requests will use these limits.',state='success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Deposit limits were not changed.'),view=self)

class DepositEnableConfirm(SafeDashboardView):
    def __init__(self,bot,owner):super().__init__(timeout=90);self.bot=bot;self.owner=owner
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Enable real deposits',style=discord.ButtonStyle.danger)
    async def confirm(self,it,b):
        if not self.bot.settings.deposits_live_verified or self.bot.settings.maintenance:return await it.response.send_message(embed=embed('Enable check failed','Review flag is absent or maintenance is active.'),ephemeral=True)
        await self.bot.db.set_config('deposits_enabled','true',it.user.id)
        self.bot.settings.deposits_enabled=True; self.bot.payments.live_enabled=True
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Live deposit invoices enabled',admin_id=it.user.id,reference=f'deposits-enabled:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Deposits enabled','Real invoice creation is enabled. Provider requests remain subject to all verification/rate guards.',state='success'),view=self)

class EconomyView(SafeDashboardView):
    def __init__(self,bot,owner):super().__init__(timeout=180);self.bot=bot;self.owner=owner
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Configure limits and daily reward',style=discord.ButtonStyle.primary)
    async def limits(self,it,b):await it.response.send_modal(EconomyModal(self.bot,self.owner))
    @discord.ui.button(label='Configure game availability',style=discord.ButtonStyle.secondary)
    async def games(self,it,b):await send_view(it,embed('Game availability','Select a game to review and change its availability.'),GameConfigView(self.bot,self.owner))
    @discord.ui.button(label='Currency label',style=discord.ButtonStyle.secondary)
    async def currency(self,it,b):await it.response.send_modal(CurrencyModal(self.bot,self.owner))


class CurrencyModal(discord.ui.Modal,title='Preview virtual-credit label'):
    value=discord.ui.TextInput(label='Currency label (letters/numbers)',min_length=1,max_length=10)
    def __init__(self,bot,owner):super().__init__();self.bot=bot;self.owner=owner;self.value.default=bot.settings.currency_symbol
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        value=str(self.value).strip()
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,9}',value):return await it.response.send_message(embed=embed('Invalid currency label','Use 1–10 letters, numbers, underscores, or hyphens, beginning with a letter.',state='error'),ephemeral=True)
        await send_view(it,embed('Currency label preview',f'Balance examples will use **{value}**.'),CurrencyConfirm(self.bot,self.owner,value))
class CurrencyConfirm(SafeDashboardView):
    def __init__(self,bot,owner,value):super().__init__(timeout=90);self.bot=bot;self.owner=owner;self.value=value
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Save currency label',style=discord.ButtonStyle.success)
    async def save(self,it,b):
        await self.bot.db.set_config('currency_symbol',self.value,it.user.id);self.bot.settings.currency_symbol=self.value
        await self.bot.db.audit_admin(it.user.id,'currency_label',self.value)
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Currency label changed',admin_id=it.user.id,label=self.value,reference=f'currency:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Currency label saved',f'New label: **{self.value}**',state='success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Currency label was not changed.'),view=self)

class EconomyModal(discord.ui.Modal,title='Preview economy settings'):
    min_bet=discord.ui.TextInput(label='Minimum wager (VC)',min_length=1,max_length=10)
    max_bet=discord.ui.TextInput(label='Maximum wager (VC, 0 = none)',min_length=1,max_length=10)
    daily_limit=discord.ui.TextInput(label='Casino daily wager cap (VC)',min_length=1,max_length=12)
    max_payout=discord.ui.TextInput(label='Maximum payout (VC)',min_length=1,max_length=12)
    reward=discord.ui.TextInput(label='Daily reward (VC, 0 = disabled)',min_length=1,max_length=12)
    def __init__(self,bot,owner):
        super().__init__();self.bot=bot;self.owner=owner
        self.min_bet.default=str(bot.settings.min_bet);self.max_bet.default=str(bot.settings.max_bet)
        self.daily_limit.default=str(bot.settings.daily_bet_limit);self.max_payout.default=str(bot.settings.max_payout);self.reward.default=str(bot.settings.daily_reward)
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        try:values=tuple(int(str(x).strip()) for x in (self.min_bet,self.max_bet,self.daily_limit,self.max_payout,self.reward))
        except ValueError:return await it.response.send_message(embed=embed('Invalid economy values','Enter whole numbers only.',state='error'),ephemeral=True)
        minimum,maximum,daily,payout,reward=values
        if minimum<1 or maximum<0 or daily<minimum or payout<minimum or (maximum and (maximum<minimum or daily<maximum or payout<maximum)) or reward<0 or reward>payout:
            return await it.response.send_message(embed=embed('Invalid economy limits','Require minimum ≤ configured maximum, daily cap, and payout cap. Daily reward must be between zero and the payout cap.',state='error'),ephemeral=True)
        view=EconomyConfirm(self.bot,self.owner,values)
        maximum_text=f'{maximum:,} VC' if maximum else 'none'
        text=(f'Minimum wager: **{minimum:,} VC**\nMaximum wager: **{maximum_text}**\n'
               f'Daily cap: **{daily:,} VC** · Payout cap: **{payout:,} VC**\nDaily reward: **{reward:,} VC**')
        await send_view(it,embed('Economy preview',text),view)

class EconomyConfirm(SafeDashboardView):
    def __init__(self,bot,owner,values):super().__init__(timeout=90);self.bot=bot;self.owner=owner;self.values=values
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Apply economy settings',style=discord.ButtonStyle.danger)
    async def apply(self,it,b):
        minimum,maximum,daily,payout,reward=self.values;s=self.bot.settings
        await self.bot.db.set_configs({'limits':f'{minimum},{maximum},{daily},{payout}','daily_reward':str(reward)},it.user.id,'economy_settings')
        s.min_bet=minimum;s.max_bet=maximum;s.daily_bet_limit=daily;s.max_payout=payout;s.daily_reward=reward
        self.bot.db.min_bet=minimum;self.bot.db.max_bet=maximum;self.bot.db.daily_bet_limit=daily;self.bot.db.max_payout=payout
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Economy settings changed',admin_id=it.user.id,min_bet=minimum,max_bet=maximum,daily_limit=daily,max_payout=payout,daily_reward=reward,reference=f'economy:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=economy_embed(self.bot),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Economy settings were not changed.'),view=self)

GAME_OPTIONS=('mines','blackjack','dragon_tower','crash','limbo','limo','dice','chicken-road','pump')
class GameConfigView(SafeDashboardView):
    def __init__(self,bot,owner):
        super().__init__(timeout=180);self.bot=bot;self.owner=owner;self.add_item(GameConfigSelect())
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
class GameConfigSelect(discord.ui.Select):
    def __init__(self):super().__init__(placeholder='Select a game',min_values=1,max_values=1,options=[discord.SelectOption(label=x.replace('_',' ').title(),value=x) for x in GAME_OPTIONS])
    async def callback(self,it):
        key='game_enabled:'+self.values[0];current=(await self.view.bot.db.get_config(key,'true')).lower()=='true'
        await send_view(it,embed('Game availability preview',f'**{self.values[0]}** is currently **{"enabled" if current else "disabled"}**. Confirm to {"disable" if current else "enable"} it for new rounds.'),GameToggleConfirm(self.view.bot,self.view.owner,self.values[0],not current))
class GameToggleConfirm(SafeDashboardView):
    def __init__(self,bot,owner,game,enabled):super().__init__(timeout=90);self.bot=bot;self.owner=owner;self.game=game;self.enabled=enabled
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Confirm game setting',style=discord.ButtonStyle.danger)
    async def confirm(self,it,b):
        await self.bot.db.set_config('game_enabled:'+self.game,str(self.enabled).lower(),it.user.id)
        if self.bot.event_logger:self.bot.event_logger.emit('admin','Game availability changed',admin_id=it.user.id,game=self.game,enabled=self.enabled,reference=f'game-toggle:{it.id}')
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Game setting saved',f'{self.game} is now {"enabled" if self.enabled else "disabled"} for new games.',state='success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Game availability was not changed.'),view=self)

def economy_embed(bot):
    s=bot.settings
    cap=f'{s.max_bet:,} VC' if s.max_bet else 'none'
    text=(f'Minimum bet: **{s.min_bet:,} VC** · Maximum bet: **{cap}**\n'
           f'Daily wager cap: **{s.daily_bet_limit:,} VC** · Maximum payout: **{s.max_payout:,} VC**\n'
           f'Daily reward: **{s.daily_reward:,} {s.currency_symbol}** (0 disables)\nCurrency: **{s.currency_symbol}**')
    return embed('Economy & games',text)

class DepositStatusCog(commands.Cog):
    def __init__(self,bot):self.bot=bot
    @app_commands.command(name='admin-dashboard',description='Open the private casino administration dashboard')
    async def dashboard(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        self.bot.started_at=getattr(self.bot,'started_at',time.time())
        view=DashboardView(self.bot,it.user.id)
        await send_view(it,overview_embed(self.bot),view)
    @app_commands.command(name='admin-economy',description='Configure persistent economy limits, daily reward, and game availability')
    async def economy(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await send_view(it,economy_embed(self.bot),EconomyView(self.bot,it.user.id))
    @app_commands.command(name='admin-deposits',description='View or safely control deposit invoice activation')
    async def deposits(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await send_view(it,deposit_readiness(self.bot),DepositControlView(self.bot,it.user.id))
    @app_commands.command(name='admin-maintenance-panel',description='Open maintenance controls and require confirmation')
    async def maintenance(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await send_view(it,maintenance_embed(self.bot),MaintenanceView(self.bot,it.user.id))
    @app_commands.command(name='admin-emoji',description='Configure custom emoji mappings')
    async def emoji(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await send_view(it,emoji_list_embed(self.bot),EmojiView(self.bot,it.user.id))
    @app_commands.command(name='admin-prefix',description='Preview and change the command prefix')
    async def prefix(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await it.response.send_modal(PrefixModal(self.bot,it.user.id))
    @app_commands.command(name='admin-logs',description='Configure and test casino log channels')
    async def logs(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await send_view(it,routes_embed(self.bot),ChannelRouteView(self.bot,it.user.id))
    @app_commands.command(name='admin-branding',description='Preview and change casino name and embed color')
    async def branding(self,it):
        if not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        await it.response.send_modal(BrandingModal(self.bot,it.user.id))
async def setup(bot): await bot.add_cog(DepositStatusCog(bot))

def deposit_readiness(bot):
    lines=[f"Provider credentials: **{'configured' if bot.payments else 'missing'}**",f"Deposit switch: **{'ON' if bot.settings.deposits_enabled else 'OFF'}**",f"Live verification reviewed: **{'yes' if bot.settings.deposits_live_verified else 'no'}**",f"Withdrawals: **disabled** (no verified payout system)",f"Minimum: **{bot.settings.min_deposit}** selected coin units"]
    if bot.payments:
        for key,(name,network,_) in SUPPORTED.items():
            problem=bot.payments.rate_readiness(key); ts=bot.payments.rate_updated_at.get(key); source=bot.payments.rate_sources.get(key,'')
            lines.append(f"**{name} · {network}:** {'Ready' if not problem else 'Unavailable'} · rate source {source or 'missing'}"+(f' · <t:{int(ts)}:R>' if ts else ''))
    else: lines.append('Supported networks: LTC, USDT BEP20, USDT ERC20 (provider not configured)')
    return embed('Deposit readiness','\n'.join(lines)+'\n\nReal deposits stay disabled until the provider review flag, fresh sourced rates, and admin confirmation are all present.',state='pending')

class BrandingModal(discord.ui.Modal,title='Preview casino branding'):
    name=discord.ui.TextInput(label='Casino name',min_length=2,max_length=40,required=True)
    color=discord.ui.TextInput(label='Embed accent color (#RRGGBB)',placeholder='#1D9A6C',min_length=6,max_length=7,required=True)
    def __init__(self,bot,owner):super().__init__();self.bot=bot;self.owner=owner
    async def on_submit(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):return await deny(it)
        name=str(self.name).strip(); raw=str(self.color).strip().removeprefix('#')
        try: color=int(raw,16)
        except ValueError:return await it.response.send_message(embed=embed('Invalid color','Use a six-digit hex color, e.g. `#1D9A6C`.'),ephemeral=True)
        if len(raw)!=6 or not name:return await it.response.send_message(embed=embed('Invalid branding','Use a name and six-digit color.'),ephemeral=True)
        await send_view(it,discord.Embed(title=name,description='Branding preview',color=color),BrandingConfirm(self.bot,self.owner,name,color))
class BrandingConfirm(SafeDashboardView):
    def __init__(self,bot,owner,name,color):super().__init__(timeout=90);self.bot=bot;self.owner=owner;self.name=name;self.color=color
    async def interaction_check(self,it):
        if it.user.id!=self.owner or not await allowed(self.bot,it.user,it.guild,it.channel):await deny(it);return False
        return True
    @discord.ui.button(label='Save branding',style=discord.ButtonStyle.success)
    async def save(self,it,b):
        await self.bot.db.set_configs({'casino_name':self.name,'brand_color':str(self.color)},it.user.id,'branding_update')
        self.bot.settings.casino_name=self.name;self.bot.settings.brand_color=self.color
        from services.ui import set_brand_color
        set_brand_color(self.color)
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('Branding saved',f'{self.name} · #{self.color:06X}',state='success'),view=self)
    @discord.ui.button(label='Cancel',style=discord.ButtonStyle.secondary)
    async def cancel(self,it,b):
        for c in self.children:c.disabled=True
        await it.response.edit_message(embed=embed('No change','Branding was not changed.'),view=self)
