"""Expose the registered slash-command implementations through dot-prefix syntax.

The adapter preserves the original command callbacks, database, fairness logic and
component views. Ephemeral replies are delivered by DM so payment and game screens
are not accidentally made public by prefix invocations.
"""
import inspect
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
from services.ui import embed

ASSET_FOR_COMMAND = {
    'mines':'mines', 'blackjack':'blackjack', 'dragon-tower':'dragon-tower',
    'crash':'crash', 'limbo':'limbo', 'limo':'limo', 'dice':'dice',
    'chicken-road':'chicken-road', 'pump':'pump', 'casino':'welcome',
}

class PrefixResponse:
    def __init__(self, interaction):
        self.interaction=interaction; self.done=False; self.ephemeral=False
    def is_done(self): return self.done
    async def defer(self, *, ephemeral=False, thinking=False):
        self.done=True; self.ephemeral=ephemeral
    async def send_message(self, content=None, **kwargs):
        self.done=True
        return await self.interaction.send(content, ephemeral=kwargs.pop('ephemeral',self.ephemeral), **kwargs)
    async def edit_message(self, **kwargs):
        self.done=True
        return await self.interaction.edit_original_response(**kwargs)

class PrefixFollowup:
    def __init__(self, interaction): self.interaction=interaction
    async def send(self, content=None, **kwargs):
        ephemeral=kwargs.pop('ephemeral',True)
        kwargs.pop('wait',None)
        return await self.interaction.send(content,ephemeral=ephemeral,**kwargs)

class PrefixInteraction:
    def __init__(self,ctx,command):
        self.ctx=ctx; self.user=ctx.author; self.guild=ctx.guild; self.channel=ctx.channel
        self.client=ctx.bot; self.command=command; self.id=ctx.message.id
        self.response=PrefixResponse(self); self.followup=PrefixFollowup(self); self._message=None
    async def send(self,content=None,*,ephemeral=False,**kwargs):
        file=kwargs.get('file')
        if file is None and not kwargs.get('files') and kwargs.get('embed') and self.command.name in ASSET_FOR_COMMAND:
            key=ASSET_FOR_COMMAND[self.command.name]
            path=Path(__file__).resolve().parents[1]/'assets'/'premium'/f'{key}.png'
            if path.is_file():
                filename=f'{key}.png'; kwargs['file']=discord.File(path,filename=filename)
                if key in ('welcome','games','wallet'): kwargs['embed'].set_image(url=f'attachment://{filename}')
                else: kwargs['embed'].set_thumbnail(url=f'attachment://{filename}')
        if ephemeral and self.ctx.guild:
            try: self._message=await self.user.send(content,**kwargs)
            except discord.Forbidden:
                # Propagate to game callbacks so any newly opened wager is refunded.
                raise
        else:
            self._message=await self.ctx.send(content,**kwargs)
        return self._message
    async def edit_original_response(self,**kwargs):
        if self._message is None: return await self.send(ephemeral=self.response.ephemeral,**kwargs)
        return await self._message.edit(**kwargs)
    async def original_response(self):
        if self._message is None: raise discord.NotFound(response=None, message='No prefix response exists yet')
        return self._message


def _prefix_annotation(parameter):
    typ=getattr(parameter.type,'name',str(parameter.type))
    if typ == 'integer': return int
    if typ == 'number': return float
    if typ == 'boolean': return bool
    if typ == 'user': return discord.User
    if typ == 'channel': return discord.TextChannel
    return str


def _choice_value(option,value):
    if not option.choices: return value
    lowered=str(value).casefold()
    for choice in option.choices:
        if lowered in (str(choice.value).casefold(),choice.name.casefold()): return choice.value
    allowed=', '.join(f'{x.name} ({x.value})' for x in option.choices)
    raise commands.BadArgument(f'Choose one of: {allowed}')


def _make_command(bot, app_command):
    original=inspect.signature(app_command.callback)
    original_parameters=list(original.parameters.values())[2:]
    options={p.name:p for p in app_command.parameters}
    params=[commands.Parameter(name='ctx',kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,default=inspect.Parameter.empty,annotation=commands.Context,description='',displayed_default='',displayed_name='ctx')]
    for index,param in enumerate(original_parameters):
        option=options.get(param.name)
        annotation=_prefix_annotation(option) if option else param.annotation
        if annotation is inspect.Parameter.empty: annotation=str
        # A final free-form string (for example an admin audit reason) consumes
        # the rest of the prefix message, matching the slash option's semantics.
        final_text=(index==len(original_parameters)-1 and option is not None and getattr(option.type,'name','')=='string')
        kind=inspect.Parameter.KEYWORD_ONLY if final_text else inspect.Parameter.POSITIONAL_OR_KEYWORD
        params.append(commands.Parameter(name=param.name,kind=kind,default=param.default,annotation=annotation,description='',displayed_default='',displayed_name=param.name))
    signature=inspect.Signature(params)
    async def invoke(ctx,*args,**kwargs):
        bound=signature.bind(ctx,*args,**kwargs); bound.apply_defaults(); values={}
        for name in signature.parameters:
            if name=='ctx': continue
            value=bound.arguments.get(name)
            option=options.get(name)
            if option and option.choices and value is not None:
                value=app_commands.Choice(name=str(value),value=_choice_value(option,value))
            values[name]=value
        # Reserve a working private channel before callbacks can debit a bet or create an invoice.
        if ctx.guild:
            try:
                dm=ctx.author.dm_channel or await ctx.author.create_dm()
                probe=await dm.send(embed=embed('Private command check','Preparing your private command response.',state='info'))
                await probe.delete()
            except discord.Forbidden:
                return await ctx.reply(embed=embed('Enable direct messages','This command returns private account or game details. Enable direct messages (DMs) from server members and try again; no action was taken.',state='error'),mention_author=False)
        adapter=PrefixInteraction(ctx,app_command)
        await app_command.callback(app_command.binding,adapter,**values)
        if adapter._message is not None and ctx.guild and getattr(adapter._message.channel,'id',None)!=ctx.channel.id:
            await ctx.send(embed=embed('Private response sent','Check your direct messages for this command result.',state='info'))
    invoke.__name__='prefix_'+app_command.name.replace('-','_')
    invoke.__signature__=signature
    invoke.__doc__=app_command.description or 'Existing casino command, available through dot-prefix syntax.'
    return commands.Command(invoke,name=app_command.name,help=app_command.description or None,brief=app_command.description or None)

async def setup(bot):
    registered=[]
    for app_command in list(bot.tree.walk_commands()):
        if not isinstance(app_command,app_commands.Command): continue
        if app_command.name in bot.all_commands: continue
        try:
            command=_make_command(bot,app_command)
            bot.add_command(command); registered.append(command.name)
        except (TypeError,ValueError) as exc:
            bot.logger.error('Prefix bridge could not register command=%s type=%s',app_command.name,type(exc).__name__)
    bot.prefix_bridge_names=tuple(sorted(registered))
