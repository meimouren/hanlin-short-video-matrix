# 翰林短视频矩阵技能

这个仓库供接手制作的人和 AI 使用。有讲座原片时可以按项目命令剪出原声样片。有热点通知时可以写老师录制稿或做配音版。拿到仓库后，可以先从随附素材生成一条已有验收基准的纯动画样片。

## 先跑一条样片

在仓库根目录运行。Windows 已用 Python 3.10 与 Chrome 验证。升级版入口通过 [visual_engine.py](scripts/visual_engine.py) 驱动 Chromium Canvas 2D 白/翰林蓝/战绩红动效、外框连通透明 Logo、108 BPM 轻快拨弦与微音效，并自动生成 `966px / 864px` 手机裁切与 12 帧实帧总览：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements.txt
.\.venv\Scripts\python.exe -B -X utf8 scripts/render_aime_canvas.py --output preview-aime
```

输出目录必须是新目录。完成后打开 `AIME-视觉升级样片.mp4`，查看 `独立封面.png`、`视频首帧.jpg`、`字幕.srt`、`关键帧总览.jpg`、`手机裁切核对.jpg` 和混音记录。若仅做轻量离线校验（无 Chrome 时），也可运行传统 Pillow 入口 `scripts/render_aime.py --output preview-aime-basic`。渲染器以本机中文字体绘制，缺字体时见下方接手手册。

## 接一条新视频

| 手上的材料 | 下一步 | 首轮交付 |
|---|---|---|
| 老师录播、直播回放 | 转写全文和原始时间码，挑 3–5 个可单独成立的段落，再剪一条原声 | 选题单、1 条真实原声样片、独立封面 |
| 热点通知，希望老师亲录 | 核证据、检索全部同题材口播，写好断句和读音 | 可照读的口播稿、来源、分镜建议 |
| 热点通知，希望直接出片 | 核证据、写口播，用阿里云百炼 `qwen-audio-3.0-tts-plus` 生成干声，成片人声 1.1 倍，按实际时间做知识动画 | 1 条带音乐样片、独立封面、字幕和发布文案 |

1. AI 先读 [SKILL.md](SKILL.md)，再按任务打开 [接手手册](references/接手手册.md) 对照命令、文件和验收点。
2. [用户规则与验收表](references/用户规则与验收表.md) 对照用户每类要求、执行位置和验收证据。
3. [选风格与找素材](references/选风格与找素材.md) 列出 7 类正文、14 款封面及各自的适用题材、样片入口和替换项。

要跑真实录播、调用授权 IP 音色或批量制作，请接入翰林短视频矩阵工作区。原片、口播语料、平台凭证和批次工程由该工作区提供。共享资料库已有 [AIME 纯动画样片和封面](https://data.hanlin.com/#library/cases/hanlin-aime-two-channel-animation-20261127)。
