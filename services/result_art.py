"""Dependency-free, compact PNG game-result cards for low-resource Termux."""
from io import BytesIO
import math, struct, zlib
W,H=960,480
BG=(8,13,22); PANEL=(15,25,38); GRID=(27,43,57); WHITE=(232,240,247); MUTED=(145,163,178); GREEN=(38,201,132); RED=(226,78,89); GOLD=(218,181,103)
# 5x7 bitmap glyphs; enlarged x4 so key values remain readable on mobile.
FONT={
'A':('01110','10001','10001','11111','10001','10001','10001'),'B':('11110','10001','10001','11110','10001','10001','11110'),'C':('01111','10000','10000','10000','10000','10000','01111'),'D':('11110','10001','10001','10001','10001','10001','11110'),'E':('11111','10000','10000','11110','10000','10000','11111'),'F':('11111','10000','10000','11110','10000','10000','10000'),'G':('01111','10000','10000','10111','10001','10001','01111'),'H':('10001','10001','10001','11111','10001','10001','10001'),'I':('11111','00100','00100','00100','00100','00100','11111'),'J':('00111','00010','00010','00010','10010','10010','01100'),'K':('10001','10010','10100','11000','10100','10010','10001'),'L':('10000','10000','10000','10000','10000','10000','11111'),'M':('10001','11011','10101','10101','10001','10001','10001'),'N':('10001','11001','11001','10101','10011','10011','10001'),'O':('01110','10001','10001','10001','10001','10001','01110'),'P':('11110','10001','10001','11110','10000','10000','10000'),'Q':('01110','10001','10001','10001','10101','10010','01101'),'R':('11110','10001','10001','11110','10100','10010','10001'),'S':('01111','10000','10000','01110','00001','00001','11110'),'T':('11111','00100','00100','00100','00100','00100','00100'),'U':('10001','10001','10001','10001','10001','10001','01110'),'V':('10001','10001','10001','10001','10001','01010','00100'),'W':('10001','10001','10001','10101','10101','11011','10001'),'X':('10001','01010','00100','00100','00100','01010','10001'),'Y':('10001','01010','00100','00100','00100','00100','00100'),'Z':('11111','00001','00010','00100','01000','10000','11111'),
'0':('01110','10001','10011','10101','11001','10001','01110'),'1':('00100','01100','00100','00100','00100','00100','01110'),'2':('01110','10001','00001','00010','00100','01000','11111'),'3':('11110','00001','00001','01110','00001','00001','11110'),'4':('00010','00110','01010','10010','11111','00010','00010'),'5':('11111','10000','10000','11110','00001','00001','11110'),'6':('01110','10000','10000','11110','10001','10001','01110'),'7':('11111','00001','00010','00100','01000','01000','01000'),'8':('01110','10001','10001','01110','10001','10001','01110'),'9':('01110','10001','10001','01111','00001','00001','01110'),
' ':('00000',)*7,'.':('00000','00000','00000','00000','00000','00110','00110'),':':('00000','00110','00110','00000','00110','00110','00000'),'-':('00000','00000','00000','11111','00000','00000','00000'),'/':('00001','00010','00010','00100','01000','01000','10000'),'$':('00100','01111','10100','01110','00101','11110','00100'),'+':('00000','00100','00100','11111','00100','00100','00000'),'×':('10001','01010','00100','00100','00100','01010','10001')}
class Canvas:
 def __init__(self): self.p=bytearray(BG*(W*H))
 def rect(self,x,y,w,h,col):
  x0=max(0,int(x)); y0=max(0,int(y)); x1=min(W,int(x+w)); y1=min(H,int(y+h)); row=bytes(col)*max(0,x1-x0)
  for yy in range(y0,y1):
   q=(yy*W+x0)*3; self.p[q:q+len(row)]=row
 def line(self,x0,y0,x1,y1,col,t=2):
  n=max(abs(int(x1-x0)),abs(int(y1-y0)),1)
  for i in range(n+1): self.rect(x0+(x1-x0)*i/n-t//2,y0+(y1-y0)*i/n-t//2,t,t,col)
 def circle(self,cx,cy,r,col):
  for y in range(max(0,int(cy-r)),min(H,int(cy+r+1))):
   dx=int(math.sqrt(max(0,r*r-(y-cy)**2))); self.rect(cx-dx,y,2*dx+1,1,col)
 def text(self,s,x,y,col=WHITE,k=4):
  x=int(x)
  for ch in str(s).upper():
   for yy,row in enumerate(FONT.get(ch,FONT[' '])):
    for xx,v in enumerate(row):
     if v=='1': self.rect(x+xx*k,y+yy*k,k,k,col)
   x+=6*k
 def png(self):
  raw=b''.join(b'\0'+self.p[y*W*3:(y+1)*W*3] for y in range(H))
  def chunk(t,d): return struct.pack('!I',len(d))+t+d+struct.pack('!I',zlib.crc32(t+d)&0xffffffff)
  return BytesIO(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',W,H,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,5))+chunk(b'IEND',b''))
def _s(v,n=22): return str(v)[:n]
def render_result(game,*,outcome,bet,payout,balance,data=None,game_id=None,won=None,status=None):
 """Render only the supplied settled outcome; no game values are generated here."""
 d=data or {}; won=(payout>0) if won is None else bool(won); c=Canvas()
 for x in range(44,W-24,64): c.line(x,98,x,312,GRID,1)
 for y in range(110,313,50): c.line(44,y,W-32,y,GRID,1)
 c.rect(0,0,W,5,GOLD); c.text(_s(game.replace('-',' '),24),44,32,GOLD,5); c.text((status or ('win' if won else 'loss')).upper(),760,38,GREEN if won else RED,4)
 c.rect(44,352,872,2,GRID)
 for x,label,value,col in [(52,'WAGER',bet,WHITE),(300,'PAYOUT',payout,GREEN if won else RED),(548,'BALANCE',balance,WHITE)]: c.text(label,x,378,MUTED,3); c.text(_s(value,14),x,406,col,4)
 if game_id: c.text('ID '+_s(game_id,16),785,406,GOLD,2)
 c.text(_s(outcome.upper(),28),52,154,GREEN if won else RED,5)
 if game in ('limbo','crash','pump'):
  point=float(d.get('point',d.get('attempted',d.get('result',d.get('multiplier',1)))) or 1); result=float(d.get('result',d.get('multiplier',point)) or 1)
  c.text('RESULT '+format(result,'.2f')+'X',52,214,WHITE,3)
  key='target' if game=='limbo' else 'point'; val=d.get(key)
  if val is not None: c.text(('TARGET ' if game=='limbo' else 'CRASH ')+format(float(val),'.2f')+'X',52,250,RED if game=='crash' else GOLD,3)
  pts=[(385+i*64,300-int(180*(i/7)**1.55)) for i in range(8)]
  for a,b in zip(pts,pts[1:]): c.line(*a,*b,GREEN if won else RED,4)
  if game=='limbo':
   ty=300-int(180*min(float(d.get('target',1))/10,1)); c.line(385,ty,833,ty,GOLD,2)
  marker=min(7,max(0,int(min(result,10)/10*7))); c.circle(*pts[marker],8,RED if not won and game in ('crash','pump') else GOLD); c.line(pts[marker][0],112,pts[marker][0],316,GOLD,2)
 elif game in ('mines','dragon-tower','chicken-road','limo'):
  cols=max(2,min(int(d.get('cols',5)),8)); rows=max(1,min(int(d.get('rows',4)),5)); cell=min(52,250//cols); left,top=440,120
  safe=set(d.get('safe',[])); bombs=set(d.get('bombs',[])); opened=set(d.get('opened',[])); winner=d.get('winner'); chosen=d.get('chosen')
  if game=='mines': bombs=set(d.get('bombs',d.get('layout',[])))
  elif game=='dragon-tower':
   cols=int(d.get('cols',2)); rows=int(d.get('rows',5)); safe={r*cols+v for r,v in enumerate(d.get('safe_path',d.get('safe',[])))}; opened={r*cols+v for r,v in enumerate(d.get('chosen_path',d.get('opened',[])))}
  elif game=='chicken-road':
   cols=3; rows=5; safe={r*cols+v for r,v in enumerate(d.get('safe_path',d.get('safe',[])))}; opened={r*cols+v for r,v in enumerate(d.get('chosen_path',d.get('opened',[])))}
   path=d.get('chosen_path',[]); steps=int(d.get('steps',0)); chosen=(steps*cols+path[-1]) if path and steps<len(path) else None
  for i in range(cols*rows):
   x=left+(i%cols)*(cell+7); y=top+(i//cols)*(cell+7); col=GREEN if i in safe or i in opened else RED if i in bombs else PANEL
   if game=='limo' and isinstance(winner,int) and i==winner: col=GOLD
   c.rect(x,y,cell,cell,col)
   if i in bombs: c.text('X',x+cell//2-9,y+cell//2-13,WHITE,4)
   elif i in safe or i in opened: c.text('+',x+cell//2-9,y+cell//2-13,WHITE,4)
   elif isinstance(chosen,int) and i==chosen: c.rect(x,y,cell,3,GOLD)
  c.text('STEPS '+str(d.get('steps',len(opened))),52,232,GOLD,3); c.text('MULT '+_s(d.get('multiplier','--'),12)+'X',52,270,WHITE,3)
 elif game=='blackjack':
  c.text('PLAYER',52,220,MUTED,3); c.text(' '.join(map(str,d.get('player',[]))) or '--',52,250,WHITE,4); c.text('DEALER',470,220,MUTED,3); c.text(' '.join(map(str,d.get('dealer',[]))) or '--',470,250,GOLD,4)
  for i,card in enumerate(d.get('player',[])[:8]): c.rect(530+i*44,112,38,66,PANEL); c.text(_s(card,3),535+i*44,137,WHITE,3)
 elif game=='dice':
  c.text(str(d.get('direction','')).upper()+' '+str(d.get('target','')),52,240,MUTED,3); c.circle(718,222,80,GOLD); c.circle(718,222,70,PANEL); c.text(_s(d.get('roll','?'),3),690,207,WHITE,6)
 else:
  details=' '.join(f'{k}:{v}' for k,v in list(d.items())[:3]); c.text(_s(details,25),52,235,MUTED,3); c.circle(720,220,78,GREEN if won else RED); c.circle(720,220,64,PANEL); c.text('WIN' if won else 'OUT',680,206,WHITE,4)
 b=c.png(); b.seek(0); return b
