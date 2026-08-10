/* 「复制给 AI」的文本构造。
 *
 * 解决的问题：你在这个页面上看到一张卡片，想让某个 AI 知道你说的是这张而不是另一张。
 * 点一下按钮，这条的内容进剪贴板，粘到哪都自足——不需要那个 AI 有读你磁盘的能力。
 *
 * 媒体本身没法跟着剪贴板走（网页写不了文件引用），所以附一组本机绝对路径：
 * 有 shell 的 Agent 直接就能用，人可以拿去 open -R 定位到文件。
 */
(function () {
  "use strict";

  var meta = { vaultRoot: "" };

  function loadMeta() {
    return fetch("/api/meta")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.vaultRoot) meta.vaultRoot = d.vaultRoot; })
      .catch(function () { /* 拿不到就退化成相对路径，不影响正文 */ });
  }

  function absPath(rel) {
    if (!rel) return "";
    if (rel.charAt(0) === "/") return rel;
    return meta.vaultRoot ? meta.vaultRoot + "/" + rel : rel;
  }

  function fmtStats(s) {
    if (!s) return "";
    var parts = [];
    var names = { views: "浏览", likes: "点赞", collects: "收藏", comments: "评论", shares: "转发" };
    Object.keys(names).forEach(function (k) {
      if (s[k] !== undefined && s[k] !== null && s[k] !== "") parts.push(names[k] + " " + s[k]);
    });
    if (!parts.length) return "";
    var when = s.capturedAt ? new Date(s.capturedAt * 1000).toLocaleDateString("zh-CN") : "";
    return parts.join(" · ") + (when ? "（" + when + " 快照，不随时间更新）" : "");
  }

  function section(title, body) {
    return body && String(body).trim() ? "\n## " + title + "\n\n" + String(body).trim() + "\n" : "";
  }

  /* opts: {topicName, withTranscript} */
  function buildClipText(post, opts) {
    opts = opts || {};
    var p = post || {};
    var out = "# " + (p.title || "(无标题)") + "\n\n";

    var who = [];
    var platform = (window.PLATFORMS && window.PLATFORMS[p.platform] && window.PLATFORMS[p.platform].label) || p.platform || "";
    if (platform) who.push(platform);
    if (p.author) who.push(p.author);
    if (p.published) who.push(p.published);
    if (who.length) out += "- 出处：" + who.join(" · ") + "\n";
    if (p.sourceLink) out += "- 原帖：" + p.sourceLink + "\n";
    out += "- 收藏于：Quarry" + (opts.topicName ? " / 课题「" + opts.topicName + "」" : "") +
           (p.number ? " #" + p.number : "") + "\n";
    var st = fmtStats(p.stats);
    if (st) out += "- 互动：" + st + "\n";
    if (p.keywords && p.keywords.length) out += "- 关键词：" + p.keywords.join("、") + "\n";

    out += section("摘要", p.summary);
    out += section("正文", p.body);
    out += section("平台原文", p.originalText);
    out += section("补充", p.supplement);
    if (opts.withTranscript !== false) out += section("口播转写", p.transcript);

    var files = [];
    if (p.mediaPath) files.push("- 视频/图片：" + absPath(p.mediaPath));
    if (p.imagePath) files.push("- 封面：" + absPath(p.imagePath));
    if (p.audioPath) files.push("- 音频：" + absPath(p.audioPath));
    if (p.transcriptSrtPath) files.push("- 字幕：" + absPath(p.transcriptSrtPath));
    if (p.transcriptMdPath) files.push("- 口播词：" + absPath(p.transcriptMdPath));
    if (p.framesDir) {
      files.push("- 关键帧" + (p.frameCount ? "（" + p.frameCount + " 张）" : "") + "：" +
                 absPath(p.framesDir) + "/");
    }
    if (files.length) {
      out += "\n## 本机文件\n\n" + files.join("\n") + "\n";
      out += "\n> 这些是本机绝对路径。视频没法跟着剪贴板走，需要看画面的话按路径打开，" +
             "或让有文件访问能力的 Agent 直接读。\n";
    }
    return out;
  }

  function legacyCopy(text) {
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        ok ? resolve() : reject(new Error("execCommand 复制失败"));
      } catch (e) { reject(e); }
    });
  }

  function writeClipboard(text) {
    // API 存在不等于能用：局域网访问走 http://192.168.x.x 时不是安全上下文，
    // 权限策略也可能直接拒绝。所以是「调用失败再兜底」，不是「没有 API 才兜底」。
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () {
        return legacyCopy(text);
      });
    }
    return legacyCopy(text);
  }

  loadMeta();

  window.TVClip = {
    buildClipText: buildClipText,
    writeClipboard: writeClipboard,
    absPath: absPath,
    meta: meta,
    reloadMeta: loadMeta,
  };
})();
