# 真人 IP 录播切片与动态圆窗工作流

把老师直播回放、课程录播或实拍口播，按**内容主导知识动画 + 8x 超采样动态小圆窗**标准剪成家长可直接看懂的竖屏短视频（对齐「于老师 AMC 进阶夏校·真人 IP 升级版」标杆）。

## 一、7 步标准化流水线

1. **全片语音识别与通读**
   - 用 `scripts/transcribe_lecture.py` 产出带词级时间戳的 `原片转写.json` 与通读文本 `原片转写.txt`。
   - AI 先通读口播全文，标出「家长问题 → 核心结论 → 前提/条件 → 例子/推导 → 结尾延展」，不遗漏数字、年级或资格限制等前提。
2. **剪出可独立成立的原声净素材**
   - 删掉多余寒暄、卡壳重录与需要前后半小时铺垫才能听懂的废话，保留 **1.0x 真实原声节奏**（禁止机器提速剪坏口型与语气）。
   - 运行 `scripts/clip_lecture.py cut` 导出 `原声净素材.mp4`、`原声纯轨.wav`、`净素材时间轴.json` 与 `字幕初稿.srt`。
3. **每幕设计一个「语义 → 视觉动作」对照**
   - 为每一幕写出 `原话锚点 → 观众该看懂的关系 → Canvas 画面动作`（例如：痛点红卡/反驳弹簧印章、三步流程串联、假期时间轴点亮、双路线对比与阶梯放大）。
   - 无现成课件时，严格按老师实际讲到的条件画图解，自拟数值须在画面标明「示意举例」。
4. **内容占主位 + 8x 超采样动态小圆窗（视觉核心规范）**
   - 调用 `scripts/visual_engine.py` 驱动 Chromium Canvas 2D，参考 `scripts/stage_ip_pip_demo.html`：
     - **高对比配色体系**：主背景 `#FFFFFF`，主双色翰林蓝 `#156BB1` / 战绩红 `#A41034`，浅底 `#E2F3FF` / `#FFEDF2`，高亮 `#1681D4` / `#CE2755`，深墨正文 `#102E4B` / 辅助字 `#395872`。
     - **视频号全局安全区**：画面主内容统一裁剪在 `g.rect(124, 0, 832, 1452)` 内，顶部 Logo 与账号胶囊留白 124 px；底部四段式章节进度条放在 `y=1276`，单行关键词高亮字幕卡放在 `y=1344..1436`，彻底清空 `y >= 1459` 狭窄作者交互区。
     - **四幕无遮挡圆窗槽位**：外径 `224 px`（内切 `214 px`，5 px 蓝渐变边框 + `8x` 超采样抗锯齿），默认随四幕切换在 `(828, 304) → (252, 304) → (828, 304) → (252, 1086)` 平滑淡出/淡入移位；HTML 背景预留对应位置白色阴影托底与名牌胶囊。
     - **首帧静置纪律**：第 0–20 帧（`0.70s`）全屏静止展示 `3:4` 独立封面，**小圆窗在前 21 帧保持完全隐藏**，第 21 帧随第一幕顺滑进入。
5. **独立 3:4 封面与精准贴标**
   - 用 AI 生图或设计工具出 `1080×1440` 3:4 独立封面，**左上角留足纯白区域**。
   - 使用 `extract_transparent_logo`（外框连通去白，完整保留蓝方块内白色 `lin` 笔画）+ `stamp_logo_on_cover` 程序化精确贴合机构透明商标。
6. **人声闪避轻配乐 + 节拍微音效**
   - 使用 `mix_audio_with_bgm_and_sfx` 混音：老师 `1.0x` 原声固定在最前，自动触发 `108 BPM` 轻快拨弦（`plucked`）或 `114 BPM` 清脆木琴（`mallet`）随说话能量平滑闪避压低（人声领先 BGM 约 20–22 dB），并在开场、转幕、反驳印章和关键结论瞬间叠加 `chime / pop / stamp` 微音效。
