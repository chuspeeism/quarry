/* global React, Icon, PLATFORMS, PLATFORM_ORDER, platformVarColor, PfChip, typeMeta, initials, relTime */
const { createElement: hh, useState, useEffect, useRef } = React;

function excerpt(post, n) {
  const s = (post.summary || post.body || post.originalText || "").replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n) + "…" : s;
}

/* ---------------- 互动数据（收藏时点快照）---------------- */
// 图标沿用 tv-icons.jsx 的 24-grid stroke 风格，在本文件内补充，避免动图标库。
const STAT_ICON_PATHS = {
  views: "M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12ZM12 14.6a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2Z",
  likes: "M12 20.2S3.6 15.2 3.6 9.7c0-2.5 1.9-4.5 4.3-4.5 1.7 0 3.2 1 4.1 2.5.9-1.5 2.4-2.5 4.1-2.5 2.4 0 4.3 2 4.3 4.5 0 5.5-8.4 10.5-8.4 10.5Z",
  collects: "M7 3.5h10v17l-5-3.4-5 3.4Z",
  comments: "M4 5.5h16v11h-9.5L5 20v-3.5H4Z",
  shares: "M13.5 5.5 21 12l-7.5 6.5v-4C9 14.5 5.5 16.5 3 20c.5-6.5 4.5-10.5 10.5-11Z",
};
const STAT_ORDER = ["views", "likes", "collects", "comments", "shares"];
const STAT_LABELS = { views: "浏览", likes: "点赞", collects: "收藏", comments: "评论", shares: "分享" };

function StatIcon({ name, size = 13 }) {
  return hh("svg", {
    width: size, height: size, viewBox: "0 0 24 24",
    fill: "none", stroke: "currentColor",
    strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round",
  }, hh("path", { d: STAT_ICON_PATHS[name] || "" }));
}

function fmtCount(n) {
  if (typeof n !== "number" || !isFinite(n)) return "";
  if (n >= 100000000) return (n / 100000000).toFixed(1).replace(/\.0$/, "") + "亿";
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, "") + "万";
  return String(n);
}

// stats -> [{key,label,value}]，只保留真实抓到的项，顺序固定：浏览/点赞/收藏/评论/分享
function statEntries(stats) {
  if (!stats || typeof stats !== "object") return [];
  return STAT_ORDER
    .filter((k) => typeof stats[k] === "number" && isFinite(stats[k]))
    .map((k) => ({ key: k, label: STAT_LABELS[k], value: stats[k] }));
}

// 一排统计小徽章；max 限制条数（卡片空间小），title 悬浮显示完整含义
function StatChips({ stats, max, className }) {
  const list = statEntries(stats).slice(0, max || STAT_ORDER.length);
  if (!list.length) return null;
  return hh("div", { className: "tv-stats" + (className ? " " + className : "") },
    list.map((s) => hh("span", { key: s.key, className: "tv-stat", title: s.label + " " + s.value.toLocaleString() },
      hh(StatIcon, { name: s.key }), fmtCount(s.value))));
}

/* ---------------- 下载完整度（内容没存全时的可见提示）---------------- */
// downloadStatus 非 success 就说明这条内容没抓全，最典型的是「视频本体下载失败、只剩封面」：
// 卡片看起来跟正常图片帖一模一样，用户点开播放才发现没有正片。这里统一挂提示。
const WARN_ICON_PATH = "M12 4.2 2.6 20.2h18.8L12 4.2ZM12 10.2v4.3M12 17.3h.01";

function WarnIcon({ size = 11 }) {
  return hh("svg", {
    width: size, height: size, viewBox: "0 0 24 24",
    fill: "none", stroke: "currentColor",
    strokeWidth: 1.9, strokeLinecap: "round", strokeLinejoin: "round",
  }, hh("path", { d: WARN_ICON_PATH }));
}

const DOWNLOAD_ISSUES = {
  partial: { tone: "warn", label: "内容不完整", detail: "部分媒体没能下载下来，本地只存了一部分。" },
  failed: { tone: "bad", label: "下载失败", detail: "媒体全部下载失败，本地没有留下文件。" },
  skipped: { tone: "mute", label: "未存媒体", detail: "这条内容没有下载任何媒体文件。" },
};

