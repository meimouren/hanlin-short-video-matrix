"""阿里云百炼 qwen-audio-3.0-tts-plus 1.1 倍速合成与字级时间轴导出工具。

仅从环境变量读取 DASHSCOPE_API_KEY（可选 DASHSCOPE_TTS_URL），不含任何硬编码密钥。
"""

import argparse
from base64 import b64decode
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import wave

sys.dont_write_bytecode = True

import numpy as np

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
from visual_engine import DEFAULT_SR, resolve_ffmpeg  # noqa: E402

MODEL = "qwen-audio-3.0-tts-plus"
RAW_SR = 24000
DEFAULT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
DEFAULT_INSTRUCTION = "普通话，沉稳亲切，像顾问跟一位家长说话。停顿自然，英文缩写逐字母念。"
TARGET_ACTIVE_RMS = 0.115

ACRONYM_RE = re.compile(
    r"\b(?:A-I-M-E|AMC|AIME|USNCO|USABO|USACO|HMMT|BMT|UKChO|BBO|F=ma|AP)\b"
)


def _load_cues(input_path: Path, default_inst: str, default_pause_ms: int):
    if input_path.suffix.lower() == ".txt":
        lines = [ln.strip() for ln in input_path.read_text("utf-8-sig").splitlines() if ln.strip()]
        return [{"text": ln, "instruction": default_inst, "pause_ms": default_pause_ms} for ln in lines]

    doc = json.loads(input_path.read_text("utf-8-sig"))
    raw_items = doc.get("cues") or doc.get("segments") or doc.get("texts") if isinstance(doc, dict) else doc
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError(f"无法识别配音脚本结构: {input_path}")

    cues = []
    for item in raw_items:
        if isinstance(item, str):
            txt = item.strip()
            if txt:
                cues.append({"text": txt, "instruction": default_inst, "pause_ms": default_pause_ms})
        elif isinstance(item, dict) and str(item.get("text", "")).strip():
            cues.append({
                "text": str(item["text"]).strip(),
                "instruction": str(item.get("instruction") or default_inst),
                "pause_ms": int(item.get("pause_ms", default_pause_ms)),
            })
    if not cues:
        raise ValueError(f"脚本中没有有效口播行: {input_path}")
    return cues


def _to_ssml(text: str) -> str:
    escaped = html.escape(text, quote=False)
    spoken = ACRONYM_RE.sub(
        lambda m: f'<say-as interpret-as="characters">{m.group(0).replace("-", "")}</say-as>',
        escaped,
    )
    return f"<speak>{spoken}</speak>"


def _synthesize_sse(url: str, api_key: str, ssml: str, voice: str, instruction: str):
    payload = json.dumps({
        "model": MODEL,
        "input": {
            "text": ssml,
            "voice": voice,
            "format": "pcm",
            "sample_rate": RAW_SR,
            "enable_ssml": True,
            "word_timestamp_enabled": True,
            "instruction": instruction,
        },
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-SSE": "enable",
            "Accept": "text/event-stream",
        },
    )
    frames, words, request_id = [], [], None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw_line in resp:
                line = raw_line.strip()
                if not line.startswith(b"data:"):
                    continue
                event = json.loads(line[5:].decode("utf-8"))
                request_id = event.get("request_id") or request_id
                out = event.get("output") or {}
                audio_b64 = (out.get("audio") or {}).get("data")
                if audio_b64:
                    frames.append(b64decode(audio_b64))
                sent = out.get("sentence") or {}
                if sent.get("words"):
                    words.extend(sent["words"])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"百炼 TTS 请求失败 HTTP {exc.code}: {body}") from exc

    if not frames:
        raise RuntimeError("百炼 TTS 未返回音频 PCM 数据")
    return b"".join(frames), words, request_id


