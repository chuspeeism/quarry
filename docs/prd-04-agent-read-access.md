# PRD：Agent 读取能力（Quarry as Context Source）

> 状态：已实施（2026-08-09）
> 目标：让 AI Agent 能检索并读取 Quarry 收集的帖子，不需要人工复制粘贴，不需要整库载入上下文。

---

## 1. 背景与现状

Quarry 已经能把 X / B 站 / 小红书 / 抖音的内容采集到本地内容层，字段完整：中文标题、AI 整理正文、摘要、关键词、平台原文、口播转写、互动数据快照、媒体路径。

但这些内容目前只有一个消费者——`app/` 里的前端页面。Agent 要读，有四个障碍：

| 障碍 | 具体表现 | 代码位置 |
|------|----------|----------|
| 定位 | 内容层在仓库之外，路径由 `git rev-parse --git-common-dir` 反推，Agent 无法预知 | `server/server.py:71-101` |
| 取数粒度 | 唯一的读接口 `GET /api/posts?topic=` 一次返回该课题全部帖子的全部字段，无检索、无字段裁剪、无单条详情 | `server/server.py:1578` |
| 转写完整性 | `posts.json` 的 `transcript` 字段被截断到 16KB，全文在另一个 `口播词.md` 文件里，两者的关联关系未对外声明 | `server/server.py:132`、`server/server.py:252` |
| 运行依赖 | 读取依赖 6002 端口的服务处于运行状态 | `server/server.py:1564` |

体量数据：`posts.json` 当前 43 条 / 约 137KB，平均每条约 3.2KB。按此估算，约 120 条即会占满 200K 上下文窗口的主要部分。整库载入不是可持续的读取方式。

---

## 2. 目标与非目标

### 2.1 适用场景

限定四个本机客户端，全部运行在同一台机器上，与内容层同盘可达：

| 场景 | 客户端形态 | 磁盘可达 | 可执行 shell |
|------|-----------|----------|--------------|
| Claude 桌面端 | 聊天应用 | 否 | 否 |
| Claude Code 桌面端 | 编码 Agent | 是 | 是 |
| Codex 桌面端 | 编码 Agent | 是 | 是 |
| Codex 终端 | 编码 Agent | 是 | 是 |

四者的能力差异决定了接入方式不统一：后三者具备文件与命令执行能力，Claude 桌面端只能通过 MCP 取数。

### 2.2 目标

1. Agent 能按课题、平台、时间、关键词检索帖子，检索结果的体积与库的总量无关。
2. Agent 能取到单条帖子的完整内容，包含不被截断的口播转写全文。
3. Agent 能拿到媒体文件路径，用于进一步处理（剪辑、转写复核、截帧）。
4. 读取路径不依赖 Quarry 服务进程处于运行状态。
5. 内容层整体迁移（换盘、换机、同步盘）后，Agent 读取能力随内容层一起迁移。

### 2.3 非目标

1. 本次不开放写入。Agent 不能通过本能力新增、修改、删除帖子或课题。
2. 不做远程访问。不实现 HTTP 传输、不做公网暴露、不做隧道与鉴权。claude.ai 网页版、手机端、Cowork 的连接由 Anthropic 云端发起，够不到本机，本次不在支持范围内。
3. 不做向量检索。当前规模下关键词检索加字段过滤已经足够，向量索引带来的依赖成本与收益不匹配。
4. 不改变 `posts.json` 的既有结构和 `/api/*` 的既有契约。

---

## 3. 方案总览

一个查询内核，两个前端，一份数据投影。

```text
接入        quarry CLI (bin/quarry)        MCP Server (stdio)
            Claude Code 桌面端             Claude 桌面端
            Codex 桌面端 / 终端
                        ↘               ↙
查询内核            server/vault_query.py
            检索 / 过滤 / 分页 / 取详情 / 体量控制
                            ↓ 读取
数据投影            vault/agent/
            index.jsonl + topics/<课题>/<序号>-<标题>.md
                            ↑ 派生自
真相源              vault/data/posts.json（结构不变）
```

分层的原因：

