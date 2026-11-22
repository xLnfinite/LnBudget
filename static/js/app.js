"use strict";

/* ================= 工具函数 ================= */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(n) || 0);
const dtFmt = (s) => (s || "").replace("T", " ").slice(0, 16);
const dtInput = (s) => (s || "").replace(" ", "T").slice(0, 16);
const icon = (id) => `<svg class="ic"><use href="#${id}"/></svg>`;
const ymNow = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };
const ymShift = (ym, delta) => { const [y, m] = ym.split("-").map(Number); const t = new Date(y, m - 1 + delta, 1); return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`; };
const ymLastDay = (ym) => { const [y, m] = ym.split("-").map(Number); return `${ym}-${String(new Date(y, m, 0).getDate()).padStart(2, "0")}`; };
const nowLocal = () => { const d = new Date(); const p = (x) => String(x).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

/* ================= API ================= */
async function api(method, path, body) {
  const opts = { method, headers: { "X-Requested-With": "XMLHttpRequest" } };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); } catch { throw new Error("网络连接失败，请检查服务是否在运行"); }
  if (res.status === 401 && state.inApp) { showLogin(); throw new Error("登录已过期，请重新登录"); }
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!data || data.ok !== true) throw new Error((data && data.error) || `请求失败（${res.status}）`);
  return data.data;
}
const GET = (p) => api("GET", p);
const POST = (p, b) => api("POST", p, b || {});
const PUT = (p, b) => api("PUT", p, b);
const DEL = (p) => api("DELETE", p);

/* ================= 全局状态 ================= */
const state = {
  inApp: false,
  user: null,
  page: "dashboard",
  categories: [],
  recMap: new Map(),
  rec: { month: ymNow(), type: "", category: "", q: "", page: 1, size: 20, total: 0, pages: 1 },
  logs: { page: 1, size: 20, total: 0, pages: 1 },
  dashMonth: ymNow(),
  anMonth: ymNow(),
  charts: [],
};

/* ================= 提示 / 弹窗 ================= */
function toast(msg, type = "info", ms = 2600) {
  const root = $("#toastRoot");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `<span>${esc(msg)}</span>`;
  root.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 300); }, ms);
}

function openModal(html) {
  const root = $("#modalRoot");
  const wrap = document.createElement("div");
  wrap.className = "modal-overlay";
  wrap.innerHTML = `<div class="modal">${html}</div>`;
  root.appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add("show"));
  const close = () => { wrap.classList.remove("show"); setTimeout(() => wrap.remove(), 200); };
  wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) close(); });
  wrap.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  return { el: wrap, close };
}

function confirmDialog(title, text) {
  return new Promise((resolve) => {
    const m = openModal(`
      <div class="modal-head"><h3>${esc(title)}</h3><button class="icon-btn" data-close>${icon("i-x")}</button></div>
      <div class="modal-body"><p class="confirm-text">${esc(text)}</p></div>
      <div class="modal-foot">
        <button class="btn btn-ghost" id="cfCancel">取消</button>
        <button class="btn btn-danger" id="cfOk">确定</button>
      </div>`);
    m.el.querySelector("#cfCancel").addEventListener("click", () => { m.close(); resolve(false); });
    m.el.querySelector("#cfOk").addEventListener("click", () => { m.close(); resolve(true); });
  });
}

function animateNumber(el, target, withMoney = true) {
  const to = Number(target) || 0;
  const t0 = performance.now(), dur = 600;
  cancelAnimationFrame(el._raf);
  const step = (t) => {
    const p = Math.min((t - t0) / dur, 1);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = (withMoney ? "¥" : "") + money(to * eased);
    if (p < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}

/* ================= 账目行 ================= */
function recRow(rec) {
  const cls = rec.category_type === "income" ? "inc" : "exp";
  const sign = rec.category_type === "income" ? "+" : "-";
  return `<div class="rec-row">
    <span class="rec-time">${esc(dtFmt(rec.txn_time))}</span>
    <span class="rec-cat"><span class="cat-dot" style="background:${rec.category_color}22;color:${rec.category_color}">${esc(rec.category_icon)}</span>${esc(rec.category_name)}</span>
    <span class="rec-note" title="${esc(rec.note)}">${esc(rec.note) || "—"}</span>
    <span class="rec-amt ${cls}">${sign}¥${money(rec.amount)}</span>
    <span class="rec-ops">
      <button class="icon-btn" data-edit="${rec.id}" title="编辑">${icon("i-edit")}</button>
      <button class="icon-btn danger" data-del="${rec.id}" title="删除">${icon("i-trash")}</button>
    </span>
  </div>`;
}

async function deleteRecord(id) {
  const r = state.recMap.get(id);
  const detail = r ? `${esc(r.category_icon)} ${esc(r.category_name)} ¥${money(r.amount)}（${esc(dtFmt(r.txn_time))}）` : "";
  const ok = await confirmDialog("删除账目", `确定要永久删除这笔账目吗？${detail ? "<br><br>" + detail : ""}`);
  if (!ok) return;
  try {
    await DEL(`/api/records/${id}`);
    toast("账目已删除", "ok");
    state.recMap.delete(id);
    refreshCurrent();
  } catch (err) { toast(err.message, "err"); }
}

/* ================= 记一笔 / 编辑弹窗 ================= */
function recordModal(record = null) {
  const isEdit = !!record;
  const rec = record || { amount: "", note: "", txn_time: nowLocal(), category_type: "expense", category_id: "" };
  let selType = rec.category_type || "expense";
  const catOptions = (type) => state.categories.filter((c) => c.type === type)
    .map((c) => `<option value="${c.id}">${esc(c.icon)} ${esc(c.name)}</option>`).join("");

  const m = openModal(`
    <div class="modal-head"><h3>${isEdit ? "编辑账目" : "记一笔"}</h3><button class="icon-btn" data-close>${icon("i-x")}</button></div>
    <div class="modal-body">
      <div class="seg" id="rmType">
        <button data-t="expense" class="exp ${selType === "expense" ? "on" : ""}">支出</button>
        <button data-t="income" class="inc ${selType === "income" ? "on" : ""}">收入</button>
      </div>
      <label class="field"><span>金额（元）</span>
        <input type="number" id="rmAmount" step="0.01" min="0.01" placeholder="0.00" value="${rec.amount ?? ""}">
      </label>
      <label class="field"><span>分类</span>
        <select id="rmCat">${catOptions(selType)}</select>
      </label>
      <label class="field"><span>交易时间</span>
        <input type="datetime-local" id="rmTime" value="${esc(dtInput(rec.txn_time))}">
      </label>
      <label class="field"><span>备注（可选）</span>
        <input type="text" id="rmNote" maxlength="200" placeholder="例如：和同事吃午饭" value="${esc(rec.note || "")}">
      </label>
      <div class="form-error hidden" id="rmError"></div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn btn-primary" id="rmSave">${isEdit ? "保存修改" : "保存账目"}</button>
    </div>`);

  const seg = m.el.querySelector("#rmType");
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    selType = b.dataset.t;
    seg.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    const sel = m.el.querySelector("#rmCat");
    const prev = sel.value;
    sel.innerHTML = catOptions(selType);
    if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
  });

  m.el.querySelector("#rmAmount").focus();
  m.el.querySelector("#rmSave").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = "保存中…";
    const errEl = m.el.querySelector("#rmError");
    try {
      const payload = {
        amount: parseFloat(m.el.querySelector("#rmAmount").value),
        category_id: Number(m.el.querySelector("#rmCat").value),
        txn_time: m.el.querySelector("#rmTime").value,
        note: m.el.querySelector("#rmNote").value.trim(),
      };
      if (!payload.amount || payload.amount <= 0) throw new Error("请输入大于 0 的金额");
      if (!payload.category_id) throw new Error("该类型下还没有分类，请先到「账目分类」创建");
      if (!payload.txn_time) throw new Error("请选择交易时间");
      if (isEdit) await PUT(`/api/records/${rec.id}`, payload);
      else await POST("/api/records", payload);
      m.close();
      toast(isEdit ? "账目已更新 ✓" : "已记一笔 ✓", "ok");
      refreshCurrent();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    } finally {
      btn.disabled = false;
      btn.textContent = isEdit ? "保存修改" : "保存账目";
    }
  });
}
/* ================= 分类弹窗 ================= */
const CAT_EMOJIS_EXP = ["🍜", "🍔", "🍰", "🚌", "🚗", "🏠", "💡", "🛍️", "👗", "🎮", "🎬", "📚", "💊", "🏥", "📱", "✈️"];
const CAT_EMOJIS_INC = ["💼", "📈", "💰", "🎁", "🧧", "🏦", "💻", "🎨", "🛠️", "🧑‍🏫", "🏆", "🪙", "💎", "🧑‍💻", "📦", "🫰"];
const CAT_COLORS = ["#f97316", "#ef4444", "#ec4899", "#8b5cf6", "#4f7cff", "#0ea5e9", "#14b8a6", "#22c55e", "#84cc16", "#eab308", "#64748b", "#1f2937"];

function categoryModal(cat = null, ctype = "expense") {
  const isEdit = !!cat;
  const c = cat || { name: "", icon: ctype === "income" ? "💰" : "🍜", color: "#4f7cff", type: ctype };
  const cur = { type: c.type, icon: c.icon, color: c.color };
  const emojiList = (t) => (t === "income" ? CAT_EMOJIS_INC : CAT_EMOJIS_EXP);

  const m = openModal(`
    <div class="modal-head"><h3>${isEdit ? "编辑分类" : "新增分类"}</h3><button class="icon-btn" data-close>${icon("i-x")}</button></div>
    <div class="modal-body">
      <div class="seg" id="cmType">
        <button data-t="expense" class="exp ${c.type === "expense" ? "on" : ""}">支出</button>
        <button data-t="income" class="inc ${c.type === "income" ? "on" : ""}">收入</button>
      </div>
      <label class="field"><span>名称</span>
        <input type="text" id="cmName" maxlength="20" placeholder="例如：餐饮" value="${esc(c.name)}">
      </label>
      <div class="field"><span>图标</span>
        <div class="emoji-grid" id="cmEmojis"></div>
        <input type="text" id="cmIconCustom" maxlength="8" placeholder="或输入自定义 emoji" value="${esc(emojiList(cur.type).includes(cur.icon) ? "" : cur.icon)}">
      </div>
      <div class="field"><span>颜色</span>
        <div class="color-row" id="cmColors">
          ${CAT_COLORS.map((col) => `<button type="button" class="swatch ${col === cur.color ? "on" : ""}" style="--c:${col}" data-c="${col}"></button>`).join("")}
          <label class="swatch swatch-custom" title="自定义颜色"><input type="color" id="cmColorInput" value="${esc(cur.color)}"></label>
        </div>
      </div>
      <div class="form-error hidden" id="cmError"></div>
    </div>
    <div class="modal-foot">
      <button class="btn btn-ghost" data-close>取消</button>
      <button class="btn btn-primary" id="cmSave">${isEdit ? "保存修改" : "创建分类"}</button>
    </div>`);

  const emoWrap = m.el.querySelector("#cmEmojis");
  const customInput = m.el.querySelector("#cmIconCustom");
  const colorInput = m.el.querySelector("#cmColorInput");
  const colorRow = m.el.querySelector("#cmColors");
  const syncSwatches = () => colorRow.querySelectorAll(".swatch[data-c]").forEach((s) => s.classList.toggle("on", s.dataset.c === cur.color));

  function renderEmojis() {
    emoWrap.innerHTML = emojiList(cur.type)
      .map((e) => `<button type="button" class="${e === cur.icon ? "on" : ""}" data-e="${e}">${e}</button>`).join("");
  }
  renderEmojis();

  m.el.querySelector("#cmType").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    cur.type = b.dataset.t;
    m.el.querySelectorAll("#cmType button").forEach((x) => x.classList.toggle("on", x === b));
    renderEmojis();
  });
  emoWrap.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    cur.icon = b.dataset.e;
    customInput.value = "";
    emoWrap.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
  });
  customInput.addEventListener("input", () => {
    cur.icon = customInput.value.trim();
    emoWrap.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.e === cur.icon));
  });
  colorRow.addEventListener("click", (e) => {
    const b = e.target.closest(".swatch[data-c]");
    if (!b) return;
    cur.color = b.dataset.c;
    colorInput.value = cur.color;
    syncSwatches();
  });
  colorInput.addEventListener("input", () => {
    cur.color = colorInput.value;
    syncSwatches();
  });

  m.el.querySelector("#cmSave").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true;
    btn.textContent = "保存中…";
    const errEl = m.el.querySelector("#cmError");
    try {
      const payload = {
        name: m.el.querySelector("#cmName").value.trim(),
        type: cur.type,
        icon: cur.icon || (cur.type === "income" ? "💰" : "🍜"),
        color: cur.color,
      };
      if (!payload.name) throw new Error("请输入分类名称");
      if (isEdit) await PUT(`/api/categories/${c.id}`, payload);
      else await POST("/api/categories", payload);
      m.close();
      toast(isEdit ? "分类已更新 ✓" : "分类已创建 ✓", "ok");
      await loadCategories();
      refreshCurrent();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    } finally {
      btn.disabled = false;
      btn.textContent = isEdit ? "保存修改" : "创建分类";
    }
  });
}

/* ================= 渲染 ================= */
function destroyCharts() {
  state.charts.forEach((fn) => { try { fn(); } catch { /* noop */ } });
  state.charts = [];
}

async function loadCategories() {
  const data = await GET(`/api/categories?month=${state.dashMonth}`);
  state.categories = data.items;
}

function setPage(page) {
  state.page = page;
  $$("[data-page]").forEach((el) => el.classList.toggle("active", el.dataset.page === page));
  $$(".page").forEach((el) => el.classList.toggle("active", el.id === `page-${page}`));
  const pageEl = $(`#page-${page}`);
  $("#pageTitle").textContent = pageEl.dataset.title || "";
  $("#pageSub").textContent = pageEl.dataset.sub || "";
  destroyCharts();
  const renderers = { dashboard: renderDashboard, records: renderRecords, categories: renderCategories, analysis: renderAnalysis, export: renderExport, logs: renderLogs };
  (renderers[page] || renderDashboard)();
}

