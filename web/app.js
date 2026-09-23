/* ==========================================================================
   freedom-accounts · 前端逻辑
   --------------------------------------------------------------------------
   唯一职责：调用后端 /api/*，把结果渲染进 index.html 定义的组件结构。
   本文件不出现任何色值与字号 —— 视觉一律由 tokens.css / style.css 承担。
   后端接口路径与载荷字段严格保持原样，本次重构不触碰契约。

   已知契约差异（已在本文件中适配）：
   · GET /api/tasks        —— steps / result_json 已由后端 json.loads 解析为数组 / 对象
   · GET /api/tasks/{id}   —— 返回 tasks 表原始行：steps 是 JSON 字符串，
                              且不含 group_name / username，须由列表行带入
   · GET /api/accounts/{id}/tasks —— 同样是原始行
   ========================================================================== */

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

let TOKEN = "";
const state = {
  tab: "groups",
  groups: [],
  accounts: [],
  currentGroup: null,
  editingGroup: null,
  editingAccount: null,
  accountModalMode: "single",
  taskFilter: "",
  meta: { login_types: [], group_types: [] },
  proxies: [],
  editingProxy: null,
  fpBase: {},
  defaultGeo: null,          // global default geo from settings (prefill source)
  proxyGeoPrefilled: false,  // geo fields already backfilled in current modal session
  expandedGroups: new Set(), // 操作项展开态：只由箭头 .group-toggle 写入，与选中态 / 账号列表完全解耦
  localEngine: true,         // 未配置 cloakserve CDP（本地 SDK 引擎）；「打开浏览器」按钮的渲染依据
  accountSort: { field: null, dir: "asc" }, // 账号表排序：field = 列 data-sort 值，dir = asc|desc
  selectedAccounts: new Set(), // 当前分组勾选的账号 ID；批量操作按此过滤
  accountAutoRefreshTimer: null, // 账号列表自动刷新定时器；null 表示当前未排队
};

/* ==========================================================================
   通用工具
   ========================================================================== */

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function modeText(m) {
  return m === "headed" ? "有头" : m === "headless" ? "无头" : "跟随系统";
}

/** 时间统一裁到「分钟」，表格里不需要秒级噪声 */
function fmtTime(v) {
  if (!v) return "—";
  const s = String(v).replace("T", " ");
  return s.length > 16 ? s.slice(0, 16) : s;
}

function safeJson(v, fallback) {
  if (v == null || v === "") return fallback;
  if (typeof v === "object") return v;
  try { return JSON.parse(v); } catch (_) { return fallback; }
}

/** 空对象 / 空数组视为「无内容」，避免详情里出现一个孤零零的 {} */
function isEmpty(v) {
  if (!v) return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v).length === 0;
  return false;
}

/** 展示用 URL：去掉协议头，避免在窄列里浪费横向空间 */
function displayUrl(u) {
  return String(u || "").replace(/^https?:\/\//, "");
}

const ENGINE_LABEL = { cloakbrowser: "CloakBrowser", playwright: "Playwright Chromium", chromium: "Chromium" };

function engineLabel(id) {
  if (!id) return "未知";
  return ENGINE_LABEL[String(id).toLowerCase()] || String(id);
}

/** 统一的后端调用入口。401 一律视为会话失效，直接退回登录视图。 */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401) { showLogin(); throw new Error("登录状态已失效，请重新登录"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

let toastTimer;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = isErr ? "toast is-error" : "toast";   // 重置 class 即移除 hidden
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 2600);
}

/* ==========================================================================
   主题（浅色 / 暗色）
   ========================================================================== */

const THEME_KEY = "fa_theme";
const ICON_MOON = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M13.3 9.7A5.7 5.7 0 0 1 6.3 2.7a5.7 5.7 0 1 0 7 7z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>';
const ICON_SUN = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><circle cx="8" cy="8" r="3.1" stroke="currentColor" stroke-width="1.4"/><path d="M8 1.4v1.6M8 13v1.6M14.6 8h-1.6M3 8H1.4M12.7 3.3l-1.1 1.1M4.4 11.6l-1.1 1.1M12.7 12.7l-1.1-1.1M4.4 4.4l-1.1-1.1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';

/** 图标表示「将要切换到的模式」：浅色下显示月亮，暗色下显示太阳。 */
function applyTheme(mode, persist = true) {
  const next = mode === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  if (persist) { try { localStorage.setItem(THEME_KEY, next); } catch (_) {} }
  const btn = $("#theme-btn");
  if (btn) {
    btn.innerHTML = next === "dark" ? ICON_SUN : ICON_MOON;
    btn.setAttribute("aria-pressed", String(next === "dark"));
  }
}

$("#theme-btn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  applyTheme(cur === "dark" ? "light" : "dark");
});

/* ==========================================================================
   视图切换
   ========================================================================== */

function showLogin() {
  $("#view-main").classList.add("hidden");
  $("#view-login").classList.remove("hidden");
}

function showMain() {
  $("#view-login").classList.add("hidden");
  $("#view-main").classList.remove("hidden");
  switchTab("groups");
  loadAll();
}

const TAB_META = {
  groups: { title: "分组与账号", sub: "按分组管理账号与浏览器指纹，一键批量上号（回调由适配器内部完成）" },
  tasks: { title: "任务日志", sub: "查看上号任务的执行状态、步骤明细与适配器操作记录" },
  proxies: { title: "代理管理", sub: "维护上号代理：测试连通性、出口 IP 与耗时（ipify）" },
  settings: { title: "系统设置", sub: "浏览器模式、指纹引擎、日志保留与管理员凭据" },
};

