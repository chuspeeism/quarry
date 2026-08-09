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
├── fable5_tweet_media_hq/  历史 X 素材（保留旧 URL 契约）
├── fable5_tweet_media/
├── outputs/                旧静态页产物
└── archive/                历史归档
```

`posts.json` 里的媒体路径一律相对 `VAULT_ROOT`，例如 `data/media/xxx.mp4`、`fable5_tweet_media_hq/xxx.mp4`。

首次启动时如果内容层是空的，会直接初始化一个空库，不需要任何种子文件。

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

## 接口

- `GET /api/topics` → `{topics:[{id,name,description,postCount,...}]}`
- `POST /api/topics` body `{name,id?}` → 创建课题
- `GET /api/posts?topic=<id>` → 返回指定课题帖子
- `POST /api/add` body `{url,topic}` → `{taskId}`
- `GET /api/task/<id>` → `{stage,progress,postId?,topic,warnings,message?}`

## 转写管线

`asr.py`：ffmpeg 抽音 → 火山豆包 ASR（Groq Whisper 兜底）→ 产出四件套 `mp4 + m4a + srt + 口播词.md`，全部落在内容层。
