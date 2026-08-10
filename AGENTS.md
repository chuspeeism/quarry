# 给 Agent 的仓库须知

Quarry 是一个本地多平台内容采集库。**这个仓库只有代码，没有内容。** 收藏到的帖子、
视频、口播转写全部在仓库之外的内容层里。

## 内容层在哪

默认是主仓库同级的 `../vault/`，可用 `QUARRY_VAULT` 指到别处。不要自己拼路径，问它：

```bash
bin/quarry where
```

在 git worktree 里也能算对——路径解析见 [server/paths.py](server/paths.py)。

## 怎么读收藏的内容

用 `bin/quarry`（把 `bin/` 加进 `PATH` 后可直接叫 `quarry`）。它直接读内容层，
**不需要后端服务处于运行状态**。

```bash
quarry topics                          # 先看有哪些课题，拿 topic id
quarry search "提示词" --topic ae      # 全字段检索，覆盖标题/正文/摘要/原文/关键词/作者/口播转写
quarry search "灯光" --in transcript   # 只在口播转写里找
quarry list --topic fable5 --limit 10  # 按课题浏览，不做关键词匹配
quarry show <uid>                      # 单帖内容（不含口播，省上下文）
quarry show <uid> --full               # 附口播全文
quarry pack --topic fable5 --out /tmp/x.md   # 整个课题打包成一个文件
```

全部子命令都支持 `--json`，位置随意（`quarry topics --json` 和 `quarry --json topics` 等价）。
过滤参数：`--topic` `--platform` `--type` `--since` `--until` `--with-transcript`
`--limit` `--cursor` `--sort`。

### 取数原则

**先检索定位，再取单帖全文。不要整库读入。** 库会持续增长，`quarry search` 的返回
体量只与 `--limit` 相关，与库的总量无关；直接读 `posts.json` 或把所有 md 灌进上下文
会随库线性膨胀。

想绕开命令直接翻文件也可以，投影在 `<内容层>/agent/`：

```text
agent/topics.json                       课题清单
agent/index.jsonl                       一行一帖的轻量索引，可按行 grep
agent/topics/<课题 id>/<序号>-<标题>.md  单帖全文
```

## 需要知道的语义

- `agent/` 是 `data/posts.json` 的**只读派生投影**。改那里的 md 不会回写主数据，
  且会在下次重建时被覆盖。要改内容走前端或 `PATCH /api/posts/<uid>`。
- 单帖 md 里的**口播全文不截断**。`posts.json` 的 `transcript` 字段有 16KB 上限，
  要完整转写就读投影或用 `quarry show --full`。库里有转写超过 4.5 万字的长视频。
- `transcriptSource` 三种取值意义不同：`asr` 有真实口播；`none` 是**已确认没有人声**
  （无声录屏、纯音乐），不要重试；空串是还没跑过转写。库里 27/39 条视频属于 `none`。
- 视频都抽了**关键帧**（均匀抽帧，4–12 张），路径在 `media.frames`，张数在 `frameCount`。
  纯文本消费方看不了视频，但能读这些静帧——很多这类内容的信息就在画面的文字卡上。
- `stats`（浏览/点赞/收藏/评论/分享）是**收藏那一刻的快照**，不随时间更新。
  引用数字时一并引用 `capturedAt`。
- `warnings` 非空表示采集时出过问题，媒体或转写可能缺失。
- `rawMeta`（平台原始响应）不进投影，需要时用 `quarry show <uid> --json --raw-meta`。
- 检索是关键词子串匹配，不做同义扩展，也不跨语言（中文词查不到英文原文）。

## 投影没跟上时

主数据被外部改动过，或投影目录被删了：

```bash
quarry reindex
```

全量重建，幂等。后端服务启动时也会自检一次。

## 改代码时

- 产品层与内容层严格分离，任何采集到的内容都不进这个仓库。
- 依赖限定在 python3 标准库，前端零构建（浏览器里 Babel standalone 直接编译 jsx）。
- 数据变更的唯一出口是 `server/server.py` 的 `save_posts()`，投影挂在它后面。
  新增写入路径时不要绕开它。
- 改了单帖 md 的渲染逻辑，要把 `server/projection.py` 的 `RENDER_VERSION` 加一，
  否则旧文件不会被重渲。
