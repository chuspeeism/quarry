# PRD：本地 X/Twitter 课题收藏器（Topic Post Vault）

> 文档状态：**实现就绪版 v2**（供 CodeX 直接实现）。
> 本版在初始草案基础上，吸收了一次工程审核结论（决策 A–E，见 §4），并补齐了
> 精确的数据结构、迁移规则、ID/去重语义、API 契约、注入锚点与验收标准。
> **实现前请先通读 §12「当前代码现状」与 §13「注入锚点」，按现有代码增量改造，不要推倒重写。**

---

## 1. 背景与现状

当前产品已从静态 Fable 5 帖子浏览器演进为本地服务版工具：粘贴 X/Twitter 链接 →
后端抓取帖子、下载媒体、调用 AI 生成中文标题/正文/摘要/关键词 → 持久化加入列表。

已落地的现状（实现时以此为基线）：

- 后端：`server/server.py`（Python 标准库，无第三方依赖），端口默认 `6002`，绑 `0.0.0.0`。
- 抓取：`opencli twitter thread <id> -f json --window background`；长文回退 `article`。
- 媒体：取 `thread` 的 `media_urls` **直链下载**，逐项判定成功/失败。
- AI：`codex exec` 异步生成中文字段；可 `AI_ENGINE=ark`/`none` 切换。
- 数据：`data/posts.json`（**当前 version 1，23 条**：21 条种子 + 用户测试新增 2 条，
  含一条 `number: 999` 的 Every 文章卡），媒体落在 `data/media/`。
- 前端：**不改动磁盘上的 `index.html`**；服务端在内存里把 `index.html` 的 `init()`
  块替换为 `/api/posts` 加载逻辑并注入输入框（见 §13）。

遗留的「单课题痕迹」需要在本次升级中消除：页面仍叫 Fable 5 Feed；数据无课题层级；
添加时只有一行状态文字、无进度条；定位仍像 Fable 5 案例浏览器。

## 2. 产品定位

- 英文名：**Topic Post Vault**；中文名：**课题帖子库**。
- `Topic` = 上层研究课题；`Post` = 不绑死 X/Twitter；`Vault` = 本地长期可回访收藏。
- 页面主标题：`Topic Post Vault`；副标题：`本地 X/Twitter 课题收藏器`。
- 课题视图可显示：`课题：Fable 5 · 23 条收藏帖`。

## 3. 用户目标（工作流）

1. 创建或选择课题（如 `fable5`、`seedance2.0`）。
2. 在该课题下粘贴一条 X/Twitter 链接。
3. 看到明确的**抓取进度条**（百分比 + 阶段文案），而非一行文字。
4. 抓取完成后，帖子永久加入**当前课题**。
5. 之后可按课题浏览、搜索、筛选、继续补充。

## 4. 工程决策（已与用户确认，无异议）

| # | 决策点 | 结论 |
|---|--------|------|
| A | `postCount` | **动态计算，不持久化**到 topic 对象（避免与实际数量漂移） |
| B | 帖子 `id` | 引入**复合唯一 id**；迁移时规范化现有 23 条的 id（仅内部使用，安全） |
| C | `/api/add` 未知 topic | **返回 400**，不静默自动建课题；缺省 topic 时回退第一个课题 |
| D | 媒体目录 | 保持**扁平、按 tweetId 命名**，跨课题同推文共享同一媒体文件 |
| E | 服务版前端 | 维持**运行时注入**（不分叉出 app.html），增加启动期锚点自检 + 命中失败原样降级 |

## 5. 范围

### 5.1 必须做
- 命名从 Fable 5 专用升级为通用课题收藏器。
- 新增课题层级：每条帖子必须归属一个 `topic`。
- 添加链接时必须选择/输入目标课题。
- 抓取过程显示进度条 + 阶段文案。
- 现有 Fable 5 数据迁移到默认课题 `fable5`，**不丢用户新增帖、不重排 number**。
- 不破坏静态 `index.html` 的 `file://` 直接打开能力。
- 服务版继续复用现有后端能力（`opencli` 抓取、媒体直链下载、`codex`/`ark` 异步 AI）。

