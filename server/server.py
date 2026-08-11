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
  DELETE /api/topics/<id>     删除课题（非空需 ?force=1；?media=1 连本地媒体一起删）
  GET    /api/posts           列出帖子 {posts:[...]}，支持 ?topic=<id>
  PATCH  /api/posts/<uid>     编辑帖子 {title?,body?,summary?,keywords?,supplement?}
  DELETE /api/posts/<uid>     删除帖子（?media=1 连本地媒体一起删）
  POST   /api/add             单条 {url,topic?} -> {taskId}；批量 {urls:[...]} 或多行 url -> {tasks:[...]}
  GET    /api/task/<id>       轮询任务状态

转写：视频类内容自动走 ASR 四件套（mp4+m4a+srt+口播词.md），见 asr.py；TV_ASR=none 关闭。

互动数据：收藏（下载）时抓取当下的浏览量/点赞/收藏/评论/分享，统一存进帖子的
  stats 字段 {views,likes,collects,comments,shares,capturedAt}，各平台缺哪项就不存哪项。

数据：
  data/posts.json        v2 持久化课题与帖子；首启从 post_content_dataset.json 种子导入
  data/media/            新帖下载的媒体

环境变量：
  PORT(默认6002) AI_ENGINE(codex|ark|none, 默认codex) OPENCLI_BIN CODEX_BIN
  ARK_API_KEY ARK_MODEL(默认 doubao-seed-1-6-250615) 用于 AI_ENGINE=ark
