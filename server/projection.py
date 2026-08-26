#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内容层 Agent 投影：把 posts.json 渲染成可被 Agent 直接 grep / read 的文件树。

产出（全部落在内容层 <vault>/agent/，不进 git）：

    agent/
    ├── README.md                       入口说明：库的构成、字段含义、检索建议
    ├── index.jsonl                     一行一帖的轻量索引
    ├── .manifest.json                  渲染清单，用于跳过未变文件
    └── topics/<课题 id>/
        ├── _topic.md                   课题说明 + 帖子目录
        └── <序号>-<标题>.md            单帖全文

真相源始终是 data/posts.json，本模块只做单向派生。增量同步与全量重建走同一段
渲染代码，差别只在是否信任清单里的哈希，因此两者结果必然一致。

口播全文直接读 transcriptMdPath 指向的文件，绕开 posts.json 里 16KB 的 transcript
截断，这是投影相对主数据唯一"更全"的地方。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import re
import time

# 渲染格式版本。改动任何渲染逻辑都要 +1，用于强制全量重渲。
RENDER_VERSION = 2

AGENT_DIRNAME = "agent"
INDEX_NAME = "index.jsonl"
TOPICS_NAME = "topics.json"
MANIFEST_NAME = ".manifest.json"
ERRORS_NAME = ".sync-errors.log"
TOPICS_DIRNAME = "topics"

# 文件名里的标题片段上限（字符数，不是字节）。
SLUG_LIMIT = 40
# frontmatter 里单条 warning 的长度上限。
WARNING_LIMIT = 200
# 索引里摘要的长度上限。索引要保持轻量，全文在单帖 md 里。
INDEX_SUMMARY_LIMIT = 200


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------

def agent_root(vault_root: str) -> str:
    return os.path.join(vault_root, AGENT_DIRNAME)


def index_path(vault_root: str) -> str:
    return os.path.join(agent_root(vault_root), INDEX_NAME)


def topics_path(vault_root: str) -> str:
    return os.path.join(agent_root(vault_root), TOPICS_NAME)


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------

_UNSAFE_FILENAME = re.compile(r"[\x00-\x1f/\\:*?\"<>|]+")
_SPACES = re.compile(r"\s+")


def slug_title(title: str) -> str:
    """标题转文件名片段。保留中文，去掉文件系统敏感字符。"""
    s = _UNSAFE_FILENAME.sub("", str(title or "").strip())
    s = _SPACES.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-._")
    return s[:SLUG_LIMIT] or "untitled"


def _yaml_scalar(value) -> str:
    """YAML 标量。字符串一律走 JSON 引号形式——JSON 是 YAML 1.2 的子集，
    这样不用自己处理冒号、井号、前导空格等一堆转义歧义。"""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return '""'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def _yaml_list(values) -> str:
    return "[" + ", ".join(_yaml_scalar(v) for v in values) + "]"


def iso_time(ts) -> str:
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def _text(value) -> str:
    return str(value or "").strip()


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------------------
# 口播词文件解析
# ---------------------------------------------------------------------------