function refreshCurrent() {
  setPage(state.page);
}

/* ---------- 首页 ---------- */
async function renderDashboard() {
  const month = state.dashMonth;
  $("#dashMonth").value = month;
  const [sum, stats] = await Promise.all([
    GET(`/api/summary?month=${month}`),
    GET(`/api/stats/categories?month=${month}`),
  ]);
  animateNumber($("#statIncome"), sum.income);
  animateNumber($("#statExpense"), sum.expense);
  animateNumber($("#statBalance"), sum.balance);
  animateNumber($("#statCount"), sum.count, false);

  const items = (stats.expense || []).map((i) => ({ label: i.name, value: i.amount, color: i.color }));
  const emptyEl = $("#dashDonutEmpty");
  const box = $("#dashDonut").closest(".chart-box");
  if (!items.length) {
    box.classList.add("hidden");
    emptyEl.classList.remove("hidden");
    $("#dashLegend").innerHTML = "";
  } else {
    box.classList.remove("hidden");
    emptyEl.classList.add("hidden");
    const total = items.reduce((a, b) => a + b.value, 0) || 1;
    state.charts.push(Charts.donut($("#dashDonut"), items, { height: 230, centerText: ["本月支出", "¥" + money(total)] }));
    $("#dashLegend").innerHTML = items.slice(0, 6).map((i) => `
      <div class="legend-item"><span class="dot" style="background:${i.color}"></span><span class="legend-name">${esc(i.label)}</span><span class="legend-val">¥${money(i.value)}</span><span class="legend-pct">${(i.value / total * 100).toFixed(1)}%</span></div>`).join("");
  }

  sum.recent.forEach((r) => state.recMap.set(r.id, r));
  $("#dashRecent").innerHTML = sum.recent.length
    ? sum.recent.map(recRow).join("")
    : `<div class="empty">暂无账目，点击右上角「记一笔」开始记账</div>`;
}