// 返回 {tone,label,detail} 或 null（内容完整、不需要提示）
function downloadIssue(post) {
  const issue = DOWNLOAD_ISSUES[post.downloadStatus];
  if (!issue) return null; // success 与未知状态都不提示
  const isVideo = post.sourceType === "video";
  // 纯文字帖本来就没有媒体，skipped 是正常状态，不算缺失
  if (post.downloadStatus === "skipped" && !isVideo) return null;
  if (isVideo && !post.hasVideo) {
    return {
      tone: post.downloadStatus === "failed" ? "bad" : "warn",
      label: "缺视频本体",
      detail: post.hasImage
        ? "视频本体没下载成功，本地只有封面图，无法播放。"
        : "视频本体没下载成功，本地没有留下可播放的文件。",
    };
  }
  return issue;
}

function DownloadBadge({ post, variant }) {
  const issue = downloadIssue(post);
  if (!issue) return null;
  return hh("span", {
    className: "tv-dlbadge " + issue.tone + (variant ? " " + variant : ""),
    title: issue.detail,
  }, hh(WarnIcon, { size: variant === "row" ? 10 : 11 }), issue.label);
}

/* one-click open-original link (stops card click) */
function SourceLink({ post, variant }) {
  if (!post.sourceLink) return null;
  return hh("a", {
    className: "tv-srclink" + (variant ? " " + variant : ""),
    href: post.sourceLink, target: "_blank", rel: "noreferrer",
    title: "打开原帖", "aria-label": "打开原帖",
    onClick: (e) => e.stopPropagation(),
  }, hh(Icon, { name: "external", size: 14 }));
}

/* ---------------- media thumbnail (real media + type-aware placeholder) ---------------- */
// 完整接入后端后，优先用真实图片/视频首帧做封面；没有真实媒体时回退到原占位图。
function thumbMedia(post, cls) {
  if (post.imageUrl) {
    return hh("img", { className: cls, src: post.imageUrl, alt: "", loading: "lazy" });
  }
  if (post.mediaUrl) {
    return hh("video", { className: cls, src: post.mediaUrl + "#t=0.5", muted: true, playsInline: true, preload: "metadata" });
  }
  return null;
}

function Thumb({ post, mini }) {
  const tm = typeMeta(post.contentType);
  const pc = platformVarColor(post.platform);
  if (mini) {
    const media = thumbMedia(post, "tv-row-thumb-media");
    return hh("div", { className: "tv-row-thumb" + (tm.multi ? " is-gallery" : "") + (media ? " has-media" : ""), style: { "--pc": pc } },
      media,
      (media && tm.icon !== "play") ? null
        : hh("div", { className: "mini", style: media ? { zIndex: 1 } : null }, hh(Icon, { name: tm.icon, size: 16, fill: tm.icon === "play" })),
      tm.multi ? hh("span", { className: "tv-row-count" }, post.imageCount) : null
    );
  }
  const p = PLATFORMS[post.platform] || PLATFORMS.x;
  const media = thumbMedia(post, "tv-thumb-media");
  const cls = "tv-thumb" + (tm.multi ? " is-gallery" : "") + (tm.textCard ? " is-text" : "") + (media ? " has-media" : "");
  return hh("div", { className: cls, style: { "--pc": pc } },
    media,
    hh("span", { className: "tv-thumb-pf" }, hh(PfChip, { id: post.platform }), p.label),
    hh("span", { className: "tv-thumb-type" },
      tm.multi ? [hh(Icon, { key: "i", name: "layers", size: 11 }), " " + post.imageCount + " 图"] : tm.label),
    tm.textCard
      ? hh("div", { className: "tv-thumb-quote" },
          hh(Icon, { name: "text", size: 16, style: { opacity: .55 } }),
          hh("p", null, excerpt(post, 86)))
      : (media && tm.icon !== "play")
        ? null
        : hh("div", { className: "tv-thumb-icon" },
            hh("div", { className: "ring" }, hh(Icon, { name: tm.icon, size: 22, fill: tm.icon === "play" }))),
    !tm.textCard && !media && post.mediaName ? hh("div", { className: "tv-thumb-file" }, post.mediaName) : null
  );
}

