#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产品层与内容层的路径解析。

server.py（HTTP 服务）、quarry_cli.py（命令行）、mcp_server.py（MCP 服务）三个
入口都要定位内容层，这里是唯一的实现。
"""

from __future__ import annotations

import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))   # <repo>/server
REPO_ROOT = os.path.dirname(HERE)                   # <repo>
APP_ROOT = os.path.join(REPO_ROOT, "app")


def main_repo_root() -> str:
    """主仓库根目录。

    git worktree 里 REPO_ROOT 指向 <repo>/.claude/worktrees/<name>/，按它取同级
    ../vault 会算到 worktrees/vault —— 既不是真的内容层，还落在仓库目录里面。用
    git 的 common-dir 反推主仓库位置：worktree 里返回主仓库的 <repo>/.git，普通
    仓库里返回相对的 .git，两种都能 join 回 <repo>。非 git 仓库（下载 zip）或
    git 不可用时退回 REPO_ROOT。
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


def resolve_vault(explicit: str = "") -> str:
    """内容层根目录。优先级：显式参数 > QUARRY_VAULT > 主仓库同级的 ../vault。

    MCP 服务由客户端拉起，工作目录与 git 环境都不确定，那条路径下必须显式传入
    或设好 QUARRY_VAULT，不能依赖 git 推断。
    """
    return os.path.abspath(
        explicit
        or os.environ.get("QUARRY_VAULT")
        or os.path.join(os.path.dirname(main_repo_root()), "vault")
    )
