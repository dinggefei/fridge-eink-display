"""The approved 480x800 portrait weather layout, encoded in the screen palette."""
from datetime import timedelta
import math

from PIL import Image, ImageDraw
from app.services.display_renderer import _font, _fit_text, _to_four_colors, BLACK, WHITE, RED, YELLOW
from app.services.weather_forecast import LOCAL_ZONE, WeatherWeek


def _icon(draw, x, y, condition, scale=1):
    rain = any(word in condition for word in ('雨', '雷', '雪'))
    sunny = '晴' in condition
    cloudy = any(word in condition for word in ('云', '阴'))
    if not (rain or sunny or cloudy):
        draw.text((x-10,y-12),'—',font=_font(24),fill=BLACK)
        return
    def pt(a,b): return round(x+a*scale), round(y+b*scale)
    def ellipse(a,b,c,e,fill):
        draw.ellipse((*pt(a,b),*pt(c,e)),fill=fill,outline=BLACK,width=max(1,round(2*scale)))
    if sunny and not rain:
        cx,cy=(-7,-7) if cloudy else (0,0)
        for i in range(8):
            t=i*math.pi/4
            draw.line([pt(cx+18*math.cos(t),cy+18*math.sin(t)),pt(cx+23*math.cos(t),cy+23*math.sin(t))],fill=BLACK,width=max(1,round(2*scale)))
        ellipse(cx-12,cy-12,cx+12,cy+12,YELLOW)
    if rain or cloudy:
        ellipse(-16,-2,8,20,WHITE)
        ellipse(-3,-12,23,18,WHITE)
        ellipse(12,-1,34,20,WHITE)
        draw.rectangle((*pt(-4,1),*pt(21,18)),fill=WHITE)
        draw.line([pt(-5,20),pt(23,20)],fill=BLACK,width=max(1,round(2*scale)))
    if rain:
        for a in (-6,8,22):
            if '雪' in condition:
                draw.text(pt(a-4,21),'*',font=_font(max(8,round(14*scale))),fill=BLACK)
            else:
                draw.line([pt(a,27),pt(a-4,34)],fill=BLACK,width=max(1,round(2*scale)))


def render_weather_image(week: WeatherWeek) -> Image.Image:
    canvas=Image.new('RGB',(480,800),WHITE)
    d=ImageDraw.Draw(canvas)
    def text(x,y,value,size=22,color=BLACK,bold=False,right=False,width=432):
        font=_font(size,bold=bold)
        value=_fit_text(d,value,font=font,max_width=width)
        if right: x-=d.textlength(value,font=font)
        d.text((x,y),value,font=font,fill=color)
    def condition(v): return v.condition_text if v else '暂无预报'
    def temperature(v): return f'{v.temp_min}~{v.temp_max}℃' if v else '--'
    values={v.displayed_on:v for v in week.days}
    today=values.get(week.displayed_on)
    text(22,15,week.city,38,bold=True,width=250)
    text(458,29,'七日天气',25,right=True)
    text(24,68,week.displayed_on.strftime('%Y年%m月%d日')+' · 星期'+'一二三四五六日'[week.displayed_on.weekday()],18)
    d.line((24,102,456,102),fill=BLACK,width=2)
    text(24,117,'今天',25,bold=True)
    text(458,123,week.displayed_on.strftime('%m/%d'),19,right=True)
    _icon(d,70,194,condition(today),1.55)
    text(176,157,condition(today),31,bold=True,width=280)
    text(173,200,temperature(today),47,bold=True,width=283)
    text(177,263,'最低 / 最高气温',16)
    d.line((24,300,456,300),fill=BLACK,width=2)
    text(24,314,'日期',16)
    text(189,314,'天气',16)
    text(456,314,'最低~最高',16,right=True)
    for i in range(6):
        day=week.displayed_on+timedelta(days=i+1)
        v=values.get(day)
        y=345+i*62
        text(24,y,'明天' if i==0 else '周'+'一二三四五六日'[day.weekday()],23,bold=True)
        text(24,y+30,day.strftime('%m/%d'),15)
        label=condition(v)
        _icon(d,134,y+20,label,0.66)
        text(183,y+10,label,22,color=RED if any(w in label for w in ('雨','雪','雷')) else BLACK,width=120)
        text(456,y+10,temperature(v),25,right=True,bold=True,width=145)
        d.line((24,y+57,456,y+57),fill=BLACK,width=1)
    fetched=week.fetched_at.astimezone(LOCAL_ZONE).strftime('%m/%d %H:%M') if week.fetched_at else '--'
    text(24,734,f'预报获取：{fetched}',16)
    if week.delayed:
        text(456,734,'更新延迟' if week.days else '暂无有效预报',16,RED,right=True,width=130)
    text(24,765,'未来天气可能变化，请关注最新预报',16)
    return _to_four_colors(canvas.transpose(Image.Transpose.ROTATE_90))