/* ---------- 流水 ---------- */
async function renderRecords() {
  const f = state.rec;
  $("#recMonth").value = f.month || "";
  $("#recType").value = f.type;
  const qs = new URLSearchParams({ month: f.month, type: f.type, category: f.category, q: f.q, page: f.page, size: f.size });
  const data = await GET(`/api/records?${qs}`);
  state.rec.total = data.total;
  state.rec.pages = data.pages;
  data.items.forEach((r) => state.recMap.set(r.id, r));
  $("#recList").innerHTML = data.items.length
    ? data.items.map(recRow).join("")
    : `<div class="empty">${f.q || f.type || f.category ? "没有符合条件的账目" : "暂无账目，点击右上角「记一笔」开始记账"}</div>`;
  $("#recPageInfo").textContent = `第 ${f.page} / ${data.pages} 页 · 共 ${data.total} 笔`;
  $("#recPrev").disabled = f.page <= 1;
  $("#recNext").disabled = f.page >= data.pages;

  const catSel = $("#recCat");
  catSel.innerHTML = `<option value="">全部分类</option>` + state.categories
    .map((c) => `<option value="${c.id}">${esc(c.icon)} ${esc(c.name)}</option>`).join("");
  catSel.value = String(f.category || "");
}

/* ---------- 分类 ---------- */
async function renderCategories() {
  const data = await GET(`/api/categories?month=${state.dashMonth}`);
  state.categories = data.items;
  const grid = (t) => data.items.filter((c) => c.type === t).map(catCard).join("") || `<div class="empty">暂无分类</div>`;
  $("#expCatGrid").innerHTML = grid("expense");
  $("#incCatGrid").innerHTML = grid("income");
}

