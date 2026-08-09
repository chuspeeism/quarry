#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Topic Post Vault / 课题帖子库 —— 本地 X/Twitter 课题收藏器后端服务

能力：
- 前端复用磁盘上的 index.html（运行时注入 /api/posts 加载逻辑 + 课题/链接输入框，磁盘文件不改动）
- 输入一个 X/Twitter 链接 -> opencli 抓正文/作者/时间/media_urls -> 直链下载媒体 ->
  codex exec 异步生成 中文标题/中文正文/摘要/关键词 -> 持久化加入列表
- 异步两段式：先把原文卡片加入并展示，中文区显示「AI 加工中」，完成后自动补全

接口：
  GET    /                    Frost 前端
  GET    /api/topics          列出课题 {topics:[...]}
  POST   /api/topics          创建课题 {name,id?}
  PATCH  /api/topics/<id>     编辑课题 {name?,description?}
  DELETE /api/topics/<id>     删除课题（非空需 ?force=1）
  GET    /api/posts           列出帖子 {posts:[...]}，支持 ?topic=<id>
  PATCH  /api/posts/<uid>     编辑帖子 {title?,body?,summary?,keywords?,supplement?}
  DELETE /api/posts/<uid>     删除帖子（?media=1 连本地媒体一起删）
  POST   /api/add             单条 {url,topic?} -> {taskId}；批量 {urls:[...]} 或多行 url -> {tasks:[...]}
  GET    /api/task/<id>       轮询任务状态

转写：视频类内容自动走 ASR 四件套（mp4+m4a+srt+口播词.md），见 asr.py；TV_ASR=none 关闭。

数据：
  data/posts.json        v2 持久化课题与帖子；首启从 post_content_dataset.json 种子导入
  data/media/            新帖下载的媒体

环境变量：
  PORT(默认6002) AI_ENGINE(codex|ark|none, 默认codex) OPENCLI_BIN CODEX_BIN
  ARK_API_KEY ARK_MODEL(默认 doubao-seed-1-6-250615) 用于 AI_ENGINE=ark
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import uuid
from datetime import timedelta
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, unquote

import asr as asr_pipeline

# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------
# 产品层：只放代码，不放任何采集到的内容。
HERE = os.path.dirname(os.path.abspath(__file__))       # <repo>/server
REPO_ROOT = os.path.dirname(HERE)                       # <repo>
APP_ROOT = os.path.join(REPO_ROOT, "app")               # 前端静态资源
INDEX_HTML = os.path.join(APP_ROOT, "index.html")


def _main_repo_root() -> str:
    """主仓库根目录。

    git worktree 里 REPO_ROOT 指向 <repo>/.claude/worktrees/<name>/，按它取同级 ../vault
    会算到 worktrees/vault —— 既不是真的内容层，还落在仓库目录里面。用 git 的 common-dir
    反推主仓库位置：worktree 里返回主仓库的 <repo>/.git，普通仓库里返回相对的 .git，
    两种都能 join 回 <repo>。非 git 仓库（下载 zip）或 git 不可用时退回 REPO_ROOT。
    """
    try:
        proc = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "--git-common-dir"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return REPO_ROOT
    if proc.returncode != 0 or not proc.stdout.strip():
        return REPO_ROOT
    root = os.path.dirname(os.path.abspath(os.path.join(REPO_ROOT, proc.stdout.strip())))
    # 认领前先自证：主仓库里必须有这份代码本身，否则宁可用 REPO_ROOT。
    return root if os.path.isfile(os.path.join(root, "server", "server.py")) else REPO_ROOT


# 内容层：与产品层彻底分离，默认落在主仓库同级的 ../vault，可用 QUARRY_VAULT 指到任意位置。
VAULT_ROOT = os.path.abspath(
    os.environ.get("QUARRY_VAULT")
    or os.path.join(os.path.dirname(_main_repo_root()), "vault")
)
DATA_DIR = os.path.join(VAULT_ROOT, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
POSTS_FILE = os.path.join(DATA_DIR, "posts.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
V1_BACKUP_FILE = os.path.join(BACKUP_DIR, "posts.v1.bak.json")
V2_BACKUP_FILE = os.path.join(BACKUP_DIR, "posts.v2.bak.json")
# 可选：历史迁移用的一次性种子，缺失时直接空库启动。
SEED_FILE = os.path.join(
    VAULT_ROOT,
    "outputs",
    "handoffs",
    "2026-06-10_codex_制作Twitter帖子浏览器_019eaf90_share",
    "post_content_dataset.json",
)

PORT = int(os.environ.get("PORT", "6002"))
OPENCLI = os.environ.get("OPENCLI_BIN", "opencli")
CODEX = os.environ.get("CODEX_BIN", "codex")
AI_ENGINE = os.environ.get("AI_ENGINE", "codex").lower()  # codex | ark | none
ARK_MODEL = os.environ.get("ARK_MODEL", "doubao-seed-1-6-250615")
ARK_BASE = os.environ.get("ARK_BASE", "https://ark.cn-beijing.volces.com/api/v3")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATA_VERSION = 3
DEFAULT_TOPIC_ID = os.environ.get("QUARRY_DEFAULT_TOPIC_ID", "inbox")
DEFAULT_TOPIC = {
    "id": DEFAULT_TOPIC_ID,
    "name": os.environ.get("QUARRY_DEFAULT_TOPIC_NAME", "未归类"),
    "description": "尚未指定课题的内容默认落在这里，之后可以再拆到具体课题。",
}
STAGE_PROGRESS = {
    "pending": 5,
    "detecting": 12,
    "fetching": 25,
    "downloading": 45,
    "transcribing": 65,
    "writing": 75,
    "ai": 88,
    "done": 100,
}
TRANSCRIPT_LIMIT = 16 * 1024
RAW_META_LIMIT = 80

LOCK = threading.RLock()
TOPICS: list = []     # 课题列表
POSTS: list = []      # 帖子列表（前端字段结构）
TASKS: dict = {}      # taskId -> {stage, progress, message, postId, topic, warnings}
# 导入任务并发闸：多条链接同时粘贴时避免 opencli 浏览器桥/ASR 互相争抢
IMPORT_SEM = threading.Semaphore(
    int(os.environ.get("QUARRY_IMPORT_CONCURRENCY") or os.environ.get("TV_IMPORT_CONCURRENCY", "2"))
)

# ---------------------------------------------------------------------------
# 帖子存取 + 种子
# ---------------------------------------------------------------------------

def _ensure_dirs():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)


def _as_list(v):
    return v if isinstance(v, list) else []


def now_ts() -> int:
    return int(time.time())


def slugify_topic(value: str) -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"\s+", "-", raw)
    raw = re.sub(r"[^a-z0-9._-]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-._")
    return raw[:50]


def valid_topic_id(topic_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,49}", topic_id or ""))


def topic_exists(topic_id: str) -> bool:
    return any(t.get("id") == topic_id for t in TOPICS)


def first_topic_id() -> str:
    return (TOPICS[0]["id"] if TOPICS else DEFAULT_TOPIC_ID)


def make_default_topic() -> dict:
    ts = now_ts()
    return {**DEFAULT_TOPIC, "createdAt": ts, "updatedAt": ts}


def normalize_topic(topic: dict) -> dict:
    ts = now_ts()
    topic_id = slugify_topic(str(topic.get("id") or topic.get("name") or DEFAULT_TOPIC_ID))
    if not valid_topic_id(topic_id):
        topic_id = DEFAULT_TOPIC_ID
    return {
        "id": topic_id,
        "name": str(topic.get("name") or topic_id).strip(),
        "description": str(topic.get("description") or "").strip(),
        "createdAt": int(topic.get("createdAt") or ts),
        "updatedAt": int(topic.get("updatedAt") or ts),
    }


