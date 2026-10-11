/* AI Drama · 群聊剧情模拟 前端逻辑 */
"use strict";

const state = { sessions: [], activeId: null, config: null };

const $ = (sel) => document.querySelector(sel);
const AVATAR_COLORS = ["#4f8cff", "#7c5cff", "#3fb96f", "#e5a73c", "#e05d5d", "#3ba0a0", "#c06bd8", "#e07b4f"];
const avatarColor = {};
let avatarIdx = 0;
function colorOf(name) {
  if (!(name in avatarColor)) avatarColor[name] = AVATAR_COLORS[avatarIdx++ % AVATAR_COLORS.length];
  return avatarColor[name];
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
  } catch (e) {
    throw new Error("无法连接服务器：服务未启动或已停止。请先运行 start.bat 启动服务，再刷新页面重试。");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok) {
    const detail = data && (data.detail || data.message);
    throw new Error(typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : res.statusText));
  }
  return data;
}

let serverWasDown = false;
async function checkServer() {
  const el = $("#server-status");
  if (!el) return;
  try {
    await api("/api/config");
    el.classList.add("hidden");
    if (serverWasDown) {
      serverWasDown = false;
      await loadSessions();
      toast("服务器已重新连接");
    }
  } catch (e) {
    serverWasDown = true;
    el.classList.remove("hidden");
  }
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden", "err");
  if (isErr) t.classList.add("err");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4000);
}

/* ================= 初始化 ================= */
async function init() {
  await loadConfig();
  await loadSessions();
  bindEvents();
  checkServer();
  setInterval(checkServer, 10000);
}

async function loadConfig() {
  const c = await api("/api/config");
  state.config = c;
  $("#cfg-model").value = c.model;
  $("#cfg-temp").value = c.temperature;
  $("#cfg-timefmt").value = c.time_format || "date";
  $("#cfg-worldcheck").value = c.world_check_mode || "advisory";
  $("#cfg-baseurl").value = c.base_url || "https://api.deepseek.com";
  $("#cfg-char-temp").value = c.character_temperature ?? 1.0;
  $("#cfg-topp").value = c.top_p ?? 0.95;
  $("#cfg-freq").value = c.frequency_penalty ?? 0.4;
  $("#cfg-pres").value = c.presence_penalty ?? 0.2;
  $("#cfg-maxtok").value = c.max_tokens ?? 600;
  $("#cfg-antiai").checked = c.anti_ai_flavor !== false;
  $("#cfg-key").value = "";
  $("#cfg-key-status").textContent = c.key_loaded ? c.masked_key : "(未设置)";
  const errBox = $("#cfg-error");
  errBox.classList.toggle("hidden", !c.config_error);
  if (c.config_error) errBox.textContent = "配置错误：" + c.config_error;
}

async function loadSessions() {
  const data = await api("/api/sessions");
  state.sessions = data.sessions;
  state.activeId = data.active_id;
  renderSessions();
  if (state.activeId) {
    await refreshActive();
  } else {
    renderEmptyChat();
  }
}

/* ================= 会话 ================= */
function renderSessions() {
  const box = $("#session-list");
  box.innerHTML = "";
  if (!state.sessions.length) {
    box.innerHTML = '<div class="session-item" style="color:var(--text-dim)">暂无会话，点击「＋ 新建群聊」开始</div>';
    return;
  }
  for (const s of state.sessions) {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === state.activeId ? " active" : "");
    item.innerHTML = `
      <div class="s-name">
        <span>${escapeHtml(s.name)}</span>
        <span class="s-btns">
          <span class="s-item-btn gear" title="会话设置">⚙</span>
          <span class="s-item-btn del danger" title="删除会话（同时删除该世界全部记忆）">✕</span>
        </span>
      </div>
      <div class="s-meta"><span class="dot">●</span> ${escapeHtml(s.world_name || s.kb_path)}<br>
        <span>${s.characters} 角色 · ${s.transcript_len} 条消息</span></div>`;
    item.addEventListener("click", (e) => {
      if (e.target.classList.contains("gear")) {
        e.stopPropagation();
        openSessionSettings(s.id);
      } else if (e.target.classList.contains("del")) {
        e.stopPropagation();
        deleteSession(s.id);
      } else {
        activateSession(s.id);
      }
    });
    box.appendChild(item);
  }
}

async function activateSession(sid) {
  try {
    await api(`/api/sessions/${sid}/activate`, { method: "POST" });
  } catch (e) { toast(e.message, true); }
  state.activeId = sid;
  renderSessions();
  await refreshActive();
}

async function deleteSession(sid) {
  const s = state.sessions.find((x) => x.id === sid);
  if (!confirm(`确定删除群聊「${s ? s.name : sid}」吗？\n这会同时删除该世界的全部角色记忆与对话记录，且不可恢复。`)) return;
  try {
    await api(`/api/sessions/${sid}`, { method: "DELETE" });
    toast("会话已删除");
  } catch (e) { toast(e.message, true); }
  await loadSessions();
}

/* ================= 聊天区 ================= */
function renderEmptyChat() {
  $("#chat-title").textContent = "未选择会话";
  $("#chat-sub").textContent = "点击左侧「＋ 新建群聊」创建会话，或选择一个已有会话";
  $("#chat-chips").innerHTML = "";
  $("#messages").innerHTML = "";
}

/* 顶部信息：结构化 chips（U4：替代单行超长拼接），路径中段省略并带完整 title */
function renderChatChips(info) {
  const shorten = (p, keep = 16) => {
    p = p || "";
    return p.length > keep * 2 + 1 ? p.slice(0, keep) + "…" + p.slice(-keep) : p;
  };
  const chips = [
    ["世界", info.world_name || "—", ""],
    ["时间", info.time || "时间未定", ""],
    ["地点", info.location || "未知地点", info.location || ""],
    ["角色·消息", `${info.characters ?? 0} · ${info.transcript_len ?? 0}`, "角色数 · 消息数"],
    ["知识库", shorten(info.kb_path), info.kb_path || ""],
  ];
  $("#chat-chips").innerHTML = chips.map(([k, v, title]) =>
    `<span class="chip"${title ? ` title="${escapeHtml(title)}"` : ""}>`
    + `<b>${escapeHtml(k)}</b>${escapeHtml(String(v))}</span>`).join("");
}

