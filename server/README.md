# Quarry 后端

本地多平台内容采集服务：先选择或创建一个课题，再粘贴 X/Twitter、B 站、小红书或抖音链接，后端会抓取内容、保存媒体、跑 ASR 转写，并用 AI 生成中文标题/正文/摘要/关键词，最后写进该课题。

## 启动

```bash
cd server && ./start.sh
```

默认端口 `6002`，启动后打印：

```text
Quarry · 选题矿场 已启动
内容层：  /path/to/vault
本机：    http://127.0.0.1:6002/
局域网：  http://192.168.x.x:6002/
```

## 产品层与内容层

后端有两个互不重叠的根目录，这是本项目的核心约束：

| 根 | 变量 | 默认位置 | 内容 |
|----|------|----------|------|
| 产品层 | `APP_ROOT` | `<repo>/app` | 前端静态资源，进 git |
| 内容层 | `VAULT_ROOT` | `<主仓库>/../vault` | 采集到的一切，**永不进 git** |

`QUARRY_VAULT` 可以把内容层指到任意路径（外置硬盘、同步盘都行）：

```bash
QUARRY_VAULT=/Volumes/Data/quarry-vault ./start.sh
```

默认位置里的 `<repo>` 指**主仓库**，不是当前工作副本。在 `git worktree` 里启动时，后端会用 `git rev-parse --git-common-dir` 反推主仓库位置，所以任何 worktree 跑起来都指向同一个内容层，不会在 worktree 旁边另开一个 vault。非 git 仓库（下载 zip）或 git 不可用时退回当前目录的同级 `../vault`。

静态文件解析是双根的：先在 `APP_ROOT` 找前端资源，找不到再回落到 `VAULT_ROOT` 找媒体。两个根各自做越界校验，`../` 逃逸会被拒绝。

## 内容层结构

```text
vault/
├── data/
│   ├── posts.json          v3 主数据（topics + posts）
│   ├── backups/            版本迁移时自动生成的备份
│   └── media/              新增采集的媒体，按平台分子目录
├── agent/                  Agent 可读投影，由 data/posts.json 单向派生
│   ├── topics.json         课题清单
│   ├── index.jsonl         一行一帖的轻量索引
│   └── topics/<课题>/      _topic.md + 一帖一个 <序号>-<标题>.md
├── fable5_tweet_media_hq/  历史 X 素材（保留旧 URL 契约）
├── fable5_tweet_media/
├── outputs/                旧静态页产物
└── archive/                历史归档
```

`posts.json` 里的媒体路径一律相对 `VAULT_ROOT`，例如 `data/media/xxx.mp4`、`fable5_tweet_media_hq/xxx.mp4`。

首次启动时如果内容层是空的，会直接初始化一个空库，不需要任何种子文件。

## Agent 投影

`agent/` 是 `data/posts.json` 的只读派生投影，供 `quarry` 命令行与 MCP 服务读取，也供 Agent 直接 grep。写入挂在 `save_posts()` 之后——那是全部数据变更的唯一出口。

- 增量同步与全量重建走同一段渲染代码，两者产物逐字节一致。
- 投影写入失败不阻断采集链路，错误记入 `agent/.sync-errors.log`。
- 单帖 md 里的口播全文取自 `transcriptMdPath` 指向的文件，不受 `transcript` 字段 16KB 截断的限制。
- `rawMeta` 不进投影。
- 服务启动时比对索引行数与主数据条数，不一致就自动全量重建。

手动重建：`bin/quarry reindex`。改了渲染逻辑要把 `projection.py` 的 `RENDER_VERSION` 加一。

## 平台支持

