/* PhantomCustom frontend */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
let TOKEN = localStorage.getItem("pc_token") || "";
let ME = null;
let TOOLS = {};
let TASKS = [];
let ws = null;
let currentTool = null;
let editingTask = null;

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (TOKEN) headers.Authorization = "Bearer " + TOKEN;
  let res;
  try {
    res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  } catch (e) {
    const err = new Error("Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.");
    err.network = true;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json().catch(() => ({})) : {};
  if (res.status === 401) { logoutLocal(); const e = new Error("Phiên hết hạn, đăng nhập lại"); e.status = 401; throw e; }
  if (!res.ok) {
    const e = new Error(data.detail || `Lỗi máy chủ (${res.status})`);
    e.status = res.status;
    throw e;
  }
  return data;
}

/* ---------------- toast ---------------- */
function toast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateX(30px)"; setTimeout(() => el.remove(), 300); }, 4200);
}

/* ---------------- view switching ---------------- */
function show(view) {
  ["viewLanding", "viewAuth", "viewDash", "viewAdmin"].forEach((v) => $("#" + v).classList.add("hidden"));
  $("#" + view).classList.remove("hidden");
  $("#navDash").classList.toggle("hidden", !ME);
  $("#navAdmin").classList.toggle("hidden", !(ME && ME.is_admin));
  $("#navAuth").classList.toggle("hidden", !!ME);
  $("#navLogout").classList.toggle("hidden", !ME);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------------- auth ---------------- */
let authMode = "login";
function setAuthMode(m) {
  authMode = m;
  $("#tabLogin").classList.toggle("active", m === "login");
  $("#tabRegister").classList.toggle("active", m === "register");
  $("#authSubmit").textContent = m === "login" ? "Đăng nhập" : "Đăng ký";
}
$("#tabLogin").onclick = () => setAuthMode("login");
$("#tabRegister").onclick = () => setAuthMode("register");

$("#authSubmit").onclick = async () => {
  const username = $("#authUser").value.trim();
  const password = $("#authPass").value;
  if (!username || !password) return toast("Nhập đủ tên và mật khẩu", "warn");
  try {
    const data = await api("/api/" + authMode, { method: "POST", body: JSON.stringify({ username, password }) });
    TOKEN = data.token; localStorage.setItem("pc_token", TOKEN);
    ME = data.user;
    toast("Chào mừng " + ME.username, "success");
    await bootUser();
  } catch (e) { toast(e.message, "error"); }
};

function logoutLocal() {
  TOKEN = ""; ME = null; localStorage.removeItem("pc_token");
  if (ws) { ws.close(); ws = null; }
  show("viewLanding");
}
$("#navLogout").onclick = async () => { try { await api("/api/logout", { method: "POST" }); } catch (e) {} logoutLocal(); toast("Đã đăng xuất"); };
$("#navAuth").onclick = () => show("viewAuth");
$("#navHome").onclick = () => show("viewLanding");
$("#navDash").onclick = () => show("viewDash");
$("#navAdmin").onclick = () => { show("viewAdmin"); loadAdmin(); };
$("#heroStart").onclick = () => { ME ? show("viewDash") : show("viewAuth"); };
$("#heroRent").onclick = openRent;

/* ---------------- tools rendering ---------------- */
const ICONS = {
  discord: `<svg viewBox="0 0 24 24" fill="#fff"><path d="M20.3 4.4A19.8 19.8 0 0 0 15.4 3l-.2.5c1.7.4 2.5 1 2.5 1a13.5 13.5 0 0 0-11.4 0s.8-.6 2.5-1L8.6 3a19.8 19.8 0 0 0-4.9 1.4C.7 9.1-.1 13.7.3 18.2A19.9 19.9 0 0 0 6.3 21l.4-1.6c-.9-.3-1.7-.8-2.4-1.4l.6.3a14.2 14.2 0 0 0 12.2 0l.6-.3c-.7.6-1.5 1.1-2.4 1.4L15.7 21a19.9 19.9 0 0 0 6-2.8c.5-5.2-.7-9.7-1.4-13.8ZM8.3 15.4c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm7.4 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>`,
  zalo: `<svg viewBox="0 0 24 24" fill="none"><rect x="2" y="3" width="20" height="18" rx="5" fill="#fff"/><path d="M7 8.5v7M7 8.5l4 7v-7M14 15.5v-4a1.5 1.5 0 0 1 3 0v4" stroke="#050506" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  messenger: `<svg viewBox="0 0 24 24" fill="none"><path d="M12 2C6.5 2 2 6.1 2 11.2c0 2.9 1.4 5.5 3.7 7.2V22l3.3-1.8c.9.3 1.9.4 3 .4 5.5 0 10-4.1 10-9.4S17.5 2 12 2Z" fill="#fff"/><path d="m6.5 13.5 4-4.2 2.4 2.4 4.6-2.5-4 4.2-2.4-2.4-4.6 2.5Z" fill="#050506"/></svg>`,
};
const ICON_KEY = { treodis: "discord", nhaydiscord: "discord", treozalo: "zalo", treomess: "messenger", nhaymess: "messenger", zalomulti: "zalo" };

function toolCard(key) {
  const t = TOOLS[key];
  return `<div class="card">
    <div class="tool-icon">${ICONS[ICON_KEY[key]] || ICONS.zalo}</div>
    <h3>${t.name}</h3>
    <p>${t.desc}</p>
    <div class="foot"><span class="pill">${key}</span><button class="btn sm primary" data-tool="${key}">Tạo task</button></div>
  </div>`;
}

function renderTools() {
  const keys = Object.keys(TOOLS);
  $("#landingTools").innerHTML = keys.map(toolCard).join("");
  $("#dashTools").innerHTML = keys.map(toolCard).join("");
  $$("[data-tool]").forEach((b) => b.onclick = () => openTaskModal(b.dataset.tool));
}

/* ---------------- field specs ---------------- */
const F = {
  tokens: { label: "Danh sách token Discord (mỗi dòng 1 token)", type: "textarea", ph: "MTAxxxxx...\nMTBxxxxx..." },
  token: { label: "Token Discord", type: "text", ph: "MTAxxxxx..." },
  channels: { label: "Danh sách channel ID (mỗi dòng 1 ID)", type: "textarea", ph: "1234567890\n9876543210" },
  channel: { label: "UID channel Discord", type: "text", ph: "1234567890" },
  message: { label: "Nội dung tin nhắn", type: "textarea", ph: "Nội dung spam..." },
  messages: { label: "Nhiều nội dung (mỗi dòng 1 câu)", type: "textarea", ph: "Câu 1\nCâu 2" },
  delay: { label: "Delay (giây)", type: "number", ph: "3", def: 3 },
  api_key: { label: "API Key Zalo", type: "text", ph: "api_key" },
  secret_key: { label: "Secret Key Zalo", type: "text", ph: "secret_key" },
  imei: { label: "IMEI (bắt buộc)", type: "text", ph: "b84aaf8f3e411c94" },
  cookies: { label: "Cookie / Session (bắt buộc · JSON hoặc chuỗi)", type: "textarea", ph: "{\"zpsid\":\"...\",\"zpw_sek\":\"...\"}\nhoặc c_user=...; xs=..." },
  cookie: { label: "Cookie Facebook", type: "textarea", ph: "c_user=...; xs=..." },
  groups: { label: "Group ID / link Zalo (để trống = tự đọc toàn bộ nhóm đang tham gia)", type: "textarea", ph: "Để trống → web tự lấy hết nhóm trong acc\nHoặc: 123456789 | https://zalo.me/g/xxx" },
  threads: { label: "Box / thread ID Messenger (mỗi dòng 1)", type: "textarea", ph: "1000123456789" },
  thread: { label: "Box / thread ID", type: "text", ph: "1000123456789" },
  members: { label: "Member UID để tag (mỗi dòng 1, có thể uid:tên)", type: "textarea", ph: "10001:Nguyễn A\n10002:Trần B" },
  ttl: { label: "TTL (ms, để trống = không)", type: "number", ph: "0" },
  colors: { label: "Màu tin nhắn (1-4, vd: 1,2,3,4)", type: "text", ph: "1,2,3,4", def: "1,2,3,4" },
  media_type: { label: "Loại media", type: "select", options: [["none", "Không media"], ["image", "Ảnh"], ["video", "Video"]] },
  media_source: { label: "Nguồn media (thư mục ảnh hoặc URL video mỗi dòng)", type: "textarea", ph: "/path/images\nhttps://...mp4" },
  typing: { label: "Fake typing MQTT", type: "select", options: [["true", "Bật"], ["false", "Tắt"]] },
  mode: { label: "Chế độ Zalo đa năng", type: "select", options: [
    ["nhaytag", "Nhây Tag"], ["treongon", "Treo Ngôn"], ["spamcall", "Spam Call"],
    ["treoanh", "Treo Ảnh"], ["doitennhom", "Đổi Tên Nhóm"], ["doianhnhom", "Đổi Avatar Nhóm"],
    ["spamsticker", "Spam Sticker"], ["spamvoice", "Spam Voice"], ["spamcard", "Spam Danh Thiếp"], ["join", "Join Nhóm"]] },
  delay_min: { label: "Delay min (giây)", type: "number", ph: "2", def: 2 },
  delay_max: { label: "Delay max (giây)", type: "number", ph: "5", def: 5 },
  tag_multiple: { label: "Tag nhiều người", type: "select", options: [["false", "Không"], ["true", "Có"]] },
  tag_random: { label: "Tag ngẫu nhiên", type: "select", options: [["false", "Không"], ["true", "Có"]] },
  repeat_count: { label: "Số lần lặp", type: "number", ph: "10", def: 10 },
  image_folder: { label: "Thư mục ảnh trên server", type: "text", ph: "/path/to/images" },
  sticker_count: { label: "Số sticker", type: "number", ph: "10", def: 10 },
  join_link: { label: "Link nhóm cần join (mỗi dòng 1)", type: "textarea", ph: "https://zalo.me/g/xxx" },
};

function fieldHTML(key, val) {
  const f = F[key] || { label: key, type: "text" };
  const v = val !== undefined && val !== null ? val : (f.def !== undefined ? f.def : "");
  let input;
  if (f.type === "textarea") input = `<div class="ta-wrap"><textarea data-f="${key}" placeholder="${f.ph || ""}">${v}</textarea><label class="ta-import" title="Nhập danh sách từ file .txt">📁 .txt<input type="file" data-import="${key}" accept=".txt,text/plain,.csv" hidden/></label></div>`;
  else if (f.type === "select") input = `<select data-f="${key}">${f.options.map(([o, l]) => `<option value="${o}" ${String(v) === o ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  else input = `<input data-f="${key}" type="${f.type}" value="${v}" placeholder="${f.ph || ""}"/>`;
  return `<div class="field"><label>${f.label}</label>${input}</div>`;
}

/* ---------------- create task ---------------- */
function openTaskModal(toolKey) {
  if (!ME) return show("viewAuth");
  if (!ME.access && !ME.is_admin) { openRent(); return; }
  currentTool = toolKey;
  const t = TOOLS[toolKey];
  $("#taskModalTitle").textContent = "Tạo task · " + t.name;
  $("#taskModalDesc").textContent = t.desc;
  $("#taskFields").innerHTML =
    `<div class="field"><label>Tên task</label><input data-f="__name" value="${t.name}" placeholder="Tên gợi nhớ"/></div>` +
    t.fields.map((f) => fieldHTML(f)).join("");
  bindImporters("#taskFields");
  openModal("overlayTask");
}

$("#btnCreateTask").onclick = async () => {
  const cfg = {};
  $$("#taskFields [data-f]").forEach((el) => {
    let v = el.value;
    if (el.type === "number") v = v === "" ? "" : Number(v);
    if (v === "true") v = true; else if (v === "false") v = false;
    cfg[el.dataset.f] = v;
  });
  const name = cfg.__name || TOOLS[currentTool].name;
  delete cfg.__name;
  try {
    await api("/api/tasks", { method: "POST", body: JSON.stringify({ tool: currentTool, name, config: cfg }) });
    toast("Đã tạo task và bắt đầu treo", "success");
    closeModal("overlayTask");
    refreshTasks();
  } catch (e) { toast(e.message, "error"); }
};


/* ---------------- nhập danh sách từ file .txt ---------------- */
function bindImporters(scope) {
  $$(scope + " [data-import]").forEach((inp) => {
    inp.onchange = () => {
      const file = inp.files && inp.files[0];
      if (!file) return;
      const key = inp.dataset.import;
      const reader = new FileReader();
      reader.onload = () => {
        const text = String(reader.result || "").replace(/\r/g, "");
        const ta = document.querySelector(`${scope} [data-f="${key}"]`);
        if (!ta) return;
        const cur = ta.value.trim();
        ta.value = cur ? cur + "\n" + text.trim() : text.trim();
        const n = text.split("\n").filter((x) => x.trim()).length;
        toast(`Đã nhập ${n} dòng từ ${file.name} vào "${key}"`, "success");
      };
      reader.onerror = () => toast("Không đọc được file", "error");
      reader.readAsText(file, "utf-8");
      inp.value = "";
    };
  });
}

/* ---------------- check live/die ---------------- */
let CHECK_ROWS = [];
let CHECK_LAST = null;
const CHECK_KIND_LABEL = { discord: "Discord token", fb_cookie: "Facebook cookie", fb_link: "Link Facebook", zalo: "Zalo" };
const CHECK_HINT = {
  discord: "Discord: mỗi dòng 1 token (dạng MTIz....GGGG.xxxx). Có thể tải file .txt chứa nhiều token.",
  fb_cookie: "Facebook cookie: mỗi dòng 1 cookie, phải có c_user=... và xs=...",
  fb_link: "Link Facebook: mỗi dòng 1 link hoặc username hoặc UID. Dán cookie ở ô dưới để check chính xác 100%.",
  zalo: "Zalo: mỗi dòng imei|cookie_json — hoặc tải nguyên file export (có dòng “IMEI:”).",
};

$("#btnCheck").onclick = () => {
  if (!ME) return show("viewAuth");
  openModal("overlayCheck");
};
$("#checkKind").onchange = () => {
  $("#checkHint").textContent = CHECK_HINT[$("#checkKind").value] || "";
  $("#checkCookie").parentElement.style.display = $("#checkKind").value === "fb_link" ? "" : "none";
};
$("#checkCookie").parentElement.style.display = "none";

$("#checkFile").onchange = () => {
  const f = $("#checkFile").files && $("#checkFile").files[0];
  if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    const text = String(r.result || "").replace(/\r/g, "").trim();
    const ta = $("#checkData");
    ta.value = ta.value.trim() ? ta.value.trim() + "\n" + text : text;
    toast(`Đã tải ${f.name} (${text.split("\n").filter((x) => x.trim()).length} dòng)`, "success");
  };
  r.readAsText(f, "utf-8");
  $("#checkFile").value = "";
};

$("#btnClearCheck").onclick = () => {
  $("#checkData").value = "";
  $("#checkResult").innerHTML = "";
  $("#checkSummary").classList.add("hidden");
  $("#btnCopyLive").disabled = true;
  CHECK_ROWS = [];
};

$("#btnRunCheck").onclick = async () => {
  const kind = $("#checkKind").value;
  const data = $("#checkData").value.trim();
  if (!data) return toast("Dán danh sách hoặc tải file .txt trước đã", "warn");
  const btn = $("#btnRunCheck");
  btn.disabled = true;
  btn.textContent = "⏳ Đang check...";
  $("#checkResult").innerHTML = `<div class="check-loading">Đang kiểm tra ${data.split("\n").filter((x) => x.trim()).length} acc… (Zalo mỗi acc ~5–20s)</div>`;
  try {
    const res = await api("/api/check", {
      method: "POST",
      body: JSON.stringify({ kind, data, cookie: $("#checkCookie").value.trim() }),
    });
    CHECK_ROWS = res.results || [];
    CHECK_LAST = res;
    renderCheck(res);
    toast(`Xong: ${res.live} live · ${res.die} die · ${res.unknown} chưa rõ`, res.live ? "success" : "warn");
  } catch (e) {
    $("#checkResult").innerHTML = `<div class="check-loading" style="color:#ff8fa3">${esc(e.message)}</div>`;
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Bắt đầu check";
  }
};

function renderCheck(res) {
  const sum = $("#checkSummary");
  sum.classList.remove("hidden");
  sum.innerHTML = `<b>${res.total}</b> acc ·
    <span class="live">${res.live} LIVE</span> ·
    <span class="die">${res.die} DIE</span> ·
    <span class="unk">${res.unknown} chưa xác định</span>`;
  $("#btnCopyLive").disabled = !res.live;
  CHECK_SHOWN = 300;
  paintCheckRows();
}

let CHECK_SHOWN = 300;
function paintCheckRows() {
  const res = CHECK_LAST;
  if (!res) return;
  const all = res.results || [];
  const rows = all.slice(0, CHECK_SHOWN);
  $("#checkResult").innerHTML = rows.map((r, i) => {
    const short = r.type === "zalo" ? r.input : (r.input.length > 46 ? r.input.slice(0, 46) + "…" : r.input);
    return `<div class="check-row ${r.status}">
      <span class="ck-badge ${r.status}">${r.status === "live" ? "LIVE" : r.status === "die" ? "DIE" : "?"}</span>
      <div class="ck-main">
        <div class="ck-name">${esc(r.name || "—")} ${r.id ? `<span class="ck-id">${esc(r.id)}</span>` : ""}</div>
        <div class="ck-sub mono">${esc(short)}</div>
        <div class="ck-note">${esc(r.note || "")}</div>
      </div>
      <button class="btn sm ghost" onclick="copyText(${i})">Copy</button>
    </div>`;
  }).join("") || `<div class="check-loading">Không có dòng nào hợp lệ.</div>`;
  if (all.length > CHECK_SHOWN) {
    $("#checkResult").innerHTML +=
      `<button class="btn" id="btnMoreCheck" style="margin-top:6px">Xem thêm ${Math.min(300, all.length - CHECK_SHOWN)} / còn ${all.length - CHECK_SHOWN} acc</button>`;
    $("#btnMoreCheck").onclick = () => { CHECK_SHOWN += 300; paintCheckRows(); };
  }
}

function copyText(i) {
  const r = CHECK_ROWS[i];
  if (!r) return;
  navigator.clipboard.writeText(r.input).then(() => toast("Đã copy", "success")).catch(() => toast("Không copy được", "error"));
}

$("#btnCopyLive").onclick = () => {
  const live = CHECK_ROWS.filter((r) => r.status === "live").map((r) => r.input).join("\n");
  if (!live) return;
  navigator.clipboard.writeText(live).then(() => toast(`Đã copy ${CHECK_ROWS.filter((r) => r.status === "live").length} acc LIVE`, "success")).catch(() => toast("Không copy được", "error"));
};

/* ---------------- task list ---------------- */
function fmtUptime(s) {
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (d) return `${d}d ${h}h ${m}m`;
  if (h) return `${h}h ${m}m ${sec}s`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}
const STATUS_LABEL = { running: "Đang chạy", paused: "Tạm dừng", stopped: "Đã dừng", finished: "Hoàn tất", error: "Lỗi" };

function renderTasks() {
  const list = $("#taskList");
  if (!TASKS.length) {
    list.innerHTML = `<div class="card" style="text-align:center;color:var(--muted)">Chưa có task nào. Bấm “+ Tạo task” để bắt đầu treo.</div>`;
    $("#taskCount").textContent = "";
    return;
  }
  $("#taskCount").textContent = `${TASKS.length} task`;
  list.innerHTML = TASKS.map((t) => {
    const st = t.status || "running";
    return `<div class="task">
      <div class="dot ${st}"></div>
      <div class="meta">
        <h4>${t.name} <span class="pill">${(TOOLS[t.tool] && TOOLS[t.tool].name) || t.tool}</span></h4>
        <div class="sub">
          <span>${STATUS_LABEL[st] || st}</span>
          <span>⏱ <b class="mono" data-up="${t.id}">${fmtUptime(t.uptime || 0)}</b></span>
          <span>📤 <b class="mono">${t.sent_count || 0}</b></span>
          ${t.last_error ? `<span style="color:#ff8fa3">${t.last_error.slice(0, 40)}</span>` : ""}
        </div>
      </div>
      <div class="actions">
        ${st === "running" ? `<button class="btn sm" onclick="pauseTask('${t.id}')">⏸ Dừng tạm</button>` : ""}
        ${st === "paused" ? `<button class="btn sm" onclick="resumeTask('${t.id}')">▶ Tiếp tục</button>` : ""}
        ${(st === "stopped" || st === "error" || st === "finished") ? `<button class="btn sm" onclick="resumeTask('${t.id}')">↻ Chạy lại</button>` : ""}
        ${st !== "stopped" ? `<button class="btn sm danger" onclick="stopTask('${t.id}')">⏹ Dừng</button>` : ""}
        <button class="btn sm" onclick="editTask('${t.id}')">⚙ Sửa</button>
        <button class="btn sm" onclick="viewLogs('${t.id}')">📜 Log</button>
        <button class="btn sm danger" onclick="deleteTask('${t.id}')">🗑</button>
      </div>
    </div>`;
  }).join("");
}

async function refreshTasks() {
  try { TASKS = await api("/api/tasks"); renderTasks(); } catch (e) {}
}
async function pauseTask(id) { try { await api(`/api/tasks/${id}/pause`, { method: "POST" }); toast("Đã tạm dừng", "warn"); refreshTasks(); } catch (e) { toast(e.message, "error"); } }
async function resumeTask(id) { try { await api(`/api/tasks/${id}/resume`, { method: "POST" }); toast("Đã tiếp tục", "success"); refreshTasks(); } catch (e) { toast(e.message, "error"); } }
async function stopTask(id) { try { await api(`/api/tasks/${id}/stop`, { method: "POST" }); toast("Đã dừng task", "warn"); refreshTasks(); } catch (e) { toast(e.message, "error"); } }
async function deleteTask(id) {
  if (!confirm("Xoá task này?")) return;
  try { await api(`/api/tasks/${id}`, { method: "DELETE" }); toast("Đã xoá", "success"); refreshTasks(); } catch (e) { toast(e.message, "error"); }
}
function editTask(id) {
  const t = TASKS.find((x) => x.id === id);
  if (!t) return;
  editingTask = id;
  const fields = TOOLS[t.tool].fields;
  $("#editFields").innerHTML = fields.map((f) => fieldHTML(f, t.config[f])).join("");
  openModal("overlayEdit");
}
$("#btnSaveConfig").onclick = async () => {
  const cfg = {};
  $$("#editFields [data-f]").forEach((el) => {
    let v = el.value;
    if (el.type === "number") v = v === "" ? "" : Number(v);
    if (v === "true") v = true; else if (v === "false") v = false;
    cfg[el.dataset.f] = v;
  });
  try {
    await api(`/api/tasks/${editingTask}/config`, { method: "PUT", body: JSON.stringify(cfg) });
    toast("Đã cập nhật cấu hình", "success");
    closeModal("overlayEdit");
    refreshTasks();
  } catch (e) { toast(e.message, "error"); }
};
async function viewLogs(id) {
  try {
    const d = await api(`/api/tasks/${id}/logs`);
    $("#logsMeta").textContent = `Trạng thái: ${STATUS_LABEL[d.status] || d.status} · Uptime: ${fmtUptime(d.uptime)}`;
    $("#logsBox").textContent = (d.logs || []).join("\n") || "Chưa có log.";
    openModal("overlayLogs");
  } catch (e) { toast(e.message, "error"); }
}

/* ---------------- admin ---------------- */
async function loadAdmin() {
  if (!ME || !ME.is_admin) return;
  try {
    const users = await api("/api/admin/users");
    $("#adminUserCount").textContent = users.length + " người dùng";
    $("#adminUsers").innerHTML = users.map((u) => `<tr>
      <td class="mono">${u.id}</td>
      <td><b>${u.username}</b> ${u.is_admin ? '<span class="tag admin">ADMIN</span>' : ""} ${u.banned ? '<span class="tag no">BANNED</span>' : ""}</td>
      <td><span class="tag ${u.access ? "ok" : "no"}">${u.access_label}</span></td>
      <td class="mono">${u.task_count}</td>
      <td>${u.last_login ? new Date(u.last_login * 1000).toLocaleString("vi-VN") : "—"}</td>
      <td style="display:flex;gap:5px;flex-wrap:wrap">
        <button class="btn sm" onclick="grant(${u.id},'week')">1 tuần</button>
        <button class="btn sm" onclick="grant(${u.id},'month')">1 tháng</button>
        <button class="btn sm" onclick="grant(${u.id},'year')">1 năm</button>
        <button class="btn sm primary" onclick="grant(${u.id},'forever')">Vĩnh viễn</button>
        <button class="btn sm danger" onclick="grant(${u.id},'revoke')">Thu hồi</button>
        <button class="btn sm danger" onclick="banUser(${u.id})">${u.banned ? "Mở khoá" : "Khoá"}</button>
      </td>
    </tr>`).join("");

    const tasks = await api("/api/admin/tasks");
    $("#adminTaskCount").textContent = tasks.length + " task";
    $("#adminTasks").innerHTML = tasks.map((t) => `<tr>
      <td>${t.name}</td>
      <td class="mono">#${t.user_id}</td>
      <td><span class="pill">${t.tool}</span></td>
      <td><span class="tag ${t.status === "running" ? "ok" : "no"}">${STATUS_LABEL[t.status] || t.status}</span></td>
      <td class="mono">${fmtUptime(t.uptime || 0)}</td>
      <td class="mono">${t.sent_count || 0}</td>
      <td style="display:flex;gap:5px">
        <button class="btn sm danger" onclick="adminStop('${t.id}')">Đóng từ xa</button>
        <button class="btn sm" onclick="adminDel('${t.id}')">Xoá</button>
      </td>
    </tr>`).join("") || `<tr><td colspan="7" style="color:var(--muted)">Chưa có task</td></tr>`;
  } catch (e) { toast(e.message, "error"); }
}
async function grant(uid, duration) {
  try { await api(`/api/admin/users/${uid}/grant`, { method: "POST", body: JSON.stringify({ duration }) }); toast("Đã cấp quyền " + duration, "success"); loadAdmin(); } catch (e) { toast(e.message, "error"); }
}
async function banUser(uid) { try { await api(`/api/admin/users/${uid}/ban`, { method: "POST" }); toast("Đã cập nhật", "success"); loadAdmin(); } catch (e) { toast(e.message, "error"); } }
async function adminStop(id) { try { await api(`/api/admin/tasks/${id}/stop`, { method: "POST" }); toast("Đã đóng task từ xa", "warn"); loadAdmin(); } catch (e) { toast(e.message, "error"); } }
async function adminDel(id) { if (!confirm("Xoá task?")) return; try { await api(`/api/admin/tasks/${id}`, { method: "DELETE" }); toast("Đã xoá", "success"); loadAdmin(); } catch (e) { toast(e.message, "error"); } }
$("#btnBroadcast").onclick = () => openModal("overlayBroadcast");
$("#btnSendBroadcast").onclick = async () => {
  const message = $("#broadcastMsg").value.trim();
  if (!message) return toast("Nhập nội dung", "warn");
  try { await api("/api/admin/broadcast", { method: "POST", body: JSON.stringify({ message }) }); toast("Đã phát thông báo", "success"); closeModal("overlayBroadcast"); } catch (e) { toast(e.message, "error"); }
};

/* ---------------- websocket ---------------- */
function connectWS() {
  if (!TOKEN) return;
  if (ws) ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?token=${TOKEN}`);
  ws.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      if (d.type === "tasks") {
        TASKS = d.tasks;
        if (!$("#viewDash").classList.contains("hidden")) renderTasks();
        if (!$("#viewAdmin").classList.contains("hidden") && ME && ME.is_admin) loadAdmin();
        // notifications toast (dedupe by id)
        (d.notifications || []).forEach((n) => {
          if (!window.__seenNotif) window.__seenNotif = new Set();
          if (!window.__seenNotif.has(n.id)) {
            window.__seenNotif.add(n.id);
            toast("📢 " + n.message, n.level === "success" ? "success" : "info");
          }
        });
      }
    } catch (e) {}
  };
  ws.onclose = () => { if (TOKEN) setTimeout(connectWS, 5000); };
  ws.onerror = () => {};
}