/* 文本规范化 + 动作/对白分层（U6）：动作段降级渲染，避免"旁白化"观感 */
function renderSpeech(text) {
  const norm = String(text == null ? "" : text)
    .replace(/\r\n?/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  let out = "";
  let pos = 0;
  const re = /[（(][^）)\n]{0,80}[）)]/g;
  let m;
  while ((m = re.exec(norm)) !== null) {
    out += escapeHtml(norm.slice(pos, m.index));
    out += `<span class="act">${escapeHtml(m[0])}</span>`;
    pos = m.index + m[0].length;
  }
  out += escapeHtml(norm.slice(pos));
  return out;
}

function buildMsgEl(m, memCount, showTime = true) {
  const wrap = document.createElement("div");
  const role = m.role || "assistant";
  const timeSpan = showTime
    ? `<span>${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>`
    : "";
  if (role === "user") {
    wrap.className = "msg user";
    const bubble = document.createElement("div");
    bubble.className = "bubble speech";
    bubble.innerHTML = renderSpeech(m.content);
    wrap.appendChild(bubble);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `${timeSpan}<span>我</span>`;
    wrap.appendChild(meta);
  } else if (role === "narrator") {
    // 导演以独立身份发言（导演 Agent 的回复 = 场景描述）
    wrap.className = "msg director";
    const head = document.createElement("div");
    head.className = "msg-head";
    head.innerHTML = `<div class="avatar" style="background:#7c5cff">导</div>
      <span class="who">导演</span>`;
    const bubble = document.createElement("div");
    bubble.className = "bubble speech";
    bubble.innerHTML = renderSpeech(m.content);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `${timeSpan}<span class="role-tag">场景描述</span>`;
    wrap.appendChild(head);
    wrap.appendChild(bubble);
    wrap.appendChild(meta);
  } else if (role === "system") {
    wrap.className = "msg system";
    wrap.innerHTML = `<div class="bubble">${escapeHtml(m.content)}</div>`;
  } else {
    const name = m.speaker || "角色";
    wrap.className = "msg";
    const head = document.createElement("div");
    head.className = "msg-head";
    head.innerHTML = `<div class="avatar" style="background:${colorOf(name)}">${escapeHtml(name[0] || "?")}</div>
      <span class="who">${escapeHtml(name)}</span>`;
    const bubble = document.createElement("div");
    bubble.className = "bubble speech";
    bubble.innerHTML = renderSpeech(m.content);
    const metaHtml = `${timeSpan}`
      + `${memCount ? `<span class="memtag">🧠 +${memCount} 条记忆</span>` : ""}`;
    wrap.appendChild(head);
    wrap.appendChild(bubble);
    if (metaHtml.trim()) {
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = metaHtml;
      wrap.appendChild(meta);
    }
  }
  return wrap;
}

function appendMessage(m, memCount) {
  const box = $("#messages");
  // 同一分钟内连续消息只显示一次时间戳（U6）
  const now = new Date();
  const minute = `${now.getHours()}:${now.getMinutes()}`;
  const showTime = box.dataset.lastMinute !== minute;
  box.dataset.lastMinute = minute;
  box.appendChild(buildMsgEl(m, memCount, showTime));
  box.scrollTop = box.scrollHeight;
}

function renderTranscript(transcript) {
  const box = $("#messages");
  box.innerHTML = "";
  delete box.dataset.lastMinute;
  for (const m of transcript) appendMessage(m);
  box.scrollTop = box.scrollHeight;
}

function renderCurrentChat() {
  const mode = $("#mode-select").value;
  if (mode === "agent") {
    const agentName = $("#agent-select").value;
    if (agentName) loadSideChat(agentName);
    else renderTranscript([]);
  } else {
    renderTranscript(state.transcript || []);
  }
}

async function loadSideChat(agentName) {
  if (!state.activeId) return;
  const r = await api(`/api/sessions/${state.activeId}/side_chat/${encodeURIComponent(agentName)}`);
  const box = $("#messages");
  box.innerHTML = "";
  delete box.dataset.lastMinute;
  for (const m of (r.side_chat || [])) {
    if (m.role === "user") {
      appendMessage({ role: "user", content: m.content });
    } else {
      appendMessage({ role: "assistant", speaker: m.speaker || agentName, content: m.content });
    }
  }
  box.scrollTop = box.scrollHeight;
}

let typingEl = null;
function showTyping(label) {
  if (typingEl) hideTyping();
  typingEl = document.createElement("div");
  typingEl.className = "typing";
  typingEl.innerHTML = `<span class="spin"></span><span>${escapeHtml(label || "角色们正在思考…")}</span>`;
  $("#messages").appendChild(typingEl);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}
function hideTyping() {
  if (typingEl) { typingEl.remove(); typingEl = null; }
}

/* ================= 刷新当前会话视图 ================= */
async function refreshActive() {
  if (!state.activeId) return renderEmptyChat();
  const sid = state.activeId;
  const info = await api(`/api/sessions/${sid}/info`);
  $("#chat-title").textContent = `${info.name}`;
  $("#chat-sub").textContent = "";
  renderChatChips(info);
  const t = await api(`/api/sessions/${sid}/transcript`);
  state.transcript = t.transcript || [];
  renderCurrentChat();
  await refreshSidePanels();
}

async function refreshSidePanels() {
  if (!state.activeId) return;
  const sid = state.activeId;
  const [agents, chars, world] = await Promise.all([
    api(`/api/sessions/${sid}/agents`),
    api(`/api/sessions/${sid}/characters`),
    api(`/api/sessions/${sid}/world`),
  ]);
  renderCharacters(chars.characters);
  renderAgentPanel(agents.agents);
  renderWorld(world);
}

/* ================= Agent 面板 ================= */
const actionLabels = { pause: "暂停", resume: "恢复", destroy: "销毁" };

function renderCharacters(chars) {
  const box = $("#char-list");
  if (!box) return;
  box.innerHTML = "";
  if (!chars || !chars.length) {
    box.innerHTML = '<div style="color:var(--text-dim)">知识库中未发现角色档案</div>';
    return;
  }
  for (const c of chars) {
    const a = { name: c.name, status: c.status || "未实例化", emotion: "—", long_memory_count: c.long_memory_count || 0 };
    box.appendChild(buildCharacterCard(a, c.brief));
  }
}