def _level_pcm16(pcm_bytes: bytes) -> np.ndarray:
    samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float64) / 32768.0
    block = RAW_SR // 50
    usable = (len(samples) // block) * block
    if usable > 0:
        wins = np.split(samples[:usable], usable // block)
        rms_vals = np.array([np.sqrt(np.mean(w * w)) for w in wins])
        active = rms_vals[rms_vals > 0.009]
        if len(active):
            cur = float(np.sqrt(np.mean(active * active)))
            peak = float(np.max(np.abs(samples))) or 1e-6
            gain = min(TARGET_ACTIVE_RMS / max(cur, 1e-9), 0.90 / peak)
            samples = np.clip(samples * gain, -0.98, 0.98)
    return np.round(samples * 32767.0).astype("<i2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="口播文本 .txt 或结构化 .json")
    parser.add_argument("--output", type=Path, required=True, help="输出目录（写入 narration.wav 与 timing.json）")
    parser.add_argument("--voice", default="longanlufeng", help="百炼音色 ID（默认 longanlufeng）")
    parser.add_argument("--speed", type=float, default=1.1, help="保音高倍速倍率（默认 1.1）")
    parser.add_argument("--pause-ms", type=int, default=180, help="句间默认停顿毫秒数（默认 180）")
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION, help="自然口语风格指令")
    parser.add_argument("--dry-run", action="store_true", help="仅校对分段与 SSML，不调用网络接口")
    args = parser.parse_args()

    if not (0.5 <= args.speed <= 2.0):
        parser.error("--speed 须在 0.5 到 2.0 之间")

    src = args.input.resolve(strict=True)
    out_dir = args.output.resolve()
    cues = _load_cues(src, args.instruction, args.pause_ms)

    plan_rows = [
        {
            "index": i,
            "text": c["text"],
            "ssml": _to_ssml(c["text"]),
            "instruction": c["instruction"],
            "pause_ms": c["pause_ms"],
        }
        for i, c in enumerate(cues, 1)
    ]

    if args.dry_run:
        print(json.dumps({
            "dry_run": True,
            "model": MODEL,
            "voice": args.voice,
            "speed": args.speed,
            "output_wav": str(out_dir / "narration.wav"),
            "output_timing": str(out_dir / "timing.json"),
            "cues": plan_rows,
        }, ensure_ascii=False, indent=2))
        return

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        parser.error("未检测到环境变量 DASHSCOPE_API_KEY，请先设置百炼 API Key 后再执行在线合成（本地验证可用 --dry-run）。")
    tts_url = os.environ.get("DASHSCOPE_TTS_URL", DEFAULT_URL).strip() or DEFAULT_URL

    out_dir.mkdir(parents=True, exist_ok=True)
    ff = resolve_ffmpeg()

    chunks = []
    timed_cues = []
    cursor_raw = 0.0

    for idx, (cue, prow) in enumerate(zip(cues, plan_rows)):
        raw_pcm, raw_words, req_id = _synthesize_sse(tts_url, api_key, prow["ssml"], args.voice, cue["instruction"])
        leveled = _level_pcm16(raw_pcm)
        seg_dur = len(leveled) / RAW_SR

        words_scaled = []
        for w in raw_words:
            bt = (float(w.get("begin_time", 0)) / 1000.0 + cursor_raw) / args.speed
            et = (float(w.get("end_time", 0)) / 1000.0 + cursor_raw) / args.speed
            words_scaled.append({
                "text": w.get("text", ""),
                "start": round(bt, 3),
                "end": round(et, 3),
            })

        timed_cues.append({
            "start": round(cursor_raw / args.speed, 3),
            "end": round((cursor_raw + seg_dur) / args.speed, 3),
            "text": cue["text"],
            "request_id": req_id,
            "words": words_scaled,
        })
        chunks.append(leveled)
        cursor_raw += seg_dur

        if idx < len(cues) - 1 and cue["pause_ms"] > 0:
            gap_samples = round(RAW_SR * (cue["pause_ms"] / 1000.0))
            chunks.append(np.zeros(gap_samples, dtype="<i2"))
            cursor_raw += gap_samples / RAW_SR

    raw_all = np.concatenate(chunks)
    final_wav = out_dir / "narration.wav"
    with tempfile.TemporaryDirectory(prefix="hanlin-tts-", dir=str(out_dir)) as tmp:
        raw_wav = Path(tmp) / "raw.wav"
        with wave.open(str(raw_wav), "wb") as w:
            w.setparams((1, 2, RAW_SR, 0, "NONE", ""))
            w.writeframes(raw_all.tobytes())
        subprocess.check_call([
            ff, "-hide_banner", "-nostdin", "-v", "error", "-y",
            "-i", str(raw_wav),
            "-af", f"atempo={args.speed:.4f},aresample={DEFAULT_SR}",
            "-ac", "1", "-ar", str(DEFAULT_SR),
            str(final_wav),
        ])

    timing_doc = {
        "model": MODEL,
        "voice": args.voice,
        "speed": args.speed,
        "duration_sec": round(cursor_raw / args.speed, 3),
        "cues": timed_cues,
    }
    timing_path = out_dir / "timing.json"
    timing_path.write_text(json.dumps(timing_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wav": str(final_wav), "timing": str(timing_path), "duration_sec": timing_doc["duration_sec"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
