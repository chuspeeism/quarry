/*
 * tv-api.js — Quarry 前端数据层
 *
 * 把本地 Python 后端（server/server.py）的 /api/* 接口接到新版 React 界面：
 *   - loadAll()            一次拉全部课题与帖子（前端按课题做本地筛选）
 *   - createTopic(n, d)    新建课题            -> POST /api/topics
 *   - addLink(url, topic)  收藏链接，返回 taskId -> POST /api/add
 *   - addLinks(urls, t)    批量收藏，返回 tasks  -> POST /api/add {urls:[...]}
 *   - pollTask(id, onTick) 轮询抓取/AI 进度    -> GET  /api/task/<id>
 *   - queueLinks(urls, t)  只入队不抓取        -> POST /api/add {defer:true}
 *   - getQueue()/startQueue()/stopQueue()      -> /api/queue[/start|/stop]
 *   - retryQueued(id)/removeQueued(id)/clearQueue()
 *   - deletePost(uid, m)   删除帖子(可连媒体)   -> DELETE /api/posts/<uid>?media=1
 *   - updatePost(uid, f)   编辑帖子字段        -> PATCH /api/posts/<uid>
 *
 * 同时负责「后端字段结构 -> UI 字段结构」的映射（adaptPost）：后端把所有内容
 * 统一存成 mediaPath / imagePath / addedAt 等，UI 需要 contentType / collectedAt /
 * mediaUrl 等派生字段。
 */
