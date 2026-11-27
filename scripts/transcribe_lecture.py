"""离线录播语音识别脚本（基于 faster-whisper，输出逐词时间 JSON 与可读带时间戳文本）。"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

import cv2

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from visual_engine import resolve_ffmpeg, resolve_ffprobe  # noqa: E402


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fmt_ts(sec: float) -> str:
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


def _probe_media(path: Path):
    """读取视频总时长并校验包含音频与视频流，无 ffprobe 时自动回退到 OpenCV + FFmpeg。"""
    fp = resolve_ffprobe()
    if fp:
        info = json.loads(subprocess.check_output([
            fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
        ]).decode("utf-8"))
        types = {s.get("codec_type") for s in info.get("streams", [])}
        if not {"audio", "video"} <= types:
            raise ValueError("输入素材必须同时包含视频与音频流。")
        return float(info["format"]["duration"])

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频文件: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    dur = float(frames) / float(fps)
    if dur <= 0:
        raise ValueError(f"视频时长无效: {path}")

    ff = resolve_ffmpeg()
    pcm = subprocess.check_output([
        ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-i", str(path), "-t", "0.2", "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-",
    ])
    if not pcm:
        raise ValueError("输入素材未检测到可用音轨。")
    return dur


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path, help="源录播/直播视频路径（mp4/mov/mkv 等）")
    parser.add_argument("output", type=Path, help="转写结果输出目录")
    parser.add_argument("--terms", default="", help="赛事/课程/人名专有术语表，逗号分隔")
    parser.add_argument("--language", default="zh", help="语言：zh、en 或 auto（默认 zh）")
    parser.add_argument("--model", help="Whisper 模型名称（如 small）或本地模型目录路径")
    parser.add_argument("--pause-sec", type=float, default=0.8, help="停顿标记阈值秒数（默认 0.8s）")
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        parser.error(
            "未检测到 faster-whisper，请先安装可选转写依赖：\n"
            "  python -m pip install faster-whisper==1.2.1"
        )

    src = args.media.resolve(strict=True)
    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / "原片转写.json"
    out_txt = out_dir / "原片转写.txt"
    if out_json.exists():
        parser.error(f"目标目录已有 {out_json.name}，请复用或换新目录。")

    model_spec = args.model
    if not model_spec:
        cached = Path.home() / ".cache" / "hanlin-video" / "faster-whisper-small"
        model_spec = str(cached) if cached.is_dir() else "small"

    duration = _probe_media(src)
    rec = WhisperModel(model_spec, device="cpu", compute_type="int8", cpu_threads=4)
    chunks, info = rec.transcribe(
        str(src),
        language=None if args.language == "auto" else args.language,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
        initial_prompt=args.terms or None,
    )

    rows = []
    for seg in chunks:
        txt = seg.text.strip()
        if not txt:
            continue
        words = [
            [round(w.start, 3), round(w.end, 3), w.word, round(w.probability, 3)]
            for w in (seg.words or [])
        ]
        rows.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": txt, "words": words})

    if not rows:
        parser.error("未识别到有效口播内容，请检查音频轨。")

    pause_gaps = []
    for prev, cur in zip(rows, rows[1:]):
        gap = round(cur["start"] - prev["end"], 3)
        if gap >= args.pause_sec:
            pause_gaps.append({"start": prev["end"], "end": cur["start"], "dur": gap})

    payload = {
        "source": str(src),
        "sha256": _sha256_file(src),
        "duration": round(duration, 3),
        "language": info.language,
        "model": Path(model_spec).name if Path(model_spec).exists() else model_spec,
        "segments": rows,
        "pause_gaps": pause_gaps,
    }

    with tempfile.NamedTemporaryFile("w", dir=out_dir, suffix=".part", delete=False, encoding="utf-8") as tmp:
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
    Path(tmp.name).replace(out_json)

    txt_lines = [f"[{_fmt_ts(r['start'])} - {_fmt_ts(r['end'])}] {r['text']}" for r in rows]
    out_txt.write_text("\n".join(txt_lines) + "\n", encoding="utf-8")
    print(f"已转写 {len(rows)} 段（总长 {duration:.2f}s），输出：{out_json} 与 {out_txt}")


if __name__ == "__main__":
    main()