"""

from __future__ import annotations

import contextlib
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
import keyframes
import paths
import projection

# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------
# 产品层：只放代码，不放任何采集到的内容。路径解析见 paths.py。
HERE = paths.HERE                                       # <repo>/server
REPO_ROOT = paths.REPO_ROOT                             # <repo>
APP_ROOT = paths.APP_ROOT                               # 前端静态资源
INDEX_HTML = os.path.join(APP_ROOT, "index.html")

# 内容层：与产品层彻底分离，默认落在主仓库同级的 ../vault，可用 QUARRY_VAULT 指到任意位置。
VAULT_ROOT = paths.resolve_vault()
DATA_DIR = os.path.join(VAULT_ROOT, "data")
MEDIA_DIR = os.path.join(DATA_DIR, "media")
POSTS_FILE = os.path.join(DATA_DIR, "posts.json")
QUEUE_FILE = os.path.join(DATA_DIR, "queue.json")
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
# opencli 只能驱动真实浏览器（没有 headless 模式），所以采集必然会在某个浏览器里开页。
# 下面三个开关决定"开在哪、开几个、开完留不留"，默认值按"尽量不打扰用户"来选：
#   window       背景窗口，不抢应用焦点
#   profile      指定一个你平时不工作的浏览器 profile 专门跑采集（强烈建议配）
#   site-session 同一平台复用同一个标签页，而不是每条命令新开一个
OPENCLI_WINDOW = os.environ.get("QUARRY_OPENCLI_WINDOW", "background")
OPENCLI_PROFILE = os.environ.get("QUARRY_OPENCLI_PROFILE", "").strip()
OPENCLI_SITE_SESSION = os.environ.get("QUARRY_OPENCLI_SITE_SESSION", "persistent").strip()
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
# Agent 投影：写入 <vault>/agent/，供 quarry CLI 与 MCP 服务读取。置 0 关闭。
AGENT_PROJECTION = (os.environ.get("QUARRY_AGENT_PROJECTION", "1") != "0")

LOCK = threading.RLock()
TOPICS: list = []     # 课题列表
POSTS: list = []      # 帖子列表（前端字段结构）
TASKS: dict = {}      # taskId -> {stage, progress, message, postId, topic, warnings}
# 待采集队列：粘链接时只落一条记录，不碰浏览器；等用户按「开始采集」再逐条跑。
# 落盘在内容层（data/queue.json），关页面、重启服务都不会丢。
QUEUE: list = []      # [{id, url, topic, platform, status, addedAt, taskId, message}]
QUEUE_STATE = {"draining": False, "stopping": False, "currentId": ""}
# 导入任务并发闸：多条链接同时粘贴时避免 opencli 浏览器桥/ASR 互相争抢
IMPORT_SEM = threading.Semaphore(
    int(os.environ.get("QUARRY_IMPORT_CONCURRENCY") or os.environ.get("TV_IMPORT_CONCURRENCY", "2"))
)
# 浏览器闸：复用标签页时，同一平台同时只允许一条 opencli 命令在跑。
# 一是同站命令共用一个标签页，并发会把彼此的页面导航掉；
# 二是同站串行后，一个平台从头到尾只占一个标签页，不会一条命令弹一次窗。
# 不同平台之间互不影响，仍然可以并行。
_SITE_LOCKS: dict = {}
_SITE_LOCKS_GUARD = threading.Lock()


def _site_lock(site: str):
    if OPENCLI_SITE_SESSION != "persistent":
        return contextlib.nullcontext()
    with _SITE_LOCKS_GUARD:
        lock = _SITE_LOCKS.get(site)
        if lock is None:
            lock = _SITE_LOCKS[site] = threading.Lock()
        return lock


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


def video_download_status(media_path: str, image_path: str, attempted: bool = True) -> str:
    """视频类内容的下载完整度：以「视频本体」为准，封面不顶数。

    封面下载成功、视频本体失败时必须是 partial —— 报 success 的话前端看不出
    这条内容缺了正片，用户要等到点开播放才发现。
    """
    if media_path:
        return "success"
    if not attempted:
        return "skipped"
    return "partial" if image_path else "failed"


def derive_download_status(post: dict) -> str:
    """没有显式状态时（种子数据/历史字段缺失）按已存文件推断。

    视频类走 video_download_status；其它类型有任意媒体就算完整，都没有算没下过。
    """
    media = str(post.get("mediaPath") or "")
    image = str(post.get("imagePath") or "")
    if str(post.get("contentType") or "") == "video":
        return video_download_status(media, image, attempted=bool(media or image))
    return "success" if (media or image) else "skipped"


def normalize_post(post: dict, topic_id: str = DEFAULT_TOPIC_ID) -> dict:
    p = dict(post)
    p["topic"] = str(p.get("topic") or topic_id)
    p["tweetId"] = str(p.get("tweetId") or "")
    p["platform"] = str(p.get("platform") or "x")
    p["externalId"] = str(p.get("externalId") or p.get("tweetId") or p.get("uid") or p.get("id") or "")
    p["contentType"] = str(p.get("contentType") or ("post" if p["platform"] == "x" else "video"))
    p["downloadStatus"] = str(p.get("downloadStatus") or derive_download_status(p))
    p["transcript"] = truncate_text(str(p.get("transcript") or ""))
    for key in ("transcriptSrtPath", "transcriptMdPath", "audioPath", "transcriptSource"):
        p[key] = str(p.get(key) or "")
    p["rawMeta"] = p.get("rawMeta") if isinstance(p.get("rawMeta"), dict) else {}
    p["stats"] = p.get("stats") if isinstance(p.get("stats"), dict) else {}
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
        "x": {"id", "author", "text", "created_at", "url", "likes", "retweets", "replies", "views", "bookmarks", "quotes", "media_urls"},
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


# 收藏时点的互动数据快照：浏览/点赞/收藏/评论/分享。
# 各平台字段名差异很大（英文/中文/嵌套 stat 结构），这里统一按候选键提取成整数。
STATS_KEY_CANDIDATES = {
    "x": {
        "views": ("views", "view_count", "impressions"),
        "likes": ("likes", "favorite_count", "like_count"),
        "collects": ("bookmarks", "bookmark_count"),
        "comments": ("replies", "reply_count", "comments"),
        "shares": ("retweets", "retweet_count", "reposts"),
    },
    "bilibili": {
        "views": ("view", "play", "views", "播放量", "播放", "播放数"),
        "likes": ("like", "likes", "点赞", "点赞数"),
        "collects": ("favorite", "favourite", "collect", "收藏", "收藏数"),
        "comments": ("reply", "comment", "评论", "评论数"),
        "shares": ("share", "分享", "分享数", "转发"),
    },
    "xiaohongshu": {
        "views": ("viewCount", "view_count", "浏览量", "浏览"),
        "likes": ("likedCount", "liked_count", "likes", "点赞", "点赞数"),
        "collects": ("collectedCount", "collected_count", "收藏", "收藏数"),
        "comments": ("commentCount", "comment_count", "comments", "评论", "评论数"),
        "shares": ("shareCount", "share_count", "分享", "分享数"),
    },
    "douyin": {
        "views": ("play_count", "playCount", "views"),
        "likes": ("digg_count", "diggCount", "like_count", "likes"),
        "collects": ("collect_count", "collectCount", "favorite_count"),
        "comments": ("comment_count", "commentCount", "comments"),
        "shares": ("share_count", "shareCount", "forward_count"),
    },
}


def _coerce_count(val):
    """把 12000 / '3,456' / '1.2万' / '8.5w' 之类的计数统一成 int；无法解析返回 None。"""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return int(val) if val >= 0 else None
    if isinstance(val, str):
        s = val.strip().replace(",", "").replace("+", "")
        if not s or s in ("-", "—"):
            return None
        mult = 1
        if s.endswith("亿"):
            mult, s = 100000000, s[:-1]
        elif s.endswith(("万", "w", "W")):
            mult, s = 10000, s[:-1]
        elif s.endswith(("k", "K")):
            mult, s = 1000, s[:-1]
        try:
            n = float(s)
        except ValueError:
            return None
        return int(n * mult) if n >= 0 else None
    return None


def build_stats(platform: str, meta: dict) -> dict:
    """从平台元数据提取下载时点的互动数据；一个都没拿到时返回 {}。"""
    if not isinstance(meta, dict):
        return {}
    merged = dict(meta)
    # B 站 stat / 抖音 statistics 是嵌套结构（有时被序列化成 JSON 字符串），摊平后一起找
    for nest_key in ("stat", "statistics"):
        nested = merged.get(nest_key)
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except Exception:  # noqa: BLE001
                nested = None
        if isinstance(nested, dict):
            for k, v in nested.items():
                merged.setdefault(k, v)
    out = {}
    for field, keys in STATS_KEY_CANDIDATES.get(platform, {}).items():
        for key in keys:
            if key in merged:
                n = _coerce_count(merged.get(key))
                if n is not None:
                    out[field] = n
                    break
    if out:
        out["capturedAt"] = now_ts()
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
    sync_projection()


def sync_projection(force: bool = False):
    """把主数据投影成 <vault>/agent/ 下的 Agent 可读文件树。

    挂在 save_posts() 后面：那是全部数据变更的唯一出口，挂在这里不会漏。投影是
    派生数据，失败只记录不上抛——采集链路的可用性优先于派生数据的实时性，缺的
    部分下次 `quarry reindex` 会补齐。
    """
    if not AGENT_PROJECTION:
        return None
    try:
        return projection.sync(VAULT_ROOT, list(POSTS), list(TOPICS), force=force)
    except Exception as e:  # noqa: BLE001
        print(f"[agent] 投影失败：{e}")
        return None


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


def list_opencli_profiles():
    """读 opencli profile list，解析成 [{contextId, alias, default}]。

    输出每行形如 `  wv6jkfus quarry — connected v1.0.22`，没有别名时中间那段就没有，
    被设成默认的那个会多一个 `default` 标记。opencli 没有 JSON 输出，只能按文本解析。
    命令跑不起来时返回 None，跟"跑起来了但一个都没连"区分开。
    """
    try:
        p = subprocess.run([OPENCLI, "profile", "list"], capture_output=True, text=True,
                           timeout=20, stdin=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return None
    if p.returncode != 0:
        return None
    out = []
    for line in p.stdout.splitlines():
        head, sep, _ = line.partition("—")
        if not sep:
            continue
        tokens = head.split()
        if not tokens:
            continue
        rest = tokens[1:]
        out.append({
            "contextId": tokens[0],
            "alias": next((t for t in rest if t != "default"), ""),
            "default": "default" in rest,
        })
    return out


def check_opencli_profile():
    """启动时把采集用哪个浏览器 profile 定死。

    两种情况都会让采集全线失败，值得在启动时先花一秒问清楚：
    - 配了个没连上的别名，每条命令都报错；
    - 同时连着多个 profile 又不指定，opencli 直接拒绝执行
      （BROWSER_CONNECT / Multiple Browser Bridge profiles are connected，exit 69），
      注意 `opencli profile use` 设的默认值救不了这种情况，必须显式传。
    """
    global OPENCLI_PROFILE
    profiles = list_opencli_profiles()
    if profiles is None:
        return  # opencli 本身就跑不起来，留给真正的采集命令去报错
    names = {p["contextId"] for p in profiles} | {p["alias"] for p in profiles if p["alias"]}
    if OPENCLI_PROFILE and OPENCLI_PROFILE in names:
        print(f"[opencli] 采集走专用浏览器 profile：{OPENCLI_PROFILE}")
        return
    if OPENCLI_PROFILE:
        print(f"[opencli] 警告：profile「{OPENCLI_PROFILE}」没连上 Browser Bridge，本次不用它")
        print("          在专用浏览器里装好扩展后，用 opencli profile list 找到 contextId，"
              f"再 opencli profile rename <contextId> {OPENCLI_PROFILE}，然后重启本服务")
        OPENCLI_PROFILE = ""
    if len(profiles) > 1:
        pick = next((p for p in profiles if p["default"]), profiles[0])
        OPENCLI_PROFILE = pick["alias"] or pick["contextId"]
        print(f"[opencli] 同时连着 {len(profiles)} 个 Browser Bridge profile，"
              f"不指定的话 opencli 会拒绝执行，本次显式用：{OPENCLI_PROFILE}")


def run_opencli_site(site: str, args, timeout=120):
    """所有 opencli 调用的唯一出口。

    窗口/profile/会话这三个"别来打扰我"的开关在这里统一注入，调用方不用各自记得写，
    也就不会再出现某条命令漏了 --window background 就把浏览器怼到最前面的情况。
    """
    args = list(args)
    cmd = [OPENCLI]
    if OPENCLI_PROFILE:
        cmd += ["--profile", OPENCLI_PROFILE]
    cmd += [site] + args
    if OPENCLI_WINDOW and "--window" not in args:
        cmd += ["--window", OPENCLI_WINDOW]
    if OPENCLI_SITE_SESSION and "--site-session" not in args:
        cmd += ["--site-session", OPENCLI_SITE_SESSION]
    # 命令行参数之外再兜一层环境变量：opencli 内部再起子命令时也照样是背景窗口
    env = dict(os.environ)
    if OPENCLI_WINDOW:
        env["OPENCLI_WINDOW"] = OPENCLI_WINDOW
    if OPENCLI_PROFILE:
        env["OPENCLI_PROFILE"] = OPENCLI_PROFILE
    with _site_lock(site):
        try:
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, stdin=subprocess.DEVNULL,
                                  cwd=VAULT_ROOT, env=env)
        except subprocess.TimeoutExpired:
            # 超时按"这条命令失败"处理，不要炸掉整次导入：浏览器桥被别的活占住时，
            # 一条字幕命令超时不该让已经抓到的正文和视频全部作废（队列跑无人值守，
            # 这点尤其要紧）。调用点本来就有 returncode != 0 的降级分支。
            return subprocess.CompletedProcess(
                cmd, 124, "", f"opencli {site} {args[0] if args else ''} 超时（{timeout}s），已跳过")


def run_opencli(args, timeout=120):
    return run_opencli_site("twitter", args, timeout=timeout)


def fetch_thread(tid: str):
    p = run_opencli(["thread", tid, "--limit", "1", "-f", "json"])
    if p.returncode != 0:
        raise RuntimeError(f"opencli thread 失败(exit {p.returncode}): {p.stderr[:200]}")
    data = json.loads(p.stdout)
    if not isinstance(data, list) or not data:
        raise RuntimeError("opencli thread 未返回帖子")
    return data[0]


def fetch_article(tid: str):
    p = run_opencli(["article", tid, "-f", "json"])
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
        stats = build_stats("x", item)

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
        # 只要有媒体没落地就不算完整：一条都没下来是 failed，下了一部分是 partial
        if remote:
            download_status = "partial" if (media_path or image_path) else "failed"
        else:
            download_status = "success" if (media_path or image_path) else "skipped"

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
            **extract_frames(media_path, warnings),
            "downloadStatus": download_status,
            "stats": stats,
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
    elif res.get("noSpeech"):
        # 已确认没有人声，与「还没转写」区分开，避免以后反复重试。
        out["transcriptSource"] = "none"
    if res["srtPath"]:
        out["transcriptSrtPath"] = relpath(res["srtPath"])
    if res["mdPath"]:
        out["transcriptMdPath"] = relpath(res["mdPath"])
    if res["audioPath"]:
        out["audioPath"] = relpath(res["audioPath"])
    return out


def extract_frames(media_rel: str, warnings: list) -> dict:
    """抽关键帧。视频本身没法进剪贴板也没法喂给纯文本消费方，静帧是它的可读替身。"""
    out = {"framesDir": "", "frameCount": 0}
    if not media_rel:
        return out
    res = keyframes.extract(os.path.join(VAULT_ROOT, media_rel))
    if res["count"]:
        out["framesDir"] = relpath(res["dir"])
        out["frameCount"] = res["count"]
    else:
        warnings.extend(res["warnings"])
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


def fetch_bilibili_view(bvid: str) -> dict:
    """B 站稿件详情走公开接口拿，不占浏览器。

    标题/简介/封面/UP 主/播放点赞收藏评论分享这一整套都在这个接口里，且不需要登录。
    拿不到就返回 {}，调用方自己退回 opencli。
    """
    if not re.fullmatch(r"BV[0-9A-Za-z]+", bvid or ""):
        return {}
    api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    try:
        req = urllib.request.Request(api, headers={
            "User-Agent": UA, "Referer": f"https://www.bilibili.com/video/{bvid}/"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return {}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {}
    meta = dict(data)
    pubdate = data.get("pubdate")
    if isinstance(pubdate, (int, float)) and pubdate > 0:
        meta["published"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(pubdate)))
    return meta


def _parse_ts_seconds(value) -> "float | None":
    """把时间戳解析成秒，兼容三种形态；解析不出来返回 None。

    - 纯数字 12.34
    - opencli subtitle 的 "12.34s"
    - opencli summary 的时钟串 "MM:SS" / "H:MM:SS"（小时位未补零）
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return None if value < 0 else float(value)
    s = str(value).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        if len(parts) > 3:
            return None
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        total = 0.0
        for n in nums:
            total = total * 60 + n
    else:
        try:
            total = float(s.rstrip("sS").strip())
        except ValueError:
            return None
    return None if total < 0 else total