(function () {
  "use strict";

  function abs(path) {
    return path ? "/" + String(path).replace(/^\/+/, "") : "";
  }

  async function jget(path) {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(path + " -> " + res.status);
    return res.json();
  }

  async function jsend(method, path, body) {
    const opts = { method: method };
    if (body !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    let data = {};
    try { data = await res.json(); } catch (e) { /* ignore */ }
    if (!res.ok) throw new Error(data.error || (path + " -> " + res.status));
    return data;
  }

  async function jpost(path, body) {
    return jsend("POST", path, body || {});
  }

  // 后端 title 形如「帖子 1：标题」，UI 里展示去前缀的干净标题，rawTitle 保留原值。
  function cleanTitle(raw) {
    const s = String(raw || "");
    return s.replace(/^帖子\s*\d+\s*[:：]\s*/, "") || s;
  }

  // 后端 contentType 只有 post/video/note 等；UI 需要 video/image/text/article 来分流卡片样式。
  function deriveType(p) {
    if (p.mediaPath) return "video";
    if (p.imagePath) return "image";
    if (Array.isArray(p.articleLinks) && p.articleLinks.length) return "article";
    return "text";
  }

  // 让「最近收藏」排序有合理的相对时间：新增帖用真实 addedAt；
  // 种子帖没有时间戳，按 number 反推一个递减的时间，保持 1 号在最前、间隔约 2 小时。
  var REL_BASE = 1781430000;
  var REL_STEP = 7400;
  function collectedAt(p) {
    if (p.addedAt) return p.addedAt;
    var n = Number(p.number);
    if (!isFinite(n) || n <= 0) n = 999;
    return REL_BASE - (n - 1) * REL_STEP;
  }

  function adaptPost(p) {
    var imageUrl = abs(p.imagePath) || ((Array.isArray(p.remoteMedia) && p.remoteMedia[0]) || "");
    return Object.assign({}, p, {
      contentType: deriveType(p),
      rawTitle: p.title || "",
      title: cleanTitle(p.title),
      keywords: Array.isArray(p.keywords) ? p.keywords : [],
      collectedAt: collectedAt(p),
      hasVideo: !!p.mediaPath,
      hasImage: !!p.imagePath,
      imageCount: p.imagePath ? 1 : 0,
      mediaUrl: abs(p.mediaPath),
      imageUrl: imageUrl,
      // 收藏时点的互动数据快照 {views,likes,collects,comments,shares,capturedAt}；旧数据没有则为空对象
      stats: (p.stats && typeof p.stats === "object" && !Array.isArray(p.stats)) ? p.stats : {},
      // 口播转写相关新字段：旧数据（含离线快照）没有这些键，统一按空串透传
      transcript: p.transcript || "",
      transcriptSrtPath: p.transcriptSrtPath || "",
      transcriptMdPath: p.transcriptMdPath || "",
      audioPath: p.audioPath || "",
      transcriptSource: p.transcriptSource || "",
    });
  }

  function adaptTopic(t) {
    return {
      id: t.id,
      name: t.name || t.id,
      description: t.description || "",
      count: t.postCount || 0,
    };
  }

  async function loadAll() {
    var results = await Promise.all([jget("/api/topics"), jget("/api/posts")]);
    var topics = (results[0].topics || []).map(adaptTopic);
    var posts = (results[1].posts || []).map(adaptPost);
    return { topics: topics, posts: posts };
  }

  async function createTopic(name, description) {
    var data = await jpost("/api/topics", { name: name, description: description || "" });
    return data.topic;
  }

  async function addLink(url, topic) {
    var data = await jpost("/api/add", { url: url, topic: topic });
    if (!data.taskId) throw new Error("后端未返回任务号");
    return data.taskId;
  }

  // 批量收藏：POST /api/add {urls:[...], topic} -> {tasks:[{url, taskId}]}
  async function addLinks(urls, topic) {
    var data = await jpost("/api/add", { urls: urls, topic: topic });
    if (!Array.isArray(data.tasks)) throw new Error("后端未返回批量任务列表");
    return data.tasks;
  }

  // ===== 待采集队列：只存链接，不开浏览器，等按「开始采集」再逐条跑 =====
  // 后端返回的快照统一是 {items, draining, stopping, queued}
  async function queueLinks(urls, topic) {
    return jpost("/api/add", { urls: urls, topic: topic, defer: true });
  }
  async function getQueue() { return jget("/api/queue"); }
  async function startQueue() { return jpost("/api/queue/start"); }
  async function stopQueue() { return jpost("/api/queue/stop"); }
  async function retryQueued(id) { return jpost("/api/queue/" + encodeURIComponent(id) + "/retry"); }
  async function removeQueued(id) { return jsend("DELETE", "/api/queue/" + encodeURIComponent(id)); }
  async function clearQueue() { return jsend("DELETE", "/api/queue"); }

  // 删除帖子：withMedia 为真时连本地媒体文件一起删（?media=1）
  async function deletePost(uid, withMedia) {
    var path = "/api/posts/" + encodeURIComponent(uid) + (withMedia ? "?media=1" : "");
    return jsend("DELETE", path);
  }

  // 编辑帖子：fields 支持 {title, body, summary, keywords(数组), supplement}
  // 返回适配后的最新帖子（后端返回 {post: ...}）
  async function updatePost(uid, fields) {
    var data = await jsend("PATCH", "/api/posts/" + encodeURIComponent(uid), fields || {});
    return data.post ? adaptPost(data.post) : null;
  }

  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function pollTask(taskId, onTick) {
    for (var i = 0; i < 240; i++) {
      var t;
      try { t = await jget("/api/task/" + encodeURIComponent(taskId)); }
      catch (e) { await wait(1500); continue; }
      if (typeof onTick === "function") onTick(t);
      if (t.stage === "done") return t;
      if (t.stage === "error") throw new Error(t.message || "处理失败");
      await wait(1500);
    }
    throw new Error("处理超时，请稍后刷新页面查看");
  }

  window.TVApi = {
    loadAll: loadAll,
    createTopic: createTopic,
    addLink: addLink,
    addLinks: addLinks,
    pollTask: pollTask,
    deletePost: deletePost,
    updatePost: updatePost,
    adaptPost: adaptPost,
    abs: abs,
    queueLinks: queueLinks,
    getQueue: getQueue,
    startQueue: startQueue,
    stopQueue: stopQueue,
    retryQueued: retryQueued,
    removeQueued: removeQueued,
    clearQueue: clearQueue,
  };
})();
