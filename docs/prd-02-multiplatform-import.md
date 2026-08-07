# PRD: 多平台视频链接导入

> 目标分支：`codex/topic-vault-multiplatform-video-import`
>
> 产品基线：Topic Post Vault / 课题帖子库。当前已经支持 X/Twitter 链接输入、课题归档、媒体保存、AI 中文加工与进度条。

## 1. 背景

当前产品已经从 Fable5 专用浏览器升级为本地课题收藏器。它的核心能力是：

- 选择或创建课题。
- 输入 X/Twitter 链接。
- 后端抓取原帖、下载媒体、生成中文标题/正文/摘要/关键词。
- 把内容保存到指定课题下。

下一步目标是支持更多中文内容平台的视频链接导入：**抖音、小红书、B 站**。用户希望像添加 X/Twitter 链接一样，把这些平台的视频/笔记链接也加入同一个课题库。

## 2. 产品目标

把 Topic Post Vault 从“X/Twitter 课题收藏器”升级为：

```text
Topic Post Vault
本地多平台内容收藏器
```

用户可以在同一个课题下收藏来自多个平台的内容：

- X/Twitter 帖子
- Bilibili 视频
- 小红书笔记/视频笔记
- 抖音视频

每条内容仍然以“可浏览的一页卡片”形式展示，并保留中文/原文切换、媒体预览、摘要、关键词、原链接。

## 3. 用户故事

1. 用户创建课题 `seedance2.0`。
2. 用户粘贴一个 B 站视频链接。
3. 系统显示进度条：识别平台、抓取元数据、下载视频、提取字幕/总结、AI 加工、保存。
4. 完成后，该视频作为一条内容卡片出现在 `seedance2.0` 下。
5. 用户继续粘贴小红书/抖音链接，这些内容也进入同一课题。
6. 用户可以按课题搜索和浏览，不需要关心来源平台差异。

## 4. 已确认的本机能力

通过 `opencli list -f json` 与 `--help` 已确认：

### 4.1 Bilibili

可用命令：

- `opencli bilibili video <bvid-or-url> -f json`
- `opencli bilibili download <bvid-or-url> --output <dir> -f json`
- `opencli bilibili subtitle <bvid-or-url> -f json`
- `opencli bilibili summary <bvid-or-url> -f json`

结论：B 站适合作为本次 MVP 的最高确定性平台。

### 4.2 小红书

可用命令：

- `opencli xiaohongshu note <full-note-url-with-xsec_token> -f json`
- `opencli xiaohongshu download <note-url-or-xhslink> --output <dir> -f json`

结论：小红书可做 MVP，但应提示：详情抓取最好使用带 `xsec_token` 的完整链接；短链主要用于下载，元数据可能不完整。

### 4.3 抖音

当前可用命令：

- `opencli douyin search <query> -f json`
- `opencli douyin user-videos <sec_uid> -f json`
- `opencli douyin videos -f json`

未发现明确的“单条视频 URL 详情/下载”命令。

结论：抖音不能按 B 站/小红书的确定性实现直接承诺完整 MVP。需要先做能力探测与降级：

- 识别抖音链接，创建任务。
- 尝试从 URL 中解析 `aweme_id`、`sec_uid` 或分享页信息。
- 若无法用现有 opencli 获取单条视频详情，则保存为“待解析/仅链接卡片”，并给出 warning。
- 可作为后续补 adapter 的独立任务。

## 5. 范围

### 5.1 本次必须做

- 新增平台识别层，支持 `twitter/x`、`bilibili`、`xiaohongshu`、`douyin`。
- 数据模型新增平台字段，但兼容现有帖子：
  - `platform`: `x` / `bilibili` / `xiaohongshu` / `douyin`
  - `externalId`: 平台内 ID，例如 tweetId、bvid、noteId、awemeId
  - `contentType`: `post` / `video` / `note` / `article`
  - `rawMeta`: 平台原始 metadata 的安全子集
  - `transcript`: 字幕/转写/平台总结文本，可为空
  - `downloadStatus`: `success` / `partial` / `failed` / `skipped`
- `/api/add` 根据链接自动识别平台，并走对应 importer。
- 任务进度阶段升级为多平台通用：
  - pending
  - detecting
  - fetching
  - downloading
  - transcribing
  - writing
  - ai
  - done / error
