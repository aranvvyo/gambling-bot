from decimal import Decimal
import pytest
from games.math import dice_probability,dice_result,chicken_safe_tile,chicken_multiplier,pump_crash_point,pump_multiplier
from services.fairness import FairnessService, commitment, digest
from database.db import Database

def test_dice_probability_and_result():
 assert dice_probability('under',30)==Decimal('.3')
 assert dice_probability('over',30)==Decimal('.69')
 with pytest.raises(ValueError): dice_probability('over',100)
 low=dice_result('0000'+'0'*60,'under',30)
 assert low==dice_result('0000'+'0'*60,'under',30) and 0<=low[0]<100
 high=dice_result('ffff'+'0'*60,'under',30)
 assert high==dice_result('ffff'+'0'*60,'under',30) and 0<=high[0]<100

def test_chicken_and_pump_math():
 d='a5'*32
 assert chicken_safe_tile(d,2)==chicken_safe_tile(d,2)
 assert chicken_multiplier(2)==Decimal('8.91')
 assert pump_crash_point(d)==pump_crash_point(d)
 assert pump_multiplier(5)==Decimal('1.40')

def test_fair_commitment_reproducibility():
 assert commitment('seed')==commitment('seed')
 assert digest('server','client',1,'dice')==digest('server','client',1,'dice')
 assert digest('server','client',1,'dice')!=digest('server','client',2,'dice')

@pytest.mark.asyncio
async def test_rotation_reveals_only_after_settlement(tmp_path,monkeypatch):
 import database.db as dbmod
 db=await Database(f"sqlite:///{tmp_path/'fair.db'}").open(); service=FairnessService(db,60)
 first=await service.allocate(88,'dice','client')
 await db.conn.execute('UPDATE fair_seeds SET created_at=1'); await db.conn.commit()
 monkeypatch.setattr(dbmod.time,'time',lambda:10000)
 second=await service.allocate(89,'dice','other')
 assert second['commitment']!=first['commitment']
 assert await service.verify(first['round_id']) is None
 from games.math import dice_result
 roll,won,mult,_=dice_result(first['digest'],'under',50)
 from services.game_math import payout
 await service.settle(first['round_id'],__import__('json').dumps({'algorithm':'casino-v1','direction':'under','target':50,'edge':'0.01','roll':roll,'won':won,'bet':10,'cap':100,'payout':payout(10,mult,100) if won else 0}))
 verified=await service.verify(first['round_id'])
 assert verified['valid'] and commitment(verified['revealed_seed'])==verified['commitment']
 assert await service.verify(second['round_id']) is None
 await db.close()

@pytest.mark.asyncio
async def test_reference_replay_and_overlapping_game_rejected(tmp_path):
 db=await Database(f"sqlite:///{tmp_path/'ledger.db'}").open(); await db.change_balance(1,20,'seed','seed:1')
 with pytest.raises(ValueError,match='different operation'): await db.change_balance(1,4,'other','seed:1')
 await db.start_game(1,'dice',5)
 with pytest.raises(ValueError,match='active game'): await db.start_game(1,'pump',5)
 await db.close()