function switchTab(tab) {
  state.tab = tab;
  $$(".rail-item").forEach((b) => b.classList.toggle("is-active", b.dataset.tab === tab));
  $$(".page").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${tab}`));
  $$(".act-set").forEach((s) => s.classList.toggle("hidden", s.dataset.for !== tab));
  const meta = TAB_META[tab] || { title: "", sub: "" };
  $("#page-title").textContent = meta.title;
  $("#page-sub").textContent = meta.sub;
  if (tab === "groups") scheduleAccountAutoRefresh();
  else stopAccountAutoRefresh();
  if (tab === "tasks") loadTasks();
  if (tab === "proxies") loadProxies();
  if (tab === "settings") loadSettings();
}

$$(".rail-item").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

/* 对话框内的 data-close 按钮统一关闭最近的 dialog */
$$("[data-close]").forEach((b) => b.addEventListener("click", () => {
  const dlg = b.closest("dialog");
  if (dlg) dlg.close();
}));

/* ==========================================================================
   二次确认对话框（替代原生 confirm，保证视觉与交互一致）
   ========================================================================== */

let confirmResolver = null;

function confirmDialog({ title, message, okText = "确认", danger = false }) {
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  const ok = $("#confirm-ok");
  ok.textContent = okText;
  ok.className = danger ? "btn btn-danger-solid" : "btn btn-primary";
  return new Promise((resolve) => {
    confirmResolver = resolve;
    $("#dlg-confirm").showModal();
  });
}

function settleConfirm(val) {
  if (!confirmResolver) return;
  const resolve = confirmResolver;
  confirmResolver = null;
  const dlg = $("#dlg-confirm");
  if (dlg.open) dlg.close();     // close 事件会再次进入本函数，但 resolver 已清空
  resolve(val);
}

$("#confirm-ok").addEventListener("click", () => settleConfirm(true));
$("#confirm-cancel").addEventListener("click", () => settleConfirm(false));
$("#dlg-confirm").addEventListener("close", () => settleConfirm(false));

/* ==========================================================================
   状态徽标
   ========================================================================== */

/* accounts.last_status: never|queued|running|token_queued|token_running|success|failed|cancelled
   tasks.status:        pending|queued|running|success|failed|callback_failed|cancelled */
const STATUS_MAP = {
  success: { label: "已完成", cls: "chip-success" },
  failed: { label: "失败", cls: "chip-danger" },
  callback_failed: { label: "回调失败", cls: "chip-danger" },
  queued: { label: "上号队列中", cls: "chip-warning" },
  running: { label: "正在上号", cls: "chip-info" },
  token_queued: { label: "刷新Token队列中", cls: "chip-warning" },
  token_running: { label: "正在刷新Token", cls: "chip-info" },
  pending: { label: "排队中", cls: "chip-warning" },
  never: { label: "未运行", cls: "chip-muted" },
  cancelled: { label: "已停止", cls: "chip-muted" },
};

const BUSY_ACCOUNT_STATUSES = new Set([
  "queued", "running", "token_queued", "token_running",
]);

function isAccountBusy(a) {
  return BUSY_ACCOUNT_STATUSES.has(a?.last_status);
}

function taskStatusChip(t) {
  if (t.operation === "token_refresh" && (t.status === "queued" || t.status === "running")) {
    return statusChip(`token_${t.status}`);
  }
  return statusChip(t.status);
}

function statusChip(s) {
  const m = STATUS_MAP[s] || { label: s || "未知", cls: "chip-muted" };
  return `<span class="chip ${m.cls}"><span class="chip-dot"></span>${esc(m.label)}</span>`;
}

/* accounts.remote_status: 上游（适配器已转中文），仅展示，不影响本地 enabled */
const REMOTE_STATUS_CLS = {
  "正常": "chip-success",
  "配额耗尽": "chip-warning",
  "限流中": "chip-warning",
  "退避中": "chip-warning",
  "已停用": "chip-muted",
  "错误": "chip-danger",
};

function remoteStatusChip(s) {
  if (!s) return '<span class="chip chip-muted">—</span>';
  const cls = REMOTE_STATUS_CLS[s] || "chip-plain";
  return `<span class="chip ${cls}"><span class="chip-dot"></span>${esc(s)}</span>`;
}

/* tasks.callback_status: none|ok|failed|skipped */
const CALLBACK_MAP = {
  ok: { label: "回调成功", cls: "chip-success" },
  failed: { label: "回调失败", cls: "chip-danger" },
  skipped: { label: "已跳过", cls: "chip-warning" },
  none: { label: "未配置", cls: "chip-muted" },
};

function callbackChip(s) {
  const m = CALLBACK_MAP[s] || { label: s || "—", cls: "chip-muted" };
  return `<span class="chip ${m.cls}">${esc(m.label)}</span>`;
}

/* ==========================================================================
   分组
   ========================================================================== */

async function loadAll() {
  // 分组卡片会展示注册表 label，必须先加载 meta，避免首屏短暂显示原始 key。
  await Promise.all([loadMeta(), loadEngine(), loadProxiesSilent()]);
  await loadGroups();
  if (state.currentGroup && state.groups.some((g) => String(g.id) === String(state.currentGroup))) {
    await loadAccounts(state.currentGroup);
  } else if (state.currentGroup) {
    closeAccountsPanel();
  }
}

/** 启动时静默拉一次代理列表，供账号表单「关联代理」下拉使用 */
async function loadProxiesSilent() {
  try {
    const d = await api("/api/proxies");
    state.proxies = d.proxies || [];
  } catch (_) { state.proxies = []; }
}

/* 注册表下拉（/api/meta）：分组类型 = 平台注册表，上号类型 = 流程适配器，fp_options = 指纹候选池 */
async function loadMeta() {
  try {
    state.meta = await api("/api/meta");
  } catch { state.meta = { login_types: [], group_types: [], fp_options: null }; }
  fillSelect($("#g-group_type"), state.meta.group_types.map((p) => ({ value: p.key, label: p.label })), "请选择分组类型");
  fillSelect($("#g-login_type"), state.meta.login_types.map((a) => ({ value: a.key, label: a.label })), "请选择上号类型");
  buildFpStaticSelects();
}

function fillSelect(sel, items, placeholder) {
  sel.innerHTML = "";
  const ph = document.createElement("option");
  ph.value = ""; ph.textContent = placeholder; ph.disabled = true;
  sel.appendChild(ph);
  items.forEach((it) => {
    const o = document.createElement("option");
    o.value = it.value; o.textContent = it.label;
    sel.appendChild(o);
  });
}

/* 上号类型 key -> 卡片短名（未注册的存量值原样显示；括号内的引擎说明不下沉到卡片） */
function loginTypeLabel(key) {
  const a = state.meta.login_types.find((x) => x.key === key);
  return a ? (a.label.split(/[（(]/)[0].trim() || key) : (key || "—");
}

/* 分组类型 key -> 显示名 */
function groupTypeLabel(key) {
  const p = state.meta.group_types.find((x) => x.key === key);
  return p ? p.label : (key || "—");
}

async function loadGroups() {
  const d = await api("/api/groups");
  state.groups = d.groups || [];
  renderGroups();
}

function renderGroups() {
  const grid = $("#groups-grid");
  grid.innerHTML = "";
  state.groups.forEach((g) => grid.appendChild(groupCard(g)));

  $("#group-count").textContent = `${state.groups.length} 个分组`;
}

function groupCard(g) {
  const el = document.createElement("div");
  const selected = String(state.currentGroup) === String(g.id);
  const open = state.expandedGroups.has(String(g.id));
  el.className = "group-card"
    + (selected ? " is-selected" : "")
    + (open ? " is-open" : "");
  el.dataset.id = g.id;
  el.tabIndex = 0;
  el.setAttribute("role", "button");
  // 卡体本身不再是「可展开」控件，它只负责选中并打开账号列表；
  // 操作项的展开态由右侧箭头（.group-toggle）独立持有，用 aria-expanded 表达。
  el.setAttribute("aria-current", selected ? "true" : "false");

  const running = (g.running_count || 0) > 0;
  const initial = (g.name || "·").trim().charAt(0).toUpperCase();
  const checking = (g.fp_check_result || "") === "检测中";
  el.innerHTML = `
    <div class="group-head">
      <span class="group-avatar" aria-hidden="true">${esc(initial)}</span>
      <div class="group-head-text">
        <div class="group-name-row">
          ${groupRiskDot(g)}
          <span class="group-name">${esc(g.name)}</span>
        </div>
        <span class="group-sub">${esc(groupTypeLabel(g.group_type))} · ${esc(loginTypeLabel(g.login_type))} · ${g.account_count || 0} 个账号</span>
      </div>
      ${running ? `<span class="chip chip-info"><span class="chip-dot"></span>运行中 ${g.running_count}</span>` : ""}
      <button class="icon-btn group-toggle" type="button" data-act="toggle"
        aria-expanded="${open}" aria-controls="group-actions-${g.id}"
        aria-label="${open ? "收起操作项" : "展开操作项"}" title="${open ? "收起操作项" : "展开操作项"}">
        <svg class="chev-down" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3.2 5.4L7 9.2l3.8-3.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <svg class="chev-up" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3.2 8.6L7 4.8l3.8 3.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </button>
    </div>
    <div class="group-actions" id="group-actions-${g.id}">
      <button class="btn btn-primary btn-sm" type="button" data-act="start">一键上号</button>
      <button class="btn btn-secondary btn-sm ${state.localEngine ? "" : "hidden"}" type="button" data-act="open-browser">打开浏览器</button>
      <button class="btn btn-secondary btn-sm ${state.localEngine ? "" : "hidden"}" type="button" data-act="close-browser">关闭浏览器</button>
      <button class="btn btn-secondary btn-sm" type="button" data-act="sync">同步账号</button>
      <button class="btn btn-secondary btn-sm" type="button" data-act="fpcheck" ${checking ? "disabled" : ""}>${checking ? "检测中…" : "指纹检测"}</button>
      <button class="btn btn-secondary btn-sm" type="button" data-act="edit">编辑</button>
      <button class="btn btn-secondary btn-sm is-danger" type="button" data-act="del">删除</button>
    </div>`;

  el.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "start") { e.stopPropagation(); return groupStart(g, []); }
    if (act === "open-browser") { e.stopPropagation(); return groupOpenBrowser(g); }
    if (act === "close-browser") { e.stopPropagation(); return groupCloseBrowser(g); }
    if (act === "sync") { e.stopPropagation(); return groupSync(g); }
    if (act === "fpcheck") { e.stopPropagation(); return groupFpCheck(g); }
    if (act === "edit") { e.stopPropagation(); return openGroupModal(g); }
    if (act === "del") { e.stopPropagation(); return groupDelete(g); }
    if (act === "toggle") {
      // 箭头只切换本卡片操作区的展开/收起，不联动账号列表
      e.stopPropagation();
      return toggleGroupCard(el);
    }
    // 点击卡片其余区域：选中并打开账号列表（已选中则重新加载）
    selectGroup(g.id);
  });
  el.addEventListener("keydown", (e) => {
    // 焦点在卡内按钮（箭头 / 操作项）上时交给它们自己处理，
    // 否则一次 Enter/Space 会既触发按钮、又冒泡到这里打开账号列表。
    if (e.target !== el) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectGroup(g.id); }
  });
  return el;
}

/** 切换单张分组卡片的操作项展开/收起（仅本卡片 .group-actions，不联动账号列表、不影响选中态） */
function toggleGroupCard(cardEl) {
  const id = String(cardEl.dataset.id);
  const willOpen = !state.expandedGroups.has(id);
  if (willOpen) state.expandedGroups.add(id);
  else state.expandedGroups.delete(id);
  cardEl.classList.toggle("is-open", willOpen);
  const btn = cardEl.querySelector(".group-toggle");
  if (btn) {
    btn.setAttribute("aria-expanded", String(willOpen));
    btn.setAttribute("aria-label", willOpen ? "收起操作项" : "展开操作项");
    btn.title = willOpen ? "收起操作项" : "展开操作项";
  }
}

/**
 * 分组风险圆点：置于分组名左侧，仅输出一个色点，悬停 tooltip 展示「风险等级/分数」。
 * 未检测过则不占位 —— 分组名左侧的位置是稀缺资源，不能塞「未检测」占位文字。
 */
function groupRiskDot(g) {
  const v = (g.fp_check_result || "").trim();
  if (!v) return "";
  const at = g.fp_check_at ? `模板检测于 ${g.fp_check_at}` : "";
  if (v === "检测中") return `<span class="fp-badge fp-badge-info" title="指纹模板检测中"></span>`;
  if (v.startsWith("失败")) return `<span class="fp-badge fp-badge-muted" title="${esc(v)}"></span>`;
  const [risk, score] = v.split("/");
  const level = fpLevel(risk);
  const tip = score ? `${level}风险/${score}` : `${level}风险`;
  return `<span class="fp-badge ${FP_LEVEL_CLS[level]}" title="${esc(at ? `${tip} · ${at}` : tip)}"></span>`;
}

/** 分组级指纹检测：用分组配置的公共指纹模板生成代表性指纹，验证模板可用性 */
async function groupFpCheck(g) {
  try {
    await api(`/api/groups/${g.id}/fp-check`, { method: "POST" });
    toast(`分组 ${g.name} 开始指纹模板检测`);
    await loadGroups();
    pollGroupFpCheck(g.id, 0);
  } catch (e) { toast(e.message, true); }
}

function pollGroupFpCheck(gid, tried) {
  if (tried >= 60) return;               // ~3 分钟后放弃轮询
  setTimeout(async () => {
    try {
      const d = await api("/api/groups");
      state.groups = d.groups || [];
      renderGroups();
      const grp = state.groups.find((x) => String(x.id) === String(gid));
      if (!grp) return;
      if ((grp.fp_check_result || "") === "检测中") {
        return pollGroupFpCheck(gid, tried + 1);
      }
      const v = (grp.fp_check_result || "").trim();
      if (v) toast(v.startsWith("失败") ? "指纹模板检测失败" : `模板检测结果：${v}`);
    } catch (_) { /* 网络抖动继续 */ }
  }, 3000);
}

async function groupSync(g) {
  const ok = await confirmDialog({
    title: `同步账号 · ${g.name}`,
    message: "将按上游账号 ID 比对：ID 已存在则仅更新上游信息（密码/2FA/指纹等本地配置不动），上游已移除的删除，新增的落库；与上游账号重复的其他账号将被停用。",
    okText: "开始同步",
  });
  if (!ok) return;
  try {
    const d = await api(`/api/groups/${g.id}/sync-accounts`, { method: "POST", body: {} });
    const bits = [`新增 ${d.created}`, `更新 ${d.updated || 0}`, `删除 ${d.deleted}`];
    if (d.disabled) bits.push(`停用重复 ${d.disabled}`);
    bits.push(`忽略 ${d.ignored}`);
    toast(`同步完成：${bits.join(" · ")}`);
    await loadGroups();
    if (String(state.currentGroup) === String(g.id)) await loadAccounts(g.id);
  } catch (e) { toast(e.message, true); }
}

async function selectGroup(id) {
  state.currentGroup = id;
  state.selectedAccounts.clear();
  // 只做「选中 + 打开账号列表」。操作项（.group-actions）的展开态完全由箭头控制，
  // 这里绝不写 is-open / expandedGroups —— 否则点卡体会顺带把操作项摊开。
  const g = state.groups.find((x) => String(x.id) === String(id));
  $$("#groups-grid .group-card").forEach((c) => {
    const on = String(c.dataset.id) === String(id);
    c.classList.toggle("is-selected", on);
    c.setAttribute("aria-current", on ? "true" : "false");
  });
  $("#accounts-panel").classList.remove("hidden");
  $("#accounts-title").textContent = `账号 · ${g ? g.name : ""}`;
  try { await loadAccounts(id); } catch (e) { toast(e.message, true); }
}

function closeAccountsPanel() {
  stopAccountAutoRefresh();
  state.currentGroup = null;
  state.accounts = [];
  state.selectedAccounts.clear();
  $("#accounts-panel").classList.add("hidden");
  // 只取消选中态；卡片操作项保持用户自己控制（箭头）的展开状态
  $$("#groups-grid .group-card").forEach((c) => {
    c.classList.remove("is-selected");
    c.setAttribute("aria-current", "false");
  });
}

$("#btn-close-accounts").addEventListener("click", closeAccountsPanel);

/* 账号表排序表头：点击切换 asc/desc */
$$("#accounts-table .th-sort").forEach((th) => {
  th.addEventListener("click", () => toggleAccountSort(th.dataset.sort));
});
$("#btn-new-group").addEventListener("click", () => openGroupModal());

$("#account-check-all").addEventListener("change", (e) => {
  const checked = e.currentTarget.checked;
  state.selectedAccounts = new Set(checked ? state.accounts.map((a) => String(a.id)) : []);
  renderAccountRows();
});

async function groupStart(g, selectedIds = selectedAccountIds()) {
  try {
    const d = await api(`/api/groups/${g.id}/start`, {
      method: "POST",
      body: { account_ids: selectedIds.length ? selectedIds : null },
    });
    toast(d.queued ? `已入队 ${d.queued} 个账号任务` : "已触发调度");
    setTimeout(loadGroups, 1200);
  } catch (e) { toast(e.message, true); }
}

/** 打开浏览器（仅本地 SDK 引擎可用）：用分组指纹模板 + 分组代理启动常驻有头浏览器 */
async function groupOpenBrowser(g) {
  try {
    const d = await api(`/api/groups/${g.id}/open-browser`, { method: "POST", body: {} });
    toast(d.reused ? `分组 ${g.name} 的浏览器已打开（复用现有窗口）` : `已为分组 ${g.name} 打开浏览器`);
    setTimeout(loadGroups, 800);
  } catch (e) { toast(e.message, true); }
}

async function groupCloseBrowser(g) {
  try {
    const d = await api(`/api/groups/${g.id}/close-browser`, { method: "POST", body: {} });
    toast(d.closed ? `分组 ${g.name} 的浏览器已关闭` : `分组 ${g.name} 没有打开的浏览器`);
  } catch (e) { toast(e.message, true); }
}
/** 「打开浏览器」按钮显隐：仅本地 SDK 引擎（未配置 cloakserve CDP）时可见。
 *  先写 state.localEngine 再改 DOM —— loadGroups 与 loadEngine 并行时，
 *  后渲染的卡片直接按状态生成，不依赖「显隐应用到已存在 DOM」的时序。 */
function applyOpenBrowserVisibility(cdpUrl) {
  state.localEngine = !(cdpUrl || "").trim();
  $$('[data-act="open-browser"], [data-act="close-browser"]').forEach((b) => b.classList.toggle("hidden", !state.localEngine));
}

$("#btn-group-start").addEventListener("click", async () => {
  if (!state.currentGroup) return;
  await groupStart({ id: state.currentGroup }, selectedAccountIds());
});

$("#btn-batch-fp").addEventListener("click", () => {
  if (!state.currentGroup) return toast("请先选择分组", true);
  const selectedIds = selectedAccountIds();
  const n = selectedIds.length || state.accounts.length;
  if (!n) return toast("该分组暂无账号", true);
  const g = state.groups.find((x) => String(x.id) === String(state.currentGroup));
  const hasTpl = g && g.fingerprint_template && Object.keys(g.fingerprint_template).length > 0;
  $("#batch-fp-sub").textContent = `将为分组「${g?.name || ""}」的 ${n} 个账号重写指纹，覆盖现有配置。` +
    (hasTpl ? "该分组已配置指纹模板。" : "该分组尚未配置指纹模板（模板方式将退化为完全随机）。");
  $("#form-batch-fp").reset();
  $("#dlg-batch-fp").showModal();
});

$("#form-batch-fp").addEventListener("submit", async (e) => {
  e.preventDefault();
  const mode = $("#batch-fp-mode").value;
  const selectedIds = selectedAccountIds();
  const n = selectedIds.length || state.accounts.length;
  const ok = await confirmDialog({
    title: "确认批量替换指纹",
    message: `分组内 ${n} 个账号的指纹将被覆盖（方式：${
      { seed_only: "仅换 seed", from_template: "按分组模板重建", random: "完全随机" }[mode]
    }），此操作不可撤销。`,
    okText: "执行替换",
  });
  if (!ok) return;
  try {
    const d = await api(`/api/groups/${state.currentGroup}/regenerate-fingerprints`, {
      method: "POST", body: { mode, account_ids: selectedIds.length ? selectedIds : null },
    });
    $("#dlg-batch-fp").close();
    toast(`已更新 ${d.updated} 个账号的指纹`);
    await loadAccounts(state.currentGroup);
  } catch (err) { toast(err.message, true); }
});

async function groupDelete(g) {
  const ok = await confirmDialog({
    title: `删除分组「${g.name}」`,
    message: `该分组下的 ${g.account_count || 0} 个账号、指纹配置与任务记录将一并删除，此操作不可撤销。`,
    okText: "删除分组",
    danger: true,
  });
  if (!ok) return;
  try {
    await api(`/api/groups/${g.id}`, { method: "DELETE" });
    if (String(state.currentGroup) === String(g.id)) closeAccountsPanel();
    toast("分组已删除");
    await loadGroups();
  } catch (e) { toast(e.message, true); }
}

/* ---------- 分组表单 ---------- */

function openGroupModal(g = null) {
  state.editingGroup = g;
  $("#dlg-group-title").textContent = g ? `编辑分组 #${g.id}` : "新建分组";
  $("#g-group_type").value = g?.group_type || "";
  $("#g-name").value = g?.name || "";
  $("#g-login_type").value = g?.login_type || "";
  // 未知存量值（旧自由文本）不在下拉里：编辑时回填为临时项避免丢数据
  if (g && $("#g-group_type").value !== (g.group_type || "")) addTempOption($("#g-group_type"), g.group_type);
  if (g && $("#g-login_type").value !== (g.login_type || "")) addTempOption($("#g-login_type"), g.login_type);
  $("#g-login_url").value = g?.login_url || "";
  $("#g-upstream_key").value = g?.upstream_key || "";
  $("#g-concurrency").value = g?.concurrency ?? 1;
  $("#g-interval_min_ms").value = g?.interval_min_ms ?? 5000;
  $("#g-interval_max_ms").value = g?.interval_max_ms ?? 10000;
  $("#g-browser_mode").value = g?.browser_mode || "inherit";
  $("#g-fp_check_url").value = g?.fp_check_url || "";
  fillProxySelect(g?.proxy_id || "", "#g-proxy_id", "不使用代理（直连）");
  fillTplForm(g?.fingerprint_template || {});
  syncGroupTypeHints();
  $("#dlg-group").showModal();
}

