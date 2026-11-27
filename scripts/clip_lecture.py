"""录播原声净素材剪辑与零起点时间轴提取脚本（支持单段 cut 与批量 batch 选题单）。"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

import cv2

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from visual_engine import DEFAULT_FPS, DEFAULT_SR, resolve_ffmpeg  # noqa: E402


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _srt_stamp(sec: float) -> str:
    ms = round(sec * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _probe_duration(path: Path) -> float:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"无法读取视频: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or DEFAULT_FPS
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    return float(frames) / float(fps)


def _auto_captions_from_words(words, max_chars=18):
    """将词级时间戳按标点与最大字数切分为单行字幕初稿。"""
    cues = []
    cur_txt = ""
    start_t = last_t = None
    for item in words:
        s, e, w = float(item["start"]), float(item["end"]), str(item["w"]).strip()
        if not w or e <= s:
            continue
        if cur_txt and (len(cur_txt + w) > max_chars or s - last_t > 0.55 or e - start_t > 4.2):
            cues.append([round(start_t, 3), round(last_t, 3), cur_txt.strip()])
            cur_txt = ""
        if not cur_txt:
            start_t = s
        cur_txt += w
        last_t = e
        if re.search(r"[。！？!?，；;,]$", w) and len(cur_txt) >= 6:
            cues.append([round(start_t, 3), round(last_t, 3), cur_txt.strip("，,；; ")])
            cur_txt = ""
    if cur_txt and start_t is not None and last_t is not None:
        cues.append([round(start_t, 3), round(last_t, 3), cur_txt.strip("，,；; ")])
    return cues


def _build_net_timeline(media_path: Path, bounds, trs_segments, custom_captions_by_part=None):
    offset = 0.0
    seg_map = []
    cues = []
    net_words = []
    custom_caps = []

    for idx, (a, b) in enumerate(bounds):
        length = round((b - a) * DEFAULT_FPS) / DEFAULT_FPS
        seg_map.append({
            "源起": round(a, 3),
            "源止": round(b, 3),
            "净片起": round(offset, 3),
            "净片止": round(offset + length, 3),
        })

        if custom_captions_by_part and custom_captions_by_part[idx]:
            for cs, ce, txt in custom_captions_by_part[idx]:
                lo = max(0.0, float(cs) - a) + offset
                hi = min(length, float(ce) - a) + offset
                if hi > lo and str(txt).strip():
                    custom_caps.append([round(lo, 3), round(hi, 3), str(txt).strip()])

        for row in trs_segments or ():
            r_start, r_end = float(row["start"]), float(row["end"])
            if r_end <= a or r_start >= b:
                continue
            row_words = row.get("words") or []
            if row_words:
                seg_text = ""
                w_first = w_last = None
                for ws, we, wt, *_ in row_words:
                    if we <= a or ws >= b or we <= ws:
                        continue
                    ns = round(max(0.0, float(ws) - a) + offset, 3)
                    ne = round(min(length, float(we) - a) + offset, 3)
                    if ne <= ns:
                        continue
                    net_words.append({"start": ns, "end": ne, "w": wt})
                    seg_text += wt
                    if w_first is None:
                        w_first = ns
                    w_last = ne
                if seg_text.strip() and w_first is not None:
                    cues.append({"start": w_first, "end": w_last, "text": seg_text.strip()})
            else:
                ns = round(max(0.0, r_start - a) + offset, 3)
                ne = round(min(length, r_end - a) + offset, 3)
                if ne > ns:
                    cues.append({"start": ns, "end": ne, "text": row["text"].strip()})
        offset += length

    captions = custom_caps if custom_caps else _auto_captions_from_words(net_words)
    if not captions and cues:
        captions = [[c["start"], c["end"], c["text"]] for c in cues]

    return {
        "source": str(media_path),
        "segments_map": seg_map,
        "duration": round(offset, 3),
        "cues": cues,
        "captions": captions,
        "words": net_words,
    }


def _cut_and_extract(media_path: Path, bounds, trs_segments, out_dir: Path, custom_captions_by_part=None):
    ff = resolve_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(media_path)
    for a, b in bounds:
        if not (0 <= a < b <= duration + 0.05) or round((b - a) * DEFAULT_FPS) < 1:
            raise ValueError(f"无效原片时间区间: {a} -> {b}（原片时长 {duration:.2f}s）")

    net_mp4 = out_dir / "原声净素材.mp4"
    net_wav = out_dir / "原声纯轨.wav"
    temp_mp4 = net_mp4.with_suffix(".part.mp4")

    with tempfile.TemporaryDirectory(prefix="hanlin-cut-", dir=str(out_dir)) as tmp:
        tmp_dir = Path(tmp)
        part_files = []
        for idx, (a, b) in enumerate(bounds, 1):
            length = round((b - a) * DEFAULT_FPS) / DEFAULT_FPS
            part_p = tmp_dir / f"part_{idx:02d}.mkv"
            vf = f"scale=trunc(iw*sar/2)*2:ih,setsar=1,fps={DEFAULT_FPS},format=yuv420p"
            subprocess.check_call([
                ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
                "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(media_path),
                "-vf", vf, "-af", f"aresample={DEFAULT_SR},apad", "-t", f"{length:.6f}",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                "-c:a", "pcm_s16le", "-ar", str(DEFAULT_SR), "-ac", "2", str(part_p),
            ])
            part_files.append(part_p)

        concat_txt = tmp_dir / "concat.txt"
        concat_txt.write_text("".join(f"file '{p.name}'\n" for p in part_files), encoding="utf-8")
        subprocess.check_call([
            ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", str(DEFAULT_SR), "-ac", "2", "-b:a", "160k",
            "-movflags", "+faststart", str(temp_mp4),
        ], cwd=str(tmp_dir))

    temp_mp4.replace(net_mp4)
    subprocess.check_call([
        ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-i", str(net_mp4), "-vn", "-ac", "1", "-ar", str(DEFAULT_SR), str(net_wav),
    ])

    timeline = _build_net_timeline(media_path, bounds, trs_segments, custom_captions_by_part)
    (out_dir / "净素材时间轴.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    srt_rows = [
        f"{i}\n{_srt_stamp(a)} --> {_srt_stamp(b)}\n{txt}"
        for i, (a, b, txt) in enumerate(timeline["captions"], 1)
    ]
    (out_dir / "字幕初稿.srt").write_text("\n\n".join(srt_rows) + ("\n" if srt_rows else ""), encoding="utf-8")
    return timeline


def _parse_segments(args):
    if args.segments:
        bounds = []
        for token in args.segments.split(","):
            t = token.strip()
            if not t:
                continue
            lo_s, _, hi_s = t.partition("-")
            bounds.append((float(lo_s), float(hi_s)))
        if bounds:
            return bounds
    if args.start is not None and args.end is not None:
        return [(float(args.start), float(args.end))]
    raise ValueError("cut 命令必须提供 --start 与 --end，或 --segments '起-止,起-止'")


def cmd_cut(args):
    media = args.media.resolve(strict=True)
    bounds = _parse_segments(args)
    trs_segments = None
    if args.transcript:
        trs = json.loads(args.transcript.resolve(strict=True).read_text(encoding="utf-8-sig"))
        trs_segments = trs.get("segments")
    timeline = _cut_and_extract(media, bounds, trs_segments, args.output.resolve())
    print(json.dumps({
        "output": str(args.output.resolve()),
        "duration": timeline["duration"],
        "segments": len(timeline["segments_map"]),
        "cues": len(timeline["cues"]),
        "captions": len(timeline["captions"]),
    }, ensure_ascii=False))


def cmd_batch(args):
    trs = json.loads(args.transcript.resolve(strict=True).read_text(encoding="utf-8-sig"))
    plan = json.loads(args.plan.resolve(strict=True).read_text(encoding="utf-8-sig"))
    media = Path(trs["source"]).resolve(strict=True)
    if plan.get("sha256") and trs.get("sha256") and plan["sha256"] != trs["sha256"]:
        raise ValueError("选题单与转写文件的 sha256 不一致")
    if trs.get("sha256") and _sha256_file(media) != trs["sha256"]:
        raise ValueError("原片文件哈希与转写记录不一致")

    out_root = args.output.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    results = []
    for idx, clip in enumerate(plan.get("作品", []), 1):
        parts = clip.get("片段") or []
        if not parts:
            raise ValueError(f"第 {idx} 条作品缺少片段定义")
        bounds = [(float(p["起"]), float(p["止"])) for p in parts]
        custom_caps = [p.get("字幕") for p in parts]
        sub = out_root / f"{idx:02d}"
        timeline = _cut_and_extract(media, bounds, trs.get("segments"), sub, custom_captions_by_part=custom_caps)
        (sub / "剪辑记录.json").write_text(
            json.dumps({"选题": clip, "原片时间映射": timeline["segments_map"]}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        results.append({"dir": str(sub), "title": clip.get("标题", f"{idx:02d}"), "duration": timeline["duration"]})
    print(json.dumps({"items": results}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cut = sub.add_parser("cut", help="裁剪单条或串联多段原声净素材")
    p_cut.add_argument("--media", type=Path, required=True, help="源录播视频路径")
    p_cut.add_argument("--start", type=float, help="开始秒数")
    p_cut.add_argument("--end", type=float, help="结束秒数")
    p_cut.add_argument("--segments", help="串联多段区间，例：3892.0-3910.0,3915.0-3924.75")
    p_cut.add_argument("--transcript", type=Path, help="可选：原片转写.json（自动重零起算时间轴）")
    p_cut.add_argument("--output", type=Path, required=True, help="输出目录")
    p_cut.set_defaults(func=cmd_cut)

    p_batch = sub.add_parser("batch", help="按选题单 JSON 批量切分原声净素材")
    p_batch.add_argument("transcript", type=Path, help="原片转写.json")
    p_batch.add_argument("plan", type=Path, help="选题单.json")
    p_batch.add_argument("output", type=Path, help="输出目录")
    p_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