- 前端添加区文案从“X/Twitter 链接”改为“粘贴 X / B站 / 小红书 / 抖音链接”。
- 卡片显示平台 badge，例如 `X`、`Bilibili`、`小红书`、`抖音`。
- B 站：实现完整导入闭环。
- 小红书：实现 note + download 的闭环，允许部分失败。
- 抖音：实现平台识别与降级保存，若现有 opencli 能拿到数据则保存；不能拿到则给 warning，不阻断整个产品。

### 5.2 本次不做

- 不做云端同步。
- 不做批量导入。
- 不做自动登录流程。
- 不强行绕过平台限制。
- 不做完整 ASR 管线，除非当前平台本身返回字幕/总结；后续可加 `ffmpeg + ASR`。
- 不承诺抖音单条视频完整下载，除非审核时发现本机已有稳定命令。

## 6. 数据模型升级

当前 `data/posts.json` 为 v2。建议升级到 v3。

### 6.1 v3 结构

```json
{
  "version": 3,
  "topics": [],
  "posts": [
    {
      "uid": "seedance2.0__bilibili__BVxxxx",
      "id": "seedance2.0__bilibili__BVxxxx",
      "topic": "seedance2.0",
      "platform": "bilibili",
      "externalId": "BVxxxx",
      "contentType": "video",
      "title": "视频标题",
      "author": "UP 主",
      "handle": "UP 主",
      "published": "发布时间",
      "body": "AI 生成的中文说明/摘要",
      "originalText": "平台标题、简介、字幕或总结",
      "summary": "摘要",
      "keywords": [],
      "sourceLink": "https://www.bilibili.com/video/BVxxxx",
      "mediaPath": "data/media/bilibili_BVxxxx_1.mp4",
      "mediaName": "bilibili_BVxxxx_1.mp4",
      "imagePath": "",
      "transcript": "字幕或官方总结",
      "downloadStatus": "success",
      "rawMeta": {}
    }
  ]
}
```

### 6.1.1 rawMeta 与 transcript 体积限制

`rawMeta` 只保存平台原始返回中的安全小字段，不允许把完整平台 JSON 直接塞入 `data/posts.json`。

建议白名单：

- 通用：`title`、`author`、`duration`、`published`、`description`、`stats`、`canonicalUrl`
- Bilibili：`bvid`、`aid`、`cid`、`owner`、`duration`、`stat`、`pic`
- 小红书：`noteId`、`title`、`desc`、`author`、`likedCount`、`collectedCount`、`commentCount`
- 抖音：`awemeId`、`desc`、`author`、`shareUrl`

`transcript` 设硬上限，建议 16KB。超出时截断并在 `warnings` 中记录；后续如果需要完整材料，再扩展为 `data/transcripts/<uid>.txt` 外部文件。

### 6.2 迁移规则 v2 → v3

- 如果 `version < 3`：
  - 给旧 X/Twitter 内容补：
    - `platform: "x"`
    - `externalId: tweetId || uid`
    - `contentType: "post"`
    - `downloadStatus`: 根据 `mediaPath/imagePath` 推断为 `success` 或 `skipped`
    - `rawMeta: {}`
    - `transcript: ""`
- 旧 `uid/id` 可以保持不变，避免破坏现有前端聚焦。
  - 写回 `version: 3`。
  - 首次迁移备份为 `data/posts.v2.bak.json`。
  - 迁移后旧 X/Twitter 内容的去重必须按 `(topic, platform, externalId)` 命中，不能只按 `uid` 字符串判断。

### 6.3 新内容 UID

新平台内容使用：

```text
uid = <topic>__<platform>__<externalId>
```

去重键：

```text
(topic, platform, externalId)
```

同一平台同一内容在同一课题下不可重复；跨课题允许重复收藏。

注意：旧 X/Twitter 内容可以保留原有 `uid=id=<topic>__<tweetId>`，新平台内容用 `<topic>__<platform>__<externalId>`。两种 uid 形态可以并存，但所有 importer 的去重逻辑必须统一使用 `(topic, platform, externalId)`。

## 7. 平台识别

新增函数：

```python
detect_platform(url) -> {
  "platform": "bilibili" | "xiaohongshu" | "douyin" | "x",
  "externalId": "...",
  "canonicalUrl": "..."
}
```