function renderAgentPanel(agents) {
  const box = $("#agent-list");
  if (!box) return;
  box.innerHTML = "";
  if (!agents || !agents.length) {
    box.innerHTML = '<div style="color:var(--text-dim)">暂无运行中的 Agent</div>';
    return;
  }
  const funcs = agents.filter((a) => a.role !== "character");
  const chars = agents.filter((a) => a.role === "character");
  if (funcs.length) {
    box.appendChild(agentSectionTitle("功能 Agent"));
    funcs.forEach((a) => box.appendChild(buildAgentCard(a)));
  }
  if (chars.length) {
    box.appendChild(agentSectionTitle("角色 Agent"));
    chars.forEach((a) => box.appendChild(buildAgentCard(a)));
  }
}

function agentSectionTitle(text) {
  const el = document.createElement("div");
  el.className = "agent-section-title";
  el.textContent = text;
  return el;
}

function buildCharacterCard(a, preview) {
  const card = document.createElement("div");
  card.className = "agent-card";
  const st = a.status || "未实例化";
  card.innerHTML = `
    <div class="a-head">
      <span class="a-name">${escapeHtml(a.name)}</span>
      <span class="a-status ${escapeHtml(st)}">${escapeHtml(st)}</span>
    </div>
    <div class="a-meta">长期记忆：${a.long_memory_count || 0} 条</div>`;
  if (preview) {
    const p = document.createElement("div");
    p.className = "a-meta a-brief";
    p.textContent = preview;
    card.appendChild(p);
  }
  const ac = document.createElement("div");
  ac.className = "a-actions";
  const v = document.createElement("button");
  v.className = "btn mini";
  v.textContent = "📄 详情";
  v.addEventListener("click", (e) => { e.stopPropagation(); openCharacterDetail(a.name); });
  ac.appendChild(v);
  const m = document.createElement("button");
  m.className = "btn mini";
  m.textContent = "🧠 记忆";
  m.addEventListener("click", (e) => { e.stopPropagation(); openMemoryEditor(a.name); });
  ac.appendChild(m);
  card.appendChild(ac);
  card.addEventListener("click", () => openCharacterDetail(a.name));
  return card;
}

function buildAgentCard(a) {
  const card = document.createElement("div");
  card.className = "agent-card";
  const st = a.status || "未实例化";
  const rl = a.role === "director" ? " · 导演" : (a.role === "character" ? " · 角色" : "");
  card.innerHTML = `
    <div class="a-head">
      <span class="a-name">${escapeHtml(a.name)}${rl}</span>
      <span class="a-status ${escapeHtml(st)}">${escapeHtml(st)}</span>
    </div>
    <div class="a-meta">情感：${escapeHtml(a.emotion || "—")} · 长期记忆：${a.long_memory_count || 0} 条</div>`;
  const ac = document.createElement("div");
  ac.className = "a-actions";
  const v = document.createElement("button");
  v.className = "btn mini";
  v.textContent = "📄 详情";
  v.addEventListener("click", (e) => { e.stopPropagation(); openCharacterDetail(a.name); });
  ac.appendChild(v);
  if (st === "active") {
    const p = document.createElement("button");
    p.className = "btn mini";
    p.textContent = "⏸ 暂停";
    p.addEventListener("click", (e) => { e.stopPropagation(); agentAction(a.name, "pause"); });
    ac.appendChild(p);
  } else if (st === "paused") {
    const r = document.createElement("button");
    r.className = "btn mini";
    r.textContent = "▶ 恢复";
    r.addEventListener("click", (e) => { e.stopPropagation(); agentAction(a.name, "resume"); });
    ac.appendChild(r);
  }
  const d = document.createElement("button");
  d.className = "btn mini danger";
  d.textContent = "✕ 销毁";
  d.addEventListener("click", (e) => { e.stopPropagation(); agentAction(a.name, "destroy"); });
  ac.appendChild(d);
  const mem = document.createElement("button");
  mem.className = "btn mini";
  mem.textContent = "🧠 记忆";
  mem.addEventListener("click", (e) => { e.stopPropagation(); openMemoryEditor(a.name); });
  ac.appendChild(mem);
  card.appendChild(ac);
  return card;
}

async function agentAction(name, action) {
  try {
    if (action === "create") {
      await api(`/api/sessions/${state.activeId}/agents/create`, {
        method: "POST",
        body: JSON.stringify({ name }),
      });
    } else {
      await api(`/api/sessions/${state.activeId}/agents/${action}`, {
        method: "POST",
        body: JSON.stringify({ name }),
      });
    }
    toast(`${name} · ${actionLabels[action] || action}成功`);
    await refreshSidePanels();
  } catch (e) { toast(e.message, true); }
}

/* ================= 世界面板 ================= */
function renderWorld(w) {
  $("#w-synopsis").textContent = (w.synopsis && w.synopsis.trim()) ? w.synopsis : "（暂无梗概，聊几轮后自动生成，或点击上方「🔄 更新」）";
  $("#w-name").textContent = w.world_name || "—";
  $("#w-time").textContent = w.time || "时间未定";
  $("#w-loc").textContent = w.location || "—";
  $("#w-chars").textContent = (w.characters && w.characters.length) ? w.characters.length + " 人" : "—";
  const tl = $("#w-timeline");
  tl.innerHTML = "";
  const timeline = w.timeline || [];
  if (!timeline.length) {
    tl.innerHTML = '<div style="color:var(--text-dim);font-size:12px">暂无事件</div>';
  }
  for (const e of timeline) {
    const item = document.createElement("div");
    item.className = "tl-item";
    item.innerHTML = `<div class="tl-meta">${escapeHtml(e.time || "")} · ${escapeHtml(e.location || "")}</div>
      <div>${escapeHtml(e.event || "")}</div>`;
    tl.appendChild(item);
  }
  const rules = (w.effective_rules || w.rules || "").trim();
  state.worldRules = rules;
  state.worldRulesOverride = (w.rules_override || "").trim();
  const preview = rules.slice(0, 200) || "（该知识库未检测到世界背景资料）";
  $("#w-rules-preview").textContent = rules.length > 200 ? preview + " …（点下方按钮查看全文）" : preview;
  const stateEl = $("#w-rules-state");
  if (state.worldRulesOverride) {
    stateEl.textContent = "⚠️ 当前为手动覆盖的世界背景（点上方按钮可编辑或恢复）";
    stateEl.classList.add("warn");
  } else {
    stateEl.textContent = "来源：知识库 World/（可在弹窗中手动覆盖）";
    stateEl.classList.remove("warn");
  }
}

