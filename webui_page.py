"""
webui_page.py — 网页版单页界面

独立于 webui.py 存放 HTML/CSS/JS，便于维护与替换。render_page() 会把当前设置里的
背景色/主题色推导成整套配色后注入模板，保持与桌面版一致的换肤算法。

页面协议(WebSocket)见 webui.py 顶部说明；前端只依赖这些消息类型。
"""

from __future__ import annotations

from typing import Mapping

from agent_core import APP_VERSION


def _hex2rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb2hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, channel))) for channel in rgb)


def _darken(value: str, factor: float) -> str:
    return _rgb2hex(tuple(channel * factor for channel in _hex2rgb(value)))


def _blend(first: str, second: str, alpha: float) -> str:
    one, two = _hex2rgb(first), _hex2rgb(second)
    return _rgb2hex(tuple(one[i] * alpha + two[i] * (1 - alpha) for i in range(3)))


def _palette(accent: str, background: str) -> dict[str, str]:
    """主题色 + 背景色 -> 整套配色(与 UiColors.cs 使用同一套公式)。"""
    try:
        rgb = _hex2rgb(background)
        luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
        is_dark = luminance < 128
        palette = {
            "--bg": background,
            "--accent": accent,
            "--accent2": _darken(accent, 0.62),
            "--user-bubble": _blend(accent, background, 0.22),
            "--badge": _blend(accent, background, 0.14),
        }
        if is_dark:
            palette.update({
                "--panel": _blend(background, "#12171E", 0.65),
                "--panel2": _blend(background, "#161D26", 0.8),
                "--border": "#232C37",
                "--text": "#E6EDF3",
                "--muted": "#8B98A5",
                "--code-bg": _blend(background, "#0D1117", 0.85),
                "--code-text": "#C9D4DE",
            })
        else:
            palette.update({
                "--panel": _blend(background, "#F6F8FA", 0.65),
                "--panel2": _blend(background, "#FFFFFF", 0.8),
                "--border": "#D0D7DE",
                "--text": "#1F2328",
                "--muted": "#57606A",
                "--code-bg": _blend(background, "#F6F8FA", 0.85),
                "--code-text": "#24292F",
            })
        return palette
    except (ValueError, IndexError):
        return {
            "--bg": "#0C1117", "--panel": "#10151C", "--panel2": "#161D26",
            "--border": "#232C37", "--text": "#E6EDF3", "--muted": "#8B98A5",
            "--code-bg": "#0D1117", "--code-text": "#C9D4DE",
            "--accent": "#4D9FFF", "--accent2": "#1F6FEB",
            "--user-bubble": "#1B3550", "--badge": "#14243A",
        }


def render_page(settings: Mapping[str, object], tool_count: int = 0) -> str:
    accent = str(settings.get("accent") or "#4D9FFF")
    background = str(settings.get("background") or "#0C1117")
    model = str(settings.get("model") or "")
    configured = "true" if settings.get("has_api_key") else "false"

    page = _TEMPLATE
    for key, value in _palette(accent, background).items():
        page = page.replace(key.upper().replace("--", "__").replace("-", "_") + "__", value)
    page = page.replace("__MODEL__", model)
    page = page.replace("__TOOL_COUNT__", str(int(tool_count)))
    page = page.replace("__VERSION__", APP_VERSION)
    page = page.replace("__CONFIGURED__", configured)
    return page


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Agent</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text y='26' font-size='26'>🦾</text></svg>">
<style>
:root {
  --bg: __BG__;
  --panel: __PANEL__;
  --panel2: __PANEL2__;
  --border: __BORDER__;
  --text: __TEXT__;
  --muted: __MUTED__;
  --accent: __ACCENT__;
  --accent2: __ACCENT2__;
  --user-bubble: __USER_BUBBLE__;
  --badge: __BADGE__;
  --code-bg: __CODE_BG__;
  --code-text: __CODE_TEXT__;
  --danger: #F85149;
  --green: #3FB950;
  --radius: 12px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; }
body {
  background: var(--bg); color: var(--text);
  font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", system-ui, sans-serif;
  display: flex; overflow: hidden; font-size: 14px;
  -webkit-font-smoothing: antialiased;
}
button { font-family: inherit; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 6px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }
::-webkit-scrollbar-track { background: transparent; }

