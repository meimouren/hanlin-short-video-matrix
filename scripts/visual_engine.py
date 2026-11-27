"""翰林短视频矩阵 · 升级版视觉动效与合成公共引擎。

整合经过实片验证的白/翰林蓝/战绩红调色板、外框连通透明官方 Logo 提取、
3:4 独立封面程序化贴标、Playwright Chromium Canvas 2D 逐帧渲染、
8x 超采样动态真人圆窗叠加、人声避让轻配乐+UI 微音效混音，以及
视频号 124px 留白 + y<1452 安全区全自动验片。
"""

import sys

sys.dont_write_bytecode = True

import base64
from functools import lru_cache, partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from playwright.sync_api import sync_playwright
from scipy.ndimage import label
from scipy.signal import butter, sosfilt

PALETTE = {
    "bg": "#FFFFFF",
    "blue": "#156BB1",
    "red": "#A41034",
    "sky": "#E2F3FF",
    "rose": "#FFEDF2",
    "bright_blue": "#1681D4",
    "bright_red": "#CE2755",
    "ink": "#102E4B",
    "muted": "#395872",
}

FINDER_MARGIN = 124
DOUYIN_MARGIN = 24
FINDER_QUIET_Y = 1452
DEFAULT_W, DEFAULT_H, DEFAULT_FPS = 1080, 1920, 30
DEFAULT_SR = 44100

LIGHT_CUES = {
    "plucked": (108, "轻快拨弦"),
    "mallet": (114, "清脆木琴"),
}


def resolve_ffmpeg(ffmpeg_path=None):
    if ffmpeg_path:
        return str(ffmpeg_path)
    here = Path(__file__).resolve()
    local_bin = here.parent / "bin/ffmpeg.exe"
    if local_bin.is_file():
        return str(local_bin)
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def resolve_ffprobe(ffprobe_path=None):
    if ffprobe_path:
        return str(ffprobe_path)
    here = Path(__file__).resolve()
    local_bin = here.parent / "bin/ffprobe.exe"
    if local_bin.is_file():
        return str(local_bin)
    return shutil.which("ffprobe")


def resolve_chrome(chrome_path=None):
    if chrome_path and Path(chrome_path).is_file():
        return str(chrome_path)
    win_chrome = Path(r"C:/Program Files/Google/Chrome/Application/chrome.exe")
    if win_chrome.is_file():
        return str(win_chrome)
    return None


def extract_transparent_logo(src_jpg, dst_png=None, threshold=235):
    """仅对与图像四边连通的外部白色背景置透明，严格保留蓝方块内白色 `lin` 笔画。"""
    with Image.open(src_jpg) as im:
        arr = np.array(im.convert("RGBA"))
    white = (arr[:, :, 0] > threshold) & (arr[:, :, 1] > threshold) & (arr[:, :, 2] > threshold)
    lbl, _ = label(white)
    border_labels = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
    border_labels.discard(0)
    bg_mask = np.isin(lbl, list(border_labels))
    arr[bg_mask, 3] = 0
    logo_im = Image.fromarray(arr, "RGBA")
    bbox = logo_im.getbbox()
    if bbox:
        logo_im = logo_im.crop(bbox)
    if dst_png:
        Path(dst_png).parent.mkdir(parents=True, exist_ok=True)
        logo_im.save(dst_png, "PNG")
    return logo_im


