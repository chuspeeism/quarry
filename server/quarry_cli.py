#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quarry —— Quarry 内容层的命令行读取入口。

给 Claude Code / Codex 这类具备 shell 能力的 Agent 用，也给人用。直接读
<vault>/agent/ 投影，不需要 Quarry 的 HTTP 服务处于运行状态。

    quarry topics                        课题清单
    quarry list --topic fable5           按课题列出
    quarry search "提示词" --topic ae    检索
    quarry show <uid> --full             单帖全文，含口播
    quarry pack --topic fable5           打包一个课题为单文件
    quarry reindex                       重建投影
    quarry where                         打印内容层路径

全局 --json 输出结构化结果，供程序调用。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths          # noqa: E402
import projection     # noqa: E402
import vault_query as vq  # noqa: E402

PLATFORMS = ("x", "bilibili", "xiaohongshu", "douyin")


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def out(text: str = ""):
    print(text)


def dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def width(text: str) -> int:
    """按终端显示宽度算，中日韩字符占两列。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(text))


def pad(text: str, cols: int) -> str:
    text = str(text)
    w = width(text)
    if w <= cols:
        return text + " " * (cols - w)
    acc = ""
    for ch in text:
        if width(acc + ch) > cols - 1:
            break
        acc += ch
    return acc + "…" + " " * max(0, cols - width(acc) - 1)


def table(headers: list, rows: list):
    cols = [max(width(h), *(width(r[i]) for r in rows)) if rows else width(h)
            for i, h in enumerate(headers)]
    cols = [min(c, 46) for c in cols]
    out("  ".join(pad(h, c) for h, c in zip(headers, cols)).rstrip())
    out("  ".join("-" * c for c in cols))
    for r in rows:
        out("  ".join(pad(v, c) for v, c in zip(r, cols)).rstrip())


def hit_lines(result: dict, show_snippets: bool):
    if not result["hits"]:
        out("没有命中。")
        return
    rows = [[h["uid"], h["platform"], h["title"], h["author"],
             "有" if h["hasTranscript"] else "-"] for h in result["hits"]]
    table(["uid", "平台", "标题", "作者", "口播"], rows)
    if show_snippets:
        for h in result["hits"]:
            for m in h.get("matched") or []:
                out(f"  ↳ [{m['field']}] {m['snippet']}")
    out()
    tail = f"共 {result['total']} 条，返回 {result['returned']} 条。"
    if result["nextCursor"]:
        tail += f" 下一页：--cursor {result['nextCursor']}"
    if result["truncated"]:
        tail += " （受体量上限截断）"
    out(tail)


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def filters_from(args) -> dict:
    has = None
    if getattr(args, "with_transcript", False):
        has = True
    elif getattr(args, "without_transcript", False):
        has = False
    return {
        "topic": getattr(args, "topic", "") or "",
        "platform": getattr(args, "platform", "") or "",
        "content_type": getattr(args, "type", "") or "",
        "has_transcript": has,
        "since": getattr(args, "since", "") or "",
        "until": getattr(args, "until", "") or "",
    }


def cmd_topics(vault, args):
    topics = vq.list_topics(vault)
    if args.json:
        return dump(topics)
    if not topics:
        return out("还没有课题。")
    rows = [[t["id"], t["name"], str(t["postCount"]), str(t.get("withTranscript", 0)),
             ",".join(t.get("platforms") or []) or "-"] for t in topics]
    table(["id", "名称", "条数", "有口播", "平台"], rows)


def cmd_list(vault, args):
    res = vq.list_posts(vault, limit=args.limit, offset=int(args.cursor or 0),
                        sort=args.sort, **filters_from(args))
    return dump(res) if args.json else hit_lines(res, False)


def cmd_search(vault, args):
    fields = tuple(f.strip() for f in args.__dict__["in"].split(",") if f.strip()) \
        if args.__dict__.get("in") else vq.ALL_FIELDS
    unknown = [f for f in fields if f not in vq.ALL_FIELDS]
    if unknown:
        raise SystemExit(f"未知的检索字段：{', '.join(unknown)}\n可用：{', '.join(vq.ALL_FIELDS)}")
    res = vq.search(vault, " ".join(args.query), fields=fields, limit=args.limit,
                    offset=int(args.cursor or 0), sort=args.sort, **filters_from(args))
    return dump(res) if args.json else hit_lines(res, True)


def cmd_show(vault, args):
    if args.json:
        include = []
        if args.full:
            include.append("transcript")
        if args.timeline:
            include.append("timeline")
        if args.raw_meta:
            include.append("rawMeta")
        return dump(vq.get_post(vault, args.uid, include=include, max_chars=args.max_chars))
    out(vq.post_markdown(vault, args.uid, full=args.full, timeline=args.timeline))


def cmd_pack(vault, args):
    text, used, omitted = vq.pack_topic(vault, args.topic, max_chars=args.max_chars,
                                        full=not args.no_transcript)
    target = args.out or os.path.join(os.getcwd(), f"quarry-{args.topic}.md")
    with open(target, "w", encoding="utf-8") as f:
        f.write(text)
    if args.json:
        return dump({"file": target, "posts": used, "omitted": omitted, "chars": len(text)})
    out(f"已写入 {target}")
    out(f"收录 {used} 条{f'，省略 {omitted} 条' if omitted else ''}，共 {len(text)} 字符。")


def cmd_reindex(vault, args):
    posts_file = os.path.join(vault.root, "data", "posts.json")
    try:
        with open(posts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise SystemExit(f"读不到主数据 {posts_file}：{e}")
    except ValueError as e:
        raise SystemExit(f"主数据不是合法 JSON：{e}")
    st = projection.sync(vault.root, data.get("posts") or [], data.get("topics") or [], force=True)
    if args.json:
        return dump(st)
    out(f"投影重建完成：{st['total']} 条")
    out(f"  写入 {st['written']} / 跳过 {st['skipped']} / 删除 {st['deleted']} / 失败 {st['errors']}")
    out(f"  位置 {vault.agent_root}")


def cmd_where(vault, args):
    if args.json:
        return dump({"vault": vault.root, "agent": vault.agent_root,
                     "posts": os.path.join(vault.root, "data", "posts.json"),
                     "exists": os.path.isdir(vault.agent_root)})
    out(vault.root)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def add_filters(p, with_sort=True):
    p.add_argument("--topic", default="", help="限定课题 id")
    p.add_argument("--platform", default="", choices=("",) + PLATFORMS, help="限定平台")
    p.add_argument("--type", default="", help="限定内容类型，如 post / video")
    p.add_argument("--since", default="", metavar="YYYY-MM-DD", help="发布时间下界")
    p.add_argument("--until", default="", metavar="YYYY-MM-DD", help="发布时间上界")
    p.add_argument("--with-transcript", action="store_true", help="只要有口播转写的")
    p.add_argument("--without-transcript", action="store_true", help="只要没有口播转写的")
    p.add_argument("--limit", type=int, default=vq.DEFAULT_LIMIT,
                   help=f"返回条数，上限 {vq.MAX_LIMIT}")
    p.add_argument("--cursor", default="", help="翻页游标，取上一页返回的 nextCursor")
    if with_sort:
        p.add_argument("--sort", default="addedAt", choices=tuple(vq.SORTERS),
                       help="排序：addedAt 收藏倒序 / published 发布倒序 / number 课题内序号")


def global_flags(argv: list) -> tuple:
    """从原始 argv 里取 --json / --vault。

    这两个开关在子命令前后都要能写——Agent 更习惯放末尾。argparse 的子解析器会
    用自己的默认值覆盖父级已解析的结果，靠 parents 继承拿不到稳定语义，所以直接
    扫一遍 argv。
    """
    as_json = "--json" in argv
    vault = ""
    for i, a in enumerate(argv):
        if a.startswith("--vault="):
            vault = a.split("=", 1)[1]
        elif a == "--vault" and i + 1 < len(argv):
            vault = argv[i + 1]
    return as_json, vault


def build_parser():
    # 两个全局开关在父级和每个子命令上都注册一份，保证任何位置都能通过解析、
    # 且 --help 里都看得到。真正生效的值由 global_flags() 从 argv 决定。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vault", default="", help="内容层根目录")
    common.add_argument("--json", action="store_true", help="输出 JSON")

    ap = argparse.ArgumentParser(
        prog="quarry", description="Quarry 内容层读取入口", parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="内容层位置：QUARRY_VAULT 环境变量，或 --vault，缺省取主仓库同级的 ../vault")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("topics", help="课题清单", parents=[common]).set_defaults(fn=cmd_topics)

    p = sub.add_parser("list", help="按课题列出帖子", parents=[common])
    add_filters(p)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("search", help="全字段检索", parents=[common])
    p.add_argument("query", nargs="+", help="检索词，多个词之间是 AND")
    p.add_argument("--in", default="", metavar="字段,字段",
                   help=f"限定检索字段，可选：{', '.join(vq.ALL_FIELDS)}")
    add_filters(p)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("show", help="单帖内容", parents=[common])
    p.add_argument("uid")
    p.add_argument("--full", action="store_true", help="附口播全文")
    p.add_argument("--timeline", action="store_true", help="附口播时间轴")
    p.add_argument("--raw-meta", action="store_true", help="附平台原始响应（仅 --json）")
    p.add_argument("--max-chars", type=int, default=vq.DEFAULT_MAX_CHARS,
                   help="正文字符上限（仅 --json）")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("pack", help="把一个课题打包成单个 md", parents=[common])
    p.add_argument("--topic", required=True)
    p.add_argument("--out", default="", help="输出文件路径，缺省写到当前目录")
    p.add_argument("--max-chars", type=int, default=0, help="总字符上限，0 为不限")
    p.add_argument("--no-transcript", action="store_true", help="不含口播全文")
    p.set_defaults(fn=cmd_pack)

    sub.add_parser("reindex", help="全量重建投影", parents=[common]).set_defaults(fn=cmd_reindex)
    sub.add_parser("where", help="打印内容层路径", parents=[common]).set_defaults(fn=cmd_where)
    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    args.json, vault_arg = global_flags(argv)
    vault = vq.Vault(paths.resolve_vault(vault_arg))
    try:
        args.fn(vault, args)
    except vq.VaultError as e:
        print(str(e), file=sys.stderr)
        return 2
    except BrokenPipeError:
        # 管到 head / less 时的正常退出路径。
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