/* ---------------- 侧栏 ---------------- */
#sidebar {
  width: 252px; min-width: 252px; background: var(--panel);
  border-right: 1px solid var(--border); display: flex; flex-direction: column;
}
.brand { display: flex; align-items: center; gap: 10px; padding: 16px 16px 12px; }
.brand .logo { font-size: 20px; }
.brand-name { font-size: 14px; font-weight: 700; }
.brand-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
#new-chat {
  margin: 0 12px 12px; padding: 9px; border: 1px solid var(--border);
  border-radius: 9px; background: var(--panel2); color: var(--text);
  cursor: pointer; font-size: 13px; transition: .15s;
}
#new-chat:hover { border-color: var(--accent); color: var(--accent); }
#sessions { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
.session {
  display: flex; align-items: center; gap: 6px; padding: 9px 10px; margin-bottom: 2px;
  border-radius: 8px; cursor: pointer; color: var(--muted); font-size: 13px;
}
.session .name { flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.session:hover { background: var(--panel2); color: var(--text); }
.session.active { background: var(--badge); color: var(--accent); }
.session .del {
  visibility: hidden; border: none; background: transparent; color: var(--muted);
  cursor: pointer; font-size: 14px; line-height: 1; padding: 0 2px; border-radius: 4px;
}
.session:hover .del { visibility: visible; }
.session .del:hover { color: var(--danger); }
.side-foot {
  padding: 10px 16px 14px; border-top: 1px solid var(--border);
  font-size: 11px; color: var(--muted); line-height: 1.7;
}
.side-foot b { color: var(--text); font-weight: 600; }

/* ---------------- 主区 ---------------- */
#main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
header {
  height: 50px; border-bottom: 1px solid var(--border); background: var(--panel);
  display: flex; align-items: center; gap: 10px; padding: 0 16px; flex-shrink: 0;
}
header .title { font-size: 13.5px; font-weight: 700; }
.badge {
  font-size: 11px; padding: 2px 9px; border-radius: 10px;
  background: var(--badge); color: var(--accent);
}
.status { margin-left: auto; font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.status .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); }
.status.busy .dot { background: var(--accent); animation: pulse 1.1s infinite; }
@keyframes pulse { 50% { opacity: .25; } }
.icon-btn {
  border: 1px solid var(--border); background: var(--panel2); color: var(--muted);
  border-radius: 8px; width: 32px; height: 32px; cursor: pointer; font-size: 15px;
}
.icon-btn:hover { color: var(--accent); border-color: var(--accent); }

#messages { flex: 1; overflow-y: auto; padding: 22px 0 10px; scroll-behavior: smooth; }
.msg { max-width: 820px; margin: 0 auto 18px; padding: 0 22px; display: flex; gap: 10px; }
.msg.user { justify-content: flex-end; }
.msg .avatar {
  width: 30px; height: 30px; border-radius: 9px; flex-shrink: 0;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  display: flex; align-items: center; justify-content: center; font-size: 14px; color: #fff;
}
.msg .col { min-width: 0; flex: 1; }
.msg .who { font-size: 11px; color: var(--muted); margin: 0 0 5px 2px; }
.msg.user .bubble {
  max-width: 76%; padding: 10px 14px; border-radius: 14px 14px 4px 14px;
  background: var(--user-bubble); line-height: 1.65; white-space: pre-wrap;
  word-break: break-word; overflow-wrap: anywhere;
}
.msg.assistant .bubble {
  padding: 11px 15px; border-radius: 4px 14px 14px 14px;
  background: var(--panel2); border: 1px solid var(--border);
  line-height: 1.7; word-break: break-word; overflow-wrap: anywhere;
}
.bubble p { margin: 0 0 8px; }
.bubble p:last-child { margin-bottom: 0; }
.bubble h1, .bubble h2, .bubble h3, .bubble h4, .bubble h5, .bubble h6 {
  margin: 14px 0 6px; line-height: 1.4; font-size: 1em; font-weight: 600;
}
.bubble h1 { font-size: 1.34em; font-weight: 700; }
.bubble h2 { font-size: 1.22em; font-weight: 700; }
.bubble h3 { font-size: 1.12em; }
.bubble h4 { font-size: 1.02em; }
.bubble ul, .bubble ol { margin: 4px 0 8px; padding-left: 22px; }
.bubble li { margin: 2px 0; }
.bubble code {
  background: var(--code-bg); color: var(--code-text); padding: 1px 5px;
  border-radius: 4px; font-size: 12.5px; font-family: Consolas, "Cascadia Mono", monospace;
}
.bubble pre { margin: 8px 0; background: var(--code-bg); border: 1px solid var(--border);
  border-radius: 9px; overflow: hidden; }
.bubble pre code { display: block; padding: 10px 12px; background: none; overflow-x: auto;
  font-size: 12.5px; line-height: 1.55; white-space: pre; }