### 5.2 不做（本次）
用户登录/多用户/权限、云端同步、浏览器插件、批量导入、非 X/Twitter 平台、复杂标签系统
（先做单层 `topic`，标签后续再说）、一帖多课题（MVP 单课题归属）。

## 6. 信息架构

```
Topic Post Vault
└── Topics
    ├── fable5
    │   ├── post 1
    │   └── ...
    └── seedance2.0
        └── ...
```

帖子至少属于一个课题；MVP 单课题归属（`post.topic` 为字符串，非数组）。

## 7. 数据模型与迁移（核心）

### 7.1 `data/posts.json` v2 结构

```json
{
  "version": 2,
  "count": 23,
  "topics": [
    {
      "id": "fable5",
      "name": "Fable 5",
      "description": "Claude Fable 5 / Mythos 相关社媒案例",
      "createdAt": 1760000000,
      "updatedAt": 1760000000
    }
  ],
  "posts": [
    {
      "uid": "fable5__2064397343101993267",
      "id": "fable5__2064397343101993267",
      "topic": "fable5",
      "number": 1,
      "tweetId": "2064397343101993267",
      "title": "帖子 1：Pokémon FireRed 视觉通关",
      "author": "Chetaslua",
      "handle": "@chetaslua",
      "published": "...",
      "body": "中文正文",
      "summary": "中文摘要",
      "originalText": "原文",
      "originalIsExcerpt": false,
      "originalNote": "",
      "keywords": ["..."],
      "supplement": "",
      "sourceLink": "https://x.com/...",
      "mediaPath": "fable5_tweet_media_hq/....mp4",
      "mediaName": "....mp4",
      "imagePath": "",
      "articleLinks": [],
      "aiStatus": "ready",
      "source": "seed"
    }
  ]
}
```

> 说明：topic 对象**不含 `postCount`**（决策 A，动态算）。post 沿用现有前端字段，
> 新增 `uid`、`topic`；`id` 置为与 `uid` 相同值以兼容前端按 `id` 聚焦的逻辑。

### 7.2 ID 方案与去重语义（决策 B）

- **`uid` = `${topic}__${tweetId}`**（无 tweetId 的特殊卡，如 Every 文章，用
  `${topic}__${slug(原id或sourceFile)}`）。`uid` 在全库唯一。
- `id` 字段 = `uid`（前端用 `id`/`tweetId` 聚焦，二者都要能命中）。
- **去重键 = (topic, tweetId)**：
  - 同 topic 内重复添加同一 tweetId → **拦截**，任务直接 `done` 且
    `message: "该帖已在该课题中，已为你定位。"`，`postId` 指向已存在帖，**不新增**。
  - 跨 topic 添加同一 tweetId → **允许**新增一条记录（不同 `uid`），共享同一媒体文件（决策 D）。

### 7.3 每课题独立序号（number）

- `number` 仅用于**课题内排序**。迁移**不重排** fable5 现有 number（含 999 哨兵）。
- 新帖 `number = next_number(topic)` = 该 topic 内 `<900` 的最大 number + 1；空课题从 1 开始。

### 7.4 迁移规则（v1 → v2，必须幂等、安全）

启动加载 `data/posts.json` 时：
1. 若已是 `version: 2` 且含 `topics` → 原样使用，不动。
2. 若 `version` 缺失/为 1 或无 `topics`：
   - 创建默认课题 `fable5`（name=`Fable 5`，description 见上，时间戳=当前）。
   - 给**每条**缺 `topic` 的帖补 `"topic": "fable5"`。
   - 为每条计算 `uid`/`id`（§7.2），**不删除任何旧字段、不改 number、不丢任何帖（含用户新增的 2 条）**。
   - 写回 `version: 2`，备份原文件为 `data/posts.v1.bak.json`（首次迁移时）。
3. 若 `data/posts.json` 不存在（全新环境）：从
   `outputs/handoffs/2026-06-10_codex_制作Twitter帖子浏览器_019eaf90_share/post_content_dataset.json`
   的 `.posts` 种子导入，并直接产出 v2（默认课题 fable5）。

## 8. API 契约

所有响应 `Content-Type: application/json; charset=utf-8`，`Cache-Control: no-store`，带 CORS `*`。

