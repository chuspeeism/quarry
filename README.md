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
│   └── docs/        PRD 与设计文档
└── vault/           ← 内容层：本地专属，不进 git
    ├── data/        posts.json + backups/ + media/
    ├── outputs/     旧静态页产物
    └── archive/     历史归档
```

后端跑的是**双根静态解析**：前端资源从 `app/` 出，媒体从 `vault/` 出，两个根各自做路径越界校验。这样产品可以随便 clone、随便重装，内容层原地不动。

内容层默认在仓库同级的 `../vault/`，也可以指到任意位置（外置硬盘、同步盘）：

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

## 文档

| 文档 | 内容 |
|------|------|
| [server/README.md](server/README.md) | 后端接口、环境变量、内容层结构 |
| [docs/prd-01-topic-collector.md](docs/prd-01-topic-collector.md) | 从单平台浏览器升级为课题帖子库 |
| [docs/prd-02-multiplatform-import.md](docs/prd-02-multiplatform-import.md) | B 站 / 小红书 / 抖音链接导入设计 |
| [docs/prd-03-v1-collection-hub.md](docs/prd-03-v1-collection-hub.md) | V1 全平台收集中台升级说明 |

## 前端

`app/` 是一个零构建的 React 应用：浏览器里用 Babel standalone 直接编译 `.jsx`，没有 npm、没有打包步骤。改完文件刷新页面就生效。

因为 Babel 用 XHR 加载 jsx，必须通过 HTTP 打开（后端已经在服务），不支持 `file://` 双击。