function addTempOption(sel, value) {
  if (!value) return;
  const o = document.createElement("option");
  o.value = value; o.textContent = `${value}（存量）`;
  sel.appendChild(o);
  sel.value = value;
}

/* ---------- 指纹选项池（单一来源：/api/meta 的 fp_options，与后端随机共用一份数据） ---------- */

const FP_FALLBACK = {
  platforms: ["windows", "macos"],
  brands: ["Chrome", "Edge", "Opera", "Vivaldi"],
  brand_versions: Array.from({ length: 22 }, (_, i) => 130 + i),
  gpus: {
    windows: [{ vendor: "Google Inc. (Intel)", renderer: "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)", label: "Intel UHD 630" }],
    macos: [{ vendor: "Google Inc. (Apple)", renderer: "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)", label: "Apple M1" }],
  },
  screens: {
    windows: [{ width: 1920, height: 1080 }],
    macos: [{ width: 1440, height: 900 }],
  },
  cores: { windows: [8], macos: [8] },
  memory: [4, 8],
  timezones: ["Asia/Shanghai", "Asia/Tokyo", "America/New_York", "America/Chicago", "Europe/London", "Europe/Berlin", "Asia/Singapore", "America/Los_Angeles"],
  locales: ["zh-CN", "en-US", "en-GB", "ja-JP", "ko-KR", "de-DE"],
};

function fpOptions() { return state.meta.fp_options || FP_FALLBACK; }

/** 平台变化后级联刷新 GPU / 分辨率 / CPU 三个平台相关下拉；keepVal 兼容存量自由值 */
function refreshFpDependentSelects(pfx, platform, keepVals = {}) {
  const opt = fpOptions();
  const p = platform || "windows";
  const fill = (id, items, toVal, toLabel) => {
    const sel = $(id);
    const cur = keepVals[id] ?? sel.value;
    sel.innerHTML = `<option value="">默认</option>`;
    items.forEach((it) => {
      const o = document.createElement("option");
      o.value = toVal(it); o.textContent = toLabel(it);
      sel.appendChild(o);
    });
    if (cur) {
      sel.value = cur;
      // 存量值不在候选（历史数据 / 兜底池）：回填临时项避免丢数据
      if (sel.value !== cur) addTempOption(sel, cur);
    }
  };
  fill(`${pfx}-gpu`, opt.gpus[p] || [], (g) => g.renderer, (g) => g.label);
  fill(`${pfx}-screen`, opt.screens[p] || [], (s) => `${s.width}x${s.height}`, (s) => `${s.width} × ${s.height}`);
  fill(`${pfx}-cores`, opt.cores[p] || [], (n) => String(n), (n) => `${n} 核`);
}

/** 组装静态下拉（时区 / 语言 / 内存）——两处表单共用，加载 meta 后调用一次 */
function buildFpStaticSelects() {
  const opt = fpOptions();
  const fill = (id, items) => {
    const sel = $(id);
    if (!sel || sel.options.length > 1) return;
    items.forEach((v) => {
      const o = document.createElement("option");
      o.value = String(v); o.textContent = String(v);
      sel.appendChild(o);
    });
  };
  ["#fp-tz", "#gt-tz"].forEach((id) => fill(id, opt.timezones));
  ["#fp-locale", "#gt-locale"].forEach((id) => fill(id, opt.locales));
  ["#fp-mem", "#gt-mem"].forEach((id) => fill(id, opt.memory));
  // 平台相关下拉按当前平台值刷一遍（初始默认 windows 池）
  refreshFpDependentSelects("#fp", $("#fp-platform").value);
  refreshFpDependentSelects("#gt", $("#gt-platform").value);
}

/* ---------- 分组表单 ---------- */

/* 分组类型 -> 上号地址占位/提示、上号类型默认值联动 */
function syncGroupTypeHints() {
  const key = $("#g-group_type").value;
  const p = state.meta.group_types.find((x) => x.key === key);
  const urlInput = $("#g-login_url");
  urlInput.placeholder = p?.login_url_hint || "https://...";
  $("#g-login_url_hint").textContent = p?.description || "";
  const lt = $("#g-login_type");
  const ltMeta = state.meta.login_types.find((a) => a.key === lt.value);
  $("#g-login_type_hint").textContent = ltMeta?.description || "";
}

$("#g-group_type").addEventListener("change", () => {
  const key = $("#g-group_type").value;
  const p = state.meta.group_types.find((x) => x.key === key);
  // 新建时按平台默认值选中上号类型；编辑时不覆盖已存值
  if (!state.editingGroup && p?.default_login_type) $("#g-login_type").value = p.default_login_type;
  syncGroupTypeHints();
});

$("#g-login_type").addEventListener("change", syncGroupTypeHints);

/* 分组指纹模板：屏幕/GPU 合并为一个下拉，读写时拆合为 screen_width/screen_height 与 gpu_renderer */
const TPL_FIELDS = [
  ["#gt-platform", "platform", "str"],
  ["#gt-brand", "brand", "str"],
  ["#gt-tz", "timezone", "str"],
  ["#gt-locale", "locale", "str"],
  ["#gt-cores", "hardware_concurrency", "num"],
  ["#gt-mem", "device_memory", "num"],
];

function fillTplForm(tpl) {
  for (const [id, key] of TPL_FIELDS) $(id).value = tpl[key] ?? "";
  $("#gt-screen").value = tpl.screen_width && tpl.screen_height ? `${tpl.screen_width}x${tpl.screen_height}` : "";
  if ($("#gt-screen").value !== (tpl.screen_width && tpl.screen_height ? `${tpl.screen_width}x${tpl.screen_height}` : "")) {
    addTempOption($("#gt-screen"), `${tpl.screen_width}x${tpl.screen_height}`);
  }
  $("#gt-gpu").value = tpl.gpu_renderer || "";
  if ($("#gt-gpu").value !== (tpl.gpu_renderer || "")) addTempOption($("#gt-gpu"), tpl.gpu_renderer || "");
  // 刷新平台相关下拉候选（screen/cores），保持与所选平台一致
  refreshFpDependentSelects("#gt", tpl.platform || $("#gt-platform").value);
}

function readTplForm() {
  const tpl = {};
  for (const [id, key, type] of TPL_FIELDS) {
    const v = $(id).value.trim();
    if (!v) continue;
    tpl[key] = type === "num" ? +v : v;
  }
  if ($("#gt-screen").value) {
    const [w, h] = $("#gt-screen").value.split("x").map(Number);
    if (w && h) { tpl.screen_width = w; tpl.screen_height = h; }
  }
  if ($("#gt-gpu").value) tpl.gpu_renderer = $("#gt-gpu").value;
  return tpl;
}

/* 分组模板平台切换 -> 级联刷新 GPU / 分辨率 / CPU 候选 */
$("#gt-platform").addEventListener("change", () => {
  refreshFpDependentSelects("#gt", $("#gt-platform").value);
});

$("#btn-gtmpl-random").addEventListener("click", () => {
  const fp = randomFp();
  delete fp.seed; // template never pins a seed
  fillTplForm(fp);
});

/* 已保存时区数据（timezone/region/city 任一非空即视为已配置） */
function geoHasData(geo) {
  return !!(geo && [geo.timezone, geo.region, geo.city].some((v) => (v || "").trim()));
}

/* ---------- 指纹变更对比（分组模板 + 账号指纹共用） ---------- */

/* 指纹字段中文名（用于确认弹窗展示） */
const FP_FIELD_LABEL = {
  seed: "种子 seed",
  platform: "平台",
  brand: "品牌",
  brand_version: "浏览器版本",
  screen_width: "屏幕宽",
  screen_height: "屏幕高",
  timezone: "时区",
  locale: "语言",
  hardware_concurrency: "CPU 核心",
  device_memory: "内存",
  gpu_vendor: "WebGL 厂商",
  gpu_renderer: "WebGL 渲染器",
  webrtc_ip: "WebRTC IP",
  storage_quota_mb: "存储配额",
  noise: "指纹噪声",
  user_agent: "User Agent",
  viewport_w: "视口宽",
  viewport_h: "视口高",
  geoip: "GeoIP",
};

/** 归一化比较值：空值统一为 ""，数字与等值字符串视为相同 */
function fpNorm(v) {
  if (v === undefined || v === null) return "";
  return String(v).trim();
}

/** 返回两份指纹间被修改的字段中文名列表（仅列出「会引起指纹变化」的差异） */
function fpChangedFields(oldFp, newFp) {
  const keys = new Set([...Object.keys(oldFp || {}), ...Object.keys(newFp || {})]);
  const changed = [];
  for (const k of keys) {
    if (fpNorm(oldFp?.[k]) !== fpNorm(newFp?.[k])) changed.push(FP_FIELD_LABEL[k] || k);
  }
  return changed;
}

/** 保存前统一确认：指纹有变化时弹二次确认；无变化直接放行。 */
async function confirmFpChange(oldFp, newFp, what) {
  const changed = fpChangedFields(oldFp, newFp);
  if (!changed.length) return true;
  return confirmDialog({
    title: `确认修改${what}`,
    message: `以下指纹配置将被修改：${changed.join("、")}。指纹变化会使该${what}对应浏览器的身份发生改变，已登录会话可能失效。确认保存吗？`,
    okText: "保存",
  });
}

/* 「回填时区」无数据时的统一提示：引导先去代理管理或系统设置配置 */
async function warnNoGeoData() {
  await confirmDialog({
    title: "暂无已保存的时区数据",
    message: "当前账号/分组未关联代理（或代理未配置时区），系统设置中也未保存默认时区位置。请先在「代理管理」为代理配置时区位置，或在「系统设置 → 默认时区位置」填写并保存，再回来回填。",
    okText: "我知道了",
  });
}

/* 分组卡上已 join 代理 geo（proxy_* 前缀），归一化为统一 geo 视图 */
function groupProxyGeo(g) {
  if (!g) return null;
  return {
    country: g.proxy_country || "",
    region: g.proxy_region || "",
    city: g.proxy_city || "",
    timezone: g.proxy_timezone || "",
    locale: g.proxy_locale || "",
  };
}