.code-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 10px; border-bottom: 1px solid var(--border);
  font-size: 11px; color: var(--muted); background: var(--panel);
}
.code-head .copy { border: none; background: none; color: var(--muted); cursor: pointer; font-size: 11px; }
.code-head .copy:hover { color: var(--accent); }
.bubble blockquote { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; color: var(--muted); margin: 6px 0; }
.bubble table { border-collapse: collapse; margin: 8px 0; font-size: 12.5px; display: block; overflow-x: auto; }
.bubble th, .bubble td { border: 1px solid var(--border); padding: 5px 9px; text-align: left; }
.bubble th { background: var(--panel); font-weight: 600; }
.bubble a { color: var(--accent); text-decoration: none; }
.bubble a:hover { text-decoration: underline; }
.cursor { color: var(--accent); animation: pulse 1s infinite; }

/* ---------------- 工具卡片 ---------------- */
.tools { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.tool {
  border: 1px solid var(--border); border-radius: 9px; background: var(--panel);
  font-size: 12px; overflow: hidden;
}
.tool summary {
  display: flex; align-items: center; gap: 8px; padding: 8px 11px; cursor: pointer;
  list-style: none; user-select: none;
}
.tool summary::-webkit-details-marker { display: none; }
.tool summary:hover { background: var(--panel2); }
.tool .tname { color: var(--accent); font-weight: 600; }
.tool .targs {
  color: var(--muted); font-family: Consolas, monospace; font-size: 11px;
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1;
}
.tool .tstate { color: var(--muted); font-size: 11px; }
.tool.done .tstate { color: var(--green); }
.tool.failed .tstate { color: var(--danger); }
.tool pre {
  border-top: 1px solid var(--border); padding: 9px 11px; max-height: 280px;
  overflow: auto; white-space: pre-wrap; word-break: break-word;
  font-family: Consolas, monospace; font-size: 11.5px; color: var(--code-text);
}
.mini-spin {
  width: 11px; height: 11px; border: 2px solid var(--border); border-top-color: var(--accent);
  border-radius: 50%; animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ---------------- 输入区 ---------------- */
.composer { border-top: 1px solid var(--border); background: var(--panel); padding: 12px 22px 14px; flex-shrink: 0; }
.composer-box {
  max-width: 820px; margin: 0 auto; display: flex; gap: 8px; align-items: flex-end;
  background: var(--panel2); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 8px; transition: border-color .15s;
}
.composer-box:focus-within { border-color: var(--accent); }
#input {
  flex: 1; background: transparent; border: none; outline: none; resize: none;
  color: var(--text); font-size: 14px; line-height: 1.6; max-height: 160px; padding: 4px 6px;
}
#input::placeholder { color: var(--muted); }
.send, .stop {
  border: none; border-radius: 9px; padding: 9px 18px; cursor: pointer;
  font-size: 13px; font-weight: 600; color: #fff; white-space: nowrap;
}
.send { background: var(--accent2); }
.send:hover:not(:disabled) { background: var(--accent); }
.send:disabled { opacity: .45; cursor: not-allowed; }
.stop { background: var(--danger); }
.stop:hover { filter: brightness(1.1); }
.hint { max-width: 820px; margin: 7px auto 0; font-size: 11px; color: var(--muted); text-align: center; }

/* ---------------- 顶部提示/弹窗 ---------------- */
.banner {
  background: #3D2B1F; color: #FFD9A0; text-align: center; font-size: 13px;
  padding: 8px 12px; border-bottom: 1px solid #5A3B22;
}
.banner b { color: #FFB86B; }
.banner button {
  margin-left: 10px; border: 1px solid #5A3B22; background: #4A3426; color: #FFD9A0;
  border-radius: 6px; padding: 2px 10px; cursor: pointer; font-size: 12px;
}
.modal { position: fixed; inset: 0; background: rgba(0,0,0,.55); display: flex;
  align-items: center; justify-content: center; z-index: 100; }
.modal[hidden] { display: none; }
.modal-box {
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px 22px; width: 400px; max-width: 92vw; max-height: 88vh; overflow-y: auto;
}
.modal-box h3 { margin: 0 0 14px; font-size: 15px; }
.field { margin-bottom: 12px; }
.field label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 5px; }
.field input[type=text], .field input[type=password], .field select {
  width: 100%; background: var(--panel2); border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 8px 10px; font-size: 13px; outline: none;
}
.field input:focus, .field select:focus { border-color: var(--accent); }
.field .note { font-size: 11px; color: var(--muted); margin-top: 4px; }
.row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.row input[type=color] { width: 42px; height: 30px; border: 1px solid var(--border);
  border-radius: 6px; background: transparent; cursor: pointer; padding: 2px; }
.preset { background: var(--panel2); border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; padding: 5px 10px; cursor: pointer; font-size: 12px; }
.preset:hover { color: var(--accent); border-color: var(--accent); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
.modal-actions button { background: var(--panel2); border: 1px solid var(--border);
  color: var(--text); border-radius: 8px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.modal-actions button.primary { background: var(--accent2); border-color: var(--accent2); color: #fff; font-weight: 600; }
#toast {
  position: fixed; left: 50%; bottom: 84px; transform: translateX(-50%) translateY(20px);
  background: var(--panel2); border: 1px solid var(--border); color: var(--text);
  padding: 8px 16px; border-radius: 9px; font-size: 12.5px; opacity: 0;
  transition: .2s; pointer-events: none; z-index: 200;
}
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
.empty { color: var(--muted); text-align: center; font-size: 13px; margin-top: 60px; line-height: 2; }
.empty .big { font-size: 30px; display: block; margin-bottom: 8px; }

@media (max-width: 720px) {
  #sidebar { display: none; }
  .msg { padding: 0 12px; }
}
</style>
</head>
<body>
<div id="banner" class="banner" hidden>⚠️ 尚未配置 API Key，请点右上角 <b>⚙</b> 填写后开始对话<button onclick="openSettings()">立即设置</button></div>

<aside id="sidebar">
  <div class="brand">
    <span class="logo">🦾</span>
    <div>
      <div class="brand-name">AI Agent</div>
      <div class="brand-sub">本地系统智能体</div>
    </div>
  </div>
  <button id="new-chat">＋ 新建对话</button>
  <div id="sessions"></div>
  <div class="side-foot">
    <div>模型: <b id="foot-model">__MODEL__</b></div>
    <div>工具: <b id="foot-tools">__TOOL_COUNT__</b> 个系统级 MCP</div>
    <div>版本 v__VERSION__ · 设置与桌面版互通</div>
  </div>
</aside>

<main id="main">
  <header>
    <span class="title">AI Agent 工作台</span>
    <span class="badge" id="model-badge">__MODEL__</span>
    <span class="status" id="status"><span class="dot"></span><span id="status-text">连接中…</span></span>
    <button class="icon-btn" id="cfg-btn" title="设置">⚙</button>
  </header>
  <section id="messages"></section>
  <footer class="composer">
    <div class="composer-box">
      <textarea id="input" rows="1" placeholder="输入消息，Enter 发送，Shift+Enter 换行…"></textarea>
      <button class="send" id="send-btn" disabled>发送</button>
      <button class="stop" id="stop-btn" hidden>■ 停止</button>
    </div>
    <div class="hint">Agent 可执行 Python / Shell、读写文件、管理进程；危险操作会先向你确认</div>
  </footer>
</main>

<div id="modal" class="modal" hidden>
  <div class="modal-box">
    <h3>⚙ 设置</h3>
    <div class="field">
      <label>模型名称</label>
      <select id="cfg-model"></select>
    </div>
    <div class="field">
      <label>API 地址</label>
      <input id="cfg-baseurl" type="text" placeholder="https://api.deepseek.com">
    </div>
    <div class="field">
      <label>API 密钥</label>
      <input id="cfg-apikey" type="password" placeholder="留空保持不变">
      <div class="note" id="cfg-keynote"></div>
    </div>
    <div class="field">
      <label>主题色</label>
      <div class="row">
        <input id="cfg-accent" type="color" value="#4D9FFF">
        <button class="preset" data-color="#4D9FFF">蓝</button>
        <button class="preset" data-color="#3FB950">绿</button>
        <button class="preset" data-color="#A371F7">紫</button>
        <button class="preset" data-color="#F0883E">橙</button>
      </div>
    </div>
    <div class="field">
      <label>背景色</label>
      <div class="row">
        <input id="cfg-bg" type="color" value="#0C1117">
        <button class="preset" data-bg="#0C1117">深色</button>
        <button class="preset" data-bg="#FFFFFF">白色</button>
        <button class="preset" data-bg="#F0F2F5">浅灰</button>
      </div>
      <div class="note">背景偏亮自动切换浅色主题，偏暗切换深色主题；与桌面版共享同一份 settings.json。</div>
    </div>
    <div class="modal-actions">
      <button id="cfg-cancel">取消</button>
      <button class="primary" id="cfg-save">保存</button>
    </div>
  </div>
</div>
<div id="toast"></div>

<script>
"use strict";

/* ================= 状态 ================= */
const state = {
  sid: null,
  sessions: [],
  streaming: false,
  runningSid: null,
  acc: "",
  contentEl: null,
  toolsEl: null,
  cards: [],
  stick: true,
  toolCount: __TOOL_COUNT__,
  model: "__MODEL__",
  ws: null,
  retry: 0,
  reconnectTimer: null,
  renderPending: false,
};

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");
const inputEl = $("input");
const sendBtn = $("send-btn");
const stopBtn = $("stop-btn");
const statusEl = $("status");
const statusTextEl = $("status-text");

/* ================= 基础工具 ================= */
function esc(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function setStatus(text, busy) {
  statusTextEl.textContent = text;
  statusEl.classList.toggle("busy", !!busy);
}

let toastTimer = null;
function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2200);
}

function nearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 80;
}
function scrollToBottom(force) {
  if (force || state.stick) messagesEl.scrollTop = messagesEl.scrollHeight;
}
messagesEl.addEventListener("scroll", () => { state.stick = nearBottom(); });

function showEmpty() {
  if (messagesEl.querySelector(".msg")) return;
  messagesEl.innerHTML = '<div class="empty"><span class="big">🦾</span>'
    + '可以直接让 Agent 操作这台电脑<br>例如：整理下载目录、查端口占用、批量改文件名</div>';
}
function clearMessages() {
  messagesEl.innerHTML = "";
  state.acc = "";
  state.contentEl = null;
  state.toolsEl = null;
  state.cards = [];
  showEmpty();
}

/* ================= Markdown ================= */
function inlineMd(text) {
  let html = esc(text);
  html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
}

function renderMarkdown(source) {
  const blocks = [];
  let text = String(source || "").replace(/\r\n/g, "\n");
  text = text.replace(/```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g, (match, lang, code) => {
    const label = (lang || "code").trim() || "code";
    blocks.push('<div class="code-wrap"><div class="code-head"><span>' + esc(label)
      + '</span><button class="copy" onclick="copyCode(this)">复制</button></div>'
      + '<pre><code>' + esc(code.replace(/\n$/, "")) + '</code></pre></div>');
    return "\u0000" + (blocks.length - 1) + "\u0000";
  });

  const lines = text.split("\n");
  let html = "";
  let para = [];
  let listType = null;
  let listItems = [];

  const flushPara = () => {
    if (para.length) { html += "<p>" + para.join("<br>") + "</p>"; para = []; }
  };
  const flushList = () => {
    if (listType) {
      html += "<" + listType + ">" + listItems.join("") + "</" + listType + ">";
      listType = null; listItems = [];
    }
  };
  const flushAll = () => { flushPara(); flushList(); };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.replace(/\s+$/, "");
    const trimmed = line.trim();

    if (!trimmed) { flushAll(); continue; }

    if (/^\u0000\d+\u0000$/.test(trimmed)) {
      flushAll();
      html += blocks[Number(trimmed.replace(/\u0000/g, ""))] || "";
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushAll();
      const level = Math.min(heading[1].length + 1, 6);
      html += "<h" + level + ">" + inlineMd(heading[2]) + "</h" + level + ">";
      continue;
    }

    if (/^(---+|\*\*\*+|___+)$/.test(trimmed)) {
      flushAll();
      html += "<hr>";
      continue;
    }

    // 表格: 表头 + 分隔行 + 若干净数据行
    if (trimmed.indexOf("|") >= 0 && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1])) {
      flushAll();
      const parseRow = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "")
        .split("|").map((cell) => cell.trim());
      const headers = parseRow(line);
      let table = "<table><thead><tr>"
        + headers.map((cell) => "<th>" + inlineMd(cell) + "</th>").join("") + "</tr></thead><tbody>";
      i += 2;
      while (i < lines.length && lines[i].indexOf("|") >= 0 && lines[i].trim()) {
        const cells = parseRow(lines[i]);
        table += "<tr>" + cells.map((cell) => "<td>" + inlineMd(cell) + "</td>").join("") + "</tr>";
        i++;
      }
      i--;
      html += table + "</tbody></table>";
      continue;
    }

    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) {
      flushAll();
      html += "<blockquote>" + inlineMd(quote[1]) + "</blockquote>";
      continue;
    }

    const ordered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    const unordered = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (ordered || unordered) {
      flushPara();
      const type = ordered ? "ol" : "ul";
      if (listType !== type) { flushList(); listType = type; }
      listItems.push("<li>" + inlineMd(ordered ? ordered[2] : unordered[1]) + "</li>");
      continue;
    }

    if (listType) { flushList(); }
    para.push(inlineMd(trimmed));
  }
  flushAll();
  html = html.replace(/\u0000(\d+)\u0000/g, (match, index) => blocks[Number(index)] || "");
  return html || "<p></p>";
}

function copyCode(button) {
  const wrap = button.closest(".code-wrap");
  const code = wrap ? wrap.querySelector("code") : null;
  if (!code) return;
  const text = code.textContent;
  const done = () => { button.textContent = "已复制"; setTimeout(() => { button.textContent = "复制"; }, 1500); };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}
function fallbackCopy(text, done) {
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast("复制失败"); }
  document.body.removeChild(area);
}

/* ================= 消息渲染 ================= */
function addUserMessage(text) {
  const row = document.createElement("div");
  row.className = "msg user";
  row.innerHTML = '<div class="bubble"></div>';
  row.querySelector(".bubble").textContent = text;
  messagesEl.appendChild(row);
  state.stick = true;
  scrollToBottom(true);
}

function ensureAssistant() {
  if (state.contentEl) return;
  const empty = messagesEl.querySelector(".empty");
  if (empty) empty.remove();
  const row = document.createElement("div");
  row.className = "msg assistant";
  row.innerHTML = '<div class="avatar">🤖</div>'
    + '<div class="col"><div class="who">AI Agent</div><div class="bubble">'
    + '<div class="content"></div><div class="tools"></div></div></div>';
  messagesEl.appendChild(row);
  state.contentEl = row.querySelector(".content");
  state.toolsEl = row.querySelector(".tools");
  state.cards = [];
  scrollToBottom();
}

function paintAssistant() {
  state.renderPending = false;
  if (!state.contentEl) return;
  const cursor = state.streaming ? '<span class="cursor">▍</span>' : "";
  const wasStick = state.stick;
  state.contentEl.innerHTML = renderMarkdown(state.acc) + cursor;
  if (wasStick) scrollToBottom(true);
}
function schedulePaint() {
  if (state.renderPending) return;
  state.renderPending = true;
  requestAnimationFrame(paintAssistant);
}

function addToolCard(name, argsText, callId) {
  ensureAssistant();
  const pretty = prettyJson(argsText);
  const summary = argsText.replace(/\s+/g, " ").slice(0, 90);
  const card = document.createElement("details");
  card.className = "tool";
  card.innerHTML = '<summary><span class="tstate"><span class="mini-spin"></span></span>'
    + '<span class="tname">' + esc(name) + '</span>'
    + '<span class="targs" title="' + esc(summary) + '">' + esc(summary) + '</span></summary>'
    + '<pre class="targs-pre">' + esc(pretty) + '</pre>'
    + '<pre class="tresult">(等待结果…)</pre>';
  state.toolsEl.appendChild(card);
  state.cards.push({ el: card, id: callId || null, done: false });
  scrollToBottom();
}

function finishToolCard(callId, content) {
  let target = null;
  if (callId) target = state.cards.find((c) => c.id === callId);
  if (!target) target = state.cards.filter((c) => !c.done).pop();
  if (!target) return;
  target.done = true;
  const failed = /^(执行 |未执行 |执行出错)/.test(String(content || ""));
  target.el.classList.add(failed ? "failed" : "done");
  const body = target.el.querySelector(".tresult");
  if (body) body.textContent = content && content.trim() ? content : "(无输出)";
  const spin = target.el.querySelector(".tstate");
  if (spin) spin.textContent = failed ? "×" : "✓";
}

function prettyJson(text) {
  if (!text) return "{}";
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch (e) { return String(text); }
}

function addErrorBubble(message) {
  const row = document.createElement("div");
  row.className = "msg assistant";
  row.innerHTML = '<div class="avatar" style="background:var(--danger)">!</div>'
    + '<div class="col"><div class="bubble" style="border-color:var(--danger)"></div></div>';
  row.querySelector(".bubble").textContent = "⚠️ " + message;
  messagesEl.appendChild(row);
  scrollToBottom(true);
}

function renderHistory(list) {
  clearMessages();
  (list || []).forEach((message) => {
    if (message.role === "user") {
      addUserMessage(message.content || "");
    } else if (message.role === "assistant" && message.content) {
      // 每条历史助手消息都要新建气泡，不能复用上一条的容器
      state.contentEl = null;
      state.toolsEl = null;
      state.cards = [];
      ensureAssistant();
      state.acc = message.content;
      state.streaming = false;
      paintAssistant();
    }
  });
  state.stick = true;
  scrollToBottom(true);
  showEmpty();
}

/* ================= 会话列表 ================= */
function renderSessions(list) {
  state.sessions = list || [];
  const box = $("sessions");
  box.innerHTML = "";
  state.sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "session" + (session.sid === state.sid ? " active" : "");
    row.innerHTML = '<span class="name"></span><button class="del" title="删除会话">×</button>';
    row.querySelector(".name").textContent = session.title || "新对话";
    row.onclick = () => switchSession(session.sid);
    row.querySelector(".del").onclick = (event) => {
      event.stopPropagation();
      deleteSession(session.sid, session.title || "新对话");
    };
    box.appendChild(row);
  });
}

function newChat() {
  if (state.streaming) return toast("请先停止当前回复");
  sendJson({ type: "new_chat" });
}
function switchSession(sid) {
  if (!sid || sid === state.sid) return;
  if (state.streaming) return toast("请先停止当前回复");
  sendJson({ type: "switch", sid: sid });
}
function deleteSession(sid, title) {
  if (state.streaming && state.runningSid === sid) return toast("请先停止当前回复");
  if (!confirm('删除会话「' + title + '」？该操作不可恢复。')) return;
  sendJson({ type: "delete", sid: sid });
}

/* ================= 连接 ================= */
function wsUrl() {
  return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws";
}
function connect() {
  clearTimeout(state.reconnectTimer);
  setStatus("连接中…", true);
  let socket;
  try { socket = new WebSocket(wsUrl()); } catch (e) { scheduleReconnect(); return; }
  state.ws = socket;

  socket.onopen = () => {
    state.retry = 0;
    setStatus("已连接", false);
  };
  socket.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (e) { return; }
    handleMessage(message);
  };
  socket.onclose = () => {
    state.streaming = false;
    updateComposer();
    setStatus("连接断开，正在重连…", true);
    scheduleReconnect();
  };
  socket.onerror = () => { try { socket.close(); } catch (e) { } };
}
function scheduleReconnect() {
  clearTimeout(state.reconnectTimer);
  const delay = Math.min(15000, 1000 * Math.pow(1.6, state.retry++));
  state.reconnectTimer = setTimeout(connect, delay);
}
function sendJson(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    toast("连接未就绪，请稍后重试");
    return false;
  }
  state.ws.send(JSON.stringify(payload));
  return true;
}

function handleMessage(message) {
  const type = message.type;
  if (type === "ready") {
    state.toolCount = message.tools || 0;
    state.model = message.model || state.model;
    $("foot-tools").textContent = state.toolCount;
    $("foot-model").textContent = state.model;
    $("model-badge").textContent = state.model;
    return;
  }
  if (type === "session") {
    state.sid = message.sid;
    state.streaming = false;
    state.runningSid = null;
    renderSessions(message.sessions || []);
    clearMessages();
    updateComposer();
    return;
  }
  if (type === "sessions") {
    renderSessions(message.list || []);
    return;
  }
  if (type === "history") {
    if (message.sid && message.sid !== state.sid) return;
    state.streaming = false;
    state.runningSid = null;
    renderHistory(message.messages || []);
    updateComposer();
    setStatus("已连接", false);
    return;
  }
  if (message.sid && state.sid && message.sid !== state.sid) return;

  switch (type) {
    case "user_message":
      // 服务端回显用户消息: 本标签页与同一会话的其他标签页都据此渲染
      addUserMessage(message.content || "");
      state.streaming = true;
      state.runningSid = message.sid || state.sid;
      state.acc = "";
      state.contentEl = null;
      state.toolsEl = null;
      state.cards = [];
      state.stick = true;
      updateComposer();
      setStatus("正在思考…", true);
      break;
    case "token":
      if (!state.streaming) { state.streaming = true; state.runningSid = message.sid; }
      ensureAssistant();
      state.acc += message.content || "";
      updateComposer();
      setStatus("正在回复…", true);
      schedulePaint();
      break;
    case "tool_call":
      if (!state.streaming) { state.streaming = true; state.runningSid = message.sid; }
      ensureAssistant();
      addToolCard(message.name || "?", message.arguments || "", message.id);
      updateComposer();
      setStatus("正在执行工具…", true);
      break;
    case "tool_result":
      finishToolCard(message.id, message.content || "");
      setStatus("正在继续…", true);
      break;
    case "done":
      if (typeof message.content === "string" && !state.acc) state.acc = message.content;
      state.streaming = false;
      state.runningSid = null;
      if (state.contentEl) paintAssistant();
      updateComposer();
      setStatus(message.stopped ? "已停止" : "已连接", false);
      scrollToBottom(true);
      break;
    case "error":
      state.streaming = false;
      state.runningSid = null;
      if (state.contentEl && state.acc) paintAssistant();
      addErrorBubble(message.message || "未知错误");
      updateComposer();
      setStatus("出错了", false);
      break;
  }
}

/* ================= 输入 ================= */
function updateComposer() {
  const disabled = state.streaming || !state.sid;
  sendBtn.hidden = state.streaming;
  stopBtn.hidden = !state.streaming;
  sendBtn.disabled = disabled;
}
function autoGrow() {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
}
function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;
  if (!state.sid) return toast("会话尚未就绪，请稍候");
  if (state.streaming) return toast("请先停止当前回复");
  if (!sendJson({ type: "chat", sid: state.sid, content: text })) return;
  inputEl.value = "";
  autoGrow();
  state.streaming = true;
  state.runningSid = state.sid;
  state.acc = "";
  state.contentEl = null;
  state.toolsEl = null;
  state.cards = [];
  state.stick = true;
  updateComposer();
  setStatus("正在思考…", true);
}
function stopGeneration() {
  if (!state.streaming) return;
  sendJson({ type: "stop", sid: state.runningSid || state.sid });
  setStatus("正在停止…", true);
}

$("new-chat").onclick = newChat;
sendBtn.onclick = sendMessage;
stopBtn.onclick = stopGeneration;
inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    if (event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    sendMessage();
  }
});
inputEl.addEventListener("input", autoGrow);

/* ================= 设置 ================= */
const MODEL_PRESETS = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat",
  "deepseek-reasoner", "gpt-4o", "gpt-4o-mini"];

function openSettings() {
  fetch("/api/settings").then((response) => response.json()).then((settings) => {
    const select = $("cfg-model");
    select.innerHTML = "";
    const models = MODEL_PRESETS.slice();
    if (models.indexOf(settings.model) < 0) models.unshift(settings.model);
    models.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      if (name === settings.model) option.selected = true;
      select.appendChild(option);
    });
    $("cfg-baseurl").value = settings.base_url || "";
    $("cfg-apikey").value = "";
    $("cfg-apikey").placeholder = settings.has_api_key ? "已保存密钥（留空保持不变）" : "填写 API Key";
    if (settings.api_key_source === "env") {
      $("cfg-keynote").textContent = "当前密钥来自环境变量 OPENAI_API_KEY，优先级高于此处设置。";
    } else if (settings.has_api_key) {
      $("cfg-keynote").textContent = "当前密钥已保存在 settings.json。";
    } else {
      $("cfg-keynote").textContent = "尚未配置密钥，填写后即可对话。";
    }
    $("cfg-accent").value = settings.accent || "#4D9FFF";
    $("cfg-bg").value = settings.background || "#0C1117";
    $("modal").hidden = false;
  }).catch(() => toast("读取设置失败"));
}
function closeSettings() { $("modal").hidden = true; }

function applyTheme(accent, background) {
  const parse = (hex) => [0, 2, 4].map((i) => parseInt(hex.replace("#", "").substr(i, 2), 16));
  const toHex = (channels) => "#" + channels.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("");
  const blend = (a, b, alpha) => toHex(parse(a).map((c, i) => c * alpha + parse(b)[i] * (1 - alpha)));
  const darken = (hex, factor) => toHex(parse(hex).map((c) => c * factor));
  const rgb = parse(background);
  const isDark = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) < 128;
  const root = document.documentElement.style;
  root.setProperty("--bg", background);
  root.setProperty("--accent", accent);
  root.setProperty("--accent2", darken(accent, 0.62));
  root.setProperty("--user-bubble", blend(accent, background, 0.22));
  root.setProperty("--badge", blend(accent, background, 0.14));
  if (isDark) {
    root.setProperty("--panel", blend(background, "#12171E", 0.65));
    root.setProperty("--panel2", blend(background, "#161D26", 0.8));
    root.setProperty("--border", "#232C37");
    root.setProperty("--text", "#E6EDF3");
    root.setProperty("--muted", "#8B98A5");
    root.setProperty("--code-bg", blend(background, "#0D1117", 0.85));
    root.setProperty("--code-text", "#C9D4DE");
  } else {
    root.setProperty("--panel", blend(background, "#F6F8FA", 0.65));
    root.setProperty("--panel2", blend(background, "#FFFFFF", 0.8));
    root.setProperty("--border", "#D0D7DE");
    root.setProperty("--text", "#1F2328");
    root.setProperty("--muted", "#57606A");
    root.setProperty("--code-bg", blend(background, "#F6F8FA", 0.85));
    root.setProperty("--code-text", "#24292F");
  }
}

function saveSettings() {
  const body = {
    model: $("cfg-model").value.trim(),
    base_url: $("cfg-baseurl").value.trim(),
    accent: $("cfg-accent").value,
    background: $("cfg-bg").value
  };
  const key = $("cfg-apikey").value.trim();
  if (key) body.api_key = key;
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  }).then((response) => response.json()).then((result) => {
    if (!result.ok) { toast(result.error || "保存失败"); return; }
    applyTheme(result.accent, result.background);
    state.model = result.model;
    $("model-badge").textContent = result.model;
    $("foot-model").textContent = result.model;
    if (result.has_api_key) $("banner").hidden = true;
    if (result.restart_required) toast("端口已修改，需要重启后端后生效");
    else toast("设置已保存");
    closeSettings();
  }).catch(() => toast("保存失败"));
}

$("cfg-btn").onclick = openSettings;
$("cfg-cancel").onclick = closeSettings;
$("cfg-save").onclick = saveSettings;
$("modal").addEventListener("click", (event) => {
  if (event.target.id === "modal") closeSettings();
  const color = event.target.getAttribute && event.target.getAttribute("data-color");
  const bg = event.target.getAttribute && event.target.getAttribute("data-bg");
  if (color) $("cfg-accent").value = color;
  if (bg) $("cfg-bg").value = bg;
});

/* ================= 启动 ================= */
if (__CONFIGURED__ === false) $("banner").hidden = false;
showEmpty();
updateComposer();
connect();
</script>
</body>
</html>
"""