def _first_present(d: dict, *keys):
    """取第一个存在且非 None 的键值（不能用 or，否则 0 秒会被当成缺失）。"""
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _bili_rows_to_timeline(rows: list) -> str:
    """B 站字幕/AI 总结行转时间轴格式；无时间信息时退回纯文本行。

    字幕有起止时间，输出 "[MM:SS → MM:SS] 文本"（与本地 ASR 输出一致）；
    AI 总结只有单个 time，输出 "[MM:SS] 文本"，其首行整体总结无时间戳，走纯文本。
    """
    lines = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        content = str(r.get("content") or "").strip()
        if not content:
            continue
        start = _parse_ts_seconds(_first_present(r, "from", "start", "start_time", "time"))
        end = _parse_ts_seconds(_first_present(r, "to", "end", "end_time"))
        if start is None:
            lines.append(content)
        elif end is None:
            lines.append(f"[{asr_pipeline._fmt_clock(int(start * 1000))}] {content}")
        else:
            lines.append(f"[{asr_pipeline._fmt_clock(int(start * 1000))} → "
                         f"{asr_pipeline._fmt_clock(int(end * 1000))}] {content}")
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
    # 标题/简介/封面/UP 主/互动数据走 B 站公开接口，不用开浏览器；失败才退回 opencli
    meta = fetch_bilibili_view(bvid)
    if not meta:
        p = run_opencli_site("bilibili", ["video", detected.get("canonicalUrl") or url, "-f", "json"], timeout=120)
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
    stats = build_stats("bilibili", meta)

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
                                      "-f", "json"], timeout=1200)
    if dl.returncode != 0:
        warnings.append(f"视频本体下载失败：{(dl.stderr or dl.stdout or '')[:120]}")
    v_media, v_name, _ = _first_existing_media(collect_downloaded_files(video_dir, before))
    if v_media:
        media_path, media_name = v_media, v_name
    elif dl.returncode == 0:
        # 退出码 0 但目录里没多出视频文件，同样是没拿到正片
        warnings.append("视频本体下载未产出文件")

    set_task(task_id, stage="transcribing", topic=topic_id, message="正在获取字幕/总结", warnings=warnings)
    transcript = ""
    transcript_source = ""
    sub = run_opencli_site("bilibili", ["subtitle", detected.get("canonicalUrl") or url, "-f", "json"], timeout=120)
    if sub.returncode == 0:
        try:
            rows = json.loads(sub.stdout)
            if isinstance(rows, list):
                transcript = _bili_rows_to_timeline(rows)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"字幕解析失败：{e}")
    if not transcript:
        summ = run_opencli_site("bilibili", ["summary", detected.get("canonicalUrl") or url, "-f", "json"], timeout=120)
        if summ.returncode == 0:
            try:
                rows = json.loads(summ.stdout)
                if isinstance(rows, list):
                    transcript = _bili_rows_to_timeline(rows)
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
        **extract_frames(media_path, warnings),
        # 只下到封面不算 success：B 站帖必然是视频，正片缺了就是 partial
        "downloadStatus": video_download_status(media_path, image_path),
        "stats": stats,
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
    p = run_opencli_site("xiaohongshu", ["note", detected.get("canonicalUrl") or url, "-f", "json"], timeout=120)
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
    dl = run_opencli_site("xiaohongshu", ["download", detected.get("canonicalUrl") or url, "--output", output_dir, "-f", "json"], timeout=180)
    if dl.returncode != 0:
        warnings.append(f"小红书媒体下载失败：{dl.stderr[:120]}")
    files = collect_downloaded_files(output_dir, before)
    media_path, media_name, image_path = _first_existing_media(files)

    title = str(meta.get("title") or meta.get("标题") or "小红书笔记")
    body_text = str(meta.get("desc") or meta.get("正文") or meta.get("description") or "")
    author = str(meta.get("author") or meta.get("作者") or "")
    stats = build_stats("xiaohongshu", meta)

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
        **extract_frames(media_path, warnings),
        # 笔记可能是图文也可能是视频，拿不到「应该有几个文件」，只能按下载命令是否报错分档：
        # 命令失败但落了几个文件 = partial，一个都没落 = failed
        "downloadStatus": (("success" if dl.returncode == 0 else "partial") if (image_path or media_path)
                           else ("failed" if dl.returncode != 0 else "skipped")),
        "stats": stats,
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
                                   "-f", "json"], timeout=240)
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
                "stats": build_stats("douyin", r),
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
        "stats": build_stats("douyin", item),
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
        "stats": {},
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
        **extract_frames(media_path, warnings),
        "downloadStatus": video_download_status(media_path, image_path),
        "stats": meta.get("stats") or {},
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


