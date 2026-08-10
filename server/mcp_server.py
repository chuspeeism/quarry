#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quarry MCP 服务：把内容层以四个只读工具的形式暴露给 MCP 客户端。

传输只做 stdio。目标客户端（Claude 桌面端、Claude Code、Codex）都在本机，不需要
HTTP 传输，因此不引入端口监听、token 鉴权与隧道。

协议是 JSON-RPC 2.0，一行一条消息。这里手写而不引第三方包，是为了守住项目
「python3 仅标准库」的依赖约束。stdout 只能出协议消息，日志一律走 stderr。

    python3 mcp_server.py [--vault <内容层路径>]

内容层定位优先级：--vault > QUARRY_VAULT > 主仓库同级的 ../vault。MCP 服务由
客户端拉起，工作目录与 git 环境都不确定，配置里应当显式给出前两者之一。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths          # noqa: E402
import vault_query as vq  # noqa: E402

SERVER_NAME = "quarry"
SERVER_VERSION = "1.0.0"
# 客户端没声明版本时用的兜底。声明了就回显它的——本服务只用 tools 能力，
# 在各版本间语义一致，回显比强推一个版本更不容易谈崩。
DEFAULT_PROTOCOL = "2025-06-18"

# 封面图内联返回的体积上限。超过就只给路径，避免把上下文塞爆。
COVER_INLINE_LIMIT = 1024 * 1024
IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
              ".gif": "image/gif", ".webp": "image/webp"}

VAULT: vq.Vault = None  # 由 main() 注入


