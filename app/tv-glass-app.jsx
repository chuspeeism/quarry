/* global React, ReactDOM, Icon, PLATFORMS, PLATFORM_ORDER, detectPlatform, Sidebar, Card, Row, PendingCard, PendingRow, Detail, CollectModal, NewTopicModal, TopicEditModal, TopicDeleteModal, useTweaks, TweaksPanel, TweakSection, TweakColor, TweakRadio */
const { createElement: e, useState, useEffect, useMemo, useRef, useCallback } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#46b24a",
  "defaultView": "\u7f51\u683c",
  "density": "\u5bbd\u677e"
}/*EDITMODE-END*/;

const SORTS = [
  { id: "recent", label: "最近收藏" },
  { id: "author", label: "按作者" },
  { id: "platform", label: "按平台" },
];

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const dense = t.density === "\u7d27\u51d1";

  const [topics, setTopics] = useState([]);
  const [posts, setPosts] = useState([]);
  const [activeTopic, setActiveTopic] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [offline, setOffline] = useState(false);

  // \u4ece\u540e\u7aef\u5b9e\u65f6\u62c9\u53d6\u8bfe\u9898 + \u5e16\u5b50\uff08\u4e00\u6b21\u62c9\u5168\u91cf\uff0c\u8bfe\u9898\u5207\u6362\u5728\u524d\u7aef\u672c\u5730\u7b5b\u9009\uff09\u3002
  const refresh = useCallback(async (preferTopic) => {
    const data = await window.TVApi.loadAll();
    setTopics(data.topics);
    setPosts(data.posts);
    setActiveTopic((prev) => {
      const want = preferTopic || prev;
      if (want && data.topics.some((tp) => tp.id === want)) return want;
      return data.topics[0] ? data.topics[0].id : null;
    });
    setLoaded(true);
    return data;
  }, []);

  // \u9996\u6b21\u52a0\u8f7d\uff1b\u540e\u7aef\u4e0d\u53ef\u7528\uff08\u670d\u52a1\u672a\u542f\u52a8 / \u7eaf\u9759\u6001\u6258\u7ba1\uff09\u65f6\u56de\u9000\u5230\u5185\u7f6e\u79bb\u7ebf\u5feb\u7167\u3002
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await refresh(localStorage.getItem("tv.activeTopic"));
      } catch (err) {
        if (!alive) return;
        console.warn("\u540e\u7aef\u52a0\u8f7d\u5931\u8d25\uff0c\u56de\u9000\u79bb\u7ebf\u5feb\u7167\uff1a", err);
        const seed = window.TV_DATA || { topics: [], posts: [] };
        setTopics(seed.topics);
        setPosts(seed.posts);
        setActiveTopic(seed.topics[0] ? seed.topics[0].id : null);
        setOffline(true);
        setLoaded(true);
      }
    })();
    return () => { alive = false; };
  }, [refresh]);

  useEffect(() => {
    if (activeTopic) localStorage.setItem("tv.activeTopic", activeTopic);
  }, [activeTopic]);

  const [query, setQuery] = useState("");
  const [platformFilter, setPlatformFilter] = useState([]);
  const [typeFilter, setTypeFilter] = useState([]);
  const [view, setView] = useState(t.defaultView === "\u5217\u8868" ? "list" : "grid");
  const [sort, setSort] = useState("recent");

  const [openIndex, setOpenIndex] = useState(-1);
  const [lang, setLang] = useState("zh");
  const [modal, setModal] = useState(null); // "collect" | "newtopic"
  const [topicAction, setTopicAction] = useState(null); // {kind:"rename"|"delete", topic}
  const [sortOpen, setSortOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const searchRef = useRef(null);

  // apply accent tweak to CSS
  useEffect(() => {
    document.documentElement.style.setProperty("--accent", t.accent);
  }, [t.accent]);
  // default view tweak
  useEffect(() => {
    if (openIndex < 0) setView(t.defaultView === "\u5217\u8868" ? "list" : "grid");
  }, [t.defaultView]);

  const topicsWithCount = useMemo(() =>
    topics.map((t) => ({ ...t, count: posts.filter((p) => p.topic === t.id).length })),
  [topics, posts]);

  const topicPosts = useMemo(() => posts.filter((p) => p.topic === activeTopic), [posts, activeTopic]);

  const visible = useMemo(() => {
    let list = topicPosts;
    if (platformFilter.length) list = list.filter((p) => platformFilter.includes(p.platform));
    if (typeFilter.length) list = list.filter((p) => typeFilter.includes(p.contentType));
    const q = query.trim().toLowerCase();
    if (q) list = list.filter((p) => [p.title, p.author, p.handle, p.body, p.summary, p.originalText, p.transcript, (p.keywords || []).join(" ")].join(" ").toLowerCase().includes(q));
    list = [...list];
    if (sort === "recent") list.sort((a, b) => b.collectedAt - a.collectedAt);
    else if (sort === "author") list.sort((a, b) => (a.author || "").localeCompare(b.author || "", "zh"));
    else if (sort === "platform") list.sort((a, b) => PLATFORM_ORDER.indexOf(a.platform) - PLATFORM_ORDER.indexOf(b.platform) || b.collectedAt - a.collectedAt);
    return list;
  }, [topicPosts, platformFilter, typeFilter, query, sort]);

  const activeTopicObj = topicsWithCount.find((t) => t.id === activeTopic) || topicsWithCount[0];
  const platformsPresent = PLATFORM_ORDER.filter((id) => topicPosts.some((p) => p.platform === id));

  const togglePlatform = (id) => setPlatformFilter((f) => f.includes(id) ? f.filter((x) => x !== id) : [...f, id]);
  const toggleType = (id) => setTypeFilter((f) => f.includes(id) ? f.filter((x) => x !== id) : [...f, id]);
  const clearFilters = () => { setPlatformFilter([]); setTypeFilter([]); setQuery(""); };
  const hasFilters = platformFilter.length || typeFilter.length || query.trim();

  const openAt = (i) => { setOpenIndex(i); setLang("zh"); };
  const closeDetail = () => setOpenIndex(-1);
  const prev = () => setOpenIndex((i) => Math.max(0, i - 1));
  const next = () => setOpenIndex((i) => Math.min(visible.length - 1, i + 1));

  const showToast = (text) => { setToast(text); setTimeout(() => setToast(null), 2600); };

  // ===== 收藏队列：粘贴链接后立即在列表顶部开预览卡片，抓取/AI 进度都在卡片里 =====
  // pending: [{key, url, topic, platform, taskId, status: running|error, progress, message}]
  const [pending, setPending] = useState([]);
  const pendingSeq = useRef(0);

  const patchPending = (key, patch) =>
    setPending((ps) => ps.map((it) => (it.key === key ? { ...it, ...patch } : it)));
  const removePending = (key) => setPending((ps) => ps.filter((it) => it.key !== key));

  // 单张卡片的完整生命周期：建任务 -> 轮询进度 -> 刷新列表让真实帖子替换卡片。
  const runPendingTask = async (key, url, topicId, taskId) => {
    let result;
    try {
      if (!taskId) taskId = await window.TVApi.addLink(url, topicId);
      patchPending(key, { taskId, message: "开始抓取…" });
      result = await window.TVApi.pollTask(taskId, (tk) => {
        patchPending(key, { progress: tk.progress || 0, message: tk.message || "" });
      });
    } catch (err) {
      patchPending(key, { status: "error", message: (err && err.message) || "收藏失败" });
      return;
    }
    patchPending(key, { progress: 100, message: "已收藏" });
    try {
      const data = await refresh();
      removePending(key);
      const post = result.postId
        ? data.posts.find((p) => p.id === result.postId && p.topic === (result.topic || topicId))
        : null;
      const nm = ((post && post.title) || "").trim();
      showToast(nm ? "已收藏「" + (nm.length > 18 ? nm.slice(0, 18) + "…" : nm) + "」" : "已收藏 1 条链接");
    } catch (err) {
      removePending(key);
      showToast("已收藏，但刷新失败，请手动刷新页面");
    }
  };

  // 入口：一批链接 -> 立即插卡（多条并行），后台批量建任务后各自轮询。
  const collectLinks = (urls, topicId) => {
    const entries = urls.map((u) => ({
      key: "pd" + (++pendingSeq.current), url: u, topic: topicId,
      platform: detectPlatform(u), taskId: null,
      status: "running", progress: 0, message: "创建任务…",
    }));
    setPending((ps) => [...entries, ...ps]);
    setActiveTopic(topicId);
    showToast(entries.length > 1
      ? "已开始并行收藏 " + entries.length + " 条，进度见顶部卡片"
      : "已开始收藏，进度见顶部卡片");
    (async () => {
      let tasks = null;
      if (entries.length > 1 && typeof window.TVApi.addLinks === "function") {
        try { tasks = await window.TVApi.addLinks(urls, topicId); }
        catch (err) { tasks = null; /* 后端不支持批量时逐条回退 */ }
      }
      const byUrl = {};
      (tasks || []).forEach((t) => { if (t && t.url && t.taskId) byUrl[t.url] = t.taskId; });
      entries.forEach((en, i) => {
        const tid = byUrl[en.url] || (tasks && tasks[i] && tasks[i].taskId) || null;
        runPendingTask(en.key, en.url, topicId, tid);
      });
    })();
  };

  const retryPending = (key) => {
    const it = pending.find((x) => x.key === key);
    if (!it) return;
    patchPending(key, { status: "running", progress: 0, message: "重新排队…", taskId: null });
    runPendingTask(key, it.url, it.topic, null);
  };

  // 当前课题下进行中的预览卡（置顶显示，不受筛选/排序影响）
  const pendingHere = pending.filter((it) => it.topic === activeTopic);
  // 删除成功后统一收尾：刷新列表 -> toast
  const afterDeleted = async (post) => {
    const nm = ((post && post.title) || "").trim();
    const short = nm.length > 18 ? nm.slice(0, 18) + "…" : nm;
    try {
      await refresh();
      showToast(short ? "已删除「" + short + "」" : "已删除这条收藏");
    } catch (err) {
      showToast("已删除，但刷新失败，请手动刷新页面");
    }
  };
  // Detail 里删除成功后：关详情 -> 收尾
  const onDeleted = async (post) => { closeDetail(); await afterDeleted(post); };
  // 卡片/行上的删除：请求失败时把错误抛回卡片自己的确认层显示
  const deletePost = async (post, withMedia) => {
    await window.TVApi.deletePost(post.uid || post.id, withMedia);
    await afterDeleted(post);
  };
  // Detail 里编辑保存后：刷新（详情保持打开，自动显示新内容）-> toast
  const onEdited = async () => {
    try {
      await refresh();
      showToast("修改已保存");
    } catch (err) {
      showToast("已保存，但刷新失败，请手动刷新页面");
    }
  };
  // NewTopicModal 已经调用后端建好课题，这里刷新并切到新课题。
  const onCreateTopic = async (topicId, name) => {
    setModal(null);
    try {
      await refresh(topicId);
      setActiveTopic(topicId);
      showToast("已创建课题「" + name + "」");
    } catch (err) {
      showToast("课题已创建，但刷新失败，请手动刷新页面");
    }
  };
  // 课题改名：id 不变，刷新后仍停在同一个课题上。
  const onTopicRenamed = async (topic) => {
    setTopicAction(null);
    try {
      await refresh(topic.id);
      showToast("课题已改名为「" + topic.name + "」");
    } catch (err) {
      showToast("已保存，但刷新失败，请手动刷新页面");
    }
  };
  // 课题删除：刷新时 activeTopic 已不存在，refresh 会自动回落到第一个课题。
  const onTopicDeleted = async (topic, removedPosts) => {
    setTopicAction(null);
    try {
      await refresh();
      showToast(removedPosts
        ? "已删除课题「" + topic.name + "」及其 " + removedPosts + " 条收藏"
        : "已删除课题「" + topic.name + "」");
    } catch (err) {
      showToast("已删除，但刷新失败，请手动刷新页面");
    }
  };

  // 全局粘贴：不在输入框里、没开弹窗时，Cmd+V 粘贴链接直接开卡收藏到当前课题。
  useEffect(() => {
    const onPaste = (ev) => {
      const el = ev.target;
      const tag = el && el.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (el && el.isContentEditable)) return;
      if (modal || topicAction) return; // 弹窗自己有输入框
      const text = (ev.clipboardData && ev.clipboardData.getData("text")) || "";
      const urls = text.split(/\s+/).map((s) => s.trim()).filter((s) => /^https?:\/\//i.test(s));
      if (!urls.length || !activeTopic) return;
      ev.preventDefault();
      collectLinks(urls, activeTopic);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [modal, topicAction, activeTopic]);

  // keyboard
  useEffect(() => {
    const onKey = (ev) => {
      if (ev.target.tagName === "INPUT" || ev.target.tagName === "TEXTAREA" || ev.target.tagName === "SELECT") {
        if (ev.key === "Escape") ev.target.blur();
        return;
      }
      if (openIndex >= 0) {
        if (ev.key === "Escape") closeDetail();
        if (ev.key === "ArrowRight" || ev.key === "ArrowDown") { ev.preventDefault(); next(); }
        if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") { ev.preventDefault(); prev(); }
        return;
      }
      if (topicAction) { if (ev.key === "Escape") setTopicAction(null); return; }
      if (modal) { if (ev.key === "Escape") setModal(null); return; }
      if (ev.key === "/") { ev.preventDefault(); searchRef.current && searchRef.current.focus(); }
      if (ev.key.toLowerCase() === "c") { ev.preventDefault(); setModal("collect"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openIndex, modal, topicAction, visible.length]);

  if (!loaded) {
    return e("div", { className: "tv-app tv-app-boot" },
      e("div", { className: "tv-boot" },
        e("div", { className: "tv-boot-mark" }, e(Icon, { name: "vault", size: 24 })),
        e("div", { className: "tv-boot-text" }, "正在加载课题库…")
      )
    );
  }

  return e("div", { className: "tv-app" },
    e(Sidebar, {
      topics: topicsWithCount, posts: topicPosts, activeTopic, setActiveTopic,
      platformFilter, togglePlatform, typeFilter, toggleType,
      onNewTopic: () => setModal("newtopic"),
      onRenameTopic: (t) => setTopicAction({ kind: "rename", topic: t }),
      onDeleteTopic: (t) => setTopicAction({ kind: "delete", topic: t }),
      total: posts.length,
    }),
    e("div", { className: "tv-main" },
      // top bar
      e("div", { className: "tv-top" },
        e("div", { className: "tv-top-title" },
          e("h1", null, e("span", { className: "tv-tname" }, activeTopicObj.name),
            e("span", { style: { fontFamily: "var(--font-mono)", fontSize: 13, color: "var(--muted)", fontWeight: 400 } }, visible.length)
          ),
          e("div", { className: "tv-topic-meta" },
            e("span", null, activeTopicObj.description || "本地多平台收藏"),
            platformsPresent.length ? e("span", { className: "dot" }) : null,
            platformsPresent.length ? e("span", { style: { display: "inline-flex", gap: 4 } },
              platformsPresent.map((id) => e("span", {
                key: id, title: PLATFORMS[id].label,
                style: { width: 7, height: 7, borderRadius: 2, background: PLATFORMS[id].color, display: "inline-block" },
              }))) : null
          )
        ),
        e("label", { className: "tv-search" },
          e(Icon, { name: "search", size: 16 }),
          e("input", { ref: searchRef, value: query, placeholder: "搜索作者、标题、关键词…", onChange: (ev) => setQuery(ev.target.value) }),
          query ? e("button", { onClick: () => setQuery(""), style: { color: "var(--muted)", display: "grid" } }, e(Icon, { name: "close", size: 14 }))
                : e("kbd", null, "/")
        ),
        e("div", { className: "tv-segment" },
          e("button", { className: view === "grid" ? "on" : "", onClick: () => setView("grid"), title: "网格" }, e(Icon, { name: "grid", size: 16 })),
          e("button", { className: view === "list" ? "on" : "", onClick: () => setView("list"), title: "列表" }, e(Icon, { name: "rows", size: 16 }))
        ),
        e("div", { style: { position: "relative", flex: "none" } },
          e("button", { className: "tv-sort", onClick: () => setSortOpen((o) => !o) },
            e(Icon, { name: "sort", size: 15 }), (SORTS.find((s) => s.id === sort) || {}).label, e(Icon, { name: "chevD", size: 14 })
          ),
          sortOpen ? e("div", {
            style: { position: "absolute", top: 46, right: 0, zIndex: 20, minWidth: 150, padding: 6,
              background: "var(--elev-2)", border: "1px solid var(--line-2)", borderRadius: 11, boxShadow: "var(--shadow)" },
            onMouseLeave: () => setSortOpen(false),
          }, SORTS.map((s) => e("button", {
            key: s.id, onClick: () => { setSort(s.id); setSortOpen(false); },
            style: { display: "flex", alignItems: "center", gap: 8, width: "100%", textAlign: "left", padding: "8px 10px", borderRadius: 7, fontSize: 13, color: s.id === sort ? "var(--ink)" : "var(--ink-2)", background: s.id === sort ? "var(--elev)" : "transparent" },
          }, e("span", { style: { width: 14 } }, s.id === sort ? e(Icon, { name: "check", size: 14, style: { color: "var(--accent)" } }) : null), s.label))) : null
        ),
        e("button", { className: "tv-collect", onClick: () => setModal("collect") },
          e(Icon, { name: "link", size: 16 }), "收藏链接")
      ),
      // active filter chips
      hasFilters ? e("div", { className: "tv-chipbar" },
        platformFilter.map((id) => e("span", { key: "p" + id, className: "tv-fchip" },
          e("span", { className: "tv-pf-chip" + (PLATFORMS[id].cjk ? " cjk" : ""), style: { width: 14, height: 14, fontSize: 8, background: PLATFORMS[id].color } }, PLATFORMS[id].mono),
          PLATFORMS[id].label,
          e("button", { className: "tv-fclose", onClick: () => togglePlatform(id) }, e(Icon, { name: "close", size: 11 })))),
        typeFilter.map((id) => e("span", { key: "t" + id, className: "tv-fchip" },
          ({ video: "视频", gallery: "图集", image: "图片", text: "文字", article: "文章" })[id],
          e("button", { className: "tv-fclose", onClick: () => toggleType(id) }, e(Icon, { name: "close", size: 11 })))),
        query.trim() ? e("span", { className: "tv-fchip" }, "“", query.trim(), "”",
          e("button", { className: "tv-fclose", onClick: () => setQuery("") }, e(Icon, { name: "close", size: 11 }))) : null,
        e("button", { className: "tv-clear", onClick: clearFilters }, "清除全部")
      ) : null,
      // board（收藏中的预览卡片固定置顶，不受筛选/排序影响）
      e("div", { className: "tv-board tv-scroll" },
        visible.length === 0 && pendingHere.length === 0
          ? e(EmptyState, { topic: activeTopicObj, hasFilters, onCollect: () => setModal("collect"), onClear: clearFilters })
          : view === "grid"
            ? e("div", { className: "tv-grid" + (dense ? " dense" : "") },
                pendingHere.map((it) => e(PendingCard, { key: it.key, item: it, dense, onRetry: retryPending, onRemove: removePending })),
                visible.map((p, i) => e(Card, { key: p.id, post: p, dense, onOpen: () => openAt(i), onDelete: deletePost })))
            : e("div", { className: "tv-list" },
                pendingHere.map((it) => e(PendingRow, { key: it.key, item: it, onRetry: retryPending, onRemove: removePending })),
                visible.map((p, i) => e(Row, { key: p.id, post: p, onOpen: () => openAt(i), onDelete: deletePost })))
      )
    ),
    // detail
    openIndex >= 0 && visible[openIndex]
      ? e(Detail, { post: visible[openIndex], index: openIndex, total: visible.length, lang, setLang, onPrev: prev, onNext: next, onClose: closeDetail, onDeleted, onEdited,
                    topicName: (topics.find((t) => t.id === visible[openIndex].topic) || {}).name || "" })
      : null,
    // modals
    modal === "collect" ? e(CollectModal, {
      topics: topicsWithCount, defaultTopic: activeTopic, onClose: () => setModal(null),
      onQueue: (links, topicId) => { setModal(null); collectLinks(links, topicId); },
    }) : null,
    modal === "newtopic" ? e(NewTopicModal, { onClose: () => setModal(null), onCreate: onCreateTopic }) : null,
    topicAction && topicAction.kind === "rename" ? e(TopicEditModal, {
      topic: topicAction.topic, onClose: () => setTopicAction(null), onSaved: onTopicRenamed,
    }) : null,
    topicAction && topicAction.kind === "delete" ? e(TopicDeleteModal, {
      topic: topicAction.topic, isLast: topicsWithCount.length <= 1,
      onClose: () => setTopicAction(null), onDeleted: onTopicDeleted,
    }) : null,
    // toast
    toast ? e("div", { className: "tv-toast-wrap" }, e("div", { className: "tv-toast" },
      e("span", { className: "ti" }, e(Icon, { name: "check", size: 13 })), toast)) : null,
    // offline badge (后端未连接，显示离线快照)
    offline ? e("div", { className: "tv-offline-pill", title: "未连接本地后端，正在显示内置离线快照" },
      e(Icon, { name: "database", size: 12 }), "离线快照") : null,
    // tweaks
    e(TweaksPanel, { title: "Tweaks" },
      e(TweakSection, { label: "外观" }),
      e(TweakColor, { label: "强调色", value: t.accent,
        options: ["#46b24a", "#2f7fe0", "#9a6cff", "#e0913a"],
        onChange: (v) => setTweak("accent", v) }),
      e(TweakSection, { label: "布局" }),
      e(TweakRadio, { label: "默认视图", value: t.defaultView,
        options: ["网格", "列表"], onChange: (v) => setTweak("defaultView", v) }),
      e(TweakRadio, { label: "卡片密度", value: t.density,
        options: ["宽松", "紧凑"], onChange: (v) => setTweak("density", v) })
    )
  );
}

function EmptyState({ topic, hasFilters, onCollect, onClear }) {
  if (hasFilters) {
    return e("div", { className: "tv-empty" }, e("div", { className: "wrap" },
      e("div", { className: "ico" }, e(Icon, { name: "filter", size: 28 })),
      e("h3", null, "没有匹配的收藏"),
      e("p", null, "当前筛选条件下这个课题里还没有内容。换个平台/类型，或清除筛选试试。"),
      e("button", { className: "tv-btn ghost", onClick: onClear, style: { margin: "0 auto" } }, "清除筛选")
    ));
  }
  return e("div", { className: "tv-empty" }, e("div", { className: "wrap" },
    e("div", { className: "ico" }, e(Icon, { name: "vault", size: 28 })),
    e("h3", null, "「" + topic.name + "」还是空的"),
    e("p", null, "粘贴一条 X / B站 / 小红书 / 抖音 链接，把第一条内容沉淀到这个课题里。"),
    e("button", { className: "tv-btn primary", onClick: onCollect, style: { margin: "0 auto" } },
      e(Icon, { name: "link", size: 15 }), "收藏第一条链接")
  ));
}

ReactDOM.createRoot(document.getElementById("root")).render(e(App));
