"""Large industrial-sector voxel previews for YAN.
Three 128x128 macro layouts: vertical foundry, industrial canyon, terraced megaforge.
No LLM/API required.
"""
from __future__ import annotations
from mcbuild.voxel import VoxelGrid
from mcbuild import palette

MATS = {
    "D":"deepslate_tiles",
    "M":"polished_andesite",
    "C":"light_gray_concrete",
    "R":"cut_copper",
    "W":"weathered_copper",
    "Y":"yellow_concrete",
    "L":"sea_lantern",
    "B":"black_concrete",
    "S":"smooth_stone",
}

_IDX = {}

def _idx(name):
    value = _IDX.get(name)
    if value is None:
        value = palette.get_block(name).index
        _IDX[name] = value
    return value

def _fill(g,a,b,m):
    idx = _idx(m)
    x1,y1,z1=a; x2,y2,z2=b
    for x in range(min(x1,x2),max(x1,x2)+1):
        for y in range(min(y1,y2),max(y1,y2)+1):
            for z in range(min(z1,z2),max(z1,z2)+1):
                g.set(x,y,z,idx)

def _clear(g,a,b):
    x1,y1,z1=a; x2,y2,z2=b
    for x in range(min(x1,x2),max(x1,x2)+1):
        for y in range(min(y1,y2),max(y1,y2)+1):
            for z in range(min(z1,z2),max(z1,z2)+1):
                g.clear_block(x,y,z)

def _room(g,x,y,z,w,h,d,wall):
    _fill(g,(x,y,z),(x+w-1,y+h-1,z+d-1),wall)
    if w>4 and h>3 and d>4:
        _clear(g,(x+2,y+1,z+2),(x+w-3,y+h-2,z+d-3))
    _clear(g,(x+3,y+1,z),(x+w-4,y+h-3,z+1))
    _fill(g,(x+3,y+h-2,z),(x+w-4,y+h-2,z),MATS["D"])
    _fill(g,(x+3,y+h-3,z+2),(x+w-4,y+h-3,z+2),MATS["L"])

def _ring(g,x1,z1,x2,z2,y,t=2,m=None):
    m=m or MATS["M"]
    _fill(g,(x1,y,z1),(x2,y+t-1,z1+t-1),m)
    _fill(g,(x1,y,z2-t+1),(x2,y+t-1,z2),m)
    _fill(g,(x1,y,z1+t),(x1+t-1,y+t-1,z2-t),m)
    _fill(g,(x2-t+1,y,z1+t),(x2,y+t-1,z2-t),m)

def _machines(g,x1,x2,y,z,rows):
    for r in range(rows):
        zz=z+r*5
        for x in range(x1,x2,5):
            _fill(g,(x,y,zz),(x+2,y+2,zz+2),MATS["R"])
            _fill(g,(x,y+3,zz),(x+2,y+3,zz+2),MATS["D"])
        _fill(g,(x1-2,y,zz+1),(x2+1,y,zz+1),MATS["W"])