function catCard(c) {
  return `<div class="cat-card">
    <span class="cat-icon" style="background:${c.color}22;color:${c.color}">${esc(c.icon)}</span>
    <div class="cat-info"><b>${esc(c.name)}</b><span>共 ${c.record_count} 笔 · 本月 ¥${money(c.month_amount)}</span></div>
    <div class="cat-ops">
      <button class="icon-btn" data-cedit="${c.id}" title="编辑">${icon("i-edit")}</button>
      <button class="icon-btn danger" data-cdel="${c.id}" title="删除">${icon("i-trash")}</button>
    </div>
  </div>`;
}

async function deleteCategory(id) {
  const c = state.categories.find((x) => x.id === id);
  const ok = await confirmDialog("删除分类", `确定要删除分类「${esc(c ? c.name : "")}」吗？`);
  if (!ok) return;
  try {
    await DEL(`/api/categories/${id}`);
    toast("分类已删除", "ok");
    await loadCategories();
    refreshCurrent();
  } catch (err) { toast(err.message, "err"); }
}
/* ---------- 分析 ---------- */
async function renderAnalysis() {
  const month = state.anMonth;
  $("#anMonth").value = month;
  $("#anPieTitle").textContent = `本月支出构成（${month}）`;
  const [stats, trend] = await Promise.all([
    GET(`/api/stats/categories?month=${month}`),
    GET(`/api/stats/trend?months=6`),
  ]);

  const items = (stats.expense || []).map((i) => ({ label: i.name, value: i.amount, color: i.color }));
  const pieBox = $("#anPie").closest(".chart-box");
  const pieEmpty = $("#anPieEmpty");
  if (!items.length) {
    pieBox.classList.add("hidden");
    pieEmpty.classList.remove("hidden");
    $("#anPieLegend").innerHTML = "";
  } else {
    pieBox.classList.remove("hidden");
    pieEmpty.classList.add("hidden");
    const total = items.reduce((a, b) => a + b.value, 0) || 1;
    state.charts.push(Charts.donut($("#anPie"), items, { height: 290, centerText: ["本月支出", "¥" + money(total)] }));
    $("#anPieLegend").innerHTML = items.map((i) => `
      <div class="legend-item"><span class="dot" style="background:${i.color}"></span><span class="legend-name">${esc(i.label)}</span><span class="legend-val">¥${money(i.value)}</span><span class="legend-pct">${(i.value / total * 100).toFixed(1)}%</span></div>`).join("");
  }

  const labels = trend.labels.map((l) => l.slice(5));
  state.charts.push(Charts.bar($("#anBar"), labels, [
    { name: "收入", color: "#16a34a", values: trend.income },
    { name: "支出", color: "#ef4444", values: trend.expense },
  ], { height: 250 }));
  const balance = trend.income.map((v, i) => Math.round((v - trend.expense[i]) * 100) / 100);
  state.charts.push(Charts.line($("#anLine"), labels, [
    { name: "结余", color: "#4f7cff", values: balance },
  ], { height: 250, fill: true }));
}