/* polling fallback (works even if websocket unavailable) */
setInterval(() => {
  if (!TOKEN || !ME) return;
  if ($("#viewDash").classList.contains("hidden") && $("#viewAdmin").classList.contains("hidden")) return;
  api("/api/tasks").then((t) => {
    TASKS = t;
    if (!$("#viewDash").classList.contains("hidden")) renderTasks();
  }).catch(() => {});
}, 4000);

/* ---------------- modals ---------------- */
function openModal(id) { $("#" + id).classList.add("open"); }
function closeModal(id) { $("#" + id).classList.remove("open"); }
function openRent() { openModal("overlayRent"); }
$$(".overlay").forEach((o) => o.addEventListener("click", (e) => { if (e.target === o) o.classList.remove("open"); }));

/* ---------------- boot ---------------- */
async function bootUser(retry = 0) {
  try {
    ME = await api("/api/me");
  } catch (e) {
    if (e.status === 401) { logoutLocal(); return; }
    // lỗi mạng / máy chủ: giữ token, thử lại thay vì đăng xuất
    if (retry < 3) {
      toast("Đang kết nối lại máy chủ...", "warn");
      await new Promise((r) => setTimeout(r, 1500 * (retry + 1)));
      return bootUser(retry + 1);
    }
    toast(e.message || "Không kết nối được máy chủ", "error");
    return;
  }
  $("#dashHello").textContent = `Xin chào ${ME.username} · ${ME.access_label}`;
  $("#accessTag").textContent = ME.access_label;
  $("#accessTag").className = "tag " + (ME.access ? "ok" : "no");
  $("#accessNotice").classList.toggle("hidden", ME.access || ME.is_admin);
  show("viewDash");
  await refreshTasks();
  connectWS();
}