def _stairs_x(g,x,z,y0,steps,width=5):
    for i in range(steps):
        xx=x+i; yy=y0+i
        _fill(g,(xx,yy,z-width//2),(xx,yy,z+width//2),MATS["M"])
        _clear(g,(xx,yy+1,z-width//2),(xx,yy+3,z+width//2))

def vertical_foundry():
    g=VoxelGrid(); _fill(g,(0,0,0),(127,1,127),MATS["D"])
    a,c,b,d=34,28,94,92
    for x,z in ((18,18),(98,18),(18,98),(98,98)):
        _fill(g,(x,2,z),(x+11,91,z+11),MATS["C"])
        _fill(g,(x+3,6,z-2),(x+7,86,z-1),MATS["R"])
    for y,i in ((12,0),(28,3),(44,6),(60,9),(76,12)):
        _ring(g,a-i,c-i,b+i,d+i,y,3)
        _fill(g,(8,y,57),(a-i,y+1,63),MATS["M"])
        _fill(g,(b+i,y,57),(119,y+1,63),MATS["M"])
    for x in (a,b): _fill(g,(x,2,c),(x+2,84,d),MATS["B"])
    for z in (c,d): _fill(g,(a,2,z),(b,84,z+2),MATS["B"])
    for y in (18,35,52,69):
        _clear(g,(a,y,48),(a+2,y+8,72)); _clear(g,(b,y,48),(b+2,y+8,72))
    for y,z in ((20,42),(36,64),(52,48),(68,70)):
        _fill(g,(41,y,z),(87,y+2,z+9),MATS["D"])
        for x in range(44,85,8): _fill(g,(x,y+3,z+2),(x+4,y+6,z+6),MATS["R"])
        _fill(g,(43,y+1,z+1),(85,y+1,z+1),MATS["Y"])
    _fill(g,(60,2,58),(67,87,65),MATS["D"]); _clear(g,(62,4,60),(65,85,63))
    for y in range(8,86,8):
        _fill(g,(58,y,57),(69,y+1,66),MATS["M"]); _clear(g,(61,y,60),(66,y+2,63))
    _room(g,42,82,42,44,9,36,MATS["C"])
    for x in range(47,82,7):
        _fill(g,(x,83,50),(x+3,87,54),MATS["R"]); _fill(g,(x,87,50),(x+3,88,54),MATS["L"])
    _room(g,4,3,38,24,14,52,MATS["C"]); _room(g,100,3,38,24,14,52,MATS["C"])
    _machines(g,8,24,5,45,7); _machines(g,104,120,5,45,7)
    for y,z in ((28,32),(44,88),(60,32)):
        _fill(g,(20,y,z),(108,y+1,z+5),MATS["M"])
        for x in range(24,106,10): _fill(g,(x,y+2,z+1),(x+2,y+2,z+4),MATS["Y"])
    _stairs_x(g,6,10,3,76,5)
    _fill(g,(10,90,20),(117,92,24),MATS["R"])
    for x in (12,114): _fill(g,(x,2,21),(x+3,90,24),MATS["D"])
    return g

def industrial_canyon():
    g=VoxelGrid(); _fill(g,(0,0,0),(127,1,127),MATS["D"])
    for y,x2 in ((2,42),(18,47),(36,51),(54,55),(72,59)):
        _fill(g,(4,y,8),(x2,min(y+15,92),119),MATS["C"])
        _clear(g,(10,y+3,16),(x2-6,min(y+12,90),111))
    for y,x1 in ((2,78),(20,74),(40,70),(60,66)):
        _fill(g,(x1,y,8),(123,min(y+17,94),119),MATS["S"])
        _clear(g,(x1+6,y+3,16),(117,min(y+13,92),111))
    _fill(g,(56,2,6),(70,3,121),MATS["M"])
    for x in (59,66): _fill(g,(x,4,8),(x+1,4,119),MATS["D"])
    for z in range(10,120,6): _fill(g,(56,4,z),(70,4,z),MATS["R"])
    for y,z,x1,x2 in ((16,26,42,84),(31,68,49,78),(47,39,54,74),(63,83,57,71),(79,22,59,76)):
        _fill(g,(x1,y,z),(x2,y+2,z+6),MATS["D"])
        for x in range(x1+3,x2-2,8): _fill(g,(x,y+3,z+1),(x+3,y+3,z+5),MATS["Y"])
    _room(g,43,74,48,42,14,34,MATS["B"]); _machines(g,48,79,76,55,4)
    _room(g,78,4,72,38,16,38,MATS["C"]); _machines(g,84,110,6,80,5)
    for y,z in ((5,22),(23,44),(41,66),(59,88)):
        _room(g,8,y,z,31,12,22,MATS["C"]); _fill(g,(39,y+4,z+8),(58,y+6,z+13),MATS["M"])
    for x in (18,34,92,108):
        _fill(g,(x,3,11),(x+2,88,13),MATS["R"])
        for y in (20,38,56,74):
            if x<64: _fill(g,(x,y,12),(58,y+1,12),MATS["W"])
            else: _fill(g,(68,y,12),(x,y+1,12),MATS["W"])
    _fill(g,(52,88,12),(75,90,116),MATS["M"])
    for z in range(18,114,12): _fill(g,(54,91,z),(73,92,z+2),MATS["L"])
    return g

def terraced_megaforge():
    g=VoxelGrid(); _fill(g,(0,0,0),(127,1,127),MATS["D"])
    for i,(x,y,z,w,h,d) in enumerate(((6,2,70,54,28,48),(32,24,48,58,32,52),(58,50,24,62,38,56))):
        _room(g,x,y,z,w,h,d,MATS["C"] if i!=1 else MATS["S"])
        _fill(g,(x-2,y+h,z-2),(x+w+1,y+h+2,z+d+1),MATS["D"])
        _machines(g,x+7,x+w-7,y+3,z+8,max(3,(d-16)//6))
    for x in range(6,118,14):
        h=18+int((x/118)*60)
        _fill(g,(x,2,112),(x+6,h,121),MATS["B"])
        _fill(g,(x+2,h+1,113),(x+4,h+4,119),MATS["R"])
    for i in range(84):
        x=12+i; y=4+i//2; z=18+i//3
        _fill(g,(x,y,z),(x+5,y,z+7),MATS["M"]); _clear(g,(x,y+1,z),(x+5,y+4,z+7))
        if i%8==0: _fill(g,(x,y+1,z+2),(x+5,y+1,z+3),MATS["Y"])
    _fill(g,(18,2,18),(33,84,34),MATS["B"]); _clear(g,(22,5,22),(29,79,30))
    for y in range(8,80,10):
        _fill(g,(16,y,16),(35,y+2,36),MATS["R"]); _clear(g,(21,y,21),(30,y+3,31))
    _room(g,82,12,82,38,17,33,MATS["S"]); _fill(g,(64,18,90),(84,20,97),MATS["M"])
    for x,z,y in ((12,80,32),(42,56,58),(78,30,90)):
        _fill(g,(x,y,z),(x+20,y+5,z+14),MATS["R"]); _fill(g,(x+3,y+6,z+3),(x+17,y+8,z+11),MATS["L"])
    _fill(g,(28,38,76),(62,40,80),MATS["M"]); _fill(g,(56,66,52),(96,68,56),MATS["M"])
    _fill(g,(8,94,10),(119,96,14),MATS["R"])
    for x in (10,116): _fill(g,(x,2,11),(x+3,94,14),MATS["D"])
    return g

MODELS = {
    "vertical_foundry": vertical_foundry,
    "industrial_canyon": industrial_canyon,
    "terraced_megaforge": terraced_megaforge,
}

def load_models():
    return {name: fn() for name,fn in MODELS.items()}
