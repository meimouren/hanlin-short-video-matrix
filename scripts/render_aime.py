"""Rebuild the six-scene AIME sample from editable covers, narration and cues."""
import argparse
from bisect import bisect_right
from functools import lru_cache
import io
import json
import math
import os
from pathlib import Path
import subprocess
import wave

from PIL import Image, ImageChops, ImageDraw, ImageFont

from mix_demo import FFMPEG, add_music, ff

ASSETS = Path(__file__).resolve().parents[1] / "assets/aime"
W, H, FPS = 1080, 1920, 30
COVER, TAIL = .7, 1.45
L, R = 124, 956
WHITE, BLUE, RED = "#ffffff", "#156bb1", "#a41034"
INK, SOFT = "#102e4b", "#395872"
ICE, SKY, ROSE = "#f3faff", "#e2f3ff", "#ffedf2"
LINE, ROSELINE = "#bedcf0", "#f2bfd0"
ACCENT, BERRY = "#1681d4", "#ce2755"
LOGO = ASSETS / "logo.jpg"


@lru_cache(maxsize=2)
def font_file(bold):
    key = "HANLIN_CJK_BOLD" if bold else "HANLIN_CJK_REGULAR"
    supplied = os.environ.get(key)
    if supplied:
        path = Path(supplied)
        if not path.is_file():
            raise ValueError(f"{key} does not point to a font: {path}")
        return path
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    suffix = "Bold" if bold else "Regular"
    candidates = (
        windows / f"HarmonyOS_Sans_SC_{suffix}.ttf",
        windows / ("msyhbd.ttc" if bold else "msyh.ttc"),
        Path(f"/usr/share/fonts/opentype/noto/NotoSansCJK-{suffix}.ttc"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError(f"Set {key} to a local Simplified Chinese font (TTF, OTF or TTC)")


@lru_cache(maxsize=None)
def font(size, bold=False):
    return ImageFont.truetype(str(font_file(bold)), size)


def text(d, x, y, line, size, color=INK, bold=False, anchor="lt"):
    d.text((x, y), line, font=font(size, bold), fill=color, anchor=anchor)


def box(d, coords, fill, border=None, radius=24):
    d.rounded_rectangle(coords, radius=radius, fill=fill, outline=border, width=2)


def line(d, ab, color=LINE, width=4):
    d.line(ab, fill=color, width=width)


def arrow(d, a, b, color=BLUE):
    line(d, (*a, *b), color, 5)
    radians = math.atan2(b[1] - a[1], b[0] - a[0])
    tips = [(b[0] - 17 * math.cos(radians + angle), b[1] - 17 * math.sin(radians + angle))
            for angle in (-.62, .62)]
    d.polygon([b, *tips], fill=color)


def stamp(seconds):
    ms=round(seconds*1000)
    return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"


SEQUENCE = [
    "孩子从 AMC 10 或 12 晋级到 AIME 了，",
    "这次去哪儿考？",
    "您先翻一下当时报名的记录，考点找原报名渠道查。",
    "AMC-China 报的，预计十二月十五号能选线下考点。",
    "经翰林报这条渠道的，还是在翰林考。",
    "阿思丹报的，回原报名入口看考点通知。",
    "二月七号，大年初二，",
    "两边下午一点开考。",
    "接送记一下，AMC-China 四点结束，",
    "阿思丹四点十分。",
    "阿思丹分两段。",
    "前八题，九十分钟。",
    "交卷前检查好，交了就不能再看、也不能改。",
    "歇十分钟，后七题再做九十分钟。",
    "AMC-China 的线下机考和三百五十元报名费都暂定。",
    "阿思丹的费用也待定，通知上写三百八十元人民币，或者四百四十九港币。",
    "要两边的对照表，",
    "私信我 A-I-M-E。",
]
CAPTION_BREAKS = {
    2: ("考点找原报名渠道查",),
    3: ("预计",),
    12: ("交了就",),
    13: ("后七题",),
    14: ("和三百五十元",),
    15: ("通知上写", "或者四百四十九港币"),
}


def ease(seconds):
    return 1 - (1 - min(1, max(0, seconds / .64))) ** 3


def title(d, primary, secondary):
    size = 82
    while font(size, True).getlength(primary) > R - L - 10:
        size -= 1
    text(d, L, 337 + (82-size)//2, primary, size, INK, True)
    text(d, L + 3, 445, secondary, 38, SOFT)


@lru_cache(maxsize=1)
def wordmark():
    logo = Image.open(LOGO).convert("RGB")
    logo_box = ImageChops.difference(logo, Image.new("RGB", logo.size, WHITE)).convert("L").point(lambda p: 255 if p > 34 else 0).getbbox()
    logo = logo.crop(logo_box)
    logo.thumbnail((292, 48), Image.Resampling.LANCZOS)
    return logo


@lru_cache(maxsize=1)
def canvas():
    image = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(image)
    d.rectangle((0, 1123, W, 1535), fill="#f9fcff")
    line(d, (L, 288, R, 288), LINE, 2)
    image.paste(wordmark(), (L, 213))
    text(d, R, 228, "AIME 考务", 36, BLUE, True, "rm")
    return image


def progress_tabs(d, index):
    active = 0 if index <= 5 else 1 if index <= 13 else 2 if index <= 15 else 3
    for n, label in enumerate(("考点", "考试时间", "费用")):
        x = L + n*282
        picked = n == active or active == 3
        color = BLUE if picked else SOFT
        text(d, x+134, 1451, label, 34, color, True, "mm")
        line(d, (x,1489,x+268,1489), ACCENT if picked else LINE, 6 if picked else 3)


def opening(d, i, p):
    title(d, "晋级 AIME 后去哪儿考？", "2027 美国数学邀请赛")
    box(d, (L, 570, R, 942), ICE, LINE, 40)
    for x, label, caption, color in ((322, "AMC", "10 或 12", BLUE), (758, "AIME", "本次考试", RED)):
        d.rounded_rectangle((x - 137, 651, x + 137, 860), 34, fill=WHITE)
        text(d, x, 727, label, 83, color, True, "mm")
        text(d, x, 823, caption, 34, INK, True, "mm")
    follow = 1 if i > 1 else p
    arrow(d, (474, 761), (474 + 130 * max(.04, follow), 761), ACCENT)
    if i >= 2:
        y = 1049 + round((1-p) * 25)
        box(d, (L, y, R, y + 232), BLUE, radius=26)
        text(d, L+40, y+43, "翻一下当时报名的记录", 53, WHITE, True)
        text(d, L+40, y+135, "考点从原报名渠道查", 43, WHITE)
    else:
        text(d, 540, 1090, "先找到当时的报名渠道", 52, BLUE, True, "mm")


def venue(d, i, p):
    title(d, "考点从哪里查？", "顺着原 AMC 报名记录找")
    box(d, (296, 551, 784, 644), BLUE, radius=24)
    text(d, 540, 596, "原 AMC 报名记录", 44, WHITE, True, "mm")
    line(d, (540, 643, 540, 705), LINE, 5)
    for left, right, color, shade, border, label, enter in (
        (L, 529, BLUE, SKY, LINE, "AMC-China", 3),
        (551, R, RED, ROSE, ROSELINE, "阿思丹", 5),
    ):
        cx = (left + right) / 2
        reach = 1 if i > enter else p if i == enter else .04
        point = 540 + (cx-540)*max(.04, reach)
        active = i >= enter
        line(d, (540, 705, point, 705), color if active else LINE, 5)
        if reach > .75:
            arrow(d, (cx, 705), (cx, 768), color)
        box(d, (left, 790, right, 1273), shade if active else ICE, border if active else LINE, 30)
        text(d, cx, 848, label, 50, color if active else SOFT, True, "mm")
        line(d, (left + 32, 916, right - 32, 916), border if active else LINE, 3)
        if enter == 3:
            text(d, cx, 966, "12 月 15 日", 50, BLUE, True, "mm")
            text(d, cx, 1032, "预计可选线下考点", 35, INK, True, "mm")
            if i >= 4:
                box(d, (left+22, 1104, right-22, 1239), WHITE, radius=20)
                text(d, cx, 1141, "经翰林报考", 32, SOFT, False, "mm")
                text(d, cx, 1201, "继续在翰林考", 36, BLUE, True, "mm")
        elif active:
            text(d, cx, 985, "回原报名入口", 44, RED, True, "mm")
            text(d, cx, 1055, "查看考点通知", 43, INK, True, "mm")


def schedule(d, i, p):
    title(d, "两边几点结束？", "北京时间 · 2027 年 2 月 7 日 · 大年初二")
    start_x, width = 167, 746
    for k, (name, color, shade, border, end, minutes, cue) in enumerate((
        ("AMC-China", BLUE, SKY, LINE, "16:00", 180, 8),
        ("阿思丹", RED, ROSE, ROSELINE, "16:10", 190, 9),
    )):
        y = 574 + k*292
        box(d, (L, y, R, y+258), shade, border, 28)
        text(d, start_x, y+30, name, 40, color, True)
        if i >= 7:
            finish = i >= cue
            text(d, start_x, y+93, "13:00", 65, INK, True)
            text(d, R-43, y+93, end if finish else "待看结束时间", 65 if finish else 32, color if finish else SOFT, True, "rt")
            line(d, (start_x, y+208, start_x+width, y+208), border, 8)
            bar = width*minutes/190*(p if i == cue else 1)
            if finish:
                line(d, (start_x, y+208, start_x+bar, y+208), color, 9)
                if i == 9 and k == 1:
                    cap = start_x + width*180/190
                    if start_x + bar > cap:
                        line(d, (cap, y+208, start_x+bar, y+208), BERRY, 13)
            d.ellipse((start_x-7,y+201,start_x+7,y+215), fill=color)
    if i >= 9:
        box(d, (L, 1167, R, 1289), WHITE, ROSELINE, 22)
        text(d, 540, 1228, "阿思丹晚 10 分钟结束", 49, RED, True, "mm")


def sections(d, i, p):
    title(d, "阿思丹的分段作答", "交卷后换下一段，前段答案会锁定")
    a, b, c, e = L, 469, 611, R
    panels = ((a,b,"前 8 题","90 分钟",BLUE,SKY,11),
              (b+12,c-12,"休息","10 分钟",RED,ROSE,13),
              (c,e,"后 7 题","90 分钟",BLUE,SKY,13))
    for left,right,words,duration,color,shade,cue in panels:
        cx = (left + right) / 2
        active = i >= cue
        box(d, (left, 596, right, 872), shade if active else ICE, LINE, 21)
        text(d, cx, 682, words, 51 if right-left>150 else 36, color if active else SOFT, True, "mm")
        if active:
            text(d, cx, 787, duration, 45 if right-left>150 else 28, color, True, "mm")
    bar_x, bar_w = L+14, R-L-28
    line(d, (bar_x, 926, bar_x+bar_w, 926), LINE, 8)
    for left,right,color,cue in ((0,90,BLUE,11),(90,100,BERRY,13),(100,190,BLUE,13)):
        if i >= cue:
            x1 = bar_x+bar_w*left/190
            x2 = x1+bar_w*(right-left)/190*(p if i == cue else 1)
            line(d, (x1,926,x2,926), color, 11)
    if i >= 12:
        y = 1009 + round((1-p)*20) if i == 12 else 1009
        box(d, (L,y,R,y+258), ROSE, ROSELINE, 24)
        d.arc((L+51,y+57,L+122,y+136), 179, 361, fill=RED, width=8)
        box(d, (L+37,y+107,L+136,y+198), RED, radius=14)
        d.ellipse((L+77,y+137,L+96,y+156), fill=WHITE)
        line(d, (L+86,y+151,L+86,y+170), WHITE, 5)
        text(d, L+177, y+64, "前 8 题交卷前检查好", 49, INK, True)
        text(d, L+179, y+153, "交了不能回看，也不能修改", 42, RED, True)


def fees(d, i, p):
    title(d, "两边的费用都还未定", "付款前，查原渠道的最新缴费通知")
    for left,right,color,shade,border,name,reveal in (
        (L,529,BLUE,SKY,LINE,"AMC-China",14), (551,R,RED,ROSE,ROSELINE,"阿思丹",15)
    ):
        cx = (left+right)/2
        active = i >= reveal
        box(d,(left,568,right,1270),shade if active else ICE,border if active else LINE,28)
        text(d,cx,639,name,48,color if active else SOFT,True,"mm")
        line(d,(left+31,703,right-31,703),border if active else LINE,3)
        if active:
            y = 788 + round((1-p)*21) if i == reveal else 788
            text(d,cx,y+18,"350" if reveal == 14 else "380",94,color,True,"mm")
            text(d,cx,884,"元人民币",38,INK,True,"mm")
            if reveal == 14:
                box(d,(left+44,967,right-44,1047),WHITE,radius=17)
                text(d,cx,1007,"报名费暂定",36,BLUE,True,"mm")
                text(d,cx,1132,"线下机考也暂定",36,BLUE,True,"mm")
            else:
                text(d,cx,974,"或 449 港币",47,RED,True,"mm")
                box(d,(left+44,1086,right-44,1166),WHITE,radius=17)
                text(d,cx,1126,"费用待定",37,RED,True,"mm")


def recap(d, i, p):
    title(d, "出发前核对三件事", "2027 年 2 月 7 日 · 大年初二")
    for y,name,color,shade,border,where,when,cost in (
        (545,"AMC-China",BLUE,SKY,LINE,"12 月 15 日预计可选考点","13:00–16:00","350 元暂定"),
        (821,"阿思丹",RED,ROSE,ROSELINE,"原报名入口查考点","13:00–16:10","380 元或 449 港币待定"),
    ):
        box(d,(L,y,R,y+245),shade,border,23)
        text(d,L+29,y+26,name,43,color,True)
        text(d,R-31,y+39,where,30,INK,True,"rt")
        text(d,L+31,y+124,when,54,INK,True)
        text(d,R-31,y+149,cost,30,color,True,"rt")
    if i == 17:
        y=1141+round((1-p)*24)
        box(d,(L,y,R,y+173),BLUE,radius=23)
        text(d,L+33,y+37,"私信「AIME」",51,WHITE,True)
        text(d,L+35,y+112,"领取两渠道对照表",35,WHITE)


def paint(index, progress, caption):
    image = canvas().copy()
    d = ImageDraw.Draw(image)
    if index <= 2:
        opening(d, index, progress)
    elif index <= 5:
        venue(d, index, progress)
    elif index <= 9:
        schedule(d, index, progress)
    elif index <= 13:
        sections(d, index, progress)
    elif index <= 15:
        fees(d, index, progress)
    else:
        recap(d, index, progress)
    progress_tabs(d, index)
    if caption:
        size = 49
        while font(size,True).getlength(caption) > 778 and size > 36:
            size -= 1
        if font(size,True).getlength(caption) > 778:
            raise ValueError(f"手机字幕过宽，检查词级时间锚点：{caption}")
        box(d,(L,1546,R,1652),INK,radius=18)
        text(d,540,1599,caption,size,WHITE,True,"mm")
    return image


def first_frame(path):
    with Image.open(path) as d:
        if not .735 < d.width/d.height < .765:
            raise ValueError("独立封面应为 3:4")
        art = d.convert("RGB").resize((R-L,round((R-L)*d.height/d.width)),Image.Resampling.LANCZOS)
    image = Image.new("RGB", (W,H), "#f1f9ff")
    panel = ImageDraw.Draw(image)
    panel.rectangle((L-2, 0, R+1, H), fill=WHITE)
    y=(H-art.height)//2
    image.paste(art,(L,y))
    image.paste(wordmark(), (L, 213))
    text(panel,R,238,"两渠道考务",36,BLUE,True,"rm")
    line(panel,(L,296,R,296),LINE,2)
    return image


def voice_data(audio, alignment):
    doc = json.loads(alignment.read_text(encoding="utf-8-sig"))
    with wave.open(str(audio)) as wav:
        duration = wav.getnframes()/wav.getframerate()
    spoken = doc["cues"]
    if len(spoken)!=len(SEQUENCE) or [c["text"] for c in spoken]!=SEQUENCE:
        raise ValueError("配音时间表与定稿的 18 句不一致")
    if not all(0 <= c["start"] < c["end"] <= duration+.03 for c in spoken):
        raise ValueError("配音时间锚点不在音频内")
    starts = [float(c["start"])+COVER for c in spoken]
    if starts != sorted(set(starts)):
        raise ValueError("配音时间必须递增")
    captions = []
    for c in doc.get("captions", []):
        captions.append((float(c["start"])+COVER,float(c["end"])+COVER,c["text"]))
    if not captions:
        for i,c in enumerate(spoken):
            full = c["text"]
            tokens = CAPTION_BREAKS.get(i, ())
            offsets = [0,*[full.index(token) for token in tokens],len(full)]
            times = [float(c["start"]),*[float(c["anchors"][token]) for token in tokens],float(c["end"])]
            for n in range(len(offsets)-1):
                words=full[offsets[n]:offsets[n+1]].strip().strip("，")
                captions.append((times[n]+COVER,times[n+1]+COVER,words))
    if not captions or any(not COVER <= a < b <= COVER + duration + .03 for a,b,_ in captions):
        raise ValueError("字幕时间必须在有效口播区间内")
    if any(a[1] > b[0] + .005 for a,b in zip(captions,captions[1:])):
        raise ValueError("字幕必须按顺序排列且不得重叠")
    return starts, captions, COVER+duration


def jpeg(image):
    sink = io.BytesIO()
    image.save(sink, format="JPEG", quality=95, subsampling=0)
    return sink.getvalue()


def render(audio, alignment, cover, output, music):
    starts,captions,voice_end=voice_data(audio, alignment)
    caption_starts=[c[0] for c in captions]
    frames = math.ceil((voice_end+TAIL)*FPS)
    cover_frame = first_frame(cover)
    cover_stream = jpeg(cover_frame)
    output.mkdir(parents=True)
    with Image.open(cover) as artwork:
        artwork.convert("RGB").save(output / "独立封面.png")
    print(f"Encoding {frames} frames at {W}×{H}", flush=True)
    encoder = subprocess.Popen([str(FFMPEG),"-nostdin","-hide_banner","-v","error","-y",
        "-f","image2pipe","-framerate",str(FPS),"-c:v","mjpeg","-i","-","-an",
        "-c:v","libx264","-preset","veryfast","-crf","16","-threads","4",
        "-pix_fmt","yuv420p","-movflags","+faststart",str(output/"画面.mp4")],stdin=subprocess.PIPE)
    last_key, last_bytes = None, None
    with encoder.stdin:
        for frame in range(frames):
            if frame and frame % 300 == 0:
                print(f"Encoded {frame}/{frames} frames", flush=True)
            sec=frame/FPS
            if frame<round(COVER*FPS):
                encoder.stdin.write(cover_stream)
                continue
            i=max(0,bisect_right(starts,sec)-1)
            k=bisect_right(caption_starts,sec)-1
            caption=captions[k][2] if k>=0 and sec<captions[k][1]+.035 else ""
            p=ease(sec-starts[i])
            key=(i,p,caption)
            if key!=last_key:
                last_key,last_bytes=key,jpeg(paint(i,p,caption))
            encoder.stdin.write(last_bytes)
    if encoder.wait():
        raise RuntimeError("画面编码失败")
    synced=output/"配音同轴.wav"
    ff("-i",audio,"-af",f"adelay={round(COVER*1000)},apad=pad_dur=2","-ac",1,"-ar",24000,synced)
    dest=output/"AIME-纯动画样片.mp4"
    add_music(output/"画面.mp4", dest, synced, frames/FPS, music)
    ff("-i",dest,"-frames:v",1,"-q:v",2,output/"视频首帧.jpg")
    txt=[f"{n}\n{stamp(a)} --> {stamp(b)}\n{caption}" for n,(a,b,caption) in enumerate(captions,1)]
    (output/"字幕.srt").write_text("\n\n".join(txt)+"\n",encoding="utf-8")
    (output/"声画时间.json").write_text(json.dumps({"frames":frames,"spoken_seconds":voice_end-COVER,"anchors":starts,"captions":captions},
                                             ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, default=ASSETS/"narration.wav")
    parser.add_argument("--timing", type=Path, default=ASSETS/"timing.json")
    parser.add_argument("--cover", type=Path, default=ASSETS/"cover.png")
    parser.add_argument("--output", type=Path, default=Path("preview-aime"))
    parser.add_argument("--music", choices=("mallet", "plucked"), default="mallet")
    opts = parser.parse_args()
    provided = [opts.audio, opts.timing, opts.cover, LOGO]
    missing = [path for path in provided if not path.is_file()]
    if missing:
        parser.error("Missing input files: " + ", ".join(map(str, missing)))
    if opts.output.exists():
        parser.error("Choose a new output directory so existing media stays intact")
    for bold in (False, True):
        font_file(bold)
    render(opts.audio, opts.timing, opts.cover, opts.output, opts.music)
