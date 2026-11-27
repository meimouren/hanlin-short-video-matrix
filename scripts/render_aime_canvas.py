"""使用升级版白/翰林蓝/战绩红 Chromium Canvas 2D 动效引擎从技能包随附 AIME 素材一键出片。"""

import argparse
import base64
import json
import sys
import wave
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parent
ASSETS = SCRIPTS_DIR.parent / "assets/aime"
STAGE_HTML = SCRIPTS_DIR / "stage_aime_canvas.html"

sys.path.insert(0, str(SCRIPTS_DIR))
from visual_engine import (  # noqa: E402
    DEFAULT_FPS,
    logo_data_uri,
    mix_audio_with_bgm_and_sfx,
    render_canvas_stage,
    verify_and_make_sheets,
)

COVER_SEC, TAIL_SEC = 0.70, 1.45
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


def srt_stamp(seconds):
    ms = round(seconds * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def load_voice_data(audio: Path, timing_json: Path):
    doc = json.loads(timing_json.read_text(encoding="utf-8-sig"))
    with wave.open(str(audio), "rb") as w:
        voice_dur = w.getnframes() / w.getframerate()
    cues = doc["cues"]
    if len(cues) != len(SEQUENCE) or [c["text"] for c in cues] != SEQUENCE:
        raise ValueError("timing.json 与内置 AIME 18 句口径不一致")
    starts = [float(c["start"]) + COVER_SEC for c in cues]
    captions = []
    for i, c in enumerate(cues):
        full = c["text"]
        tokens = CAPTION_BREAKS.get(i, ())
        offsets = [0, *[full.index(tok) for tok in tokens], len(full)]
        times = [float(c["start"]), *[float(c["anchors"][tok]) for tok in tokens], float(c["end"])]
        for n in range(len(offsets) - 1):
            words = full[offsets[n]:offsets[n + 1]].strip().strip("，")
            if words:
                captions.append([times[n] + COVER_SEC, times[n + 1] + COVER_SEC, words])
    return voice_dur, starts, captions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="新建输出目录")
    parser.add_argument("--audio", type=Path, default=ASSETS / "narration.wav")
    parser.add_argument("--timing", type=Path, default=ASSETS / "timing.json")
    parser.add_argument("--cover", type=Path, default=ASSETS / "cover.png")
    parser.add_argument("--logo", type=Path, default=ASSETS / "logo.jpg")
    parser.add_argument("--music", choices=("plucked", "mallet"), default="plucked")
    args = parser.parse_args()

    out_dir = args.output.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    voice_dur, starts, captions = load_voice_data(args.audio, args.timing)
    total_sec = round(COVER_SEC + voice_dur + TAIL_SEC, 3)
    total_frames = round(total_sec * DEFAULT_FPS)

    # Save standalone copy of cover & SRT
    (out_dir / "独立封面.png").write_bytes(args.cover.read_bytes())
    srt_rows = [
        f"{idx}\n{srt_stamp(a)} --> {srt_stamp(b)}\n{txt}"
        for idx, (a, b, txt) in enumerate(captions, 1)
    ]
    (out_dir / "字幕.srt").write_text("\n\n".join(srt_rows) + "\n", encoding="utf-8")

    cfg = {
        "cover": COVER_SEC,
        "duration": total_sec,
        "starts": starts,
        "captions": captions,
        "logoUri": logo_data_uri(args.logo),
        "coverUri": "data:image/png;base64," + base64.b64encode(args.cover.read_bytes()).decode("ascii"),
    }
    plate_mp4 = out_dir / "画面.mp4"
    render_canvas_stage(STAGE_HTML, STAGE_HTML.parent, cfg, plate_mp4, total_frames, fps=DEFAULT_FPS)

    sfx_events = [(s, "whoosh" if i in (3, 6, 10, 14, 16) else "pop") for i, s in enumerate(starts)]
    final_mp4 = out_dir / "AIME-视觉升级样片.mp4"
    report = mix_audio_with_bgm_and_sfx(
        plate_mp4,
        args.audio,
        final_mp4,
        total_sec=total_sec,
        cover_sec=COVER_SEC,
        music_style=args.music,
        sfx_events=sfx_events,
        first_frame_jpg=out_dir / "视频首帧.jpg",
    )
    qa = verify_and_make_sheets(final_mp4, out_dir, total_frames, cover_frames=round(COVER_SEC * DEFAULT_FPS))
    print(json.dumps({"mix": report, "qa": qa, "output": str(final_mp4)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
