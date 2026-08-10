/* global React, Icon, PLATFORMS, PLATFORM_ORDER, platformVarColor, PfChip, Thumb, typeMeta, initials, relTime, detectPlatform, StatIcon, statEntries, fmtCount, WarnIcon, downloadIssue, localFileCount */
const { createElement: m, useState, useEffect, useRef } = React;

/* ===================== detail media (placeholder, type-aware) ===================== */
function DetailMedia({ post, pc, p, tm }) {
  const [gi, setGi] = useState(0);
  const n = post.imageCount || 0;
  const isGallery = post.contentType === "gallery" && n > 0;
  const isText = tm.textCard;

  // 完整接入后端：优先展示真实视频 / 图片（回退到下方的占位图）。
  if (post.mediaUrl) {
    return m("div", { className: "tv-detail-media", style: { "--pc": pc } },
      m("span", { className: "tv-thumb-pf pf-float" }, m(PfChip, { id: post.platform }), p.label),
      m("div", { className: "tv-detail-stage has-media", style: { "--pc": pc } },
        m("video", { className: "tv-detail-media-el", src: post.mediaUrl, controls: true, playsInline: true, preload: "metadata" })
      )
    );
  }
  if (post.imageUrl) {
    return m("div", { className: "tv-detail-media", style: { "--pc": pc } },
      m("span", { className: "tv-thumb-pf pf-float" }, m(PfChip, { id: post.platform }), p.label),
      m("div", { className: "tv-detail-stage has-media", style: { "--pc": pc } },
        m("img", { className: "tv-detail-media-el", src: post.imageUrl, alt: post.title || "", loading: "lazy" })
      )
    );
  }

  if (isGallery) {
    return m("div", { className: "tv-detail-media", style: { "--pc": pc } },
      m("span", { className: "tv-thumb-pf pf-float" }, m(PfChip, { id: post.platform }), p.label),
      m("div", { className: "tv-gal-wrap" },
        m("div", { className: "tv-detail-stage", style: { "--pc": pc } },
          m("div", { className: "big-icon" }, m("div", { className: "ring" }, m(Icon, { name: "image", size: 30 }))),
          m("div", { className: "ph-note" }, `图 ${gi + 1} / ${n} · ${p.label}图集`),
          n > 1 ? m("button", { className: "tv-gal-nav prev", onClick: () => setGi((g) => (g - 1 + n) % n), title: "上一张" }, m(Icon, { name: "chevL", size: 18 })) : null,
          n > 1 ? m("button", { className: "tv-gal-nav next", onClick: () => setGi((g) => (g + 1) % n), title: "下一张" }, m(Icon, { name: "chevR", size: 18 })) : null,
          m("div", { className: "tv-gal-count" }, `${gi + 1}/${n}`)
        ),
        m("div", { className: "tv-gal-strip" },
          Array.from({ length: n }).map((_, i) =>
            m("button", { key: i, className: "tv-gal-thumb" + (i === gi ? " on" : ""), style: { "--pc": pc }, onClick: () => setGi(i) },
              m(Icon, { name: "image", size: 14 })))
        )
      )
    );
  }

  if (isText) {
    return m("div", { className: "tv-detail-media", style: { "--pc": pc } },
      m("span", { className: "tv-thumb-pf pf-float" }, m(PfChip, { id: post.platform }), p.label),
      m("div", { className: "tv-detail-stage tv-text-stage", style: { "--pc": pc } },
        m("div", { className: "tv-bigquote" },
          m(Icon, { name: "text", size: 30, style: { opacity: .4 } }),
          m("p", null, (post.summary || post.body || "").replace(/\s+/g, " ").trim().slice(0, 200))
        ),
        m("div", { className: "ph-note" }, `纯文字帖 · 无媒体 · ${p.label}`)
      )
    );
  }

  return m("div", { className: "tv-detail-media", style: { "--pc": pc } },
    m("span", { className: "tv-thumb-pf pf-float" }, m(PfChip, { id: post.platform }), p.label),
    m("div", { className: "tv-detail-stage", style: { "--pc": pc } },
      m("div", { className: "big-icon" }, m("div", { className: "ring" }, m(Icon, { name: tm.icon, size: 30, fill: tm.icon === "play" }))),
      m("div", { className: "ph-note" }, post.mediaName || `${tm.label} · ${p.label}`)
    )
  );
}