### 8.1 `GET /api/topics`
```json
{ "topics": [ { "id": "fable5", "name": "Fable 5", "description": "...", "postCount": 23 } ] }
```
`postCount` 动态统计当前 `posts` 中该 topic 的数量（决策 A）。

### 8.2 `POST /api/topics`
请求：`{ "name": "Seedance 2.0", "id": "seedance2.0" }`
- `id` 可选；缺省时由 `name` 生成 slug：转小写、空格转 `-`、仅保留 `[a-z0-9._-]`、去重复连字符。
- 校验：`name` 必填；`id` 非空、`^[a-z0-9][a-z0-9._-]{0,49}$`、全库唯一。
- 冲突/非法 → `400 { "error": "..." }`。
- 成功 → `201 { "topic": { "id", "name", "description", "createdAt", "updatedAt" } }`，并持久化。

### 8.3 `GET /api/posts?topic=<id>`
- 带 `topic` → 只返回该课题帖子：`{ "posts": [...], "count": N, "topic": "<id>" }`。
- 不带 `topic` → 返回全部（向后兼容）：`{ "posts": [...], "count": M }`。
- `topic` 不存在 → 返回空列表 `{ "posts": [], "count": 0, "topic": "<id>" }`（不报错，供空状态用）。

### 8.4 `POST /api/add`
请求：`{ "url": "https://x.com/.../status/123", "topic": "fable5" }`
- `url` 必填且能解析出 tweetId，否则 `400`。
- `topic` 缺省 → 回退**第一个** topic（决策 C）；`topic` 提供但**不存在 → 400**（决策 C）。
- 成功 → `{ "taskId": "xxx" }`，后台线程异步处理。

### 8.5 `GET /api/task/<id>`
```json
{
  "taskId": "xxx",
  "stage": "fetching",
  "progress": 20,
  "message": "正在抓取推文正文与作者信息",
  "postId": null,
  "topic": "fable5",
  "warnings": []
}
```
`postId` 为帖子 `uid`（卡片写入后即填充，供前端聚焦）。

## 9. 任务进度映射

| stage | progress | 文案 |
|-------|----------|------|
| pending | 5 | 已创建任务 |
| fetching | 20 | 正在抓取推文正文与作者信息 |
| downloading | 45 | 正在下载媒体 |
| writing | 60 | 正在写入本地收藏 |
| ai | 80 | 正在生成中文标题、翻译和摘要 |
| done | 100 | 已加入收藏 |
| error | 保持当前值 | 处理失败（附 message） |

要求：
- `error` 时**不回退 progress**（保留进入该阶段时的值；实现上：每进入一个阶段就写一次 progress，error 分支只写 stage/message）。
- 媒体下载 warning **不阻断**任务，但要带回 `warnings` 并在前端显示。
- 卡片已写入但 AI 未完成时（stage=ai），列表中该帖显示「AI 加工中」（沿用现有 `aiStatus` + body 占位）。

## 10. 前端（服务版，运行时注入）

> 决策 E：维持内存注入，不分叉文件。在现有 `build_app_html()` 的注入基础上**增量扩展**。
> 启动时对所有注入锚点做命中自检，任一未命中则打印告警并对该处原样降级（不崩）。

### 10.1 文本替换（精确锚点见 §13）
- `<title>` → `Topic Post Vault · 课题帖子库`
- H1 `Fable 5<br>Feed` → `Topic Post<br>Vault`
- 副标题 `Claude Fable 5 社媒案例浏览器` → `本地 X/Twitter 课题收藏器`

### 10.2 新增 UI（注入到左栏 `.search-wrap` 区域附近）
- **课题选择器**：下拉/分段，列出 `GET /api/topics`；显示当前课题名与 `postCount`。
- **新建课题入口**：`+ 新建课题` → 弹输入（name，可选 id）→ `POST /api/topics` → 刷新选择器并切到新课题。
- **添加区**：链接输入框 + 「添加到 <当前课题名>」按钮（明确标出目标课题）。
- **进度条组件**：独立元素（例如 `#addProgress`/`.add-progress-bar`），**不得复用右栏的 `#progressFill`**（那是滚动位置指示，与任务进度无关）。

参考左栏结构：
```
Topic Post Vault / 本地 X/Twitter 课题收藏器
[课题下拉: Fable 5 (23)]   [+ 新建课题]
[搜索当前课题帖子]
[粘贴 X/Twitter 链接]      [添加到 Fable 5]
[████████░░ 80% 正在生成中文…]
```