/* 分组模板：回填已保存的时区数据（分组代理 > 系统设置默认），不发起任何解析请求 */
$("#btn-gtmpl-geo").addEventListener("click", async () => {
  const gid = state.editingGroup?.id;
  const proxyId = $("#g-proxy_id").value;
  let geo = null;
  if (proxyId) {
    geo = (state.proxies || []).find((p) => String(p.id) === String(proxyId)) || null;
  }
  if (!geoHasData(geo) && gid) {
    const g = (state.groups || []).find((x) => String(x.id) === String(gid));
    geo = groupProxyGeo(g) || geo;         // 分组代理上已保存的 geo
  }
  if (!geoHasData(geo) && geoHasData(state.defaultGeo)) geo = state.defaultGeo;
  if (!geoHasData(geo)) return warnNoGeoData();
  $("#gt-tz").value = geo.timezone || "";
  if (geo.timezone && $("#gt-tz").value !== geo.timezone) addTempOption($("#gt-tz"), geo.timezone);
  $("#gt-locale").value = geo.locale || "";
  if (geo.locale && $("#gt-locale").value !== geo.locale) addTempOption($("#gt-locale"), geo.locale);
  toast(`已回填：${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(" / ")}`);
});

$("#btn-gtmpl-clear").addEventListener("click", () => fillTplForm({}));

/* 提交挂在 form 上，而不是按钮的 click 上 —— 这样浏览器原生的 required 校验才会生效 */
$("#form-group").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = {
    group_type: $("#g-group_type").value.trim(),
    name: $("#g-name").value.trim(),
    login_type: $("#g-login_type").value.trim(),
    login_url: $("#g-login_url").value.trim(),
    upstream_key: $("#g-upstream_key").value.trim(),
    concurrency: +$("#g-concurrency").value || 1,
    interval_min_ms: +$("#g-interval_min_ms").value || 5000,
    interval_max_ms: +$("#g-interval_max_ms").value || 10000,
    browser_mode: $("#g-browser_mode").value,
    fp_check_url: $("#g-fp_check_url").value.trim(),
    proxy_id: $("#g-proxy_id").value ? +$("#g-proxy_id").value : null,
    fingerprint_template: readTplForm(),
  };
  // 指纹模板任一字段变化时二次确认（新建无原值，不弹）
  if (state.editingGroup) {
    const oldTpl = safeJson(state.editingGroup.fingerprint_template, {});
    const ok = await confirmFpChange(oldTpl, body.fingerprint_template, `分组「${state.editingGroup.name}」的指纹模板`);
    if (!ok) return;
  }
  try {
    if (state.editingGroup) await api(`/api/groups/${state.editingGroup.id}`, { method: "PUT", body });
    else await api("/api/groups", { method: "POST", body });
    $("#dlg-group").close();
    toast("分组已保存");
    await loadAll();
  } catch (err) { toast(err.message, true); }
});

/* ==========================================================================
   账号
   ========================================================================== */

async function loadAccounts(gid) {
  const d = await api(`/api/accounts?group_id=${gid}`);
  state.accounts = sortAccounts(d.accounts || []);
  state.selectedAccounts = new Set(
    [...state.selectedAccounts].filter((id) => state.accounts.some((a) => String(a.id) === String(id))));
  renderAccountRows();
  scheduleAccountAutoRefresh();
}

function stopAccountAutoRefresh() {
  clearTimeout(state.accountAutoRefreshTimer);
  state.accountAutoRefreshTimer = null;
}

function scheduleAccountAutoRefresh() {
  stopAccountAutoRefresh();
  const seconds = +$("#account-auto-refresh").value;
  const canRun = seconds > 0
    && state.tab === "groups"
    && state.currentGroup != null
    && !$("#accounts-panel").classList.contains("hidden")
    && !$("#view-main").classList.contains("hidden");
  if (!canRun) return;

  state.accountAutoRefreshTimer = setTimeout(async () => {
    state.accountAutoRefreshTimer = null;
    const gid = state.currentGroup;
    try {
      await loadAccounts(gid);
    } catch (e) {
      // 刷新失败不能让列表静默停在旧数据；登录失效时不再继续后台轮询。
      toast(e.message, true);
      scheduleAccountAutoRefresh();
    }
  }, seconds * 1000);
}

$("#account-auto-refresh").addEventListener("change", scheduleAccountAutoRefresh);

/** Sort accounts by the active sort field; Chinese-safe localeCompare for text fields. */
function sortAccounts(accounts) {
  const { field, dir } = state.accountSort;
  if (!field || dir === "") return accounts;
  const mul = dir === "desc" ? -1 : 1;
  return [...accounts].sort((a, b) => {
    let va = a[field], vb = b[field];
    // empty values always sink to the bottom
    const emptyA = va == null || va === "";
    const emptyB = vb == null || vb === "";
    if (emptyA && emptyB) return 0;
    if (emptyA) return 1;
    if (emptyB) return -1;
    if (field === "last_run_at") {
      // timestamp strings sort lexicographically
      return mul * String(va).localeCompare(String(vb));
    }
    return mul * String(va).localeCompare(String(vb), "zh-Hans-CN");
  });
}

/** Toggle account sort on th click; re-render the table body. */
function toggleAccountSort(field) {
  if (state.accountSort.field === field) {
    state.accountSort.dir = state.accountSort.dir === "asc" ? "desc" : "asc";
  } else {
    state.accountSort = { field, dir: "asc" };
  }
  state.accounts = sortAccounts(state.accounts);
  renderAccountRows();
}

/** Re-render the accounts table body from state.accounts (without re-fetching). */
function renderAccountRows() {
  const tb = $("#accounts-table tbody");
  tb.innerHTML = "";
  state.accounts.forEach((a) => tb.appendChild(accountRow(a, state.currentGroup)));
  if (!state.accounts.length) {
    tb.innerHTML = '<tr><td colspan="11"><span class="empty-state">该分组暂无账号，点击上方「添加账号」创建。</span></td></tr>';
  }
  // update sort indicators on headers
  $$("#accounts-table .th-sort").forEach((th) => {
    const active = th.dataset.sort === state.accountSort.field;
    th.classList.toggle("is-sorted", active);
    th.classList.toggle("is-desc", active && state.accountSort.dir === "desc");
  });
  updateAccountSelectionUI();
}

function selectedAccountIds() {
  const ids = state.accounts
    .filter((a) => state.selectedAccounts.has(String(a.id)))
    .map((a) => Number(a.id));
  return [...new Set(ids)];
}

function updateAccountSelectionUI() {
  const total = state.accounts.length;
  const selected = selectedAccountIds().length;
  const checkAll = $("#account-check-all");
  checkAll.checked = total > 0 && selected === total;
  checkAll.indeterminate = selected > 0 && selected < total;
  const selectedBusy = state.accounts.some((a) =>
    state.selectedAccounts.has(String(a.id)) && isAccountBusy(a));
  $("#btn-batch-delete").disabled = selected === 0 || selectedBusy;
  const scope = selected ? `已选 ${selected}` : "ALL";
  $("#btn-group-start").textContent = `一键上号（${scope}）`;
  $("#btn-batch-fp").textContent = `批量换指纹（${scope}）`;
  const refreshing = state.accounts.some(isAccountBusy);
  $("#btn-batch-refresh-token").disabled = refreshing;
  $("#btn-batch-refresh-token").textContent = refreshing
    ? "账号任务进行中…"
    : `一键刷新Token（${scope}）`;
  $("#btn-batch-delete").textContent = selected ? `删除（已选 ${selected}）` : "删除账号";
}

function fpSummary(fp) {
  if (!fp || !fp.seed) return "未配置";
  const scr = fp.screen_width && fp.screen_height ? `${fp.screen_width}×${fp.screen_height}` : "—";
  return `#${fp.seed} · ${fp.platform || "—"} · ${scr} · ${fp.timezone || "—"}`;
}

function accountRow(a, gid) {
  const tr = document.createElement("tr");
  const on = !!a.enabled;
  const busy = isAccountBusy(a);
  const tokenBusy = a.last_status === "token_queued" || a.last_status === "token_running";
  const loginBusy = a.last_status === "queued" || a.last_status === "running";
  tr.classList.toggle("is-disabled", !on);
  tr.classList.toggle("is-selected", state.selectedAccounts.has(String(a.id)));
  const proxyName = a.proxy_name
    ? `代理 ${a.proxy_name}`
    : "直连";
  tr.innerHTML = `
    <td class="col-select">
      <input class="checkbox account-select" type="checkbox" data-act="select"
        data-id="${esc(a.id)}" ${state.selectedAccounts.has(String(a.id)) ? "checked" : ""}
        aria-label="选择账号 ${esc(a.username)}">
    </td>
    <td class="col-account">
      <span class="cell-stack">
        <span>${esc(a.username)}</span>
        <span class="cell-sub">${a.remote_id ? `ID ${esc(a.remote_id)} · ` : ""}${a.remote_remark ? esc(a.remote_remark) : "无备注"}</span>
      </span>
    </td>
    <td>${remoteStatusChip(a.remote_status)}</td>
    <td><span class="cell-mono">${esc(fpSummary(a.fingerprint))}</span></td>
    <td>${fpCheckChip(a)}</td>
    <td><span class="cell-muted">${modeText(a.browser_mode)}</span></td>
    <td><span class="chip ${a.proxy_name ? "chip-plain" : "chip-muted"}">${esc(proxyName)}</span></td>
    <td>
      <button class="switch ${on ? "is-on" : ""}" type="button" data-act="toggle-enabled"
        role="switch" aria-checked="${on}" title="${on ? "已启用，点击停用" : "已停用，点击启用"}">
        <span class="switch-knob"></span>
      </button>
    </td>
    <td>${statusChip(a.last_status)}</td>
    <td><span class="cell-muted">${esc(fmtTime(a.last_run_at))}</span></td>
    <td>
      <span class="cell-actions">
        ${on ? `<button class="link-btn" type="button" data-act="run" ${busy ? "disabled" : ""}>${a.last_status === "running" ? "上号中…" : busy ? "队列中…" : "上号"}</button>
        <button class="link-btn" type="button" data-act="fp" ${busy ? "disabled" : ""}>换指纹</button>
        <button class="link-btn" type="button" data-act="refresh-token" ${busy ? "disabled" : ""}>${tokenBusy ? "刷新中…" : "刷新Token"}</button>
        <button class="link-btn" type="button" data-act="fpcheck" ${busy || a.fp_check_result === "检测中" ? "disabled" : ""}>${a.fp_check_result === "检测中" ? "检测中…" : "指纹检测"}</button>
        ${loginBusy ? `<button class="link-btn" type="button" data-act="stop">停止</button>` : ""}
        <button class="link-btn" type="button" data-act="log">日志</button>` : `<span class="chip chip-warning">已停用</span>`}
        <button class="link-btn" type="button" data-act="edit">编辑</button>
        <button class="link-btn is-danger" type="button" data-act="del" ${busy ? "disabled" : ""}>删除</button>
      </span>
    </td>`;

  tr.addEventListener("click", async (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "select") {
      const id = String(e.target.closest(".account-select").dataset.id);
      if (e.target.checked) state.selectedAccounts.add(id);
      else state.selectedAccounts.delete(id);
      tr.classList.toggle("is-selected", e.target.checked);
      updateAccountSelectionUI();
      return;
    }
    if (act === "toggle-enabled") return toggleAccountEnabled(a, gid);
    if (act === "run") {
      if (!a.enabled) return toast("账号已停用，仅允许编辑/删除", true);
      if (busy) return toast("账号正在运行或排队，请稍后再试", true);
      return accountRun(a);
    }
    if (act === "stop") return stopAccountRun(a, gid);
    if (act === "edit") return openAccountModal(a);
    if (act === "fp") {
      if (!a.enabled) return toast("账号已停用，仅允许编辑/删除", true);
      if (busy) return toast("账号正在运行或排队，请稍后再试", true);
      return regenFp(a);
    }
    if (act === "refresh-token") {
      if (!a.enabled) return toast("账号已停用，仅允许编辑/删除", true);
      if (busy) return toast("账号正在运行或排队，请稍后再试", true);
      return refreshToken(a, gid);
    }
    if (act === "fpcheck") {
      if (!a.enabled) return toast("账号已停用，仅允许编辑/删除", true);
      if (busy) return toast("账号正在运行或排队，请稍后再试", true);
      return startFpCheck(a, gid);
    }
    if (act === "log") {
      if (!a.enabled) return toast("账号已停用，仅允许编辑/删除", true);
      return showAccountTasks(a);
    }
    if (act === "del") {
      const ok = await confirmDialog({
        title: `删除账号 ${a.username}`,
        message: "该账号的登录凭据、2FA 密钥与浏览器指纹将一并删除，此操作不可撤销。",
        okText: "删除账号",
        danger: true,
      });
      if (!ok) return;
      if (busy) return toast("账号正在运行或排队，不能删除", true);
      try {
        await api(`/api/accounts/${a.id}`, { method: "DELETE" });
        toast("账号已删除");
        state.selectedAccounts.delete(String(a.id));
        await loadAccounts(gid);
        await loadGroups();
      } catch (err) { toast(err.message, true); }
    }
  });
  return tr;
}