/* ---------- 导出 ---------- */
function expRange() {
  const v = $("input[name=range]:checked").value;
  if (v === "month") { const m = ymNow(); return { start: m + "-01", end: ymLastDay(m) }; }
  if (v === "prev") { const p = ymShift(ymNow(), -1); return { start: p + "-01", end: ymLastDay(p) }; }
  if (v === "custom") return { start: $("#expStart").value || "", end: $("#expEnd").value || "" };
  return { start: "", end: "" };
}

async function updateExpMeta() {
  const v = $("input[name=range]:checked").value;
  const { start, end } = expRange();
  if (v === "custom" && (!start || !end)) {
    $("#expMeta").textContent = start || end ? "请补全开始和结束日期" : "请选择自定义日期范围";
    return;
  }
  if (start && end && start > end) {
    $("#expMeta").textContent = "开始日期不能晚于结束日期";
    return;
  }
  try {
    const qs = new URLSearchParams({ size: "1", start, end });
    const data = await GET(`/api/records?${qs}`);
    $("#expMeta").textContent = `将导出 ${data.total} 笔账目`;
  } catch { $("#expMeta").textContent = ""; }
}

async function renderExport() {
  updateExpMeta();
}

/* ---------- 日志 ---------- */
async function renderLogs() {
  const data = await GET(`/api/logs?page=${state.logs.page}&size=${state.logs.size}`);
  state.logs.total = data.total;
  state.logs.pages = data.pages;
  $("#logBody").innerHTML = data.items.length
    ? data.items.map((l) => `<tr><td>${esc(l.ts)}</td><td>${esc(l.user)}</td><td>${esc(l.ip)}</td><td><span class="badge">${esc(l.action)}</span></td><td class="log-detail">${esc(l.detail)}</td></tr>`).join("")
    : `<tr><td colspan="5"><div class="empty">暂无操作日志</div></td></tr>`;
  $("#logPageInfo").textContent = `第 ${state.logs.page} / ${data.pages} 页 · 共 ${data.total} 条`;
  $("#logPrev").disabled = state.logs.page <= 1;
  $("#logNext").disabled = state.logs.page >= data.pages;
}