def slugify_post_id(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return slug[:80] or uuid.uuid4().hex[:12]


def make_uid(topic_id: str, post: dict) -> str:
    key = str(post.get("tweetId") or "").strip()
    if not key:
        key = slugify_post_id(post.get("id") or post.get("sourceFile") or post.get("file") or post.get("sourceLink"))
    return f"{topic_id}__{key}"


def make_platform_uid(topic_id: str, platform: str, external_id: str) -> str:
    return f"{topic_id}__{platform}__{slugify_post_id(external_id)}"


def normalize_post(post: dict, topic_id: str = DEFAULT_TOPIC_ID) -> dict:
    p = dict(post)
    p["topic"] = str(p.get("topic") or topic_id)
    p["tweetId"] = str(p.get("tweetId") or "")
    p["platform"] = str(p.get("platform") or "x")
    p["externalId"] = str(p.get("externalId") or p.get("tweetId") or p.get("uid") or p.get("id") or "")
    p["contentType"] = str(p.get("contentType") or ("post" if p["platform"] == "x" else "video"))
    p["downloadStatus"] = str(p.get("downloadStatus") or ("success" if p.get("mediaPath") or p.get("imagePath") else "skipped"))
    p["transcript"] = truncate_text(str(p.get("transcript") or ""))
    for key in ("transcriptSrtPath", "transcriptMdPath", "audioPath", "transcriptSource"):
        p[key] = str(p.get(key) or "")
    p["rawMeta"] = p.get("rawMeta") if isinstance(p.get("rawMeta"), dict) else {}
    uid = str(p.get("uid") or make_uid(p["topic"], p))
    p["uid"] = uid
    p["id"] = uid
    p["keywords"] = _as_list(p.get("keywords"))
    p["articleLinks"] = _as_list(p.get("articleLinks"))
    if "aiStatus" not in p:
        p["aiStatus"] = "ready"
    return p


def topic_counts() -> dict:
    counts = {}
    for p in POSTS:
        tid = p.get("topic") or DEFAULT_TOPIC_ID
        counts[tid] = counts.get(tid, 0) + 1
    return counts


def public_topics() -> list:
    counts = topic_counts()
    return [{**t, "postCount": counts.get(t["id"], 0)} for t in TOPICS]


def truncate_text(text: str, limit: int = TRANSCRIPT_LIMIT) -> str:
    text = text or ""
    return text if len(text.encode("utf-8")) <= limit else text.encode("utf-8")[:limit].decode("utf-8", "ignore") + "\n（已截断）"


def compact_meta(platform: str, meta: dict) -> dict:
    if not isinstance(meta, dict):
        return {}
    allowed = {
        "x": {"id", "author", "text", "created_at", "url", "likes", "retweets", "media_urls"},
        "bilibili": {"bvid", "aid", "cid", "title", "author", "owner", "duration", "stat", "pic", "thumbnail", "desc", "description", "publish_time", "canonicalUrl"},
        "xiaohongshu": {"noteId", "title", "desc", "author", "likedCount", "collectedCount", "commentCount", "canonicalUrl"},
        "douyin": {"awemeId", "desc", "author", "shareUrl", "canonicalUrl"},
    }.get(platform, set())
    out = {}
    for key in allowed:
        if key in meta:
            val = meta[key]
            if isinstance(val, (str, int, float, bool)) or val is None:
                out[key] = val
            elif isinstance(val, (list, dict)):
                out[key] = json.dumps(val, ensure_ascii=False)[:RAW_META_LIMIT * 20]
    return out


def normalize_opencli_kv(data):
    if isinstance(data, dict):
        return data
    if not isinstance(data, list):
        return {}
    out = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        if "field" in item and "value" in item:
            out[str(item["field"])] = item["value"]
        elif "key" in item and "value" in item:
            out[str(item["key"])] = item["value"]
        else:
            out.update(item)
    return out


def relpath(path: str) -> str:
    """内容层文件 -> 前端可用的相对 URL（始终相对 VAULT_ROOT）。"""
    return os.path.relpath(path, VAULT_ROOT).replace(os.sep, "/")


def snapshot_files(directory: str) -> set:
    if not os.path.isdir(directory):
        return set()
    found = set()
    for root, _, files in os.walk(directory):
        for file in files:
            found.add(os.path.join(root, file))
    return found


def collect_downloaded_files(directory: str, before=None) -> list:
    before = before or set()
    after = snapshot_files(directory)
    files = [p for p in after - before if os.path.isfile(p)]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files


def classify_local_file(path: str) -> str:
    ext = os.path.splitext(path.lower())[1]
    if ext in (".mp4", ".mov", ".m4v"):
        return "video"
    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        return "image"
    return "other"


def ensure_unique_topics(topics: list) -> list:
    seen = set()
    out = []
    for raw in topics:
        t = normalize_topic(raw)
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    if not out:
        out.append(make_default_topic())
    return out


def seed_from_dataset() -> list:
    """从 post_content_dataset.json(.posts) 映射成前端字段结构。"""
    with open(SEED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    src = data.get("posts", [])
    out = []
    for p in src:
        post = {
            "id": str(p.get("id") or p.get("tweetId") or p.get("sourceFile") or ""),
            "file": p.get("sourceFile", ""),
            "title": p.get("title", ""),
            "number": p.get("number", 999),
            "tweetId": str(p.get("tweetId") or ""),
            "author": p.get("author", ""),
            "handle": p.get("handle", ""),
            "published": p.get("published", ""),
            "body": p.get("chinese", ""),
            "summary": p.get("summary", ""),
            "originalText": p.get("original", ""),
            "originalIsExcerpt": bool(p.get("originalIsExcerpt", False)),
            "originalNote": p.get("originalNote", ""),
            "keywords": _as_list(p.get("keywords")),
            "supplement": p.get("supplement", ""),
            "sourceLink": p.get("sourceLink", ""),
            "mediaPath": p.get("mediaPath", ""),
            "mediaName": p.get("mediaName", ""),
            "imagePath": p.get("imagePath", ""),
            "articleLinks": _as_list(p.get("articleLinks")),
            "aiStatus": "ready",
            "source": "seed",
        }
        out.append(normalize_post(post, DEFAULT_TOPIC_ID))
    return out


def load_posts():
    global POSTS, TOPICS
    _ensure_dirs()
    if os.path.exists(POSTS_FILE):
        with open(POSTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw_posts = data.get("posts", [])
        raw_topics = data.get("topics")
        if data.get("version") == DATA_VERSION and isinstance(raw_topics, list):
            TOPICS = ensure_unique_topics(raw_topics)
            POSTS = [normalize_post(p, p.get("topic") or first_topic_id()) for p in raw_posts]
            print(f"[posts] 已加载 v{DATA_VERSION}：{len(POSTS)} 条 / {len(TOPICS)} 个课题（{POSTS_FILE}）")
        else:
            version = data.get("version") or 1
            backup = V2_BACKUP_FILE if version == 2 else V1_BACKUP_FILE
            if not os.path.exists(backup):
                shutil.copy2(POSTS_FILE, backup)
                print(f"[posts] 已备份 v{version} 数据 -> {backup}")
            TOPICS = ensure_unique_topics(raw_topics if isinstance(raw_topics, list) else [make_default_topic()])
            POSTS = [normalize_post(p, p.get("topic") or first_topic_id()) for p in raw_posts]
            save_posts()
            print(f"[posts] 已迁移 v{version} -> v{DATA_VERSION}：{len(POSTS)} 条 / {len(TOPICS)} 个课题")
        return
    # 首启：内容层为空是正常状态，只有存在历史种子文件时才导入。
    TOPICS = [make_default_topic()]
    POSTS = []
    if os.path.exists(SEED_FILE):
        try:
            POSTS = seed_from_dataset()
            print(f"[posts] 首次启动，已从种子导入 {len(POSTS)} 条 -> {POSTS_FILE}")
        except Exception as e:  # noqa: BLE001
            POSTS = []
            print(f"[posts] 种子导入失败：{e}")
    else:
        print(f"[posts] 内容层为空，已初始化空库 -> {POSTS_FILE}")
    save_posts()


def save_posts():
    tmp = POSTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": DATA_VERSION, "count": len(POSTS), "topics": TOPICS, "posts": POSTS}, f,
                  ensure_ascii=False, indent=2)
    os.replace(tmp, POSTS_FILE)


def next_number(topic_id: str) -> int:
    nums = [p.get("number", 0) for p in POSTS
            if p.get("topic") == topic_id and isinstance(p.get("number"), int) and p["number"] < 900]
    return (max(nums) + 1) if nums else 1


def find_by_topic_tweetid(topic_id: str, tid: str):
    for p in POSTS:
        if p.get("topic") == topic_id and tid and str(p.get("tweetId")) == str(tid):
            return p
    return None


def find_by_content_key(topic_id: str, platform: str, external_id: str):
    for p in POSTS:
        if (
            p.get("topic") == topic_id
            and p.get("platform") == platform
            and external_id
            and str(p.get("externalId")) == str(external_id)
        ):
            return p
    return None


# ---------------------------------------------------------------------------
# 任务状态
# ---------------------------------------------------------------------------

def set_task(task_id, **kw):
    with LOCK:
        t = TASKS.setdefault(task_id, {
            "taskId": task_id,
            "stage": "pending",
            "progress": STAGE_PROGRESS["pending"],
            "warnings": [],
        })
        stage = kw.get("stage")
        if stage in STAGE_PROGRESS and "progress" not in kw:
            kw["progress"] = STAGE_PROGRESS[stage]
        t.update(kw)


def get_task(task_id):
    with LOCK:
        return dict(TASKS.get(task_id, {"taskId": task_id, "stage": "unknown", "progress": 0, "warnings": []}))


# ---------------------------------------------------------------------------
# opencli / codex / ark 调用
# ---------------------------------------------------------------------------

def extract_tweet_id(url: str) -> str:
    m = re.search(r"/status/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(\d{10,25})", url)
    return m.group(1) if m else ""


def resolve_redirect(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.geturl() or url
    except Exception:  # noqa: BLE001
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.geturl() or url
        except Exception:  # noqa: BLE001
            return url


def extract_bvid(url: str) -> str:
    m = re.search(r"(BV[0-9A-Za-z]+)", url)
    return m.group(1) if m else ""


def extract_xhs_id(url: str) -> str:
    m = re.search(r"/(?:explore|discovery/item|item)/([0-9a-zA-Z]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"source=note&noteId=([0-9a-zA-Z]+)", url)
    return m.group(1) if m else slugify_post_id(url)


def extract_douyin_id(url: str) -> str:
    m = re.search(r"(?:video|note)/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"modal_id=(\d+)", url)
    if m:
        return m.group(1)
    return slugify_post_id(url)


def detect_platform(url: str) -> dict:
    resolved = resolve_redirect(url) if any(host in url for host in ("b23.tv", "xhslink.com", "v.douyin.com")) else url
    host = urlparse(resolved).netloc.lower()
    if "bilibili.com" in host or "b23.tv" in host:
        external_id = extract_bvid(resolved) or slugify_post_id(resolved)
        return {"platform": "bilibili", "externalId": external_id, "canonicalUrl": resolved}
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return {"platform": "xiaohongshu", "externalId": extract_xhs_id(resolved), "canonicalUrl": resolved}
    if "douyin.com" in host or "iesdouyin.com" in host:
        return {"platform": "douyin", "externalId": extract_douyin_id(resolved), "canonicalUrl": resolved}
    if "x.com" in host or "twitter.com" in host:
        tid = extract_tweet_id(resolved)
        return {"platform": "x", "externalId": tid, "canonicalUrl": resolved}
    return {"platform": "unknown", "externalId": slugify_post_id(resolved), "canonicalUrl": resolved}


def run_opencli_site(site: str, args, timeout=120):
    cmd = [OPENCLI, site] + args
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL,
                          cwd=VAULT_ROOT)


def run_opencli(args, timeout=120):
    return run_opencli_site("twitter", args, timeout=timeout)


def fetch_thread(tid: str):
    p = run_opencli(["thread", tid, "--limit", "1", "-f", "json",
                     "--window", "background"])
    if p.returncode != 0:
        raise RuntimeError(f"opencli thread 失败(exit {p.returncode}): {p.stderr[:200]}")
    data = json.loads(p.stdout)
    if not isinstance(data, list) or not data:
        raise RuntimeError("opencli thread 未返回帖子")
    return data[0]


def fetch_article(tid: str):
    p = run_opencli(["article", tid, "-f", "json", "--window", "background"])
    if p.returncode != 0:
        return None
    try:
        d = json.loads(p.stdout)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(d, list):
        d = d[0] if d else None
    return d


def format_published(created_at: str) -> str:
    try:
        dt = parsedate_to_datetime(created_at)
        utc = dt.strftime("%Y-%m-%d %H:%M:%S")
        bj = (dt + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        return f"{utc} UTC；北京时间 {bj}"
    except Exception:  # noqa: BLE001
        return created_at or ""


def classify_media(url: str, ctype: str):
    u = url.lower()
    if "video" in ctype or ".mp4" in u or "video.twimg" in u:
        return "video", "mp4"
    if "png" in ctype or u.endswith(".png"):
        return "image", "png"
    if "webp" in ctype or ".webp" in u:
        return "image", "webp"
    if "image" in ctype or any(e in u for e in (".jpg", ".jpeg")) or "pbs.twimg" in u:
        return "image", "jpg"
    return ("video", "mp4") if "video.twimg" in u else ("image", "jpg")


def download_media(url: str, tid: str, idx: int, headers: dict | None = None) -> dict:
    """直链下载单个媒体，返回 {kind, path, name}；失败抛异常。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=90) as resp:
        ctype = resp.headers.get("Content-Type", "")
        blob = resp.read()
    if not blob:
        raise RuntimeError("空响应")
    kind, ext = classify_media(url, ctype)
    name = f"{tid}_{idx}.{ext}"
    with open(os.path.join(MEDIA_DIR, name), "wb") as f:
        f.write(blob)
    return {"kind": kind, "path": f"data/media/{name}", "name": name,
            "size": len(blob)}


# --- AI ---------------------------------------------------------------------

AI_PROMPT_TMPL = (
    "你是多平台内容收藏器的中文卡片整理助手。下面是一条来自 {platform} 的内容材料"
    "（可能包含标题、正文、字幕、平台总结或链接）。\n"
    "请仅输出一个 JSON 对象，不要任何解释、不要使用任何工具、不要读写文件、不要使用 markdown 代码块。\n"
    "字段要求：\n"
    "- title: 一个简洁中文标题（不超过20字，不要加\"帖子\"前缀）\n"
    "- chinese: 完整、通顺的中文内容卡片（中文平台则整理要点，外文内容则翻译并整理；保留关键事实与换行）\n"
    "- summary: 两句话的中文摘要\n"
    "- keywords: 由3个中文关键词组成的数组\n"
    "作者：@{handle}\n"
    "材料：\n\"\"\"\n{text}\n\"\"\"\n"
)


def _extract_json(text: str):
    if not text:
        return None
    # 去掉可能的 ```json 包裹
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:  # noqa: BLE001
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def ai_codex(text: str, handle: str, platform: str = "x"):
    prompt = AI_PROMPT_TMPL.format(handle=handle, text=text, platform=platform)
    p = subprocess.run([CODEX, "exec", "--skip-git-repo-check", prompt],
                       capture_output=True, text=True, timeout=240,
                       stdin=subprocess.DEVNULL, cwd=VAULT_ROOT)
    return _extract_json(p.stdout)


def ai_ark(text: str, handle: str, platform: str = "x"):
    key = os.environ.get("ARK_API_KEY")
    if not key:
        return None
    prompt = AI_PROMPT_TMPL.format(handle=handle, text=text, platform=platform)
    body = json.dumps({
        "model": ARK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        ARK_BASE.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        d = json.loads(resp.read())
    content = d["choices"][0]["message"]["content"]
    return _extract_json(content)


def run_ai(text: str, handle: str, platform: str = "x"):
    try:
        if AI_ENGINE == "codex":
            return ai_codex(text, handle, platform)
        if AI_ENGINE == "ark":
            return ai_ark(text, handle, platform)
    except Exception as e:  # noqa: BLE001
        print(f"[ai] 失败：{e}")
    return None


# ---------------------------------------------------------------------------
# 添加链接的处理流程（后台线程）
# ---------------------------------------------------------------------------

def process_add_x(task_id: str, url: str, topic_id: str, detected: dict):
    try:
        set_task(task_id, stage="fetching", topic=topic_id, message="正在抓取推文正文与作者信息")
        tid = detected.get("externalId") or extract_tweet_id(url)
        if not tid:
            raise RuntimeError("无法从链接解析出推文 ID")

        # 同课题去重：已存在则定位，绝不改动现有数据；跨课题允许收藏同一 tweetId
        with LOCK:
            existing = find_by_content_key(topic_id, "x", tid) or find_by_topic_tweetid(topic_id, tid)
        if existing:
            set_task(task_id, stage="done", postId=existing["id"], topic=topic_id,
                     message="该帖已在该课题中，已为你定位。", warnings=[])
            return

        # 1) 抓正文
        item = fetch_thread(tid)
        text = (item.get("text") or "").strip()
        username = item.get("author") or ""
        created = item.get("created_at") or ""
        media_urls = _as_list(item.get("media_urls"))
        canonical = item.get("url") or url

        article = None
        if not text and not media_urls:
            set_task(task_id, stage="fetching", topic=topic_id, message="尝试作为长文抓取…")
            article = fetch_article(tid)
            if article:
                text = (article.get("content") or "").strip()

        # 2) 下载媒体（逐项判定，失败记录 warning）
        set_task(task_id, stage="downloading", topic=topic_id, message="正在下载媒体")
        warnings = []
        remote = []
        media_path = media_name = image_path = ""
        for i, u in enumerate(media_urls, start=1):
            try:
                m = download_media(u, tid, i)
                if m["kind"] == "video" and not media_path:
                    media_path, media_name = m["path"], m["name"]
                elif m["kind"] == "image" and not image_path:
                    image_path = m["path"]
            except Exception as e:  # noqa: BLE001
                warnings.append(f"媒体下载失败：{u[:70]} ({e})")
                remote.append(u)
        if media_urls and not media_path and not image_path:
            warnings.append("全部媒体下载失败，已保留远程链接。")

        # 2.5) 视频口播转写（四件套：mp4 + m4a + srt + 口播词.md）
        title_seed = (article.get("title") if article else "") or f"@{username} 的帖子"
        tr = {"transcript": "", "transcriptSrtPath": "", "transcriptMdPath": "",
              "audioPath": "", "transcriptSource": ""}
        if media_path:
            set_task(task_id, stage="transcribing", topic=topic_id,
                     message="正在转写视频口播（无人声会自动跳过）", warnings=warnings)
            tr = transcribe_media(media_path, title_seed, canonical, warnings)

        # 3) 先写入原文卡片（AI 待补全）
        set_task(task_id, stage="writing", topic=topic_id, message="正在写入本地收藏", warnings=warnings)
        number = next_number(topic_id)
        post = {
            "uid": f"{topic_id}__{tid}",
            "id": f"{topic_id}__{tid}",
            "topic": topic_id,
            "platform": "x",
            "externalId": tid,
            "contentType": "post",
            "file": canonical,
            "title": title_seed,
            "number": number,
            "tweetId": tid,
            "author": username,
            "handle": f"@{username}" if username else "",
            "published": format_published(created),
            "body": "🤖 正在生成中文翻译与摘要…",
            "summary": "",
            "originalText": text,
            "originalIsExcerpt": False,
            "originalNote": "",
            "keywords": [],
            "supplement": "",
            "sourceLink": canonical,
            "mediaPath": media_path,
            "mediaName": media_name,
            "imagePath": image_path,
            "remoteMedia": remote,
            "articleLinks": [],
            "transcript": tr["transcript"],
            "transcriptSrtPath": tr["transcriptSrtPath"],
            "transcriptMdPath": tr["transcriptMdPath"],
            "audioPath": tr["audioPath"],
            "transcriptSource": tr["transcriptSource"],
            "downloadStatus": "success" if media_path or image_path else ("partial" if remote else "skipped"),
            "rawMeta": compact_meta("x", item),
            "aiStatus": "pending",
            "warnings": warnings,
            "source": "added",
            "addedAt": int(time.time()),
        }
        with LOCK:
            existing = find_by_content_key(topic_id, "x", tid) or find_by_topic_tweetid(topic_id, tid)
            if existing:
                set_task(task_id, stage="done", postId=existing["id"], topic=topic_id,
                         message="该帖已在该课题中，已为你定位。", warnings=warnings)
                return
            POSTS.append(post)
            save_posts()
        # 卡片已可见，进入 AI 阶段
        set_task(task_id, stage="ai", postId=post["id"], topic=topic_id,
                 message="正在生成中文标题、翻译和摘要", warnings=warnings)

        # 4) AI 异步补全（材料 = 正文 + 口播转写）
        material = "\n\n".join(x for x in [
            text, ("视频口播转写：\n" + tr["transcript"]) if tr["transcript"] else ""] if x)
        if AI_ENGINE != "none" and material:
            ai = run_ai(material, username, "x")
            with LOCK:
                if ai:
                    if ai.get("title"):
                        post["title"] = str(ai["title"]).strip()
                    if ai.get("chinese"):
                        post["body"] = str(ai["chinese"]).strip()
                    post["summary"] = str(ai.get("summary", "")).strip()
                    kw = ai.get("keywords")
                    post["keywords"] = [str(k) for k in kw] if isinstance(kw, list) else []
                    post["aiStatus"] = "ready"
                else:
                    post["body"] = "（AI 生成失败，仅显示原文，可点击「原文」查看。）"
                    post["aiStatus"] = "failed"
                    warnings.append("AI 生成失败")
                save_posts()
        else:
            with LOCK:
                post["body"] = text or post["body"]
                post["aiStatus"] = "skipped"
                save_posts()

        set_task(task_id, stage="done", postId=post["id"], topic=topic_id,
                 message="已加入收藏", warnings=warnings)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        set_task(task_id, stage="error", topic=topic_id, message=str(e))


def transcribe_media(media_rel: str, title: str, source_link: str, warnings: list) -> dict:
    """对本地视频跑 ASR 四件套（m4a/srt/口播词.md），返回可直接并入帖子的字段。"""
    out = {"transcript": "", "transcriptSrtPath": "", "transcriptMdPath": "",
           "audioPath": "", "transcriptSource": ""}
    if not media_rel:
        return out
    res = asr_pipeline.transcribe_video(
        os.path.join(VAULT_ROOT, media_rel), title=title, source_link=source_link)
    warnings.extend(res["warnings"])
    if res["transcript"]:
        out["transcript"] = truncate_text(res["transcript"])
        out["transcriptSource"] = res["source"] or "asr"
    if res["srtPath"]:
        out["transcriptSrtPath"] = relpath(res["srtPath"])
    if res["mdPath"]:
        out["transcriptMdPath"] = relpath(res["mdPath"])
    if res["audioPath"]:
        out["audioPath"] = relpath(res["audioPath"])
    return out


def _first_existing_media(files: list) -> tuple:
    media_path = media_name = image_path = ""
    for path in files:
        kind = classify_local_file(path)
        if kind == "video" and not media_path:
            media_path, media_name = relpath(path), os.path.basename(path)
        elif kind == "image" and not image_path:
            image_path = relpath(path)
    return media_path, media_name, image_path


def _write_pending_post(task_id: str, post: dict, warnings: list):
    with LOCK:
        existing = find_by_content_key(post["topic"], post["platform"], post["externalId"])
        if existing:
            set_task(task_id, stage="done", postId=existing["id"], topic=post["topic"],
                     message="该内容已在该课题中，已为你定位。", warnings=warnings)
            return existing, False
        POSTS.append(post)
        save_posts()
    set_task(task_id, stage="ai", postId=post["id"], topic=post["topic"],
             message="正在生成中文标题、翻译和摘要", warnings=warnings)
    return post, True


def _finish_ai(post: dict, text: str, handle: str, platform: str, warnings: list):
    if AI_ENGINE != "none" and text:
        ai = run_ai(text, handle, platform)
        with LOCK:
            if ai:
                if ai.get("title"):
                    post["title"] = str(ai["title"]).strip()
                if ai.get("chinese"):
                    post["body"] = str(ai["chinese"]).strip()
                post["summary"] = str(ai.get("summary", "")).strip()
                kw = ai.get("keywords")
                post["keywords"] = [str(k) for k in kw] if isinstance(kw, list) else []
                post["aiStatus"] = "ready"
            else:
                post["body"] = post.get("body") or "（AI 生成失败，仅显示原始材料。）"
                post["aiStatus"] = "failed"
                warnings.append("AI 生成失败")
            save_posts()
    else:
        with LOCK:
            post["body"] = text or post.get("body") or ""
            post["aiStatus"] = "skipped"
            save_posts()


def _bili_rows_to_timeline(rows: list) -> str:
    """B 站字幕行转 "[MM:SS] 文本" 时间轴格式；无时间信息时退回纯文本行。"""
    lines = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        content = str(r.get("content") or "").strip()
        if not content:
            continue
        start = r.get("from") or r.get("start") or r.get("start_time")
        if isinstance(start, (int, float)):
            lines.append(f"[{asr_pipeline._fmt_clock(int(float(start) * 1000))}] {content}")
        else:
            lines.append(content)
    return "\n".join(lines)


def process_add_bilibili(task_id: str, url: str, topic_id: str, detected: dict):
    warnings = []
    bvid = detected.get("externalId") or extract_bvid(url) or slugify_post_id(url)
    with LOCK:
        existing = find_by_content_key(topic_id, "bilibili", bvid)
    if existing:
        set_task(task_id, stage="done", postId=existing["id"], topic=topic_id,
                 message="该内容已在该课题中，已为你定位。", warnings=[])
        return

    set_task(task_id, stage="fetching", topic=topic_id, message="正在抓取 B 站视频信息")
    meta = {}
    p = run_opencli_site("bilibili", ["video", detected.get("canonicalUrl") or url, "-f", "json", "--window", "background"], timeout=120)
    if p.returncode == 0:
        try:
            meta = normalize_opencli_kv(json.loads(p.stdout))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"B 站元数据解析失败：{e}")
    else:
        warnings.append(f"B 站元数据抓取失败：{p.stderr[:120]}")
    title = str(meta.get("title") or meta.get("标题") or f"Bilibili {bvid}")
    owner = meta.get("owner")
    if isinstance(owner, dict):
        owner = owner.get("name") or owner.get("uname") or owner.get("mid")
    author = str(meta.get("author") or owner or meta.get("UP主") or "")
    pic = str(meta.get("thumbnail") or meta.get("pic") or meta.get("封面") or "")

    set_task(task_id, stage="downloading", topic=topic_id, message="正在保存封面", warnings=warnings)
    media_path = media_name = image_path = ""
    if pic.startswith("http"):
        try:
            m = download_media(pic, f"bilibili_{bvid}", 1)
            if m["kind"] == "image":
                image_path = m["path"]
        except Exception as e:  # noqa: BLE001
            warnings.append(f"封面下载失败：{e}")

    # 视频本体下载（opencli bilibili download，底层 yt-dlp，可能需要几分钟）
    set_task(task_id, stage="downloading", topic=topic_id,
             message="正在下载视频本体（大视频可能需要几分钟）", warnings=warnings)
    video_dir = os.path.join(MEDIA_DIR, "bilibili", bvid)
    os.makedirs(video_dir, exist_ok=True)
    before = snapshot_files(video_dir)
    dl = run_opencli_site("bilibili", ["download", bvid, "--output", video_dir,
                                      "-f", "json", "--window", "background"], timeout=1200)
    if dl.returncode != 0:
        warnings.append(f"视频本体下载失败：{(dl.stderr or dl.stdout or '')[:120]}")
    v_media, v_name, _ = _first_existing_media(collect_downloaded_files(video_dir, before))
    if v_media:
        media_path, media_name = v_media, v_name

    set_task(task_id, stage="transcribing", topic=topic_id, message="正在获取字幕/总结", warnings=warnings)
    transcript = ""
    transcript_source = ""
    sub = run_opencli_site("bilibili", ["subtitle", detected.get("canonicalUrl") or url, "-f", "json", "--window", "background"], timeout=120)
    if sub.returncode == 0:
        try:
            rows = json.loads(sub.stdout)
            if isinstance(rows, list):
                transcript = _bili_rows_to_timeline(rows)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"字幕解析失败：{e}")
    if not transcript:
        summ = run_opencli_site("bilibili", ["summary", detected.get("canonicalUrl") or url, "-f", "json", "--window", "background"], timeout=120)
        if summ.returncode == 0:
            try:
                rows = json.loads(summ.stdout)
                if isinstance(rows, list):
                    transcript = "\n".join(str(r.get("content") or "") for r in rows if isinstance(r, dict))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"总结解析失败：{e}")
    if transcript:
        transcript_source = "platform"
    transcript = truncate_text(transcript)

    # 平台没有字幕/总结时，用本地 ASR 对下载的视频兜底转写
    tr = {"transcript": "", "transcriptSrtPath": "", "transcriptMdPath": "",
          "audioPath": "", "transcriptSource": ""}
    if not transcript and media_path:
        set_task(task_id, stage="transcribing", topic=topic_id,
                 message="平台无字幕，正在 ASR 转写视频口播", warnings=warnings)
        tr = transcribe_media(media_path, title, detected.get("canonicalUrl") or url, warnings)
        if tr["transcript"]:
            transcript = tr["transcript"]
            transcript_source = tr["transcriptSource"]
    elif not transcript:
        warnings.append("未获取到字幕/官方总结，且无本地视频可转写")

    set_task(task_id, stage="writing", topic=topic_id, message="正在写入本地收藏", warnings=warnings)
    description = str(meta.get("description") or meta.get("desc") or meta.get("简介") or "")
    material = "\n".join(x for x in [title, description, transcript] if x)
    uid = make_platform_uid(topic_id, "bilibili", bvid)
    post = {
        "uid": uid, "id": uid, "topic": topic_id, "platform": "bilibili", "externalId": bvid,
        "contentType": "video", "file": detected.get("canonicalUrl") or url, "title": title,
        "number": next_number(topic_id), "tweetId": "", "author": author, "handle": author,
        "published": str(meta.get("publish_time") or meta.get("published") or meta.get("发布时间") or ""),
        "body": "🤖 正在生成中文内容卡片…", "summary": "", "originalText": material,
        "originalIsExcerpt": False, "originalNote": "", "keywords": [], "supplement": "",
        "sourceLink": detected.get("canonicalUrl") or url, "mediaPath": media_path, "mediaName": media_name,
        "imagePath": image_path, "remoteMedia": [], "articleLinks": [], "transcript": transcript,
        "transcriptSrtPath": tr["transcriptSrtPath"], "transcriptMdPath": tr["transcriptMdPath"],
        "audioPath": tr["audioPath"], "transcriptSource": transcript_source,
        "downloadStatus": "success" if image_path or media_path else "skipped",
        "rawMeta": compact_meta("bilibili", {**meta, "bvid": bvid, "canonicalUrl": detected.get("canonicalUrl") or url}),
        "aiStatus": "pending", "warnings": warnings, "source": "added", "addedAt": now_ts(),
    }
    post, created = _write_pending_post(task_id, post, warnings)
    if created:
        _finish_ai(post, material, author, "bilibili", warnings)
        set_task(task_id, stage="done", postId=post["id"], topic=topic_id, message="已加入收藏", warnings=warnings)


def process_add_xiaohongshu(task_id: str, url: str, topic_id: str, detected: dict):
    warnings = []
    note_id = detected.get("externalId") or slugify_post_id(url)
    with LOCK:
        existing = find_by_content_key(topic_id, "xiaohongshu", note_id)
    if existing:
        set_task(task_id, stage="done", postId=existing["id"], topic=topic_id,
                 message="该内容已在该课题中，已为你定位。", warnings=[])
        return

    set_task(task_id, stage="fetching", topic=topic_id, message="正在抓取小红书笔记信息")
    meta = {}
    p = run_opencli_site("xiaohongshu", ["note", detected.get("canonicalUrl") or url, "-f", "json", "--window", "background"], timeout=120)
    if p.returncode == 0:
        try:
            meta = normalize_opencli_kv(json.loads(p.stdout))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"小红书笔记解析失败：{e}")
    else:
        warnings.append("小红书 note 抓取失败，可能缺少 xsec_token；尝试仅下载媒体。")

    set_task(task_id, stage="downloading", topic=topic_id, message="正在下载小红书媒体", warnings=warnings)
    output_dir = os.path.join(MEDIA_DIR, "xiaohongshu", note_id)
    os.makedirs(output_dir, exist_ok=True)
    before = snapshot_files(output_dir)
    dl = run_opencli_site("xiaohongshu", ["download", detected.get("canonicalUrl") or url, "--output", output_dir, "-f", "json", "--window", "background"], timeout=180)
    if dl.returncode != 0:
        warnings.append(f"小红书媒体下载失败：{dl.stderr[:120]}")
    files = collect_downloaded_files(output_dir, before)
    media_path, media_name, image_path = _first_existing_media(files)

    title = str(meta.get("title") or meta.get("标题") or "小红书笔记")
    body_text = str(meta.get("desc") or meta.get("正文") or meta.get("description") or "")
    author = str(meta.get("author") or meta.get("作者") or "")

    # 视频笔记：本地 ASR 转写口播（四件套）
    tr = {"transcript": "", "transcriptSrtPath": "", "transcriptMdPath": "",
          "audioPath": "", "transcriptSource": ""}
    if media_path:
        set_task(task_id, stage="transcribing", topic=topic_id,
                 message="正在转写视频口播（无人声会自动跳过）", warnings=warnings)
        tr = transcribe_media(media_path, title, detected.get("canonicalUrl") or url, warnings)

    material = "\n".join(x for x in [
        title, body_text,
        ("视频口播转写：\n" + tr["transcript"]) if tr["transcript"] else ""] if x)

    set_task(task_id, stage="writing", topic=topic_id, message="正在写入本地收藏", warnings=warnings)
    uid = make_platform_uid(topic_id, "xiaohongshu", note_id)
    post = {
        "uid": uid, "id": uid, "topic": topic_id, "platform": "xiaohongshu", "externalId": note_id,
        "contentType": "note", "file": detected.get("canonicalUrl") or url, "title": title,
        "number": next_number(topic_id), "tweetId": "", "author": author, "handle": author,
        "published": str(meta.get("published") or meta.get("发布时间") or ""),
        "body": "🤖 正在生成中文内容卡片…", "summary": "", "originalText": material,
        "originalIsExcerpt": False, "originalNote": "", "keywords": [], "supplement": "",
        "sourceLink": detected.get("canonicalUrl") or url, "mediaPath": media_path, "mediaName": media_name,
        "imagePath": image_path, "remoteMedia": [], "articleLinks": [], "transcript": tr["transcript"],
        "transcriptSrtPath": tr["transcriptSrtPath"], "transcriptMdPath": tr["transcriptMdPath"],
        "audioPath": tr["audioPath"], "transcriptSource": tr["transcriptSource"],
        "downloadStatus": "success" if image_path or media_path else ("failed" if dl.returncode != 0 else "skipped"),
        "rawMeta": compact_meta("xiaohongshu", {**meta, "noteId": note_id, "canonicalUrl": detected.get("canonicalUrl") or url}),
        "aiStatus": "pending", "warnings": warnings, "source": "added", "addedAt": now_ts(),
    }
    post, created = _write_pending_post(task_id, post, warnings)
    if created:
        _finish_ai(post, material, author, "xiaohongshu", warnings)
        set_task(task_id, stage="done", postId=post["id"], topic=topic_id, message="已加入收藏", warnings=warnings)


DOUYIN_MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def _douyin_meta_from_user_videos(sec_uid: str, aweme_id: str):
    """策略 A：链接里带 sec_uid（用户页 modal 链接）时，从作品列表精确匹配。"""
    p = run_opencli_site("douyin", ["user-videos", sec_uid, "--limit", "20",
                                   "--with_comments", "true", "--comment_limit", "5",
                                   "-f", "json", "--window", "background"], timeout=240)
    if p.returncode != 0:
        raise RuntimeError(f"opencli douyin user-videos 失败：{(p.stderr or '')[:120]}")
    rows = json.loads(p.stdout)
    if not isinstance(rows, list):
        return None
    for r in rows:
        if isinstance(r, dict) and str(r.get("aweme_id")) == str(aweme_id):
            return {
                "desc": str(r.get("title") or ""),
                "author": str(r.get("author") or r.get("nickname") or ""),
                "secUid": sec_uid,
                "playUrl": str(r.get("play_url") or ""),
                "cover": "",
                "createTime": "",
                "comments": r.get("top_comments") if isinstance(r.get("top_comments"), list) else [],
            }
    return None


def _douyin_find_item(obj):
    """在 _ROUTER_DATA 里递归找 item_list[0]。"""
    if isinstance(obj, dict):
        item_list = obj.get("item_list")
        if isinstance(item_list, list) and item_list and isinstance(item_list[0], dict):
            return item_list[0]
        for v in obj.values():
            r = _douyin_find_item(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _douyin_find_item(v)
            if r:
                return r
    return None


def _douyin_meta_from_share_page(aweme_id: str):
    """策略 B：无登录态依赖的分享页 _ROUTER_DATA 解析（移动端 UA）。"""
    share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/"
    req = urllib.request.Request(share_url, headers={"User-Agent": DOUYIN_MOBILE_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", "ignore")
    m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        raise RuntimeError("分享页未返回 _ROUTER_DATA（可能触发风控）")
    item = _douyin_find_item(json.loads(m.group(1)))
    if not item:
        raise RuntimeError("分享页数据里没有视频条目")
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    play_addr = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
    url_list = play_addr.get("url_list") if isinstance(play_addr.get("url_list"), list) else []
    uri = str(play_addr.get("uri") or "")
    play = str(url_list[0]) if url_list else ""
    if not play and uri:
        play = f"https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}&ratio=720p&line=0"
    # 分享页地址常带水印标记，尝试换成无水印端点
    play = play.replace("playwm", "play")
    cover_addr = video.get("cover") if isinstance(video.get("cover"), dict) else {}
    cover_list = cover_addr.get("url_list") if isinstance(cover_addr.get("url_list"), list) else []
    create_time = item.get("create_time")
    published = ""
    if isinstance(create_time, (int, float)) and create_time > 0:
        published = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(create_time)))
    return {
        "desc": str(item.get("desc") or ""),
        "author": str(author.get("nickname") or ""),
        "secUid": str(author.get("sec_uid") or ""),
        "playUrl": play,
        "cover": str(cover_list[0]) if cover_list else "",
        "createTime": published,
        "comments": [],
    }


def _douyin_placeholder(task_id: str, url: str, topic_id: str, detected: dict, warnings: list):
    """全部策略失败时的降级：保存链接占位卡片（原有行为）。"""
    external_id = detected.get("externalId") or slugify_post_id(url)
    set_task(task_id, stage="writing", topic=topic_id, message="正在保存抖音链接卡片", warnings=warnings)
    uid = make_platform_uid(topic_id, "douyin", external_id)
    post = {
        "uid": uid, "id": uid, "topic": topic_id, "platform": "douyin", "externalId": external_id,
        "contentType": "video", "file": detected.get("canonicalUrl") or url, "title": "抖音视频待解析",
        "number": next_number(topic_id), "tweetId": "", "author": "", "handle": "", "published": "",
        "body": "已保存抖音链接，但本次自动抓取失败（详见 warnings）。可稍后删除本卡片重新收藏。",
        "summary": "抖音链接已加入当前课题，自动抓取失败待重试。", "originalText": detected.get("canonicalUrl") or url,
        "originalIsExcerpt": False, "originalNote": "", "keywords": ["抖音", "待解析", "视频链接"], "supplement": "",
        "sourceLink": detected.get("canonicalUrl") or url, "mediaPath": "", "mediaName": "", "imagePath": "",
        "remoteMedia": [], "articleLinks": [], "transcript": "", "downloadStatus": "skipped",
        "rawMeta": compact_meta("douyin", {"awemeId": external_id, "shareUrl": url, "canonicalUrl": detected.get("canonicalUrl") or url}),
        "aiStatus": "skipped", "warnings": warnings, "source": "added", "addedAt": now_ts(),
    }
    with LOCK:
        POSTS.append(post)
        save_posts()
    set_task(task_id, stage="done", postId=post["id"], topic=topic_id, message="已保存抖音链接（未能自动抓取）", warnings=warnings)


def process_add_douyin(task_id: str, url: str, topic_id: str, detected: dict):
    warnings = []
    canonical = detected.get("canonicalUrl") or url
    aweme_id = detected.get("externalId") or ""
    if not re.fullmatch(r"\d{8,25}", aweme_id or ""):
        m = re.search(r"(\d{15,25})", canonical)
        aweme_id = m.group(1) if m else ""
    with LOCK:
        existing = find_by_content_key(topic_id, "douyin", aweme_id or slugify_post_id(url))
    if existing:
        set_task(task_id, stage="done", postId=existing["id"], topic=topic_id,
                 message="该内容已在该课题中，已为你定位。", warnings=[])
        return
    if not aweme_id:
        warnings.append("无法从链接解析出视频 ID")
        _douyin_placeholder(task_id, url, topic_id, detected, warnings)
        return

    # 抓元数据：A) 用户页作品列表精确匹配  B) 分享页 _ROUTER_DATA
    set_task(task_id, stage="fetching", topic=topic_id, message="正在抓取抖音视频信息")
    meta = None
    sec_match = re.search(r"/user/([\w-]+)", canonical)
    if sec_match:
        try:
            meta = _douyin_meta_from_user_videos(sec_match.group(1), aweme_id)
            if meta is None:
                warnings.append("作者近 20 条作品里未找到该视频，改用分享页解析")
        except Exception as e:  # noqa: BLE001
            warnings.append(f"作品列表抓取失败：{e}")
    if meta is None:
        try:
            meta = _douyin_meta_from_share_page(aweme_id)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"分享页解析失败：{e}")
    if meta is None:
        _douyin_placeholder(task_id, url, topic_id, detected, warnings)
        return

    # 下载视频 + 封面
    set_task(task_id, stage="downloading", topic=topic_id, message="正在下载抖音视频", warnings=warnings)
    video_dir = os.path.join(MEDIA_DIR, "douyin", aweme_id)
    os.makedirs(video_dir, exist_ok=True)
    media_path = media_name = image_path = ""
    dl_headers = {"User-Agent": DOUYIN_MOBILE_UA, "Referer": "https://www.douyin.com/"}
    if meta["playUrl"]:
        try:
            req = urllib.request.Request(meta["playUrl"], headers=dl_headers)
            with urllib.request.urlopen(req, timeout=180) as resp:
                blob = resp.read()
            if not blob or len(blob) < 20 * 1024:
                raise RuntimeError(f"下载内容异常（{len(blob)} bytes）")
            video_abs = os.path.join(video_dir, f"{aweme_id}.mp4")
            with open(video_abs, "wb") as f:
                f.write(blob)
            media_path, media_name = relpath(video_abs), f"{aweme_id}.mp4"
        except Exception as e:  # noqa: BLE001
            warnings.append(f"视频下载失败：{e}")
    else:
        warnings.append("未拿到视频播放地址")
    if meta["cover"]:
        try:
            req = urllib.request.Request(meta["cover"], headers=dl_headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                blob = resp.read()
            cover_abs = os.path.join(video_dir, f"{aweme_id}_cover.jpg")
            with open(cover_abs, "wb") as f:
                f.write(blob)
            image_path = relpath(cover_abs)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"封面下载失败：{e}")

    # 口播转写（四件套）
    title = meta["desc"].strip().splitlines()[0][:40] if meta["desc"].strip() else f"抖音视频 {aweme_id}"
    tr = {"transcript": "", "transcriptSrtPath": "", "transcriptMdPath": "",
          "audioPath": "", "transcriptSource": ""}
    if media_path:
        set_task(task_id, stage="transcribing", topic=topic_id,
                 message="正在转写视频口播（无人声会自动跳过）", warnings=warnings)
        tr = transcribe_media(media_path, title, canonical, warnings)

    # 热门评论 → 补充说明
    supplement = ""
    if meta["comments"]:
        lines = []
        for c in meta["comments"][:5]:
            text = c.get("text") if isinstance(c, dict) else str(c)
            if text:
                lines.append(f"· {str(text).strip()}")
        if lines:
            supplement = "热门评论：\n" + "\n".join(lines)

    set_task(task_id, stage="writing", topic=topic_id, message="正在写入本地收藏", warnings=warnings)
    material = "\n\n".join(x for x in [
        meta["desc"],
        ("视频口播转写：\n" + tr["transcript"]) if tr["transcript"] else ""] if x)
    uid = make_platform_uid(topic_id, "douyin", aweme_id)
    post = {
        "uid": uid, "id": uid, "topic": topic_id, "platform": "douyin", "externalId": aweme_id,
        "contentType": "video", "file": canonical, "title": title,
        "number": next_number(topic_id), "tweetId": "", "author": meta["author"], "handle": meta["author"],
        "published": meta["createTime"],
        "body": "🤖 正在生成中文内容卡片…", "summary": "", "originalText": material or meta["desc"],
        "originalIsExcerpt": False, "originalNote": "", "keywords": [], "supplement": supplement,
        "sourceLink": canonical, "mediaPath": media_path, "mediaName": media_name,
        "imagePath": image_path, "remoteMedia": ([meta["playUrl"]] if (meta["playUrl"] and not media_path) else []),
        "articleLinks": [], "transcript": tr["transcript"],
        "transcriptSrtPath": tr["transcriptSrtPath"], "transcriptMdPath": tr["transcriptMdPath"],
        "audioPath": tr["audioPath"], "transcriptSource": tr["transcriptSource"],
        "downloadStatus": "success" if media_path else ("partial" if image_path else "failed"),
        "rawMeta": compact_meta("douyin", {"awemeId": aweme_id, "desc": meta["desc"][:200],
                                          "author": meta["author"], "shareUrl": url, "canonicalUrl": canonical}),
        "aiStatus": "pending", "warnings": warnings, "source": "added", "addedAt": now_ts(),
    }
    post, created = _write_pending_post(task_id, post, warnings)
    if created:
        _finish_ai(post, material or meta["desc"], meta["author"], "douyin", warnings)
        set_task(task_id, stage="done", postId=post["id"], topic=topic_id, message="已加入收藏", warnings=warnings)


def process_add(task_id: str, url: str, topic_id: str):
    try:
        with IMPORT_SEM:
            _process_add_inner(task_id, url, topic_id)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        set_task(task_id, stage="error", topic=topic_id, message=str(e))


def _process_add_inner(task_id: str, url: str, topic_id: str):
    try:
        set_task(task_id, stage="detecting", topic=topic_id, message="正在识别平台")
        detected = detect_platform(url)
        if detected["platform"] == "unknown":
            raise RuntimeError("暂不支持该链接平台")
        if detected["platform"] == "x":
            process_add_x(task_id, detected.get("canonicalUrl") or url, topic_id, detected)
        elif detected["platform"] == "bilibili":
            process_add_bilibili(task_id, url, topic_id, detected)
        elif detected["platform"] == "xiaohongshu":
            process_add_xiaohongshu(task_id, url, topic_id, detected)
        elif detected["platform"] == "douyin":
            process_add_douyin(task_id, url, topic_id, detected)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        set_task(task_id, stage="error", topic=topic_id, message=str(e))


def build_app_html() -> bytes:
    # 新版 Quarry（Frost）前端是自包含的 React 应用，自己通过 /api/* 实时加载数据，
    # 不再需要运行时注入。旧版 vanilla 注入逻辑保留在 index.legacy.html 与 git 历史中。
    with open(INDEX_HTML, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------

APP_PATHS = {"/", "/index.html", "/app", "/app.html"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Quarry/2.0"

    def log_message(self, fmt, *args):  # 安静一点
        return

    # --- 工具 ---
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _send_bytes(self, data: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _safe_local_path(self, urlpath: str):
        """双根解析：先在产品层 app/ 找前端资源，再回落到内容层 vault/ 找媒体。

        两个根都各自做越界校验，任何一个根都不允许 ../ 逃逸。
        """
        rel = unquote(urlpath.lstrip("/"))
        found = None
        for root in (APP_ROOT, VAULT_ROOT):
            full = os.path.normpath(os.path.join(root, rel))
            if full != root and not full.startswith(root + os.sep):
                continue
            if os.path.isfile(full):
                return full
            if found is None:
                found = full
        return found

    def _serve_static(self, urlpath: str):
        full = self._safe_local_path(urlpath)
        if not full or not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        ctype, _ = (None, None)
        import mimetypes
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if full.endswith(".mp4"):
            ctype = "video/mp4"
        elif full.endswith(".jsx"):
            ctype = "application/javascript"
        if ("charset" not in ctype) and (
            ctype.startswith("text/") or "javascript" in ctype or ctype == "application/json"
        ):
            ctype += "; charset=utf-8"
        size = os.path.getsize(full)
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            start = int(m.group(1)) if m and m.group(1) else 0
            end = int(m.group(2)) if m and m.group(2) else size - 1
            end = min(end, size - 1)
            start = min(start, end)
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with open(full, "rb") as f:
                f.seek(start)
                self.wfile.write(f.read(length))
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with open(full, "rb") as f:
            self.wfile.write(f.read())

    # --- 路由 ---
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in APP_PATHS:
            try:
                self._send_bytes(build_app_html(), "text/html; charset=utf-8")
            except Exception as e:  # noqa: BLE001
                self.send_error(500, str(e))
            return
        if path == "/api/topics":
            with LOCK:
                self._send_json({"topics": public_topics()})
            return
        if path == "/api/posts":
            topic_id = (query.get("topic") or [""])[0]
            with LOCK:
                if topic_id:
                    posts = [p for p in POSTS if p.get("topic") == topic_id]
                    self._send_json({"posts": posts, "count": len(posts), "topic": topic_id})
                else:
                    self._send_json({"posts": POSTS, "count": len(POSTS)})
            return
        if path.startswith("/api/task/"):
            tid = path[len("/api/task/"):]
            self._send_json(get_task(tid))
            return
        self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/topics":
            try:
                payload = self._read_json()
            except Exception:  # noqa: BLE001
                self._send_json({"error": "请求体不是合法 JSON"}, 400)
                return
            name = str(payload.get("name") or "").strip()
            raw_id = str(payload.get("id") or "").strip()
            topic_id = raw_id if raw_id else slugify_topic(name)
            if not raw_id and not topic_id:
                topic_id = f"topic-{uuid.uuid4().hex[:6]}"
            description = str(payload.get("description") or "").strip()
            if not name:
                self._send_json({"error": "课题名称不能为空"}, 400)
                return
            if not topic_id or not valid_topic_id(topic_id):
                self._send_json({"error": "课题 ID 只能包含小写字母、数字、点、下划线和连字符，且必须以字母或数字开头"}, 400)
                return
            with LOCK:
                if topic_exists(topic_id):
                    self._send_json({"error": "课题 ID 已存在"}, 400)
                    return
                ts = now_ts()
                topic = {
                    "id": topic_id,
                    "name": name,
                    "description": description,
                    "createdAt": ts,
                    "updatedAt": ts,
                }
                TOPICS.append(topic)
                save_posts()
            self._send_json({"topic": topic}, 201)
            return

        # 重新转写：对已入库、有本地视频的帖子补跑 ASR（异步任务）
        m = re.fullmatch(r"/api/posts/(.+)/retranscribe", path)
        if m:
            uid = unquote(m.group(1))
            with LOCK:
                post = next((p for p in POSTS if str(p.get("uid")) == uid or str(p.get("id")) == uid), None)
            if not post:
                self._send_json({"error": f"帖子不存在：{uid}"}, 404)
                return
            if not post.get("mediaPath"):
                self._send_json({"error": "该帖子没有本地视频，无法转写"}, 400)
                return
            task_id = uuid.uuid4().hex[:12]
            set_task(task_id, stage="pending", topic=post.get("topic"), message="已创建转写任务", warnings=[])

            def _retranscribe(p=post, tid=task_id):
                try:
                    with IMPORT_SEM:
                        warnings = []
                        set_task(tid, stage="transcribing", topic=p.get("topic"),
                                 message="正在重新转写视频口播", warnings=warnings)
                        tr = transcribe_media(p["mediaPath"], p.get("title") or "",
                                              p.get("sourceLink") or "", warnings)
                        with LOCK:
                            if tr["transcript"]:
                                p.update({k: tr[k] for k in (
                                    "transcript", "transcriptSrtPath", "transcriptMdPath",
                                    "audioPath", "transcriptSource")})
                            save_posts()
                        msg = "转写完成" if tr["transcript"] else "转写未产出内容（详见 warnings）"
                        set_task(tid, stage="done", postId=p["id"], topic=p.get("topic"),
                                 message=msg, warnings=warnings)
                except Exception as e:  # noqa: BLE001
                    set_task(tid, stage="error", topic=p.get("topic"), message=str(e))

            threading.Thread(target=_retranscribe, daemon=True).start()
            self._send_json({"taskId": task_id})
            return

        if path != "/api/add":
            self.send_error(404, "Not Found")
            return
        try:
            payload = self._read_json()
        except Exception:  # noqa: BLE001
            self._send_json({"error": "请求体不是合法 JSON"}, 400)
            return
        topic_id = str(payload.get("topic") or "").strip() or first_topic_id()
        with LOCK:
            ok_topic = topic_exists(topic_id)
        if not ok_topic:
            self._send_json({"error": f"课题不存在：{topic_id}"}, 400)
            return

        # 支持批量：urls 数组，或 url 里粘贴多行/空白分隔的多条链接
        raw_urls = payload.get("urls")
        if isinstance(raw_urls, list):
            url_list = [str(u).strip() for u in raw_urls if str(u).strip()]
        else:
            url_list = [u for u in re.split(r"\s+", str(payload.get("url") or "")) if u.strip()]
        url_list = [u for u in url_list if re.match(r"https?://", u)]
        if not url_list:
            self._send_json({"error": "请提供有效的平台内容链接"}, 400)
            return

        if len(url_list) == 1 and not isinstance(raw_urls, list):
            # 单条：保持原有契约（预检平台，直接返回 taskId）
            url = url_list[0]
            detected = detect_platform(url)
            if detected.get("platform") == "unknown":
                self._send_json({"error": "暂不支持该链接平台"}, 400)
                return
            task_id = uuid.uuid4().hex[:12]
            set_task(task_id, stage="pending", topic=topic_id, message="已创建任务", warnings=[])
            threading.Thread(target=process_add, args=(task_id, url, topic_id),
                             daemon=True).start()
            self._send_json({"taskId": task_id})
            return

        # 批量：不做同步预检（短链解析耗时），平台不支持的链接由任务自身报 error
        tasks = []
        for url in url_list:
            task_id = uuid.uuid4().hex[:12]
            set_task(task_id, stage="pending", topic=topic_id, message="已创建任务", warnings=[])
            threading.Thread(target=process_add, args=(task_id, url, topic_id),
                             daemon=True).start()
            tasks.append({"url": url, "taskId": task_id})
        self._send_json({"tasks": tasks})

    # --- 删除 / 编辑 ---
    def _delete_post_files(self, post: dict) -> list:
        """删除帖子关联的本地文件（仅限项目目录内），返回 warning 列表。"""
        warnings = []
        rels = [post.get("mediaPath"), post.get("imagePath"), post.get("audioPath"),
                post.get("transcriptSrtPath"), post.get("transcriptMdPath")]
        dirs = set()
        for rel in rels:
            if not rel:
                continue
            full = self._safe_local_path("/" + str(rel))
            if not full or not os.path.isfile(full):
                continue
            try:
                os.remove(full)
                dirs.add(os.path.dirname(full))
            except Exception as e:  # noqa: BLE001
                warnings.append(f"文件删除失败：{rel} ({e})")
        # 清理因此变空的媒体子目录（仅 data/media 之下）
        for d in dirs:
            try:
                if d.startswith(MEDIA_DIR + os.sep) and not os.listdir(d):
                    os.rmdir(d)
            except Exception:  # noqa: BLE001
                pass
        return warnings

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/api/posts/"):
            uid = unquote(path[len("/api/posts/"):])
            with_media = (query.get("media") or ["0"])[0] in ("1", "true", "yes")
            with LOCK:
                post = next((p for p in POSTS if str(p.get("uid")) == uid or str(p.get("id")) == uid), None)
                if not post:
                    self._send_json({"error": f"帖子不存在：{uid}"}, 404)
                    return
                POSTS.remove(post)
                save_posts()
            warnings = self._delete_post_files(post) if with_media else []
            self._send_json({"ok": True, "removed": uid, "warnings": warnings})
            return
        if path.startswith("/api/topics/"):
            topic_id = unquote(path[len("/api/topics/"):])
            force = (query.get("force") or ["0"])[0] in ("1", "true", "yes")
            with LOCK:
                topic = next((t for t in TOPICS if t.get("id") == topic_id), None)
                if not topic:
                    self._send_json({"error": f"课题不存在：{topic_id}"}, 404)
                    return
                related = [p for p in POSTS if p.get("topic") == topic_id]
                if related and not force:
                    self._send_json({"error": f"课题非空（{len(related)} 条收藏），如确认连帖子一起删除请加 ?force=1"}, 400)
                    return
                for p in related:
                    POSTS.remove(p)
                TOPICS.remove(topic)
                if not TOPICS:
                    TOPICS.append(make_default_topic())
                save_posts()
            self._send_json({"ok": True, "removed": topic_id, "removedPosts": len(related)})
            return
        self.send_error(404, "Not Found")

    def do_PATCH(self):
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
        except Exception:  # noqa: BLE001
            self._send_json({"error": "请求体不是合法 JSON"}, 400)
            return
        if path.startswith("/api/posts/"):
            uid = unquote(path[len("/api/posts/"):])
            with LOCK:
                post = next((p for p in POSTS if str(p.get("uid")) == uid or str(p.get("id")) == uid), None)
                if not post:
                    self._send_json({"error": f"帖子不存在：{uid}"}, 404)
                    return
                for key in ("title", "body", "summary", "supplement"):
                    if key in payload:
                        post[key] = str(payload.get(key) or "").strip()
                if "keywords" in payload:
                    kw = payload.get("keywords")
                    post["keywords"] = [str(k).strip() for k in kw if str(k).strip()] if isinstance(kw, list) else []
                post["editedAt"] = now_ts()
                save_posts()
                self._send_json({"post": post})
            return
        if path.startswith("/api/topics/"):
            topic_id = unquote(path[len("/api/topics/"):])
            with LOCK:
                topic = next((t for t in TOPICS if t.get("id") == topic_id), None)
                if not topic:
                    self._send_json({"error": f"课题不存在：{topic_id}"}, 404)
                    return
                if "name" in payload and str(payload.get("name") or "").strip():
                    topic["name"] = str(payload["name"]).strip()
                if "description" in payload:
                    topic["description"] = str(payload.get("description") or "").strip()
                topic["updatedAt"] = now_ts()
                save_posts()
                self._send_json({"topic": topic})
            return
        self.send_error(404, "Not Found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def _is_real_lan(ip: str) -> bool:
    # 真正的家用/办公局域网网段；排除 VPN TUN 常用的 198.18.0.0/15
    return ip.startswith("192.168.") or ip.startswith("10.") or any(
        ip.startswith(f"172.{n}.") for n in range(16, 32))


def lan_ip() -> str:
    # macOS 上优先取物理网卡地址，避免 VPN 隧道地址(198.18.x.x)
    for iface in ("en0", "en1", "en2"):
        try:
            out = subprocess.run(["ipconfig", "getifaddr", iface],
                                 capture_output=True, text=True, timeout=3).stdout.strip()
            if out and _is_real_lan(out):
                return out
        except Exception:  # noqa: BLE001
            pass
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return ip if _is_real_lan(ip) else "127.0.0.1"
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def main():
    _ensure_dirs()
    load_posts()
    # 启动即校验新版前端入口与关键静态资源是否就位
    required = ["index.html", "tv-glass-theme.css", "tv-glass-app.jsx", "tv-data.js", "tv-api.js"]
    missing = [name for name in required if not os.path.exists(os.path.join(APP_ROOT, name))]
    if missing:
        print(f"[app] 警告：缺少前端文件 {missing}")
    else:
        print(f"[app] 前端就位：Quarry Frost（{len(required)} 个文件 + jsx 组件）")
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    ip = lan_ip()
    print("=" * 56)
    print(f"  Quarry · 选题矿场 已启动")
    print(f"  AI 引擎：{AI_ENGINE}")
    print(f"  内容层：  {VAULT_ROOT}")
    print(f"  本机：    http://127.0.0.1:{PORT}/")
    print(f"  局域网：  http://{ip}:{PORT}/")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