async function toggleAccountEnabled(a, gid) {
  const next = !a.enabled;
  if (!next && isAccountBusy(a)) return toast("账号正在运行或排队，不能停用", true);
  try {
    await api(`/api/accounts/${a.id}/enabled`, { method: "PUT", body: { enabled: next } });
    toast(next ? "账号已启用" : "账号已停用（仅可编辑/删除）");
    a.enabled = next ? 1 : 0;
    await loadAccounts(gid);
  } catch (e) { toast(e.message, true); }
}

async function accountRun(a) {
  if (isAccountBusy(a)) return toast("账号正在运行或排队，请稍后再试", true);
  if (!a.has_password) {
    toast(`账号 ${a.username} 未配置密码，请先编辑账号`, true);
    return;
  }
  try {
    const d = await api("/api/accounts/start", { method: "POST", body: { account_ids: [a.id] } });
    toast(`任务已入队（${d.queued}）`);
    setTimeout(() => loadAccounts(state.currentGroup), 1000);
  } catch (e) { toast(e.message, true); }
}

async function stopAccountRun(a, gid) {
  const queued = a.last_status === "queued";
  const ok = await confirmDialog({
    title: `停止上号：${a.username}`,
    message: queued
      ? "该账号仍在队列中，停止后会直接从队列移除。"
      : "该账号正在上号，停止后会中断后续流程并关闭指纹浏览器。",
    okText: "停止",
  });
  if (!ok) return;
  try {
    const d = await api(`/api/accounts/${a.id}/stop`, { method: "POST" });
    toast(d.action === "queued_removed" ? "已从队列移除" : "上号任务已停止");
    await loadAccounts(gid);
  } catch (e) { toast(e.message, true); }
}

async function regenFp(a) {
  const ok = await confirmDialog({
    title: "重新生成浏览器指纹",
    message: `将为账号 ${a.username} 随机生成一套新的指纹（平台、分辨率、时区、WebGL 等），覆盖现有配置。`,
    okText: "重新生成",
  });
  if (!ok) return;
  try {
    await api(`/api/accounts/${a.id}/regenerate-fingerprint`, { method: "POST" });
    toast("指纹已更新");
    await loadAccounts(state.currentGroup);
  } catch (e) { toast(e.message, true); }
}

async function refreshToken(a, gid) {
  if (isAccountBusy(a)) return toast("账号正在运行或排队，请稍后再试", true);
  const ok = await confirmDialog({
    title: `刷新 Token：${a.username}`,
    message: "账号级刷新会忽略 30 分钟窗口限制，但仍要求上游状态正常且能识别 Token 过期时间。",
    okText: "刷新 Token",
  });
  if (!ok) return;
  try {
    await api(`/api/accounts/${a.id}/refresh-token`, { method: "POST" });
    toast(`账号 ${a.username} 开始刷新 Token`);
    await loadAccounts(gid);
    pollTokenRefresh(gid, [Number(a.id)]);
  } catch (e) { toast(e.message, true); }
}

function pollTokenRefresh(gid, ids, tried = 0) {
  if (tried >= 900) return;             // 2s x 900：足够覆盖长批量任务
  setTimeout(async () => {
    if (String(state.currentGroup) !== String(gid)) return;
    try {
      await loadAccounts(gid);
      const refreshing = state.accounts.some((a) =>
        ids.includes(Number(a.id)) &&
        (a.last_status === "token_queued" || a.last_status === "token_running"));
      if (refreshing) return pollTokenRefresh(gid, ids, tried + 1);
    } catch { return pollTokenRefresh(gid, ids, tried + 1); }
  }, 2000);
}

$("#btn-batch-refresh-token").addEventListener("click", async () => {
  const gid = state.currentGroup;
  if (!gid) return toast("请先选择分组", true);
  const selectedIds = selectedAccountIds();
  const n = selectedIds.length || state.accounts.length;
  if (!n) return toast("该分组暂无账号", true);
  const ok = await confirmDialog({
    title: `一键刷新 ${n} 个账号 Token`,
    message: "将先同步上游数据；批量刷新仅处理上游状态正常且 Token 将在 30 分钟内过期的启用账号，多个账号之间间隔 5–20 秒。",
    okText: "开始刷新",
  });
  if (!ok) return;
  try {
    const d = await api(`/api/groups/${gid}/refresh-tokens`, {
      method: "POST",
      body: { account_ids: selectedIds.length ? selectedIds : null },
    });
    if (!d.queued) return toast(d.message || "没有需要刷新 Token 的启用账号", true);
    toast(`已提交 ${d.queued} 个账号刷新 Token`);
    await loadAccounts(gid);
    pollTokenRefresh(gid, d.accounts.map((a) => Number(a.id)));
  } catch (err) { toast(err.message, true); }
});

$("#btn-batch-delete").addEventListener("click", async () => {
  const selected = state.accounts.filter((a) => state.selectedAccounts.has(String(a.id)));
  if (!selected.length) return;
  const ok = await confirmDialog({
    title: `删除 ${selected.length} 个账号`,
    message: `将删除：${selected.map((a) => a.username).join("、")}。登录凭据、2FA 密钥与浏览器指纹将一并删除，此操作不可撤销。`,
    okText: "删除账号",
    danger: true,
  });
  if (!ok) return;
  try {
    const d = await api("/api/accounts/batch-delete", {
      method: "POST",
      body: { account_ids: selected.map((a) => Number(a.id)) },
    });
    toast(`已删除 ${d.deleted} 个账号`);
    state.selectedAccounts.clear();
    await loadAccounts(state.currentGroup);
    await loadGroups();
  } catch (err) { toast(err.message, true); }
});

/* ---------- 指纹检测 ---------- */

/* 检测结果风险等级 -> 圆点配色（绿=低 / 黄=中 / 红=高），悬停 tooltip 展示等级/分数 */
const FP_LEVEL_CLS = {
  "高": "fp-badge-danger",
  "中": "fp-badge-warning",
  "低": "fp-badge-success",
};

/** 从风险文案提取等级字："高风险"→高、"中等风险"→中、"极低风险"→低、"低"→低 */
function fpLevel(risk) {
  const s = (risk || "").replace("风险", "");
  if (/高/.test(s)) return "高";
  if (/中/.test(s)) return "中";
  if (/低/.test(s)) return "低";
  return "低";                     // 未知文案按最低风险兜底展示
}

/**
 * 指纹检测结果圆点徽标：仅一个色点，悬停 tooltip 展示「风险等级/分数」。
 * @param {string} v  fp_check_result 原始值："高风险/80" | "检测中" | "失败: ..." | ""
 * @param {string} at 检测时间（tooltip 附加）
 */
function fpBadge(v, at) {
  v = (v || "").trim();
  if (!v) return '<span class="cell-muted">未检测</span>';
  if (v === "检测中") return '<span class="chip chip-info"><span class="chip-dot"></span>检测中</span>';
  if (v.startsWith("失败")) return `<span class="chip chip-muted" title="${esc(v)}">${esc(v.slice(0, 14))}</span>`;
  const [risk, score] = v.split("/");
  const level = fpLevel(risk);
  const cls = FP_LEVEL_CLS[level];
  const tip = score ? `${level}风险/${score}` : `${level}风险`;
  const title = at ? `${tip} · ${at}` : tip;
  return `<span class="fp-badge ${cls}" title="${esc(title)}"></span>`;
}

/** 账号行检测结果徽标 */
function fpCheckChip(a) {
  return fpBadge(a.fp_check_result, a.fp_check_at);
}

async function startFpCheck(a, gid) {
  try {
    await api(`/api/accounts/${a.id}/fp-check`, { method: "POST" });
    toast(`账号 ${a.username} 开始指纹检测`);
    // 检测在后台执行：先立即刷新出「检测中」，再轮询拿最终结果
    await loadAccounts(gid);
    pollFpCheck(a.id, gid);
  } catch (e) { toast(e.message, true); }
}

function pollFpCheck(accountId, gid, tried = 0) {
  if (tried >= 60) return;               // ~3 分钟后放弃轮询
  setTimeout(async () => {
    if (String(state.currentGroup) !== String(gid)) return;
    try {
      const d = await api(`/api/accounts?group_id=${gid}`);
      state.accounts = d.accounts || [];
      const a = state.accounts.find((x) => x.id === accountId);
      if (a && a.fp_check_result === "检测中") return pollFpCheck(accountId, gid, tried + 1);
      await loadAccounts(gid);
      if (a) toast(a.fp_check_result.startsWith("失败")
        ? "指纹检测失败" : `检测结果：${a.fp_check_result}`);
    } catch (_) { /* 网络抖动时继续下一轮 */ }
  }, 3000);
}

/* ---------- 账号表单 ---------- */

function openAccountModal(a = null) {
  if (!state.currentGroup) { toast("请先选择分组", true); return; }
  state.editingAccount = a;
  state.accountModalMode = "single";
  state.fpBase = safeJson(a?.fingerprint, {});
  $("#dlg-account-title").textContent = a ? `编辑账号 #${a.id}` : "添加账号";
  $("#account-mode-seg").classList.toggle("hidden", !!a);
  setAccountModalMode("single");
  $("#a-bulk").value = "";
  $("#a-username").value = a?.username || "";
  $("#a-password").value = "";
  $("#a-totp").value = "";
  $("#a-browser_mode").value = a?.browser_mode || "inherit";
  $("#a-enabled").checked = a ? !!a.enabled : true;
  $("#a-enabled").value = a && !a.enabled ? "0" : "1";
  $("#a-remark").value = a?.remark || "";
  setAccountProxySummary(a);
  const fp = a?.fingerprint || {};
  fillAccountFpForm(fp);
  $("#dlg-account").showModal();
}

function setAccountModalMode(mode) {
  state.accountModalMode = mode === "bulk" ? "bulk" : "single";
  $$("#account-mode-seg .segmented-item").forEach((b) =>
    b.classList.toggle("is-active", b.dataset.mode === state.accountModalMode));
  $("#account-single-fields").classList.toggle("hidden", state.accountModalMode !== "single");
  $("#account-bulk-fields").classList.toggle("hidden", state.accountModalMode !== "bulk");
  $("#a-username").required = state.accountModalMode === "single";
  $("#a-password").required = state.accountModalMode === "single";
  $("#a-bulk").required = state.accountModalMode === "bulk";
  $("#account-input-title").textContent =
    state.accountModalMode === "bulk" ? "批量账号" : "账号信息";
}

$("#account-mode-seg").addEventListener("click", (e) => {
  const b = e.target.closest(".segmented-item");
  if (b) setAccountModalMode(b.dataset.mode);
});

$("#btn-toggle-account-env").addEventListener("click", (e) => {
  const open = $("#account-env-fields").classList.toggle("hidden");
  e.currentTarget.textContent = open ? "展开" : "收起";
  e.currentTarget.setAttribute("aria-expanded", String(!open));
});

/** 账号指纹表单回填：seed 手填，其余全部下拉（GPU/分辨率合并单选） */
function fillAccountFpForm(fp) {
  state.fpBase = { ...(fp || {}) };
  $("#fp-seed").value = fp.seed || "";
  $("#fp-platform").value = fp.platform || "";
  $("#fp-brand").value = fp.brand || "";
  refreshFpDependentSelects("#fp", fp.platform || "");
  $("#fp-screen").value = fp.screen_width && fp.screen_height ? `${fp.screen_width}x${fp.screen_height}` : "";
  if (fp.screen_width && fp.screen_height && $("#fp-screen").value !== `${fp.screen_width}x${fp.screen_height}`) {
    addTempOption($("#fp-screen"), `${fp.screen_width}x${fp.screen_height}`);
  }
  $("#fp-tz").value = fp.timezone || "";
  if (fp.timezone && $("#fp-tz").value !== fp.timezone) addTempOption($("#fp-tz"), fp.timezone);
  $("#fp-locale").value = fp.locale || "";
  if (fp.locale && $("#fp-locale").value !== fp.locale) addTempOption($("#fp-locale"), fp.locale);
  $("#fp-cores").value = fp.hardware_concurrency != null ? String(fp.hardware_concurrency) : "";
  if (fp.hardware_concurrency != null && $("#fp-cores").value !== String(fp.hardware_concurrency)) {
    addTempOption($("#fp-cores"), String(fp.hardware_concurrency));
  }
  $("#fp-mem").value = fp.device_memory != null ? String(fp.device_memory) : "";
  if (fp.device_memory != null && $("#fp-mem").value !== String(fp.device_memory)) {
    addTempOption($("#fp-mem"), String(fp.device_memory));
  }
  $("#fp-gpu").value = fp.gpu_renderer || "";
  if (fp.gpu_renderer && $("#fp-gpu").value !== fp.gpu_renderer) addTempOption($("#fp-gpu"), fp.gpu_renderer);
}

