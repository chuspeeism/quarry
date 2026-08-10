#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_download_status.py —— 存量数据一次性修复：视频缺正片却写成 success 的 downloadStatus

背景：早期 importer 和 normalize_post 都是「mediaPath 或 imagePath 有一个就算 success」，
于是「视频本体下载失败、只存下封面」的帖子被记成 success，前端看不出这条内容缺失。
importer 侧已改成以视频本体为准（见 server.py 的 video_download_status），
但已经落库的帖子不会被自动改写（normalize_post 只在字段缺失时才推断），所以要跑一次这个脚本。

判定范围（只动这一类，其它状态一律不碰）：
  contentType == "video" 且 mediaPath 为空 且 downloadStatus == "success"
改写结果：
  有封面(imagePath) -> partial      连封面都没有 -> failed

用法：
  python3 server/repair_download_status.py --dry-run   # 只列出会改哪些，不写盘
  python3 server/repair_download_status.py             # 实际写回（先自动备份）

写回前会把原 posts.json 备份到 data/backups/posts.pre-download-status-repair.json。
后端进程在跑的时候会拒绝执行：它内存里存着旧数据，任何一次收藏/编辑都会把修复覆盖掉。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import server as S  # noqa: E402  复用同一套路径解析与状态判定，避免两处逻辑漂移

BACKUP_FILE = os.path.join(S.BACKUP_DIR, "posts.pre-download-status-repair.json")


def needs_repair(post: dict) -> bool:
    return (
        str(post.get("contentType") or "") == "video"
        and not str(post.get("mediaPath") or "")
        and str(post.get("downloadStatus") or "") == "success"
    )


def repaired_status(post: dict) -> str:
    # attempted=True：这条帖子当初报了 success，说明下载环节确实跑过
    return S.video_download_status("", str(post.get("imagePath") or ""), attempted=True)


def backend_is_running() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", S.PORT)) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="修复视频缺正片却记成 success 的 downloadStatus")
    ap.add_argument("--dry-run", action="store_true", help="只列出会改哪些，不写盘")
    ap.add_argument("--force", action="store_true", help="后端在运行时也强制写回（不建议）")
    args = ap.parse_args()

    print(f"内容层：{S.VAULT_ROOT}")
    print(f"数据文件：{S.POSTS_FILE}")
    if not os.path.exists(S.POSTS_FILE):
        print("数据文件不存在，无需修复。")
        return 0

    with open(S.POSTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    posts = data.get("posts") or []

    targets = [p for p in posts if needs_repair(p)]
    print(f"共 {len(posts)} 条帖子，命中 {len(targets)} 条需要修复。")
    for p in targets:
        new = repaired_status(p)
        first_warning = (S._as_list(p.get("warnings")) or [""])[0]
        print(f"  - {p.get('uid')}  success -> {new}"
              f"  封面={'有' if p.get('imagePath') else '无'}"
              f"  首条warning={str(first_warning)[:40]!r}")
    if not targets:
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

    for p in targets:
        p["downloadStatus"] = repaired_status(p)

    tmp = S.POSTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, S.POSTS_FILE)
    print(f"已修复 {len(targets)} 条并写回 {S.POSTS_FILE}")
    print("后端如果之前在跑，重启后才会加载到修复过的数据。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