- 数据投影单独可用。具备文件读取能力的客户端可以不经过任何程序，直接 grep 与 read。
- 查询内核只实现一次。CLI 与 MCP 是同一套检索逻辑的两个适配层，返回结构一致，不会出现两处行为分叉。
- CLI 与 MCP 并存，不是冗余。二者的上下文成本不同，见 §6.1。

---

## 4. 数据投影层：vault/agent/

### 4.1 目录结构

新增 `vault/agent/`，与 `vault/data/` 同级，属于内容层，不进 git：

```text
vault/agent/
├── README.md                 入口说明：库的构成、字段含义、检索建议
├── topics.json               课题清单：条数、平台分布、最近更新
├── index.jsonl               一行一帖的轻量索引
├── .manifest.json            渲染清单，用于跳过未变文件
└── topics/
    ├── fable5/
    │   ├── _topic.md         课题说明 + 该课题帖子目录
    │   ├── 001-pokemon-firered-视觉通关.md
    │   └── 002-....md
    └── minimax-h3/
        └── ...
```

### 4.2 单帖文件格式

文件名：`<number>-<title-slug>.md`，`number` 为课题内序号（既有字段，`docs/prd-01-topic-collector.md` §7.3），补零到 3 位。序号保证排序稳定，标题片段保证人工可辨认。

```markdown
---
uid: v1-acceptance__douyin__7587225361230974260
topic: v1-acceptance
topicName: 验收测试
number: 1
platform: douyin
contentType: video
author: 大师的AI小灶
handle: 大师的AI小灶
published: 2025-12-23 18:00:24
addedAt: 2026-08-06T12:23:45+08:00
sourceLink: https://www.douyin.com/video/7587225361230974260
keywords: [图生视频, 提示词, AI创作]
stats:
  views: 1234567
  likes: 45678
  collects: 12345
  comments: 890
  shares: 456
  capturedAt: 2026-08-06T12:23:45+08:00
media:
  main: data/media/douyin/7587225361230974260/7587225361230974260.mp4
  audio: data/media/douyin/7587225361230974260/7587225361230974260.m4a
  srt: data/media/douyin/7587225361230974260/7587225361230974260.srt
  transcriptMd: data/media/douyin/7587225361230974260/7587225361230974260.口播词.md
transcriptSource: asr
hasTranscript: true
transcriptChars: 1180
warnings: []
---

# 图生视频提示词并非越长越好

## 摘要
图生视频的提示词并非越长越有效，冗余信息可能影响 AI 理解核心要求。

## 正文
《大师的AI复盘》系列第一集提出了一个反常识观点……

## 平台原文
抖音知识年终大赏 | 提示词越长，AI越笨？……

## 口播全文
这样的提示词就一定更专业了。其实提示词做到 70%，得到的效果是一样的……

## 口播时间轴
[00:00 → 00:02] 这样的提示词就一定更专业了
[00:02 → 00:05] 其实提示词做到70%
...
```

字段来源约定：

| md 区块 | posts.json 字段 | 说明 |
|---------|-----------------|------|
| frontmatter | 同名字段直取 | `stats` 为空对象时输出空，不补零值 |
| 摘要 | `summary` | |
| 正文 | `body` | AI 整理的中文正文 |
| 平台原文 | `originalText` | `originalIsExcerpt` 为真时在区块首行标注「节选」，附 `originalNote` |
| 口播全文 | 读 `transcriptMdPath` 指向的文件 | **不截断**，绕开 `TRANSCRIPT_LIMIT` |
| 口播时间轴 | 同上文件的时间轴段落 | 无 ASR 产物时整块省略 |
| 补充 | `supplement` | 非空时才输出该区块 |

`rawMeta` 不进 md，只保留在 `posts.json`。它是平台原始响应的调试残留，对内容理解无贡献，且体积不可控。

### 4.3 索引格式

`index.jsonl`，一行一条 JSON，无外层数组：

```json
{"uid":"fable5__2064397343101993267","topic":"fable5","topicName":"Fable 5","number":1,"platform":"x","contentType":"post","title":"帖子 1：Pokémon FireRed 视觉通关","author":"Chetaslua","handle":"@chetaslua","published":"2026-06-09 17:20:55 UTC","addedAt":1781426253,"summary":"作者表示 Claude Fable 5 仅依靠视觉输入完成了 Pokémon FireRed……","keywords":["with vision alone","raw screenshots only"],"stats":{},"hasTranscript":false,"chars":486,"file":"topics/fable5/001-pokemon-firered-视觉通关.md","sourceLink":"https://x.com/chetaslua/status/2064397343101993267"}
```