/* ---------------- 单条删除的公共部件 ---------------- */
// 帖子在内容层里的本地文件数，和后端 _delete_post_files 清理的是同一批。
// 用来给确认层报出「会连带删掉几个文件」，一个文件都没有时直接不显示这个选项。
// 关键帧是一整个目录，按目录里的帧数计——一条视频往往 4–12 张，不计的话数字会明显偏小。
function localFileCount(post) {
  const files = [post.mediaPath, post.imagePath, post.audioPath,
                 post.transcriptSrtPath, post.transcriptMdPath].filter(Boolean);
  return files.length + (post.framesDir ? (post.frameCount || 1) : 0);
}

/* ---------------- 卡片内联删除确认（盖在卡片/行上，替代 window.confirm） ---------------- */
// 删除直接改写 posts.json，没有回滚点，所以确认层里必须先勾「我确认」才解锁删除按钮；
// 确认层会盖住卡片本身，因此把标题也列出来，避免点错卡还看不出删的是哪条。
// 删除失败时不关确认层，原地显示后端返回的错误，用户可以重试或取消。
function DeleteConfirm({ post, variant, onCancel, onDelete }) {
  const fileCount = localFileCount(post);
  const [ack, setAck] = useState(false);
  const [withMedia, setWithMedia] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const cancelRef = useRef(null);
  // 打开时把焦点放到「取消」上：既是安全默认项，也让 Esc 能落在确认层里被接住
  useEffect(() => { cancelRef.current && cancelRef.current.focus(); }, []);

  async function go(ev) {
    ev.stopPropagation();
    if (busy || !ack) return;
    setBusy(true); setErr("");
    try {
      await onDelete(post, withMedia && fileCount > 0);
    } catch (e) {
      setBusy(false);
      setErr((e && e.message) || "删除失败");
    }
  }

  return hh("div", {
      className: "tv-confirm" + (variant ? " " + variant : ""),
      onClick: (e) => e.stopPropagation(),
      onKeyDown: (e) => { e.stopPropagation(); if (e.key === "Escape" && !busy) onCancel(); },
    },
    hh("div", { className: "tv-confirm-msg" },
      hh("span", { className: "ic" }, hh(Icon, { name: "trash", size: 14 })),
      hh("b", null, "删除这条收藏？")),
    hh("div", { className: "tv-confirm-title", title: post.title }, "「" + post.title + "」"),
    hh("label", { className: "tv-confirm-opt strong" },
      hh("input", { type: "checkbox", checked: ack, disabled: busy,
        onChange: (e) => setAck(e.target.checked) }),
      "我确认删除，不可恢复"),
    fileCount ? hh("label", { className: "tv-confirm-opt" },
      hh("input", { type: "checkbox", checked: withMedia, disabled: busy,
        onChange: (e) => setWithMedia(e.target.checked) }),
      "同时删除 " + fileCount + " 个本地文件") : null,
    err ? hh("div", { className: "tv-confirm-err", title: err }, err) : null,
    hh("div", { className: "tv-confirm-acts" },
      hh("button", { ref: cancelRef, className: "tv-pcard-act", disabled: busy,
        onClick: (e) => { e.stopPropagation(); onCancel(); } }, "取消"),
      hh("button", { className: "tv-pcard-act danger solid", disabled: busy || !ack, onClick: go },
        busy ? "删除中…" : "删除"))
  );
}