/* ================= 发送消息 ================= */
async function sendMessage() {
  const input = $("#msg-input");
  const text = input.value.trim();
  if (!text) return;
  if (!state.activeId) { toast("请先新建或选择一个群聊会话", true); return; }
  const mode = $("#mode-select").value;
  input.value = "";
  appendMessage({ role: "user", content: text });
  showTyping(mode === "group" ? "导演正在调度角色…" : (mode === "agent" ? "Agent 正在思考…" : ""));
  try {
    if (mode === "group") {
      const r = await api(`/api/sessions/${state.activeId}/chat`, {
        method: "POST", body: JSON.stringify({ message: text }),
      });
      hideTyping();
      if (r.narration) appendMessage({ role: "narrator", content: r.narration });
      const tags = r.memories_extracted || {};
      for (const rep of r.replies) {
        appendMessage({ role: "assistant", speaker: rep.speaker, content: rep.content }, tags[rep.speaker]);
      }
      if (r.skipped && r.skipped.length) {
        appendMessage({ role: "system", content: "以下角色本轮未参与（不存在或已暂停）：" + r.skipped.join("、") });
      }
      const sum = Object.values(tags).reduce((a, b) => a + b, 0);
      if (sum) appendMessage({ role: "system", content: `🧠 记忆管理器已保存 ${sum} 条长期记忆到对应角色记忆库。` });
    } else if (mode === "agent") {
      const agentName = $("#agent-select").value;
      if (!agentName) { toast("请先选择一个 Agent", true); hideTyping(); return; }
      const r = await api(`/api/sessions/${state.activeId}/chat/agent`, {
        method: "POST", body: JSON.stringify({ message: text, agent_name: agentName }),
      });
      hideTyping();
      if (r.error) { appendMessage({ role: "system", content: "❌ " + r.error }); }
      else { appendMessage({ role: "assistant", speaker: r.speaker, content: r.reply }); }
    }
    await refreshSidePanels();
    const info = await api(`/api/sessions/${state.activeId}/info`);
    renderChatChips(info);
    await loadSessions();
  } catch (e) {
    hideTyping();
    appendMessage({ role: "system", content: "❌ " + e.message });
    toast("发送失败", true);
  }
}

/* ================= 会话设置弹窗 ================= */
let sessModalId = null;

function openSessionSettings(sid) {
  const s = state.sessions.find((x) => x.id === sid);
  if (!s) return;
  sessModalId = sid;
  $("#sess-name").value = s.name;
  $("#sess-world").textContent = s.world_name || "—";
  $("#sess-kb").textContent = s.kb_path || "—";
  $("#sess-stats").textContent = `${s.characters} 角色 · ${s.transcript_len} 条消息`;
  $("#session-modal").classList.remove("hidden");
  setTimeout(() => $("#sess-name").focus(), 50);
}

function closeSessionSettings() {
  $("#session-modal").classList.add("hidden");
  sessModalId = null;
}