$("#btn-new-account").addEventListener("click", () => openAccountModal());

/** 代理下拉填充：第一项固定为直连；sel 可为账号或分组表单的下拉 */
function fillProxySelect(selected, selId = "#a-proxy_id", directLabel = "不使用代理（直连）") {
  const sel = $(selId);
  sel.innerHTML = `<option value="">${directLabel}</option>`;
  state.proxies.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = `${p.name}（${(p.server_masked || "").replace(/^[a-z0-9]+:\/\//, "")}）`;
    sel.appendChild(o);
  });
  sel.value = selected != null && selected !== "" ? String(selected) : "";
  // 存量值已不在列表（代理被删）：回填临时项避免丢数据
  if (selected && sel.value !== String(selected)) addTempOption(sel, selected);
}

/** 账号表单不再暴露账号级代理选项；已有覆盖只读展示，提交时原样保留。 */
function setAccountProxySummary(a) {
  const summary = $("#a-proxy-summary");
  const proxy = state.proxies.find((p) => String(p.id) === String(a?.proxy_id || ""));
  summary.textContent = proxy ? `账号代理：${proxy.name}` : "跟随分组代理";
  summary.className = "field-hint";
}

$("#btn-regen-fp").addEventListener("click", () => {
  fillAccountFpForm(randomFp());
});

/* 账号指纹：回填已保存的时区数据（账号代理 > 分组代理 > 系统设置默认），不发起解析请求 */
$("#btn-fp-geo").addEventListener("click", async () => {
  const proxyId = state.editingAccount?.proxy_id || "";
  const gid = state.editingAccount?.group_id || state.currentGroup;
  let geo = null;
  if (proxyId) {
    geo = (state.proxies || []).find((p) => String(p.id) === String(proxyId)) || null;
  }
  if (!geoHasData(geo) && gid) {
    const g = (state.groups || []).find((x) => String(x.id) === String(gid));
    geo = groupProxyGeo(g) || geo;         // 分组代理上已保存的 geo
  }
  if (!geoHasData(geo) && geoHasData(state.defaultGeo)) geo = state.defaultGeo;
  if (!geoHasData(geo)) return warnNoGeoData();
  $("#fp-tz").value = geo.timezone || "";
  if (geo.timezone && $("#fp-tz").value !== geo.timezone) addTempOption($("#fp-tz"), geo.timezone);
  $("#fp-locale").value = geo.locale || "";
  if (geo.locale && $("#fp-locale").value !== geo.locale) addTempOption($("#fp-locale"), geo.locale);
  toast(`已回填：${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(" / ")}`);
});

/** 账号指纹表单读取：可见字段可清空，表单未表达的字段保留在 fpBase 中。 */
function readFpForm() {
  const v = (id) => $(id).value.trim();
  const fp = { ...(state.fpBase || {}) };
  const setOrDelete = (key, value) => {
    if (value === "" || value == null) delete fp[key];
    else fp[key] = value;
  };
  setOrDelete("seed", v("#fp-seed") ? +v("#fp-seed") : "");
  setOrDelete("platform", v("#fp-platform"));
  setOrDelete("brand", v("#fp-brand"));
  if (v("#fp-screen")) {
    const [w, h] = v("#fp-screen").split("x").map(Number);
    if (w && h) {
      fp.screen_width = w;
      fp.screen_height = h;
    } else {
      delete fp.screen_width;
      delete fp.screen_height;
    }
  } else {
    delete fp.screen_width;
    delete fp.screen_height;
  }
  setOrDelete("timezone", v("#fp-tz"));
  setOrDelete("locale", v("#fp-locale"));
  setOrDelete("hardware_concurrency", v("#fp-cores") ? +v("#fp-cores") : "");
  setOrDelete("device_memory", v("#fp-mem") ? +v("#fp-mem") : "");
  setOrDelete("gpu_renderer", v("#fp-gpu"));
  return fp;
}

/* 账号指纹平台切换 -> 级联刷新 GPU / 分辨率 / CPU 候选 */
$("#fp-platform").addEventListener("change", () => {
  refreshFpDependentSelects("#fp", $("#fp-platform").value);
});

function parseBulkAccounts(text) {
  const rows = [];
  const errors = [];
  const emails = new Set();
  let duplicates = 0;
  text.split(/\r?\n/).forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) return;
    const parts = line.split("|").map((v) => v.trim());
    if (parts.length < 2 || parts.length > 3 || !parts[0] || !parts[1]) {
      errors.push(`第 ${index + 1} 行格式应为：邮箱|密码|2FA密钥`);
      return;
    }
    const email = parts[0].toLowerCase();
    if (emails.has(email)) {
      duplicates += 1;
      return;
    }
    emails.add(email);
    rows.push({ username: parts[0], password: parts[1], totp_secret: parts[2] || "" });
  });
  return { rows, errors, duplicates };
}

$("#form-account").addEventListener("submit", async (e) => {
  e.preventDefault();
  const shared = {
    group_id: state.currentGroup,
    browser_mode: $("#a-browser_mode").value,
    fingerprint: readFpForm(),
    enabled: $("#a-enabled").value === "1",
    remark: $("#a-remark").value.trim(),
    proxy_id: state.editingAccount?.proxy_id || null,
  };

  if (!state.editingAccount && state.accountModalMode === "bulk") {
    const { rows, errors, duplicates } = parseBulkAccounts($("#a-bulk").value);
    if (errors.length) return toast(errors[0], true);
    if (!rows.length) return toast("请至少输入一个账号", true);

    const failures = [];
    let created = 0;
    let skipped = duplicates;
    for (const row of rows) {
      try {
        const result = await api("/api/accounts", {
          method: "POST",
          body: { ...shared, ...row },
        });
        if (result.exists) skipped += 1;
        else created += 1;
      } catch (err) {
        failures.push(`${row.username}: ${err.message}`);
      }
    }
    await loadAccounts(state.currentGroup);
    await loadGroups();
    if (failures.length) {
      toast(`已添加 ${created} 个，跳过 ${skipped} 个，失败 ${failures.length} 个；${failures[0]}`, true);
    } else {
      $("#dlg-account").close();
      toast(created
        ? (skipped ? `已添加 ${created} 个账号，跳过 ${skipped} 个已存在账号` : `已添加 ${created} 个账号`)
        : `所选账号均已存在，已跳过 ${skipped} 个`);
    }
    return;
  }

  const body = {
    ...shared,
    username: $("#a-username").value.trim(),
    password: $("#a-password").value || (state.editingAccount ? "__KEEP_OLD__" : ""),
    totp_secret: $("#a-totp").value.trim() || (state.editingAccount ? "__CLEAR__" : ""),
  };
  if (!body.password) { toast("密码不能为空", true); return; }
  // 账号指纹任一字段变化时二次确认（新建无原值，不弹）
  if (state.editingAccount) {
    const oldFp = safeJson(state.editingAccount.fingerprint, {});
    const ok = await confirmFpChange(oldFp, body.fingerprint, `账号 ${state.editingAccount.username} 的指纹`);
    if (!ok) return;
  }
  try {
    let result;
    if (state.editingAccount) result = await api(`/api/accounts/${state.editingAccount.id}`, { method: "PUT", body });
    else result = await api("/api/accounts", { method: "POST", body });
    $("#dlg-account").close();
    toast(!state.editingAccount && result.exists ? "账号已存在，已跳过" : "账号已保存");
    await loadAccounts(state.currentGroup);
    await loadGroups();
  } catch (err) { toast(err.message, true); }
});

/** 前端随机指纹：候选全部来自 fp_options（/api/meta 下发），与后端 generate_fingerprint 同源自洽。
 *  gpu_vendor 不生成 —— CloakBrowser 按渲染器自动推断，显式填写反而可能不一致。 */
function randomFp() {
  const opt = fpOptions();
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const platform = pick(opt.platforms);
  const gpu = pick(opt.gpus[platform] || []);
  const screen = pick(opt.screens[platform] || []);
  return {
    seed: Math.floor(Math.random() * 1e9),
    platform,
    brand: pick(opt.brands),
    brand_version: pick(opt.brand_versions || []),
    gpu_renderer: gpu.renderer,
    screen_width: screen.width,
    screen_height: screen.height,
    timezone: pick(opt.timezones),
    locale: pick(opt.locales),
    hardware_concurrency: pick(opt.cores[platform] || []),
    device_memory: pick(opt.memory),
    webrtc_ip: "auto",
    noise: true,
    geoip: true,
  };
}

/* ==========================================================================
   任务日志
   ========================================================================== */

$("#btn-refresh-tasks").addEventListener("click", loadTasks);

$("#task-filter").addEventListener("click", (e) => {
  const b = e.target.closest(".segmented-item");
  if (!b) return;
  state.taskFilter = b.dataset.status || "";
  $$("#task-filter .segmented-item").forEach((x) => x.classList.toggle("is-active", x === b));
  loadTasks();
});

async function loadTasks() {
  let all = [];
  try {
    const d = await api("/api/tasks?limit=100");
    all = d.tasks || [];
  } catch (e) { toast(e.message, true); return; }

  renderTaskMetrics(all);

  const list = state.taskFilter ? all.filter((t) => t.status === state.taskFilter) : all;
  const tb = $("#tasks-table tbody");
  tb.innerHTML = "";
  list.forEach((t) => tb.appendChild(taskRow(t)));
  if (!list.length) {
    tb.innerHTML = `<tr><td colspan="6"><span class="empty-state">${state.taskFilter ? "该状态下暂无任务记录。" : "暂无任务记录。"}</span></td></tr>`;
  }
}

/** 指标条始终基于最近 100 条全量任务，不受筛选影响，避免「总任务」随筛选跳动 */
function renderTaskMetrics(tasks) {
  const n = (s) => tasks.filter((t) => t.status === s).length;
  $("#t-total").textContent = tasks.length;
  $("#t-success").textContent = n("success");
  $("#t-failed").textContent = n("failed") + n("callback_failed");
  $("#t-running").textContent =
    n("queued") + n("running") + n("token_queued") + n("token_running") + n("pending");
}

