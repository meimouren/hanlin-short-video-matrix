"""真人 IP 动态圆窗样板渲染入口（兼容独立离线演示与真实录播净素材输入）。"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.dont_write_bytecode = True

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCRIPTS_DIR = Path(__file__).resolve().parent
ASSETS = SCRIPTS_DIR.parent / "assets/aime"
STAGE_HTML = SCRIPTS_DIR / "stage_ip_pip_demo.html"

sys.path.insert(0, str(SCRIPTS_DIR))
from visual_engine import (  # noqa: E402
    DEFAULT_FPS,
    DEFAULT_SR,
    composite_dynamic_circle_pip,
    extract_transparent_logo,
    logo_data_uri,
    mix_audio_with_bgm_and_sfx,
    render_canvas_stage,
    resolve_ffmpeg,
    stamp_logo_on_cover,
    verify_and_make_sheets,
)

COVER_SEC = 0.70
DEMO_CLIP_SEC = 15.30
DEMO_CENTERS = ((828, 304), (252, 304), (828, 304), (252, 1086))
DEMO_STARTS = [0.70, 1.85, 3.05, 4.40, 5.75, 7.10, 8.20, 9.10, 10.25, 11.50, 12.60, 13.80, 14.90]
DEMO_MOVE_SECS = (4.40, 9.10, 12.60)
DEMO_CAPTIONS = [
    [0.70, 1.85, "你如果AMC比完了"],
    [1.85, 3.05, "取得了一个不错的成绩"],
    [3.05, 4.40, "接下来怎么衔接？"],
    [4.40, 5.75, "10-11年级拿到荣誉"],
    [5.75, 7.10, "常因身份限制没法再比"],
    [7.10, 8.20, "难道等12年级再用？"],
    [8.20, 9.10, "不是啊！"],
    [9.10, 10.25, "等到假期的时候"],
    [10.25, 11.50, "把数学竞赛荣誉用起来"],
    [11.50, 12.60, "去申请顶尖数学夏校"],
    [12.60, 13.80, "把数学学术能力延伸开来"],
    [13.80, 15.85, "竞赛加夏校放大升学优势"],
]
DEMO_SFX = [
    (0.70, "chime"),
    (3.05, "pop"),
    (4.40, "chime"),
    (8.20, "stamp"),
    (9.10, "chime"),
    (11.50, "pop"),
    (12.60, "chime"),
    (14.90, "pop"),
]


def _load_font(size, bold=False):
    candidates = []
    if bold:
        env_b = os.environ.get("HANLIN_CJK_BOLD")
        if env_b:
            candidates.append(env_b)
        win_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates.extend([
            str(win_fonts / "msyhbd.ttc"),
            str(win_fonts / "simhei.ttf"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ])
    else:
        env_r = os.environ.get("HANLIN_CJK_REGULAR")
        if env_r:
            candidates.append(env_r)
        win_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates.extend([
            str(win_fonts / "msyh.ttc"),
            str(win_fonts / "simhei.ttf"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/System/Library/Fonts/PingFang.ttc",
        ])
    for cand in candidates:
        if cand and Path(cand).is_file():
            return ImageFont.truetype(cand, size)
    return ImageFont.load_default()


def _srt_stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _build_demo_cover(logo_jpg: Path, speaker: str, out_cover_png: Path, work_dir: Path):
    """生成 1080×1440 白/蓝/红示范独立封面，并用外框连通透明 Logo 精确贴标。"""
    raw_cover = work_dir / "raw_demo_cover.png"
    logo_png = work_dir / "transparent_logo.png"
    extract_transparent_logo(logo_jpg, logo_png)

    im = Image.new("RGB", (1080, 1440), "#FFFFFF")
    draw = ImageDraw.Draw(im)

    # Top header divider + speaker badge on right (left 40..490 kept pure white for logo stamp)
    draw.line((44, 154, 1036, 154), fill="#BFDFF5", width=3)
    f_badge = _load_font(28, bold=True)
    badge = f"{speaker} · 直播精讲"
    bw = int(f_badge.getlength(badge)) + 52
    bx = 1036 - bw
    draw.rounded_rectangle((bx, 64, 1036, 124), radius=30, fill="#E2F3FF", outline="#BFDFF5", width=2)
    draw.text((bx + bw // 2, 94), badge, font=f_badge, fill="#156BB1", anchor="mm")

    # Main hero title
    f_tag = _load_font(30, bold=True)
    draw.rounded_rectangle((48, 200, 396, 260), radius=30, fill="#FFEDF2", outline="#F2C3D1", width=2)
    draw.text((222, 230), "竞赛规划 · 家长必看", font=f_tag, fill="#A41034", anchor="mm")

    draw.text((48, 294), "AMC 拿奖后", font=_load_font(94, bold=True), fill="#102E4B")
    draw.text((48, 412), "下一步怎么衔接？", font=_load_font(86, bold=True), fill="#156BB1")

    # Center visual comparison card (left: bottleneck vs right: holiday summer school)
    draw.rounded_rectangle((48, 560, 1032, 1140), radius=34, fill="#F4FAFF", outline="#BFDFF5", width=3)
    draw.rounded_rectangle((84, 608, 514, 920), radius=24, fill="#FFEDF2", outline="#F2C3D1", width=2)
    draw.text((114, 638), "常见卡点", font=_load_font(30, bold=True), fill="#A41034")
    draw.text((114, 700), "高一高二拿奖后\n干等 12 年级再用？", font=_load_font(38, bold=True), fill="#102E4B")
    draw.rounded_rectangle((114, 834, 484, 892), radius=14, fill="#A41034")
    draw.text((299, 863), "别浪费黄金假期!", font=_load_font(30, bold=True), fill="#FFFFFF", anchor="mm")

    draw.rounded_rectangle((566, 608, 996, 920), radius=24, fill="#156BB1")
    draw.text((596, 638), "正确接力方案", font=_load_font(30, bold=True), fill="#E2F3FF")
    draw.text((596, 700), "假期立刻申请\n顶尖数学夏校", font=_load_font(40, bold=True), fill="#FFFFFF")
    draw.rounded_rectangle((596, 834, 966, 892), radius=14, fill="#FFFFFF")
    draw.text((781, 863), "学术优势持续放大 ✓", font=_load_font(28, bold=True), fill="#156BB1", anchor="mm")

    # Presenter circular avatar preview inside cover card
    cx, cy, rr = 220, 1026, 78
    draw.ellipse((cx - rr - 6, cy - rr - 6, cx + rr + 6, cy + rr + 6), fill="#1681D4")
    draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill="#E2F3FF")
    draw.ellipse((cx - 26, cy - 42, cx + 26, cy + 10), fill="#156BB1")
    draw.chord((cx - 48, cy + 12, cx + 48, cy + 88), start=180, end=360, fill="#156BB1")
    draw.text((334, 976), "8x 超采样动态圆窗 + 白蓝红知识图解", font=_load_font(34, bold=True), fill="#102E4B")
    draw.text((334, 1034), "不遮挡重点图表 · 108 BPM 轻快拨弦", font=_load_font(28, bold=False), fill="#395872")

    # Bottom footer band
    draw.rounded_rectangle((48, 1188, 1032, 1344), radius=28, fill="#102E4B")
    draw.text((540, 1244), "真人出镜示范样板 · 替换 --clip 即刻套用", font=_load_font(36, bold=True), fill="#FFFFFF", anchor="mm")
    draw.text((540, 1300), "124px 侧边安全留白 · 3:4 独立封面贴标标准", font=_load_font(26, bold=False), fill="#7FD1FF", anchor="mm")

    im.save(raw_cover)
    stamp_logo_on_cover(raw_cover, logo_png, out_cover_png, size=(1080, 1440), logo_w=430, dest=(44, 38))


def _synthesize_demo_media(src_wav: Path, work_dir: Path, dur_sec: float, fps: int, ff: str):
    """生成带口播波形律动的 480×480 示范说话人视频与裁剪人声音轨。"""
    speaker_wav = work_dir / "demo_speech.wav"
    subprocess.check_call([
        ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-i", str(src_wav), "-t", f"{dur_sec:.3f}", "-vn", "-ac", "1", "-ar", str(DEFAULT_SR), str(speaker_wav),
    ])

    with wave.open(str(speaker_wav), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    total_frames = round(dur_sec * fps)
    hop = max(1, len(pcm) // total_frames)

    demo_mp4 = work_dir / "demo_speaker.mp4"
    cmd = [
        ff, "-y", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", "480x480", "-framerate", str(fps), "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        "-pix_fmt", "yuv420p", str(demo_mp4),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    font_tag = _load_font(28, bold=True)

    # Static background gradient
    yy, xx = np.indices((480, 480), dtype=np.float32)
    dist = np.sqrt((xx - 240.0) ** 2 + (yy - 230.0) ** 2) / 280.0
    bg_arr = np.zeros((480, 480, 3), dtype=np.float32)
    bg_arr[..., 0] = np.clip(232 - 38 * dist, 180, 245)
    bg_arr[..., 1] = np.clip(245 - 24 * dist, 210, 252)
    bg_arr[..., 2] = 255.0
    base_bg = Image.fromarray(bg_arr.astype(np.uint8), "RGB")

    for idx in range(total_frames):
        seg = pcm[idx * hop:(idx + 1) * hop]
        rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
        amp = min(1.0, rms * 7.5)
        bob = int(round(3.0 * np.sin(idx * 0.14)))

        frame = base_bg.copy()
        d = ImageDraw.Draw(frame, "RGBA")
        # Voice pulse halos around presenter
        for r_base, alpha in ((145, 55), (175, 32)):
            rr = r_base + int(amp * 22)
            d.ellipse((240 - rr, 232 - rr, 240 + rr, 232 + rr), outline=(21, 107, 177, alpha), width=4)
        # Presenter shoulders & jacket
        d.chord((112, 276 + bob, 368, 492 + bob), start=180, end=360, fill=(21, 107, 177, 255))
        d.polygon([(205, 290 + bob), (275, 290 + bob), (240, 364 + bob)], fill=(255, 255, 255, 235))
        # Neck & head
        d.rectangle((222, 246 + bob, 258, 298 + bob), fill=(246, 212, 186, 255))
        d.ellipse((178, 126 + bob, 302, 260 + bob), fill=(250, 220, 196, 255))
        # Hair
        d.chord((174, 118 + bob, 306, 214 + bob), start=180, end=360, fill=(22, 42, 68, 255))
        # Glasses + friendly smile responding subtly to audio energy
        d.rounded_rectangle((196, 178 + bob, 232, 202 + bob), radius=6, outline=(16, 46, 75, 230), width=3)
        d.rounded_rectangle((248, 178 + bob, 284, 202 + bob), radius=6, outline=(16, 46, 75, 230), width=3)
        d.line((232, 190 + bob, 248, 190 + bob), fill=(16, 46, 75, 230), width=3)
        mouth_h = 4 + int(amp * 9)
        d.ellipse((226, 224 + bob - mouth_h // 2, 254, 224 + bob + mouth_h // 2 + 3), fill=(164, 16, 52, 210))

        # Mini equalizer strip at bottom of square frame
        for b in range(7):
            bh = 10 + int(amp * 28 * (0.5 + 0.5 * abs(np.sin(idx * 0.25 + b))))
            bx = 186 + b * 16
            d.rounded_rectangle((bx, 428 - bh, bx + 9, 434), radius=4, fill=(22, 129, 212, 210))
        d.text((240, 456), "IP PIP DEMO", font=font_tag, fill=(21, 107, 177, 190), anchor="mm")
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("合成示范说话人视频失败")
    return demo_mp4, speaker_wav


def _probe_video(mp4_path: Path):
    cap = cv2.VideoCapture(str(mp4_path))
    assert cap.isOpened(), f"无法读取输入视频: {mp4_path}"
    w = round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or DEFAULT_FPS
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return w, h, float(frames) / float(fps)


def _parse_crop(raw_crop: str, w: int, h: int):
    if raw_crop:
        parts = [int(x.strip()) for x in raw_crop.split(",")]
        if len(parts) == 3:
            s, cx, cy = parts
            return (s, s, cx, cy)
        if len(parts) == 4:
            return tuple(parts)
        raise ValueError("--crop 格式应为 'size,x,y' 或 'w,h,x,y'")
    size = max(120, int(min(w, h) * 0.44) // 2 * 2)
    cx = max(0, (w - size) // 2)
    cy = max(0, min(h - size, int(h * 0.14)))
    return (size, size, cx, cy)


def _load_clip_timing(timing_path: Path, cover_sec: float, clip_dur: float):
    doc = json.loads(timing_path.read_text(encoding="utf-8-sig"))
    raw_starts = doc.get("starts")
    if isinstance(raw_starts, list) and len(raw_starts) >= 2:
        starts = [round(float(s) + cover_sec, 3) for s in raw_starts]
    elif "cues" in doc and doc["cues"]:
        cues = doc["cues"]
        raw = [float(c["start"]) for c in cues]
        starts = [round(raw[min(len(raw) - 1, i)] + cover_sec, 3) for i in range(13)]
    else:
        starts = [round(cover_sec + clip_dur * i / 13.0, 3) for i in range(13)]

    while len(starts) < 13:
        last = starts[-1] if starts else cover_sec
        step = max(0.25, (cover_sec + clip_dur - last) / max(1, 14 - len(starts)))
        starts.append(round(min(cover_sec + clip_dur - 0.10, last + step), 3))
    starts = starts[:13]

    captions = []
    if doc.get("captions"):
        for item in doc["captions"]:
            if len(item) >= 3:
                captions.append([round(float(item[0]) + cover_sec, 3), round(float(item[1]) + cover_sec, 3), str(item[2])])
    elif doc.get("cues"):
        for c in doc["cues"]:
            txt = str(c.get("text", "")).strip()
            if txt:
                captions.append([round(float(c["start"]) + cover_sec, 3), round(float(c["end"]) + cover_sec, 3), txt])

    move_secs = doc.get("move_secs") or [starts[3], starts[7], starts[10]]
    centers = tuple(tuple(c) for c in doc.get("centers", DEMO_CENTERS))
    sfx_events = [(round(float(t) + cover_sec, 3), k) for t, k in doc.get("sfx_events", [])] or [
        (starts[0], "chime"),
        (starts[3], "chime"),
        (starts[7], "chime"),
        (starts[10], "chime"),
    ]
    return starts, captions, move_secs, centers, sfx_events, doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="新建输出目录")
    parser.add_argument("--clip", type=Path, help="可选：真实老师原声净素材 .mp4（留空则运行内置离线圆窗示范）")
    parser.add_argument("--timing", type=Path, help="可选：时间轴 JSON（或 clip_lecture.py 生成的 净素材时间轴.json）")
    parser.add_argument("--cover", type=Path, help="可选：3:4 独立封面图片")
    parser.add_argument("--stamp-logo", action="store_true", help="对传入的 --cover 左上角自动贴合透明官方 Logo")
    parser.add_argument("--logo", type=Path, default=ASSETS / "logo.jpg", help="官方白底 Logo 原图")
    parser.add_argument("--crop", help="可选：说话人正方裁切框 'size,x,y' 或 'w,h,x,y'")
    parser.add_argument("--speaker", default="主讲老师", help="页眉及小圆窗名牌显示名称")
    parser.add_argument("--music", choices=("plucked", "mallet"), default="plucked")
    args = parser.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ff = resolve_ffmpeg()
    cover_frames = round(COVER_SEC * DEFAULT_FPS)

    with tempfile.TemporaryDirectory(prefix="hanlin-ip-pip-") as tmp:
        work_dir = Path(tmp)
        cover_out = out_dir / "独立封面.png"
        if args.cover:
            src_cover = args.cover.resolve(strict=True)
            if args.stamp_logo:
                logo_png = work_dir / "transparent_logo.png"
                extract_transparent_logo(args.logo.resolve(strict=True), logo_png)
                stamp_logo_on_cover(src_cover, logo_png, cover_out, size=(1080, 1440))
            else:
                Image.open(src_cover).convert("RGB").resize((1080, 1440), Image.Resampling.LANCZOS).save(cover_out)
        else:
            _build_demo_cover(args.logo.resolve(strict=True), args.speaker, cover_out, work_dir)

        meta = {}
        if args.clip:
            speaker_mp4 = args.clip.resolve(strict=True)
            src_w, src_h, clip_dur = _probe_video(speaker_mp4)
            crop_box = _parse_crop(args.crop, src_w, src_h)
            speech_wav = work_dir / "speech.wav"
            subprocess.check_call([
                ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
                "-i", str(speaker_mp4), "-vn", "-ac", "1", "-ar", str(DEFAULT_SR), str(speech_wav),
            ])
            if args.timing:
                starts, captions, move_secs, centers, sfx_events, meta = _load_clip_timing(
                    args.timing.resolve(strict=True), COVER_SEC, clip_dur
                )
            else:
                starts = [round(COVER_SEC + clip_dur * i / 13.0, 3) for i in range(13)]
                captions = [[starts[0], round(COVER_SEC + clip_dur - 0.1, 3), f"{args.speaker}核心讲解（请配合字幕时间轴）"]]
                move_secs = (starts[3], starts[7], starts[10])
                centers = DEMO_CENTERS
                sfx_events = [(t, "chime") for t in (COVER_SEC, *move_secs)]
        else:
            clip_dur = DEMO_CLIP_SEC
            speaker_mp4, speech_wav = _synthesize_demo_media(
                (ASSETS / "narration.wav").resolve(strict=True), work_dir, clip_dur, DEFAULT_FPS, ff
            )
            crop_box = _parse_crop(args.crop or "380,380,50,40", 480, 480)
            starts = DEMO_STARTS
            captions = DEMO_CAPTIONS
            move_secs = DEMO_MOVE_SECS
            centers = DEMO_CENTERS
            sfx_events = DEMO_SFX

        total_sec = round(COVER_SEC + clip_dur, 3)
        total_frames = round(total_sec * DEFAULT_FPS)
        move_frames = [round(float(m) * DEFAULT_FPS) for m in move_secs]

        srt_rows = [
            f"{idx}\n{_srt_stamp(a)} --> {_srt_stamp(b)}\n{txt}"
            for idx, (a, b, txt) in enumerate(captions, 1)
        ]
        (out_dir / "字幕.srt").write_text("\n\n".join(srt_rows) + "\n", encoding="utf-8")

        cfg = {
            "cover": COVER_SEC,
            "duration": total_sec,
            "starts": starts,
            "captions": captions,
            "centers": [list(c) for c in centers],
            "headerBadge": meta.get("header_badge", f"{args.speaker} · 直播实录"),
            "slotLabels": meta.get("slot_labels", [args.speaker, f"{args.speaker}拆解", "正确接力方案", f"{args.speaker}总结"]),
            "logoUri": logo_data_uri(args.logo.resolve(strict=True)),
            "coverUri": "data:image/png;base64," + base64.b64encode(cover_out.read_bytes()).decode("ascii"),
        }
        for opt_k, cfg_k in (("progress_names", "progressNames"), ("blue_keywords", "blueKeywords"), ("red_keywords", "redKeywords")):
            if meta.get(opt_k):
                cfg[cfg_k] = meta[opt_k]

        plate_mp4 = work_dir / "plate.mp4"
        pip_mp4 = work_dir / "pip.mp4"
        render_canvas_stage(STAGE_HTML, STAGE_HTML.parent, cfg, plate_mp4, total_frames, fps=DEFAULT_FPS)
        composite_dynamic_circle_pip(
            plate_mp4, speaker_mp4, pip_mp4, total_frames,
            crop_box=crop_box, centers=centers, move_frames=move_frames,
            cover_frames=cover_frames, portrait_size=224, inset=5, fps=DEFAULT_FPS,
        )

        final_mp4 = out_dir / "真人IP圆窗-升级样片.mp4"
        report = mix_audio_with_bgm_and_sfx(
            pip_mp4, speech_wav, final_mp4, total_sec=total_sec,
            cover_sec=COVER_SEC, music_style=args.music,
            sfx_events=sfx_events, first_frame_jpg=out_dir / "视频首帧.jpg",
        )
        qa = verify_and_make_sheets(final_mp4, out_dir, total_frames, cover_frames=cover_frames)
        print(json.dumps({"mix": report, "qa": qa, "output": str(final_mp4)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
