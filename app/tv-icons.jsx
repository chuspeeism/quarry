/* global React */
const { createElement: h } = React;

// ---- icon set (stroke-based, 24-grid) ----
const P = {
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.3-4.3",
  plus: "M12 5v14M5 12h14",
  link: "M9 15l6-6M10.5 6.5l1-1a4 4 0 0 1 6 6l-2 2M13.5 17.5l-1 1a4 4 0 0 1-6-6l2-2",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  rows: "M4 6h16M4 12h16M4 18h16",
  sort: "M7 4v16M7 4l-3 3M7 4l3 3M17 20V4M17 20l-3-3M17 20l3-3",
  close: "M6 6l12 12M18 6L6 18",
  chevL: "M15 6l-6 6 6 6",
  chevR: "M9 6l6 6-6 6",
  chevD: "M6 9l6 6 6-6",
  chevU: "M6 15l6-6 6 6",
  check: "M5 12l4 4 10-10",
  play: "M8 5v14l11-7z",
  doc: "M7 3h7l5 5v13a0 0 0 0 1 0 0H7zM14 3v5h5M9 13h6M9 17h6",
  image: "M4 5h16v14H4zM4 15l4-4 4 4 3-3 5 5M9 9a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0",
  tag: "M3 12V4h8l9 9-8 8-9-9ZM7.5 7.5h.01",
  external: "M14 4h6v6M20 4l-9 9M19 13v6H5V5h6",
  vault: "M4 5h16v14H4zM4 9h16M8 13.5a2 2 0 1 0 4 0 2 2 0 0 0-4 0M12.5 13.5h3.5",
  database: "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3ZM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6",
  filter: "M4 5h16l-6 7v6l-4 2v-8z",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  download: "M12 4v11M7 11l5 5 5-5M5 20h14",
  bolt: "M13 3L5 13h5l-1 8 8-10h-5z",
  refresh: "M20 11a8 8 0 1 0-1 5M20 5v6h-6",
  hash: "M9 4 7 20M17 4l-2 16M5 9h14M4 15h14",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 2",
  layers: "M8 8h12v12H8zM8 14l3-2 3 3 2-1 2 2M4 4h12M4 4v12",
  home: "M4 11l8-7 8 7M6 9.5V20h12V9.5",
  text: "M5 6h14M5 11h14M5 16h9",
  edit: "M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z",
  trash: "M4 6h16M9 6V4h6v2M6 6l1 14h10l1-14M10 10.5v5.5M14 10.5v5.5",
  copy: "M9 9h10v10a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V9ZM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
};

function Icon({ name, size = 18, fill = false, style, strokeWidth = 1.8 }) {
  const d = P[name] || "";
  const filled = fill || name === "play";
  return h("svg", {
    width: size, height: size, viewBox: "0 0 24 24", style,
    fill: filled ? "currentColor" : "none",
    stroke: filled ? "none" : "currentColor",
    strokeWidth, strokeLinecap: "round", strokeLinejoin: "round",
  }, h("path", { d }));
}

// ---- platform metadata ----
const PLATFORMS = {
  x:           { id: "x",           label: "X",      mono: "X",  cjk: false, cssVar: "--x",           color: "#d7dadf", hosts: ["x.com", "twitter.com", "t.co"] },
  bilibili:    { id: "bilibili",    label: "B站",    mono: "B",  cjk: false, cssVar: "--bilibili",    color: "#5ab6f0", hosts: ["bilibili.com", "b23.tv"] },
  xiaohongshu: { id: "xiaohongshu", label: "小红书", mono: "红", cjk: true,  cssVar: "--xiaohongshu", color: "#ff5a72", hosts: ["xiaohongshu.com", "xhslink.com"] },
  douyin:      { id: "douyin",      label: "抖音",   mono: "抖", cjk: true,  cssVar: "--douyin",      color: "#2fe0d2", hosts: ["douyin.com", "iesdouyin.com", "v.douyin.com"] },
};
const PLATFORM_ORDER = ["x", "bilibili", "xiaohongshu", "douyin"];

function platformVarColor(id) { return `var(${(PLATFORMS[id] || PLATFORMS.x).cssVar})`; }

function PfChip({ id, size }) {
  const p = PLATFORMS[id] || PLATFORMS.x;
  return h("span", {
    className: "tv-pf-chip" + (p.cjk ? " cjk" : ""),
    style: { background: platformVarColor(id), ...(size ? { width: size, height: size } : {}) },
  }, p.mono);
}

function detectPlatform(url) {
  if (!url) return null;
  let host = "";
  try { host = new URL(url.trim()).hostname.replace(/^www\./, ""); } catch { return null; }
  for (const id of PLATFORM_ORDER) {
    if (PLATFORMS[id].hosts.some((hn) => host === hn || host.endsWith("." + hn) || host.includes(hn))) return id;
  }
  return null;
}

function typeMeta(t) {
  if (t === "article") return { label: "ARTICLE", icon: "doc" };
  if (t === "gallery") return { label: "GALLERY", icon: "layers", multi: true };
  if (t === "image") return { label: "IMAGE", icon: "image" };
  if (t === "text") return { label: "TEXT", icon: "text", textCard: true };
  return { label: "VIDEO", icon: "play" };
}

function initials(name, handle) {
  const src = (handle || name || "").replace(/^@/, "").trim();
  const ascii = src.match(/[A-Za-z0-9]/g);
  if (ascii && ascii.length) return ascii.slice(0, 2).join("").toUpperCase();
  return (src.slice(0, 1) || "·");
}

function relTime(ts) {
  const now = 1781430000;
  const diff = Math.max(0, now - ts);
  const d = Math.floor(diff / 86400);
  if (d >= 1) return `${d} 天前`;
  const hMin = Math.floor(diff / 3600);
  if (hMin >= 1) return `${hMin} 小时前`;
  const m = Math.floor(diff / 60);
  return m >= 1 ? `${m} 分钟前` : "刚刚";
}

Object.assign(window, {
  Icon, PLATFORMS, PLATFORM_ORDER, platformVarColor, PfChip,
  detectPlatform, typeMeta, initials, relTime,
});