async function saveSessionSettings() {
  if (!sessModalId) return;
  const name = $("#sess-name").value.trim();
  if (!name) { toast("名称不能为空", true); return; }
  try {
    await api(`/api/sessions/${sessModalId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    toast("会话已重命名");
    closeSessionSettings();
    await loadSessions();
  } catch (e) { toast(e.message, true); }
}

async function clearSessionSettings() {
  if (!sessModalId) return;
  if (!confirm("确定清空该会话的对话记录并重置世界时间线吗？\n角色长期记忆会保留。")) return;
  try {
    await api(`/api/sessions/${sessModalId}/clear`, { method: "POST" });
    toast("对话已清空，角色记忆已保留");
    closeSessionSettings();
    await loadSessions();
  } catch (e) { toast(e.message, true); }
}

/* ================= 人物详情弹窗 ================= */
function fillList(el, items, emptyText) {
  if (items && items.length) {
    el.innerHTML = items.map((x) => `<div class="mem-item">• ${escapeHtml(String(x))}</div>`).join("");
  } else {
    el.innerHTML = `<span class="empty">${escapeHtml(emptyText)}</span>`;
  }
}

async function openCharacterDetail(name) {
  if (!state.activeId) return;
  const sid = state.activeId;
  const el = $("#char-modal");
  $("#cm-avatar").style.background = colorOf(name);
  $("#cm-avatar").textContent = (name || "?")[0];
  $("#cm-name").textContent = name;
  const st = $("#cm-status");
  st.textContent = "加载中…";
  st.className = "a-status";
  fillList($("#cm-profile"), null, ""); // 占位，下面用 textContent 填充
  $("#cm-profile").textContent = "加载中…";
  $("#cm-emotion").textContent = "";
  fillList($("#cm-relations"), null, "");
  fillList($("#cm-memories"), null, "");
  fillList($("#cm-skills"), null, "");
  state.charName = name;
  state.charPrompt = "";
  state.charPromptLocked = false;
  $("#cm-prompt-state").textContent = "";
  el.classList.remove("hidden");
  try {
    const d = await api(`/api/sessions/${sid}/character?name=${encodeURIComponent(name)}`);
    $("#cm-avatar").style.background = colorOf(d.name || name);
    $("#cm-avatar").textContent = ((d.name || name) || "?")[0];
    $("#cm-name").textContent = d.name || name;
    st.textContent = d.status;
    st.className = "a-status " + (d.status || "");
    $("#cm-profile").textContent = d.profile || "（知识库中未找到角色资料）";
    $("#cm-emotion").textContent = d.emotion_state || "—";
    const rels = d.relationships || {};
    $("#cm-relations").innerHTML = Object.keys(rels).length
      ? Object.entries(rels).map(([k, v]) => `<div class="mem-item">• ${escapeHtml(k)}：${escapeHtml(v)}</div>`).join("")
      : '<span class="empty">（暂无记录）</span>';
    fillList($("#cm-memories"), d.long_memory, "（暂无长期记忆）");
    fillList($("#cm-skills"), d.skills, "（暂无记录）");
    state.charName = d.name || name;
    state.charPrompt = d.system_prompt || "";
    state.charPromptLocked = !!d.prompt_locked;
    const ps = $("#cm-prompt-state");
    ps.textContent = state.charPromptLocked
      ? "⚠️ 已手动编辑（不再自动重建）"
      : "当前为自动生成（按角色卡与世界观拼装）";
    ps.classList.toggle("warn", state.charPromptLocked);
  } catch (e) {
    st.textContent = "加载失败";
    st.className = "a-status";
    $("#cm-profile").textContent = e.message;
  }
}

function closeCharacterDetail() {
  $("#char-modal").classList.add("hidden");
}

/* ================= 提示词查看 / 编辑（V4） ================= */
let promptCtx = null; // { kind: "agent" | "world", name }

function openPromptEditor(kind, name, text, locked) {
  promptCtx = { kind, name };
  const isWorld = kind === "world";
  $("#pm-title").textContent = isWorld ? "世界背景（注入提示词）" : `「${name}」的 System Prompt`;
  $("#pm-sub").textContent = isWorld
    ? "本内容会注入到导演与所有角色的提示词；保存后立即对未锁定的 Agent 生效。"
    : "本内容就是该 Agent 每轮发给模型的 System Prompt。保存后即锁定，不再被自动重建覆盖。";
  $("#pm-text").value = text || "";
  const st = $("#pm-state");
  st.textContent = locked
    ? "⚠️ 已手动编辑（不会再被自动重建覆盖）"
    : "当前为自动生成；保存即锁定为手动版本。";
  st.classList.toggle("warn", !!locked);
  $("#prompt-modal").classList.remove("hidden");
}

function closePromptEditor() {
  $("#prompt-modal").classList.add("hidden");
  promptCtx = null;
}

async function savePromptEditor() {
  if (!promptCtx || !state.activeId) return;
  const ctx = promptCtx;
  const btn = $("#btn-pm-save");
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    if (ctx.kind === "world") {
      await api(`/api/sessions/${state.activeId}/world/rules`, {
        method: "PUT", body: JSON.stringify({ rules: $("#pm-text").value }),
      });
      toast("世界背景已保存");
    } else {
      await api(`/api/sessions/${state.activeId}/agents/prompt`, {
        method: "PUT",
        body: JSON.stringify({ name: ctx.name, system_prompt: $("#pm-text").value, lock: true }),
      });
      toast("提示词已保存（已锁定）");
    }
    closePromptEditor();
    await refreshSidePanels();
    if (ctx.kind === "agent" && !$("#char-modal").classList.contains("hidden") && state.charName === ctx.name) {
      await openCharacterDetail(ctx.name);
    }
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

async function resetPromptEditor() {
  if (!promptCtx || !state.activeId) return;
  const ctx = promptCtx;
  const btn = $("#btn-pm-reset");
  btn.disabled = true;
  btn.textContent = "恢复中…";
  try {
    if (ctx.kind === "world") {
      await api(`/api/sessions/${state.activeId}/world/rules`, { method: "DELETE" });
      toast("已恢复为知识库世界背景");
      closePromptEditor();
    } else {
      const r = await api(`/api/sessions/${state.activeId}/agents/prompt?name=${encodeURIComponent(ctx.name)}`, { method: "DELETE" });
      $("#pm-text").value = r.system_prompt || "";
      $("#pm-state").textContent = "当前为自动生成（已解除手动覆盖）";
      $("#pm-state").classList.remove("warn");
      toast("已恢复为自动生成");
    }
    await refreshSidePanels();
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "恢复自动生成";
  }
}

/* ================= 轮次详情（V4） ================= */
function openTurnDetail(idx) {
  const turns = state.turns || [];
  const t = turns[idx];
  if (!t) return;
  $("#tm-title").textContent = `第 #${turns.length - idx} 轮详情`;
  const flags = [];
  if (!t.ok) flags.push("本轮失败");
  if (t.world_corrected) flags.push("世界已修正");
  if (t.date_reverted) flags.push("日期回退被拒");
  if ((t.world_issues || 0) > 0) flags.push(`世界违规 ${t.world_issues}`);
  const ms = t.memory_stats || {};
  const calls = t.calls || [];
  const maxMs = Math.max(1, ...calls.map((c) => c.duration_ms || 0));
  const rows = calls.map((c) => {
    const w = Math.max(4, Math.round((c.duration_ms || 0) / maxMs * 100));
    const cls = c.ok === false ? "bad" : ((c.duration_ms || 0) >= 3000 ? "warn" : "");
    return `<tr class="${cls}">`
      + `<td>${escapeHtml(c.agent)}</td><td>${escapeHtml(c.kind)}</td>`
      + `<td class="num">${fmtDur(c.duration_ms)}<span class="mini-bar"><i style="width:${w}%"></i></span></td>`
      + `<td class="num">${c.prompt_tokens ?? 0} / ${c.completion_tokens ?? 0}</td>`
      + `<td>${c.ok === false ? "❌ " + escapeHtml(c.error || "") : "✅"}</td></tr>`;
  }).join("");
  $("#tm-body").innerHTML = `
    <div class="tm-kv"><span>参与者</span><b>${escapeHtml((t.participants || []).join("、") || "—")}</b></div>
    <div class="tm-kv"><span>用户输入</span><b>${escapeHtml(t.user_input || "—")}</b></div>
    <div class="tm-kv"><span>时间</span><b>${escapeHtml(t.timestamp || "—")}</b></div>
    <div class="tm-kv"><span>总耗时 · 调用数</span><b>${fmtDur(t.latency_ms)} · ${t.llm_calls || 0} 次</b></div>
    <div class="tm-kv"><span>Token（prompt + completion）</span><b>${fmtCompact((t.prompt_tokens || 0) + (t.completion_tokens || 0))}</b></div>
    <div class="tm-kv"><span>记忆治理</span><b>新增 ${ms.added || 0} · 去重 ${ms.deduped || 0} · 冲突消解 ${ms.conflicts_resolved || 0}</b></div>
    ${flags.length ? `<div class="tm-flags">${escapeHtml(flags.join(" · "))}</div>` : ""}
    <div class="w-block-title">Agent 调用明细</div>
    <table class="tm-table">
      <thead><tr><th>Agent</th><th>类型</th><th class="num">耗时</th><th class="num">Token(p/c)</th><th>状态</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="5">无调用记录</td></tr>'}</tbody>
    </table>`;
  $("#turn-modal").classList.remove("hidden");
}

function closeTurnDetail() {
  $("#turn-modal").classList.add("hidden");
}

/* ================= 长期记忆管理弹窗 ================= */
let memModalName = null;
let memDirty = false;

function memRowEl(text) {
  const row = document.createElement("div");
  row.className = "mem-item-row";
  const ta = document.createElement("textarea");
  ta.placeholder = "输入一条长期记忆…";
  ta.value = text || "";
  ta.addEventListener("input", () => { memDirty = true; });
  const del = document.createElement("button");
  del.className = "btn mini danger";
  del.textContent = "✕";
  del.title = "删除这条记忆";
  del.addEventListener("click", () => {
    row.remove();
    memDirty = true;
    if (!$("#mem-list").children.length) renderMemRows([""]);
  });
  row.appendChild(ta);
  row.appendChild(del);
  return row;
}

function renderMemRows(memories) {
  const box = $("#mem-list");
  box.innerHTML = "";
  const list = (memories && memories.length) ? memories : [""];
  for (const m of list) box.appendChild(memRowEl(m));
}

async function openMemoryEditor(name) {
  if (!state.activeId) return;
  const sid = state.activeId;
  memModalName = name;
  memDirty = false;
  $("#mem-avatar").style.background = colorOf(name);
  $("#mem-avatar").textContent = (name || "?")[0];
  $("#mem-name").textContent = name;
  $("#mem-status").textContent = "加载中…";
  $("#mem-status").className = "a-status";
  renderMemRows([]);
  $("#mem-modal").classList.remove("hidden");
  try {
    const d = await api(`/api/sessions/${sid}/character?name=${encodeURIComponent(name)}`);
    $("#mem-name").textContent = d.name || name;
    $("#mem-avatar").style.background = colorOf(d.name || name);
    $("#mem-avatar").textContent = ((d.name || name) || "?")[0];
    $("#mem-status").textContent = d.status;
    $("#mem-status").className = "a-status " + (d.status || "");
    renderMemRows(d.long_memory || []);
  } catch (e) {
    toast(e.message, true);
  }
}

function closeMemoryEditor() {
  if (memDirty && !confirm("有未保存的记忆修改，确定放弃吗？")) return;
  $("#mem-modal").classList.add("hidden");
  memModalName = null;
  memDirty = false;
}

async function saveMemoryEditor() {
  if (!memModalName || !state.activeId) return;
  const items = [];
  $("#mem-list").querySelectorAll("textarea").forEach((ta) => {
    const v = ta.value.trim();
    if (v && !items.includes(v)) items.push(v);
  });
  const btn = $("#btn-mem-save");
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    const r = await api(`/api/sessions/${state.activeId}/character/memory?name=${encodeURIComponent(memModalName)}`, {
      method: "PUT",
      body: JSON.stringify({ long_memory: items }),
    });
    toast(`已保存 ${r.long_memory.length} 条长期记忆`);
    memDirty = false;
    $("#mem-modal").classList.add("hidden");
    const opened = memModalName;
    memModalName = null;
    await refreshSidePanels();
    if (!$("#char-modal").classList.contains("hidden")) {
      await openCharacterDetail(opened);
    }
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "保存";
  }
}

/* ================= 事件绑定 ================= */
function bindEvents() {
  $("#btn-send").addEventListener("click", sendMessage);
  $("#msg-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $("#mode-select").addEventListener("change", () => {
    const isAgent = $("#mode-select").value === "agent";
    $("#agent-select").classList.toggle("hidden", !isAgent);
    if (isAgent && state.activeId) {
      api(`/api/sessions/${state.activeId}/agents`).then(r => {
        const sel = $("#agent-select");
        const cur = sel.value;
        sel.innerHTML = '<option value="">— 选择 Agent —</option>' +
          r.agents.map(a => `<option value="${a.name}">${a.name}${a.role === "director" ? " (导演)" : ""}</option>`).join("");
        if (cur) sel.value = cur;
      }).catch(() => {});
    }
    if (state.activeId) renderCurrentChat();
  });
  $("#agent-select").addEventListener("change", () => {
    if ($("#mode-select").value === "agent" && state.activeId) renderCurrentChat();
  });
  $("#btn-save-config").addEventListener("click", async () => {
    try {
      await api("/api/config", {
        method: "POST",
        body: JSON.stringify({
          api_key: $("#cfg-key").value.trim() || null,
          base_url: $("#cfg-baseurl").value.trim(),
          model: $("#cfg-model").value.trim(),
          temperature: parseFloat($("#cfg-temp").value),
          time_format: $("#cfg-timefmt").value,
          world_check_mode: $("#cfg-worldcheck").value,
          character_temperature: parseFloat($("#cfg-char-temp").value),
          top_p: parseFloat($("#cfg-topp").value),
          frequency_penalty: parseFloat($("#cfg-freq").value),
          presence_penalty: parseFloat($("#cfg-pres").value),
          max_tokens: parseInt($("#cfg-maxtok").value, 10),
          anti_ai_flavor: $("#cfg-antiai").checked,
        }),
      });
      toast("配置已保存");
      $("#cfg-key").value = "";
      await loadConfig();
      await loadSessions();   // 切换时间格式后立即按新格式刷新界面
    } catch (e) { toast(e.message, true); }
  });
  $("#btn-test-config").addEventListener("click", async () => {
    const btn = $("#btn-test-config");
    btn.disabled = true;
    btn.textContent = "测试中…";
    try {
      const r = await api("/api/config/test", { method: "POST" });
      toast("连接成功：" + (r.reply || ""));
    } catch (e) {
      toast("连接失败：" + e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "测试连接";
    }
  });
  $("#btn-key-toggle").addEventListener("click", () => {
    const input = $("#cfg-key");
    input.type = input.type === "password" ? "text" : "password";
  });
  $("#btn-new-session").addEventListener("click", () => {
    $("#new-kbpath").value = "";
    $("#modal").classList.remove("hidden");
    setTimeout(() => $("#new-name").focus(), 50);
  });
  $("#btn-modal-cancel").addEventListener("click", () => $("#modal").classList.add("hidden"));
  $("#btn-modal-ok").addEventListener("click", createSession);
  $("#modal").addEventListener("click", (e) => {
    if (e.target === $("#modal")) $("#modal").classList.add("hidden");
  });
  $("#new-kbpath").addEventListener("keydown", (e) => { if (e.key === "Enter") createSession(); });
  $("#new-name").addEventListener("keydown", (e) => { if (e.key === "Enter") createSession(); });

  // 📂 浏览：弹 Windows 系统原生「选择文件夹」对话框（由同机后端弹出），失败则 tips 报错
  $("#btn-browse-kb").addEventListener("click", async () => {
    try {
      const r = await api("/api/kb/native-pick", { method: "POST" });
      if (r && r.path) {
        $("#new-kbpath").value = r.path;
        validateKbPath(r.path);
      } else {
        toast("未选择文件夹", true);
      }
    } catch (e) {
      toast(e.message, true);
    }
  });

  async function validateKbPath(path) {
    if (!path) return;
    try {
      const r = await api("/api/kb/validate?path=" + encodeURIComponent(path));
      const err = [];
      if (!r.exists) err.push("路径不存在");
      if (r.exists && !r.is_dir) err.push("不是文件夹");
      (r.missing_dirs || []).forEach((d) => err.push("缺少 " + d));
      if (err.length) toast("知识库提示：" + err.join("、") + "（缺失会自动新建）");
      else toast("知识库校验通过 ✓");
    } catch (e) {
      toast("校验失败：" + e.message, true);
    }
  }

  // 会话设置弹窗
  $("#btn-sess-save").addEventListener("click", saveSessionSettings);
  $("#btn-sess-clear").addEventListener("click", clearSessionSettings);
  $("#btn-sess-delete").addEventListener("click", () => {
    if (!sessModalId) return;
    const sid = sessModalId;
    closeSessionSettings();
    deleteSession(sid);
  });
  $("#btn-sess-cancel").addEventListener("click", closeSessionSettings);
  $("#session-modal").addEventListener("click", (e) => {
    if (e.target === $("#session-modal")) closeSessionSettings();
  });
  $("#sess-name").addEventListener("keydown", (e) => { if (e.key === "Enter") saveSessionSettings(); });

  // 人物详情弹窗
  $("#btn-char-close").addEventListener("click", closeCharacterDetail);
  $("#btn-prompt-edit").addEventListener("click", () => {
    if (!state.charName) return;
    openPromptEditor("agent", state.charName, state.charPrompt, state.charPromptLocked);
  });
  $("#char-modal").addEventListener("click", (e) => {
    if (e.target === $("#char-modal")) closeCharacterDetail();
  });

  // 世界背景 / 提示词查看编辑弹窗
  $("#btn-world-rules").addEventListener("click", () => {
    openPromptEditor("world", null, state.worldRulesOverride || state.worldRules, !!state.worldRulesOverride);
  });
  $("#btn-pm-save").addEventListener("click", savePromptEditor);
  $("#btn-pm-cancel").addEventListener("click", closePromptEditor);
  $("#btn-pm-reset").addEventListener("click", resetPromptEditor);
  $("#prompt-modal").addEventListener("click", (e) => {
    if (e.target === $("#prompt-modal")) closePromptEditor();
  });

  // 轮次详情弹窗
  $("#btn-tm-close").addEventListener("click", closeTurnDetail);
  $("#turn-modal").addEventListener("click", (e) => {
    if (e.target === $("#turn-modal")) closeTurnDetail();
  });

  // 长期记忆管理弹窗
  $("#btn-mem-edit").addEventListener("click", () => {
    const name = $("#cm-name").textContent.trim();
    if (name && name !== "加载中…") openMemoryEditor(name);
  });
  $("#btn-mem-add").addEventListener("click", () => {
    $("#mem-list").appendChild(memRowEl(""));
    memDirty = true;
  });
  $("#btn-mem-cancel").addEventListener("click", closeMemoryEditor);
  $("#btn-mem-save").addEventListener("click", saveMemoryEditor);
  $("#mem-modal").addEventListener("click", (e) => {
    if (e.target === $("#mem-modal")) closeMemoryEditor();
  });

  // 剧情梗概手动刷新
  $("#btn-synopsis-refresh").addEventListener("click", async () => {
    if (!state.activeId) { toast("请先选择一个群聊会话", true); return; }
    const btn = $("#btn-synopsis-refresh");
    btn.disabled = true;
    btn.textContent = "生成中…";
    try {
      const r = await api(`/api/sessions/${state.activeId}/synopsis`, { method: "POST" });
      $("#w-synopsis").textContent = r.synopsis || "（暂无梗概）";
      toast("剧情梗概已更新");
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "🔄 更新";
    }
  });

  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.tab;
      $("#tab-characters").classList.toggle("hidden", target !== "characters");
      $("#tab-agents").classList.toggle("hidden", target !== "agents");
      $("#tab-world").classList.toggle("hidden", target !== "world");
      $("#tab-observe").classList.toggle("hidden", target !== "observe");
      if (target === "observe") loadObservability();
    });
  });

  $("#btn-obs-refresh")?.addEventListener("click", loadObservability);
  $("#btn-obs-export-md")?.addEventListener("click", () => {
    if (state.activeId) window.open(`/api/sessions/${state.activeId}/export?format=md`, "_blank");
  });
  $("#btn-obs-export-json")?.addEventListener("click", () => {
    if (state.activeId) window.open(`/api/sessions/${state.activeId}/export?format=json`, "_blank");
  });
  $("#btn-obs-judge")?.addEventListener("click", runJudge);
}