def read_transcript(vault_root: str, rel_path: str) -> tuple:
    """读 asr.py 产出的口播词 md，拆成（纯文本, 分句时间轴）。

    格式见 server/asr.py build_koubo_md：一级标题 + 来源信息 +「## 纯文本」+
    可选的「## 分句时间轴」。文件缺失或格式不符时返回空串，不抛异常——投影
    的可用性不应该被单个转写文件拖垮。
    """
    rel_path = _text(rel_path)
    if not rel_path:
        return "", ""
    full = os.path.join(vault_root, rel_path)
    try:
        with open(full, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return "", ""
    plain, timeline = "", ""
    section = None
    buf = {"plain": [], "timeline": []}
    for line in raw.splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            section = {"纯文本": "plain", "分句时间轴": "timeline"}.get(head)
            continue
        if section:
            buf[section].append(line)
    plain = "\n".join(buf["plain"]).strip()
    timeline = "\n".join(buf["timeline"]).strip()
    return plain, timeline


def transcript_signature(vault_root: str, rel_path: str) -> str:
    """口播词文件的变更签名。只用于清单比对，不进渲染内容。"""
    rel_path = _text(rel_path)
    if not rel_path:
        return ""
    try:
        st = os.stat(os.path.join(vault_root, rel_path))
    except OSError:
        return "missing"
    return f"{st.st_mtime_ns}:{st.st_size}"


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

MEDIA_FIELDS = (
    ("main", "mediaPath"),
    ("cover", "imagePath"),
    ("audio", "audioPath"),
    ("srt", "transcriptSrtPath"),
    ("transcriptMd", "transcriptMdPath"),
    ("frames", "framesDir"),
)


def render_post_md(post: dict, topic: dict, plain: str, timeline: str) -> str:
    """单帖 markdown。frontmatter 只放结构化字段，正文放可读内容。

    rawMeta 不进投影：它是平台原始响应的调试残留，体积不可控，对内容理解无贡献。
    """
    fm = []
    fm.append("---")
    fm.append(f"uid: {_yaml_scalar(post.get('uid'))}")
    fm.append(f"topic: {_yaml_scalar(post.get('topic'))}")
    fm.append(f"topicName: {_yaml_scalar(topic.get('name'))}")
    number = post.get("number")
    fm.append(f"number: {_yaml_scalar(number if isinstance(number, int) else 0)}")
    fm.append(f"platform: {_yaml_scalar(post.get('platform'))}")
    fm.append(f"contentType: {_yaml_scalar(post.get('contentType'))}")
    fm.append(f"author: {_yaml_scalar(post.get('author'))}")
    if _text(post.get("handle")):
        fm.append(f"handle: {_yaml_scalar(post.get('handle'))}")
    fm.append(f"published: {_yaml_scalar(post.get('published'))}")
    added = iso_time(post.get("addedAt"))
    if added:
        fm.append(f"addedAt: {_yaml_scalar(added)}")
    fm.append(f"sourceLink: {_yaml_scalar(post.get('sourceLink'))}")
    keywords = [k for k in (post.get("keywords") or []) if _text(k)]
    if keywords:
        fm.append(f"keywords: {_yaml_list(keywords)}")

    stats = {k: v for k, v in (post.get("stats") or {}).items() if v not in ("", None)}
    if stats:
        fm.append("stats:")
        for key in ("views", "likes", "collects", "comments", "shares", "capturedAt"):
            if key in stats:
                val = stats[key]
                if key == "capturedAt":
                    val = iso_time(val) or val
                fm.append(f"  {key}: {_yaml_scalar(val)}")
        for key in sorted(k for k in stats if k not in
                          ("views", "likes", "collects", "comments", "shares", "capturedAt")):
            fm.append(f"  {key}: {_yaml_scalar(stats[key])}")

    media = [(name, _text(post.get(field))) for name, field in MEDIA_FIELDS]
    media = [(name, val) for name, val in media if val]
    if media:
        fm.append("media:")
        for name, val in media:
            fm.append(f"  {name}: {_yaml_scalar(val)}")
    remote = [u for u in (post.get("remoteMedia") or []) if _text(u)]
    if remote:
        fm.append(f"remoteMedia: {_yaml_list(remote)}")

    fm.append(f"downloadStatus: {_yaml_scalar(post.get('downloadStatus'))}")
    if _text(post.get("transcriptSource")):
        fm.append(f"transcriptSource: {_yaml_scalar(post.get('transcriptSource'))}")
    if post.get("frameCount"):
        fm.append(f"frameCount: {_yaml_scalar(int(post['frameCount']))}")
    fm.append(f"hasTranscript: {_yaml_scalar(bool(plain))}")
    if plain:
        fm.append(f"transcriptChars: {len(plain)}")
    warnings = [_text(w)[:WARNING_LIMIT] for w in (post.get("warnings") or []) if _text(w)]
    if warnings:
        fm.append(f"warnings: {_yaml_list(warnings)}")
    fm.append("---")

    body = [""]
    body.append(f"# {_text(post.get('title')) or '(无标题)'}")

    summary = _text(post.get("summary"))
    if summary:
        body += ["", "## 摘要", "", summary]

    main_body = _text(post.get("body"))
    if main_body:
        body += ["", "## 正文", "", main_body]

    original = _text(post.get("originalText"))
    if original:
        body += ["", "## 平台原文", ""]
        if post.get("originalIsExcerpt"):
            note = _text(post.get("originalNote"))
            body.append(f"> 节选{('：' + note) if note else ''}")
            body.append("")
        body.append(original)

    supplement = _text(post.get("supplement"))
    if supplement:
        body += ["", "## 补充", "", supplement]

    if plain:
        body += ["", "## 口播全文", "", plain]
    if timeline:
        body += ["", "## 口播时间轴", "", timeline]

    links = [u for u in (post.get("articleLinks") or []) if _text(u)]
    if links:
        body += ["", "## 站外链接", ""]
        body += [f"- {u}" for u in links]

    body += ["", "## 来源", "", f"- 原帖：{_text(post.get('sourceLink')) or '(无)'}"]
    for name, val in media:
        note = f"（{post['frameCount']} 张）" if name == "frames" and post.get("frameCount") else ""
        body.append(f"- {name}{note}：`{val}`")
    body.append("")
    return "\n".join(fm) + "\n".join(body)


def index_row(post: dict, topic: dict, rel_file: str, plain: str) -> dict:
    return {
        "uid": post.get("uid"),
        "topic": post.get("topic"),
        "topicName": topic.get("name"),
        "number": post.get("number") if isinstance(post.get("number"), int) else 0,
        "platform": post.get("platform"),
        "contentType": post.get("contentType"),
        "title": _text(post.get("title")),
        "author": _text(post.get("author")),
        "handle": _text(post.get("handle")),
        "published": _text(post.get("published")),
        "addedAt": int(post.get("addedAt") or 0),
        "summary": clip(_text(post.get("summary")), INDEX_SUMMARY_LIMIT),
        "keywords": [k for k in (post.get("keywords") or []) if _text(k)],
        "stats": {k: v for k, v in (post.get("stats") or {}).items() if v not in ("", None)},
        "hasTranscript": bool(plain),
        "transcriptChars": len(plain),
        "bodyChars": len(_text(post.get("body"))),
        "hasMedia": bool(_text(post.get("mediaPath")) or _text(post.get("imagePath"))),
        "frameCount": int(post.get("frameCount") or 0),
        "downloadStatus": _text(post.get("downloadStatus")),
        "warningCount": len([w for w in (post.get("warnings") or []) if _text(w)]),
        "file": rel_file,
        "sourceLink": _text(post.get("sourceLink")),
    }


def render_topic_md(topic: dict, rows: list) -> str:
    out = [
        "---",
        f"topic: {_yaml_scalar(topic.get('id'))}",
        f"name: {_yaml_scalar(topic.get('name'))}",
        f"postCount: {len(rows)}",
        "---",
        "",
        f"# {_text(topic.get('name')) or topic.get('id')}",
    ]
    desc = _text(topic.get("description"))
    if desc:
        out += ["", desc]
    out += ["", f"共 {len(rows)} 条。", "", "| # | 平台 | 标题 | 作者 | 转写 | 文件 |",
            "|---|------|------|------|------|------|"]
    for row in rows:
        name = os.path.basename(row["file"])
        title = row["title"].replace("|", "\\|")
        author = row["author"].replace("|", "\\|")
        out.append(f"| {row['number']} | {row['platform']} | {title} | {author} | "
                   f"{'有' if row['hasTranscript'] else '无'} | [{name}]({name}) |")
    out.append("")
    return "\n".join(out)


README_TEXT = """# Quarry 内容层 · Agent 读取入口

这个目录是 `data/posts.json` 的只读派生投影，由 `server/projection.py` 生成，
供 AI Agent 直接检索与阅读。**人工编辑这里的文件不会回写主数据，且会在下次
重建时被覆盖。**

## 构成

| 路径 | 内容 |
|------|------|
| `topics.json` | 课题清单：条数、平台分布、最近更新 |
| `index.jsonl` | 一行一帖的轻量索引，可按行 grep，不必整文件解析 |
| `topics/<课题 id>/_topic.md` | 课题说明与帖子目录 |
| `topics/<课题 id>/<序号>-<标题>.md` | 单帖全文 |

## 检索建议

先读 `index.jsonl` 定位，再按其中的 `file` 字段取单帖全文。不要一次性读入
全部单帖文件——这个库会持续增长。

命令行入口（无需启动 Quarry 服务）：

```bash
quarry topics                     # 课题清单
quarry search "关键词" --topic X  # 检索
quarry show <uid> --full          # 单帖全文，含口播
```

## 字段说明

| 字段 | 含义 |
|------|------|
| `uid` | 全库唯一 id，形如 `<课题>__<平台>__<平台内 id>` |
| `number` | 课题内序号，同时是文件名前缀 |
| `platform` | `x` / `bilibili` / `xiaohongshu` / `douyin` |
| `published` | 平台发布时间，各平台格式不统一，原样保留 |
| `addedAt` | 收藏进库的时间 |
| `stats` | **收藏时刻**的互动数据快照，不随时间更新，引用时请一并引用 `capturedAt` |
| `hasTranscript` | 是否有口播转写。单帖 md 里的口播全文不截断 |
| `warnings` | 采集过程中的告警。非空表示媒体或转写可能缺失 |

## 与主数据的差异

- 口播全文取自 `transcriptMdPath` 指向的文件，不受 `posts.json` 中 `transcript`
  字段 16KB 截断的限制。
- `rawMeta`（平台原始响应）不进投影，需要时查 `data/posts.json`。
"""


# ---------------------------------------------------------------------------
# 同步
# ---------------------------------------------------------------------------

def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _write_if_changed(path: str, text: str) -> bool:
    """内容相同就不落盘，避免无谓的 mtime 抖动干扰同步盘与文件监听。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    _atomic_write(path, text)
    return True


def _load_manifest(root: str) -> dict:
    try:
        with open(os.path.join(root, MANIFEST_NAME), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if data.get("renderVersion") != RENDER_VERSION:
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _log_error(root: str, message: str) -> None:
    try:
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, ERRORS_NAME), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


def _plan(posts: list, topics: list) -> list:
    """确定每条帖子的目标文件路径与顺序。课题按 topics 顺序，课题内按 number 升序。"""
    by_id = {t.get("id"): t for t in topics}
    order = {t.get("id"): i for i, t in enumerate(topics)}
    fallback = len(topics)
    ordered = sorted(
        posts,
        key=lambda p: (order.get(p.get("topic"), fallback), p.get("topic") or "",
                       p.get("number") if isinstance(p.get("number"), int) else 0,
                       p.get("uid") or ""),
    )
    seen = set()
    plan = []
    for post in ordered:
        topic_id = post.get("topic") or ""
        topic = by_id.get(topic_id) or {"id": topic_id, "name": topic_id, "description": ""}
        number = post.get("number") if isinstance(post.get("number"), int) else 0
        name = f"{number:03d}-{slug_title(post.get('title'))}"
        rel = f"{TOPICS_DIRNAME}/{topic_id}/{name}.md"
        if rel in seen:
            # 序号加标题仍然撞车时用 uid 尾巴消歧，保证一帖一文件。
            tail = hashlib.sha1((post.get("uid") or "").encode("utf-8")).hexdigest()[:6]
            rel = f"{TOPICS_DIRNAME}/{topic_id}/{name}-{tail}.md"
        seen.add(rel)
        plan.append((post, topic, rel))
    return plan


def _render_key(post: dict, topic: dict, rel: str, sig: str) -> str:
    payload = json.dumps(
        {"post": post, "topicName": topic.get("name"), "file": rel,
         "sig": sig, "v": RENDER_VERSION},
        ensure_ascii=False, sort_keys=True, default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def sync(vault_root: str, posts: list, topics: list, force: bool = False) -> dict:
    """把 posts/topics 投影到 <vault>/agent/。

    force=False 时按清单里的哈希跳过未变的帖子；force=True 时全量重渲。两条路径
    的渲染逻辑完全相同，因此产物一致——这是 reindex 可以用来自检的前提。

    返回统计信息，不抛异常给调用方：投影是派生数据，它的失败不该阻断采集链路。
    """
    root = agent_root(vault_root)
    stats = {"total": len(posts), "written": 0, "skipped": 0, "deleted": 0, "errors": 0}
    try:
        os.makedirs(os.path.join(root, TOPICS_DIRNAME), exist_ok=True)
    except OSError as e:
        _log_error(root, f"创建目录失败：{e}")
        stats["errors"] += 1
        return stats

    manifest = {} if force else _load_manifest(root)
    plan = _plan(posts, topics)
    new_manifest = {}
    rows_by_topic = {}
    index_rows = []

    for post, topic, rel in plan:
        uid = post.get("uid") or rel
        sig = transcript_signature(vault_root, post.get("transcriptMdPath"))
        key = _render_key(post, topic, rel, sig)
        full = os.path.join(root, rel)
        prev = manifest.get(uid) or {}
        cached = prev.get("key") == key and prev.get("file") == rel and os.path.exists(full)

        plain, timeline = read_transcript(vault_root, post.get("transcriptMdPath"))
        row = index_row(post, topic, rel, plain)

        if cached:
            stats["skipped"] += 1
        else:
            try:
                _atomic_write(full, render_post_md(post, topic, plain, timeline))
                stats["written"] += 1
            except OSError as e:
                _log_error(root, f"写入 {rel} 失败：{e}")
                stats["errors"] += 1
                continue

        new_manifest[uid] = {"key": key, "file": rel}
        index_rows.append(row)
        rows_by_topic.setdefault(topic.get("id"), []).append(row)

    # 清掉改名或已删除的帖子留下的旧文件。
    keep = {entry["file"] for entry in new_manifest.values()}
    for uid, entry in manifest.items():
        old = entry.get("file")
        if old and old not in keep:
            try:
                os.remove(os.path.join(root, old))
                stats["deleted"] += 1
            except OSError:
                pass

    # 全量重建时顺带清理清单之外的游离 md（历史格式、人工残留）。
    if force:
        stats["deleted"] += _prune(root, keep)

    topic_rows = []
    for topic in topics:
        tid = topic.get("id")
        rows = rows_by_topic.get(tid, [])
        _write_if_changed(os.path.join(root, TOPICS_DIRNAME, tid, "_topic.md"),
                          render_topic_md(topic, rows))
        topic_rows.append({
            "id": tid,
            "name": _text(topic.get("name")) or tid,
            "description": _text(topic.get("description")),
            "postCount": len(rows),
            "platforms": sorted({r["platform"] for r in rows if r["platform"]}),
            "withTranscript": sum(1 for r in rows if r["hasTranscript"]),
            "latestAddedAt": max([r["addedAt"] for r in rows] or [0]),
            "createdAt": int(topic.get("createdAt") or 0),
            "updatedAt": int(topic.get("updatedAt") or 0),
        })

    # 课题被删掉之后，它在 topics/ 下的目录不会有任何东西来触发清理：帖子 md 会被上面的
    # manifest 差分删掉，但 _topic.md 不在 manifest 里，_prune 又特意跳过它，于是目录里
    # 永远剩着一个 _topic.md、永远不为空、永远删不掉。结果是 agent 层留着一份写着
    # "验收测试 … 共 7 条" 的说明，而那个课题已经不存在了——AI 去 grep 就读到假数据。
    # 这里按"活着的课题 id"兜底清理，不依赖 force：删课题是常规操作，不该等到全量重建。
    stats["deleted"] += _prune_dead_topic_dirs(root, {t.get("id") for t in topics})

    _atomic_write(topics_path(vault_root), json.dumps(topic_rows, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(index_path(vault_root),
                  "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in index_rows))
    _write_if_changed(os.path.join(root, "README.md"), README_TEXT)
    _atomic_write(os.path.join(root, MANIFEST_NAME),
                  json.dumps({"renderVersion": RENDER_VERSION, "updatedAt": int(time.time()),
                              "entries": new_manifest}, ensure_ascii=False, indent=2))
    return stats


def _prune_dead_topic_dirs(root: str, live_ids: set) -> int:
    """删掉 topics/ 下那些课题已经不存在了的整目录，返回删掉的文件数。

    只认"目录名不在活着的课题 id 里"这一条，不看目录内容——课题没了，它底下的
    _topic.md 和残留帖子 md 就都是过期数据，整个端掉。活着的课题一律不碰，
    哪怕它一条帖子都没有（比如新建还没收藏的课题，_topic.md 该留着）。
    """
    removed = 0
    base = os.path.join(root, TOPICS_DIRNAME)
    if not os.path.isdir(base):
        return 0
    for topic_dir in os.listdir(base):
        full_dir = os.path.join(base, topic_dir)
        if not os.path.isdir(full_dir) or topic_dir in live_ids:
            continue
        try:
            removed += sum(len(files) for _, _, files in os.walk(full_dir))
            shutil.rmtree(full_dir)
        except OSError:
            pass
    return removed


def _prune(root: str, keep: set) -> int:
    """删掉 topics/ 下不在计划内的 md 文件与随之变空的课题目录。"""
    removed = 0
    base = os.path.join(root, TOPICS_DIRNAME)
    if not os.path.isdir(base):
        return 0
    for topic_dir in os.listdir(base):
        full_dir = os.path.join(base, topic_dir)
        if not os.path.isdir(full_dir):
            continue
        for name in os.listdir(full_dir):
            if not name.endswith(".md") or name == "_topic.md":
                continue
            rel = f"{TOPICS_DIRNAME}/{topic_dir}/{name}"
            if rel not in keep:
                try:
                    os.remove(os.path.join(full_dir, name))
                    removed += 1
                except OSError:
                    pass
        if not os.listdir(full_dir):
            try:
                os.rmdir(full_dir)
            except OSError:
                pass
    return removed


def index_is_stale(vault_root: str, expected: int) -> bool:
    """索引行数与主数据条数是否不一致。用于服务启动时的自检。"""
    try:
        with open(index_path(vault_root), "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip()) != expected
    except OSError:
        return True