async function boot() {
  try { TOOLS = await api("/api/tools"); } catch (e) { TOOLS = {}; }
  renderTools();
  if (TOKEN) {
    try { ME = await api("/api/me"); await bootUser(); }
    catch (e) { logoutLocal(); }
  } else {
    show("viewLanding");
  }
}

/* ---------------- snow ---------------- */
(function snow() {
  const c = $("#snow"), ctx = c.getContext("2d");
  let W, H, flakes = [];
  function resize() { W = c.width = innerWidth; H = c.height = innerHeight; }
  resize(); addEventListener("resize", resize);
  const N = Math.min(140, Math.floor(innerWidth / 12));
  for (let i = 0; i < N; i++) flakes.push({ x: Math.random() * W, y: Math.random() * H, r: Math.random() * 2.2 + 0.6, s: Math.random() * 0.8 + 0.3, d: Math.random() * Math.PI * 2 });
  function draw() {
    ctx.clearRect(0, 0, W, H);
    flakes.forEach((f) => {
      ctx.beginPath();
      ctx.arc(f.x, f.y, f.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${0.35 + f.r / 6})`;
      ctx.fill();
      f.y += f.s; f.x += Math.sin(f.d) * 0.4; f.d += 0.01;
      if (f.y > H + 5) { f.y = -5; f.x = Math.random() * W; }
      if (f.x > W + 5) f.x = -5; if (f.x < -5) f.x = W + 5;
    });
    requestAnimationFrame(draw);
  }
  draw();
})();

/* ---------------- music ---------------- */
let audioCtx = null, ambientOn = false, ambientNodes = [];
function ambientStart() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const master = audioCtx.createGain(); master.gain.value = 0.06; master.connect(audioCtx.destination);
    const freqs = [174.61, 220, 261.63, 329.63];
    freqs.forEach((fr, i) => {
      const o = audioCtx.createOscillator(); o.type = "sine"; o.frequency.value = fr;
      const g = audioCtx.createGain(); g.gain.value = 0.25;
      const lfo = audioCtx.createOscillator(); lfo.frequency.value = 0.05 + i * 0.02;
      const lg = audioCtx.createGain(); lg.gain.value = 0.15; lfo.connect(lg); lg.connect(g.gain);
      o.connect(g); g.connect(master); o.start(); lfo.start();
      ambientNodes.push(o, lfo);
    });
    ambientOn = true;
  } catch (e) {}
}
function ambientStop() { ambientNodes.forEach((n) => { try { n.stop(); } catch (e) {} }); ambientNodes = []; ambientOn = false; }
function setMusicUI(playing) {
  const eq = $("#eq"), dock = $("#musicDock");
  if (eq) eq.classList.toggle("hidden", !playing);
  if (dock) dock.classList.toggle("playing", playing);
}

const bgAudio = $("#bgMusic");
let musicWanted = true;
try { musicWanted = sessionStorage.getItem("pc_music") !== "0"; } catch (e) {}
let lastUnmuteAt = 0;
let musicRetry = 0;
let userUnmuted = false;

function markMusicState(on) { try { sessionStorage.setItem("pc_music", on ? "1" : "0"); } catch (e) {} }
function markPlaying() {
  setMusicUI(true);
  markMusicState(true);
  const dock = $("#musicDock");
  if (dock) dock.classList.remove("muted-hint");
}
function hintMuted() {
  const dock = $("#musicDock");
  if (dock) dock.classList.add("muted-hint");
}

/* Thử phát có tiếng trước; nếu trình duyệt chặn thì phát muted (im lặng),
   rồi mở tiếng ngay ở thao tác đầu tiên của người dùng. */
function attemptPlay(unmuted) {
  if (!bgAudio || !musicWanted) return Promise.reject(new Error("off"));
  if (userUnmuted) unmuted = true;
  bgAudio.muted = !unmuted;
  bgAudio.volume = 0.45;
  const p = bgAudio.play();
  if (!p || !p.then) return Promise.resolve();
  return p.then(() => {
    markPlaying();
    if (!unmuted) { armUnmute(); hintMuted(); }
    return true;
  }).catch(() => {
    if (unmuted) return attemptPlay(false);
    throw new Error("blocked");
  });
}

function armUnmute() {
  const unmute = () => {
    if (!musicWanted) return;
    lastUnmuteAt = Date.now();
    if (!bgAudio) return;
    bgAudio.muted = false;
    bgAudio.volume = 0.45;
    const p = bgAudio.paused ? bgAudio.play() : Promise.resolve();
    const done = () => {
      userUnmuted = true;
      setMusicUI(true);
      EVENTS.forEach((ev) => document.removeEventListener(ev, unmute, true));
      toast("🎵 10 ngàn năm — h.ngocday~", "success");
    };
    if (p && p.then) p.then(done).catch(() => { bgAudio.muted = true; });
    else done();
  };
  EVENTS.forEach((ev) => document.addEventListener(ev, unmute, { capture: true, passive: true }));
}
const EVENTS = ["pointerdown", "pointermove", "keydown", "touchstart", "wheel", "scroll", "click"];

/* Vòng thử lại: vài trình duyệt chặn cả muted autoplay ở lần đầu */
function startMusicLoop() {
  if (!bgAudio || !musicWanted) { setMusicUI(false); return; }
  armUnmute(); // luôn sẵn sàng mở tiếng ngay khi người dùng chạm vào trang
  attemptPlay(true).catch(() => {
    hintMuted();
    const tick = () => {
      if (!musicWanted || userUnmuted || !bgAudio.paused) return;
      if (musicRetry++ > 20) return; // ~20s rồi thôi, chờ người dùng chạm
      attemptPlay(false).catch(() => setTimeout(tick, 1000));
    };
    setTimeout(tick, 300);
  });
}

function playMusic() {
  if (!bgAudio) return;
  musicWanted = true;
  musicRetry = 0;
  attemptPlay(true).then(() => toast("🎵 10 ngàn năm — h.ngocday~", "success"))
    .catch(() => { hintMuted(); toast("Bấm vào trang 1 lần để bật tiếng nhạc 🔊", "info"); });
}

$("#musicToggle").onclick = () => {
  if (!bgAudio) return;
  if (Date.now() - lastUnmuteAt < 500) return;
  if (bgAudio.paused) {
    playMusic();
  } else {
    bgAudio.pause();
    ambientStop();
    setMusicUI(false);
    musicWanted = false;
    markMusicState(false);
    toast("Đã tắt nhạc");
  }
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => setTimeout(startMusicLoop, 50));
} else {
  setTimeout(startMusicLoop, 50);
}
window.addEventListener("load", () => { if (bgAudio && bgAudio.paused && musicWanted) startMusicLoop(); });
if (bgAudio) {
  ["loadedmetadata", "canplay", "canplaythrough"].forEach((ev) =>
    bgAudio.addEventListener(ev, () => { if (musicWanted && bgAudio.paused) attemptPlay(false).catch(() => {}); }));
  bgAudio.addEventListener("playing", markPlaying);
  bgAudio.addEventListener("play", () => { markMusicState(true); setMusicUI(true); });
}

/* ---------------- Facebook UID & Box ---------------- */
let fbBoxes = [];
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
$("#btnFbInfo").onclick = () => { openModal("overlayFbInfo"); };
$("#btnFbFetch").onclick = async () => {
  const cookie = $("#fbCookie").value.trim();
  if (!cookie) return toast("Dán cookie Facebook trước đã", "warn");
  const btn = $("#btnFbFetch"); btn.disabled = true; btn.textContent = "Đang lấy...";
  $("#fbResult").innerHTML = '<div class="sub" style="color:var(--muted)">Đang kết nối Facebook...</div>';
  try {
    const data = await api("/api/fb/info", { method: "POST", body: JSON.stringify({ cookie }) });
    fbBoxes = data.boxes || [];
    let html = `<div class="card" style="padding:14px;margin-bottom:12px">
      <div style="font-size:12px;color:var(--muted)">UID</div>
      <div class="mono" style="font-size:18px;font-weight:800">${esc(data.uid)}</div>
      <div style="font-size:12px;color:var(--muted);margin-top:8px">Tên</div>
      <div style="font-weight:700">${esc(data.name)}</div>
    </div>`;
    if (fbBoxes.length) {
      html += `<div class="sub" style="margin-bottom:8px;color:var(--muted)">Tìm thấy <b style="color:#fff">${fbBoxes.length}</b> box:</div>
        <div style="max-height:260px;overflow:auto;display:flex;flex-direction:column;gap:6px">`;
      fbBoxes.forEach((b) => {
        const meta = [b.type, b.count ? b.count + " tin" : ""].filter(Boolean).join(" · ");
        html += `<div class="task" style="grid-template-columns:1fr auto;padding:9px 12px;gap:8px">
          <div><div style="font-size:13px;font-weight:600">${esc(b.name || "(box " + b.id + ")")}</div>
          <div class="mono" style="font-size:11px;color:var(--muted)">${esc(b.id)}${meta ? " · " + esc(meta) : ""}</div>
          ${b.snippet ? `<div style="font-size:11px;color:#6f6f7a;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(b.snippet)}</div>` : ""}</div>
          <button class="btn sm" data-copy="${esc(b.id)}">Copy</button></div>`;
      });
      html += `</div>`;
    } else {
      html += `<div class="sub" style="color:var(--muted)">${esc(data.note || "Không đọc được danh sách box (cookie có thể thiếu quyền hoặc FB chặn). UID vẫn dùng được.")}</div>`;
    }
    $("#fbResult").innerHTML = html;
    $("#btnFbCopyAll").disabled = fbBoxes.length === 0;
    $("#fbResult").querySelectorAll("[data-copy]").forEach((el) => {
      el.onclick = () => { navigator.clipboard?.writeText(el.dataset.copy); toast("Đã copy " + el.dataset.copy, "success"); };
    });
    toast(`Lấy xong: UID ${data.uid} · ${fbBoxes.length} box`, "success");
  } catch (e) {
    $("#fbResult").innerHTML = `<div class="sub" style="color:var(--danger)">${esc(e.message)}</div>`;
    toast(e.message, "error");
  } finally { btn.disabled = false; btn.textContent = "Lấy thông tin"; }
};
$("#btnFbCopyAll").onclick = () => {
  const ids = fbBoxes.map((b) => b.id).join("\n");
  navigator.clipboard?.writeText(ids);
  toast("Đã copy " + fbBoxes.length + " ID box", "success");
};

boot();
