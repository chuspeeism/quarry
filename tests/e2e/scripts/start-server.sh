#!/usr/bin/env bash
# e2e 专用后端启动脚本（由 tests/e2e/e2e.config.ts 的 app.command 拉起）。
#
# 每次运行前重建一次性内容层：QUARRY_VAULT 必须指向 /tmp 下的测试目录，
# 脚本会清空它、灌入确定性种子，再启动真正的后端。
# 产品层与真实内容层（默认 ../vault）全程不被触碰。
set -eu
cd "$(dirname "$0")/../../.."   # -> 仓库根目录

: "${QUARRY_VAULT:?QUARRY_VAULT 必须由 e2e.config.ts 传入测试专用的 /tmp 目录}"
: "${PORT:?PORT 必须由 e2e.config.ts 传入}"

rm -rf "$QUARRY_VAULT"
python3 tests/e2e/scripts/seed_vault.py "$QUARRY_VAULT"

# AI_ENGINE=none：绝不调用 codex/Ark（不在测试范围）。
# 不设 QUARRY_OPENCLI_PROFILE：不做 opencli profile 探测；测试也从不触发采集。
export QUARRY_VAULT PORT AI_ENGINE="${AI_ENGINE:-none}"
exec python3 server/server.py