/* ===================== detail extras: transcript + stats ===================== */
// 收藏时点的互动数据条：浏览/点赞/收藏/评论/分享 + 抓取时间标注
function DetailStats({ stats }) {
  const list = statEntries(stats);
  if (!list.length) return null;
  let cap = "";
  if (stats.capturedAt) {
    const d = new Date(stats.capturedAt * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    cap = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  return m("div", { className: "tv-detail-stats" },
    list.map((s) => m("span", { key: s.key, className: "tv-stat", title: s.label + " " + s.value.toLocaleString() },
      m(StatIcon, { name: s.key, size: 14 }),
      m("b", null, fmtCount(s.value)),
      m("span", { className: "lb" }, s.label))),
    cap ? m("span", { className: "tv-stat-cap", title: "互动数据为收藏（下载）时抓取的快照，非实时" }, "收藏时数据 · " + cap) : null
  );
}

// 口播转写：行格式 "[MM:SS → MM:SS] 文本"，等宽字体逐行展示，时间戳弱化
function TranscriptView({ text }) {
  const lines = String(text || "").split(/\r?\n/).filter((ln) => ln.trim() !== "");
  return m("div", { className: "tv-transcript" },
    lines.map((ln, i) => {
      const mt = ln.match(/^\s*(\[[^\]]*\])\s*(.*)$/);
      return m("div", { key: i, className: "tv-tr-line" },
        mt ? m("span", { className: "ts" }, mt[1]) : null,
        m("span", { className: "tx" }, mt ? mt[2] : ln)
      );
    })
  );
}

// 内容没抓全时的整条提示：说清缺了什么，并把后端记的 warnings 摊开给用户看。
// warnings 里常混进 opencli/node 的 stderr，逐条截断，只列前几条。
function DownloadNotice({ post }) {
  const issue = downloadIssue(post);
  if (!issue) return null;
  const warns = (Array.isArray(post.warnings) ? post.warnings : [])
    .map((w) => String(w || "").replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .slice(0, 3);
  return m("div", { className: "tv-dlnote " + issue.tone },
    m("span", { className: "ico" }, m(WarnIcon, { size: 15 })),
    m("div", { style: { minWidth: 0 } },
      m("b", null, issue.label),
      m("p", null, issue.detail + "（可以删掉这条重新收藏，或点「打开原帖」去源站看。）"),
      warns.length
        ? m("ul", null, warns.map((w, i) =>
            m("li", { key: i, title: w }, w.length > 120 ? w.slice(0, 120) + "…" : w)))
        : null
    )
  );
}

/* ===================== detail lightbox ===================== */
function Detail({ post, index, total, onPrev, onNext, onClose, lang, setLang, onDeleted, onEdited, topicName }) {
  const pc = platformVarColor(post.platform);
  const p = PLATFORMS[post.platform] || PLATFORMS.x;
  const tm = typeMeta(post.contentType);
  const uid = post.uid || post.id; // 离线快照只有 id，后端两者同值
  const hasTranscript = !!(post.transcript && String(post.transcript).trim());
  // 三档切换：中文 / 原文 / 转写；翻到没有转写的帖子时安全回退中文
  const mode = (lang === "transcript" && !hasTranscript) ? "zh" : lang;
  const copy = mode === "original"
    ? (post.originalText || "这条记录暂未留档原文。")
    : (post.body || post.summary || "暂无中文记录。");
  const note = mode === "original" && (post.originalNote || post.originalIsExcerpt)
    ? (post.originalNote || "当前素材仅保存了原文关键词/摘录。")
    : "";

  const [confirmDel, setConfirmDel] = useState(false);
  const [delAck, setDelAck] = useState(false);
  const [delMedia, setDelMedia] = useState(true);
  const [delBusy, setDelBusy] = useState(false);
  const [delErr, setDelErr] = useState("");
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState("");
  // 和卡片上的确认层同一道闸：删除不可恢复，必须先勾「我确认」
  const delFileCount = localFileCount(post);

  // 前后翻帖时重置删除确认条与编辑弹窗，避免误操作到另一条
  useEffect(() => {
    setConfirmDel(false); setDelAck(false); setDelMedia(true);
    setDelBusy(false); setDelErr(""); setEditing(false);
    setCopied("");
  }, [uid]);

  // 复制给 AI：把这一条的内容 + 本机文件路径写进剪贴板，粘到任何 AI 里都自足。
  // 按住 Shift 点则不带口播转写（长视频的转写能有几千字）。
  const doCopy = (ev) => {
    if (!window.TVClip) { setCopied("err"); return; }
    const text = window.TVClip.buildClipText(post, {
      topicName: topicName || "",
      withTranscript: !ev.shiftKey,
    });
    window.TVClip.writeClipboard(text)
      .then(() => { setCopied("ok"); setTimeout(() => setCopied(""), 1800); })
      .catch(() => { setCopied("err"); setTimeout(() => setCopied(""), 2600); });
  };

  async function doDelete() {
    if (delBusy || !delAck) return;
    setDelBusy(true); setDelErr("");
    try {
      await window.TVApi.deletePost(uid, delMedia && delFileCount > 0);
      if (onDeleted) onDeleted(post);
    } catch (err) {
      setDelBusy(false);
      setDelErr((err && err.message) || "删除失败");
    }
  }

  return m("div", { className: "tv-overlay", onMouseDown: (e) => { if (e.target === e.currentTarget) onClose(); } },
    m("button", { className: "tv-detail-nav prev", onClick: onPrev, disabled: index <= 0, title: "上一条" }, m(Icon, { name: "chevL", size: 18 })),
    m("button", { className: "tv-detail-nav next", onClick: onNext, disabled: index >= total - 1, title: "下一条" }, m(Icon, { name: "chevR", size: 18 })),
    m("div", { className: "tv-detail" },
      m("button", { className: "tv-detail-x", onClick: onClose, title: "关闭 (Esc)" }, m(Icon, { name: "close", size: 16 })),
      m(DetailMedia, { post, pc, p, tm }),
      // side
      m("div", { className: "tv-detail-side" },
        m("div", { className: "tv-detail-head" },
          m("span", { className: "tv-ava", style: { "--pc": pc, background: pc } }, initials(post.author, post.handle)),
          m("div", { className: "id" },
            m("div", { className: "nm" }, post.author),
            m("div", { className: "hd" }, post.handle || p.label)
          ),
          m("span", { style: { fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--faint)" } }, `${index + 1}/${total}`)
        ),
        m("div", { className: "tv-detail-body tv-scroll" },
          m("div", { className: "tv-switch", role: "group" },
            m("button", { className: mode === "zh" ? "on" : "", onClick: () => setLang("zh") }, "中文"),
            m("button", { className: mode === "original" ? "on" : "", onClick: () => setLang("original") }, "原文"),
            hasTranscript
              ? m("button", { className: mode === "transcript" ? "on" : "", onClick: () => setLang("transcript") }, "转写")
              : null
          ),
          m("h2", { className: "tv-detail-title" }, post.title),
          m(DownloadNotice, { post }),
          m(DetailStats, { stats: post.stats }),
          mode === "transcript"
            ? m(TranscriptView, { text: post.transcript })
            : m("p", { className: "tv-detail-copy" }, copy),
          note ? m("div", { className: "tv-detail-note" }, note) : null,
          post.keywords.length ? m("div", { className: "tv-kwgroup" },
            post.keywords.map((k, i) => m("span", { key: i, className: "tv-tag" }, k))
          ) : null,
          post.supplement ? m("div", { className: "tv-supp" }, post.supplement) : null
        ),
        confirmDel
          ? m("div", { className: "tv-del-confirm" },
              m("div", { className: "tv-del-row" },
                m("span", { className: "warn" }, m(Icon, { name: "trash", size: 14 })),
                m("div", { className: "msg" },
                  m("b", null, "删除这条收藏？"),
                  m("label", { className: "opt strong" },
                    m("input", { type: "checkbox", checked: delAck, disabled: delBusy,
                      onChange: (e) => setDelAck(e.target.checked) }),
                    "我确认删除，不可恢复"),
                  delFileCount ? m("label", { className: "opt" },
                    m("input", { type: "checkbox", checked: delMedia, disabled: delBusy,
                      onChange: (e) => setDelMedia(e.target.checked) }),
                    "同时删除 " + delFileCount + " 个本地文件") : null
                ),
                m("button", { className: "tv-btn ghost sm", disabled: delBusy,
                  onClick: () => { setConfirmDel(false); setDelAck(false); setDelErr(""); } }, "取消"),
                m("button", { className: "tv-btn danger sm", disabled: delBusy || !delAck, onClick: doDelete },
                  delBusy ? "删除中…" : "确认删除")
              ),
              delErr ? m("div", { className: "tv-del-err" }, delErr) : null
            )
          : m("div", { className: "tv-detail-foot" },
              m("span", { className: "when" }, post.published || "未记录时间"),
              m("button", {
                className: "tv-foot-act tv-copy-ai" + (copied === "ok" ? " done" : "") + (copied === "err" ? " danger" : ""),
                title: copied === "err" ? "复制失败" : "复制这一条给 AI（按住 Shift 不带口播转写）",
                onClick: doCopy,
              },
                m(Icon, { name: copied === "ok" ? "check" : "copy", size: 15 }),
                m("span", null, copied === "ok" ? "已复制" : copied === "err" ? "失败" : "复制给 AI")),
              m("button", { className: "tv-foot-act", title: "编辑", onClick: () => setEditing(true) },
                m(Icon, { name: "edit", size: 15 })),
              m("button", { className: "tv-foot-act danger", title: "删除",
                onClick: () => { setDelErr(""); setConfirmDel(true); } },
                m(Icon, { name: "trash", size: 15 })),
              post.sourceLink
                ? m("a", { className: "tv-open", href: post.sourceLink, target: "_blank", rel: "noreferrer" }, m(Icon, { name: "external", size: 14 }), "打开原帖")
                : null
            )
      ),
      // 编辑弹窗：作为 .tv-detail 的兄弟节点挂在遮罩层里（tv-detail 有 overflow:hidden）
      editing ? m(EditModal, {
        post,
        onClose: () => setEditing(false),
        onSaved: (updated) => { setEditing(false); if (onEdited) onEdited(updated || post); },
      }) : null
    )
  );
}

/* ===================== edit post（风格照抄 NewTopicModal） ===================== */
function EditModal({ post, onClose, onSaved }) {
  // 标题预填后端真实存储值（rawTitle 含「帖子 N：」前缀），避免保存时静默丢前缀
  const [title, setTitle] = useState(post.rawTitle || post.title || "");
  const [body, setBody] = useState(post.body || "");
  const [summary, setSummary] = useState(post.summary || "");
  const [kw, setKw] = useState((Array.isArray(post.keywords) ? post.keywords : []).join(", "));
  const [supp, setSupp] = useState(post.supplement || "");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const ref = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { ref.current && ref.current.focus(); }, []);
  useEffect(() => () => { mounted.current = false; }, []);

  // PATCH /api/posts/<uid>：保存成功后由 Detail 通知上层刷新 + toast
  async function submit() {
    if (busy) return;
    setBusy(true); setErrorMsg("");
    try {
      const keywords = kw.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
      const updated = await window.TVApi.updatePost(post.uid || post.id, {
        title: title.trim(), body: body, summary: summary, keywords: keywords, supplement: supp,
      });
      if (!mounted.current) return;
      onSaved(updated);
    } catch (err) {
      if (!mounted.current) return;
      setErrorMsg((err && err.message) || "保存失败");
      setBusy(false);
    }
  }

  return m("div", {
    className: "tv-overlay",
    onMouseDown: (e) => { if (e.target === e.currentTarget && !busy) onClose(); },
    // Esc 只关编辑弹窗，不透传到 App 层去关掉整个详情
    onKeyDown: (e) => {
      const tag = e.target.tagName;
      if (e.key === "Escape" && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") {
        e.stopPropagation(); onClose();
      }
    },
  },
    m("div", { className: "tv-modal tv-edit-modal" },
      m("button", { className: "tv-detail-x", onClick: onClose, style: { top: 16, right: 16 } }, m(Icon, { name: "close", size: 16 })),
      m("div", { className: "tv-modal-head" },
        m("div", { className: "mi" }, m(Icon, { name: "edit", size: 18 })),
        m("div", null,
          m("h3", null, "编辑收藏"),
          m("p", null, "修改这条收藏的标题、正文、摘要、关键词与补充说明。"))
      ),
      m("div", { className: "tv-modal-body tv-scroll" },
        m("div", { className: "tv-field" },
          m("label", null, "标题"),
          m("input", { ref, value: title, onChange: (e) => setTitle(e.target.value) })
        ),
        m("div", { className: "tv-field" },
          m("label", null, "中文正文"),
          m("textarea", { value: body, rows: 5, onChange: (e) => setBody(e.target.value) })
        ),
        m("div", { className: "tv-field" },
          m("label", null, "摘要"),
          m("textarea", { value: summary, rows: 3, onChange: (e) => setSummary(e.target.value) })
        ),
        m("div", { className: "tv-field" },
          m("label", null, "关键词（逗号分隔）"),
          m("input", { value: kw, placeholder: "关键词 1, 关键词 2", onChange: (e) => setKw(e.target.value) })
        ),
        m("div", { className: "tv-field" },
          m("label", null, "补充说明"),
          m("textarea", { value: supp, rows: 3, onChange: (e) => setSupp(e.target.value) })
        ),
        errorMsg ? m("div", { className: "tv-field-error" }, errorMsg) : null
      ),
      m("div", { className: "tv-modal-foot" },
        m("div", { className: "spacer" }),
        m("button", { className: "tv-btn ghost", onClick: onClose, disabled: busy }, "取消"),
        m("button", { className: "tv-btn primary", disabled: busy, onClick: submit },
          m(Icon, { name: busy ? "refresh" : "check", size: 15 }), busy ? "保存中…" : "保存修改")
      )
    )
  );
}

/* ===================== collect (paste link, 支持多行批量) ===================== */
// 点「收藏」后立即把链接交给 App 层的收藏队列（onQueue）并关闭弹窗：
// 抓取/AI 的实时进度显示在列表顶部的预览卡片里，用户可以继续浏览和操作。
function CollectModal({ topics, defaultTopic, onClose, onQueue }) {
  const [url, setUrl] = useState("");
  const [topic, setTopic] = useState(defaultTopic);
  const inputRef = useRef(null);

  // 粘贴内容按换行/空白切分成多条链接
  const links = url.split(/\s+/).map((s) => s.trim()).filter(Boolean);
  const multi = links.length > 1;
  const detected = detectPlatform(links[0] || "");
  const detectedSet = {};
  links.forEach((u) => { const id = detectPlatform(u); if (id) detectedSet[id] = true; });

  useEffect(() => { inputRef.current && inputRef.current.focus(); }, []);

  function start() {
    if (!links.length) return;
    onQueue(links, topic);
  }

  return m("div", { className: "tv-overlay", onMouseDown: (e) => { if (e.target === e.currentTarget) onClose(); } },
    m("div", { className: "tv-modal" },
      m("button", { className: "tv-detail-x", onClick: onClose, style: { top: 16, right: 16 } }, m(Icon, { name: "close", size: 16 })),
      m("div", { className: "tv-modal-head" },
        m("div", { className: "mi" }, m(Icon, { name: "link", size: 19 })),
        m("div", null,
          m("h3", null, "收藏链接"),
          m("p", null, "粘贴 X / B站 / 小红书 / 抖音 链接，支持多行批量。收藏后立即开卡，进度在列表顶部实时显示。")
        )
      ),
      m(React.Fragment, null,
        m("div", { className: "tv-modal-body" },
          m("div", { className: "tv-paste" + (multi || url.indexOf("\n") >= 0 ? " is-multi" : "") },
            m("span", { className: "pf-detect", style: !multi && detected ? { background: PLATFORMS[detected].color, color: "#0b0c0f" } : {} },
              multi ? m(Icon, { name: "layers", size: 14 })
                : detected ? PLATFORMS[detected].mono : m(Icon, { name: "link", size: 14 })
            ),
            m("textarea", { ref: inputRef, value: url,
              rows: Math.min(5, Math.max(1, url.split("\n").length)),
              placeholder: "https://…  支持粘贴多行链接批量收藏", spellCheck: false,
              onChange: (e) => setUrl(e.target.value),
              // Enter 开始收藏（与旧版一致），Shift+Enter 换行
              onKeyDown: (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (links.length) start(); } } }),
            url ? m("button", { className: "clear", onClick: () => setUrl("") }, m(Icon, { name: "close", size: 14 })) : null
          ),
          m("div", { className: "tv-detect-row" },
            multi
              ? m("span", { className: "ok", style: { display: "inline-flex", alignItems: "center", gap: 7 } },
                  m(Icon, { name: "layers", size: 14 }), "识别到 ", m("b", null, links.length), " 条链接，将并行批量收藏")
              : detected
                ? m("span", { className: "ok", style: { display: "inline-flex", alignItems: "center", gap: 7 } },
                    m(Icon, { name: "check", size: 14 }), "识别为 ", m("b", null, PLATFORMS[detected].label))
                : url.trim()
                  ? m("span", null, "未识别平台，可手动选择或仍按链接保存")
                  : m("span", null, "支持 x.com · bilibili.com · xiaohongshu.com · douyin.com"),
          ),
          m("div", { className: "tv-platform-pills" },
            PLATFORM_ORDER.map((id) => m("span", { key: id, className: "tv-pill" + ((multi ? detectedSet[id] : detected === id) ? " on" : "") },
              m(PfChip, { id }), PLATFORMS[id].label))
          ),
          m("div", { className: "tv-topic-select" },
            m("span", { className: "lbl" }, "收藏到课题"),
            m("select", { value: topic, onChange: (e) => setTopic(e.target.value) },
              topics.map((t) => m("option", { key: t.id, value: t.id }, t.name)))
          )
        ),
        m("div", { className: "tv-modal-foot" },
          m("div", { className: "spacer" }),
          m("button", { className: "tv-btn ghost", onClick: onClose }, "取消"),
          m("button", { className: "tv-btn primary", disabled: !links.length, onClick: start },
            m(Icon, { name: "download", size: 15 }), multi ? "立即收藏 " + links.length + " 条" : "立即收藏")
        )
      )
    )
  );
}

/* ===================== new topic ===================== */
function NewTopicModal({ onClose, onCreate }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const ref = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { ref.current && ref.current.focus(); }, []);
  useEffect(() => () => { mounted.current = false; }, []);

  // 真实流程：POST /api/topics 建好课题后，让上层刷新并切到新课题。
  async function submit() {
    const nm = name.trim();
    if (!nm || busy) return;
    setBusy(true); setErrorMsg("");
    try {
      const topic = await window.TVApi.createTopic(nm, desc.trim());
      if (!mounted.current) return;
      onCreate(topic.id, topic.name || nm);
    } catch (err) {
      if (!mounted.current) return;
      setErrorMsg((err && err.message) || "创建失败");
      setBusy(false);
    }
  }

  return m("div", { className: "tv-overlay", onMouseDown: (e) => { if (e.target === e.currentTarget && !busy) onClose(); } },
    m("div", { className: "tv-modal" },
      m("button", { className: "tv-detail-x", onClick: onClose, style: { top: 16, right: 16 } }, m(Icon, { name: "close", size: 16 })),
      m("div", { className: "tv-modal-head" },
        m("div", { className: "mi" }, m(Icon, { name: "plus", size: 19 })),
        m("div", null, m("h3", null, "新建课题"), m("p", null, "课题是收藏的容器，把同一主题的多平台内容沉淀到一起。"))
      ),
      m("div", { className: "tv-modal-body" },
        m("div", { className: "tv-field" },
          m("label", null, "课题名称"),
          m("input", { ref, value: name, placeholder: "例如：Seedance 2.0", onChange: (e) => setName(e.target.value),
            onKeyDown: (e) => { if (e.key === "Enter" && name.trim()) submit(); } })
        ),
        m("div", { className: "tv-field" },
          m("label", null, "描述（可选）"),
          m("textarea", { value: desc, placeholder: "这个课题收集什么内容？", onChange: (e) => setDesc(e.target.value) })
        ),
        errorMsg ? m("div", { className: "tv-field-error" }, errorMsg) : null
      ),
      m("div", { className: "tv-modal-foot" },
        m("div", { className: "spacer" }),
        m("button", { className: "tv-btn ghost", onClick: onClose }, "取消"),
        m("button", { className: "tv-btn primary", disabled: !name.trim() || busy, onClick: submit },
          m(Icon, { name: busy ? "refresh" : "check", size: 15 }), busy ? "创建中…" : "创建课题")
      )
    )
  );
}

/* ===================== rename topic（课题改名 / 改描述） ===================== */
// 只改展示名和描述：课题 id 是帖子的归属键，改了会把已有收藏全部孤儿化，所以固定不动。
function TopicEditModal({ topic, onClose, onSaved }) {
  const [name, setName] = useState(topic.name || "");
  const [desc, setDesc] = useState(topic.description || "");
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const ref = useRef(null);
  const mounted = useRef(true);
  useEffect(() => { if (ref.current) { ref.current.focus(); ref.current.select(); } }, []);
  useEffect(() => () => { mounted.current = false; }, []);

  const dirty = name.trim() !== (topic.name || "") || desc.trim() !== (topic.description || "");

  // PATCH /api/topics/<id>：保存成功后由上层刷新课题列表 + toast
  async function submit() {
    const nm = name.trim();
    if (!nm || busy || !dirty) return;
    setBusy(true); setErrorMsg("");
    try {
      const updated = await window.TVApi.updateTopic(topic.id, { name: nm, description: desc.trim() });
      if (!mounted.current) return;
      onSaved(updated || { ...topic, name: nm, description: desc.trim() });
    } catch (err) {
      if (!mounted.current) return;
      setErrorMsg((err && err.message) || "保存失败");
      setBusy(false);
    }
  }

  return m("div", { className: "tv-overlay", onMouseDown: (e) => { if (e.target === e.currentTarget && !busy) onClose(); } },
    m("div", { className: "tv-modal" },
      m("button", { className: "tv-detail-x", onClick: onClose, style: { top: 16, right: 16 } }, m(Icon, { name: "close", size: 16 })),
      m("div", { className: "tv-modal-head" },
        m("div", { className: "mi" }, m(Icon, { name: "edit", size: 19 })),
        m("div", null,
          m("h3", null, "重命名课题"),
          m("p", null, "课题 ID ", m("code", { className: "tv-code" }, topic.id),
            " 不变（收藏按 ID 归属），这里只改显示名称和描述。"))
      ),
      m("div", { className: "tv-modal-body" },
        m("div", { className: "tv-field" },
          m("label", null, "课题名称"),
          m("input", { ref, value: name, onChange: (e) => setName(e.target.value),
            onKeyDown: (e) => { if (e.key === "Enter" && name.trim()) submit(); } })
        ),
        m("div", { className: "tv-field" },
          m("label", null, "描述（可选）"),
          m("textarea", { value: desc, placeholder: "这个课题收集什么内容？", onChange: (e) => setDesc(e.target.value) })
        ),
        errorMsg ? m("div", { className: "tv-field-error" }, errorMsg) : null
      ),
      m("div", { className: "tv-modal-foot" },
        m("div", { className: "spacer" }),
        m("button", { className: "tv-btn ghost", onClick: onClose, disabled: busy }, "取消"),
        m("button", { className: "tv-btn primary", disabled: !name.trim() || !dirty || busy, onClick: submit },
          m(Icon, { name: busy ? "refresh" : "check", size: 15 }), busy ? "保存中…" : "保存修改")
      )
    )
  );
}

/* ===================== delete topic（删课题，非空要二次确认） ===================== */
// 删除是不可恢复的（posts.json 直接改写），所以非空课题必须显式勾选确认，
// 默认连带清理本地媒体，否则内容层会留下一堆没人引用的孤儿文件。
function TopicDeleteModal({ topic, isLast, onClose, onDeleted }) {
  const count = topic.count || 0;
  const [ack, setAck] = useState(false);
  const [withMedia, setWithMedia] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const blocked = count > 0 && !ack;

  async function submit() {
    if (busy || blocked) return;
    setBusy(true); setErrorMsg("");
    try {
      const res = await window.TVApi.deleteTopic(topic.id, count > 0, count > 0 && withMedia);
      if (!mounted.current) return;
      onDeleted(topic, (res && res.removedPosts) || 0);
    } catch (err) {
      if (!mounted.current) return;
      setErrorMsg((err && err.message) || "删除失败");
      setBusy(false);
    }
  }

  return m("div", { className: "tv-overlay", onMouseDown: (e) => { if (e.target === e.currentTarget && !busy) onClose(); } },
    m("div", { className: "tv-modal" },
      m("button", { className: "tv-detail-x", onClick: onClose, style: { top: 16, right: 16 } }, m(Icon, { name: "close", size: 16 })),
      m("div", { className: "tv-modal-head" },
        m("div", { className: "mi danger" }, m(Icon, { name: "trash", size: 19 })),
        m("div", null,
          m("h3", null, "删除课题「" + topic.name + "」"),
          m("p", null, count
            ? "这个课题下还有 " + count + " 条收藏，删除课题会把它们一起删掉，且不可恢复。"
            : "这是一个空课题，删除后随时可以重新新建。"))
      ),
      m("div", { className: "tv-modal-body" },
        count ? m("div", { className: "tv-danger-box" },
          m("label", { className: "tv-danger-opt" },
            m("input", { type: "checkbox", checked: ack, disabled: busy,
              onChange: (e) => setAck(e.target.checked) }),
            m("span", null, "我确认连同这 ", m("b", null, count), " 条收藏一起删除")),
          m("label", { className: "tv-danger-opt" },
            m("input", { type: "checkbox", checked: withMedia, disabled: busy,
              onChange: (e) => setWithMedia(e.target.checked) }),
            m("span", null, "同时删除这些收藏的本地媒体文件（视频 / 图片 / 音频 / 转写）"))
        ) : null,
        isLast ? m("div", { className: "tv-modal-hint" }, "这是最后一个课题，删除后会自动重建一个空的默认课题。") : null,
        errorMsg ? m("div", { className: "tv-field-error", style: { marginTop: 12 } }, errorMsg) : null
      ),
      m("div", { className: "tv-modal-foot" },
        m("div", { className: "spacer" }),
        m("button", { className: "tv-btn ghost", onClick: onClose, disabled: busy }, "取消"),
        m("button", { className: "tv-btn danger", disabled: blocked || busy, onClick: submit },
          m(Icon, { name: busy ? "refresh" : "trash", size: 15 }),
          busy ? "删除中…" : (count ? "删除课题和 " + count + " 条收藏" : "删除课题"))
      )
    )
  );
}

Object.assign(window, { Detail, EditModal, CollectModal, NewTopicModal, DownloadNotice,
                        TopicEditModal, TopicDeleteModal });
