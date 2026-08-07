#!/usr/bin/env bash
# 启动 Quarry · 选题矿场 后端
#
# 用法：
#   ./start.sh                                  默认端口 6002、AI 引擎 codex、内容层 ../vault
#   PORT=6010 AI_ENGINE=ark ./start.sh          换端口 / 换 AI 引擎
#   QUARRY_VAULT=/path/to/vault ./start.sh      把内容层指到别的位置
set -e
cd "$(dirname "$0")"
exec python3 server.py