识别规则：

- `x.com` / `twitter.com` → `x`
- `bilibili.com/video/BV...`、`b23.tv/...` → `bilibili`
- `xiaohongshu.com`、`xhslink.com` → `xiaohongshu`
- `douyin.com`、`v.douyin.com`、`iesdouyin.com` → `douyin`

短链可先把原 URL 原样传给 opencli；如果 importer 能解析 canonical，再更新。

## 8. Importer 设计

后端从 `process_add(task_id, url, topic)` 改为：

```python
process_add(task_id, url, topic):
  detected = detect_platform(url)
  importer = get_importer(detected.platform)
  post = importer.import_url(url, topic, task_id)
```

保留现有 X/Twitter importer，不要重写其稳定逻辑。

### 8.0 通用 importer 约定

#### 8.0.1 短链解析

新增 `resolve_redirect(url)`：

- 对 `b23.tv`、`xhslink.com`、`v.douyin.com` 等短链，先跟随重定向拿 canonical URL。
- 若解析失败，保留原 URL 继续尝试 importer，并记录 warning。

#### 8.0.2 下载文件收集

多平台 opencli download 命令通常只返回 `status/size`，不稳定返回本地文件路径。因此不要依赖 JSON 中的路径字段。

统一实现：

```python
collect_downloaded_files(output_dir, before_snapshot=None) -> list[path]
```

策略：

- download 前记录输出目录已有文件。
- download 后 glob 扫描新增文件。
- 按扩展名判断主媒体：
  - 视频：`.mp4`、`.mov`、`.m4v`
  - 图片：`.jpg`、`.jpeg`、`.png`、`.webp`
- 只把成功存在的本地文件映射到 `mediaPath` / `imagePath`。
- download 命令 exit code 为 0 也要逐项检查返回 JSON 的 `status`，失败项进入 warning。

### 8.1 X/Twitter importer

现有逻辑基本保留：

- `opencli twitter thread`
- 媒体直链下载
- AI 加工

仅补平台字段。

### 8.2 Bilibili importer

流程：

1. `detecting`: 识别平台与 bvid/URL。
2. `fetching`: `opencli bilibili video <url> -f json --window background`
3. `downloading`: 优先保存封面图；整片下载作为可选能力，使用低风险质量与熔断。
4. `transcribing`: 优先：
   - `opencli bilibili subtitle <url> -f json`
   - 如果无字幕，再尝试 `opencli bilibili summary <url> -f json`
5. `writing`: 写入原始卡片。
6. `ai`: 用标题、简介、字幕/总结生成中文正文、摘要、关键词。

媒体文件处理：

- B 站视频可能很大，不应默认强制下载整片作为 MVP 成功条件。
- MVP 以“元数据 + 封面 + 字幕/总结 + 卡片入库”为完整闭环。
- 如果要下载整片，建议用 `opencli bilibili download <url> --quality 480p --output ...`，并设置超时/失败 warning；下载失败不阻断卡片保存。
- opencli download 返回的成功文件需要通过 `collect_downloaded_files()` 找到本地文件并映射到 `mediaPath`。
- 若下载失败但元数据成功，仍保存卡片，`downloadStatus="failed"`，warning 显示。

### 8.3 Xiaohongshu importer

流程：

1. `fetching`: `opencli xiaohongshu note <url> -f json --window background`
2. `downloading`: `opencli xiaohongshu download <url> --output data/media/xiaohongshu/<externalId> -f json --window background`
3. `writing`: 保存标题、作者、正文、互动数据和媒体。
4. `ai`: 如果笔记正文足够，生成中文摘要和关键词。

注意：

- 小红书链接如果缺少 `xsec_token`，`note` 可能失败；这时可尝试只运行 `download`。
- `download` 部分成功也应保存卡片并记录 warning。

### 8.4 Douyin importer

MVP 降级策略：

1. `detecting`: 识别为 `douyin`。
2. `fetching`: 尝试从 URL 解析 aweme_id 或 sec_uid。
3. 如果能从现有 opencli 命令获得单条信息，则保存完整卡片。
4. 如果不能：
   - 写入一条“待解析”卡片：
     - `title`: `抖音视频待解析`
     - `sourceLink`: 原链接
     - `platform`: `douyin`
     - `externalId`: 解析出的 aweme_id 或 slug
     - `downloadStatus`: `skipped`
     - `warnings`: `当前 opencli 未提供稳定的抖音单条视频详情/下载命令，已先保存链接。`
   - 任务 `done`，不是 `error`。

