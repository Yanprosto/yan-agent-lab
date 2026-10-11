"""Compose already rendered block models; never synthesizes model imagery."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont
ROOT=Path(__file__).parent/'output'
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD=FONT.replace('.ttf','-Bold.ttf')
def font(n,bold=False): return ImageFont.truetype(BOLD if bold else FONT,n)
canvas=Image.new('RGB',(2100,1460),'#101b24'); d=ImageDraw.Draw(canvas)
d.text((48,30),'YAN / ГРУЗОВОЙ УЗЕЛ',font=font(36,True),fill='#eef2ef')
d.text((48,82),'Три пространственных варианта • реальные блоковые модели • участок 96 × 96',font=font(23),fill='#a9bac5')
items=[('well','01  КОЛОДЕЦ','Галереи вокруг пустоты · подвесная платформа'),('canyon','02  КАНЬОН','Два массива · мосты на разных отметках'),('shaft','03  ШАХТНЫЙ УЗЕЛ','Кольцевые ярусы · боковой машинный зал')]
for i,(key,title,desc) in enumerate(items):
    x=28+i*692
    d.rounded_rectangle((x,140,x+664,1360),radius=12,fill='#1a2934')
    d.text((x+22,162),title,font=font(29,True),fill='#f3c76e')
    d.text((x+22,210),desc,font=font(17),fill='#c2ced5')
    for name,top,h in [('overview',250,540),('cutaway',845,390)]:
        im=Image.open(ROOT/key/f'{name}.png').convert('RGBA'); im.thumbnail((640,h),Image.Resampling.LANCZOS)
        canvas.paste(im,(x+(664-im.width)//2,top+(h-im.height)//2),im)
    d.text((x+22,809),'РАЗРЕЗ / Z ≥ 46',font=font(20,True),fill='#a9bac5')
    report=json.loads((ROOT/key/'report.json').read_text())
    d.text((x+22,1260),f"{report['blocks']:,} блоков  •  высота {report['bounds'][1][1]+1}".replace(',',' '),font=font(23),fill='#eef2ef')
    d.text((x+22,1304),'Вход → 3 галереи: пути найдены*',font=font(20),fill='#84cba5')
d.text((48,1390),'* Геометрическая проверка с подъёмом на 1 блок. Механизмы декоративные; размещения в игре не было.',font=font(21),fill='#a9bac5')
canvas.save(ROOT/'comparison.jpg',quality=92)
