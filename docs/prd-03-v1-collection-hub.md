# V1「全平台收集中台」升级说明

> 日期：2026-08-04
> 目标：把 TopicVault 从"X 收藏器 + 部分平台元数据"升级为全平台素材收集中台——任何链接进来，产出统一的本地素材资产（视频 + 音频 + 字幕 + 口播词），并且库可增可删可改。

## 本次新增能力

### 1. 抖音真实抓取（原来只存链接占位）
- 策略 A：链接带 `sec_uid`（用户页 modal 链接）→ `opencli douyin user-videos` 精确匹配，可同时拿热门评论（写入卡片"补充说明"）
- 策略 B：`/video/<id>` 或 `v.douyin.com` 短链 → iesdouyin 分享页 `_ROUTER_DATA` 解析（移动端 UA，无需登录态）
- 全部失败 → 降级为链接占位卡片（原有行为），warning 说明原因，可删除后重收

### 2. B 站视频本体下载（原来只下封面）
- `opencli bilibili download`（底层 yt-dlp）下载视频到 `data/media/bilibili/<bvid>/`
- 字幕升级为带时间轴格式；无字幕时官方 AI 总结兜底；再无 → 本地 ASR 转写

### 3. 统一 ASR 转写管线（`server/asr.py`，四件套产出）
任何平台的视频类内容，自动产出与手工习惯一致的"四件套"：
```
<视频>.mp4 + <视频>.m4a + <视频>.srt + <视频>.口播词.md
```
- 引擎：火山豆包 ASR（标准版，毫秒级时间戳）；网络失败自动落 Groq Whisper
- transcript 以 `[MM:SS → MM:SS] 文本` 时间轴格式入库，可全文检索
- 无人声（纯音乐）自动跳过并记 warning；`TV_ASR=none` 全局关闭
- AI 中文卡片的材料 = 正文 + 口播转写（视频内容的摘要质量因此大幅提升）

### 4. 库的增删改（原来只进不出）
- `DELETE /api/posts/<uid>?media=1` 删帖（可连本地媒体文件一起删，自动清空目录）
- `PATCH /api/posts/<uid>` 编辑 title/body/summary/keywords/supplement
- `PATCH /api/topics/<id>` 课题改名/改描述；`DELETE /api/topics/<id>?force=1` 删课题
- `POST /api/posts/<uid>/retranscribe` 对已入库帖子补跑/重跑转写

### 5. 批量导入
- `POST /api/add` 支持 `{urls:[...]}` 或多行粘贴，逐条建任务返回 `{tasks:[{url,taskId}]}`
- 单条失败不阻塞其他条；`TV_IMPORT_CONCURRENCY`（默认 2）控制并发，避免浏览器桥争抢

### 6. 前端（Frost）
- 详情页：中文/原文/转写 三档切换；编辑弹窗；删除（含"同时删媒体"确认）
- 收藏弹窗：多行粘贴批量收藏，逐条进度
- 搜索覆盖口播转写全文

## 新增环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `TV_ASR` | `volc` | `volc`（失败自动落 groq）/ `groq` / `none` |
| `TV_ASR_MAX_DURATION` | `3600` | 超过该秒数的视频跳过自动转写 |
| `TV_IMPORT_CONCURRENCY` | `2` | 导入任务并发数 |

ASR 凭证沿用 video-speech-content skill：`~/.hermes/credentials/volcengine-asr.json`（火山）与 `groq-asr.json`（Groq）。

## 已知边界

- 火山 ASR 域名（openspeech.bytedance.com）会被部分 VPN 的 fake-IP 劫持导致 SSL 中断，此时自动落 Groq（免费层单文件 25MB，管线上传的是压缩 mp3，一般不超）
- 抖音分享页解析依赖 iesdouyin 页面结构，风控变化时降级为占位卡片
- 抖音策略 A 只覆盖作者最近 20 条作品（opencli 上限）
- X 媒体仍存平层 `data/media/<tweetId>_<n>.*`（历史兼容）；抖音/B站按 `data/media/<平台>/<id>/` 归目录

## 验收记录（2026-08-04）

- X：Minimax H3 教程帖（@seiiiiiiiiiiru）→ 视频落盘 + AI 中文卡片；纯音乐视频 ASR 正确跳过 ✅
- 抖音：用户自己的视频 → 分享页解析 + 34MB 视频下载 + Groq 转写 115 句 + 四件套齐全 ✅
- B站：短视频 → 视频本体 17MB 下载 + 平台字幕入库 ✅
- CRUD：课题建/改/删、帖子编辑、删除连媒体清理 ✅
- 批量：1 条有效 + 1 条无效链接，各自独立完成/报错 ✅
