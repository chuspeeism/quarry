#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查询内核：检索、过滤、分页、体量控制。

quarry_cli.py 与 mcp_server.py 都是本模块的适配层，两者返回同构结果，不会出现
行为分叉。数据来自 <vault>/agent/ 投影，不经过 Quarry 的 HTTP 服务。

设计要点：检索返回轻量结果，取详情才返回全文。这是控制 Agent 上下文消耗的核心
——命中列表的体积只与 limit 相关，与库的总量无关。
"""

from __future__ import annotations

import json
import os
import re

import projection

# 命中片段中关键词前后各取的字符数。
SNIPPET_PAD = 40
# 单条命中最多附几段片段。
MAX_SNIPPETS = 3
# 命中列表的默认与上限条数。
DEFAULT_LIMIT = 20
MAX_LIMIT = 50
# 检索结果序列化后的硬上限，超出即截断并标注。
SEARCH_BYTES_CAP = 32 * 1024
# 单帖详情默认返回的字符上限。
DEFAULT_MAX_CHARS = 40000
# 命中列表里摘要的展示长度。
HIT_SUMMARY_LIMIT = 120

# 可检索字段。索引字段直接来自 index.jsonl，正文字段要读单帖 md。
INDEX_FIELDS = ("title", "summary", "author", "handle", "keywords")
BODY_FIELDS = ("body", "originalText", "supplement", "transcript", "timeline")
ALL_FIELDS = INDEX_FIELDS + BODY_FIELDS

# 单帖 md 的区块标题 -> 字段名
SECTION_FIELDS = {
    "摘要": "summary",
    "正文": "body",
    "平台原文": "originalText",
    "补充": "supplement",
    "口播全文": "transcript",
    "口播时间轴": "timeline",
    "站外链接": "articleLinks",
    "来源": "source",
}


class VaultError(Exception):
    """内容层不可用或投影缺失。"""


# ---------------------------------------------------------------------------
# 读取与缓存
# ---------------------------------------------------------------------------

class Vault:
    """一个内容层的只读视图。

    MCP 服务是长驻进程，索引与单帖正文都按 mtime 缓存；CLI 是一次性进程，缓存
    自然失效，不需要区别处理。
    """

    def __init__(self, vault_root: str):
        self.root = vault_root
        self.agent_root = projection.agent_root(vault_root)
        self._index = None
        self._index_sig = None
        self._topics = None
        self._topics_sig = None
        self._md_cache = {}

    # --- 基础 ---

    def _sig(self, path: str):
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def ensure_ready(self):
        if not os.path.exists(projection.index_path(self.root)):
            raise VaultError(
                f"内容层投影不存在：{self.agent_root}\n"
                f"内容层根目录：{self.root}\n"
                f"先执行 `quarry reindex` 生成，或确认 QUARRY_VAULT 是否指对。")

    @property
    def index(self) -> list:
        path = projection.index_path(self.root)
        sig = self._sig(path)
        if self._index is None or sig != self._index_sig:
            self.ensure_ready()
            rows = []
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except ValueError:
                            continue
            self._index, self._index_sig = rows, sig
        return self._index

    @property
    def topics(self) -> list:
        path = projection.topics_path(self.root)
        sig = self._sig(path)
        if self._topics is None or sig != self._topics_sig:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._topics = json.load(f)
            except (OSError, ValueError):
                # 投影是旧版本或缺 topics.json 时，从索引里凑一份，避免整个命令挂掉。
                seen = {}
                for row in self.index:
                    t = seen.setdefault(row["topic"], {
                        "id": row["topic"], "name": row.get("topicName") or row["topic"],
                        "description": "", "postCount": 0, "platforms": set(),
                        "withTranscript": 0, "latestAddedAt": 0,
                    })
                    t["postCount"] += 1
                    t["platforms"].add(row.get("platform"))
                    t["withTranscript"] += 1 if row.get("hasTranscript") else 0
                    t["latestAddedAt"] = max(t["latestAddedAt"], row.get("addedAt") or 0)
                self._topics = [{**t, "platforms": sorted(p for p in t["platforms"] if p)}
                                for t in seen.values()]
            self._topics_sig = sig
        return self._topics

    def row(self, uid: str):
        for r in self.index:
            if r.get("uid") == uid:
                return r
        return None

    def md(self, rel_file: str) -> str:
        path = os.path.join(self.agent_root, rel_file)
        sig = self._sig(path)
        hit = self._md_cache.get(rel_file)
        if hit and hit[0] == sig:
            return hit[1]
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        self._md_cache[rel_file] = (sig, text)
        return text

    def sections(self, rel_file: str) -> dict:
        return parse_sections(self.md(rel_file))


# ---------------------------------------------------------------------------
# 单帖 md 解析
# ---------------------------------------------------------------------------

_FM_SPLIT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def parse_frontmatter(text: str) -> dict:
    """解析 projection.py 产出的 frontmatter。

    只需覆盖本项目自己发出的子集：标量一律是 JSON 形式，列表是 JSON 流式写法，
    嵌套只有 stats / media 两个一层缩进的映射。两边格式由同一个仓库控制，所以
    这个窄解析器比引入 YAML 依赖更合适。
    """
    m = _FM_SPLIT.match(text)
    if not m:
        return {}
    out, current = {}, None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        nested = line.startswith("  ")
        key, _, raw = line.strip().partition(":")
        raw = raw.strip()
        if not _:
            continue
        if nested and current:
            out[current][key] = _scalar(raw)
            continue
        if raw == "":
            current = key
            out[key] = {}
            continue
        current = None
        out[key] = _scalar(raw)
    return out


def _scalar(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def parse_sections(text: str) -> dict:
    """把单帖 md 拆成 {字段名: 内容}。区块标题见 SECTION_FIELDS。"""
    body = _FM_SPLIT.sub("", text, count=1)
    out, current, buf = {}, None, []
    for line in body.splitlines():
        if line.startswith("## "):
            if current:
                out[current] = "\n".join(buf).strip()
            current = SECTION_FIELDS.get(line[3:].strip())
            buf = []
            continue
        if current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out


# ---------------------------------------------------------------------------
# 过滤与检索
# ---------------------------------------------------------------------------

_DATE = re.compile(r"(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?")


def _date_key(text: str) -> str:
    """从各平台格式不一的 published 里抠出 YYYY-MM-DD，抠不出返回空串。"""
    m = _DATE.search(str(text or ""))
    if not m:
        return ""
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3) or 1)
    return f"{y}-{mo:02d}-{d:02d}"


def apply_filters(rows: list, topic="", platform="", content_type="",
                  has_transcript=None, since="", until="") -> list:
    out = []
    for r in rows:
        if topic and r.get("topic") != topic:
            continue
        if platform and r.get("platform") != platform:
            continue
        if content_type and r.get("contentType") != content_type:
            continue
        if has_transcript is not None and bool(r.get("hasTranscript")) != bool(has_transcript):
            continue
        if since or until:
            key = _date_key(r.get("published"))
            if not key:
                continue
            if since and key < since:
                continue
            if until and key > until:
                continue
        out.append(r)
    return out


SORTERS = {
    "addedAt": lambda r: (-(r.get("addedAt") or 0), r.get("topic") or "", r.get("number") or 0),
    "published": lambda r: (_date_key(r.get("published")) or "0000-00-00", r.get("number") or 0),
    "number": lambda r: (r.get("topic") or "", r.get("number") or 0),
}


def sort_rows(rows: list, sort: str) -> list:
    key = SORTERS.get(sort)
    if not key:
        return rows
    reverse = sort == "published"
    return sorted(rows, key=key, reverse=reverse)


def _field_texts(vault: Vault, row: dict, fields: tuple) -> list:
    """按字段取可检索文本。索引字段不落盘读取，正文字段才读 md。"""
    out = []
    for f in fields:
        if f in INDEX_FIELDS:
            val = row.get(f)
            if f == "keywords":
                val = " ".join(val or [])
            if val:
                out.append((f, str(val)))
    body_fields = [f for f in fields if f in BODY_FIELDS]
    if body_fields:
        sec = vault.sections(row.get("file") or "")
        for f in body_fields:
            if sec.get(f):
                out.append((f, sec[f]))
    return out


def _snippet(text: str, pos: int, length: int) -> str:
    start = max(0, pos - SNIPPET_PAD)
    end = min(len(text), pos + length + SNIPPET_PAD)
    frag = text[start:end].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


def search(vault: Vault, query: str, fields=ALL_FIELDS, limit=DEFAULT_LIMIT,
           offset=0, sort="addedAt", **filters) -> dict:
    """空格分词，词间 AND，大小写不敏感的子串匹配。

    中文不做分词——子串匹配对中文本来就有效，引入分词器只会带来依赖和歧义。
    代价是跨语言检索不命中（中文词查不到英文原文），已在 PRD §9 声明。
    """
    tokens = [t.lower() for t in str(query or "").split() if t.strip()]
    rows = sort_rows(apply_filters(vault.index, **filters), sort)
    if not tokens:
        return _page(vault, rows, limit, offset, matched=None)

    hits = []
    for row in rows:
        texts = _field_texts(vault, row, tuple(fields))
        lowered = [(f, t, t.lower()) for f, t in texts]
        matched, seen_fields = [], set()
        ok = True
        for tok in tokens:
            found = False
            for f, raw, low in lowered:
                pos = low.find(tok)
                if pos < 0:
                    continue
                found = True
                if f not in seen_fields and len(matched) < MAX_SNIPPETS:
                    seen_fields.add(f)
                    matched.append({"field": f, "snippet": _snippet(raw, pos, len(tok))})
                break
            if not found:
                ok = False
                break
        if ok:
            hits.append((row, matched))
    return _page(vault, [h[0] for h in hits], limit, offset,
                 matched={h[0].get("uid"): h[1] for h in hits})


def _hit(row: dict, matched) -> dict:
    out = {
        "uid": row.get("uid"),
        "topic": row.get("topic"),
        "topicName": row.get("topicName"),
        "number": row.get("number"),
        "platform": row.get("platform"),
        "contentType": row.get("contentType"),
        "title": row.get("title"),
        "author": row.get("author"),
        "published": row.get("published"),
        "summary": projection.clip(row.get("summary") or "", HIT_SUMMARY_LIMIT),
        "hasTranscript": bool(row.get("hasTranscript")),
        "sourceLink": row.get("sourceLink"),
    }
    if matched:
        out["matched"] = matched
    return out


def _page(vault: Vault, rows: list, limit: int, offset: int, matched) -> dict:
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    offset = max(0, int(offset or 0))
    window = rows[offset:offset + limit]
    hits = [_hit(r, (matched or {}).get(r.get("uid"))) for r in window]

    truncated = False
    while hits and len(json.dumps(hits, ensure_ascii=False).encode("utf-8")) > SEARCH_BYTES_CAP:
        hits.pop()
        truncated = True

    nxt = offset + len(hits)
    return {
        "hits": hits,
        "total": len(rows),
        "returned": len(hits),
        "nextCursor": str(nxt) if nxt < len(rows) else "",
        "truncated": truncated,
    }


def list_posts(vault: Vault, limit=DEFAULT_LIMIT, offset=0, sort="addedAt", **filters) -> dict:
    rows = sort_rows(apply_filters(vault.index, **filters), sort)
    return _page(vault, rows, limit, offset, matched=None)


def list_topics(vault: Vault) -> list:
    return vault.topics


# ---------------------------------------------------------------------------
# 单帖详情
# ---------------------------------------------------------------------------

DETAIL_DEFAULT = ("summary", "body", "originalText", "supplement")


def get_post(vault: Vault, uid: str, include=(), max_chars=DEFAULT_MAX_CHARS) -> dict:
    row = vault.row(uid)
    if not row:
        raise VaultError(f"没有这条帖子：{uid}")
    rel = row.get("file") or ""
    fm = parse_frontmatter(vault.md(rel))
    sec = vault.sections(rel)
    include = set(include or ())

    wanted = list(DETAIL_DEFAULT)
    for extra in ("transcript", "timeline"):
        if extra in include:
            wanted.append(extra)
    content = {f: sec[f] for f in wanted if sec.get(f)}

    budget = int(max_chars or DEFAULT_MAX_CHARS)
    truncated = []
    for field in wanted:
        if field not in content:
            continue
        if len(content[field]) > budget:
            content[field] = content[field][:max(0, budget)] + "\n（已截断）"
            truncated.append(field)
            budget = 0
        else:
            budget -= len(content[field])

    out = {
        "uid": uid,
        "topic": row.get("topic"),
        "topicName": row.get("topicName"),
        "number": row.get("number"),
        "platform": row.get("platform"),
        "contentType": row.get("contentType"),
        "title": row.get("title"),
        "author": row.get("author"),
        "handle": row.get("handle"),
        "published": row.get("published"),
        "addedAt": fm.get("addedAt") or "",
        "sourceLink": row.get("sourceLink"),
        "keywords": row.get("keywords") or [],
        "hasTranscript": bool(row.get("hasTranscript")),
        "transcriptChars": row.get("transcriptChars") or 0,
        "downloadStatus": row.get("downloadStatus"),
        "file": rel,
        "content": content,
        "truncated": truncated,
    }
    if "stats" in include or row.get("stats"):
        out["stats"] = fm.get("stats") or row.get("stats") or {}
    media = dict(fm.get("media") or {})
    if media:
        out["media"] = {
            "relative": media,
            "absolute": {k: os.path.join(vault.root, v) for k, v in media.items()},
        }
    if fm.get("warnings"):
        out["warnings"] = fm["warnings"]
    if "rawMeta" in include:
        out["rawMeta"] = _raw_meta(vault, uid)
    return out


def _raw_meta(vault: Vault, uid: str) -> dict:
    """rawMeta 不进投影，需要时回主数据取。"""
    try:
        with open(os.path.join(vault.root, "data", "posts.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    for p in data.get("posts", []):
        if p.get("uid") == uid:
            return p.get("rawMeta") or {}
    return {}


def post_markdown(vault: Vault, uid: str, full=False, timeline=False) -> str:
    """单帖原始 md。full=False 时去掉口播区块，避免长转写挤占上下文。"""
    row = vault.row(uid)
    if not row:
        raise VaultError(f"没有这条帖子：{uid}")
    text = vault.md(row.get("file") or "")
    if full and timeline:
        return text
    drop = []
    if not full:
        drop.append("口播全文")
    if not timeline:
        drop.append("口播时间轴")
    return _drop_sections(text, drop)


def _drop_sections(text: str, titles: list) -> str:
    if not titles:
        return text
    out, skipping = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            skipping = line[3:].strip() in titles
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


def pack_topic(vault: Vault, topic: str, max_chars=0, full=True) -> tuple:
    """把一个课题打包成单个 md。返回（文本, 收录条数, 省略条数）。"""
    rows = sort_rows(apply_filters(vault.index, topic=topic), "number")
    meta = next((t for t in vault.topics if t.get("id") == topic), None)
    if meta is None and not rows:
        raise VaultError(f"没有这个课题：{topic}")
    name = (meta or {}).get("name") or topic
    head = [f"# {name}", "", f"课题 id：`{topic}`　条数：{len(rows)}"]
    desc = (meta or {}).get("description")
    if desc:
        head += ["", desc]
    head += ["", "> 由 `quarry pack` 从 Quarry 内容层导出。互动数据是收藏时刻的快照。", ""]

    parts, used, omitted = ["\n".join(head)], 0, 0
    budget = int(max_chars or 0)
    for row in rows:
        body = post_markdown(vault, row["uid"], full=full, timeline=False)
        block = "\n---\n\n" + body
        if budget and sum(len(p) for p in parts) + len(block) > budget:
            omitted += 1
            continue
        parts.append(block)
        used += 1
    if omitted:
        parts.append(f"\n---\n\n> 受 --max-chars 限制，另有 {omitted} 条未收录。\n")
    return "".join(parts), used, omitted