### 10.3 状态与交互
- 新增 `state.topic`（当前课题 id）；默认取第一个 topic（可用 `localStorage` 记住上次选择，nice-to-have）。
- 切换课题：`reloadPosts(topic)` 调 `/api/posts?topic=` → 重置 `state.index=0` → `render()` → 更新标题/计数。
- 搜索沿用现有 `filterPosts`，天然只在 `state.posts`（=当前课题）内搜（符合 §5/§7 不改布局）。
- 添加：请求体带 `state.topic`；进行中禁用输入框与按钮；`pollTask` 读 `progress` 驱动进度条宽度与文案；`done` 显示 100% + warnings；`error` 显示错误文案并保留 warnings。
- 空课题：显示空状态提示（如「该课题还没有收藏，粘贴一条链接开始」），不得报错或显示「没有匹配的帖子」误导文案。

## 11. 媒体与兼容性

- 媒体保持扁平 `data/media/<tweetId>_<n>.<ext>`（决策 D）。跨课题同推文复用同一文件。
- 静态 `index.html` 磁盘文件**零改动**，`file://` 打开仍用内置 `fallbackPosts`（单课题 Fable 5）正常显示。
- 服务版 `http://127.0.0.1:6002/` 使用新版课题收藏器 UI。
- 进度条/Range 等现有能力（视频 206）保持不变。

## 12. 当前代码现状（实现参照，勿推倒重写）

`server/server.py` 关键现状：
- 全局：`POSTS`（list，前端字段结构）、`TASKS`（dict，taskId→状态）、`LOCK`（RLock）。
- 函数：`seed_from_dataset()`、`load_posts()`/`save_posts()`、`next_number()`、
  `find_by_tweetid()`、`set_task()`/`get_task()`、`run_opencli()`/`fetch_thread()`/`fetch_article()`、
  `format_published()`、`download_media()`、`run_ai()`/`ai_codex()`/`ai_ark()`、
  `process_add(task_id, url)`、`build_app_html()`、`Handler`（do_GET/do_POST + Range 静态）、`lan_ip()`、`main()`。
- 路由：`GET /`(=注入版 index.html，`APP_PATHS`)、`GET /api/posts`、`GET /api/task/<id>`、
  `POST /api/add`、其余走 `_serve_static`（项目根，带 Range）。

需改造的点对应关系：
- `seed_from_dataset`/`load_posts`：产出/迁移到 v2（§7.4），新增 `TOPICS` 内存结构。
- `next_number`→按 topic；`find_by_tweetid`→`find_by_topic_tweetid(topic, tid)`。
- `set_task`：每阶段附带 `progress`；新增 `topic` 字段。
- `process_add(task_id, url)`→`process_add(task_id, url, topic)`：写 `post.topic`/`uid`，逐阶段写 progress，去重按 (topic, tweetId)。
- `Handler`：新增 `GET /api/topics`、`POST /api/topics`；`/api/posts` 支持 `?topic=`；`/api/add` 读 `topic`。
- `build_app_html`：扩展注入（§10、§13）。

前端帖子字段（现有，迁移后新增 `uid`/`topic`）：
`uid,id,topic,number,tweetId,title,author,handle,published,body,summary,originalText,
originalIsExcerpt,originalNote,keywords[],supplement,sourceLink,mediaPath,mediaName,
imagePath,articleLinks[],aiStatus,(remoteMedia,warnings,source,addedAt)`。

## 13. 注入锚点（精确字符串）

`build_app_html()` 对内存中的 `index.html` 文本做精确替换；每个锚点替换前先 `in` 判断，未命中则告警并跳过（降级），不抛错。

1. 标题：`<title>Fable 5 帖子浏览器</title>` → `<title>Topic Post Vault · 课题帖子库</title>`
2. 品牌块（位于 `<header class="brand">` 内）：
   - `<h1>Fable 5<br>Feed</h1>` → `<h1>Topic Post<br>Vault</h1>`
   - `<p>Claude Fable 5 社媒案例浏览器</p>` → `<p>本地 X/Twitter 课题收藏器</p>`