这符合“能通过输入链接放置到产品中”的最低目标，但不假装完成了不可验证的抓取。

## 9. AI 加工策略

现有 `AI_PROMPT_TMPL` 需要平台通用化：

输入应包含：

- platform
- title
- author
- description/text
- transcript/summary
- sourceLink

输出仍为：

```json
{
  "title": "中文标题",
  "chinese": "中文正文",
  "summary": "两句话摘要",
  "keywords": ["关键词1", "关键词2", "关键词3"]
}
```

对于中文平台，不一定要“翻译”，更像是“整理成中文内容卡片”。

## 10. 前端改造

### 10.1 文案

改：

```text
粘贴 X/Twitter 链接，回车添加
```

为：

```text
粘贴 X / B站 / 小红书 / 抖音链接，回车添加
```

按钮保持：

```text
添加到 <课题名>
```

### 10.2 平台 badge

在卡片头部或 media badge 附近显示：

- `X`
- `Bilibili`
- `小红书`
- `抖音`

### 10.3 任务阶段文案

新增：

- `detecting`: 正在识别平台
- `transcribing`: 正在获取字幕/总结

进度建议：

| stage | progress |
|---|---:|
| pending | 5 |
| detecting | 12 |
| fetching | 25 |
| downloading | 45 |
| transcribing | 65 |
| writing | 75 |
| ai | 88 |
| done | 100 |

## 11. 验收标准

### 11.1 基础兼容

- 原 X/Twitter 链接导入仍可用。
- 现有 23 条 X 内容仍显示在 `fable5`。
- `data/posts.json` 升级到 v3，旧数据不丢。
- `file:// index.html` 仍不受影响。

### 11.2 Bilibili

- 输入一个 B 站视频链接后：
  - 能识别为 `platform=bilibili`。
  - 能抓到标题/作者/链接。
  - 能保存一条卡片到当前 topic。
  - 如果视频下载或字幕失败，任务仍 done，并显示 warning。

### 11.3 小红书

- 输入一个小红书笔记链接后：
  - 能识别为 `platform=xiaohongshu`。
  - 能保存标题/正文/作者或可用字段。
  - 能保存下载成功的图片/视频。
  - 缺 token 或部分失败时，任务 done + warning。

### 11.4 抖音

- 输入抖音链接后：
  - 能识别为 `platform=douyin`。
  - 至少能创建一条带原链接的“待解析”卡片。
  - 不应让任务直接 error，除非链接本身无法识别。
  - warning 必须明确说明当前抓取能力限制。

### 11.5 前端

- 添加区文案支持四类平台。
- 任务进度条显示 detecting/transcribing 等新阶段。
- 卡片能显示平台 badge。

## 12. 风险与护栏

- 不要声称抖音完整支持，除非审核发现可稳定按单条链接抓取。
- 不要因为媒体下载失败而丢弃卡片。
- 不要把平台字段只放前端，必须持久化。
- 不要破坏 X/Twitter 现有链路。
- 不要在未验证的情况下删除或重写 `data/posts.json`。
- 不要把平台返回的超大原始 JSON 完整塞进 `rawMeta`；只保留安全小字段。
- B 站/小红书/抖音命令都依赖登录态，失败时要给出可读 warning。

## 13. 建议实施顺序

### Step 1: 数据与平台框架

- v2 → v3 迁移。
- `detect_platform`。
- `platform/externalId/contentType/downloadStatus/transcript/rawMeta` 字段。
- importer 抽象。
- X importer 回归验证。

### Step 2: Bilibili

- metadata + download + subtitle/summary。
- AI prompt 通用化。
- 前端 badge。

### Step 3: Xiaohongshu

- note + download。
- 部分失败 warning。

### Step 4: Douyin

- 先实现识别 + 降级卡片。
- 审核是否可利用现有 opencli 命令补完整抓取。

### Step 5: 验收

- 每个平台至少跑一条真实或可控链接。
- 若缺登录态或平台限制，记录为 warning，不静默失败。