# ---------------------------------------------------------------------------
# 待采集队列：先存链接，等人不在电脑前了再批量跑
# ---------------------------------------------------------------------------

def guess_platform(url: str) -> str:
    """只看域名猜平台，不发任何请求。

    入队要快、要不打扰人，所以不能像 detect_platform() 那样为了短链去发 HEAD；
    真正的平台识别留到出队真跑的时候做。
    """
    host = urlparse(url).netloc.lower()
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    if "xiaohongshu.com" in host or "xhslink.com" in host:
        return "xiaohongshu"
    if "douyin.com" in host or "iesdouyin.com" in host:
        return "douyin"
    if "x.com" in host or "twitter.com" in host:
        return "x"
    return ""


def load_queue():
    global QUEUE
    if not os.path.exists(QUEUE_FILE):
        QUEUE = []
        return
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"[queue] 读取失败，按空队列启动：{e}")
        QUEUE = []
        return
    items = raw.get("items") if isinstance(raw, dict) else raw
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not it.get("url"):
            continue
        # 上次是跑到一半被关掉的，重启后回到待采集，让用户自己决定什么时候重来
        status = it.get("status") if it.get("status") in ("queued", "error") else "queued"
        out.append({
            "id": str(it.get("id") or uuid.uuid4().hex[:12]),
            "url": str(it["url"]),
            "topic": str(it.get("topic") or ""),
            "platform": str(it.get("platform") or guess_platform(str(it["url"]))),
            "status": status,
            "addedAt": int(it.get("addedAt") or now_ts()),
            "taskId": "",
            "message": str(it.get("message") or ""),
        })
    QUEUE = out
    if QUEUE:
        print(f"[queue] 待采集 {len(QUEUE)} 条（在界面上按「开始采集」才会跑）")


