# 翰林短视频矩阵技能

这个仓库是独立可运行的短视频制作技能包与渲染工具集，支持两条核心路线：

1. **真人 IP 录播切片（于老师 AMC 升级版同款引擎）**：老师 `1.0x` 原声 + 白/翰林蓝/战绩红 Canvas 2D 知识动画 + `8x` 超采样随幕换位小圆窗 + `108 BPM` 轻快拨弦避让人声与微音效 + `124 px` 视频号安全区验片。
2. **双渠道纯动画热点（AIME 1.1 倍配音示范）**：顾问口语化校订 + 阿里云百炼 `qwen-audio-3.0-tts-plus` 1.1 倍字级对轴 + 六幕纯动画对照 + 3:4 独立封面精准贴标。

## 环境准备（Windows / macOS / Linux，已用 Python 3.10 + Chrome 验证）

```powershell
git clone https://github.com/meimouren/hanlin-short-video-matrix.git
cd hanlin-short-video-matrix
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements.txt
```

> 基础渲染与圆窗合成自带 `imageio-ffmpeg`，**无需**额外安装 `ffprobe`。如需跑本地离线语音转写，可再执行 `.\.venv\Scripts\python.exe -m pip install faster-whisper==1.2.1`；如需在线合成百炼 1.1 倍配音，设置环境变量 `DASHSCOPE_API_KEY`。

---

## 先跑两条零门槛升级标杆样片

### 1. 真人 IP 动态圆窗样板（于老师 AMC 同款布局与引擎）

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/render_ip_pip_demo.py --output preview-ip-pip
```

无需准备额外原片，脚本会即时合成一位虚拟主讲人与口播律动，演示四幕移位 `8x` 动态圆窗、首 `21` 帧 `3:4` 贴标封面静置、关键词高亮单行字幕、`108 BPM` 轻快拨弦混音及 `966px / 864px` 手机裁切自动 QA。  
输出：`真人IP圆窗-升级样片.mp4`、`独立封面.png`、`视频首帧.jpg`、`字幕.srt`、`关键帧总览.jpg`、`手机裁切核对.jpg`、混音记录。

拿到自己的老师实录净素材后，只需追加 `--clip` 与 `--timing` 即可直接套用：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/render_ip_pip_demo.py --output preview-real-ip --clip "净素材.mp4" --timing "净素材时间轴.json" --speaker "王老师"
```

### 2. AIME 双渠道纯动画样板（百炼 1.1x 配音引擎）

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/render_aime_canvas.py --output preview-aime
```

使用随包 AIME 干声与时间轴生成 `AIME-视觉升级样片.mp4`、`独立封面.png`、`视频首帧.jpg`、`字幕.srt`、`关键帧总览.jpg` 与 `手机裁切核对.jpg`。缺中文字体时，设置环境变量 `HANLIN_CJK_REGULAR` / `HANLIN_CJK_BOLD` 指向本机字体文件；若无 Chrome，也可运行传统 Pillow 入口 `scripts/render_aime.py --output preview-aime-basic`。

---

## 独立脚本工具箱

| 脚本 | 用途 | 额外依赖 / 说明 |
|---|---|---|
| [scripts/visual_engine.py](scripts/visual_engine.py) | 公共视觉引擎（Canvas 逐帧、8x 动态圆窗、外框去白贴标、动态避让配乐、手机安全区 QA） | 仅需 `scripts/requirements.txt` + Chrome |
| [scripts/render_ip_pip_demo.py](scripts/render_ip_pip_demo.py) | 真人 IP 动态圆窗样板与净素材渲染入口（搭配 [stage_ip_pip_demo.html](scripts/stage_ip_pip_demo.html)） | 开箱即跑 |
| [scripts/render_aime_canvas.py](scripts/render_aime_canvas.py) | AIME 双渠道纯动画升级版入口（搭配 [stage_aime_canvas.html](scripts/stage_aime_canvas.html)） | 开箱即跑 |
| [scripts/transcribe_lecture.py](scripts/transcribe_lecture.py) | 录播离线转写，生成带词级时间戳的 `原片转写.json` 与可读 `原片转写.txt` | 需安装 `faster-whisper==1.2.1` |
| [scripts/clip_lecture.py](scripts/clip_lecture.py) | 按 `cut`（起止区间）或 `batch`（选题单）剪出 `原声净素材.mp4`、纯轨与零起点时间轴 | 开箱即跑 |
| [scripts/check_copy.py](scripts/check_copy.py) | 口播去机械化与自然度只读体检（公文词、编号排比、`<=22` 字换气、尾句趋同） | 开箱即跑 |
| [scripts/tts_bailian.py](scripts/tts_bailian.py) | 阿里云百炼 `qwen-audio-3.0-tts-plus` 1.1 倍配音与字级时间轴导出（支持 `--dry-run`） | 在线合成需环境变量 `DASHSCOPE_API_KEY` |

---

## 同事接手必读导航

| 文档 | 内容 |
|---|---|
| [SKILL.md](SKILL.md) | 给 Claude Code / Codex / Antigravity 等编程 Agent 的全流程核心指令 |
| [真人 IP 录播切片工作流](references/真人IP录播切片工作流.md) | 复刻于老师 AMC 标杆的 7 步实战与**直接复制给 AI 助手的提示词模板** |
| [接手手册](references/接手手册.md) | 录播 / 老师实录 / 纯动画配音三条路线的逐命令执行手册 |
| [口播去机械化与润色规范](references/口播去机械化与润色规范.md) | 顾问口语规范、禁重尾句与自检清单 |
| [用户规则与验收表](references/用户规则与验收表.md) | 20 项成片硬指标与验收留证对照表 |
| [选风格与找素材](references/选风格与找素材.md) | 9 类视频正文结构与 14 款独立封面选型对照 |

> 要批量复用内部历年老师原片、历史口播语料与机构分发配置，请配合公司私有「翰林短视频矩阵工作区」。共享案例库见 [AIME 纯动画样片和封面](https://data.hanlin.com/#library/cases/hanlin-aime-two-channel-animation-20261127)。