def logo_data_uri(src_jpg, max_size=(286, 48)):
    im = extract_transparent_logo(src_jpg)
    im.thumbnail(max_size, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def stamp_logo_on_cover(raw_cover_path, logo_png_path, out_png_path, size=(1080, 1440), logo_w=430, dest=(44, 38)):
    """将 3:4 独立封面图规整到目标分辨率，并在左上角留白位置程序化叠加官方透明 Logo。"""
    with Image.open(raw_cover_path) as raw:
        cover = ImageOps.fit(raw.convert("RGBA"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    with Image.open(logo_png_path) as lg:
        logo = lg.convert("RGBA")
        logo_h = round(logo.height * (logo_w / logo.width))
        logo_resized = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
    cover.alpha_composite(logo_resized, dest=dest)
    out = Path(out_png_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cover.convert("RGB").save(out, "PNG")
    return out


class _QuietHTTPHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def render_canvas_stage(
    html_path,
    serve_dir,
    cfg,
    out_mp4,
    total_frames,
    fps=DEFAULT_FPS,
    width=DEFAULT_W,
    height=DEFAULT_H,
    canvas_id="stage",
    chrome_path=None,
    ffmpeg_path=None,
):
    """通过 Playwright + Chrome 逐帧驱动 HTML Canvas 2D (`setupStage` / `renderFrame`) 渲染视频流。"""
    html_file = Path(html_path).resolve()
    root_serve = Path(serve_dir).resolve()
    rel_url = html_file.relative_to(root_serve).as_posix()
    out_file = Path(out_mp4)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    temp_mp4 = out_file.with_suffix(".part.mp4")

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHTTPHandler, directory=str(root_serve)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port

    ff = resolve_ffmpeg(ffmpeg_path)
    exe = resolve_chrome(chrome_path)
    launch_kw = {"headless": True, "args": ["--disable-background-timer-throttling"]}
    if exe:
        launch_kw["executable_path"] = exe
    else:
        launch_kw["channel"] = "chrome"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_kw)
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(f"http://127.0.0.1:{port}/{rel_url}")
            page.evaluate("cfg => window.setupStage(cfg)", cfg)

            cmd = [
                ff, "-y", "-v", "error",
                "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "pipe:0", "-an",
                "-vf", "scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p",
                "-c:v", "libx264", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-threads", "5", "-preset", "veryfast", "-crf", "15", "-movflags", "+faststart",
                str(temp_mp4),
            ]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            js_eval = (
                f"(s) => {{ window.renderFrame(s); "
                f"return document.getElementById('{canvas_id}').toDataURL('image/jpeg', 0.94).split(',')[1]; }}"
            )
            for n in range(total_frames):
                b64 = page.evaluate(js_eval, n / fps)
                proc.stdin.write(base64.b64decode(b64))
                if n % 200 == 0 or n == total_frames - 1:
                    print(f"[Canvas] {n + 1}/{total_frames}", flush=True)
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError("FFmpeg Canvas pipe encode failed")
            browser.close()
    finally:
        server.shutdown()

    temp_mp4.replace(out_file)
    return out_file


def make_circle_mask(size):
    scale = 8
    large = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(large).ellipse((4, 4, size * scale - 5, size * scale - 5), fill=255)
    return large.resize((size, size), Image.Resampling.LANCZOS)


def composite_dynamic_circle_pip(
    plate_mp4,
    speaker_mp4,
    out_mp4,
    total_frames,
    crop_box,
    centers,
    move_frames,
    cover_frames=21,
    portrait_size=224,
    inset=5,
    fps=DEFAULT_FPS,
    ring_colors=((22, 129, 212), (21, 107, 177)),
    ffmpeg_path=None,
):
    """将真实说话人裁切为 8x 抗锯齿渐变边框圆窗，前 21 帧完全隐藏并随幕次平滑移位。"""
    ff = resolve_ffmpeg(ffmpeg_path)
    out_file = Path(out_mp4)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    temp_out = out_file.with_suffix(".part.mp4")

    cw, ch, cx_crop, cy_crop = crop_box
    inner_size = portrait_size - inset * 2

    def pos_expr(axis):
        left = [c[axis] - portrait_size // 2 for c in centers]
        expr = str(left[-1])
        for m, v in reversed(list(zip(move_frames, left[:-1]))):
            expr = f"if(lt(t*{fps},{m - 1e-4}),{v},{expr})"
        return expr

    with tempfile.TemporaryDirectory(prefix="hanlin-pip-", dir=str(out_file.parent)) as tmp:
        tmp_dir = Path(tmp)
        inner_png = tmp_dir / "inner.png"
        ring_png = tmp_dir / "ring.png"
        alpha_raw = tmp_dir / "fade.gray"

        make_circle_mask(inner_size).save(inner_png)
        outer = np.array(make_circle_mask(portrait_size), np.float32)

        yy, xx = np.indices((portrait_size, portrait_size))
        ratio = (xx + yy) / (2 * (portrait_size - 1))
        ring = np.stack([a + (b - a) * ratio for a, b in zip(ring_colors[0], ring_colors[1])], axis=-1).astype(np.uint8)
        Image.fromarray(ring, "RGB").save(ring_png)

        with alpha_raw.open("wb") as writer:
            for n in range(total_frames):
                if n < cover_frames:
                    eased = 0.0
                else:
                    open_p = min(1.0, (n - cover_frames + 1) / (0.18 * fps))
                    open_e = open_p * open_p * (3 - 2 * open_p)
                    d = min((abs(n - m) for m in move_frames), default=999)
                    p = min(1.0, d / (0.15 * fps))
                    move_e = p * p * (3 - 2 * p)
                    eased = open_e * move_e
                writer.write(np.round(outer * eased).astype(np.uint8).tobytes())

        chain = (
            f"[0:v]settb=1/{fps},setpts=N[page];"
            f"[1:v]settb=1/{fps},setpts=N,crop={cw}:{ch}:{cx_crop}:{cy_crop},"
            f"scale={inner_size}:{inner_size}:flags=lanczos,setsar=1,format=yuva420p,"
            f"tpad=start={cover_frames}:start_mode=clone:stop=40:stop_mode=clone,settb=1/{fps},setpts=N[raw];"
            "[2:v]format=gray[inner];[raw][inner]alphamerge[cutout];"
            f"[3:v][cutout]overlay=x={inset}:y={inset}:format=yuv420:shortest=1[rimmed];"
            "[rimmed][4:v]alphamerge[speaker];"
            f"[page][speaker]overlay=x='{pos_expr(0)}':y='{pos_expr(1)}':shortest=1:format=yuv420[v]"
        )
        subprocess.check_call([
            ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-i", str(plate_mp4), "-i", str(speaker_mp4), "-i", str(inner_png),
            "-loop", "1", "-framerate", str(fps), "-i", str(ring_png),
            "-f", "rawvideo", "-pixel_format", "gray", "-video_size", f"{portrait_size}x{portrait_size}",
            "-framerate", str(fps), "-i", str(alpha_raw),
            "-filter_complex_threads", "2", "-filter_complex", chain,
            "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "15", "-threads", "5",
            "-pix_fmt", "yuv420p", "-color_primaries", "bt709", "-colorspace", "bt709", "-color_trc", "bt709",
            "-fps_mode", "cfr", "-r", str(fps), "-frames:v", str(total_frames), str(temp_out),
        ])
    temp_out.replace(out_file)
    return out_file


@lru_cache(maxsize=96)
def _synth_note(sound, pitch, sr=DEFAULT_SR):
    freq = 440.0 * 2.0 ** ((pitch - 69) / 12.0)
    t = np.arange(round(0.74 * sr)) / sr
    phase = 2.0 * np.pi * freq * t
    attack = np.minimum(1.0, t / 0.011)
    if sound == "plucked":
        w = (
            np.sin(phase)
            + 0.34 * np.sin(phase * 2.0) * np.exp(-t / 0.22)
            + 0.20 * np.sin(phase * 3.0) * np.exp(-t / 0.09)
            + 0.10 * np.sin(phase * 4.0) * np.exp(-t / 0.045)
        )
        return w * attack * np.exp(-t / 0.17)
    w = np.sin(phase) + 0.22 * np.sin(phase * 3.97) * np.exp(-t / 0.037)
    return w * attack * np.exp(-t / 0.13)


def light_arrangement(size, style="plucked", sr=DEFAULT_SR):
    bpm, _ = LIGHT_CUES[style]
    beat = 60.0 / bpm
    rng = np.random.default_rng(bpm)
    bed = np.zeros((size, 2), dtype=np.float64)

    def place(line, beat_time, level, pan):
        at = int(beat_time * beat * sr)
        line = line[:max(0, size - at)]
        if len(line):
            bed[at:at + len(line)] += line[:, None] * level * np.array((1.0 - pan, 1.0 + pan))

    for bar in range(int(size / sr / (4 * beat)) + 1):
        down = bar * 4
        if style == "plucked":
            chords = ((53, 60, 65, 69), (50, 57, 62, 65), (46, 53, 58, 62), (48, 55, 60, 64))
            rhythm = ((0.12, 1), (0.73, 2), (1.51, 3), (2.24, 1), (2.84, 2), (3.52, 3))
        else:
            chords = ((60, 64, 67, 72), (57, 60, 64, 69), (53, 57, 60, 65), (55, 62, 67, 71))
            rhythm = ((0.15, 2), (0.61, 3), (1.24, 1), (2.10, 2), (2.73, 3), (3.18, 1))
        chord = chords[bar % len(chords)]
        place(_synth_note(style, chord[0], sr), down + 0.02, 0.46, -0.12)
        pattern = rhythm if bar % 2 == 0 else rhythm[:-1]
        for q, (when, idx) in enumerate(pattern):
            off = 12 if style == "mallet" and (bar + q) % 8 == 0 else 0
            place(_synth_note(style, chord[idx] + off, sr), down + when, float(rng.uniform(0.21, 0.36)), 0.15 * (-1) ** q)
        t = np.arange(round(sr * 0.064)) / sr
        brush = rng.normal(0.0, 0.32, len(t)) * np.minimum(1.0, t / 0.009) * np.exp(-t / 0.016)
        brush = sosfilt(butter(1, (490, 2350), btype="bandpass", fs=sr, output="sos"), brush)
        for at in (1.52, 3.50):
            place(brush, down + at, 0.075, 0.28)
    bed = sosfilt(butter(2, 3500, fs=sr, output="sos"), bed, axis=0)
    bed *= 0.043 / max(1e-8, np.sqrt(np.mean(bed ** 2)))
    return bed


def synth_ui_sfx(kind="pop", sr=DEFAULT_SR):
    if kind == "pop":
        dur = 0.085
        t = np.arange(int(dur * sr)) / sr
        f = 520.0 + 260.0 * np.exp(-t / 0.025)
        w = np.sin(2.0 * np.pi * f * t) * np.minimum(1.0, t / 0.004) * np.exp(-t / 0.022)
        return w * 0.055
    if kind == "stamp":
        dur = 0.11
        t = np.arange(int(dur * sr)) / sr
        thud = np.sin(2.0 * np.pi * (170.0 + 120.0 * np.exp(-t / 0.015)) * t) * np.exp(-t / 0.032)
        hi = np.sin(2.0 * np.pi * 660.0 * t) * np.exp(-t / 0.018) * 0.35
        return (thud + hi) * np.minimum(1.0, t / 0.003) * 0.070
    dur = 0.14
    t = np.arange(int(dur * sr)) / sr
    c1 = np.sin(2.0 * np.pi * 587.33 * t) * np.exp(-t / 0.045)
    c2 = np.sin(2.0 * np.pi * 880.00 * t) * np.exp(-t / 0.055) * 0.45
    return (c1 + c2) * np.minimum(1.0, t / 0.006) * 0.045


def mix_audio_with_bgm_and_sfx(
    video_mp4,
    speech_audio,
    out_mp4,
    total_sec,
    cover_sec=0.70,
    music_style="plucked",
    sfx_events=(),
    sr=DEFAULT_SR,
    ffmpeg_path=None,
    first_frame_jpg=None,
):
    """将人声（1.0x 原声或定稿配音）+ 包络闪避轻配乐 + UI 微音效混音封装并生成首帧图与混音 JSON。"""
    ff = resolve_ffmpeg(ffmpeg_path)
    pcm_bytes = subprocess.check_output([
        ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-i", str(speech_audio), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-",
    ])
    raw = np.frombuffer(pcm_bytes, dtype="<f4").astype(np.float64)

    sample_count = round(total_sec * sr)
    pad_front = round(cover_sec * sr)
    voice = np.zeros(sample_count, dtype=np.float64)
    put_len = min(len(raw), sample_count - pad_front)
    if put_len > 0:
        voice[pad_front:pad_front + put_len] = raw[:put_len]

    voice = sosfilt(butter(2, 66, btype="highpass", fs=sr, output="sos"), voice)
    step = sr // 50
    lengths = np.arange(0, sample_count, step)
    starts = [(i, min(sample_count, i + step)) for i in lengths]
    before = np.array([np.sqrt(np.mean(voice[a:b] ** 2)) for a, b in starts])
    active = before > max(0.001, np.percentile(before, 76) * 0.22)
    if not active.any():
        raise ValueError("没有检测到有效口播人声")
    voice *= min(3.5, 0.118 / np.sqrt(np.mean(before[active] ** 2)), 0.83 / max(abs(voice)))

    if put_len > 0:
        fade_tail = min(round(0.04 * sr), put_len)
        voice[pad_front + put_len - fade_tail:pad_front + put_len] *= np.linspace(1.0, 0.0, fade_tail)

    level = np.array([np.sqrt(np.mean(voice[a:b] ** 2)) for a, b in starts])
    envelope = sosfilt(butter(1, 4, fs=50, output="sos"), np.clip(level / 0.028, 0, 1))
    duck = np.interp(np.arange(sample_count), lengths, envelope)

    bed = light_arrangement(sample_count, music_style, sr=sr)
    bed *= 0.36 - 0.22 * duck[:, None]
    fi = min(round(0.45 * sr), sample_count)
    fo = min(round(0.75 * sr), sample_count)
    bed[:fi] *= np.linspace(0.0, 1.0, fi)[:, None]
    bed[-fo:] *= np.linspace(1.0, 0.0, fo)[:, None]

    sfx = np.zeros((sample_count, 2), dtype=np.float64)
    for at_sec, kind in sfx_events:
        w_sfx = synth_ui_sfx(kind, sr=sr)
        at = round(at_sec * sr)
        take = min(len(w_sfx), sample_count - at)
        if take > 0:
            sfx[at:at + take, 0] += w_sfx[:take]
            sfx[at:at + take, 1] += w_sfx[:take]

    total = voice[:, None] + bed + sfx
    gain = min(1.0, 0.87 / np.max(abs(total)))
    total *= gain

    out_file = Path(out_mp4)
    temp_out = out_file.with_suffix(".part.mp4")
    with tempfile.TemporaryDirectory(prefix="hanlin-mix-", dir=str(out_file.parent)) as tmp:
        mixed_wav = Path(tmp) / "mixed.wav"
        with wave.open(str(mixed_wav), "wb") as w:
            w.setparams((2, 2, sr, 0, "NONE", ""))
            w.writeframes(np.round(total * 32767).astype("<i2").tobytes())
        subprocess.check_call([
            ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-i", str(video_mp4), "-i", str(mixed_wav),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-b:a", "160k",
            "-movflags", "+faststart", str(temp_out),
        ])
    temp_out.replace(out_file)

    if first_frame_jpg:
        subprocess.check_call([
            ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-i", str(out_file), "-frames:v", "1", "-q:v", "2", str(first_frame_jpg),
        ])

    bpm, cue_label = LIGHT_CUES[music_style]
    music_rms_db = float(20 * np.log10(gain * np.sqrt(np.mean(bed ** 2))))
    voice_rms_db = float(20 * np.log10(gain * np.sqrt(np.mean(level[active] ** 2))))
    peak_db = float(20 * np.log10(np.max(abs(total))))
    report = {
        "duration_sec": total_sec,
        "music_style": music_style,
        "cue": cue_label,
        "bpm": bpm,
        "active_voice_rms_dbfs": round(voice_rms_db, 2),
        "music_rms_dbfs": round(music_rms_db, 2),
        "voice_over_music_db": round(voice_rms_db - music_rms_db, 2),
        "mix_peak_dbfs": round(peak_db, 2),
    }
    out_file.with_suffix(".混音记录.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def verify_and_make_sheets(
    final_mp4,
    out_dir,
    total_frames,
    cover_frames=21,
    fps=DEFAULT_FPS,
    margin_px=FINDER_MARGIN,
    quiet_y=1458,
    sample_times=None,
    phone_times=None,
    ffprobe_path=None,
):
    """检验视频流参数、首 21 帧静止与安全边距，并生成 12 帧实帧总览和手机裁切核对图。"""
    fp = resolve_ffprobe(ffprobe_path)
    out = Path(out_dir)
    if fp:
        info = json.loads(subprocess.check_output([
            fp, "-v", "error",
            "-show_entries", "stream=codec_type,width,height,pix_fmt,r_frame_rate,nb_frames,sample_rate,channels,duration",
            "-of", "json", str(final_mp4),
        ]).decode("utf-8"))
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next(s for s in info["streams"] if s["codec_type"] == "audio")
        assert (v["width"], v["height"], v["r_frame_rate"], v["pix_fmt"]) == (1080, 1920, f"{fps}/1", "yuv420p"), v
        assert int(v["nb_frames"]) == total_frames, v
        assert (int(a["sample_rate"]), int(a["channels"])) == (48000, 2), a
    else:
        probe_cap = cv2.VideoCapture(str(final_mp4))
        assert probe_cap.isOpened(), f"无法打开视频: {final_mp4}"
        w = round(probe_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = round(probe_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap_fps = probe_cap.get(cv2.CAP_PROP_FPS)
        fc = round(probe_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        probe_cap.release()
        assert (w, h) == (1080, 1920), (w, h)
        assert abs(cap_fps - fps) < 0.1, cap_fps
        assert fc == total_frames, (fc, total_frames)

    dur = total_frames / fps
    if not sample_times:
        sample_times = [round(dur * k / 12 + 0.20, 2) for k in range(12)]
        sample_times[-1] = min(sample_times[-1], dur - 0.15)
    if not phone_times:
        phone_times = [round(dur * k, 2) for k in (0.01, 0.32, 0.62, 0.90)]

    cap = cv2.VideoCapture(str(final_mp4))
    prev_cov = None
    max_cov_mean_diff = 0.0
    min_margin_mean = 255.0
    min_bottom_mean = 255.0
    for fidx in range(total_frames):
        ok, bgr = cap.read()
        assert ok, f"读取第 {fidx} 帧失败"
        if fidx < cover_frames:
            if prev_cov is not None:
                diff = float(np.mean(np.abs(bgr.astype(np.int16) - prev_cov.astype(np.int16))))
                max_cov_mean_diff = max(max_cov_mean_diff, diff)
            prev_cov = bgr
        if fidx % 15 == 0:
            left_mean = float(np.mean(bgr[:, :margin_px]))
            right_mean = float(np.mean(bgr[:, 1080 - margin_px:]))
            min_margin_mean = min(min_margin_mean, left_mean, right_mean)
            if quiet_y is not None:
                min_bottom_mean = min(min_bottom_mean, float(np.mean(bgr[quiet_y:, :])))
    cap.release()

    # Keyframe contact sheet
    sheet = Image.new("RGB", (4 * 270, 3 * 520), "#F4F8FB")
    draw = ImageDraw.Draw(sheet)
    cap = cv2.VideoCapture(str(final_mp4))
    for idx, t in enumerate(sample_times[:12]):
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(total_frames - 1, round(t * fps)))
        ok, bgr = cap.read()
        if not ok:
            continue
        im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)).resize((256, 455), Image.Resampling.LANCZOS)
        x, y = (idx % 4) * 270 + 7, (idx // 4) * 520 + 12
        sheet.paste(im, (x, y))
        draw.text((x + 4, y + 462), f"t={t:.2f}s (f={round(t * fps)})", fill="#102E4B")
    cap.release()
    sheet.save(out / "关键帧总览.jpg", quality=92)

    # Phone crop check (966px / 864px Finder overlays)
    psheet = Image.new("RGB", (len(phone_times) * 270, 2 * 500), "#1B2836")
    pdraw = ImageDraw.Draw(psheet)
    cap = cv2.VideoCapture(str(final_mp4))
    for ci, t in enumerate(phone_times):
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(total_frames - 1, round(t * fps)))
        ok, bgr = cap.read()
        if not ok:
            continue
        src_im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        for ri, vw in enumerate((966, 864)):
            left = (1080 - vw) // 2
            cropped = src_im.crop((left, 0, left + vw, 1920)).copy()
            d = ImageDraw.Draw(cropped, "RGBA")
            ov_y = 1459 if vw == 864 else 1495
            d.rectangle((0, ov_y, vw, 1920), fill=(12, 20, 28, 185))
            d.rectangle((24, ov_y + 24, 340, ov_y + 72), fill=(255, 255, 255, 210))
            d.rectangle((24, ov_y + 92, vw - 130, ov_y + 132), fill=(255, 255, 255, 170))
            d.rectangle((24, ov_y + 148, vw - 180, ov_y + 184), fill=(255, 255, 255, 140))
            thumb = cropped.resize((246, round(246 * 1920 / vw)), Image.Resampling.LANCZOS)
            thumb.thumbnail((246, 455), Image.Resampling.LANCZOS)
            px = ci * 270 + (270 - thumb.width) // 2
            py = ri * 500 + 10
            psheet.paste(thumb, (px, py))
            pdraw.text((ci * 270 + 14, ri * 500 + 472), f"{vw}px | t={t:.2f}s", fill="#FFFFFF")
    cap.release()
    psheet.save(out / "手机裁切核对.jpg", quality=92)

    assert max_cov_mean_diff < 1.1, f"Cover not static: {max_cov_mean_diff}"
    assert min_margin_mean >= 254.0, f"Side margin bleed: {min_margin_mean}"
    assert min_bottom_mean >= 254.0, f"Bottom quiet zone bleed: {min_bottom_mean}"
    return {
        "max_cover_mean_diff": round(max_cov_mean_diff, 4),
        "min_margin_mean": round(min_margin_mean, 3),
        "min_bottom_quiet_mean": round(min_bottom_mean, 3),
    }