def log(msg: str):
    print(f"[quarry-mcp] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------

_FILTERS = {
    "topic": {"type": "string", "description": "限定课题 id，取自 quarry_list_topics"},
    "platform": {"type": "string", "enum": ["x", "bilibili", "xiaohongshu", "douyin"],
                 "description": "限定平台"},
    "contentType": {"type": "string", "description": "限定内容类型，如 post / video"},
    "hasTranscript": {"type": "boolean", "description": "是否只要有口播转写的内容"},
    "since": {"type": "string", "description": "发布时间下界，YYYY-MM-DD"},
    "until": {"type": "string", "description": "发布时间上界，YYYY-MM-DD"},
    "limit": {"type": "integer", "minimum": 1, "maximum": vq.MAX_LIMIT,
              "description": f"返回条数，默认 {vq.DEFAULT_LIMIT}，上限 {vq.MAX_LIMIT}"},
    "cursor": {"type": "string", "description": "翻页游标，取上一次返回的 nextCursor"},
}

TOOLS = [
    {
        "name": "quarry_list_topics",
        "description": "列出 Quarry 里的全部课题：id、名称、条数、平台分布、有口播的条数。"
                       "检索前先调用这个拿 topic id。返回体量与库规模无关。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "quarry_search",
        "description": "在收藏的帖子里按关键词检索，覆盖标题、正文、摘要、平台原文、关键词、"
                       "作者与口播转写全文。多个词之间是 AND，中文直接用词即可。"
                       "返回轻量命中列表（标题、作者、摘要、命中片段），不含全文——"
                       "要正文用 quarry_get_post 按 uid 取。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索词，空格分隔，词间 AND"},
                "fields": {"type": "array", "items": {"type": "string", "enum": list(vq.ALL_FIELDS)},
                           "description": "限定检索字段，缺省全字段"},
                "sort": {"type": "string", "enum": list(vq.SORTERS),
                         "description": "排序：addedAt 收藏倒序（默认）/ published 发布倒序 / number 课题内序号"},
                **_FILTERS,
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "quarry_list_posts",
        "description": "按课题浏览帖子，不做关键词匹配。用于「这个课题里都收了什么」这类问题。"
                       "返回结构与 quarry_search 一致，不含命中片段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sort": {"type": "string", "enum": list(vq.SORTERS),
                         "description": "排序，默认 addedAt"},
                **_FILTERS,
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
    {
        "name": "quarry_get_post",
        "description": "取单条帖子的完整内容：摘要、AI 整理的中文正文、平台原文、互动数据快照、"
                       "媒体文件路径。include 里加 transcript 才返回口播全文（可能很长），"
                       "加 timeline 返回带时间戳的分句。封面图小于 1MB 时一并内联返回。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string", "description": "帖子 uid，取自检索结果"},
                "include": {
                    "type": "array",
                    "items": {"type": "string",
                              "enum": ["transcript", "timeline", "rawMeta", "cover"]},
                    "description": "额外返回的内容。transcript 口播全文、timeline 口播时间轴、"
                                   "rawMeta 平台原始响应、cover 内联封面图",
                },
                "maxChars": {"type": "integer", "minimum": 500,
                             "description": f"正文字符上限，默认 {vq.DEFAULT_MAX_CHARS}"},
            },
            "required": ["uid"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def _filters(args: dict) -> dict:
    return {
        "topic": args.get("topic") or "",
        "platform": args.get("platform") or "",
        "content_type": args.get("contentType") or "",
        "has_transcript": args.get("hasTranscript"),
        "since": args.get("since") or "",
        "until": args.get("until") or "",
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _json_block(obj) -> dict:
    return _text_block(json.dumps(obj, ensure_ascii=False, indent=2))


def tool_list_topics(args: dict) -> list:
    topics = vq.list_topics(VAULT)
    if not topics:
        return [_text_block("库里还没有课题。")]
    return [_json_block(topics)]


def tool_search(args: dict) -> list:
    fields = tuple(args.get("fields") or vq.ALL_FIELDS)
    res = vq.search(VAULT, args.get("query") or "", fields=fields,
                    limit=args.get("limit") or vq.DEFAULT_LIMIT,
                    offset=int(args.get("cursor") or 0),
                    sort=args.get("sort") or "addedAt", **_filters(args))
    if not res["hits"]:
        return [_text_block("没有命中。可以放宽关键词，或用 quarry_list_topics 看看有哪些课题。")]
    return [_json_block(res)]


def tool_list_posts(args: dict) -> list:
    res = vq.list_posts(VAULT, limit=args.get("limit") or vq.DEFAULT_LIMIT,
                        offset=int(args.get("cursor") or 0),
                        sort=args.get("sort") or "addedAt", **_filters(args))
    if not res["hits"]:
        return [_text_block("这个课题下没有符合条件的帖子。")]
    return [_json_block(res)]


def tool_get_post(args: dict) -> list:
    uid = args.get("uid") or ""
    include = set(args.get("include") or ())
    detail = vq.get_post(VAULT, uid, include=include,
                         max_chars=args.get("maxChars") or vq.DEFAULT_MAX_CHARS)
    md = vq.post_markdown(VAULT, uid, full="transcript" in include,
                          timeline="timeline" in include)

    blocks = [_text_block(md)]

    absolute = (detail.get("media") or {}).get("absolute") or {}
    if absolute:
        lines = ["## 本机路径", ""] + [f"- {k}：{v}" for k, v in absolute.items()]
        lines += ["", "（Claude 桌面端读不了这些文件本身，需要处理媒体时用 Claude Code 或 Codex。）"]
        blocks.append(_text_block("\n".join(lines)))

    if "rawMeta" in include and detail.get("rawMeta"):
        blocks.append(_text_block("## 平台原始响应\n\n```json\n"
                                  + json.dumps(detail["rawMeta"], ensure_ascii=False, indent=2)
                                  + "\n```"))

    if "cover" in include:
        block = _cover_block(absolute.get("cover") or absolute.get("main") or "")
        if block:
            blocks.append(block)
    return blocks


def _cover_block(path: str):
    """封面图内联返回。体积超限或不是图片就跳过，只保留路径。"""
    ext = os.path.splitext(path)[1].lower()
    mime = IMAGE_MIME.get(ext)
    if not mime or not path:
        return None
    try:
        if os.path.getsize(path) > COVER_INLINE_LIMIT:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}


HANDLERS = {
    "quarry_list_topics": tool_list_topics,
    "quarry_search": tool_search,
    "quarry_list_posts": tool_list_posts,
    "quarry_get_post": tool_get_post,
}


# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

def _result(rid, payload) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": payload}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(msg: dict):
    """返回要回给客户端的消息，通知类返回 None。"""
    method = msg.get("method") or ""
    rid = msg.get("id")
    params = msg.get("params") or {}

    if rid is None:
        # 通知：initialized / cancelled 之类，收下不回。
        return None

    if method == "initialize":
        asked = str(params.get("protocolVersion") or "")
        version = asked if asked.count("-") == 2 else DEFAULT_PROTOCOL
        return _result(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Quarry 是本机的多平台内容收藏库。回答「我收藏过什么」这类问题时，"
                            "先用 quarry_list_topics 看课题，再用 quarry_search 检索，"
                            "最后按 uid 用 quarry_get_post 取正文。互动数据是收藏时刻的快照。",
        })

    if method == "ping":
        return _result(rid, {})

    if method == "tools/list":
        return _result(rid, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if not fn:
            return _error(rid, -32602, f"没有这个工具：{name}")
        try:
            return _result(rid, {"content": fn(args), "isError": False})
        except vq.VaultError as e:
            return _result(rid, {"content": [_text_block(str(e))], "isError": True})
        except Exception as e:  # noqa: BLE001
            log("工具执行失败：\n" + traceback.format_exc())
            return _result(rid, {"content": [_text_block(f"{name} 执行失败：{e}")],
                                 "isError": True})

    return _error(rid, -32601, f"不支持的方法：{method}")


def serve(stdin, stdout):
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            stdout.write(json.dumps(_error(None, -32700, "不是合法 JSON")) + "\n")
            stdout.flush()
            continue
        try:
            reply = handle(msg)
        except Exception as e:  # noqa: BLE001
            log("处理消息失败：\n" + traceback.format_exc())
            reply = _error(msg.get("id"), -32603, str(e))
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def main(argv=None):
    global VAULT
    ap = argparse.ArgumentParser(prog="quarry-mcp", description="Quarry MCP 服务（stdio）")
    ap.add_argument("--vault", default="", help="内容层根目录，缺省读 QUARRY_VAULT")
    args = ap.parse_args(argv)

    root = paths.resolve_vault(args.vault)
    VAULT = vq.Vault(root)
    log(f"内容层：{root}")
    if not os.path.exists(os.path.join(VAULT.agent_root, "index.jsonl")):
        # 不在这里退出：initialize 要能成功，客户端才显示为已连接；具体的错误
        # 由工具调用时返回，比连不上更容易排查。
        log("警告：投影不存在，先在仓库里执行 `bin/quarry reindex`")
    serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
