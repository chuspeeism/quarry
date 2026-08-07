/* global React, Icon, PLATFORMS, PLATFORM_ORDER, platformVarColor, PfChip, typeMeta, initials, relTime */
const { createElement: hh } = React;

function excerpt(post, n) {
  const s = (post.summary || post.body || post.originalText || "").replace(/\s+/g, " ").trim();
  return s.length > n ? s.slice(0, n) + "…" : s;
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
        hh("span", null, post.keywords.length ? `${post.keywords.length} 关键词` : "笔记")
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

Object.assign(window, { Thumb, Card, Row, Sidebar });