| 平台 | 当前支持 |
|------|----------|
| X/Twitter | 完整链路：正文、媒体、ASR、AI 加工 |
| Bilibili | 元数据、封面、字幕/官方总结优先，可下载视频本体 |
| 小红书 | 笔记信息 + 图片/视频下载；完整详情通常需要带 `xsec_token` 的链接 |
| 抖音 | 真实抓取 + 下载 + 统一 ASR 转写 |

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `PORT` | 6002 | 监听端口 |
| `QUARRY_VAULT` | `<主仓库>/../vault` | 内容层根目录 |
| `QUARRY_DEFAULT_TOPIC_ID` | `inbox` | 默认课题 id |
| `QUARRY_DEFAULT_TOPIC_NAME` | 未归类 | 默认课题名 |
| `QUARRY_IMPORT_CONCURRENCY` | 2 | 并发导入闸门 |
| `AI_ENGINE` | codex | `codex` / `ark` / `none` |
| `ARK_API_KEY` | — | `AI_ENGINE=ark` 时必填 |
| `ARK_MODEL` | doubao-seed-1-6-250615 | 豆包模型 |
| `OPENCLI_BIN` / `CODEX_BIN` | opencli / codex | 可执行文件路径 |
| `QUARRY_AGENT_PROJECTION` | 1 | 置 0 关闭 `agent/` 投影 |

## 接口

- `GET /api/topics` → `{topics:[{id,name,description,postCount,...}]}`
- `POST /api/topics` body `{name,id?}` → 创建课题
- `PATCH /api/topics/<id>` body `{name?,description?}` → 课题改名/改描述（id 不变，帖子按 id 归属）
- `DELETE /api/topics/<id>` → 删课题；非空必须加 `?force=1` 连帖子一起删，再加 `?media=1` 连本地媒体一起清理。删掉最后一个课题会自动重建默认课题
- `GET /api/posts?topic=<id>` → 返回指定课题帖子
- `PATCH /api/posts/<uid>` body `{title?,body?,summary?,keywords?,supplement?}` → 编辑帖子
- `DELETE /api/posts/<uid>` → 删帖子；`?media=1` 连本地媒体文件一起删
- `POST /api/add` body `{url,topic}` → `{taskId}`
- `GET /api/task/<id>` → `{stage,progress,postId?,topic,warnings,message?}`
- `GET /api/meta` → `{vaultRoot,version,posts,topics}`，前端「复制给 AI」拼本机绝对路径用

## 读取入口（不经过 HTTP 服务）

| 入口 | 文件 | 用途 |
|------|------|------|
| 命令行 | `../bin/quarry` → `quarry_cli.py` | 给人用，也给有 shell 的 Agent 用 |
| MCP | `mcp_server.py` | 给 Claude 桌面端这类够不到磁盘的客户端用，stdio 传输 |
| 查询内核 | `vault_query.py` | 上面两者共用，保证返回结构一致 |

```bash
../bin/quarry topics
../bin/quarry search "提示词" --topic ae
../bin/quarry show <uid> --full
python3 mcp_server.py --vault <内容层路径>     # MCP 服务，由客户端拉起
```

MCP 只暴露四个只读工具：`quarry_list_topics` / `quarry_search` / `quarry_list_posts` / `quarry_get_post`。不实现 HTTP 传输，不做公网暴露。各客户端配置见 [docs/prd-04-agent-read-access.md](../docs/prd-04-agent-read-access.md) §6.2。

## 转写管线

`asr.py`：ffmpeg 抽音 → 火山豆包 ASR（Groq Whisper 兜底）→ 产出四件套 `mp4 + m4a + srt + 口播词.md`，全部落在内容层。

**「无人声」与「转写失败」是两回事。** 火山返回 errcode `20000003 / no valid speech` 时是一个确定结论，不是引擎故障，此时不落兜底引擎——Whisper 在无人声音频上会自信地编造中文字幕组样板文本（「请不吝点赞订阅转发打赏」之类），用它去兜一个正确的否定判断只会把幻觉写进库里。判定为无人声时 `transcriptSource` 记 `none`，并清掉可能残留的旧 srt / 口播词.md。Groq 的结果还要再过一道幻觉检查（整条都由样板句组成才判定，避免误杀真的说了「记得点赞」的视频）。

## 关键帧

`keyframes.py`：按时长均匀抽 4–12 张静帧到 `<视频名>.关键帧/`，用输入端 seek 逐帧取，不解码全片。

用均匀抽帧而不是场景切换检测，是实测结论：同一条 3 分钟的说话人视频，均匀抽帧 6 张抓到 4 张信息卡片，`select='gt(scene,0.3)'` 抽 7 张全是同一机位、一张卡片没抓到。这类内容机位不切，信息在叠加的文字卡上，一张卡出现时整帧像素差异够不到 scene 阈值。场景检测还要解码全片，慢一个量级。