选用 jsonl 而非 json 的原因：可追加写、可按行 grep、单行自包含、规模增长后不需要整文件解析。

实测单行约 946 字节（中文摘要与标题占大头，摘要在索引里截到 200 字），43 条共 40KB；按此推算 1000 条约 920KB，仍可被 CLI 整读并在内存中过滤。超过该规模再引入 SQLite FTS，届时 jsonl 保留为导出格式。

### 4.4 同步机制

投影是派生数据，`posts.json` 保持唯一真相源。三条保证一致性：

1. **单一写入点**：`save_posts()`（`server/server.py:502`）是全部 16 处数据变更的唯一出口。在其中调用 `projection.sync(changed_uids)`，按变更集增量重写对应 md 与索引行，删除的帖子同步删除文件。
2. **幂等全量重建**：`quarry reindex` 全量重扫 `posts.json` 重写整个 `vault/agent/`。用于存量数据补齐、格式升级、损坏修复。重建结果与增量同步结果必须逐字节一致，这是投影逻辑的自检条件。
3. **启动校验**：服务启动时比对 `index.jsonl` 行数与 `POSTS` 长度，不一致则自动触发一次全量重建并在启动日志中记录。

失败处理：投影写入失败不阻断主流程。`save_posts()` 已经完成的写入不回滚，投影错误记入 `vault/agent/.sync-errors.log`，下次 `reindex` 修复。理由是采集链路的可用性优先于派生数据的实时性。

---

## 5. 查询层：内核与 CLI

检索、过滤、分页、体量控制统一实现在 `server/vault_query.py`，`server/quarry_cli.py` 与 `server/mcp_server.py` 都是它的适配层。CLI 通过 `bin/quarry` 暴露，直接读取 `vault/agent/`，不经过 Quarry 的 HTTP 服务。

| 命令 | 用途 | 输出 |
|------|------|------|
| `quarry topics` | 课题列表、条数、平台分布、最近更新时间 | 表格 / `--json` |
| `quarry list --topic <id>` | 按课题列出帖子，支持 `--platform` `--type` `--since` `--until` `--limit` `--sort` | 一行一条 |
| `quarry search <query>` | 全字段检索，支持与 `list` 相同的过滤参数，`--in` 限定检索字段 | 命中列表 + 片段 |
| `quarry show <uid>` | 单条完整内容，`--full` 附口播全文，`--timeline` 附时间轴 | md |
| `quarry pack --topic <id>` | 将一个课题打包为单个 md 文件 | 文件路径 |
| `quarry reindex` | 全量重建投影 | 统计结果 |
| `quarry where` | 打印内容层绝对路径 | 路径 |

全局参数 `--json` 输出结构化结果，供程序调用；缺省输出为人工阅读格式。

`quarry pack` 承担一个具体职责：把一个课题整体作为上下文输入交给模型，用于「通读全部素材后给结论」这类不适合逐条检索的任务，也用于向 Claude 桌面端手工上传。打包时按 `--max-chars` 控制体积，超出时按 `addedAt` 倒序截断，并在文件尾部标注被省略的条数。

---

## 6. 接入层

### 6.1 接入方式分配

按客户端能力与上下文成本分配，不强求四个场景用同一种方式：

| 场景 | 接入方式 | 依据 |
|------|----------|------|
| Claude 桌面端 | MCP stdio | 无 shell 与文件能力，MCP 是唯一通路 |
| Claude Code 桌面端 | CLI 为主，MCP 可选 | 具备 Bash，CLI 不占用上下文 |
| Codex 桌面端 | CLI 为主，MCP 可选 | 同上 |
| Codex 终端 | CLI 为主，MCP 可选 | 同上 |

上下文成本的差异：MCP 服务注册后，四个工具的定义在每次会话开始时进入上下文，约占 1–2KB，与是否实际使用无关。CLI 经 Bash 调用，未使用时占用为零，代价是 Agent 需要通过 `AGENTS.md` 或 skill 才知道该命令存在。