/* ================= 登录 / 退出 ================= */
async function doLogin(e) {
  e.preventDefault();
  const btn = $("#loginBtn"), errEl = $("#loginError");
  btn.disabled = true;
  btn.textContent = "登录中…";
  errEl.classList.add("hidden");
  try {
    const data = await POST("/api/login", { username: $("#loginUser").value.trim(), password: $("#loginPass").value });
    enterApp(data);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove("hidden");
    const card = $(".login-card");
    card.classList.remove("shake");
    void card.offsetWidth;
    card.classList.add("shake");
  } finally {
    btn.disabled = false;
    btn.textContent = "登 录";
  }
}

async function enterApp(user) {
  state.user = user;
  state.inApp = true;
  $("#loginView").classList.add("hidden");
  $("#appView").classList.remove("hidden");
  $("#sideUserName").textContent = user.username;
  $("#userAvatar").textContent = user.username.slice(0, 1).toUpperCase();
  $("#sideServerTime").textContent = "已登录";
  try {
    await loadCategories();
  } catch { /* 分类加载失败时各页面会自行提示 */ }
  setPage("dashboard");
}

function showLogin() {
  state.inApp = false;
  state.user = null;
  destroyCharts();
  $("#appView").classList.add("hidden");
  $("#loginView").classList.remove("hidden");
  $("#loginPass").value = "";
  $("#loginUser").focus();
}

