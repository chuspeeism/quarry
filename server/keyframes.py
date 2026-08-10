#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关键帧抽取：给每条视频抽一组静帧，让只能读图文的消费方也能看到视频内容。

策略是**均匀抽帧**，不是场景切换检测。这是实测结论，不是省事：

    同一条 3 分钟视频（fable5 #6，说话人 + 文字卡片）
    均匀抽帧      6 帧，抓到 4 张信息卡片
    场景切换抽帧  7 帧，全是同一机位的说话人，一张卡片没抓到

原因是这类内容机位根本不切。信息在叠加的文字卡上，一张卡出现时只改变画面一小块
区域，整帧像素差异够不到 scene 阈值；而 select='gt(scene,N)' 恰好只认整帧突变。
场景检测还要解码全片算差异，3 分钟的片子跑 16 秒，均匀抽帧是秒出。

产出与视频同目录：<base>.关键帧/001.jpg …
"""

from __future__ import annotations

import os
import shutil
import subprocess

FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")

FRAMES_SUFFIX = ".关键帧"
# 抽帧张数：一分钟以内 4 张，之后每 30 秒加 1 张，上限 12 张。
BASE_FRAMES = 4
SECONDS_PER_EXTRA = 30
MAX_FRAMES = 12
# 长边缩到这个尺寸。够看清文字卡，又不至于让一条视频的帧比视频还大。
FRAME_WIDTH = 960
JPEG_QUALITY = "4"


def frame_count(duration: float) -> int:
    if duration <= 0:
        return BASE_FRAMES
    extra = max(0.0, duration - 60) // SECONDS_PER_EXTRA
    return int(min(MAX_FRAMES, BASE_FRAMES + extra))


def _duration(path: str) -> float:
    try:
        p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path],
                           capture_output=True, text=True, timeout=30)
        return float((p.stdout or "").strip())
    except Exception:  # noqa: BLE001
        return 0.0


def frames_dir(video_path: str) -> str:
    return os.path.splitext(video_path)[0] + FRAMES_SUFFIX


def extract(video_path: str, force: bool = False) -> dict:
    """抽帧。返回 {dir, frames:[路径…], count, duration, warnings:[]}。

    逐帧用 `-ss` 放在 `-i` 前做输入端 seek——直接跳到关键帧位置解码一张，不走全片。
    16 分钟 172MB 那条按整片解码要几十秒，按输入端 seek 是每帧几十毫秒。
    """
    out = {"dir": "", "frames": [], "count": 0, "duration": 0.0, "warnings": []}
    if not video_path or not os.path.exists(video_path):
        out["warnings"].append("抽帧跳过：视频文件不存在")
        return out

    dur = _duration(video_path)
    out["duration"] = dur
    target = frames_dir(video_path)

    if os.path.isdir(target) and not force:
        existing = sorted(f for f in os.listdir(target) if f.endswith(".jpg"))
        if existing:
            out["dir"] = target
            out["frames"] = [os.path.join(target, f) for f in existing]
            out["count"] = len(existing)
            return out

    n = frame_count(dur)
    if os.path.isdir(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target, exist_ok=True)

    made = []
    for i in range(n):
        # 取每段的中点，避开片头片尾常见的黑帧与转场。
        pos = dur * (i + 0.5) / n if dur > 0 else 0
        dst = os.path.join(target, f"{i + 1:03d}.jpg")
        r = subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-ss", f"{pos:.3f}", "-i", video_path,
             "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", JPEG_QUALITY, dst],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
            made.append(dst)
        elif r.stderr.strip():
            out["warnings"].append(f"第 {i + 1} 帧抽取失败：{r.stderr.strip()[:120]}")

    if not made:
        shutil.rmtree(target, ignore_errors=True)
        out["warnings"].append("抽帧失败：没有产出任何帧")
        return out

    out["dir"] = target
    out["frames"] = made
    out["count"] = len(made)
    return out
