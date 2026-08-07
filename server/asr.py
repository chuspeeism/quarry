#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asr.py —— Quarry 统一转写管线（四件套产出）

输入一个本地视频/音频文件，产出：
  <base>.m4a          抽取的音频（与视频同目录）
  <base>.srt          毫秒级字幕
  <base>.口播词.md     纯文本口播词（带来源信息头）
  transcript 文本      行格式 "[MM:SS → MM:SS] 文本"，供入库与检索

转写引擎：火山引擎豆包 ASR（复用 video-speech-content skill 的脚本与凭证）。
环境变量 TV_ASR=volc|none 控制开关（默认 volc）。
失败不抛异常，返回 warnings，调用方降级处理。
"""

from __future__ import annotations

import json
import os
import re
import subprocess

ASR_ENGINE = os.environ.get("TV_ASR", "volc").lower()  # volc（失败自动落 groq）| groq | none
_SKILL_DIRS = [
    os.path.expanduser("~/.claude/skills/video-speech-content/scripts"),
    os.path.expanduser("~/.codex/skills/video-speech-content/scripts"),
    os.path.expanduser("~/.hermes/scripts"),
]
VOLC_SCRIPT_CANDIDATES = [os.path.join(d, "volcengine_asr.py") for d in _SKILL_DIRS]
GROQ_SCRIPT_CANDIDATES = [os.path.join(d, "groq_asr.py") for d in _SKILL_DIRS]
FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")
# 超过该时长（秒）不自动转写，避免长片阻塞导入；0 表示不限制
ASR_MAX_DURATION = int(
    os.environ.get("QUARRY_ASR_MAX_DURATION") or os.environ.get("TV_ASR_MAX_DURATION", "3600")
)


def _volc_script() -> str:
    for path in VOLC_SCRIPT_CANDIDATES:
        if os.path.exists(path):
            return path
    return ""


def _groq_script() -> str:
    for path in GROQ_SCRIPT_CANDIDATES:
        if os.path.exists(path):
            return path
    return ""


def media_duration(path: str) -> float:
    try:
        p = subprocess.run(
            [FFPROBE, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return float(p.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def has_audio_stream(path: str) -> bool:
    try:
        p = subprocess.run(
            [FFPROBE, "-v", "quiet", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30)
        return "audio" in p.stdout
    except Exception:  # noqa: BLE001
        return True  # 探测失败时仍尝试抽音


def extract_audio(video_path: str, out_base: str) -> dict:
    """抽出两份音频：m4a（四件套留档）+ mp3（ASR 上传用，压缩体积）。"""
    m4a = out_base + ".m4a"
    mp3 = out_base + ".asr.mp3"
    r1 = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", video_path, "-vn", "-c:a", "aac", "-b:a", "128k", m4a],
        capture_output=True, text=True, timeout=600)
    r2 = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", video_path, "-vn",
         "-acodec", "libmp3lame", "-ac", "1", "-ar", "16000", "-b:a", "48k", mp3],
        capture_output=True, text=True, timeout=600)
    return {
        "m4a": m4a if r1.returncode == 0 and os.path.exists(m4a) else "",
        "mp3": mp3 if r2.returncode == 0 and os.path.exists(mp3) else "",
        "error": (r2.stderr or r1.stderr or "").strip()[:200] if (r1.returncode or r2.returncode) else "",
    }


def run_volc_asr(audio_path: str) -> dict:
    """调用火山 ASR 脚本，返回 {utterances:[{start_time,end_time,text}], text}。"""
    script = _volc_script()
    if not script:
        raise RuntimeError("未找到 volcengine_asr.py 脚本")
    p = subprocess.run(
        ["python3", script, audio_path, "--mode", "standard", "--timestamps", "--json"],
        capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError(f"ASR 失败：{(p.stderr or '').strip()[-200:]}")
    data = json.loads(p.stdout)
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("ASR 返回结构异常")
    utterances = result.get("utterances")
    text = str(result.get("text") or "")
    if not isinstance(utterances, list):
        utterances = []
    return {"utterances": utterances, "text": text}


def run_groq_asr(audio_path: str) -> dict:
    """Groq Whisper 兜底（火山被 VPN/网络干扰时用）。返回同 run_volc_asr 结构。"""
    script = _groq_script()
    if not script:
        raise RuntimeError("未找到 groq_asr.py 脚本")
    p = subprocess.run(
        ["python3", script, audio_path, "--timestamps", "--json", "--language", "zh"],
        capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError(f"Groq ASR 失败：{(p.stderr or '').strip()[-200:]}")
    data = json.loads(p.stdout)
    segments = data.get("segments") if isinstance(data, dict) else None
    utterances = []
    if isinstance(segments, list):
        for s in segments:
            if not isinstance(s, dict):
                continue
            utterances.append({
                "start_time": int(float(s.get("start") or 0) * 1000),
                "end_time": int(float(s.get("end") or 0) * 1000),
                "text": str(s.get("text") or "").strip(),
            })
    return {"utterances": utterances, "text": str(data.get("text") or "")}


def run_asr(audio_path: str, warnings: list) -> dict:
    """按引擎设置执行转写：volc 优先，失败自动落 groq。"""
    if ASR_ENGINE == "groq":
        return run_groq_asr(audio_path)
    try:
        return run_volc_asr(audio_path)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"火山 ASR 失败，改用 Groq Whisper 兜底：{str(e)[:120]}")
        return run_groq_asr(audio_path)


def _fmt_clock(ms: int) -> str:
    total = int(ms) // 1000
    h, rem = divmod(total, 3600)
    mnt, sec = divmod(rem, 60)
    return f"{h:02d}:{mnt:02d}:{sec:02d}" if h else f"{mnt:02d}:{sec:02d}"


def _fmt_srt(ms: int) -> str:
    ms = int(ms)
    total, milli = divmod(ms, 1000)
    h, rem = divmod(total, 3600)
    mnt, sec = divmod(rem, 60)
    return f"{h:02d}:{mnt:02d}:{sec:02d},{milli:03d}"


def utterances_to_srt(utterances: list) -> str:
    blocks = []
    for i, u in enumerate(utterances, start=1):
        text = str(u.get("text") or "").strip()
        if not text:
            continue
        blocks.append(
            f"{i}\n{_fmt_srt(u.get('start_time', 0))} --> {_fmt_srt(u.get('end_time', 0))}\n{text}\n")
    return "\n".join(blocks)


def utterances_to_timeline(utterances: list) -> str:
    lines = []
    for u in utterances:
        text = str(u.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[{_fmt_clock(u.get('start_time', 0))} → {_fmt_clock(u.get('end_time', 0))}] {text}")
    return "\n".join(lines)


def build_koubo_md(title: str, source_link: str, plain_text: str, timeline: str) -> str:
    parts = [
        f"# 口播词：{title or '未命名'}",
        "",
        f"- 来源：{source_link or '（未记录）'}",
        "- 转写：火山引擎豆包 ASR（标准版，带时间戳）",
        "",
        "## 纯文本",
        "",
        plain_text or "（无口播内容）",
    ]
    if timeline:
        parts += ["", "## 分句时间轴", "", timeline]
    return "\n".join(parts) + "\n"


def transcribe_video(video_path: str, title: str = "", source_link: str = "") -> dict:
    """完整管线。返回：
    {transcript, srtPath, mdPath, audioPath, source, warnings:[]}
    路径为绝对路径；失败时 transcript 为空并给 warnings。
    """
    out = {"transcript": "", "srtPath": "", "mdPath": "", "audioPath": "",
           "source": "", "warnings": []}
    if ASR_ENGINE == "none":
        return out
    if not video_path or not os.path.exists(video_path):
        out["warnings"].append("转写跳过：媒体文件不存在")
        return out
    if not has_audio_stream(video_path):
        out["warnings"].append("转写跳过：媒体没有音轨")
        return out
    dur = media_duration(video_path)
    if ASR_MAX_DURATION and dur > ASR_MAX_DURATION:
        out["warnings"].append(f"转写跳过：时长 {int(dur)}s 超过上限 {ASR_MAX_DURATION}s")
        return out

    base = os.path.splitext(video_path)[0]
    audio = extract_audio(video_path, base)
    if not audio["mp3"]:
        out["warnings"].append(f"抽取音频失败：{audio['error'] or '未知错误'}")
        return out
    out["audioPath"] = audio["m4a"] or audio["mp3"]

    try:
        asr = run_asr(audio["mp3"], out["warnings"])
    except Exception as e:  # noqa: BLE001
        out["warnings"].append(f"ASR 转写失败：{e}")
        return out
    finally:
        # ASR 上传用的压缩 mp3 属于中间产物，转写后清理
        try:
            if audio["mp3"] and audio["m4a"] and os.path.exists(audio["mp3"]):
                os.remove(audio["mp3"])
        except Exception:  # noqa: BLE001
            pass

    plain = asr["text"] or " ".join(
        str(u.get("text") or "").strip() for u in asr["utterances"])
    plain = plain.strip()
    if not plain or not re.search(r"[\w一-鿿]", plain):
        out["warnings"].append("转写完成但没有识别到口播内容（可能是纯音乐/无人声）")
        return out

    timeline = utterances_to_timeline(asr["utterances"])
    out["transcript"] = timeline or plain
    out["source"] = "asr"

    srt = utterances_to_srt(asr["utterances"])
    if srt:
        srt_path = base + ".srt"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt)
        out["srtPath"] = srt_path

    md_path = base + ".口播词.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_koubo_md(title, source_link, plain, timeline))
    out["mdPath"] = md_path
    return out
