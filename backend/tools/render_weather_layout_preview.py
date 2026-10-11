"""Standalone design preview; no API, database, settings, or device changes."""
from datetime import date
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw
from app.services.display_renderer import _font, _to_four_colors, native_image_to_portrait

ROOT = Path(__file__).resolve().parents[2]
BLACK, WHITE, RED, YELLOW = '#111111', '#FFFFFF', '#C42B25', '#E0A000'


def main():
    data = json.loads((ROOT / 'docs/design/weather_mode_preview_20260915.json').read_text())
    days = data['days']
    assert len(days) == 7
    assert all((date.fromisoformat(v['date']) - date.fromisoformat(days[0]['date'])).days == i for i, v in enumerate(days))
    canvas = Image.new('RGB', (480, 800), WHITE)
    d = ImageDraw.Draw(canvas)

    def text(x, y, value, size=22, color=BLACK, bold=False, right=False):
        font = _font(size, bold=bold)
        if right:
            x -= d.textlength(value, font=font)
        box = d.textbbox((x, y), value, font=font)
        assert box[0] >= 0 and box[2] <= 480 and box[3] <= 800, (value, box)
        d.text((x, y), value, font=font, fill=color)

    def icon(x, y, kind, scale=1):
        def pt(a,b): return (round(x+a*scale), round(y+b*scale))
        def ellipse(a,b,c,e,fill,outline=BLACK):
            d.ellipse((*pt(a,b),*pt(c,e)),fill=fill,outline=outline,width=max(1,round(2*scale)))
        if kind != 'rain':
            cx,cy = (0,0) if kind == 'sun' else (-7,-7)
            for i in range(8):
                t=i*math.pi/4
                d.line([pt(cx+18*math.cos(t),cy+18*math.sin(t)),pt(cx+23*math.cos(t),cy+23*math.sin(t))],fill=BLACK,width=max(1,round(2*scale)))
            ellipse(cx-12,cy-12,cx+12,cy+12,YELLOW)
        if kind != 'sun':
            ellipse(-16,-2,8,20,WHITE)
            ellipse(-3,-12,23,18,WHITE)
            ellipse(12,-1,34,20,WHITE)
            d.rectangle((*pt(-4,1),*pt(21,18)),fill=WHITE)
            d.line([pt(-5,20),pt(23,20)],fill=BLACK,width=max(1,round(2*scale)))
        if kind == 'rain':
            for a in [-6,8,22]:
                d.line([pt(a,27),pt(a-4,34)],fill=BLACK,width=max(1,round(2*scale)))

    text(22, 15, data['city'], 38, bold=True)
    text(458, 29, '七日天气', 25, right=True)
    text(24, 68, '2026年9月15日 · 星期二', 18)
    d.line((24,102,456,102),fill=BLACK,width=2)
    text(24,117,'今天',25,bold=True)
    text(458,123,'09/15',19,right=True)
    icon(70,194,'partly',1.55)
    text(176,157,days[0]['text'],31,bold=True)
    text(173,200,'21~30℃',47,bold=True)
    text(177,263,'最低 / 最高气温',16)
    d.line((24,300,456,300),fill=BLACK,width=2)
    text(24,314,'日期',16)
    text(189,314,'天气',16)
    text(456,314,'最低~最高',16,right=True)
    for i, v in enumerate(days[1:]):
        y=345+i*62
        day=date.fromisoformat(v['date'])
        label='明天' if i==0 else '周'+'一二三四五六日'[day.weekday()]
        text(24,y,label,23,bold=True)
        text(24,y+30,day.strftime('%m/%d'),15)
        icon(134,y+20,v['icon'],0.66)
        text(183,y+10,v['text'],22,color=RED if v['icon']=='rain' else BLACK)
        text(456,y+10,f"{v['min']}~{v['max']}℃",25,right=True,bold=True)
        d.line((24,y+57,456,y+57),fill=BLACK,width=1)
    text(24,734,'预报获取：09/15 凌晨',16)
    text(24,765,'未来天气可能变化，请关注最新预报',16)
    native=_to_four_colors(canvas.transpose(Image.Transpose.ROTATE_90))
    portrait=native_image_to_portrait(native)
    out=ROOT/'docs/assets/weather_mode'
    out.mkdir(parents=True,exist_ok=True)
    for name,im in [('weather_7day_20260915_native.png',native),('weather_7day_20260915_portrait.png',portrait),('weather_7day_20260915_preview.png',portrait.resize((960,1600),Image.Resampling.NEAREST))]:
        path=out/name
        im.save(path)
        print(path)
    assert native.size == (800,480)
    assert len(native.getcolors(384001)) <= 4


if __name__ == '__main__':
    main()
