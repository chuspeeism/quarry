/* global React, Icon, PLATFORMS, PLATFORM_ORDER, platformVarColor, PfChip, typeMeta, initials, relTime */
const { createElement: hh } = React;

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

/* ---------------- grid card ---------------- */
function Card({ post, dense, onOpen }) {
  const pc = platformVarColor(post.platform);
  const onKey = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } };
  return hh("div", { className: "tv-card" + (dense ? " dense" : ""), onClick: onOpen, onKeyDown: onKey, role: "button", tabIndex: 0 },
    hh("div", { className: "tv-thumb-wrap" },
      hh(Thumb, { post }),
      hh(SourceLink, { post })
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
    )
  );
}

/* ---------------- list row ---------------- */
function Row({ post, onOpen }) {
  const p = PLATFORMS[post.platform] || PLATFORMS.x;
  const onKey = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOpen(); } };
  return hh("div", { className: "tv-row", onClick: onOpen, onKeyDown: onKey, role: "button", tabIndex: 0 },
    hh(Thumb, { post, mini: true }),
    hh("div", { className: "tv-row-main" },
      hh("div", { className: "t" }, post.title),
      hh("div", { className: "s" },
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
      hh(SourceLink, { post, variant: "row" })
    )
  );
}

/* ---------------- sidebar ---------------- */
function Sidebar({ topics, posts, activeTopic, setActiveTopic, platformFilter, togglePlatform,
                   typeFilter, toggleType, onNewTopic, total }) {
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
        topics.map((t) => hh("button", {
          key: t.id, type: "button",
          className: "tv-topic" + (t.id === activeTopic ? " on" : ""),
          onClick: () => setActiveTopic(t.id),
        },
          hh("span", { className: "tv-topic-dot" }),
          hh("span", { className: "tv-topic-name" }, t.name),
          hh("span", { className: "tv-topic-count" }, t.count)
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

Object.assign(window, { Thumb, Card, Row, Sidebar, StatChips, StatIcon, statEntries, fmtCount });