7. **自动帧级 QA + 双视口核对**
   - `verify_and_make_sheets` 自动核验参数、首 `21` 帧静置（`diff < 1.1`）、左右 `124 px` 纯白防溢色及底部静区，并输出 `关键帧总览.jpg` 与模拟 `966 px / 864 px` 视频号遮挡线的 `手机裁切核对.jpg`。

---

## 二、同事实操命令行流水线

拿到一条老师长录播 `lecture.mp4` 后，在技能仓根目录按顺序执行：

```powershell
# 0. 安装基础环境（只需一次；若需本地转写额外安装 faster-whisper==1.2.1）
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements.txt

# 1. 可选：离线语音转写，找出值得拆条的精彩段落与时间码
.\.venv\Scripts\python.exe -m pip install faster-whisper==1.2.1
.\.venv\Scripts\python.exe -B -X utf8 scripts/transcribe_lecture.py "lecture.mp4" "work/asr" --terms "AMC,AIME,数学夏校"

# 2. 按起止秒数剪出 1.0x 原声净素材并生成零起点时间轴与字幕初稿
.\.venv\Scripts\python.exe -B -X utf8 scripts/clip_lecture.py cut `
  --media "lecture.mp4" --start 3892.0 --end 3924.75 `
  --transcript "work/asr/原片转写.json" --output "work/net-clip"

# 3. 检查配套文案是否机械化 / 超 22 字无换气长句
.\.venv\Scripts\python.exe -B -X utf8 scripts/check_copy.py "work/net-clip/字幕初稿.srt"

# 4. 用净素材直接套用或由 AI 改写 Canvas 舞台后渲染成片
.\.venv\Scripts\python.exe -B -X utf8 scripts/render_ip_pip_demo.py `
  --output "work/out" `
  --clip "work/net-clip/原声净素材.mp4" `
  --timing "work/net-clip/净素材时间轴.json" `
  --speaker "主讲老师" `
  --music plucked
```

> 若暂未传 `--cover`，脚本会自动按白/蓝/红标准绘制 3:4 示范独立封面并用 `stamp_logo_on_cover` 贴合透明商标；若传入老师真人 3:4 封面图，可加 `--cover "my-cover.png" --stamp-logo` 自动完成左上角精准贴标。

---

## 三、给同事的 AI 编程助手提示词模板

在使用 Claude Code / Codex / Antigravity 打开本仓库时，把老师原片放进目录并发送下面这段指令，即可让 AI 按「于老师 AMC 标杆」自动完成审听、出稿、定制分镜、合成圆窗与验片：

```text
请先读取当前仓库的 SKILL.md、references/真人IP录播切片工作流.md 和 scripts/visual_engine.py。
我这里有一段老师讲解视频：【填写文件名与开始-结束时间，或整场转写要求】，老师称呼为【XX老师】，需要输出【视频号 124px 安全版 / 抖音 24px 版】。

请按以下要求制作：
1. 先用 scripts/transcribe_lecture.py 和 scripts/clip_lecture.py 剪出 1.0x 原声净素材与零起点时间轴，校对中英文术语、数字和单行断句字幕。
2. 参照 scripts/stage_ip_pip_demo.html 的白/翰林蓝/战绩红高对比规范与 g.rect(124,0,832,1452) 视频号净区，围绕这位老师的真实原话结构重写 Canvas 2D 分镜 HTML（不要直接套旧文字，要让每一句重点话触发对应卡片、对比、日历或阶梯动作）。
3. 调用 scripts/visual_engine.py 的 render_canvas_stage + composite_dynamic_circle_pip（8x 超采样动态圆窗，前 21 帧封面静置期间隐藏，随幕换位不压重点信息）+ mix_audio_with_bgm_and_sfx（108 BPM plucked 轻快拨弦避让人声 + 微音效）+ verify_and_make_sheets 自动生成成片与手机裁切核对图。
4. 完成后把关键帧总览.jpg 和 手机裁切核对.jpg 呈现给我确认。
```