3. `init()` 块：现有实现已把原 `init` 替换为 `NEW_INIT`（含 `reloadPosts/injectComposer/addLink/pollTask`）。
   本次在 `NEW_INIT` 基础上扩展：`state.topic`、课题选择器/新建、`reloadPosts(topic, focusId)`
   带 `?topic=`、进度条渲染。注入的新 UI 通过 JS 建 DOM + 注入 `<style>`，挂到 `.search-wrap` 之后。

> 注意：右栏已有 `#progressFill`（滚动位置指示），任务进度条必须用**新的**元素 id/class，勿混用。

## 14. 验收标准

### 14.1 数据迁移
- 启动后 `data/posts.json` 为 `version: 2`，且生成了 `data/posts.v1.bak.json` 备份（首迁）。
- 所有旧帖（含用户新增 2 条，共 23 条）都有 `topic: "fable5"` 与唯一 `uid`，number 未被重排。
- `GET /api/topics` 至少返回 `fable5`，其 `postCount` 与实际一致。
- `GET /api/posts?topic=fable5` 返回现有全部 fable5 帖。

### 14.2 课题创建
- 能创建 `seedance2.0`；创建后可切换；空课题显示空状态而非报错。
- 非法/重复 id → 400。

### 14.3 添加帖子
- 在 `seedance2.0` 下添加一条链接后，该帖只出现在 `seedance2.0`；切回 `fable5` 看不到它。
- 同 topic 内重复添加同一链接 → 提示已存在、不新增重复项、定位到原帖。
- 跨 topic 添加同一链接 → 允许新增（不同 uid），媒体文件复用。

### 14.4 进度条
- 添加开始后显示进度条，按 pending(5)→fetching(20)→downloading(45)→writing(60)→ai(80)→done(100) 推进。
- 完成显示 100%；失败显示错误文案并保留已知 warning；warning 不阻断流程。
- 卡片写入后（done 前）该帖在列表显示「AI 加工中」。

### 14.5 兼容性
- 磁盘 `index.html` 未被修改；`file://` 打开仍显示内置 Fable 5 数据。
- 服务版 `http://127.0.0.1:6002/` 显示新版课题收藏器 UI（新标题/副标题/课题选择器/进度条）。

## 15. 实施步骤（建议两步，每步自带验证）

### Step 1 — 数据与 API
1. v2 schema + 迁移（§7.4，含 v1 备份），内存加载 `TOPICS`。
2. `next_number(topic)`、`find_by_topic_tweetid`、去重语义（§7.2）。
3. `GET/POST /api/topics`（动态 postCount、slug 校验）。
4. `GET /api/posts?topic=`、`POST /api/add` 带 topic（未知→400、缺省→首个）。
5. `set_task`/`process_add` 加 `progress`+`topic`，按 §9 映射。
6. 验证：迁移结果、topics、按 topic 取帖、去重、跨 topic 行为（用 curl）。

### Step 2 — 前端注入与体验
1. 标题/副标题/H1 文本替换（§13），启动锚点自检。
2. 课题选择器 + 新建课题入口 + 「添加到 <课题>」输入区。
3. 进度条组件（新 id）+ `pollTask` 读 `progress`。
4. `state.topic` + 切换刷新（`?topic=`）+ 空状态。
5. 验证：建课题→切换→空状态→加帖只入当前课题→重复拦截→进度条到 100%；
   确认磁盘 index.html 未变、file:// 正常。

## 16. 风险与护栏（实现时务必遵守）

- `topic` 必须**持久化到每条帖**，不能只做前端筛选状态。
- 产品名不得硬编码 Fable 5；Fable 5 只能作为默认 topic。
- 进度必须有**可视百分比**，不能只显示「处理中」。
- 媒体下载失败**不得阻断**收藏（除非正文抓取也失败）；失败记 warning + 保留远程链接。
- 不得破坏静态文件的 `file://` 打开能力（磁盘 `index.html` 零改动）。
- 不得重置/丢失用户当前 `data/posts.json` 中的帖（迁移前先备份 v1）。
- 帖子 `uid` 必须全库唯一；前端聚焦同时支持按 `id`/`tweetId` 命中。
- 注入锚点替换前先判存在，未命中降级而非崩溃。