/* ================= 观测面板（V4：分组指标 + 调用步骤条） ================= */
function gateClass(s) { return s === "PASS" ? "pass" : (s === "FAIL" ? "fail" : "base"); }

// badge 与 label 分离渲染：label 文本转义、badge 作为独立元素（修复把 HTML 当文本的乱码）
function obsCard(label, value, gate) {
  const badge = gate ? `<span class="obs-badge ${gateClass(gate)}">${escapeHtml(gate)}</span>` : "";
  return `<div class="obs-card"><div class="k">${escapeHtml(label)}${badge}</div>`
    + `<div class="v">${escapeHtml(String(value))}</div></div>`;
}
function obsGroup(title, cardsHtml) {
  return `<div class="obs-group-title">${escapeHtml(title)}</div><div class="obs-grid">${cardsHtml}</div>`;
}
function fmtPct(v) { return (v === null || v === undefined) ? "—" : (Number(v) * 100).toFixed(1) + "%"; }
function fmtNum(v, d = 2) { return (v === null || v === undefined) ? "—" : Number(v).toFixed(d); }
function fmtCompact(v) {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(Math.round(n));
}
function fmtDur(ms) {
  if (ms === null || ms === undefined) return "—";
  const n = Number(ms);
  return n >= 1000 ? (n / 1000).toFixed(1) + "s" : Math.round(n) + "ms";
}

