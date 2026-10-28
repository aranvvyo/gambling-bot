from types import SimpleNamespace
import struct
import discord
import pytest
from services.result_art import render_result
from services.result_ui import game_result

GAMES = ('limbo','crash','mines','dragon-tower','blackjack','dice','chicken-road','limo','pump')

@pytest.mark.parametrize('game', GAMES)
def test_result_png_is_valid_and_compact(game):
    stream=render_result(game,outcome='win',bet=100,payout=180,balance=1080,
        data={'target':2.0,'result':2.4,'point':3.2,'roll':42,'direction':'under','player':['A','K'],'dealer':['9','7'],
              'cols':4,'rows':4,'bombs':[2,9],'opened':[0,1],'safe_path':[0,1,1], 'chosen_path':[0,1], 'steps':2,'multiplier':'1.80'},game_id='session-abc')
    raw=stream.getvalue()
    assert raw.startswith(b'\x89PNG\r\n\x1a\n')
    assert struct.unpack('!II',raw[16:24]) == (960,480)
    assert len(raw) < 100_000

@pytest.mark.parametrize('game', GAMES)
def test_game_specific_result_art_differs(game):
    data={'target':2.0,'result':2.4,'point':3.2,'roll':42,'direction':'under','player':['A','K'],'dealer':['9','7'],
          'cols':4,'rows':4,'bombs':[2,9],'opened':[0,1],'safe_path':[0,1,1], 'chosen_path':[0,1], 'steps':2,'multiplier':'1.80'}
    a=render_result(game,outcome='won',bet=100,payout=180,balance=1080,data=data).getvalue()
    b=render_result(game,outcome='lost',bet=100,payout=0,balance=800,data=data).getvalue()
    assert a != b

@pytest.mark.asyncio
async def test_result_embed_reflects_settled_data_and_attaches_png():
    class DB:
        async def balance(self, uid):
            assert uid == 42
            return 735
    bot=SimpleNamespace(db=DB())
    e,f=await game_result(bot,42,'limbo',outcome='Target 2.00x · result 2.44x',bet=25,payout=61,
        data={'target':2.0,'result':2.44},game_id='real-session-9',fair={'round_id':'real-round-8'})
    assert [x.value for x in e.fields] == ['25 VC','61 VC','735 VC','Round `real-round-8`']
    assert e.footer.text.startswith('Game ID real-session-9')
    assert e.image.url == 'attachment://game-result.png'
    assert f.filename == 'game-result.png'
    assert f.fp.read(8) == b'\x89PNG\r\n\x1a\n'

@pytest.mark.asyncio
async def test_result_renderer_does_not_require_bundled_game_assets():
    png=render_result('mines',outcome='loss',bet=1,payout=0,balance=0,data={'bombs':[0]},game_id=None)
    assert png.read(8) == b'\x89PNG\r\n\x1a\n'

@pytest.mark.parametrize(('game','first','second'),[
 ('limbo',{'target':1.5,'result':2.1},{'target':7.0,'result':2.1}),
 ('crash',{'point':2.1,'result':2.0},{'point':8.5,'result':2.0}),
 ('dice',{'roll':12,'target':50,'direction':'under'},{'roll':82,'target':50,'direction':'under'}),
 ('blackjack',{'player':['A','K'],'dealer':['8','7']},{'player':['5','6'],'dealer':['K','Q']}),
 ('mines',{'cols':4,'rows':4,'bombs':[1,4],'opened':[2]},{'cols':4,'rows':4,'bombs':[3,7],'opened':[8]}),
])
def test_graphic_tracks_real_game_specific_values(game,first,second):
    a=render_result(game,outcome='settled',bet=10,payout=0,balance=90,data=first).getvalue()
    b=render_result(game,outcome='settled',bet=10,payout=0,balance=90,data=second).getvalue()
    assert a != b

def test_every_implemented_game_cog_wires_result_art():
    import ast
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/'cogs'
    expected={
        'limbo.py':'game_result', 'crash.py':'game_result', 'mines.py':'game_result',
        'dragon_tower.py':'game_result', 'blackjack.py':'game_result', 'new_games.py':'game_result',
        'limo.py':'game_result',
    }
    for filename, function in expected.items():
        tree=ast.parse((root/filename).read_text())
        assert any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id==function for node in ast.walk(tree)), filename
