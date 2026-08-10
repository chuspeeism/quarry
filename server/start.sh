#!/usr/bin/env bash
# 启动 Quarry · 选题矿场 后端
#
# 用法：
#   ./start.sh                                  默认端口 6002、AI 引擎 codex、内容层 ../vault
#   PORT=6010 AI_ENGINE=ark ./start.sh          换端口 / 换 AI 引擎
#   QUARRY_VAULT=/path/to/vault ./start.sh      把内容层指到别的位置
#
# 本机固定的配置写进同目录的 .env（已 gitignore），每行 KEY=value，会自动读进来；
# 命令行上现给的环境变量优先级更高，不会被 .env 覆盖。
set -e
cd "$(dirname "$0")"
if [ -f .env ]; then
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue;; *'='*) ;; *) continue;; esac
    key=${line%%=*}
    # 已经在环境里的就不动，让命令行覆盖 .env
    [ -n "${!key:-}" ] || export "$line"
  done < .env
fi
exec python3 server.py