async function loadObservability() {
  const sid = state.activeId;
  if (!sid) {
    $("#obs-metrics").innerHTML = obsGroup("提示", obsCard("请先选择会话", "—"));
    $("#obs-turns").innerHTML = "";
    return;
  }
  try {
    const [m, t] = await Promise.all([
      api(`/api/sessions/${sid}/metrics`),
      api(`/api/sessions/${sid}/turns?limit=30`),
    ]);
    renderObservability(m, t.turns || []);
  } catch (e) {
    toast("加载观测数据失败：" + e.message, true);
  }
}

function renderObservability(m, turns) {
  const gates = m.gates || {};
  const g = (k) => gates[k] || "";
  const gateCards = [
    obsCard("编排成功率", fmtPct(m.agent_orchestration_success_rate), g("agent_orchestration_success_rate")),
    obsCard("场外泄漏", m.offscreen_leak_count ?? 0, g("offscreen_leak_count")),
    obsCard("世界违规率", fmtPct(m.world_violation_rate), g("world_violation_rate")),
    obsCard("时间线问题", m.timeline_issues ?? 0, g("timeline_issues")),
    obsCard("排除目录泄漏", m.world_leak_from_excluded ?? 0, g("world_leak_from_excluded")),
  ].join("");
  const scaleCards = [
    obsCard("完成轮次", `${m.turns_completed ?? 0}/${m.turns_total ?? 0}`),
    obsCard("自动修正率", fmtPct(m.world_correction_rate)),
    obsCard("长期记忆", m.memories_total ?? 0),
    obsCard("有效角色", m.characters_active ?? 0),
  ].join("");
  const perfCards = [
    obsCard("单轮平均 Token", fmtCompact(m.avg_tokens_per_turn)),
    obsCard("P50 延迟", fmtDur(m.p50_turn_latency_ms)),
    obsCard("P95 延迟", fmtDur(m.p95_turn_latency_ms)),
    obsCard("梗概覆盖", fmtPct(m.synopsis_coverage)),
    obsCard("AI 腔命中率", fmtNum(m.ai_flavor_rate, 2) + " /千字"),
    obsCard("示例注入率", fmtPct(m.example_injected_ratio)),
  ].join("");
  $("#obs-metrics").innerHTML =
    obsGroup("门禁", gateCards) + obsGroup("规模", scaleCards) + obsGroup("延迟与用量", perfCards);

  const box = $("#obs-turns");
  state.turns = turns;
  if (!turns.length) { box.innerHTML = '<div class="obs-empty">暂无轮次记录</div>'; return; }
  const total = turns.length;
  box.innerHTML = turns.map((t, i) => {
    const flags = [];
    if (!t.ok) flags.push("失败");
    if (t.world_corrected) flags.push("世界已修正");
    if (t.date_reverted) flags.push("日期回退");
    if ((t.world_issues || 0) > 0) flags.push(`违规 ${t.world_issues}`);
    return `<button class="obs-turn-btn" type="button" data-turn="${i}">`
      + `<span class="t-main">`
      + `<span class="t-title">#${total - i} ${escapeHtml((t.participants || []).join("、") || t.user_input || "")}</span>`
      + `<span class="t-meta">${fmtDur(t.latency_ms)} · ${t.llm_calls || 0} 次调用</span>`
      + `</span>`
      + (flags.length ? `<span class="t-flags">${escapeHtml(flags.join(" · "))}</span>` : "")
      + `<span class="t-arrow">查看详情 ›</span></button>`;
  }).join("");
  box.querySelectorAll(".obs-turn-btn").forEach((b) => {
    b.addEventListener("click", () => openTurnDetail(parseInt(b.dataset.turn, 10)));
  });
}