/* ---------------- grid card ---------------- */
function Card({ post, dense, onOpen, onDelete }) {
  const pc = platformVarColor(post.platform);
  const [confirming, setConfirming] = useState(false);
  const onKey = (e) => {
    if (confirming) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); }
  };
  return hh("div", {
      className: "tv-card" + (dense ? " dense" : "") + (confirming ? " is-confirming" : ""),
      onClick: confirming ? undefined : onOpen, onKeyDown: onKey, role: "button", tabIndex: 0,
    },
    hh("div", { className: "tv-thumb-wrap" },
      hh(Thumb, { post }),
      // 缺内容徽章挂左下、动作簇挂右下，各占一角互不遮挡
      hh(DownloadBadge, { post, variant: "card" }),
      hh("div", { className: "tv-card-acts" },
        onDelete ? hh("button", {
          className: "tv-card-del", title: "删除这条收藏", "aria-label": "删除这条收藏",
          onClick: (e) => { e.stopPropagation(); setConfirming(true); },
        }, hh(Icon, { name: "trash", size: 14 })) : null,
        hh(SourceLink, { post })
      )
    ),
    hh("div", { className: "tv-card-body" },
      hh("div", { className: "tv-card-author" },
        hh("span", { className: "tv-ava", style: { "--pc": pc, background: pc } }, initials(post.author, post.handle)),
        hh("span", { style: { minWidth: 0 } },
          hh("div", { className: "nm" }, post.author),
          post.handle ? hh("div", { className: "hd" }, post.handle) : null
        )
      ),
      hh("h3", { className: "tv-card-title" }, post.title),
      hh(StatChips, { stats: post.stats, max: 4, className: "card" }),
      hh("div", { className: "tv-card-foot" },
        post.keywords.length
          ? hh("span", { className: "tv-kw" }, hh(Icon, { name: "tag", size: 12 }), `${post.keywords.length} 关键词`)
          : hh("span", { className: "tv-kw" }, hh(Icon, { name: "doc", size: 12 }), "笔记"),
        hh("span", { className: "when" }, relTime(post.collectedAt))
      )
    ),
    confirming ? hh(DeleteConfirm, { post, onCancel: () => setConfirming(false), onDelete }) : null
  );
}

/* ---------------- list row ---------------- */
function Row({ post, onOpen, onDelete }) {
  const p = PLATFORMS[post.platform] || PLATFORMS.x;
  const [confirming, setConfirming] = useState(false);
  const onKey = (e) => {
    if (confirming) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); }
  };
  return hh("div", {
      className: "tv-row" + (confirming ? " is-confirming" : ""),
      onClick: confirming ? undefined : onOpen, onKeyDown: onKey, role: "button", tabIndex: 0,
    },
    hh(Thumb, { post, mini: true }),
    hh("div", { className: "tv-row-main" },
      hh("div", { className: "t" }, post.title),
      hh("div", { className: "s" },
        hh(DownloadBadge, { post, variant: "row" }),
        hh("span", null, post.author),
        hh("span", { className: "dot" }),
        hh("span", null, post.keywords.length ? `${post.keywords.length} 关键词` : "笔记"),
        statEntries(post.stats).length ? hh("span", { className: "dot" }) : null,
        hh(StatChips, { stats: post.stats, max: 3, className: "row" })
      )
    ),
    hh("div", { className: "tv-row-side" },
      hh("span", { className: "pf" }, hh(PfChip, { id: post.platform }), p.label),
      hh("span", { className: "when" }, relTime(post.collectedAt)),
      onDelete ? hh("button", {
        className: "tv-row-del", title: "删除这条收藏", "aria-label": "删除这条收藏",
        onClick: (e) => { e.stopPropagation(); setConfirming(true); },
      }, hh(Icon, { name: "trash", size: 14 })) : null,
      hh(SourceLink, { post, variant: "row" })
    ),
    confirming ? hh(DeleteConfirm, { post, variant: "row", onCancel: () => setConfirming(false), onDelete }) : null
  );
}