def save_queue():
    tmp = QUEUE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "items": QUEUE}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, QUEUE_FILE)


def enqueue_links(urls: list, topic_id: str) -> list:
    """把链接压进待采集队列。同一课题下重复的链接直接跳过。"""
    added = []
    with LOCK:
        seen = {(it["topic"], it["url"]) for it in QUEUE}
        for url in urls:
            if (topic_id, url) in seen:
                continue
            seen.add((topic_id, url))
            item = {
                "id": uuid.uuid4().hex[:12], "url": url, "topic": topic_id,
                "platform": guess_platform(url), "status": "queued",
                "addedAt": now_ts(), "taskId": "", "message": "",
            }
            QUEUE.append(item)
            added.append(item)
        if added:
            save_queue()
    return added


def queue_snapshot() -> dict:
    with LOCK:
        return {
            "items": [dict(it) for it in QUEUE],
            "draining": QUEUE_STATE["draining"],
            "stopping": QUEUE_STATE["stopping"],
            "queued": sum(1 for it in QUEUE if it["status"] == "queued"),
        }


def _drain_queue():
    """逐条把队列跑完。串行是故意的：一次只占一个浏览器标签页。"""
    try:
        while True:
            with LOCK:
                if QUEUE_STATE["stopping"]:
                    break
                item = next((it for it in QUEUE if it["status"] == "queued"), None)
                if item is None:
                    break
                task_id = uuid.uuid4().hex[:12]
                item["status"] = "running"
                item["taskId"] = task_id
                item["message"] = "已创建任务"
                QUEUE_STATE["currentId"] = item["id"]
                save_queue()
            set_task(task_id, stage="pending", topic=item["topic"], message="已创建任务", warnings=[])
            process_add(task_id, item["url"], item["topic"])
            task = get_task(task_id)
            with LOCK:
                still = next((it for it in QUEUE if it["id"] == item["id"]), None)
                if still is not None:
                    if task.get("stage") == "error":
                        # 失败的留在队列里显示原因，用户可以重试或删掉
                        still["status"] = "error"
                        still["message"] = task.get("message") or "采集失败"
                        still["taskId"] = ""
                    else:
                        QUEUE.remove(still)
                QUEUE_STATE["currentId"] = ""
                save_queue()
    finally:
        with LOCK:
            QUEUE_STATE["draining"] = False
            QUEUE_STATE["stopping"] = False
            QUEUE_STATE["currentId"] = ""


