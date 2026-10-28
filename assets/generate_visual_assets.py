"""Regenerate the original, dependency-free Emerald Vault PNG art pack."""
from pathlib import Path
import math, struct, zlib
OUT=Path(__file__).parent/'premium'; OUT.mkdir(exist_ok=True)
INK=(9,15,12); PANEL=(15,28,22); GREEN=(24,125,82); MINT=(72,205,145); GOLD=(207,174,100); WHITE=(222,235,226)

def png(path,w,h,pixel):
    raw=bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w): raw.extend((*pixel(x,y),255))
    def chunk(tag,data): return struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data)&0xffffffff)
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',w,h,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw),9))+chunk(b'IEND',b'')
    path.write_bytes(data)

def inside_poly(x,y,pts):
    c=False; j=len(pts)-1
    for i in range(len(pts)):
        xi,yi=pts[i]; xj,yj=pts[j]
        if ((yi>y)!=(yj>y)) and x < (xj-xi)*(y-yi)/(yj-yi+1e-9)+xi: c=not c
        j=i
    return c

def line_dist(x,y,a,b):
    ax,ay=a; bx,by=b; dx=bx-ax; dy=by-ay
    t=max(0,min(1,((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy+1e-9)))
    return math.hypot(x-(ax+t*dx),y-(ay+t*dy))

def art(name,w=256,h=256):
    # A custom drawn illustration with no external assets or network references.
    cx=w/2; cy=h/2; scale=min(w,h)/256; banner=w>h; virtual_w=w/scale
    def p(x,y): return (x/scale,y/scale)
    def color(x,y):
        X,Y=p(x,y); t=max(0,min(1,Y/256)); bg=tuple(int(INK[i]*(1-t)+PANEL[i]*t) for i in range(3))
        # fine border and radial emerald ambient light
        r=math.hypot(X-(virtual_w*.78 if banner else 128),Y-128)
        if r<122 and not banner:
            glow=max(0,1-r/180)*.13; bg=tuple(min(255,int(v+GREEN[i]*glow)) for i,v in enumerate(bg))
        if min(X,Y,virtual_w-X,256-Y)<2:return (31,75,53)
        def circ(x0,y0,r0): return math.hypot(X-x0,Y-y0)<=r0
        def rect(x0,y0,x1,y1): return x0<=X<=x1 and y0<=Y<=y1
        def poly(pts): return inside_poly(X,Y,pts)
        def ln(a,b,th=3): return line_dist(X,Y,a,b)<=th/2
        if name=='logo':
            if 91<=X<=165 and 56<=Y<=200 and (abs(X-91)<5 or abs(X-165)<5 or abs(Y-56)<5 or abs(Y-200)<5): return GOLD
            if poly([(103,75),(130,75),(153,97),(130,120),(153,143),(130,167),(103,167),(126,143),(108,125),(126,105)]): return MINT
            if circ(128,128,107) and not circ(128,128,103): return GREEN
        elif name in ('welcome','games','wallet'):
            # Banner ratio is 3:1; keep the left half open for embed titles.
            bx=virtual_w*.78; by=128
            if circ(bx,by,76) and not circ(bx,by,67): return GOLD
            if abs(math.hypot(X-bx,Y-by)-57)<2: return MINT
            if poly([(bx,by-43),(bx+34,by),(bx,by+43),(bx-34,by)]): return (23,84,57)
            if name=='wallet' and ln((bx-39,by+4),(bx+39,by+4),4): return GOLD
            if name=='games' and any(rect(bx+dx,by+dy,bx+dx+12,by+dy+12) for dx,dy in [(-17,-17),(4,-17),(-17,4),(4,4)]): return MINT
            if rect(35,211,virtual_w-35,213): return GOLD
            if rect(35,38,37,213): return GREEN
        elif name=='mines':
            for yy in (70,122,174):
                for xx in (70,122,174):
                    if rect(xx,yy,xx+39,yy+39):
                        if (xx,yy)==(122,122): return GOLD if circ(xx+20,yy+20,11) else PANEL
                        return MINT if rect(xx+4,yy+4,xx+35,yy+35) else GREEN
        elif name=='blackjack':
            if poly([(65,65),(156,65),(174,170),(83,185)]): return (26,61,44)
            if poly([(100,52),(188,70),(164,188),(77,170)]): return WHITE if (abs(X-100)<2 or abs(Y-52)<2) else GREEN
            if circ(131,121,20) and rect(120,108,141,137): return GOLD
        elif name=='dragon-tower':
            for i in range(4):
                yy=184-i*35; xx=68+i*23
                if poly([(xx,yy),(xx+91,yy),(xx+76,yy-26),(xx-15,yy-26)]): return MINT if yy==79 else GREEN
                if ln((xx,yy),(xx+91,yy),2): return GOLD
            if poly([(124,60),(148,60),(141,38),(131,45),(123,35),(113,51)]): return GOLD
        elif name=='crash':
            for yy in (75,125,175):
                if ln((55,yy),(201,yy),1): return (39,59,49)
            if line_dist(X,Y,(59,190),(98,161))<4 or line_dist(X,Y,(98,161),(128,165))<4 or line_dist(X,Y,(128,165),(163,112))<4 or line_dist(X,Y,(163,112),(198,65))<4:return MINT
            if circ(198,65,7):return GOLD
        elif name=='limbo':
            r=math.hypot(X-128,Y-128)
            if abs(r-72)<5:return GREEN
            if abs(r-48)<5:return MINT
            if abs(r-23)<5:return GOLD
            if line_dist(X,Y,(128,128),(187,78))<3:return WHITE
            if circ(128,128,5):return GOLD
        elif name=='dice':
            if poly([(66,87),(142,64),(194,91),(117,115)]): return MINT
            if poly([(66,87),(117,115),(117,192),(66,164)]): return GREEN
            if poly([(117,115),(194,91),(194,166),(117,192)]): return (28,96,62)
            for px,py in [(88,105),(101,147),(142,130),(167,110),(169,152)]:
                if circ(px,py,4):return WHITE
        elif name=='chicken-road':
            if poly([(48,190),(80,160),(110,170),(141,124),(170,136),(207,78),(216,198)]): return (19,61,43)
            if any(line_dist(X,Y,a,b)<5 for a,b in [((50,185),(91,145)),((91,145),(126,158)),((126,158),(160,112)),((160,112),(195,63))]): return MINT
            for xx,yy in [(91,145),(126,158),(160,112),(195,63)]:
                if circ(xx,yy,6): return GOLD
            if circ(76,196,15):return GOLD
        elif name=='limo':
            if poly([(46,147),(67,119),(163,119),(194,143),(211,150),(211,179),(45,179)]): return GREEN
            if poly([(80,124),(101,124),(101,142),(67,142)]): return MINT
            if poly([(108,124),(158,124),(177,142),(108,142)]): return MINT
            for xx in (78,174):
                if circ(xx,179,14):return GOLD if circ(xx,179,6) else INK
            if rect(49,150,207,153):return GOLD
        elif name=='pump':
            if poly([(104,65),(150,65),(150,91),(168,111),(168,183),(85,183),(85,111),(104,91)]): return GREEN
            if rect(105,45,150,68):return GOLD
            if poly([(94,145),(108,126),(124,143),(140,105),(157,134),(161,166),(94,166)]):return MINT
            if ln((85,187),(168,187),4):return GOLD
        return bg
    png(OUT/f'{name}.png',w,h,color)

for n in ('logo','mines','blackjack','dragon-tower','crash','limbo','dice','chicken-road','limo','pump'): art(n)
for n in ('welcome','games','wallet'): art(n,1200,400)
print('generated',len(list(OUT.glob('*.png'))),'PNG assets')
