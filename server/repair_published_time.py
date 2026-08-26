#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_published_time.py —— 存量数据一次性修复：按本机时区渲染的 published 改成北京时间

背景：B 站和抖音的发布时间原本用 time.localtime 渲染，跟的是跑服务那台机器的时区，
而两个平台页面上显示的都是北京时间。机器不在 +8 时卡片就跟原帖对不上（本机在美西，
差 15~16 小时）。采集侧已改成一律按 +8 渲染（见 server.py 的 published_beijing），
但已经落库的帖子不会被自动改写，所以要跑一次这个脚本。

各平台怎么修（判定依据是"这个值当初是怎么渲染出来的"）：

  bilibili  优先拿 B 站公开接口的 pubdate 当真值重算——最准，还能补上原来缺的秒。
            接口取不到时退回本地推算：
              rawMeta.publish_time == published  ->  opencli 兜底给的 UTC 串，+8 小时
              否则                                ->  当初是 localtime 渲染的，按本机时区反解再转北京
  douyin    库里没留 create_time，只能把串按本机时区反解回时间戳再转北京。
            额外拿 aweme_id 高 32 位（ID 生成时刻）做旁证打印出来——它比发布时刻略早
            属正常，不作为真值。
  x         不动。format_published 存的是 "... UTC；北京时间 ..."，时区本来就是显式的。
  xiaohongshu 从笔记 id 反推，本来就按北京时间渲染（见 xhs_published_from_note_id），
            只在跟重算结果不一致时才改。

published 为空的一律跳过：那是当初就没抓到时间，属于"缺数据"，不是"时区错"，
补它需要重新抓一次原帖，不在本脚本职责内。

用法：
  python3 server/repair_published_time.py --dry-run   # 只列出会改哪些，不写盘
  python3 server/repair_published_time.py             # 实际写回（先自动备份）

写回前会把原 posts.json 备份到 data/backups/posts.pre-published-time-repair.json。
后端进程在跑的时候会拒绝执行：它内存里存着旧数据，任何一次收藏/编辑都会把修复覆盖掉。
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import shutil
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import projection  # noqa: E402
import server as S  # noqa: E402  复用同一套时间渲染，避免两处逻辑漂移

BACKUP_FILE = os.path.join(S.BACKUP_DIR, "posts.pre-published-time-repair.json")
FMTS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def local_text_to_ts(text: str):
    """把当初 time.localtime 渲染出来的串按本机时区反解回 Unix 时间戳。

    mktime 会按那一天的实际 DST 规则算，所以夏令时/冬令时不用自己判断。
    前提是这台机器的时区跟当初采集时一致（本机一直是 America/Los_Angeles）。
    """
    for fmt in FMTS:
        try:
            return int(time.mktime(time.strptime(text, fmt)))
        except ValueError:
            continue
    return None


def fixed_bilibili(post: dict, note: list) -> str:
    bvid = str(post.get("externalId") or "")
    stored = str(post.get("published") or "")
    meta = S.fetch_bilibili_view(bvid) if bvid else {}
    truth = str((meta or {}).get("published") or "")
    if truth:
        note.append("公开接口 pubdate")
        return truth
    raw = post.get("rawMeta") or {}
    if str(raw.get("publish_time") or "") == stored:
        note.append("opencli 兜底 UTC 串 +8")
        return S.utc_text_to_beijing(stored)
    ts = local_text_to_ts(stored)
    note.append("按本机时区反解")
    return S.published_beijing(ts) if ts else stored


def fixed_douyin(post: dict, note: list) -> str:
    stored = str(post.get("published") or "")
    ts = local_text_to_ts(stored)
    if not ts:
        note.append("串认不出，跳过")
        return stored
    try:
        id_ts = int(str(post.get("externalId") or "0")) >> 32
        if 1_000_000_000 <= id_ts <= 4_000_000_000:
            gap = (ts - id_ts) / 60.0
            note.append(f"按本机时区反解；旁证 aweme_id 时刻早 {gap:.0f} 分钟")
        else:
            note.append("按本机时区反解")
    except ValueError:
        note.append("按本机时区反解")
    return S.published_beijing(ts)


def fixed_xiaohongshu(post: dict, note: list) -> str:
    note.append("按笔记 id 重算")
    return S.xhs_published_from_note_id(str(post.get("externalId") or "")) or str(post.get("published") or "")


FIXERS = {"bilibili": fixed_bilibili, "douyin": fixed_douyin, "xiaohongshu": fixed_xiaohongshu}


def backend_is_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", S.PORT)) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把按本机时区渲染的 published 修成北京时间")
    ap.add_argument("--dry-run", action="store_true", help="只列出会改哪些，不写盘")
    ap.add_argument("--force", action="store_true", help="后端在运行时也强制写回（不建议）")
    args = ap.parse_args()

    print(f"内容层：{S.VAULT_ROOT}")
    print(f"数据文件：{S.POSTS_FILE}")
    print(f"本机时区：{time.tzname}")
    if not os.path.exists(S.POSTS_FILE):
        print("数据文件不存在，无需修复。")
        return 0

    with open(S.POSTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    posts = data.get("posts") or []

    changes, skipped_empty, checked = [], 0, 0
    for p in posts:
        plat = str(p.get("platform") or "")
        fixer = FIXERS.get(plat)
        if not fixer:
            continue
        stored = str(p.get("published") or "")
        if not stored:
            skipped_empty += 1
            continue
        checked += 1
        note = []
        new = fixer(p, note)
        if new and new != stored:
            changes.append((p, stored, new, "；".join(note)))
        if plat == "bilibili":
            time.sleep(1.2)  # B 站公开接口连打会限流，返回空会让本脚本误判成"取不到"

    print(f"\n共 {len(posts)} 条帖子；跳过 x（时区本来就显式）；"
          f"检查 {checked} 条；published 为空跳过 {skipped_empty} 条。")
    print(f"需要修复 {len(changes)} 条：\n")
    for p, old, new, why in changes:
        print(f"  [{p.get('platform')}] {p.get('externalId')}  {str(p.get('title') or '')[:28]}")
        print(f"      {old}  ->  {new}")
        print(f"      依据：{why}")
    if not changes:
        print("  （没有需要修复的）")
        return 0
    if args.dry_run:
        print("\n--dry-run：未写盘。")
        return 0
    if backend_is_running() and not args.force:
        print(f"\n后端仍在 127.0.0.1:{S.PORT} 运行，它内存里是旧数据，写回会被下一次保存覆盖。"
              f"\n请先停掉后端再跑本脚本（确实要强行写回就加 --force）。")
        return 2

    os.makedirs(S.BACKUP_DIR, exist_ok=True)
    shutil.copy2(S.POSTS_FILE, BACKUP_FILE)
    print(f"\n已备份原数据 -> {BACKUP_FILE}")

    for p, _old, new, _why in changes:
        p["published"] = new

    tmp = S.POSTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, S.POSTS_FILE)
    print(f"已修复 {len(changes)} 条并写回 {S.POSTS_FILE}")

    topics = data.get("topics") or []
    try:
        projection.sync(S.VAULT_ROOT, posts, topics, force=True)
        print("已重建 agent 投影（vault/agent/），投影里的时间跟着一起更新。")
    except Exception as e:  # noqa: BLE001
        print(f"警告：投影重建失败，请起一次后端让它自己重建：{e}")
    print("后端如果之前在跑，重启后才会加载到修复过的数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
