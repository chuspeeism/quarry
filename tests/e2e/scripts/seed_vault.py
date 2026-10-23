#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E2E 测试专用的内容层种子脚本。

用法：python3 seed_vault.py <vault-root>

只往**测试专用的临时内容层**（tests/e2e 的 e2e.config.ts 用 QUARRY_VAULT 指进来的
/tmp 目录）写数据，绝不触碰默认内容层，也不产生任何进 git 的文件。

种子走的是 server 的本地数据契约（data/posts.json v3：topics + posts），不经过
真实采集管线（opencli / AI 加工 / 转写下载都不在测试范围内）。服务端启动时按
v3 直接加载这份文件，并自动重建 agent/ 投影。
"""

from __future__ import annotations

import json
import os
import struct
import sys

# 固定时间戳，保证排序与相对时间断言完全确定
T0 = 1781400000  # 2026-06-14 前后的固定时刻


def png_bytes() -> bytes:
    """1x1 红色 PNG。"""
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
        "53de0000000c4944415408d763f8cfc000000301010018dd8db00000000049"
        "454e44ae426082"
    )


def mp4_header_bytes() -> bytes:
    """带合法 ftyp box 头的极小 mp4 占位（仅用于「文件存在/可删除」断言）。"""
    ftyp = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    free = b"\x00\x00\x00\x08free"
    mdat_size = struct.pack(">I", 8)
    return ftyp + free + mdat_size + b"mdat"


def media_file(vault: str, rel: str, data: bytes) -> str:
    path = os.path.join(vault, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return rel


def main() -> None:
    vault = os.path.abspath(sys.argv[1])
    data_dir = os.path.join(vault, "data")
    os.makedirs(data_dir, exist_ok=True)

    cover_rel = media_file(vault, "data/media/e2e/seed-cover.png", png_bytes())
    latte_rel = media_file(vault, "data/media/e2e/seed-latte.png", png_bytes())
    delete_rel = media_file(vault, "data/media/e2e/seed-delete.png", png_bytes())
    scratch_rel = media_file(vault, "data/media/e2e/seed-scratch.png", png_bytes())
    video_rel = media_file(vault, "data/media/e2e/seed-video.mp4", mp4_header_bytes())
    srt_rel = "data/media/e2e/seed-video.srt"
    md_rel = "data/media/e2e/seed-video.口播词.md"
    media_file(vault, srt_rel, "1\n00:00:00,000 --> 00:00:04,000\n夸克星门独家转写标记：三点布光从主光开始。\n".encode("utf-8"))
    media_file(vault, md_rel, "# 口播词\n\n夸克星门独家转写标记：三点布光从主光开始。\n".encode("utf-8"))

    topics = [
        {"id": "inbox", "name": "未归类", "description": "尚未指定课题的内容默认落在这里，之后可以再拆到具体课题。",
         "createdAt": T0, "updatedAt": T0},
        {"id": "e2e-camp", "name": "E2E 采集场", "description": "e2e 测试用课题：检索与展示断言的数据集。",
         "createdAt": T0, "updatedAt": T0},
        {"id": "e2e-lib", "name": "E2E 图书馆", "description": "e2e 测试用课题：编辑与删除演练。",
         "createdAt": T0, "updatedAt": T0},
        {"id": "e2e-scratch", "name": "E2E 删除陪练", "description": "e2e 测试用课题：课题删除演练，删掉就删掉。",
         "createdAt": T0, "updatedAt": T0},
    ]

    posts = [
        {
            "uid": "e2e-camp__bilibili__BV1E2E00001",
            "topic": "e2e-camp",
            "platform": "bilibili",
            "contentType": "video",
            "tweetId": "BV1E2E00001",
            "externalId": "BV1E2E00001",
            "number": 1,
            "title": "E2E 灯光师手记：一间小房间的布光方案",
            "author": "李光明",
            "handle": "@lightguy",
            "published": "2026-01-02 12:00",
            "body": "小房间布光要从主光开始，再补眼神光。E2E 种子数据正文。",
            "summary": "小房间三点布光的入门方案。",
            "originalText": "raw: 三点布光。",
            "keywords": ["布光", "拍摄"],
            "supplement": "",
            "sourceLink": "https://www.bilibili.com/video/BV1E2E00001",
            "mediaPath": video_rel,
            "mediaName": "seed-video.mp4",
            "imagePath": cover_rel,
            "transcript": "[00:00 → 00:04] 夸克星门独家转写标记：三点布光从主光开始。",
            "transcriptSrtPath": srt_rel,
            "transcriptMdPath": md_rel,
            "audioPath": "",
            "transcriptSource": "asr",
            "downloadStatus": "success",
            "stats": {"views": 12345, "likes": 234, "comments": 12, "capturedAt": T0},
            "addedAt": T0 + 7200,
            "aiStatus": "ready",
            "warnings": [],
        },
        {
            "uid": "e2e-camp__xiaohongshu__note666",
            "topic": "e2e-camp",
            "platform": "xiaohongshu",
            "contentType": "note",
            "tweetId": "note666",
            "externalId": "note666",
            "number": 2,
            "title": "E2E 咖啡拉花入门笔记",
            "author": "阿真",
            "handle": "",
            "published": "2026-01-03 09:30",
            "body": "拉花先练奶泡。E2E 种子数据正文。",
            "summary": "入门拉花的三个练习。",
            "keywords": ["咖啡"],
            "sourceLink": "https://www.xiaohongshu.com/explore/note666",
            "imagePath": latte_rel,
            "addedAt": T0 + 3600,
            "aiStatus": "ready",
            "warnings": [],
        },
        {
            "uid": "e2e-camp__x__1780000000001",
            "topic": "e2e-camp",
            "platform": "x",
            "contentType": "post",
            "tweetId": "1780000000001",
            "externalId": "1780000000001",
            "number": 3,
            "title": "E2E 选题会的三条纪律",
            "author": "王采",
            "handle": "@wangcai",
            "published": "2026-01-04 21:00",
            "body": "一题一矿、先存链接后开采、当天复盘。E2E 种子数据正文。",
            "summary": "选题会的三条纪律。",
            "keywords": ["选题"],
            "sourceLink": "https://x.com/wangcai/status/1780000000001",
            "addedAt": T0,
            "aiStatus": "ready",
            "warnings": [],
        },
        {
            "uid": "e2e-lib__x__1780000000002",
            "topic": "e2e-lib",
            "platform": "x",
            "contentType": "post",
            "tweetId": "1780000000002",
            "externalId": "1780000000002",
            "number": 1,
            "title": "E2E 待编辑的旧笔记",
            "author": "赵编",
            "handle": "@zhaoeditor",
            "published": "2026-01-05 10:00",
            "body": "这条笔记会被编辑测试改写。",
            "summary": "旧摘要。",
            "keywords": ["编辑"],
            "sourceLink": "https://x.com/zhaoeditor/status/1780000000002",
            "addedAt": T0 + 10000,
            "aiStatus": "ready",
            "warnings": [],
        },
        {
            "uid": "e2e-lib__xiaohongshu__note777",
            "topic": "e2e-lib",
            "platform": "xiaohongshu",
            "contentType": "note",
            "tweetId": "note777",
            "externalId": "note777",
            "number": 2,
            "title": "E2E 待删除的图集笔记",
            "author": "阿真",
            "handle": "",
            "published": "2026-01-06 08:00",
            "body": "这条笔记会被删除测试删掉。",
            "summary": "待删除。",
            "keywords": [],
            "sourceLink": "https://www.xiaohongshu.com/explore/note777",
            "imagePath": delete_rel,
            "addedAt": T0 + 11000,
            "aiStatus": "ready",
            "warnings": [],
        },
        {
            "uid": "e2e-scratch__x__1780000000003",
            "topic": "e2e-scratch",
            "platform": "x",
            "contentType": "post",
            "tweetId": "1780000000003",
            "externalId": "1780000000003",
            "number": 1,
            "title": "E2E 陪练帖子：随课题一起删除",
            "author": "钱陪",
            "handle": "@qianpei",
            "published": "2026-01-07 10:00",
            "body": "课题删除演练的陪练帖子。",
            "summary": "陪练。",
            "keywords": [],
            "sourceLink": "https://x.com/qianpei/status/1780000000003",
            "imagePath": scratch_rel,
            "addedAt": T0 + 12000,
            "aiStatus": "ready",
            "warnings": [],
        },
    ]

    payload = {"version": 3, "count": len(posts), "topics": topics, "posts": posts}
    posts_file = os.path.join(data_dir, "posts.json")
    with open(posts_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.makedirs(os.path.join(data_dir, "backups"), exist_ok=True)
    print(f"[seed] 已写入 {posts_file}：{len(posts)} 帖 / {len(topics)} 课题")


if __name__ == "__main__":
    main()