三个编码类客户端建议先用 CLI。若实际使用中 Agent 频繁遗漏该命令，再补注册 MCP，两者可以并存。

MCP 传输只实现 stdio。四个场景都在本机，不需要 HTTP 传输，因此不引入端口监听、token 鉴权与隧道。

### 6.2 各客户端配置

以下配置的版本与命令形态已在本机核实：Claude 桌面端 1.26832.0（应用内仍读取 `claude_desktop_config.json` 的 `mcpServers`）、Codex CLI 0.146.0。

**Claude 桌面端** —— 编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "quarry": {
      "command": "python3",
      "args": ["<仓库绝对路径>/server/mcp_server.py"],
      "env": { "QUARRY_VAULT": "<内容层绝对路径>" }
    }
  }
}
```

该文件当前存在但没有 `mcpServers` 键，需要新增。修改后重启应用生效。

**Claude Code 桌面端** —— `user` 作用域，对所有项目生效：

```bash
claude mcp add quarry -s user -e QUARRY_VAULT=<内容层绝对路径> -- python3 <仓库绝对路径>/server/mcp_server.py
```

**Codex 桌面端与终端** —— 共用 `~/.codex/config.toml`，配置一次覆盖两个场景：

```bash
codex mcp add quarry --env QUARRY_VAULT=<内容层绝对路径> -- python3 <仓库绝对路径>/server/mcp_server.py
```

**CLI** —— 将 `<仓库绝对路径>/bin` 加入 `PATH`，三个编码类客户端即可直接调用 `quarry`。

四处配置都显式传入 `QUARRY_VAULT`。原因是 MCP 服务由客户端拉起，工作目录不确定，`server.py` 中基于 `git rev-parse --git-common-dir` 的内容层推断（`server/server.py:71-101`）在该环境下不成立，显式传入避免定位到错误的内容层。CLI 保留该推断逻辑，因为它在仓库内运行。

### 6.3 工具契约

设计原则：**检索返回轻量结果，取详情才返回全文**。这是控制上下文消耗的核心。

#### `quarry_list_topics`

- 入参：无
- 返回：`[{id, name, description, postCount, platforms, latestAddedAt}]`
- 体量：每课题一行

#### `quarry_search`

- 入参：
  - `query`（必填，空格分词，词间 AND）
  - `topic` / `platform` / `contentType` / `hasTranscript`（可选过滤）
  - `since` / `until`（`YYYY-MM-DD`，作用于 `published`）
  - `limit`（默认 20，上限 50）、`cursor`
  - `in`（限定检索字段，缺省覆盖 title / body / summary / originalText / keywords / author / transcript）
- 检索范围中的 transcript 取自 md 投影的口播全文，不受 `TRANSCRIPT_LIMIT` 截断影响。
- 返回：
  ```json
  {
    "hits": [{
      "uid": "...", "topic": "...", "topicName": "...", "platform": "...",
      "author": "...", "title": "...", "published": "...",
      "summary": "不超过 120 字",
      "matched": [{"field": "transcript", "snippet": "……命中词前后各 40 字……"}],
      "hasTranscript": true, "sourceLink": "..."
    }],
    "total": 37, "returned": 20, "nextCursor": "...", "truncated": false
  }
  ```
- 单次返回硬上限 32KB，超出则截断并置 `truncated: true`。

#### `quarry_get_post`

- 入参：
  - `uid`（必填）
  - `include`（数组，可选值 `transcript` / `timeline` / `originalText` / `stats` / `rawMeta`；缺省包含前述除 `transcript`、`timeline`、`rawMeta` 外的内容）
  - `maxChars`（限制单次返回字符数，默认 40000）
- 返回：md 全文 + 结构化 frontmatter + 媒体路径，路径同时给相对内容层根目录的相对路径与绝对路径。
- 封面图在存在且体积小于 1MB 时，以 MCP image content block 返回，使 Claude 桌面端可以直接看到画面。视频与音频只返回路径，不内联。

#### `quarry_list_posts`

- 入参：`topic`（必填）、`sort`（`addedAt` / `published` / `number`）、以及与 `quarry_search` 相同的过滤与分页参数
- 返回：与 `quarry_search` 的 `hits` 同构，不含 `matched`

---

## 7. 上下文预算

| 操作 | 预期返回体量 | 说明 |
|------|--------------|------|
| `quarry_list_topics` | < 1KB | 与库规模无关 |
| `quarry_search`（limit=20） | 6–12KB | 与库规模无关，只与 limit 相关 |
| `quarry_get_post`（不含转写） | 2–5KB | |
| `quarry_get_post`（含转写全文） | 5–40KB | 受 `maxChars` 约束 |

一次典型的「找素材」会话：list_topics + search + 取 2–3 条详情，约 20–40KB。对比整库载入的 137KB（当前规模）与线性增长趋势，检索式读取的消耗不随库增长。

---

## 8. 实施与验收

### 8.1 交付物

| 阶段 | 文件 | 覆盖场景 |
|------|------|----------|
| 一 | `server/projection.py`、`server/server.py` 的 `sync_projection()` 挂钩 | 三个编码类客户端可 grep 与 read |
| 二 | `server/vault_query.py`、`server/quarry_cli.py`、`bin/quarry` | 三个编码类客户端可检索 |
| 三 | `server/mcp_server.py` | Claude 桌面端 |
| 共用 | `server/paths.py`（内容层定位，服务与两个读取入口共用一份） | — |

### 8.2 验收结果（2026-08-09，43 条存量数据）

| 判据 | 结果 |
|------|------|
| 存量数据全部生成 md 与索引 | 43 条 → 43 个 md + 43 行索引 + 5 个课题目录 |
| `reindex` 连续两次运行结果逐字节一致 | 一致（对全部文件比对 sha1） |
| 新增一条帖子后投影自动更新 | `save_posts()` 后索引由 1 行变 2 行，新 md 已生成 |
| 删除帖子后投影同步清理 | 索引行与 md 文件均已移除 |
| 单帖 md 的 frontmatter 可被 YAML 解析 | 43/43 通过 |
| 口播全文不被 16KB 截断 | 源 64,800 字节：`posts.json` 截到 16,399 字节，投影保留全部 64,800 字节 |
| 七个子命令全部可用、`--json` 可被解析 | 通过；`--json` 在子命令前后均生效 |
| Quarry 服务停止状态下仍可查询 | 通过（验收期间 6002 端口未监听） |
| MCP 握手与四个工具可调用 | initialize / tools/list / tools/call 全部正常，协议版本回显客户端声明 |
| CLI 与 MCP 对同一查询返回同构结果 | 两者输出完全相同 |
| 检索返回体量受控 | `limit=50` 实测 14KB，未触上限；将上限调低后能正确截断并置 `truncated` |
| 封面图内联 | 有封面的帖子返回 `image` content block（image/jpeg） |

### 8.3 文档同步

README 的文档表格与「让 AI Agent 读这个库」一节；`server/README.md` 的内容层结构、Agent 投影、读取入口、环境变量；仓库根新增 `AGENTS.md`，写明内容层定位规则、取数原则与 `quarry` 用法，使编码类客户端进入仓库即知道该命令存在。

---

## 9. 边界

1. 投影是派生数据。人工编辑 `vault/agent/` 下的 md 文件不会回写 `posts.json`，且会在下次 `reindex` 时被覆盖。
2. 检索为关键词匹配，不做同义扩展与语义召回。跨语言检索（中文词查英文原文）不命中。
3. `stats` 是收藏时刻的快照，不随时间更新。Agent 引用互动数据时应同时引用 `capturedAt`。
4. `warnings` 非空的帖子可能缺少媒体或转写。索引中保留该字段，供 Agent 判断数据完整性。
5. Claude 桌面端只能取到媒体文件路径，无法读取或处理视频与音频本身。需要对媒体做进一步加工（截帧、剪辑、转写复核）时，使用三个编码类客户端。
6. 四个场景均要求客户端与内容层在同一台机器上。内容层若被指向外置硬盘或同步盘，该盘未挂载时 MCP 服务启动失败，CLI 返回路径不存在。
