<div align="center">
  <img src="app/assets/icon/quarry-icon-1024.png" width="128" alt="Quarry">
  <h1>Quarry · 选题矿场</h1>
  <p>围绕一个课题，把全网素材开采到本地。</p>
</div>

---

Quarry 是一个本地优先的多平台内容采集中台。先建一个课题，再粘贴 X/Twitter、B 站、小红书、抖音的链接（支持多行批量），它会把帖子正文、视频、封面、摘要、原文，以及**口播转写四件套（mp4 + m4a + srt + 口播词.md）**统一沉淀到你自己的磁盘上。库内容可增可删可改，支持含转写全文的检索。

**这个仓库只有产品，没有内容。** 采集到的一切都落在仓库之外的内容层，永远不会被提交。

## 快速开始

```bash
git clone https://github.com/chuspeeism/quarry.git
cd quarry/server && ./start.sh
```

打开 <http://127.0.0.1:6002/>。首次启动内容层是空的，直接新建课题开始粘链接即可。

依赖：`python3`（仅标准库）、`ffmpeg`（转写用）、`opencli`（抓取用）、`codex` 或火山 Ark API Key（AI 加工用）。

## 产品层 / 内容层分离

这是 Quarry 的核心结构约束——代码和素材彻底分开，各自独立演进：

```text
Quarry-选题矿场/
├── quarry/          ← 产品层：本仓库，只有代码
│   ├── app/         前端（自包含 React + Babel standalone，无构建步骤）
│   ├── server/      后端（Python 标准库 HTTP 服务）
│   ├── bin/         quarry 命令行入口
│   └── docs/        PRD 与设计文档
└── vault/           ← 内容层：本地专属，不进 git
    ├── data/        posts.json + backups/ + media/
    ├── agent/       Agent 可读投影（一帖一 md + 索引，由 data/ 派生）
    ├── outputs/     旧静态页产物
    └── archive/     历史归档
```

后端跑的是**双根静态解析**：前端资源从 `app/` 出，媒体从 `vault/` 出，两个根各自做路径越界校验。这样产品可以随便 clone、随便重装，内容层原地不动。

内容层默认在**主仓库**同级的 `../vault/`（在 git worktree 里启动也会自动指回同一个内容层，不会在 worktree 旁边另开一个），也可以指到任意位置（外置硬盘、同步盘）：

```bash
QUARRY_VAULT=/Volumes/Data/quarry-vault ./start.sh
```

## 内容按层级分批管理

内容层是**按文件层级分批**组织的，新采集的内容自动落到对应平台目录：

```text
vault/data/media/
├── bilibili/<bvid>/          按稿件号一件一目录
├── douyin/<aweme_id>/
├── xiaohongshu/<note_id>/
└── <tweet_id>_<n>.{mp4,m4a,srt,口播词.md}
```

`posts.json` 里记录的路径一律相对内容层根目录，所以整个 `vault/` 可以整体搬走、备份、换盘，不用改一行代码。

## 把一条内容交给 AI

详情页底部有「复制给 AI」：点一下，这条的标题、摘要、正文、平台原文、口播全文，
外加视频/音频/字幕/关键帧的本机绝对路径，一起进剪贴板。粘到任何 AI 里都自足，
不需要对方有读你磁盘的能力。按住 Shift 点则不带口播（长视频的转写能有几万字）。

视频本身没法跟着剪贴板走，所以每条视频都抽了 4–12 张**关键帧**——纯文本消费方
看不了视频，但能读这些静帧。

## 让 AI Agent 检索这个库

收藏进来的内容会同步投影到 `vault/agent/`：一帖一个 md（含不截断的口播全文），加一份 `index.jsonl` 轻量索引。Agent 可以直接 grep 和 read，也可以走命令：

```bash
export PATH="$PWD/bin:$PATH"
quarry topics                       # 课题清单
quarry search "提示词" --topic ae   # 全字段检索，含口播转写
quarry show <uid> --full            # 单帖全文
quarry pack --topic fable5          # 打包一个课题为单文件
```

命令直接读投影，不需要后端服务在跑。Claude 桌面端够不到磁盘，走 MCP：

```bash
claude mcp add quarry -s user -e QUARRY_VAULT=<内容层路径> -- python3 <仓库路径>/server/mcp_server.py
codex  mcp add quarry    --env QUARRY_VAULT=<内容层路径> -- python3 <仓库路径>/server/mcp_server.py
```

完整设计与各客户端配置见 [docs/prd-04-agent-read-access.md](docs/prd-04-agent-read-access.md)。

## 文档

| 文档 | 内容 |
|------|------|
| [AGENTS.md](AGENTS.md) | 给 Agent 的仓库须知：内容层在哪、怎么查 |
| [server/README.md](server/README.md) | 后端接口、环境变量、内容层结构 |
| [docs/prd-01-topic-collector.md](docs/prd-01-topic-collector.md) | 从单平台浏览器升级为课题帖子库 |
| [docs/prd-02-multiplatform-import.md](docs/prd-02-multiplatform-import.md) | B 站 / 小红书 / 抖音链接导入设计 |
| [docs/prd-03-v1-collection-hub.md](docs/prd-03-v1-collection-hub.md) | V1 全平台收集中台升级说明 |
| [docs/prd-04-agent-read-access.md](docs/prd-04-agent-read-access.md) | Agent 读取能力：投影、CLI、MCP |

## 前端

`app/` 是一个零构建的 React 应用：浏览器里用 Babel standalone 直接编译 `.jsx`，没有 npm、没有打包步骤。改完文件刷新页面就生效。

因为 Babel 用 XHR 加载 jsx，必须通过 HTTP 打开（后端已经在服务），不支持 `file://` 双击。
