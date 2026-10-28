import asyncio
import logging
import pytest
from services.event_logging import EventLogger

class Channel:
 def __init__(self): self.calls=0; self.messages=[]
 async def send(self,**kwargs):
  self.calls+=1
  if self.calls==1: raise RuntimeError('temporary')
  self.messages.append(kwargs)
class Bot:
 def __init__(self):self.channel=Channel()
 def get_channel(self,id):return self.channel
 async def fetch_channel(self,id):return self.channel

@pytest.mark.asyncio
async def test_logging_queues_retries_and_deduplicates(caplog):
 bot=Bot(); service=EventLogger(bot,{'bet':10});service.start()
 service.emit('bet','Bet settled',user_id=3,amount=5,reference='bet:one')
 service.emit('bet','Bet settled',user_id=3,amount=5,reference='bet:one')
 await asyncio.wait_for(service.queue.join(),timeout=5)
 assert bot.channel.calls==2 and len(bot.channel.messages)==1
 assert 'Bet settled' in caplog.text
 await service.close()

@pytest.mark.asyncio
async def test_missing_route_is_nonblocking_and_local_record_is_written(caplog):
 caplog.set_level(logging.INFO,logger='casino.audit')
 bot=Bot(); service=EventLogger(bot,{})
 service.start(); service.emit('security','Denied',user_id=12,reference='denied:12')
 await asyncio.wait_for(service.queue.join(),timeout=1)
 assert bot.channel.calls==0 and 'Denied' in caplog.text
 await service.close()