/* ---------------- pending collect card（收藏进行中的占位卡） ---------------- */
// 粘贴链接后立即插入列表顶部：抓取/AI 的实时进度都显示在卡片里，
// 完成后由 App 刷新替换成真实帖子卡；失败则原地显示错误 + 重试/移除。
function shortLink(u) {
  const s = String(u || "").replace(/^https?:\/\//, "");
  return s.length > 44 ? s.slice(0, 28) + "…" + s.slice(-13) : s;
}

function PendingCard({ item, dense, onRetry, onRemove }) {
  const pid = item.platform;
  const p = pid ? PLATFORMS[pid] : null;
  const pc = pid ? platformVarColor(pid) : "var(--x)";
  const isErr = item.status === "error";
  const pct = Math.max(0, Math.min(100, Math.round(item.progress || 0)));
  return hh("div", { className: "tv-card tv-pcard" + (dense ? " dense" : "") + (isErr ? " is-error" : "") },
    hh("div", { className: "tv-thumb-wrap" },
      hh("div", { className: "tv-thumb", style: { "--pc": pc } },
        isErr ? null : hh("div", { className: "tv-pcard-sheen" }),
        p ? hh("span", { className: "tv-thumb-pf" }, hh(PfChip, { id: pid }), p.label) : null,
        hh("span", { className: "tv-thumb-type" }, isErr ? "失败" : "收藏中"),
        hh("div", { className: "tv-thumb-icon" },
          hh("div", { className: "ring" },
            hh(Icon, { name: isErr ? "close" : "refresh", size: 22,
              style: isErr ? { color: "#e0563f" } : { animation: "spin 1.1s linear infinite" } })))
      )
    ),
    hh("div", { className: "tv-card-body" },
      hh("div", { className: "tv-pcard-url", title: item.url }, shortLink(item.url)),
      isErr
        ? hh("div", { className: "tv-pcard-err" }, item.message || "收藏失败")
        : hh("div", null,
            hh("div", { className: "tv-batch-bar" },
              hh("span", { className: "fill", style: { width: Math.max(4, pct) + "%" } })),
            hh("div", { className: "tv-pcard-msg" }, item.message || "处理中…")),
      hh("div", { className: "tv-card-foot tv-pcard-foot" },
        isErr
          ? hh(React.Fragment, null,
              hh("button", { className: "tv-pcard-act", onClick: () => onRetry(item.key) }, "重试"),
              hh("button", { className: "tv-pcard-act danger", onClick: () => onRemove(item.key) }, "移除"))
          : hh(React.Fragment, null,
              hh("span", { className: "tv-kw" },
                hh(Icon, { name: "refresh", size: 12, style: { animation: "spin 1.1s linear infinite" } }), pct + "%"),
              hh("span", { className: "when" }, "后台抓取中"))
      )
    )
  );
}

function PendingRow({ item, onRetry, onRemove }) {
  const pid = item.platform;
  const p = pid ? PLATFORMS[pid] : null;
  const pc = pid ? platformVarColor(pid) : "var(--x)";
  const isErr = item.status === "error";
  const pct = Math.max(0, Math.min(100, Math.round(item.progress || 0)));
  return hh("div", { className: "tv-row tv-prow" + (isErr ? " is-error" : "") },
    hh("div", { className: "tv-row-thumb", style: { "--pc": pc } },
      hh("div", { className: "mini" },
        hh(Icon, { name: isErr ? "close" : "refresh", size: 16,
          style: isErr ? { color: "#e0563f" } : { animation: "spin 1.1s linear infinite" } }))),
    hh("div", { className: "tv-row-main" },
      hh("div", { className: "t tv-pcard-url", title: item.url }, shortLink(item.url)),
      isErr
        ? hh("div", { className: "tv-pcard-err" }, item.message || "收藏失败")
        : hh("div", null,
            hh("div", { className: "tv-batch-bar" },
              hh("span", { className: "fill", style: { width: Math.max(4, pct) + "%" } })),
            hh("div", { className: "tv-pcard-msg" }, item.message || "处理中…"))
    ),
    hh("div", { className: "tv-row-side" },
      isErr
        ? hh(React.Fragment, null,
            hh("button", { className: "tv-pcard-act", onClick: () => onRetry(item.key) }, "重试"),
            hh("button", { className: "tv-pcard-act danger", onClick: () => onRemove(item.key) }, "移除"))
        : hh(React.Fragment, null,
            p ? hh("span", { className: "pf" }, hh(PfChip, { id: pid }), p.label) : null,
            hh("span", { className: "when" }, pct + "%"))
    )
  );
}

/* ---------------- sidebar ---------------- */
function Sidebar({ topics, posts, activeTopic, setActiveTopic, platformFilter, togglePlatform,
                   typeFilter, toggleType, onNewTopic, onRenameTopic, onDeleteTopic, total }) {
  const platCounts = {};
  PLATFORM_ORDER.forEach((id) => { platCounts[id] = posts.filter((p) => p.platform === id).length; });
  const types = [
    { id: "video", label: "视频", icon: "play" },
    { id: "gallery", label: "图集", icon: "layers" },
    { id: "image", label: "图片", icon: "image" },
    { id: "text", label: "文字", icon: "text" },
    { id: "article", label: "文章", icon: "doc" },
  ];
  const typeCounts = {};
  types.forEach((t) => { typeCounts[t.id] = posts.filter((p) => p.contentType === t.id).length; });

  return hh("aside", { className: "tv-side" },
    hh("div", { className: "tv-brand" },
      hh("div", { className: "tv-mark" }, hh(Icon, { name: "vault", size: 19 })),
      hh("div", { className: "tv-word" }, hh("b", null, "Quarry"), hh("span", null, "选题矿场"))
    ),
    hh("div", { className: "tv-side-scroll tv-scroll" },
      // topics
      hh("div", { className: "tv-sec" },
        hh("div", { className: "tv-sec-head" },
          hh("h4", null, "课题"),
          hh("button", { className: "tv-add", onClick: onNewTopic, title: "新建课题" }, hh(Icon, { name: "plus", size: 14 }))
        ),
        // 课题行 = 切换按钮 + 悬停才露出的重命名/删除（做成兄弟节点，避免按钮套按钮）
        topics.map((t) => hh("div", {
          key: t.id, className: "tv-topic-item" + (t.id === activeTopic ? " on" : ""),
        },
          hh("button", {
            type: "button",
            className: "tv-topic" + (t.id === activeTopic ? " on" : ""),
            onClick: () => setActiveTopic(t.id),
          },
            hh("span", { className: "tv-topic-dot" }),
            hh("span", { className: "tv-topic-name" }, t.name),
            hh("span", { className: "tv-topic-count" }, t.count)
          ),
          (onRenameTopic || onDeleteTopic) ? hh("span", { className: "tv-topic-acts" },
            onRenameTopic ? hh("button", {
              type: "button", className: "tv-topic-act",
              title: "重命名课题", "aria-label": "重命名课题「" + t.name + "」",
              onClick: () => onRenameTopic(t),
            }, hh(Icon, { name: "edit", size: 13 })) : null,
            onDeleteTopic ? hh("button", {
              type: "button", className: "tv-topic-act danger",
              title: "删除课题", "aria-label": "删除课题「" + t.name + "」",
              onClick: () => onDeleteTopic(t),
            }, hh(Icon, { name: "trash", size: 13 })) : null
          ) : null
        ))
      ),
      // platforms
      hh("div", { className: "tv-sec" },
        hh("div", { className: "tv-sec-head" }, hh("h4", null, "平台")),
        PLATFORM_ORDER.map((id) => {
          const p = PLATFORMS[id];
          const on = platformFilter.includes(id);
          return hh("button", {
            key: id, type: "button",
            className: "tv-filter" + (on ? " on" : ""),
            onClick: () => togglePlatform(id),
          },
            hh("span", { className: "tv-pf-chip" + (p.cjk ? " cjk" : ""), style: { background: p.color } }, p.mono),
            hh("span", { className: "tv-filter-name" }, p.label),
            on ? hh(Icon, { name: "check", size: 15, style: { color: "var(--accent)" } })
               : hh("span", { className: "tv-filter-count" }, platCounts[id])
          );
        })
      ),
      // types
      hh("div", { className: "tv-sec" },
        hh("div", { className: "tv-sec-head" }, hh("h4", null, "类型")),
        types.map((t) => {
          const on = typeFilter.includes(t.id);
          return hh("button", {
            key: t.id, type: "button",
            className: "tv-filter" + (on ? " on" : ""),
            onClick: () => toggleType(t.id),
          },
            hh("span", { style: { width: 20, display: "grid", placeItems: "center", color: "var(--muted)" } }, hh(Icon, { name: t.icon, size: 15, fill: t.icon === "play" })),
            hh("span", { className: "tv-filter-name" }, t.label),
            on ? hh(Icon, { name: "check", size: 15, style: { color: "var(--accent)" } })
               : hh("span", { className: "tv-filter-count" }, typeCounts[t.id])
          );
        })
      )
    ),
    hh("div", { className: "tv-side-foot" },
      hh("div", { className: "tv-store" }, hh(Icon, { name: "database", size: 14 })),
      hh("small", null, hh("b", null, `本地已沉淀 ${total} 条`), hh("br"), "保存在本机 · 不上云")
    )
  );
}

Object.assign(window, { Thumb, Card, Row, Sidebar, PendingCard, PendingRow, StatChips, StatIcon, statEntries, fmtCount,
                        WarnIcon, DownloadBadge, downloadIssue, DeleteConfirm, localFileCount });