function taskRow(t) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><span class="cell-mono">#${t.id}</span></td>
    <td>
      <span class="cell-stack">
        <span>${esc(t.group_name || `分组 ${t.group_id}`)}</span>
        <span class="cell-sub">${esc(t.username || `账号 ${t.account_id}`)}</span>
      </span>
    </td>
    <td>${taskStatusChip(t)}</td>
    <td>${callbackChip(t.callback_status)}</td>
    <td><span class="cell-muted">${esc(fmtTime(t.created_at))}</span></td>
    <td><span class="cell-actions"><button class="link-btn" type="button" data-act="detail">详情</button></span></td>`;
  /* 列表行已携带 group_name / username，带入详情对话框以弥补 /api/tasks/{id} 的字段缺失 */
  tr.addEventListener("click", (e) => {
    if (e.target.closest('[data-act="detail"]')) showTaskApi(t.id, t);
  });
  return tr;
}

function openTaskDialog(title, sub) {
  $("#dlg-task-title").textContent = title;
  $("#dlg-task-sub").textContent = sub || "";
  $("#dlg-task").showModal();
}

function detailItem(key, val, mono = false) {
  const v = val == null || val === "" ? "—" : val;
  return `<div class="detail-item"><span class="detail-key">${esc(key)}</span><span class="detail-val${mono ? " mono" : ""}">${esc(v)}</span></div>`;
}

function detailBlock(title, content) {
  return `<div class="detail-block"><span class="detail-block-title">${esc(title)}</span><pre class="code-block">${esc(content)}</pre></div>`;
}

/* 后端 scheduler 写入的步骤结构：{t, step, detail, ok} */
const STEP_LABEL = {
  task_created: "任务入队",
  token_refresh_started: "开始刷新Token",
  upstream_refresh: "调用上游刷新接口",
  token_refresh_result: "刷新Token结果",
  browser_mode: "解析浏览器模式",
  fingerprint: "应用浏览器指纹",
  browser_launched: "启动浏览器",
  browser_closed: "关闭浏览器",
  finished: "执行结束",
};

function stepItem(s, i) {
  let name = "步骤", detail = "", time = "", ok = true;
  if (typeof s === "string") {
    name = s;
  } else if (s && typeof s === "object") {
    name = s.step || s.name || s.text || "步骤";
    detail = s.detail ?? s.message ?? "";
    time = s.t || s.time || s.ts || s.at || "";
    ok = s.ok !== false;
  }
  const label = STEP_LABEL[name] || name;
  const text = detail && detail !== "-" ? `${label} · ${detail}` : label;
  return `<li class="step-item${ok ? "" : " is-error"}"><span class="step-index">${i + 1}</span><span class="step-text">${esc(text)}</span>${time ? `<span class="step-time">${esc(fmtTime(time))}</span>` : ""}</li>`;
}

/**
 * 任务详情。ctx 由调用方带入列表行信息：
 * GET /api/tasks/{id} 只返回 tasks 表原始行，不含 group_name / username。
 */
async function showTaskApi(id, ctx = {}) {
  let t;
  try { t = await api(`/api/tasks/${id}`); } catch (e) { return toast(e.message, true); }

  const steps = safeJson(t.steps, []);
  const result = safeJson(t.result_json, null);

  const parts = [
    `<div class="detail-grid">
      ${detailItem("任务编号", `#${t.id}`, true)}
      <div class="detail-item"><span class="detail-key">状态</span><span class="detail-val">${taskStatusChip(t)}</span></div>
      ${detailItem("浏览器模式", modeText(t.browser_mode))}
      ${detailItem("回调状态", CALLBACK_MAP[t.callback_status]?.label || t.callback_status || "—")}
      ${detailItem("开始时间", fmtTime(t.started_at))}
      ${detailItem("结束时间", fmtTime(t.finished_at))}
    </div>`,
  ];
  if (t.error) parts.push(detailBlock("错误信息", t.error));
  if (Array.isArray(steps) && steps.length) {
    parts.push(`<div class="detail-block"><span class="detail-block-title">执行步骤</span><ol class="step-list">${steps.map(stepItem).join("")}</ol></div>`);
  }
  if (!isEmpty(result)) parts.push(detailBlock("执行结果", JSON.stringify(result, null, 2)));
  if (t.callback_response) parts.push(detailBlock("上游回调响应", t.callback_response));

  $("#dlg-task-body").innerHTML = parts.join("");
  openTaskDialog(
    `任务 #${t.id} 详情`,
    `${ctx.group_name || "—"} · ${ctx.username || "—"} · ${fmtTime(ctx.created_at || t.created_at)}`
  );
}

async function showAccountTasks(a) {
  let tasks = [];
  try {
    const d = await api(`/api/accounts/${a.id}/tasks`);
    tasks = d.tasks || [];
  } catch (e) { return toast(e.message, true); }

  const body = $("#dlg-task-body");
  if (!tasks.length) {
    body.innerHTML = '<p class="empty-state">该账号暂无任务记录。</p>';
  } else {
    body.innerHTML = `<div class="hist-list">${tasks.map((t) => `
      <button class="hist-row" type="button" data-task="${t.id}">
        ${statusChip(t.status)}
        <span>任务 #${t.id}</span>
        <span class="hist-time">${esc(fmtTime(t.created_at))}</span>
      </button>`).join("")}</div>`;
    body.querySelectorAll("[data-task]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const t = tasks.find((x) => String(x.id) === String(btn.dataset.task));
        const g = state.groups.find((x) => String(x.id) === String(t?.group_id));
        showTaskApi(btn.dataset.task, {
          username: a.username,
          group_name: g ? g.name : "",
          created_at: t?.created_at,
        });
      }));
  }
  openTaskDialog(`账号 ${a.username} 的最近任务`, `${tasks.length} 条记录 · 点击任意条目查看完整详情`);
}

/* ==========================================================================
   代理管理
   ========================================================================== */

/* proxies 表格列（index.html）：名称 | 地址 | 出口IP | 耗时 | 关联账号 | 测试时间 | 操作 */

function latencyText(v) {
  if (v == null || v === "") return "—";
  return `${v} ms`;
}

function proxyRow(p) {
  const tr = document.createElement("tr");
  tr.dataset.id = p.id;
  tr.dataset.name = (p.name || "").toLowerCase();
  const testing = p.testing === true || (p.check_error || "") === "检测中";
  const failed = !testing && (p.check_error || "").trim() !== "";
  const exitCell = testing
    ? '<span class="chip chip-info"><span class="chip-dot"></span>检测中</span>'
    : failed
      ? `<span class="cell-danger" title="${esc(p.check_error)}">失败</span>`
      : `<span class="cell-mono">${esc(p.exit_ip || "—")}</span>`;
  const latencyCell = testing
    ? '<span class="cell-muted">…</span>'
    : failed
      ? '<span class="cell-muted">—</span>'
      : `<span class="latency-ok">${esc(latencyText(p.latency_ms))}</span>`;
  tr.innerHTML = `
    <td><span class="cell-strong">${esc(p.name)}</span></td>
    <td>
      <span class="cell-stack">
        <span class="cell-mono">${esc(p.server_masked || "—")}</span>
        ${p.custom_geo ? `<span class="cell-sub">${esc([p.country, p.region, p.city, p.timezone].filter(Boolean).join(" · "))}</span>` : ""}
      </span>
    </td>
    <td>${exitCell}</td>
    <td>${latencyCell}</td>
    <td><span class="cell-muted">${p.linked_accounts || 0}</span></td>
    <td><span class="cell-muted">${esc(testing ? "" : fmtTime(p.check_at))}</span></td>
    <td>
      <span class="cell-actions">
        <button class="icon-btn" type="button" data-act="test" title="测试连接" aria-label="测试连接" ${testing ? "disabled" : ""}>
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2 6.4a8.5 8.5 0 0 1 12 0M4.4 8.9a5.2 5.2 0 0 1 7.2 0M6.8 11.4a1.9 1.9 0 0 1 2.4 0" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="8" cy="13.4" r="0.9" fill="currentColor"/></svg>
        </button>
        <button class="icon-btn" type="button" data-act="edit" title="编辑" aria-label="编辑">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M11.3 2.2l2.5 2.5-8.1 8.1-3.2.7.7-3.2 8.1-8.1z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>
        </button>
        <button class="icon-btn is-danger" type="button" data-act="del" title="删除" aria-label="删除">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M2.5 4h11M6.5 4V2.8h3V4M4 4l.6 9.2a1 1 0 0 0 1 .9h4.8a1 1 0 0 0 1-.9L12 4M6.6 7v4.4M9.4 7v4.4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      </span>
    </td>`;

  tr.addEventListener("click", async (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "test") return proxyTest(p);
    if (act === "edit") return openProxyModal(p);
    if (act === "del") {
      const ok = await confirmDialog({
        title: `删除代理「${p.name}」`,
        message: `该代理与 ${p.linked_accounts || 0} 个账号的关联配置将被删除，此操作不可撤销。`,
        okText: "删除代理",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/api/proxies/${p.id}`, { method: "DELETE" });
        toast("代理已删除");
        await loadProxies();
      } catch (err) { toast(err.message, true); }
    }
  });
  return tr;
}

async function loadProxies() {
  let list = [];
  try {
    const d = await api("/api/proxies");
    list = d.proxies || [];
  } catch (e) { return toast(e.message, true); }
  state.proxies = list;

  const kw = ($("#proxy-search").value || "").trim().toLowerCase();
  const rows = kw ? list.filter((p) => (p.name || "").toLowerCase().includes(kw)) : list;
  const tb = $("#proxies-table tbody");
  tb.innerHTML = "";
  rows.forEach((p) => tb.appendChild(proxyRow(p)));
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="7"><span class="empty-state">${kw ? "没有匹配的代理。" : "暂无代理，点击右上角「新增代理」创建。"}</span></td></tr>`;
  }
  $("#proxy-count").textContent = `${list.length} 个代理`;
}

$("#proxy-search").addEventListener("input", () => loadProxies());
$("#btn-new-proxy").addEventListener("click", () => openProxyModal());

/* ---------- 编辑代理弹窗 ---------- */

function openProxyModal(p = null) {
  state.editingProxy = p;
  state.proxyGeoPrefilled = false;   // geo fields not yet backfilled this session
  $("#dlg-proxy-title").textContent = p ? `编辑代理` : "新增代理";
  $("#px-name").value = p?.name || "";
  // 编辑时地址留空表示保留原值；新建必须填写
  $("#px-server").value = "";
  $("#px-server").type = "password";
  syncProxyEye(false);
  $("#px-country").value = p?.country || "";
  $("#px-region").value = p?.region || "";
  $("#px-city").value = p?.city || "";
  $("#px-timezone").value = p?.timezone || "";
  $("#px-locale").value = p?.locale || "";
  // 已有的 geo 值视为已回填过（编辑场景不覆盖用户数据）
  state.proxyGeoPrefilled = !!(p?.country || p?.timezone);
  $("#px-geo-source").textContent = state.proxyGeoPrefilled
    ? "使用该代理已保存的位置，可手动修改或按出口 IP 解析"
    : "打开「自定义时区位置」后将预填系统默认值";
  syncGeoFields();
  $("#dlg-proxy").showModal();
}

function syncGeoFields() {
  const on = $("#px-custom_geo").checked;
  $("#px-geo-fields").classList.toggle("hidden", !on);
  // 打开自定义时区且尚无值：预填系统设置里的全局默认时区位置
  if (on && !state.proxyGeoPrefilled) {
    const noValue = !["#px-country", "#px-region", "#px-city", "#px-timezone"]
      .some((id) => $(id).value.trim());
    if (noValue && state.defaultGeo) {
      $("#px-country").value = state.defaultGeo.country || "";
      $("#px-region").value = state.defaultGeo.region || "";
      $("#px-city").value = state.defaultGeo.city || "";
      $("#px-timezone").value = state.defaultGeo.timezone || "";
      $("#px-locale").value = state.defaultGeo.locale || "";
      $("#px-geo-source").textContent = "已预填系统默认值，可手动修改或按出口 IP 解析";
    }    state.proxyGeoPrefilled = true;
  }
}

$("#px-custom_geo").addEventListener("change", syncGeoFields);

function syncProxyEye(visible) {
  $("#px-server").type = visible ? "text" : "password";
  document.querySelector("#px-server-eye .eye-show").classList.toggle("hidden", visible);
  document.querySelector("#px-server-eye .eye-hide").classList.toggle("hidden", !visible);
}

$("#px-server-eye").addEventListener("click", () => {
  syncProxyEye($("#px-server").type === "password");
});

/* 按该代理已测得的出口 IP（无则现测一次）解析 geo 并回填表单 */
$("#btn-px-geo-auto").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  const src = $("#px-geo-source");
  const old = src.textContent;
  src.textContent = "正在解析出口 IP…";
  try {
    let ip = state.editingProxy?.exit_ip || "";
    if (!ip) {
      // 该代理还没测过：先落库再测一次拿出口 IP
      const name = $("#px-name").value.trim();
      const server = $("#px-server").value.trim();
      if (!name) { src.textContent = old; return toast("请先填写代理名称", true); }
      if (!state.editingProxy && !server) { src.textContent = old; return toast("请先填写代理地址", true); }
      let pid = state.editingProxy?.id;
      if (pid) {
        await api(`/api/proxies/${pid}`, { method: "PUT", body: proxyFormBody(server) });
      } else {
        const d = await api("/api/proxies", { method: "POST", body: proxyFormBody(server) });
        pid = d.id;
        state.editingProxy = { id: pid };
        $("#dlg-proxy-title").textContent = "编辑代理";
      }
      src.textContent = "正在通过代理测试获取出口 IP…";
      await api(`/api/proxies/${pid}/test`, { method: "POST" });
      ip = await pollProxyExitIp(pid, 20);
      if (!ip) { src.textContent = old; return toast("未能获取出口 IP（代理连接失败？）", true); }
    }
    const g = await api(`/api/geo/lookup?ip=${encodeURIComponent(ip)}`);
    if (!g.ok) { src.textContent = old; return toast(g.error || "解析失败", true); }
    $("#px-country").value = g.country || "";
    $("#px-region").value = g.region || "";
    $("#px-city").value = g.city || "";
    $("#px-timezone").value = g.timezone || "";
    $("#px-locale").value = g.locale || "";
    src.textContent = `已按出口 IP ${g.ip} 解析回填，可继续手动修改`;
    toast(`已解析：${[g.country, g.city, g.timezone, g.locale].filter(Boolean).join(" / ") || "无结果"}`);
  } catch (err) { src.textContent = old; toast(err.message, true); }
  finally { btn.disabled = false; }
});

/* 测试连接：编辑中先落库再测，保证测的是保存后的地址 */
$("#btn-proxy-test").addEventListener("click", async () => {
  const name = $("#px-name").value.trim();
  const server = $("#px-server").value.trim();
  if (!name) return toast("请先填写代理名称", true);
  if (!state.editingProxy && !server) return toast("请先填写代理地址", true);
  try {
    let pid = state.editingProxy?.id;
    if (pid) {
      await api(`/api/proxies/${pid}`, { method: "PUT", body: proxyFormBody(server) });
    } else {
      const d = await api("/api/proxies", { method: "POST", body: proxyFormBody(server) });
      pid = d.id;
      state.editingProxy = { id: pid };
      $("#dlg-proxy-title").textContent = "编辑代理";
    }
    await api(`/api/proxies/${pid}/test`, { method: "POST" });
    $("#dlg-proxy").close();
    toast("测试连接已发起");
    await loadProxies();
    pollProxyTest(pid, 0, Date.now());
  } catch (e) { toast(e.message, true); }
});

function proxyFormBody(serverOverride) {
  return {
    name: $("#px-name").value.trim(),
    server: (serverOverride ?? $("#px-server").value).trim(),
    custom_geo: $("#px-custom_geo").checked,
    country: $("#px-country").value.trim(),
    region: $("#px-region").value.trim(),
    city: $("#px-city").value.trim(),
    timezone: $("#px-timezone").value.trim(),
    locale: $("#px-locale").value.trim(),
  };
}

$("#form-proxy").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    if (state.editingProxy?.id) {
      await api(`/api/proxies/${state.editingProxy.id}`, { method: "PUT", body: proxyFormBody() });
      toast("代理已保存");
    } else {
      await api("/api/proxies", { method: "POST", body: proxyFormBody() });
      toast("代理已创建");
    }
    $("#dlg-proxy").close();
    await loadProxies();
  } catch (err) { toast(err.message, true); }
});