async function runJudge() {
  const sid = state.activeId;
  if (!sid) { toast("请先选择会话", true); return; }
  const box = $("#obs-judge");
  box.classList.remove("hidden");
  box.innerHTML = "裁判采样中…";
  try {
    const r = await api(`/api/sessions/${sid}/judge`, { method: "POST" });
    const val = (r.value === null || r.value === undefined) ? "—" : (r.value * 100).toFixed(1) + "%";
    const fl = r.ai_flavor;
    const flVal = (v) => (v === null || v === undefined) ? "—" : (v * 100).toFixed(1) + "%";
    const flLine = fl
      ? `<div class="dim">文风裁判（AI 腔，1=自然）：${flVal(fl.value)} · stdev ${fl.stdev ?? "—"}</div>`
      : "";
    box.innerHTML = `<b>人设一致率（观察项，不参与门禁）</b>：${val}`
      + `<div class="dim">样本数 ${(r.samples || []).length} · stdev ${r.stdev ?? "—"} · ${escapeHtml(r.model || "")}</div>`
      + (r.characters || []).map((c) =>
        `<div>${escapeHtml(c.name)}：${c.value === null || c.value === undefined ? "—" : (c.value * 100).toFixed(0) + "%"}</div>`).join("")
      + flLine
      + `<div class="dim">${escapeHtml(r.note || "")}</div>`;
  } catch (e) {
    box.innerHTML = "裁判失败：" + escapeHtml(e.message);
  }
}

async function createSession() {
  const name = $("#new-name").value.trim();
  const kbPath = $("#new-kbpath").value.trim();
  if (!name || !kbPath) { toast("请填写会话名称与知识库路径", true); return; }
  try {
    const ws = await api("/api/sessions", { method: "POST", body: JSON.stringify({ name, kb_path: kbPath }) });
    toast(`会话「${ws.name}」创建成功，世界：${ws.world_name}`);
    $("#modal").classList.add("hidden");
    await loadSessions();
  } catch (e) {
    toast("创建失败：" + e.message, true);
  }
}

init().catch((e) => {
  document.body.innerHTML = `<div style="padding:40px;color:#e05d5d">前端初始化失败：${escapeHtml(e.message)}</div>`;
});




