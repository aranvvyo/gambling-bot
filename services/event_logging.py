"""Non-blocking Discord audit-event delivery; financial truth stays in SQLite."""
import asyncio, logging
from datetime import datetime, timezone
import discord

class EventLogger:
    def __init__(self, bot, channels):
        self.bot, self.channels = bot, channels
        self.queue = asyncio.Queue(maxsize=2000); self.seen = set(); self.task = None
        self.logger = logging.getLogger('casino.audit')
    def start(self):
        if self.task is None: self.task = asyncio.create_task(self._worker(), name='casino-event-logger')
    async def publish_fairness_commitment(self, commitment):
        channel_id=self.channels.get('fairness',0)
        if not channel_id: raise RuntimeError('FAIRNESS_LOG_CHANNEL_ID is required to publish commitments before play')
        channel=self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        from services.emojis import resolve_emoji
        e=discord.Embed(title=f"{resolve_emoji(self.bot,'outcome')} Provably fair seed commitment",description=f'Active server-seed SHA-256: `{commitment}`\nPublished before games using this seed.',color=0xD4AF37,timestamp=datetime.now(timezone.utc))
        for attempt in range(3):
            try:
                await channel.send(embed=e,allowed_mentions=discord.AllowedMentions.none()); return
            except discord.Forbidden:
                raise RuntimeError('Cannot publish fairness commitment: missing channel permissions')
            except discord.HTTPException:
                if attempt==2: raise
                await asyncio.sleep(2**attempt)

    async def publish_fairness_reveal(self, commitment, server_seed, revealed_at):
        channel_id=self.channels.get('fairness',0)
        if not channel_id: raise RuntimeError('FAIRNESS_LOG_CHANNEL_ID is required to publish retired seeds')
        channel=self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        from services.emojis import resolve_emoji
        e=discord.Embed(title=f"{resolve_emoji(self.bot,'outcome')} Provably fair server seed revealed",description=f'Commitment: `{commitment}`\nServer seed: `{server_seed}`\nRetired and revealed: <t:{int(revealed_at)}:F>\nAll associated rounds settled or were refunded.',color=0xD4AF37,timestamp=datetime.now(timezone.utc))
        for attempt in range(3):
            try: await channel.send(embed=e,allowed_mentions=discord.AllowedMentions.none()); return
            except discord.Forbidden: raise RuntimeError('Cannot publish retired seed: missing channel permissions')
            except discord.HTTPException:
                if attempt==2: raise
                await asyncio.sleep(2**attempt)

    def emit(self, category, event, **fields):
        ref=fields.get('reference'); key=(category,ref) if ref else None
        if key and key in self.seen: return
        if key: self.seen.add(key)
        safe={k:v for k,v in fields.items() if not any(x in str(k).casefold() for x in ('token','secret','password','address','private_key','api_key'))}
        self.logger.info('event=%s category=%s fields=%r',event,category,safe)
        try: self.queue.put_nowait((category,event,safe))
        except asyncio.QueueFull: self.logger.error('audit queue full; event=%s category=%s',event,category)
    async def _worker(self):
        while True:
            category,event,fields=await self.queue.get(); channel_id=self.channels.get(category,0) or (self.channels.get('general',0) if category=='wallet' else 0)
            if not channel_id: self.queue.task_done(); continue
            for attempt in range(3):
                try:
                    channel=self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    from services.emojis import resolve_emoji
                    safe={k:v for k,v in fields.items() if not any(x in k.casefold() for x in ('token','secret','password','address','private_key','api_key'))}
                    lines=[f'**{key.replace("_"," ").title()}:** {str(value)[:180]}' for key,value in safe.items()]
                    icon={'wins':'success','loss':'failed','deposit':'note','withdrawal':'locked','admin':'locked','security':'alert','error':'alert','fairness':'outcome','general':'info'}.get(category)
                    title=f"{resolve_emoji(self.bot,icon)} {event}" if icon else event
                    e=discord.Embed(title=title[:240],description='\n'.join(lines)[:3900] or 'Casino event',color=0xD4AF37,timestamp=datetime.now(timezone.utc))
                    await channel.send(embed=e,allowed_mentions=discord.AllowedMentions.none()); break
                except asyncio.CancelledError: raise
                except Exception as exc:
                    self.logger.warning('audit delivery attempt %s failed for %s: %s',attempt+1,event,type(exc).__name__)
                    if attempt<2: await asyncio.sleep(2**attempt)
            self.queue.task_done()
    async def close(self):
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