/* ---------- 测试连接轮询 ---------- */

/** 列表「测试连接」按钮：发起后台探测，行内立即显示检测中，轮询结果后提示 */
async function proxyTest(p) {
  if ((p.check_error || "") === "检测中" || p.testing === true) return;
  try {
    await api(`/api/proxies/${p.id}/test`, { method: "POST" });
    p.check_error = "检测中";          // 本地先行置检测中，行内立刻有反馈
    p.testing = true;
    p._testStartedAt = Date.now();     // 轮询只认这次发起之后的新结果
    renderProxyRows();
    pollProxyTest(p.id, 0, p._testStartedAt);
  } catch (e) { toast(e.message, true); }
}

/** 轮询拿代理的出口 IP；拿到立即返回，超时返回空串 */
function pollProxyExitIp(pid, maxTries) {
  return new Promise((resolve) => {
    let tried = 0;
    const tick = async () => {
      tried += 1;
      if (tried > maxTries) return resolve("");
      try {
        const d = await api("/api/proxies");
        state.proxies = d.proxies || [];
        const p = state.proxies.find((x) => String(x.id) === String(pid));
        if (p && p.exit_ip) return resolve(p.exit_ip);
        if (p && (p.check_error || "").trim() && (p.check_error || "").trim() !== "检测中") {
          return resolve("");
        }
      } catch (_) { /* 网络抖动继续 */ }
      setTimeout(tick, 2000);
    };
    setTimeout(tick, 2000);
  });
}

function pollProxyTest(pid, tried, startedAt = 0) {
  if (tried >= 40) return;               // ~2 分钟后放弃轮询
  setTimeout(async () => {
    try {
      const d = await api("/api/proxies");
      state.proxies = d.proxies || [];
      const p = state.proxies.find((x) => String(x.id) === String(pid));
      if (p) {
        renderProxyRows();
        // check_at 是这次探测之后落的新结果才作数，否则是发起前的旧数据
        const at = p.check_at ? new Date(String(p.check_at).replace(" ", "T")).getTime() : 0;
        const fresh = !startedAt || at > startedAt - 2000;
        if (fresh && (p.check_error || "").trim()) {
          toast(`测试失败：${p.check_error}`, true);
          return;
        }
        if (fresh && p.exit_ip) {
          toast(`测试通过：出口 ${p.exit_ip} · ${p.latency_ms} ms`);
          return;
        }
        return pollProxyTest(pid, tried + 1, startedAt);
      }
      renderProxyRows();
    } catch (_) { /* 网络抖动继续 */ }
  }, 3000);
}

/** 仅重绘表格行（不重新拉接口），保持轮询轻量 */
function renderProxyRows() {
  const kw = ($("#proxy-search").value || "").trim().toLowerCase();
  const rows = kw ? state.proxies.filter((p) => (p.name || "").toLowerCase().includes(kw)) : state.proxies;
  const tb = $("#proxies-table tbody");
  tb.innerHTML = "";
  rows.forEach((p) => tb.appendChild(proxyRow(p)));
  $("#proxy-count").textContent = `${state.proxies.length} 个代理`;
}

/* ==========================================================================
   系统设置
   ========================================================================== */

function applyEngine(e) {
  if (!e) return;
  const degraded = e.cloak_available === false;
  $("#engine-badge").textContent = degraded ? `${engineLabel(e.engine)} · 降级` : engineLabel(e.engine);
  const dot = $("#engine-dot");
  dot.classList.toggle("is-off", degraded);
  dot.title = degraded ? "CloakBrowser 不可用，已降级运行" : "指纹引擎正常";
}

/** 左侧导航的引擎状态卡片 —— 启动即展示，不依赖设置页 */
async function loadEngine() {
  try {
    const s = await api("/api/settings");
    applyEngine(s.engine);
    applyOpenBrowserVisibility(s.cloak_cdp_url);
    // 回填时区入口不依赖用户是否打开过系统设置页，启动时同步缓存全局默认位置。
    state.defaultGeo = {
      country: s.default_geo_country || "",
      region: s.default_geo_region || "",
      city: s.default_geo_city || "",
      timezone: s.default_geo_timezone || "",
      locale: s.default_geo_locale || "",
    };
  } catch (_) { /* 引擎信息非关键路径 */ }
}

async function loadSettings() {
  let s;
  try { s = await api("/api/settings"); } catch (e) { return toast(e.message, true); }

  applyEngine(s.engine);
  applyOpenBrowserVisibility(s.cloak_cdp_url);

  const mode = s.global_browser_mode || "headless";
  $$("#browser-mode-seg .segmented-item").forEach((b) => b.classList.toggle("is-active", b.dataset.mode === mode));

  $("#cloak-cdp").value = s.cloak_cdp_url || "";

  $("#log-retention").value = s.log_retention_days ?? 3;
  $("#token-refresh-interval").value = s.token_refresh_interval_seconds ?? 3600;
  $("#fp-check-url").value = s.fp_check_url || "";
  $("#geo-country").value = s.default_geo_country || "";
  $("#geo-region").value = s.default_geo_region || "";
  $("#geo-city").value = s.default_geo_city || "";
  $("#geo-timezone").value = s.default_geo_timezone || "";
  $("#geo-locale").value = s.default_geo_locale || "";
  state.defaultGeo = {
    country: s.default_geo_country || "",
    region: s.default_geo_region || "",
    city: s.default_geo_city || "",
    timezone: s.default_geo_timezone || "",
    locale: s.default_geo_locale || "",
  };

  const e = s.engine || {};
  $("#engine-name").textContent = engineLabel(e.engine);
  $("#engine-cloak").textContent = e.cloak_available ? "可用" : "不可用";
  $("#engine-version").textContent = e.cdp_version
    ? `${e.cloak_version || "—"}（CDP ${e.cdp_version}）`
    : (e.cloak_version || "—");
  $("#engine-key").textContent = { env: "已配置（.env）", file: "已配置（license.key）", none: "未配置" }[e.license_key_source] || "未知";
  $("#engine-python").textContent = e.python || "—";
}

$("#browser-mode-seg").addEventListener("click", (e) => {
  const b = e.target.closest(".segmented-item");
  if (!b) return;
  $$("#browser-mode-seg .segmented-item").forEach((x) => x.classList.toggle("is-active", x === b));
});

$("#btn-save-gbm").addEventListener("click", async () => {
  const b = $("#browser-mode-seg .segmented-item.is-active");
  if (!b) return toast("请选择浏览器模式", true);
  try {
    await api("/api/settings", { method: "PUT", body: { global_browser_mode: b.dataset.mode } });
    toast("浏览器模式已保存");
  } catch (e) { toast(e.message, true); }
});

$("#btn-save-cdp").addEventListener("click", async () => {
  try {
    await api("/api/settings", { method: "PUT", body: { cloak_cdp_url: $("#cloak-cdp").value.trim() } });
    toast("CDP 地址已保存");
    applyOpenBrowserVisibility($("#cloak-cdp").value);   // 立即生效，不等刷新
    await loadSettings();
  } catch (e) { toast(e.message, true); }
});

$("#btn-save-retention").addEventListener("click", async () => {
  const days = +$("#log-retention").value;
  if (!days || days < 1 || days > 365) return toast("保留天数需在 1–365 之间", true);
  try {
    await api("/api/settings", { method: "PUT", body: { log_retention_days: days } });
    toast(`日志保留期已设为 ${days} 天`);
  } catch (e) { toast(e.message, true); }
});

$("#btn-prune-now").addEventListener("click", async () => {
  try {
    const r = await api("/api/logs/prune", { method: "POST" });
    toast(`已清理：适配器日志 ${r.adapter_logs_deleted} 条 · 任务日志 ${r.tasks_deleted} 条`);
  } catch (e) { toast(e.message, true); }
});

$("#btn-save-token-refresh").addEventListener("click", async () => {
  const seconds = +$("#token-refresh-interval").value;
  if (!seconds || seconds < 60 || seconds > 2592000) {
    return toast("刷新间隔需在 60–2592000 秒之间", true);
  }
  try {
    await api("/api/settings", {
      method: "PUT",
      body: { token_refresh_interval_seconds: seconds },
    });
    toast(`Token 自动刷新间隔已设为 ${seconds} 秒`);
  } catch (e) { toast(e.message, true); }
});

$("#btn-save-fpcheck").addEventListener("click", async () => {
  try {
    await api("/api/settings", { method: "PUT", body: { fp_check_url: $("#fp-check-url").value.trim() } });
    toast("检测站点地址已保存");
  } catch (e) { toast(e.message, true); }
});

/* ---------- 全局默认时区位置 ---------- */

function geoFormBody() {
  return {
    default_geo_country: $("#geo-country").value.trim(),
    default_geo_region: $("#geo-region").value.trim(),
    default_geo_city: $("#geo-city").value.trim(),
    default_geo_timezone: $("#geo-timezone").value.trim(),
    default_geo_locale: $("#geo-locale").value.trim(),
  };
}

function fillGeoForm(geo, { quiet = false } = {}) {
  $("#geo-country").value = geo.country || "";
  $("#geo-region").value = geo.region || "";
  $("#geo-city").value = geo.city || "";
  $("#geo-timezone").value = geo.timezone || "";
  $("#geo-locale").value = geo.locale || "";
  if (!quiet) toast(`已解析：${geo.ip} → ${[geo.country, geo.city, geo.timezone, geo.locale].filter(Boolean).join(" / ") || "无结果"}`);
}

$("#btn-save-geo").addEventListener("click", async () => {
  try {
    const body = geoFormBody();
    await api("/api/settings", { method: "PUT", body });
    state.defaultGeo = { ...state.defaultGeo, ...body };
    toast("默认时区位置已保存");
  } catch (e) { toast(e.message, true); }
});

$("#btn-geo-auto").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  try {
    const g = await api("/api/geo/lookup");
    if (!g.ok) return toast(g.error || "解析失败", true);
    fillGeoForm(g);
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; }
});

$("#btn-save-pwd").addEventListener("click", async () => {
  try {
    await api("/api/auth/change-password", {
      method: "POST",
      body: { old_password: $("#pwd-old").value, new_password: $("#pwd-new").value },
    });
    $("#pwd-old").value = "";
    $("#pwd-new").value = "";
    toast("密码已修改");
  } catch (e) { toast(e.message, true); }
});

/* ==========================================================================
   登录 / 登出 / 启动
   ========================================================================== */

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#login-err");
  err.classList.add("hidden");
  try {
    const d = await api("/api/auth/login", {
      method: "POST",
      body: { username: $("#login-user").value, password: $("#login-pass").value },
    });
    TOKEN = d.token;
    $("#login-pass").value = "";
    showMain();
  } catch (e2) {
    err.textContent = e2.message;
    err.classList.remove("hidden");
  }
});

$("#logout-btn").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) {}
  TOKEN = "";
  showLogin();
});

(async function boot() {
  applyTheme(document.documentElement.getAttribute("data-theme") || "light", false);
  // 登录态保存在 HttpOnly Cookie；刷新后内存 TOKEN 丢失也必须先用 Cookie 恢复。
  try {
    await api("/api/auth/me");
    showMain();
  } catch (_) { /* api() 已切回登录视图 */ }
})();