async function doLogout() {
  try { await POST("/api/logout"); } catch { /* 忽略 */ }
  toast("已退出登录", "info");
  showLogin();
}
/* ================= 事件绑定 ================= */
function bindStatic() {
  $$("[data-page]").forEach((el) => el.addEventListener("click", () => setPage(el.dataset.page)));
  $$("[data-goto]").forEach((el) => el.addEventListener("click", () => setPage(el.dataset.goto)));
  $("#loginForm").addEventListener("submit", doLogin);
  $("#logoutBtn").addEventListener("click", doLogout);
  $("#quickAddBtn").addEventListener("click", () => recordModal());

  // 首页月份
  $("#dashMonth").addEventListener("change", () => { state.dashMonth = $("#dashMonth").value || ymNow(); renderDashboard(); });
  $("#dashPrev").addEventListener("click", () => { state.dashMonth = ymShift(state.dashMonth, -1); $("#dashMonth").value = state.dashMonth; renderDashboard(); });
  $("#dashNext").addEventListener("click", () => { state.dashMonth = ymShift(state.dashMonth, 1); $("#dashMonth").value = state.dashMonth; renderDashboard(); });
  $("#dashToday").addEventListener("click", () => { state.dashMonth = ymNow(); $("#dashMonth").value = state.dashMonth; renderDashboard(); });

  // 流水筛选
  const resetRecPage = () => { state.rec.page = 1; renderRecords(); };
  $("#recMonth").addEventListener("change", () => { state.rec.month = $("#recMonth").value || ""; resetRecPage(); });
  $("#recType").addEventListener("change", () => { state.rec.type = $("#recType").value; resetRecPage(); });
  $("#recCat").addEventListener("change", () => { state.rec.category = $("#recCat").value; resetRecPage(); });
  $("#recSearch").addEventListener("input", debounce(() => { state.rec.q = $("#recSearch").value.trim(); resetRecPage(); }, 350));
  $("#recClear").addEventListener("click", () => {
    state.rec = Object.assign(state.rec, { month: ymNow(), type: "", category: "", q: "", page: 1 });
    $("#recMonth").value = state.rec.month;
    $("#recType").value = "";
    $("#recSearch").value = "";
    renderRecords();
  });
  $("#recPrev").addEventListener("click", () => { if (state.rec.page > 1) { state.rec.page--; renderRecords(); } });
  $("#recNext").addEventListener("click", () => { if (state.rec.page < state.rec.pages) { state.rec.page++; renderRecords(); } });

  // 记录操作（事件委托）
  const handleRecOps = (e) => {
    const editBtn = e.target.closest("[data-edit]");
    const delBtn = e.target.closest("[data-del]");
    if (editBtn) {
      const r = state.recMap.get(Number(editBtn.dataset.edit));
      if (r) recordModal(r);
    }
    if (delBtn) deleteRecord(Number(delBtn.dataset.del));
  };
  $("#recList").addEventListener("click", handleRecOps);
  $("#dashRecent").addEventListener("click", handleRecOps);

  // 分类
  $("#addExpCat").addEventListener("click", () => categoryModal(null, "expense"));
  $("#addIncCat").addEventListener("click", () => categoryModal(null, "income"));
  const handleCatOps = (e) => {
    const editBtn = e.target.closest("[data-cedit]");
    const delBtn = e.target.closest("[data-cdel]");
    if (editBtn) {
      const c = state.categories.find((x) => x.id === Number(editBtn.dataset.cedit));
      if (c) categoryModal(c);
    }
    if (delBtn) deleteCategory(Number(delBtn.dataset.cdel));
  };
  $("#expCatGrid").addEventListener("click", handleCatOps);
  $("#incCatGrid").addEventListener("click", handleCatOps);

  // 分析月份
  $("#anMonth").addEventListener("change", () => { state.anMonth = $("#anMonth").value || ymNow(); renderAnalysis(); });
  $("#anPrev").addEventListener("click", () => { state.anMonth = ymShift(state.anMonth, -1); $("#anMonth").value = state.anMonth; renderAnalysis(); });
  $("#anNext").addEventListener("click", () => { state.anMonth = ymShift(state.anMonth, 1); $("#anMonth").value = state.anMonth; renderAnalysis(); });

  // 图表下载 PNG
  $$(".chart-download").forEach((btn) => btn.addEventListener("click", () => {
    const canvas = $("#" + btn.dataset.chart);
    if (!canvas) return;
    try {
      const a = document.createElement("a");
      const ts = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "");
      a.href = canvas.toDataURL("image/png");
      a.download = `LnBudget-图表-${ts}.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      toast("图表已下载 ✓", "ok");
    } catch { toast("图表导出失败", "err"); }
  }));

  // 导出页
  $$("input[name=range]").forEach((r) => r.addEventListener("change", () => {
    $("#expCustom").classList.toggle("hidden", r.value !== "custom");
    updateExpMeta();
  }));
  $("#expStart").addEventListener("change", updateExpMeta);
  $("#expEnd").addEventListener("change", updateExpMeta);
  $("#expBtn").addEventListener("click", async () => {
    const fmt = $("input[name=fmt]:checked").value;
    const rangeValue = $("input[name=range]:checked").value;
    const { start, end } = expRange();
    if (rangeValue === "custom" && (!start || !end)) { toast("请选择完整的自定义日期范围", "err"); return; }
    if (start && end && start > end) { toast("开始日期不能晚于结束日期", "err"); return; }
    const btn = $("#expBtn");
    btn.disabled = true;
    btn.innerHTML = "导出中…";
    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json" },
        body: JSON.stringify({ format: fmt, start, end }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => null);
        throw new Error((d && d.error) || `导出失败（${res.status}）`);
      }
      const blob = await res.blob();
      let fname = "LnBudget-export." + ({ csv: "csv", excel: "xls", json: "json", html: "html" }[fmt] || "bin");
      const cd = res.headers.get("Content-Disposition") || "";
      const m1 = cd.match(/filename\*=UTF-8''([^;]+)/i);
      const m2 = cd.match(/filename="?([^";]+)"?/i);
      if (m1) { try { fname = decodeURIComponent(m1[1]); } catch { fname = m1[1]; } }
      else if (m2) fname = m2[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
      toast(`已导出 ${fmt.toUpperCase()} 文件 ✓`, "ok");
      updateExpMeta();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `${icon("i-download")}立即导出下载`;
    }
  });

  // 日志分页
  $("#logPrev").addEventListener("click", () => { if (state.logs.page > 1) { state.logs.page--; renderLogs(); } });
  $("#logNext").addEventListener("click", () => { if (state.logs.page < state.logs.pages) { state.logs.page++; renderLogs(); } });

  window.addEventListener("resize", debounce(() => { if (state.inApp) refreshCurrent(); }, 300));
}

/* ================= 启动 ================= */
window.addEventListener("DOMContentLoaded", () => {
  bindStatic();
  $("#loginUser").focus();
  GET("/api/me").then(enterApp).catch(() => showLogin());
});