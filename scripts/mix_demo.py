"""Mix an instrumental arrangement under recorded narration."""

from functools import lru_cache
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import wave

import numpy as np
from scipy.signal import butter, sosfilt
from imageio_ffmpeg import get_ffmpeg_exe


FFMPEG = get_ffmpeg_exe()
SR = 24000

LIGHT_CUES = {
    "plucked": (108, "轻快拨弦"),
    "mallet": (114, "清脆木琴"),
}


@lru_cache(maxsize=96)
def note(sound, pitch):
    freq = 440 * 2**((pitch-69)/12)
    t = np.arange(round(.74*SR)) / SR
    phase = 2*np.pi*freq*t
    attack = np.minimum(1, t/.011)
    if sound == "plucked":
        wave = (np.sin(phase) + .34*np.sin(phase*2)*np.exp(-t/.22)
                + .20*np.sin(phase*3)*np.exp(-t/.09)
                + .10*np.sin(phase*4)*np.exp(-t/.045))
        return wave * attack * np.exp(-t/.17)
    wave = np.sin(phase) + .22*np.sin(phase*3.97)*np.exp(-t/.037)
    return wave * attack * np.exp(-t/.13)


def light_arrangement(size, style):
    bpm, _ = LIGHT_CUES[style]
    beat = 60/bpm
    rng = np.random.default_rng(bpm)
    bed = np.zeros((size, 2))

    def place(line, beat_time, level, pan):
        at = int(beat_time*beat*SR)
        line = line[:max(0, size-at)]
        if len(line):
            bed[at:at+len(line)] += line[:,None]*level*np.array((1-pan,1+pan))

    for bar in range(int(size/SR/(4*beat))+1):
        down = bar*4
        if style == "plucked":
            chords = ((53,60,65,69),(50,57,62,65),(46,53,58,62),(48,55,60,64))
            rhythm = ((.12,1),(.73,2),(1.51,3),(2.24,1),(2.84,2),(3.52,3))
        else:
            chords = ((60,64,67,72),(57,60,64,69),(53,57,60,65),(55,62,67,71))
            rhythm = ((.15,2),(.61,3),(1.24,1),(2.10,2),(2.73,3),(3.18,1))
        chord = chords[bar % len(chords)]
        place(note(style,chord[0]),down+.02,.46,-.12)
        pattern = rhythm if bar%2==0 else rhythm[:-1]
        for q,(when,i) in enumerate(pattern):
            off = 12 if style=="mallet" and (bar+q)%8==0 else 0
            place(note(style,chord[i]+off),down+when,float(rng.uniform(.21,.36)),.15*(-1)**q)
        # A short soft brush marks the offbeat without a constant high-frequency click.
        t = np.arange(round(SR*.064))/SR
        brush = rng.normal(0,.32,len(t))*np.minimum(1,t/.009)*np.exp(-t/.016)
        brush = sosfilt(butter(1,(490,2350),btype="bandpass",fs=SR,output="sos"),brush)
        for at in (1.52,3.50):
            place(brush,down+at,.075,.28)
    bed = sosfilt(butter(2,3500,fs=SR,output="sos"),bed,axis=0)
    bed *= .043 / max(1e-8,np.sqrt(np.mean(bed**2)))
    return bed


def ff(*arguments):
    return subprocess.check_output([str(FFMPEG), "-hide_banner", "-nostdin",
                                    "-v", "error", "-y", *map(str, arguments)])


def add_music(video, destination, speech, duration, style):
    sample_count = round(duration * SR)
    data = ff("-i", speech, "-vn", "-ac", 1, "-ar", SR, "-f", "f32le", "-")
    voice = np.frombuffer(data, dtype="<f4").astype("float64")[:sample_count]
    voice = np.pad(voice, (0, sample_count - len(voice)))
    voice = sosfilt(butter(2, 66, btype="highpass", fs=SR, output="sos"), voice)
    lengths = np.arange(0, sample_count, SR//50)
    starts = [(i, min(sample_count,i+SR//50)) for i in lengths]
    before = np.array([np.sqrt(np.mean(voice[a:b] ** 2)) for a,b in starts])
    active = before > max(.001, np.percentile(before, 76)*.22)
    if not active.any():
        raise ValueError("没有可用于混音的口播")
    voice *= min(3.5, .118 / np.sqrt(np.mean(before[active] ** 2)), .83/max(abs(voice)))
    level = np.array([np.sqrt(np.mean(voice[a:b] ** 2)) for a,b in starts])
    envelope = sosfilt(butter(1, 4, fs=50, output="sos"), np.clip(level/.028, 0, 1))
    with TemporaryDirectory(prefix="hanlin-native-voice-mix-") as folder:
        duck = np.interp(np.arange(sample_count), lengths, envelope)
        bed = light_arrangement(sample_count, style)
        bed *= .38 - .235 * duck[:, None]
        attribution = "Locally synthesized instrumental arrangement"
        fade = min(round(.40 * SR), sample_count)
        bed[:fade] *= np.linspace(.0,1.,fade)[:,None]
        fade = min(round(.68 * SR), sample_count)
        bed[-fade:] *= np.linspace(1.,.0,fade)[:,None]
        total = voice[:,None] + bed
        gain = min(1, .87 / np.max(abs(total)))
        total *= gain
        mixed = Path(folder) / "voice-and-music.wav"
        with wave.open(str(mixed), "wb") as wav:
            wav.setparams((2, 2, SR, 0, "NONE", ""))
            wav.writeframes(np.round(total*32767).astype("<i2").tobytes())
        stage = destination.with_suffix(".part.mp4")
        ff("-i", video, "-i", mixed, "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "copy", "-c:a", "aac", "-ar", 48000, "-b:a", "160k",
           "-metadata", "comment=" + attribution, "-movflags", "+faststart", stage)
        stage.replace(destination)
    report = {"seconds": duration, "music_rms_dbfs": round(20*np.log10(gain*np.sqrt(np.mean(bed**2))),2),
              "active_voice_rms_dbfs": round(20*np.log10(gain*np.sqrt(np.mean(level[active]**2))),2),
              "mix_peak_dbfs": round(20*np.log10(np.max(abs(total))),2),
              "music_source": attribution}
    report["bpm"], report["cue"] = LIGHT_CUES[style]
    destination.with_suffix(".混音记录.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