def start_queue() -> dict:
    with LOCK:
        if QUEUE_STATE["draining"]:
            return queue_snapshot()
        if not any(it["status"] == "queued" for it in QUEUE):
            return queue_snapshot()
        QUEUE_STATE["draining"] = True
        QUEUE_STATE["stopping"] = False
    threading.Thread(target=_drain_queue, daemon=True).start()
    return queue_snapshot()


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
        if path == "/api/meta":
            # 前端「复制给 AI」要拼本机绝对路径，媒体路径在 posts.json 里是相对内容层
            # 根的，所以得把根目录告诉前端。
            with LOCK:
                self._send_json({"vaultRoot": VAULT_ROOT, "version": DATA_VERSION,
                                 "posts": len(POSTS), "topics": len(TOPICS)})
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
        if path == "/api/queue":
            self._send_json(queue_snapshot())
            return
        self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path

        # --- 待采集队列 ---
        if path == "/api/queue/start":
            self._send_json(start_queue())
            return
        if path == "/api/queue/stop":
            with LOCK:
                if QUEUE_STATE["draining"]:
                    QUEUE_STATE["stopping"] = True
            self._send_json(queue_snapshot())
            return
        m = re.fullmatch(r"/api/queue/([^/]+)/retry", path)
        if m:
            qid = unquote(m.group(1))
            with LOCK:
                item = next((it for it in QUEUE if it["id"] == qid), None)
                if not item:
                    self._send_json({"error": f"队列里没有这一条：{qid}"}, 404)
                    return
                if item["status"] == "running":
                    self._send_json({"error": "这一条正在采集中"}, 400)
                    return
                item["status"] = "queued"
                item["message"] = ""
                save_queue()
            self._send_json(queue_snapshot())
            return

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

        # defer=true：只把链接压进待采集队列，一个浏览器页都不开
        if payload.get("defer"):
            added = enqueue_links(url_list, topic_id)
            snap = queue_snapshot()
            snap["added"] = added
            snap["skipped"] = len(url_list) - len(added)
            self._send_json(snap)
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
        # 关键帧是一整个目录（<视频名>.关键帧/），不在上面按文件删的清单里，
        # 漏掉的话每删一条视频就在内容层留下一整目录静帧（存量 38 个目录 8MB 量级）。
        # 这里不能走 _safe_local_path：它是按文件找的，目录命中不了 isfile，
        # 会回落到第一个根（产品层 app/）的候选路径，导致这段静默不生效。
        frames_rel = str(post.get("framesDir") or "")
        if frames_rel:
            full = os.path.normpath(os.path.join(VAULT_ROOT, frames_rel))
            # 只删自己抽帧产出的目录：normpath 后必须仍在内容层内，且带抽帧后缀
            if not full.startswith(VAULT_ROOT + os.sep):
                warnings.append(f"关键帧目录越界，未删除：{frames_rel}")
            elif os.path.isdir(full):
                if not os.path.basename(full).endswith(keyframes.FRAMES_SUFFIX):
                    warnings.append(f"关键帧目录名不符合抽帧命名，未删除：{frames_rel}")
                else:
                    try:
                        shutil.rmtree(full)
                        dirs.add(os.path.dirname(full))
                    except Exception as e:  # noqa: BLE001
                        warnings.append(f"关键帧目录删除失败：{frames_rel} ({e})")
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

        # --- 待采集队列：清空 / 删单条（正在跑的那条不动）---
        if path == "/api/queue":
            with LOCK:
                kept = [it for it in QUEUE if it["status"] == "running"]
                removed = len(QUEUE) - len(kept)
                QUEUE[:] = kept
                save_queue()
            snap = queue_snapshot()
            snap["removed"] = removed
            self._send_json(snap)
            return
        if path.startswith("/api/queue/"):
            qid = unquote(path[len("/api/queue/"):])
            with LOCK:
                item = next((it for it in QUEUE if it["id"] == qid), None)
                if not item:
                    self._send_json({"error": f"队列里没有这一条：{qid}"}, 404)
                    return
                if item["status"] == "running":
                    self._send_json({"error": "这一条正在采集中，先停止队列再删"}, 400)
                    return
                QUEUE.remove(item)
                save_queue()
            snap = queue_snapshot()
            snap["removed"] = 1
            self._send_json(snap)
            return

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
            with_media = (query.get("media") or ["0"])[0] in ("1", "true", "yes")
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
            # 连帖子一起删时，媒体文件也一并清理，否则内容层会留下没人引用的孤儿文件
            warnings = []
            if with_media:
                for p in related:
                    warnings.extend(self._delete_post_files(p))
            self._send_json({"ok": True, "removed": topic_id,
                             "removedPosts": len(related), "warnings": warnings})
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
    load_queue()
    check_opencli_profile()
    # 投影自检：索引行数与主数据条数对不上就全量重建（首启、格式升级、外部改动）
    if AGENT_PROJECTION and projection.index_is_stale(VAULT_ROOT, len(POSTS)):
        st = sync_projection(force=True)
        if st:
            print(f"[agent] 投影重建：{st['total']} 条 / 写入 {st['written']} / 删除 {st['deleted']}"
                  f"{' / 失败 ' + str(st['errors']) if st['errors'] else ''}")
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
