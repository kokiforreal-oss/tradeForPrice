const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

    const PRESS_SEL = "a.card, .card, a.btn, button:not(.tl-acc-head), nav a, table a, a.name-link, .quote-box, .cat-row, .po-acc-toggle, .icon-btn, .cat-all, .cat-rail, a.todo-row";
let pressClearTimer = 0;
function clearPress(immediate) {
  window.clearTimeout(pressClearTimer);
  const run = () => $$(".is-press").forEach((el) => el.classList.remove("is-press"));
  if (immediate) run();
  else pressClearTimer = window.setTimeout(run, 240);
}
document.addEventListener("pointerdown", (e) => {
  if (e.button !== 0) return;
  const el = e.target.closest(PRESS_SEL);
  if (!el || el.disabled) return;
  window.clearTimeout(pressClearTimer);
  $$(".is-press").forEach((n) => {
    if (n !== el) n.classList.remove("is-press");
  });
  el.classList.add("is-press");
});
document.addEventListener("pointerup", () => clearPress(false), true);
document.addEventListener("pointercancel", () => clearPress(true), true);
document.addEventListener(
  "click",
  (e) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    const a = e.target.closest("a.card, a.btn, nav a, a.todo-row");
    if (!a) return;
    const href = a.getAttribute("href");
    if (!href || !href.startsWith("#") || href === "#") return;
    e.preventDefault();
    a.classList.add("is-press");
    window.setTimeout(() => {
      location.hash = href;
    }, 220);
  },
  true
);

const INQ = {
  pending_quote: "待报价",
  quoted: "已报价",
  selling: "销售中",
  done: "已完成",
};
const CLOSE_REASONS = ["客户未回复", "客户长时间未回", "价格不接受", "客户取消", "其他"];
const ORD = {
  draft: "草稿",
  pending_audit: "待审核",
  contract: "待填合同",
  fulfilling: "履约中",
  done: "完成",
};
const PO = {
  pending_fill: "待采购填写",
  pending_audit: "待审核",
  in_progress: "进行中",
  received: "收货",
  inbound: "入库",
  accepted: "验收",
  done: "已完成",
};
const INCOTERMS = ["EXW", "FCA", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];

let assistantTimer = null;

function stopAssistantTimer() {
  if (assistantTimer) {
    clearInterval(assistantTimer);
    assistantTimer = null;
  }
}

function tickAssistantClocks() {
  $$("#clock-grid .clock-card").forEach((card) => {
    const tz = card.dataset.tz;
    if (!tz) return;
    const now = new Date();
    const time = now.toLocaleTimeString("zh-CN", { timeZone: tz, hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const date = now.toLocaleDateString("zh-CN", { timeZone: tz, month: "2-digit", day: "2-digit" });
    const weekday = now.toLocaleDateString("zh-CN", { timeZone: tz, weekday: "short" });
    const t = card.querySelector(".time");
    const d = card.querySelector(".clock-date");
    if (t) t.textContent = time;
    if (d) d.textContent = `${date} ${weekday}`;
    const hourPart = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hour: "numeric",
      hour12: false,
      hourCycle: "h23",
    }).formatToParts(now).find((p) => p.type === "hour");
    const hour = Number(hourPart?.value);
    const wd = now.toLocaleDateString("en-US", { timeZone: tz, weekday: "short" });
    const work = !["Sat", "Sun"].includes(wd) && hour >= 9 && hour < 18;
    card.classList.toggle("is-work", work);
    const st = card.querySelector(".clock-status");
    if (st) st.textContent = work ? "工作时间" : ["Sat", "Sun"].includes(wd) ? "周末" : "非工作时间";
  });
}

function updateFxConvert(quotes, fx) {
  const usd = Number(quotes?.find((q) => q.code === "USD")?.rate) || Number(fx?.rates?.USD) || 0;
  const eur = Number(quotes?.find((q) => q.code === "EUR")?.rate) || Number(fx?.rates?.EUR) || 0;
  const amt = Number($("#fx-amt")?.value) || 0;
  const code = $("#fx-ccy")?.value || "USD";
  const rate = code === "EUR" ? eur : usd;
  if ($("#fx-out")) $("#fx-out").textContent = amt ? `${(amt * rate).toFixed(2)} RMB` : "—";
}

function renderFxQuotes(quotes, fx) {
  $("#fx-quotes").innerHTML = (quotes || [])
    .map(
      (q) => `<div class="fx-card">
        <div class="pair">${esc(q.pair)}</div>
        <div class="rate">${esc(q.rate)}</div>
        <div class="muted">${esc(q.per)} ≈ ${esc(q.rate)} 人民币</div>
      </div>`
    )
    .join("");
  const hint = $("#fx-asof");
  if (hint) hint.textContent = fx?.as_of ? `更新时间 ${fx.as_of}` : "";
  updateFxConvert(quotes, fx);
}

async function viewAssistant() {
  pageTitle("外贸助手");
  let data;
  try {
    data = await api("/api/assistant");
  } catch (err) {
    $("#view").innerHTML = `<div class="panel"><p class="error">${esc(err.message || "加载失败")}</p></div>`;
    return;
  }
  $("#view").innerHTML = `
    <div class="assist-grid">
      <div class="panel assist-panel">
        <div class="assist-toolbar">
          <h3>美元 / 欧元汇率</h3>
          <button type="button" class="ghost" id="fx-refresh">刷新汇率</button>
        </div>
        <p class="muted" id="fx-asof" style="margin-top:0"></p>
        <div class="fx-cards" id="fx-quotes"></div>
        <div class="fx-convert">
          <label>换算<input id="fx-amt" type="number" step="0.01" min="0" value="100"></label>
          <label>币种<select id="fx-ccy"><option value="USD">USD</option><option value="EUR">EUR</option></select></label>
          <output id="fx-out">—</output>
        </div>
      </div>
      <div class="panel assist-panel">
        <h3>世界时间</h3>
        <p class="muted" style="margin-top:0">对照北京时间，便于联系海外客户与供应商。绿色边框为当地工作时间（工作日 9:00–18:00）。</p>
        <div class="clock-grid" id="clock-grid">
          ${(data.clocks || [])
            .map(
              (c) => `<div class="clock-card ${c.work ? "is-work" : ""}" data-tz="${esc(c.tz)}">
                <div class="clock-head">
                  <strong>${esc(c.city)}</strong>
                  <span>${esc(c.region)}</span>
                </div>
                <div class="time">${esc(c.time)}</div>
                <div class="clock-meta"><span class="clock-date">${esc(c.date)} ${esc(c.weekday)}</span> · ${esc(c.offset)}</div>
                <div class="clock-meta">${esc(c.vs_beijing)} · <span class="clock-status">${esc(c.work_label)}</span></div>
              </div>`
            )
            .join("")}
        </div>
      </div>
    </div>`;
  const quotes = data.quotes || [];
  const fx = data.fx || {};
  renderFxQuotes(quotes, fx);
  const recalc = () => updateFxConvert(quotes, fx);
  $("#fx-amt").oninput = recalc;
  $("#fx-ccy").onchange = recalc;
  $("#fx-refresh").onclick = async () => {
    try {
      const n = await api("/api/assistant?refresh=true");
      quotes.splice(0, quotes.length, ...(n.quotes || []));
      Object.assign(fx, n.fx || {});
      renderFxQuotes(quotes, fx);
    } catch (err) {
      alert(err.message || "刷新失败");
    }
  };
  stopAssistantTimer();
  tickAssistantClocks();
  assistantTimer = setInterval(tickAssistantClocks, 1000);
}

let me = null;
let productsCache = [];
let prodState = {
  categoryId: "",
  sku: "",
  status: "active",
  page: 1,
  pageSize: 50,
  expanded: new Set(),
  expandedInited: false,
  treeCollapsed: false,
};

function token() {
  return localStorage.getItem("token") || "";
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (token()) headers.Authorization = "Bearer " + token();
  if (!e2eSkipPath(path)) {
    await e2eLoadKeys();
    path = await e2eProtectPath(path);
  }
  if (opts.json) {
    headers["Content-Type"] = "application/json";
    const payload = e2eSkipPath(path) ? opts.json : await e2eWalkEncrypt(opts.json);
    opts.body = JSON.stringify(payload);
  }
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    e2eClearKeys();
    localStorage.removeItem("token");
    location.hash = "#/login";
    throw new Error("请重新登录");
  }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg || JSON.stringify(x)).join("; ") : data.message || "请求失败";
      throw new Error(msg);
    }
  if (e2eSkipPath(path) || !e2eAesKey) return data;
  return e2eWalkDecrypt(data);
}

function navItems() {
  const all = [
    { href: "#/home", label: "工作台" },
    { href: "#/products", label: "产品库" },
  ];
  if (["admin", "sales", "purchase", "finance"].includes(me.role)) {
    all.push({ href: "#/inquiries", label: "询价单管理" });
  }
  if (["admin", "sales", "purchase", "finance"].includes(me.role)) {
    all.push({ href: "#/orders", label: "销售订单" });
  }
  if (["admin", "sales", "purchase", "finance"].includes(me.role)) {
    all.push({ href: "#/purchase-orders", label: "采购订单" });
  }
  if (["admin", "finance"].includes(me.role)) {
    all.push({ href: "#/finance", label: "资金管理" });
  }
  if (me.role === "admin") all.push({ href: "#/users", label: "用户管理" });
  all.push({ href: "#/assistant", label: "外贸助手", foot: true });
  return all;
}

function renderNavLinks(items, path) {
  return items
    .map((i) => {
      if (i.group) return `<div class="nav-label">${esc(i.group)}</div>`;
      const active = path === i.href || (i.href !== "#/home" && path.startsWith(i.href));
      return `<a href="${i.href}" class="${active ? "active" : ""} ${i.indent ? "sub" : ""}">${i.label}</a>`;
    })
    .join("");
}

function renderNav() {
  const path = parseHash().path || "#/home";
  const items = navItems();
  $("#nav").innerHTML = renderNavLinks(items.filter((i) => !i.foot), path);
  $("#nav-foot").innerHTML = renderNavLinks(items.filter((i) => i.foot), path);
  $("#who").innerHTML = `<span class="who-avatar">${esc((me.name || "?").slice(0, 1))}</span><span class="who-text">${esc(me.name)} · ${esc(me.role_label)}</span>`;
}

function pageTitle(t) {
  $("#page-title").textContent = t;
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function pill(status, label) {
  const cls = status === "closed" || status === "done" ? "won" : status;
  return `<span class="pill ${cls}">${esc(label)}</span>`;
}

async function ensureMe() {
  if (!token()) return null;
  try {
    await e2eLoadKeys();
    me = await api("/api/auth/me");
    return me;
  } catch {
    me = null;
    return null;
  }
}

function showLogin() {
  $("#login-page").classList.remove("hidden");
  $("#app-shell").classList.add("hidden");
}

function showApp() {
  $("#login-page").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");
  renderNav();
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  const fd = new FormData(e.target);
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      json: { username: fd.get("username"), password: fd.get("password") },
    });
    localStorage.setItem("token", data.token);
    me = data.user;
    await e2eLoadKeys();
    location.hash = "#/home";
    await route();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#logout").addEventListener("click", () => {
  localStorage.removeItem("token");
  e2eClearKeys();
  me = null;
  location.hash = "#/login";
  route();
});

function parseHash() {
  const h = location.hash || "#/home";
  const i = h.indexOf("?");
  return {
    path: i >= 0 ? h.slice(0, i) : h,
    params: new URLSearchParams(i >= 0 ? h.slice(i + 1) : ""),
  };
}

function listFilterQs() {
  const p = parseHash().params;
  const q = new URLSearchParams();
  if (p.get("status")) q.set("status", p.get("status"));
  if (p.get("from")) q.set("date_from", p.get("from"));
  if (p.get("to")) q.set("date_to", p.get("to"));
  const s = q.toString();
  return s ? "?" + s : "";
}

function dateRangeFields() {
  const p = parseHash().params;
  return `<label class="doc-range">从<input type="date" name="from" value="${esc(p.get("from") || "")}"></label>
    <label class="doc-range">到<input type="date" name="to" value="${esc(p.get("to") || "")}"></label>`;
}

function bindDocListFilter(baseHash) {
  const apply = () => {
    const q = new URLSearchParams();
    const status = ($("#view select[name=status]") || {}).value || "";
    const from = ($("#view input[name=from]") || {}).value || "";
    const to = ($("#view input[name=to]") || {}).value || "";
    if (status) q.set("status", status);
    if (from) q.set("from", from);
    if (to) q.set("to", to);
    const s = q.toString();
    location.hash = s ? `${baseHash}?${s}` : baseHash;
  };
  const form = $("#view .page-toolbar");
  if (form && form.tagName === "FORM") {
    form.onsubmit = (e) => {
      e.preventDefault();
      apply();
    };
  }
}

const CARD_HREF = {
  pending_quote: "#/inquiries?status=pending_quote",
  quoted: "#/inquiries?status=quoted",
  selling: "#/inquiries?status=selling",
  done: "#/inquiries?status=done",
  pending_audit: "#/orders?status=pending_audit",
  contract: "#/orders?status=contract",
  fulfilling: "#/orders?status=fulfilling",
  po_fill: "#/purchase-orders?status=pending_fill",
  po_pending: "#/purchase-orders?status=pending_audit",
  po_progress: "#/purchase-orders?status=in_progress",
  pay_fill: "#/finance?tab=payments",
};

async function viewHome() {
  pageTitle("工作台");
  const d = await api("/api/dashboard");
  const todos = d.todos || [];
  const todoHint =
    me.role === "admin"
      ? "待审核的销售订单、采购订单会显示在这里。"
      : me.role === "sales"
        ? "已报价询价单、审核驳回待处理的单据、待填写合同会显示在这里。"
        : me.role === "purchase"
          ? "待报价询价单、待填写及审核驳回的采购单会显示在这里。"
          : me.role === "finance"
            ? "采购单审核通过后生成的待填写付款单会显示在这里。"
            : "当前角色没有流程待办。";
  $("#view").innerHTML = `
    <p class="muted">你好，${esc(d.name)}</p>
    <div class="cards">
      ${d.cards
        .map((c) => {
          const href = CARD_HREF[c.key] || "#/home";
          return `<a class="card" href="${href}"><div class="n">${c.count}</div><div class="l">${esc(c.label)}</div></a>`;
        })
        .join("")}
    </div>
    <div class="panel todo-panel">
      <div class="todo-head">
        <h3>待办事项</h3>
        <span class="todo-count">${todos.length}</span>
      </div>
      <p class="muted todo-hint">${todoHint}</p>
      ${
        todos.length
          ? `<div class="todo-list">${todos
              .map(
                (t) => `<a class="todo-row" href="${esc(t.href)}">
                  <span class="pill ${esc(t.kind)}">${esc(t.tag)}</span>
                  <span class="todo-main">
                    <strong>${esc(t.title)}</strong>
                    <span class="muted">${esc(t.subtitle || "")}${t.time ? ` · ${esc(t.time)}` : ""}</span>
                  </span>
                  <span class="todo-go">去处理</span>
                </a>`
              )
              .join("")}</div>`
          : `<p class="muted todo-empty">暂无待办，当前事项都已处理。</p>`
      }
    </div>`;
}

async function loadProducts(activeOnly = false) {
  const data = await api("/api/products" + (activeOnly ? "?active_only=true&page_size=500" : "?page_size=500"));
  productsCache = data.items || [];
  return productsCache;
}

function flattenCats(nodes, acc = []) {
  for (const n of nodes || []) {
    acc.push(n);
    if (n.children?.length) flattenCats(n.children, acc);
  }
  return acc;
}

function ensureCatExpanded(tree) {
  if (prodState.expandedInited) return;
  flattenCats(tree).forEach((n) => {
    if (n.children?.length) prodState.expanded.add(n.id);
  });
  prodState.expandedInited = true;
}

function catTreeHtml(nodes, depth = 0) {
  const selected = String(prodState.categoryId || "");
  return (nodes || [])
    .map((n) => {
      const has = n.children?.length;
      const open = has && prodState.expanded.has(n.id);
      return `<div class="cat-node" style="--d:${depth}">
        <div class="cat-row ${String(n.id) === selected ? "on" : ""}" data-cat="${n.id}">
          <button type="button" class="cat-chevron ${has ? "" : "empty"}" data-toggle="${n.id}">${has ? (open ? "▾" : "▸") : ""}</button>
          <span class="cat-label">${esc(n.code)} ${esc(n.name)}</span>
        </div>
        ${has && open ? `<div class="cat-children">${catTreeHtml(n.children, depth + 1)}</div>` : ""}
      </div>`;
    })
    .join("");
}

async function viewProducts() {
  pageTitle("产品库");
  $("#view").classList.add("catalog-fill");
  document.querySelector(".workspace")?.classList.add("catalog-mode");
  const canEdit = me.role === "admin";
  const showCost = me.role === "admin" || me.role === "purchase";
  const qs = new URLSearchParams();
  if (prodState.sku) qs.set("sku", prodState.sku);
  if (prodState.status) qs.set("status", prodState.status);
  if (prodState.categoryId) qs.set("category_id", prodState.categoryId);
  qs.set("page", String(prodState.page));
  qs.set("page_size", String(prodState.pageSize));
  const [tree, data] = await Promise.all([
    api("/api/products/categories"),
    api("/api/products?" + qs.toString()),
  ]);
  ensureCatExpanded(tree);
  const rows = data.items || [];
  const total = data.total || 0;
  const pages = Math.max(1, Math.ceil(total / prodState.pageSize));
  if (prodState.page > pages) prodState.page = pages;
  const flat = flattenCats(tree);
  const catName = (id) => {
    const c = flat.find((x) => String(x.id) === String(id));
    return c ? `${c.code} ${c.name}` : "";
  };
  const tags = [];
  if (prodState.status) tags.push({ key: "status", text: prodState.status === "active" ? "启用" : "停用" });
  if (prodState.sku) tags.push({ key: "sku", text: prodState.sku });
  if (prodState.categoryId) tags.push({ key: "categoryId", text: catName(prodState.categoryId) });

  $("#view").innerHTML = `
    <div class="catalog ${prodState.treeCollapsed ? "tree-collapsed" : ""}">
      <div class="cat-tree">
        ${
          prodState.treeCollapsed
            ? `<button type="button" class="cat-rail" id="cat-unfold" title="展开分类">分类</button>`
            : `<div class="cat-tree-head">
          <span class="cat-tree-title">分类</span>
          <div class="cat-tree-actions">
            <button type="button" class="icon-btn" id="cat-add" title="新增分类">+</button>
            ${canEdit ? `<button type="button" class="icon-btn" id="cat-edit" title="编辑分类">✎</button>` : ""}
            <button type="button" class="icon-btn" id="cat-fold" title="收起分类">‹</button>
          </div>
        </div>
        <button type="button" class="cat-all ${prodState.categoryId ? "" : "on"}" id="cat-all">全部</button>
        <div class="cat-tree-body">${catTreeHtml(tree)}</div>`
        }
      </div>
      <div class="cat-main">
        <div class="filter-bar">
          <label>产品ID<input name="sku" value="${esc(prodState.sku)}" placeholder="输入产品ID"></label>
          <label class="filter-status">状态
            <select name="status">
              <option value="">全部</option>
              <option value="active" ${prodState.status === "active" ? "selected" : ""}>启用</option>
              <option value="disabled" ${prodState.status === "disabled" ? "selected" : ""}>停用</option>
            </select>
          </label>
          <div class="filter-actions">
            <button type="button" class="ghost" id="p-search">查询</button>
            <button type="button" id="add-p">新增产品</button>
          </div>
        </div>
        ${
          tags.length
            ? `<div class="filter-tags">${tags
                .map((t) => `<span class="filter-tag">${esc(t.text)}<button type="button" data-clear="${t.key}">×</button></span>`)
                .join("")}</div>`
            : ""
        }
        <div class="erp-table-wrap">
          <table class="erp">
            <thead>
              <tr>
                <th class="col-idx">#</th>
                <th class="col-check"><input type="checkbox" id="p-all"></th>
                <th>产品分类</th>
                <th>产品ID</th>
                <th>产品名称</th>
                <th>规格</th>
                <th>商品类型</th>
                <th>计价方式</th>
                <th>计量单位</th>
                <th>主计量单位</th>
                <th>辅助计量单位</th>
                <th>销售单位</th>
                ${showCost ? "<th>参考成本</th>" : ""}
                <th>状态</th>
                ${canEdit ? "<th>操作</th>" : ""}
              </tr>
            </thead>
            <tbody>
              ${
                rows.length
                  ? rows
                      .map((p, i) => {
                        const idx = (prodState.page - 1) * prodState.pageSize + i + 1;
                        const cat = p.category_name ? `${esc(p.category_code)} ${esc(p.category_name)}` : "";
                        return `<tr>
                          <td class="col-idx">${idx}</td>
                          <td class="col-check"><input type="checkbox" data-check="${p.id}"></td>
                          <td>${cat}</td>
                          <td>${esc(p.sku)}</td>
                          <td><a href="#" class="name-link" data-open="${p.id}">${esc(p.name)}</a></td>
                          <td>${esc(p.spec)}</td>
                          <td>${esc(p.product_type)}</td>
                          <td>${esc(p.pricing_method)}</td>
                          <td>${esc(p.unit)}</td>
                          <td>${esc(p.primary_unit)}</td>
                          <td>${esc(p.aux_unit)}</td>
                          <td>${esc(p.sales_unit)}</td>
                          ${showCost ? `<td>${p.cost_price ?? ""}</td>` : ""}
                          <td>${pill(p.status, p.status === "active" ? "启用" : "停用")}</td>
                          ${
                            canEdit
                              ? `<td class="row-actions">
                                  <button class="ghost" data-edit="${p.id}">编辑</button>
                                  <button class="danger" data-del="${p.id}">删除</button>
                                </td>`
                              : ""
                          }
                        </tr>`;
                      })
                      .join("")
                  : `<tr><td colspan="16" class="empty-hint muted">暂无产品</td></tr>`
              }
            </tbody>
          </table>
        </div>
        <div class="pager">
          <span class="muted">共 ${total} 条</span>
          <label>每页显示
            <select name="page_size">
              ${[20, 50, 100, 500].map((n) => `<option value="${n}" ${n === prodState.pageSize ? "selected" : ""}>${n}</option>`).join("")}
            </select>
          </label>
          <div class="pager-btns">
            <button type="button" class="ghost" data-page="1" ${prodState.page <= 1 ? "disabled" : ""}>首页</button>
            <button type="button" class="ghost" data-page="${prodState.page - 1}" ${prodState.page <= 1 ? "disabled" : ""}>上一页</button>
            <span>${prodState.page} / ${pages}</span>
            <button type="button" class="ghost" data-page="${prodState.page + 1}" ${prodState.page >= pages ? "disabled" : ""}>下一页</button>
            <button type="button" class="ghost" data-page="${pages}" ${prodState.page >= pages ? "disabled" : ""}>末页</button>
          </div>
        </div>
      </div>
    </div>
    <div id="p-modal"></div>`;

  const readFilters = () => {
    prodState.sku = $("#view input[name=sku]").value.trim();
    prodState.status = $("#view select[name=status]").value;
    prodState.page = 1;
  };
  $("#p-search").onclick = () => {
    readFilters();
    viewProducts();
  };
  $("#view input[name=sku]").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      readFilters();
      viewProducts();
    }
  });
  $("#view select[name=status]").onchange = () => {
    readFilters();
    viewProducts();
  };
  $("#view select[name=page_size]").onchange = (e) => {
    prodState.pageSize = Number(e.target.value);
    prodState.page = 1;
    viewProducts();
  };
  $$("[data-page]").forEach((b) => {
    b.onclick = () => {
      prodState.page = Number(b.dataset.page);
      viewProducts();
    };
  });
  $$("[data-clear]").forEach((b) => {
    b.onclick = () => {
      prodState[b.dataset.clear] = "";
      prodState.page = 1;
      viewProducts();
    };
  });
  $("#cat-all")?.addEventListener("click", () => {
    prodState.categoryId = "";
    prodState.page = 1;
    viewProducts();
  });
  $("#cat-fold")?.addEventListener("click", () => {
    prodState.treeCollapsed = true;
    viewProducts();
  });
  $("#cat-unfold")?.addEventListener("click", () => {
    prodState.treeCollapsed = false;
    viewProducts();
  });
  $$(".cat-row[data-cat]").forEach((el) => {
    el.onclick = (e) => {
      if (e.target.closest("[data-toggle]")) return;
      prodState.categoryId = el.dataset.cat;
      prodState.page = 1;
      viewProducts();
    };
  });
  $$("[data-toggle]").forEach((b) => {
    b.onclick = (e) => {
      e.stopPropagation();
      const id = +b.dataset.toggle;
      if (prodState.expanded.has(id)) prodState.expanded.delete(id);
      else prodState.expanded.add(id);
      viewProducts();
    };
  });
  const all = $("#p-all");
  if (all) {
    all.onchange = () => $$("[data-check]").forEach((c) => (c.checked = all.checked));
  }
  $("#add-p").onclick = () => productForm(null, tree);
  $("#cat-add")?.addEventListener("click", () => categoryForm(tree));
  $$("[data-open], [data-edit]").forEach((b) => {
    b.onclick = (e) => {
      e.preventDefault();
      productForm(rows.find((x) => x.id === +b.dataset.open || x.id === +b.dataset.edit), tree);
    };
  });
  if (canEdit) {
    $("#cat-edit")?.addEventListener("click", () => {
      if (!prodState.categoryId) {
        alert("请先在左侧选择要编辑的分类");
        return;
      }
      const cur = flat.find((x) => String(x.id) === String(prodState.categoryId));
      categoryForm(tree, cur);
    });
    $$("[data-del]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("确认删除？已被引用的产品将改为停用。")) return;
        const r = await api("/api/products/" + b.dataset.del, { method: "DELETE" });
        alert(r.message);
        viewProducts();
      };
    });
  }
}

function categoryForm(tree, cat) {
  const flat = flattenCats(tree);
  $("#p-modal").innerHTML = `
    <div class="modal-mask">
      <form class="modal-card" id="cf">
        <h3>${cat ? "编辑分类" : "新增分类"}</h3>
        <div class="form-grid inq-form">
          <label>上级分类
            <select name="parent_id">
              <option value="">无（一级分类）</option>
              ${flat
                .filter((c) => !cat || c.id !== cat.id)
                .map(
                  (c) =>
                    `<option value="${c.id}" ${String(c.id) === String(cat?.parent_id || (!cat && prodState.categoryId)) ? "selected" : ""}>${esc(c.code)} ${esc(c.name)}</option>`
                )
                .join("")}
            </select>
          </label>
          <label>编码<input name="code" required value="${esc(cat?.code || "")}" placeholder="如 04"></label>
          <label>名称<input name="name" required value="${esc(cat?.name || "")}"></label>
        </div>
        <div class="row-actions form-footer">
          <button type="submit">保存</button>
          ${cat && me.role === "admin" ? `<button type="button" class="danger" id="cf-del">删除分类</button>` : ""}
          <button type="button" class="ghost" id="cf-cancel">取消</button>
        </div>
      </form>
    </div>`;
  const close = () => ($("#p-modal").innerHTML = "");
  $("#cf-cancel").onclick = close;
  $(".modal-mask").onclick = (e) => {
    if (e.target.classList.contains("modal-mask")) close();
  };
  if ($("#cf-del")) {
    $("#cf-del").onclick = async () => {
      if (!confirm("确认删除该分类？")) return;
      await api("/api/products/categories/" + cat.id, { method: "DELETE" });
      if (String(prodState.categoryId) === String(cat.id)) prodState.categoryId = "";
      close();
      viewProducts();
    };
  }
  $("#cf").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = {
      code: fd.get("code"),
      name: fd.get("name"),
      parent_id: fd.get("parent_id") ? Number(fd.get("parent_id")) : null,
    };
    if (cat) await api("/api/products/categories/" + cat.id, { method: "PATCH", json: body });
    else await api("/api/products/categories", { method: "POST", json: body });
    close();
    viewProducts();
  };
}

function productForm(p, tree = []) {
  const canSave = !p || me.role === "admin";
  const flat = flattenCats(tree);
  const defaultCat = p?.category_id || prodState.categoryId || "";
  $("#p-modal").innerHTML = `
    <div class="modal-mask">
      <form class="modal-card wide" id="pf">
        <h3>${p ? "产品详情" : "新增产品"}</h3>
        <div class="form-grid inq-form">
          <label class="full">产品分类
            <select name="category_id">
              <option value="">未分类</option>
              ${flat.map((c) => `<option value="${c.id}" ${String(c.id) === String(defaultCat) ? "selected" : ""}>${esc(c.code)} ${esc(c.name)}</option>`).join("")}
            </select>
          </label>
          ${!p ? `<div class="full"><button type="button" class="ghost" id="pf-new-cat">没有合适分类？新建分类</button></div>` : ""}
          <label>产品ID<input name="sku" required value="${esc(p?.sku || "")}" ${p && !canSave ? "readonly" : ""}></label>
          <label>产品名称<input name="name" required value="${esc(p?.name || "")}" ${!canSave ? "readonly" : ""}></label>
          <label>规格<input name="spec" value="${esc(p?.spec || "")}" ${!canSave ? "readonly" : ""}></label>
          <label>商品类型<select name="product_type" ${!canSave ? "disabled" : ""}>
            ${["实物", "服务"].map((x) => `<option ${ (p?.product_type || "实物") === x ? "selected" : ""}>${x}</option>`).join("")}
          </select></label>
          <label>计价方式<select name="pricing_method" ${!canSave ? "disabled" : ""}>
            ${["固定价", "移动平均"].map((x) => `<option ${ (p?.pricing_method || "固定价") === x ? "selected" : ""}>${x}</option>`).join("")}
          </select></label>
          <label>计量单位<input name="unit" value="${esc(p?.unit || "pcs")}" ${!canSave ? "readonly" : ""}></label>
          <label>主计量单位<input name="primary_unit" value="${esc(p?.primary_unit || p?.unit || "pcs")}" ${!canSave ? "readonly" : ""}></label>
          <label>辅助计量单位<input name="aux_unit" value="${esc(p?.aux_unit || "")}" ${!canSave ? "readonly" : ""}></label>
          <label>销售单位<input name="sales_unit" value="${esc(p?.sales_unit || p?.unit || "pcs")}" ${!canSave ? "readonly" : ""}></label>
          <label>参考成本 RMB<input name="cost_price" type="number" step="0.01" value="${p?.cost_price ?? ""}" ${!canSave ? "readonly" : ""}></label>
          <label>状态<select name="status" ${!canSave ? "disabled" : ""}>
            <option value="active" ${p?.status !== "disabled" ? "selected" : ""}>启用</option>
            <option value="disabled" ${p?.status === "disabled" ? "selected" : ""}>停用</option>
          </select></label>
          <label class="full">备注<input name="remark" value="${esc(p?.remark || "")}" ${!canSave ? "readonly" : ""}></label>
        </div>
        <div class="row-actions form-footer">
          ${canSave ? `<button type="submit">保存</button>` : ""}
          <button type="button" class="ghost" id="pf-cancel">取消</button>
        </div>
      </form>
    </div>`;
  const close = () => ($("#p-modal").innerHTML = "");
  $("#pf-cancel").onclick = close;
  if ($("#pf-new-cat")) {
    $("#pf-new-cat").onclick = () => categoryForm(tree);
  }
  $(".modal-mask").onclick = (e) => {
    if (e.target.classList.contains("modal-mask")) close();
  };
  $("#pf").onsubmit = async (e) => {
    e.preventDefault();
    if (!canSave) return;
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd.entries());
    body.cost_price = body.cost_price === "" ? null : Number(body.cost_price);
    body.category_id = body.category_id ? Number(body.category_id) : null;
    if (p) await api("/api/products/" + p.id, { method: "PATCH", json: body });
    else await api("/api/products", { method: "POST", json: body });
    close();
    viewProducts();
  };
}

async function viewInquiries() {
  pageTitle("询价单管理");
  const status = parseHash().params.get("status") || "";
  const rows = await api("/api/inquiries" + listFilterQs());
  const canCreate = me.role === "sales";
  const canDelete = me.role === "admin";
  $("#view").innerHTML = `
    <div class="inq-page">
    <form class="toolbar page-toolbar">
      <select name="status">
        <option value="">全部状态</option>
        ${Object.entries(INQ)
          .map(([k, v]) => `<option value="${k}" ${k === status ? "selected" : ""}>${v}</option>`)
          .join("")}
      </select>
      ${dateRangeFields()}
      <button class="ghost" type="submit">筛选</button>
      ${canCreate ? `<a class="btn" href="#/inquiries/new">新建询价单</a>` : ""}
    </form>
    <div class="table-wrap"><table>
      <thead><tr><th>单号</th><th>客户</th><th>币种</th><th>状态</th><th>销售</th><th>创建时间</th><th>操作</th></tr></thead>
      <tbody>
        ${
          rows.length
            ? rows
                .map(
                  (r) => `<tr>
            <td><a href="#/inquiries/${r.id}">${esc(r.no)}</a></td>
            <td>${esc(r.customer_name)}</td><td>${esc(r.currency)}</td>
            <td>${pill(r.status, r.status_label)}</td>
            <td>${esc(r.creator_name)}</td><td>${esc(r.created_at)}</td>
            <td class="row-actions">
              <a class="btn" href="#/inquiries/${r.id}">查看</a>
              ${canDelete ? `<button class="danger" data-del-inq="${r.id}">删除</button>` : ""}
            </td>
          </tr>`
                )
                .join("")
            : `<tr><td colspan="7" class="empty-hint muted">暂无询价单</td></tr>`
        }
      </tbody>
    </table></div>
    </div>`;
  bindDocListFilter("#/inquiries");
  $$("[data-del-inq]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("确认删除该询价单？关联订单会一并删除。")) return;
      await api("/api/inquiries/" + b.dataset.delInq, { method: "DELETE" });
      viewInquiries();
    };
  });
}

async function viewInquiryNew() {
  if (me.role !== "sales") {
    location.hash = "#/inquiries";
    return;
  }
  pageTitle("新建询价单");
  await loadProducts(true);
  $("#view").innerHTML = inquiryFormHtml();
  bindInquiryForm();
}

function inquiryFormHtml(inq) {
  const lines = inq?.lines?.length ? inq.lines : [{ product_id: "", quantity: 1, target_price: "", remark: "" }];
  return `
    <form id="inq-form" class="inq-page">
      <div class="panel">
        <h3>客户信息</h3>
        <div class="form-grid inq-form">
          <label>客户名称<input name="customer_name" required value="${esc(inq?.customer_name || "")}"></label>
          <label>联系人<input name="contact_name" value="${esc(inq?.contact_name || "")}"></label>
          <label>电话<input name="phone" value="${esc(inq?.phone || "")}"></label>
          <label>邮箱<input name="email" value="${esc(inq?.email || "")}"></label>
          <label>币种<select name="currency">
            ${["RMB", "USD", "EUR"]
              .map((c) => `<option ${ (inq?.currency || "RMB") === c ? "selected" : ""}>${c}</option>`)
              .join("")}
          </select></label>
          <label class="full">需求说明<textarea name="requirement" placeholder="交货要求、包装、认证等">${esc(inq?.requirement || "")}</textarea></label>
        </div>
      </div>
      <div class="panel">
        <h3>产品明细</h3>
        <p class="muted section-lead">至少一行。可从产品库选择，也可直接输入产品名称。</p>
        <div class="table-wrap"><table class="line-table">
          <thead><tr><th>产品</th><th>规格</th><th>单位</th><th>数量</th><th>客户目标价</th><th>备注</th><th></th></tr></thead>
          <tbody id="lines">${lines.map(lineRow).join("")}</tbody>
        </table></div>
        <div class="row-actions form-footer">
          <button type="button" class="ghost" id="add-line">加一行</button>
          <button type="submit">保存询价单</button>
        </div>
      </div>
    </form>`;
}

function lineRow(ln = {}) {
  const opts = productsCache
    .map(
      (p) =>
        `<option value="${p.id}" ${String(p.id) === String(ln.product_id || "") ? "selected" : ""}>${esc(p.sku)} ${esc(p.name)}</option>`
    )
    .join("");
  const fromCatalog = Boolean(ln.product_id);
  return `<tr>
    <td class="col-product${fromCatalog ? " from-catalog" : ""}">
      <div class="product-pick">
        <select name="product_id">
          <option value="">手动输入</option>
          ${opts}
        </select>
        <input name="product_name" class="product-name-input" ${fromCatalog ? "" : "required"} value="${esc(ln.product_name || "")}" placeholder="输入产品名称" ${fromCatalog ? "hidden" : ""}>
      </div>
    </td>
    <td><input name="spec" value="${esc(ln.spec || "")}" placeholder="规格"></td>
    <td class="col-qty"><input name="unit" value="${esc(ln.unit || "pcs")}"></td>
    <td class="col-qty"><input name="quantity" type="number" step="0.01" min="0.01" required value="${ln.quantity ?? 1}"></td>
    <td class="col-price"><input name="target_price" type="number" step="0.01" value="${ln.target_price ?? ""}" placeholder="选填"></td>
    <td><input name="remark" value="${esc(ln.remark || "")}" placeholder="选填"></td>
    <td><button type="button" class="ghost rm-line">删除</button></td>
  </tr>`;
}

function syncLineProductMode(tr) {
  const sel = $("[name=product_id]", tr);
  const name = $("[name=product_name]", tr);
  if (!sel || !name) return;
  const p = productsCache.find((x) => String(x.id) === sel.value);
  const fromCatalog = Boolean(p);
  tr.querySelector(".col-product")?.classList.toggle("from-catalog", fromCatalog);
  name.hidden = fromCatalog;
  name.required = !fromCatalog;
  if (fromCatalog) {
    name.value = p.name || "";
    $("[name=spec]", tr).value = p.spec || "";
    $("[name=unit]", tr).value = p.unit || "pcs";
  } else {
    name.focus();
  }
}

function bindInquiryForm(inqId) {
  $("#add-line").onclick = () => {
    $("#lines").insertAdjacentHTML("beforeend", lineRow());
  };
  $("#inq-form").addEventListener("click", (e) => {
    if (e.target.classList.contains("rm-line")) {
      const trs = $$("#lines tr");
      if (trs.length > 1) e.target.closest("tr").remove();
    }
  });
  $("#inq-form").addEventListener("change", (e) => {
    if (e.target.name !== "product_id") return;
    const tr = e.target.closest("tr");
    if (tr) syncLineProductMode(tr);
  });
  $("#inq-form").onsubmit = async (e) => {
    e.preventDefault();
    const f = e.target;
    const lines = $$("#lines tr").map((tr) => ({
      product_id: $("[name=product_id]", tr).value ? Number($("[name=product_id]", tr).value) : null,
      product_name: $("[name=product_name]", tr).value,
      spec: $("[name=spec]", tr).value,
      unit: $("[name=unit]", tr).value,
      quantity: Number($("[name=quantity]", tr).value),
      target_price: $("[name=target_price]", tr).value === "" ? null : Number($("[name=target_price]", tr).value),
      remark: $("[name=remark]", tr).value,
    }));
    const body = {
      customer_name: f.customer_name.value,
      contact_name: f.contact_name.value,
      phone: f.phone.value,
      email: f.email.value,
      currency: f.currency.value,
      requirement: f.requirement.value,
      lines,
    };
    if (inqId) await api("/api/inquiries/" + inqId, { method: "PATCH", json: body });
    else {
      const created = await api("/api/inquiries", { method: "POST", json: body });
      location.hash = "#/inquiries/" + created.id;
      return route();
    }
    location.hash = "#/inquiries/" + inqId;
    route();
  };
}

function sellingResultHtml(inq) {
  if (!(inq.can_win || inq.can_requote || inq.can_close || inq.audit_rejected) && inq.status !== "selling" && !inq.order_id) return "";
  const options = (inq.close_reason_options && inq.close_reason_options.length
    ? inq.close_reason_options
    : CLOSE_REASONS
  )
    .map((x) => `<option value="${esc(x)}">${esc(x)}</option>`)
    .join("");
  const hasActions = inq.can_win || inq.can_requote || inq.can_close || inq.order_id || inq.audit_rejected;
  if (!hasActions) return "";

  const rejectCard = inq.audit_rejected
    ? `<div class="panel advance-card">
        <h3>审核已驳回</h3>
        <p class="muted advance-desc">订单 ${esc(inq.audit_reject_order_no || "")} 已提交后被驳回，请按原因修改后重新提交审核。</p>
        <div class="req-block"><span>驳回原因</span>${esc(inq.audit_reject_remark || "未填写")}</div>
      </div>`
    : "";

  const winCard = inq.order_id && inq.order_status === "pending_audit"
    ? `<div class="panel advance-card">
        <h3>待管理员审核</h3>
        <p class="muted advance-desc">订单 ${esc(inq.order_no || "")} 已提交，审核通过后请填写销售订单</p>
        ${me.role === "admin" ? `<div class="row-actions"><a class="btn" href="#/orders/${inq.order_id}">去审核</a></div>` : ""}
      </div>`
    : inq.order_id && inq.order_status && inq.order_status !== "rejected"
    ? `<div class="panel advance-card">
        <h3>已生成订单</h3>
        <p class="muted advance-desc">订单 <a href="#/orders/${inq.order_id}">${esc(inq.order_no || "查看订单")}</a> 已审核通过，请到订单页填写合同；采购与财务将分线履约。</p>
        <div class="row-actions"><a class="btn" href="#/orders/${inq.order_id}">进入订单</a></div>
      </div>`
    : inq.can_win
      ? `<div class="panel advance-card">
        <h3>生成订单</h3>
        <p class="muted advance-desc">客户已接受当前选用报价时，提交管理员审核。通过后进入销售订单。</p>
        <div class="row-actions"><button type="button" id="win">提交审核</button></div>
      </div>`
      : "";

  const requoteCard = inq.can_requote
    ? `<div class="panel advance-card">
        <h3>二次询价</h3>
        <p class="muted advance-desc">价格偏高或交期不合适时，填写原因后回到待报价，采购再报一轮。历史报价会保留。</p>
        <form id="requote-form">
          <label class="advance-field">原因（必填）
            <textarea name="reason" required placeholder="例如：价格偏高，客户希望再报一轮"></textarea>
          </label>
          <div class="row-actions form-footer">
            <button type="submit" class="ghost">提交二次询价</button>
          </div>
        </form>
      </div>`
    : "";

  const closeCard = inq.can_close
    ? `<div class="panel advance-card advance-close">
        <h3>结束询价</h3>
        <p class="muted advance-desc">本单无法成交时结束流程，结束后不可再报价。</p>
        <form id="close-form">
          <div class="form-grid advance-close-grid">
            <label>结束原因（必填）
              <select name="reason" required>
                <option value="">请选择结束原因</option>
                ${options}
              </select>
            </label>
            <label><span id="close-detail-label">补充说明</span>
              <input name="detail" placeholder="选择「其他」时必填，例如客户未回复">
            </label>
          </div>
          <div class="row-actions form-footer">
            <button type="submit" class="danger">结束此询价单</button>
          </div>
        </form>
      </div>`
    : "";

  return `<div class="advance-stack">${rejectCard}${winCard}${requoteCard}${closeCard}</div>`;
}

function bindSellingActions(id) {
  if ($("#win")) {
    $("#win").onclick = async () => {
      if (!confirm("确认提交管理员审核？通过后才会进入销售订单。")) return;
      await api(`/api/inquiries/${id}/win`, { method: "POST" });
      viewInquiryDetail(id);
    };
  }
  const rf = $("#requote-form");
  if (rf) {
    rf.onsubmit = async (e) => {
      e.preventDefault();
      const reason = (rf.reason.value || "").trim();
      if (!reason) {
        alert("请填写二次询价原因");
        return;
      }
      if (!confirm("确认二次询价？状态将回到待报价，由采购重新报价。")) return;
      await api(`/api/inquiries/${id}/requote`, { method: "POST", json: { reason } });
      viewInquiryDetail(id);
    };
  }
  const form = $("#close-form");
  if (!form) return;
  const sel = form.reason;
  const detail = form.detail;
  const label = $("#close-detail-label");
  const syncOther = () => {
    const need = sel.value === "其他";
    detail.required = need;
    if (label) label.textContent = need ? "其他原因（必填）" : "补充说明";
    detail.placeholder = need
      ? "请填写具体原因，例如客户未回复"
      : "可补充说明";
  };
  sel.addEventListener("change", syncOther);
  syncOther();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const reason = sel.value.trim();
    const extra = (detail.value || "").trim();
    if (!reason) {
      alert("请选择结束原因");
      return;
    }
    if (reason === "其他" && !extra) {
      alert("选择「其他」时请填写具体原因");
      return;
    }
    if (!confirm("确认结束该询价单？结束后不可再报价。")) return;
    await api(`/api/inquiries/${id}/close`, { method: "POST", json: { reason, detail: extra } });
    viewInquiryDetail(id);
  };
}

async function viewInquiryDetail(id) {
  const inq = await api("/api/inquiries/" + id);
  pageTitle("询价单 " + inq.no);
  const lineMap = Object.fromEntries(inq.lines.map((l) => [l.id, l]));
  const requoteLog = inq.requote_log || [];
  const reasonByRound = Object.fromEntries(requoteLog.map((x) => [x.round, x]));
  const quotesHtml = inq.quotes.length
    ? inq.quotes
        .slice()
        .sort((a, b) => (b.round_no || 1) - (a.round_no || 1) || b.id - a.id)
        .map((q) => {
          const rows = q.lines
            .map((ql) => {
              const ln = lineMap[ql.inquiry_line_id] || {};
              return `<tr><td>${esc(ln.sku)} ${esc(ln.product_name)}</td><td>${ln.quantity}</td><td>${ql.unit_price}</td><td>${ql.amount}</td></tr>`;
            })
            .join("");
          const round = q.round_no || 1;
          const rr = reasonByRound[round];
          return `<div class="quote-box ${q.selected ? "selected" : ""}">
        <div class="quote-head">
          <div>
            <strong>第 ${round} 轮 · 报价 #${q.id}</strong>
            ${q.selected ? pill("won", "已选用") : ""}
          </div>
          <div class="quote-meta">
            <span>采购 <b>${esc(q.purchaser_name)}</b></span>
            <span>交期 <b>${q.lead_days} 天</b></span>
            <span>合计 <b>${q.total} ${esc(inq.currency)}</b></span>
            <span>${esc(q.created_at)}</span>
          </div>
        </div>
        ${rr ? `<p class="muted quote-note">本轮询价原因：${esc(rr.reason)}</p>` : ""}
        ${q.note ? `<p class="muted quote-note">${esc(q.note)}</p>` : ""}
        <div class="table-wrap"><table><thead><tr><th>产品</th><th>数量</th><th>单价</th><th>金额</th></tr></thead><tbody>${rows}</tbody></table></div>
        ${
          inq.can_select
            ? `<div class="row-actions form-footer"><button data-sel="${q.id}" ${q.selected ? "disabled" : ""}>${q.selected ? "已选用" : "选择此报价"}</button></div>`
            : ""
        }
      </div>`;
        })
        .join("")
    : `<p class="muted empty-hint">暂无采购报价</p>`;

  let quoteForm = "";
  if (inq.can_quote) {
    quoteForm = `<form id="quote-form" class="panel">
      <h3>提交报价${inq.quote_round > 1 ? ` · 第 ${inq.quote_round} 轮` : ""}</h3>
      ${
        inq.requote_reason
          ? `<div class="req-block"><span>销售二次询价原因</span>${esc(inq.requote_reason)}</div>`
          : `<p class="muted section-lead">先填写产品单价，交期和说明可选填。提交后销售即可选择报价。</p>`
      }
      <div class="table-wrap"><table><thead><tr><th>产品</th><th>数量</th><th>单价（${esc(inq.currency)}）</th></tr></thead>
      <tbody>
        ${inq.lines
          .map(
            (l) => `<tr>
            <td>${esc(l.sku)} ${esc(l.product_name)}</td><td>${l.quantity} ${esc(l.unit)}</td>
            <td class="col-price"><input name="price-${l.id}" type="number" step="0.01" min="0" required placeholder="必填"></td>
          </tr>`
          )
          .join("")}
      </tbody></table></div>
      <div class="form-grid inq-form" style="margin-top:18px">
        <label>交期（天）<input name="lead_days" type="number" value="15"></label>
        <label class="full">说明<textarea name="note" placeholder="选填"></textarea></label>
      </div>
      <div class="row-actions form-footer"><button type="submit">提交报价</button></div>
    </form>`;
  }

  $("#view").innerHTML = `
    <div class="inq-page">
    <div class="panel">
      <div class="detail-head">
        <h3>询价信息</h3>
        ${pill(inq.status, inq.status_label)}
      </div>
      <div class="kv kv-wide inq-kv">
        <div><span>单号</span><b>${esc(inq.no)}</b></div>
        <div><span>客户</span><b>${esc(inq.customer_name)}</b></div>
        <div><span>币种</span><b>${esc(inq.currency)}</b></div>
        <div><span>销售</span><b>${esc(inq.creator_name)}</b></div>
        <div><span>创建时间</span><b>${esc(inq.created_at)}</b></div>
        <div><span>询价轮次</span><b>第 ${inq.quote_round || 1} 轮</b></div>
        ${
          inq.order_id
            ? `<div><span>关联订单</span><b>${
                inq.can_open_order
                  ? `<a href="#/orders/${inq.order_id}">${esc(inq.order_no)}</a>`
                  : esc(inq.order_no)
              }</b></div>`
            : ""
        }
        <div><span>联系人</span><b>${esc(inq.contact_name) || "—"}</b></div>
        <div><span>电话</span><b>${esc(inq.phone) || "—"}</b></div>
        <div><span>邮箱</span><b>${esc(inq.email) || "—"}</b></div>
      </div>
      ${
        inq.requirement
          ? `<div class="req-block"><span>需求说明</span>${esc(inq.requirement)}</div>`
          : ""
      }
      ${
        inq.requote_reason && inq.status === "pending_quote"
          ? `<div class="req-block"><span>二次询价原因</span>${esc(inq.requote_reason)}</div>`
          : ""
      }
      ${
        inq.status === "selling" && !inq.order_id
          ? `<p class="muted section-lead">已选用报价，正在销售。可二次询价、生成订单，或结束本单。</p>`
          : ""
      }
      ${inq.close_reason ? `<div class="req-block"><span>结束原因</span>${esc(inq.close_reason)}</div>` : ""}
    </div>
    <div class="panel">
      <h3>产品明细</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>产品ID</th><th>产品</th><th>规格</th><th>数量</th><th>目标价</th></tr></thead>
        <tbody>
          ${inq.lines
            .map(
              (l) =>
                `<tr><td>${esc(l.sku)}</td><td>${esc(l.product_name)}</td><td>${esc(l.spec)}</td><td>${l.quantity} ${esc(l.unit)}</td><td>${l.target_price ?? ""}</td></tr>`
            )
            .join("")}
        </tbody>
      </table></div>
    </div>
    <div class="panel">
      <h3>采购报价</h3>
      <div class="quote-list">${quotesHtml}</div>
    </div>
    ${quoteForm}
    ${sellingResultHtml(inq)}
    ${
      inq.can_delete
        ? `<div class="panel"><div class="row-actions"><button class="danger" id="del-inq">删除询价单</button></div></div>`
        : ""
    }
    </div>`;

  $$("[data-sel]").forEach((b) => {
    b.onclick = async () => {
      await api(`/api/inquiries/${id}/select-quote`, { method: "POST", json: { quote_id: +b.dataset.sel } });
      viewInquiryDetail(id);
    };
  });
  const qf = $("#quote-form");
  if (qf) {
    qf.onsubmit = async (e) => {
      e.preventDefault();
      const lines = inq.lines.map((l) => ({
        inquiry_line_id: l.id,
        unit_price: Number(e.target[`price-${l.id}`].value),
      }));
      await api(`/api/inquiries/${id}/quotes`, {
        method: "POST",
        json: { note: e.target.note.value, lead_days: Number(e.target.lead_days.value || 0), lines },
      });
      location.hash = "#/inquiries";
      route();
    };
  }
  bindSellingActions(id);
  if ($("#del-inq")) {
    $("#del-inq").onclick = async () => {
      if (!confirm("确认删除该询价单？关联订单会一并删除。")) return;
      await api("/api/inquiries/" + id, { method: "DELETE" });
      location.hash = "#/inquiries";
      route();
    };
  }
}

async function viewOrders() {
  pageTitle("销售订单");
  const status = parseHash().params.get("status") || "";
  const rows = await api("/api/orders" + listFilterQs());
  $("#view").innerHTML = `
    <form class="toolbar page-toolbar">
      <select name="status">
        <option value="">全部状态</option>
        ${Object.entries(ORD)
          .map(([k, v]) => `<option value="${k}" ${k === status ? "selected" : ""}>${v}</option>`)
          .join("")}
      </select>
      ${dateRangeFields()}
      <button class="ghost" type="submit">筛选</button>
      ${me.role === "sales" ? `<a class="btn" href="#/orders/new">新建销售订单</a>` : ""}
    </form>
    <div class="table-wrap"><table>
      <thead><tr><th>单据日期</th><th>销售单号</th><th>客户</th><th>金额</th><th>当前状态</th><th>业务员</th><th>操作</th></tr></thead>
      <tbody>
        ${
          rows.length
            ? rows
                .map((r) => {
                  const del =
                    me.role === "admin"
                      ? ` <button class="danger" data-del-ord="${r.id}">删除</button>`
                      : "";
                  return `<tr>
            <td>${esc(r.doc_date || r.created_at || "")}</td>
            <td><a href="#/orders/${r.id}">${esc(r.no)}</a></td>
            <td>${esc(r.customer_name)}</td>
            <td>${fmtMoney(r.total)} ${esc(r.currency)}</td>
            <td>${pill(r.status, r.status_label)}</td>
            <td>${esc(r.sales_name)}</td>
            <td><a class="btn" href="#/orders/${r.id}">进入</a>${del}</td>
          </tr>`;
                })
                .join("")
            : `<tr><td colspan="7" class="empty-hint muted">暂无销售订单</td></tr>`
        }
      </tbody>
    </table></div>`;
  bindDocListFilter("#/orders");
  $$("[data-del-ord]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("确认删除该销售订单？")) return;
      await api("/api/orders/" + b.dataset.delOrd, { method: "DELETE" });
      viewOrders();
    };
  });
}

async function viewSalesOrderNew() {
  if (me.role !== "sales") {
    location.hash = "#/orders";
    return;
  }
  pageTitle("新建销售订单");
  const [, meta] = await Promise.all([loadProducts(true), api("/api/orders/meta")]);
  $("#view").innerHTML = soSheetHtml({}, meta);
  bindSoForm({
    meta,
    onDraft: async (payload) => {
      const created = await api("/api/orders", { method: "POST", json: payload });
      location.hash = "#/orders/" + created.id;
      route();
    },
    onSubmit: async (payload) => {
      const created = await api("/api/orders", { method: "POST", json: { ...payload, submit: true } });
      location.hash = "#/orders";
      route();
    },
  });
}

function soSheetHtml(o, meta) {
  const customers = meta.customers || [];
  const salespeople = meta.salespeople || [];
  const methods = (meta.settle_methods || []).map((m) => `<option ${m === (o.settle_method || "") ? "selected" : ""}>${esc(m)}</option>`).join("");
  const accounts = (meta.accounts || []).map((m) => `<option ${m === (o.pay_account || "") ? "selected" : ""}>${esc(m)}</option>`).join("");
  return `
    <form id="so-fill" class="po-sheet">
      <div class="voucher-toolbar">
        <a class="btn ghost" href="#/orders">放弃</a>
        <button type="button" class="ghost" id="so-draft">保存草稿</button>
        <button type="submit">提交审核</button>
      </div>
      <div class="panel voucher-head">
        <div class="voucher-type-row">
          <label class="radio"><input type="radio" name="voucher_type" value="sale" ${o.voucher_type !== "return" ? "checked" : ""}> 销售</label>
          <label class="radio"><input type="radio" name="voucher_type" value="return" ${o.voucher_type === "return" ? "checked" : ""}> 退货</label>
        </div>
        <div class="form-grid voucher-meta po-head-grid">
          <label>单据日期<input name="doc_date" type="date" required value="${esc(o.doc_date || meta.today || "")}"></label>
          <label>单据编号<input value="${esc(o.no || "保存后自动生成")}" readonly></label>
          <label>客户
            <input name="customer_name" list="so-customers" value="${esc(o.customer_name || "")}" placeholder="必填后才能提交">
            <datalist id="so-customers">${customers.map((s) => `<option value="${esc(s)}">`).join("")}</datalist>
          </label>
          <label>客户国家<input name="customer_country" value="${esc(o.customer_country || "")}" placeholder="如 德国"></label>
          <label>目标港口<input name="destination_port" value="${esc(o.destination_port || "")}" placeholder="如 Hamburg"></label>
          <label>项目<input name="project" value="${esc(o.project || "")}" placeholder="选填"></label>
          <label>业务员
            <select name="salesperson_id">
              <option value="">请选择</option>
              ${salespeople.map((u) => `<option value="${u.id}" ${String(o.salesperson_id || me.id) === String(u.id) ? "selected" : ""}>${esc(u.name)}</option>`).join("")}
            </select>
          </label>
          <label>预计交货<input name="expected_date" type="date" value="${esc(o.expected_date || "")}"></label>
          <label>税率%<input name="header_tax_rate" type="number" step="0.01" min="0" value="${o.header_tax_rate ?? 0}"></label>
          <label>币种<select name="currency">${["RMB", "USD", "EUR"].map((c) => `<option ${(o.currency || "RMB") === c ? "selected" : ""}>${c}</option>`).join("")}</select></label>
          <label class="full">备注<input name="order_remark" value="${esc(o.order_remark || "")}"></label>
        </div>
      </div>
      <div class="panel">
        <div class="toolbar alloc-toolbar">
          <input id="so-scan" placeholder="扫描录入：输入产品ID 回车加入明细" autocomplete="off">
          <button type="button" class="ghost" id="add-so-line">加一行</button>
        </div>
        ${soLinesTable(o.lines && o.lines.length ? o.lines : [{}])}
        <div class="po-pay-row">
          <label class="radio"><input type="checkbox" name="pay_deposit" ${o.pay_deposit ? "checked" : ""}> 一般性订金</label>
          <label>结算方式<select name="settle_method"><option value="">请选择</option>${methods}</select></label>
          <label>收款账号<select name="pay_account"><option value="">请选择</option>${accounts}</select></label>
          <label>订金<input name="deposit" type="number" step="0.01" min="0" value="${o.deposit ?? 0}"></label>
          <input type="hidden" name="freight" value="${o.freight ?? 0}">
          <input type="hidden" name="extra_tax" value="${o.extra_tax ?? 0}">
        </div>
        <div class="voucher-sum">
          <span>订单金额 <b id="so-order-amt">0.00</b></span>
          <span>整单订金 <b id="so-deposit-amt">0.00</b></span>
          <span>剩余金额 <b id="so-remain-amt">0.00</b></span>
        </div>
        <div class="po-status-bar muted">
          <span>本单上欠 <b>0.00</b></span>
          <span>本单欠款 <b id="so-debt">0.00</b></span>
          <span>此后应收 <b id="so-receivable">0.00</b></span>
          <span>商品种类 <b id="so-sku-count">0</b></span>
        </div>
      </div>
    </form>`;
}

function soLinesTable(lines) {
  const rows = lines.length ? lines : [{}];
  return `<div class="table-wrap"><table class="voucher-table po-line-table">
    <thead><tr>
      <th></th><th>条码</th><th>商品</th><th>规格</th><th>型号</th><th>备注</th>
      <th>单位</th><th>数量</th><th>单价</th><th>税率%</th><th>金额</th><th>可用量</th><th>供应商</th><th>赠品</th><th></th>
    </tr></thead>
    <tbody id="so-lines">${rows.map((l) => soLineRow(l)).join("")}</tbody>
    <tfoot><tr><td colspan="7" class="right">小计</td><td id="so-qty-sum">0</td><td colspan="2"></td><td id="so-goods">0.00</td><td colspan="4"></td></tr></tfoot>
  </table></div>`;
}

function soLineRow(ln = {}) {
  const opts = (productsCache || [])
    .map((p) => `<option value="${p.id}" ${String(p.id) === String(ln.product_id || "") ? "selected" : ""}>${esc(p.sku)} ${esc(p.name)}</option>`)
    .join("");
  return `<tr>
    <td class="col-idx"></td>
    <td><input name="barcode" value="${esc(ln.barcode || ln.sku || "")}"></td>
    <td class="col-product"><select name="product_id"><option value="">请选择</option>${opts}</select></td>
    <td><input name="spec" value="${esc(ln.spec || "")}"></td>
    <td><input name="model" value="${esc(ln.model || "")}"></td>
    <td><input name="line_remark" value="${esc(ln.line_remark || "")}"></td>
    <td class="col-qty"><input name="unit" value="${esc(ln.unit || "pcs")}"></td>
    <td class="col-qty"><input name="quantity" type="number" step="0.01" min="0" value="${ln.quantity ?? 1}"></td>
    <td class="col-price"><input name="unit_price" type="number" step="0.01" min="0" value="${ln.unit_price ?? 0}"></td>
    <td class="col-qty"><input name="tax_rate" type="number" step="0.01" min="0" value="${ln.tax_rate ?? 0}"></td>
    <td class="so-amt">0.00</td>
    <td class="muted">—</td>
    <td><input name="supplier_name" value="${esc(ln.supplier_name || "")}"></td>
    <td><input type="checkbox" name="is_gift" ${ln.is_gift ? "checked" : ""}></td>
    <td class="row-actions"><button type="button" class="ghost ins-line">+</button><button type="button" class="ghost rm-line">删除</button></td>
  </tr>`;
}

function collectSoPayload(form) {
  const headerRate = Number(form.header_tax_rate.value) || 0;
  const lines = $$("#so-lines tr")
    .map((tr) => ({
      product_id: $("[name=product_id]", tr).value ? Number($("[name=product_id]", tr).value) : null,
      sku: $("[name=barcode]", tr).value,
      barcode: $("[name=barcode]", tr).value,
      spec: $("[name=spec]", tr).value,
      model: $("[name=model]", tr).value,
      line_remark: $("[name=line_remark]", tr).value,
      unit: $("[name=unit]", tr).value,
      quantity: Number($("[name=quantity]", tr).value),
      unit_price: Number($("[name=unit_price]", tr).value) || 0,
      tax_rate: Number($("[name=tax_rate]", tr).value) || 0,
      supplier_name: $("[name=supplier_name]", tr).value,
      is_gift: $("[name=is_gift]", tr).checked,
    }))
    .filter((l) => l.quantity > 0 && (l.product_id || l.barcode));
  return {
    voucher_type: form.voucher_type.value,
    customer_name: form.customer_name.value,
    customer_country: form.customer_country?.value || "",
    currency: form.currency.value,
    doc_date: form.doc_date.value || null,
    project: form.project.value,
    salesperson_id: form.salesperson_id.value ? Number(form.salesperson_id.value) : null,
    expected_date: form.expected_date.value || null,
    header_tax_rate: headerRate,
    order_remark: form.order_remark.value,
    destination_port: form.destination_port?.value || "",
    freight: Number(form.freight.value) || 0,
    extra_tax: Number(form.extra_tax.value) || 0,
    deposit: Number(form.deposit.value) || 0,
    settle_method: form.settle_method.value,
    pay_account: form.pay_account.value,
    pay_deposit: form.pay_deposit.checked,
    lines,
  };
}

function recalcSoLines() {
  let goods = 0;
  let qtySum = 0;
  let kinds = 0;
  $$("#so-lines tr").forEach((tr, i) => {
    const idx = tr.querySelector(".col-idx");
    if (idx) idx.textContent = i + 1;
    const qty = Number($("[name=quantity]", tr).value) || 0;
    const price = Number($("[name=unit_price]", tr).value) || 0;
    const rate = Number($("[name=tax_rate]", tr).value) || 0;
    const gift = $("[name=is_gift]", tr).checked;
    const amt = gift ? 0 : Math.round(qty * price * (1 + rate / 100) * 100) / 100;
    const cell = $(".so-amt", tr);
    if (cell) cell.textContent = amt.toFixed(2);
    goods += amt;
    qtySum += qty;
    if ($("[name=product_id]", tr).value || $("[name=barcode]", tr).value) kinds += 1;
  });
  const deposit = Number($("#so-fill [name=deposit]")?.value) || 0;
  const payNow = $("#so-fill [name=pay_deposit]")?.checked;
  const remain = Math.round((goods - deposit) * 100) / 100;
  const set = (id, v) => {
    const el = $(id);
    if (el) el.textContent = typeof v === "number" ? v.toFixed(2) : v;
  };
  set("#so-goods", goods);
  set("#so-qty-sum", qtySum);
  set("#so-order-amt", goods);
  set("#so-deposit-amt", deposit);
  set("#so-remain-amt", remain);
  set("#so-debt", remain);
  set("#so-receivable", remain);
  const c = $("#so-sku-count");
  if (c) c.textContent = String(kinds);
}

function bindSoForm({ meta = {}, onDraft, onSubmit }) {
  const form = $("#so-fill");
  const fillFromProduct = (tr, pid) => {
    const p = (productsCache || []).find((x) => String(x.id) === String(pid));
    if (!p || !tr) return;
    $("[name=barcode]", tr).value = p.sku || "";
    $("[name=spec]", tr).value = p.spec || "";
    $("[name=unit]", tr).value = p.unit || "pcs";
    const rate = Number(form.header_tax_rate.value) || 0;
    if (!$("[name=tax_rate]", tr).value || Number($("[name=tax_rate]", tr).value) === 0) $("[name=tax_rate]", tr).value = rate;
  };
  const addRow = (ln, after) => {
    const html = soLineRow(ln || {});
    if (after) after.insertAdjacentHTML("afterend", html);
    else $("#so-lines").insertAdjacentHTML("beforeend", html);
    recalcSoLines();
  };
  $("#add-so-line").onclick = () => addRow();
  const scan = $("#so-scan");
  if (scan) {
    scan.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const q = scan.value.trim().toLowerCase();
      if (!q) return;
      const p = (productsCache || []).find((x) => String(x.sku).toLowerCase() === q || String(x.name).toLowerCase().includes(q));
      if (!p) {
        alert("未找到产品：" + scan.value);
        return;
      }
      const rate = Number(form.header_tax_rate.value) || 0;
      addRow({ product_id: p.id, barcode: p.sku, spec: p.spec, unit: p.unit, quantity: 1, unit_price: 0, tax_rate: rate });
      fillFromProduct($$("#so-lines tr").slice(-1)[0], p.id);
      scan.value = "";
    };
  }
  form.addEventListener("click", (e) => {
    if (e.target.classList.contains("rm-line")) {
      if ($$("#so-lines tr").length > 1) e.target.closest("tr").remove();
      recalcSoLines();
    }
    if (e.target.classList.contains("ins-line")) addRow({}, e.target.closest("tr"));
  });
  form.addEventListener("input", (e) => {
    if (["quantity", "unit_price", "tax_rate", "deposit", "header_tax_rate"].includes(e.target.name)) recalcSoLines();
  });
  form.addEventListener("change", (e) => {
    if (e.target.name === "product_id") fillFromProduct(e.target.closest("tr"), e.target.value);
    if (e.target.name === "header_tax_rate") {
      const rate = Number(e.target.value) || 0;
      $$("#so-lines [name=tax_rate]").forEach((el) => {
        if (!el.value || Number(el.value) === 0) el.value = rate;
      });
    }
    recalcSoLines();
  });
  if ($("#so-draft") && onDraft)
    $("#so-draft").onclick = async () => {
      try {
        await onDraft(collectSoPayload(form));
      } catch (err) {
        alert(err.message || "保存失败");
      }
    };
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      await onSubmit(collectSoPayload(e.target));
    } catch (err) {
      alert(err.message || "提交失败");
    }
  };
  recalcSoLines();
}

function orderInfoPanel(o) {
  const pos = o.purchase_orders || [];
  const poHtml = pos.length
    ? pos
        .map((p) => `<a href="#/purchase-orders/${p.id}">${esc(p.no)}</a>（${esc(PO[p.status] || p.status)}）`)
        .join("、")
    : "—";
  const val = (v) => (v ? esc(v) : "—");
  return `
    <div class="panel order-sheet">
      <h3>订单信息</h3>
      <div class="kv order-kv">
        <div><span>订单号</span><b>${esc(o.no)}</b></div>
        <div><span>客户</span><b>${val(o.customer_name)}</b></div>
        <div><span>客户国家</span><b>${val(o.customer_country)}</b></div>
        <div><span>币种</span><b>${esc(o.currency)}</b></div>
        <div><span>成交金额</span><b>${fmtMoney(o.order_amount ?? o.quote_total)}</b></div>
        <div><span>交易方式</span><b>${val(o.incoterm)}</b></div>
        <div><span>装运港</span><b>${val(o.loading_port)}</b></div>
        <div><span>目标港口</span><b>${val(o.destination_port)}</b></div>
        <div><span>付款条款</span><b>${val(o.payment_terms)}</b></div>
        <div><span>合同编号</span><b>${val(o.contract_no)}</b></div>
        <div><span>合同日期</span><b>${val(o.contract_date)}</b></div>
        ${o.expected_date ? `<div><span>预计交货</span><b>${esc(o.expected_date)}</b></div>` : ""}
        ${o.project ? `<div><span>项目</span><b>${esc(o.project)}</b></div>` : ""}
        ${o.factory_address ? `<div><span>交货地址</span><b>${esc(o.factory_address)}</b></div>` : ""}
      </div>
      ${o.contract_remark ? `<p class="order-note">合同备注：${esc(o.contract_remark)}</p>` : ""}
      ${o.audit_remark ? `<p class="order-note muted">审核说明：${esc(o.audit_remark)}</p>` : ""}
      <div class="table-wrap order-lines"><table>
        <thead><tr><th>条码</th><th>商品</th><th>规格</th><th>型号</th><th>数量</th><th>单价</th><th>税率</th><th>金额</th><th>赠品</th></tr></thead>
        <tbody>
          ${o.lines
            .map(
              (l) =>
                `<tr><td>${esc(l.barcode || l.sku)}</td><td>${esc(l.product_name)}</td><td>${esc(l.spec)}</td><td>${esc(l.model || "")}</td><td>${l.quantity} ${esc(l.unit)}</td><td>${fmtMoney(l.unit_price)}</td><td>${fmtMoney(l.tax_rate)}%</td><td>${fmtMoney(l.amount)}</td><td>${l.is_gift ? "是" : ""}</td></tr>`
            )
            .join("")}
        </tbody>
      </table></div>
      <div class="order-relate">
        <h4>关联信息</h4>
        <div class="kv order-relate-kv">
          <div><span>销售</span><b>${val(o.sales_name)}</b></div>
          <div><span>关联询价单</span><b>${o.inquiry_id ? `<a href="#/inquiries/${o.inquiry_id}">${esc(o.inquiry_no)}</a>` : "—"}</b></div>
          <div><span>关联采购单</span><b>${poHtml}</b></div>
        </div>
      </div>
    </div>`;
}

function flowDiagram(o) {
  const idx = o.steps.findIndex((s) => s.key === o.status);
  return `<div class="flow-track">
    ${o.steps
      .map((s, i) => {
        const cls = i < idx ? "done" : i === idx ? "current" : "todo";
        const state = i < idx ? "已完成" : i === idx ? "进行中" : "未开始";
        return `<div class="flow-item ${cls}">
          <div class="flow-dot">${i + 1}</div>
          ${i < o.steps.length - 1 ? `<div class="flow-bar ${i < idx ? "on" : ""}"></div>` : ""}
          <div class="flow-name">${esc(s.label)}</div>
          <div class="flow-state">${state}</div>
        </div>`;
      })
      .join("")}
  </div>`;
}

function stageFormHtml(o) {
  const back = `<a class="btn ghost" href="#/orders">返回销售订单</a>`;
  if (o.can_audit) {
    return `<form id="audit-form" class="panel">
      <h3>管理员审核</h3>
      <p class="muted advance-desc">通过后该单出现在销售订单，销售可按交易方式填写合同。</p>
      <label class="advance-field">审核说明<textarea name="remark" placeholder="驳回时必填"></textarea></label>
      <div class="row-actions form-footer">
        <button type="button" id="audit-pass">审核通过</button>
        <button type="button" class="danger" id="audit-reject">驳回</button>
        ${back}
      </div>
    </form>`;
  }
  if (o.status === "contract" && me.role === "sales") {
    const t = o.incoterm || "FOB";
    return `<form id="c-form" class="panel" novalidate>
      <h3>填写合同</h3>
      <p class="muted advance-desc">按报价交易方式填写。提交后进入履约：采购走采购订单，财务走资金管理。</p>
      <div class="form-grid contract-form">
        <label>合同编号（必填）<input name="contract_no" required placeholder="例如 HT-2026-001"></label>
        <label>合同日期（必填）<input name="contract_date" type="date" required></label>
        <label>交易方式（必填）
          <select name="incoterm" id="incoterm" required>
            ${INCOTERMS.map((x) => `<option ${x === t ? "selected" : ""}>${x}</option>`).join("")}
          </select>
        </label>
        <label>客户国家（必填）<input name="customer_country" required value="${esc(o.customer_country || "")}" placeholder="如 德国 / United States"></label>
        <label id="f-dest">目标港口（必填）<input name="destination_port" required value="${esc(o.destination_port || "")}" placeholder="如 Hamburg / Los Angeles"></label>
        <label>付款条款<input name="payment_terms" value="${esc(o.payment_terms || "")}" placeholder="如 30% 定金，见提单付余款"></label>
        <label id="f-load">装运港<input name="loading_port" value="${esc(o.loading_port || "")}"></label>
        <label id="f-exw" class="full">工厂/仓库地址<input name="factory_address" value="${esc(o.factory_address || "")}"></label>
        <label class="full">合同备注<textarea name="contract_remark">${esc(o.contract_remark || "")}</textarea></label>
      </div>
      <div class="row-actions form-footer">
        <button type="submit">提交合同，开始履约</button>
        ${back}
      </div>
    </form>`;
  }
  if (o.status === "fulfilling") {
    return "";
  }
  if (o.status === "done") {
    return `<div class="panel"><h3>完成</h3><p class="muted">订单已完成。</p>${back}</div>`;
  }
  return `<div class="panel"><p class="muted">${me.role === "admin" ? "管理员可审核、查询和删除。" : "当前节点由对应角色办理。"}</p>
    ${me.role === "admin" ? `<button class="danger" id="del-ord">删除订单</button> ` : ""}
    ${back}</div>`;
}

function incotermNeedFields(term) {
  const v = (term || "").toUpperCase();
  return {
    needLoad: ["FOB", "CFR", "CIF", "FCA"].includes(v),
    needDest: ["CIF", "CFR", "CIP", "CPT", "DAP", "DPU", "DDP"].includes(v),
    needExw: v === "EXW",
  };
}

function syncIncotermFields() {
  const v = $("#incoterm")?.value;
  if (!v) return;
  const { needLoad, needDest, needExw } = incotermNeedFields(v);
  const loadLab = $("#f-load");
  const destLab = $("#f-dest");
  const exwLab = $("#f-exw");
  if (loadLab) {
    loadLab.style.display = needLoad || needDest ? "" : "none";
    loadLab.firstChild.textContent = needLoad ? "装运港（必填）" : "装运港";
    const inp = loadLab.querySelector("input");
    if (inp) inp.required = needLoad;
  }
  if (destLab) {
    destLab.style.display = "";
    destLab.firstChild.textContent = "目标港口（必填）";
    const inp = destLab.querySelector("input");
    if (inp) inp.required = true;
  }
  if (exwLab) {
    exwLab.style.display = needExw ? "" : "none";
    exwLab.firstChild.textContent = needExw ? "工厂/仓库地址（必填）" : "工厂/仓库地址";
    const inp = exwLab.querySelector("input");
    if (inp) inp.required = needExw;
  }
}

function validateContractForm(form) {
  const term = (form.incoterm?.value || "").trim().toUpperCase();
  const { needLoad, needExw } = incotermNeedFields(term);
  const checks = [
    [form.contract_no, "合同编号"],
    [form.contract_date, "合同日期"],
    [form.incoterm, "交易方式"],
    [form.customer_country, "客户国家"],
    [form.destination_port, "目标港口"],
  ];
  if (needLoad) checks.push([form.loading_port, "装运港"]);
  if (needExw) checks.push([form.factory_address, "工厂/仓库地址"]);
  const missing = [];
  let firstEmpty = null;
  for (const [el, name] of checks) {
    if (!(el?.value || "").trim()) {
      missing.push(name);
      if (!firstEmpty) firstEmpty = el;
    }
  }
  if (missing.length) {
    alert("请填写必填项：" + missing.join("、"));
    firstEmpty?.focus();
    return false;
  }
  return true;
}

function groupPoLogs(logs) {
  const items = [];
  const pending = [];
  let lastProgress = null;
  for (const lg of logs || []) {
    if (lg.kind === "logistics") {
      if (lastProgress) lastProgress.logistics.push(lg);
      else pending.push(lg);
      continue;
    }
    const item = { lg, logistics: [] };
    items.push(item);
    if (lg.to_status === "in_progress") {
      lastProgress = item;
      if (pending.length) {
        lastProgress.logistics.push(...pending);
        pending.length = 0;
      }
    }
  }
  if (pending.length && lastProgress) lastProgress.logistics.push(...pending);
  else if (pending.length && items.length) items[items.length - 1].logistics.push(...pending);
  return items;
}

function poLogisticsNestedHtml(list) {
  if (!list || !list.length) return "";
  return `<div class="tl-nested">
    <p class="tl-nested-label">物流更新</p>
    ${list
      .map(
        (lg) => `<div class="tl-logi">
          <div class="tl-title">物流 ${esc(lg.logistics_company || "")} ${esc(lg.tracking_no || "")}</div>
          <div class="tl-meta"><span>${esc(lg.created_at)}</span><span>${esc(lg.operator || "—")}</span></div>
          <div class="kv kv-wide" style="margin-top:8px">
            <div><span>物流公司</span><b>${esc(lg.logistics_company) || "—"}</b></div>
            <div><span>运单号</span><b>${esc(lg.tracking_no) || "—"}</b></div>
          </div>
          ${lg.comment ? `<p class="tl-comment">${esc(lg.comment)}</p>` : ""}
        </div>`
      )
      .join("")}
  </div>`;
}

function timelineCardHtml(title, metaHtml, bodyHtml) {
  const body = (bodyHtml || "").trim() || `<p class="muted tl-comment">无补充说明</p>`;
  return `<div class="tl-card">
    <button type="button" class="tl-acc-head" aria-expanded="false">
      <span class="tl-acc-main">
        <span class="tl-title">${title}</span>
        <span class="tl-meta">${metaHtml}</span>
      </span>
      <span class="po-acc-chevron" aria-hidden="true">▾</span>
    </button>
    <div class="tl-acc-body" hidden>${body}</div>
  </div>`;
}

function bindTimelineAccordions() {
  $$(".tl-acc-head").forEach((btn) => {
    btn.onclick = () => {
      const card = btn.closest(".tl-card");
      const body = card.querySelector(".tl-acc-body");
      const open = card.classList.toggle("is-open");
      body.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    };
  });
}

async function viewOrderDetail(id) {
  const o = await api("/api/orders/" + id);
  pageTitle("销售订单 " + o.no);
  if (o.can_fill) {
    const meta = await api("/api/orders/meta");
    await loadProducts(true);
    $("#view").innerHTML = soSheetHtml(o, meta);
    bindSoForm({
      meta,
      onDraft: async (payload) => {
        await api(`/api/orders/${id}/save`, { method: "POST", json: payload });
        viewOrderDetail(id);
      },
      onSubmit: async (payload) => {
        await api(`/api/orders/${id}/submit`, { method: "POST", json: payload });
        location.hash = "#/orders";
        route();
      },
    });
    return;
  }
  $("#view").innerHTML = `
    <div class="panel flow-panel">
      <div class="flow-head">
        <h3>订单状态流转</h3>
        <span class="pill ${o.status}">当前：${esc(o.status_label)}</span>
      </div>
      ${flowDiagram(o)}
    </div>
    ${orderInfoPanel(o)}
    ${stageFormHtml(o)}
    <div class="panel">
      <h3>流转记录</h3>
      ${
        (o.logs || []).filter((lg) => !(lg.from_status === "pending_audit" && lg.to_status === "contract")).length
          ? `<ol class="timeline">
              ${o.logs
                .filter((lg) => !(lg.from_status === "pending_audit" && lg.to_status === "contract"))
                .map(
                  (lg) => `<li>
                    <div class="tl-dot"></div>
                    ${timelineCardHtml(
                      esc(lg.to_label),
                      `<span>${esc(lg.created_at)}</span><span>${esc(lg.operator)}</span><span>${esc(lg.role_label || "")}</span>`,
                      lg.comment ? `<div class="tl-comment">${esc(lg.comment)}</div>` : ""
                    )}
                  </li>`
                )
                .join("")}
            </ol>`
          : `<p class="muted">暂无流转记录</p>`
      }
    </div>`;
  if ($("#incoterm")) {
    $("#incoterm").onchange = syncIncotermFields;
    syncIncotermFields();
  }
  if ($("#c-form")) {
    $("#c-form").onsubmit = async (e) => {
      e.preventDefault();
      if (!validateContractForm(e.target)) return;
      try {
        await api("/api/orders/" + id + "/submit-contract", { method: "POST", body: new FormData(e.target) });
        viewOrderDetail(id);
      } catch (err) {
        alert(err.message || "提交失败");
      }
    };
  }
  if ($("#audit-pass")) {
    $("#audit-pass").onclick = async () => {
      const remark = $("#audit-form textarea[name=remark]")?.value || "";
      await api("/api/orders/" + id + "/audit", { method: "POST", json: { action: "pass", remark } });
      viewOrderDetail(id);
    };
  }
  if ($("#audit-reject")) {
    $("#audit-reject").onclick = async () => {
      const remark = ($("#audit-form textarea[name=remark]")?.value || "").trim();
      if (!remark) {
        alert("请填写驳回原因");
        return;
      }
      if (!confirm("驳回后销售可在询价单查看原因并重新提交审核。")) return;
      await api("/api/orders/" + id + "/audit", { method: "POST", json: { action: "reject", remark } });
      location.hash = "#/orders?status=pending_audit";
      route();
    };
  }
  if ($("#del-ord")) {
    $("#del-ord").onclick = async () => {
      if (!confirm("确认删除该订单？")) return;
      await api("/api/orders/" + id, { method: "DELETE" });
      location.hash = "#/orders";
      route();
    };
  }
  bindTimelineAccordions();
}
async function viewPurchaseOrders() {
  pageTitle("采购订单");
  const status = parseHash().params.get("status") || "";
  const rows = await api("/api/purchase-orders" + listFilterQs());
  $("#view").innerHTML = `
    <form class="toolbar page-toolbar">
      <select name="status">
        <option value="">全部状态</option>
        ${Object.entries(PO).map(([k, v]) => `<option value="${k}" ${k === status ? "selected" : ""}>${v}</option>`).join("")}
      </select>
      ${dateRangeFields()}
      <button class="ghost" type="submit">筛选</button>
      ${me.role === "purchase" ? `<a class="btn" href="#/purchase-orders/new">新建采购单</a>` : ""}
    </form>
    <div class="table-wrap"><table>
      <thead><tr><th>单据日期</th><th>采购单号</th><th>供应商</th><th>业务员</th><th>销售订单</th><th>金额</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>
        ${
          rows.length
            ? rows.map((r) => `<tr>
                <td>${esc(r.doc_date || r.created_at || "")}</td>
                <td><a href="#/purchase-orders/${r.id}">${esc(r.no)}</a></td>
                <td>${esc(r.supplier_name) || "—"}</td>
                <td>${esc(r.purchaser_name || r.creator_name)}</td>
                <td>${
                  r.sales_order_id
                    ? `<a href="#/orders/${r.sales_order_id}">${esc(r.sales_order_no)}</a>`
                    : "—"
                }</td>
                <td>${fmtMoney(r.total)} ${esc(r.currency)}</td>
                <td>${pill(r.status, r.status_label)}</td>
                <td><a class="btn" href="#/purchase-orders/${r.id}">进入</a>${
                  r.can_delete ? ` <button class="danger" data-del-po="${r.id}">删除</button>` : ""
                }</td>
              </tr>`).join("")
            : `<tr><td colspan="8" class="empty-hint muted">暂无采购单</td></tr>`
        }
      </tbody>
    </table></div>`;
  bindDocListFilter("#/purchase-orders");
  $$("[data-del-po]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("确认删除该采购单？关联的仅指向本单的付款单会一并删除。")) return;
      try {
        await api("/api/purchase-orders/" + b.dataset.delPo, { method: "DELETE" });
        viewPurchaseOrders();
      } catch (err) {
        alert(err.message || "删除失败");
      }
    };
  });
}

async function viewPurchaseOrderNew() {
  if (me.role !== "purchase") {
    location.hash = "#/purchase-orders";
    return;
  }
  pageTitle("新建采购单");
  await loadProducts(true);
  let orders = [];
  try {
    orders = await api("/api/orders");
  } catch {
    orders = [];
  }
  const meta = await api("/api/purchase-orders/meta");
  $("#view").innerHTML = poSheetHtml({}, orders, meta, true);
  bindPoForm({
    orders,
    meta,
    onDraft: async (payload) => {
      const created = await api("/api/purchase-orders", { method: "POST", json: payload });
      location.hash = "#/purchase-orders/" + created.id;
      route();
    },
    onSubmit: async (payload) => {
      const created = await api("/api/purchase-orders", { method: "POST", json: { ...payload, submit: true } });
      location.hash = "#/purchase-orders/" + created.id;
      route();
    },
  });
}

function poSheetHtml(o, orders, meta, isNew) {
  return `
    <form id="po-fill" class="po-sheet">
      ${o.audit_remark ? `<p class="muted">上次审核意见：${esc(o.audit_remark)}</p>` : ""}
      <div class="voucher-toolbar">
        <a class="btn ghost" href="#/purchase-orders">放弃</a>
        <button type="button" class="ghost" id="po-draft">保存草稿</button>
        <button type="submit">提交审核</button>
      </div>
      <div class="panel voucher-head">
        ${poHeaderFields(o, orders, meta, isNew)}
      </div>
      <div class="panel">
        <div class="toolbar alloc-toolbar">
          <button type="button" class="ghost" id="add-po-line">加一行</button>
        </div>
        ${poLinesTable(o.lines && o.lines.length ? o.lines : [{}])}
        ${poFooterHtml(o, meta)}
      </div>
    </form>`;
}

function poHeaderFields(o = {}, orders = [], meta = {}, isNew = false) {
  const sid = o.sales_order_id || "";
  const purchasers = (meta.purchasers || []).filter((u) => me.role !== "purchase" || String(u.id) === String(me.id));
  const today = meta.today || "";
  const selectedPurchaser = o.purchaser_id || (me.role === "purchase" ? me.id : "");
  return `<div class="form-grid voucher-meta po-head-grid">
    <label>单据日期<input name="doc_date" type="date" required value="${esc(o.doc_date || today)}"></label>
    <label>单据编号<input value="${esc(o.no || "保存后自动生成")}" readonly></label>
    <label>供应商
      <input name="supplier_name" value="${esc(o.supplier_name || "")}" placeholder="手动填写" autocomplete="off">
    </label>
    <label>开户行<input name="supplier_bank" value="${esc(o.supplier_bank || "")}" placeholder="对方公司开户行" autocomplete="off"></label>
    <label>账号<input name="supplier_account" value="${esc(o.supplier_account || "")}" placeholder="对方公司账号" autocomplete="off"></label>
    <label>业务员
      <select name="purchaser_id" ${me.role === "purchase" ? "disabled" : ""}>
        <option value="">请选择</option>
        ${purchasers.map((u) => `<option value="${u.id}" ${String(selectedPurchaser) === String(u.id) ? "selected" : ""}>${esc(u.name)}</option>`).join("")}
      </select>
      ${me.role === "purchase" ? `<input type="hidden" name="purchaser_id" value="${esc(me.id)}">` : ""}
    </label>
    <label>选单（销售订单）
      <select name="sales_order_id" id="po-so">
        <option value="">不关联</option>
        ${orders
          .map((ord) => `<option value="${ord.id}" ${String(ord.id) === String(sid) ? "selected" : ""}>${esc(ord.no)} · ${esc(ord.customer_name)}</option>`)
          .join("")}
      </select>
    </label>
    <label>项目<input name="project" value="${esc(o.project || "")}" placeholder="选填"></label>
    <label>联系人<input name="contact_name" value="${esc(o.contact_name || "")}"></label>
    <label>联系电话<input name="contact_phone" value="${esc(o.contact_phone || "")}"></label>
    <label>交货时间<input name="expected_date" type="date" required value="${esc(o.expected_date || "")}"></label>
    <label>发货仓库<input name="shipping_warehouse" value="${esc(o.shipping_warehouse || "")}" placeholder="手动填写"></label>
    <label>币种<select name="currency">
      ${["RMB", "USD", "EUR"].map((c) => `<option ${ (o.currency || "RMB") === c ? "selected" : ""}>${c}</option>`).join("")}
    </select></label>
    <label>运费<input name="freight" type="number" step="0.01" min="0" value="${o.freight ?? 0}"></label>
    <label>税费<input name="extra_tax" type="number" step="0.01" min="0" value="${o.extra_tax ?? 0}"></label>
    <label class="full">备注<input name="remark" value="${esc(o.remark || "")}"></label>
    <input type="hidden" name="payment_terms" value="${esc(o.payment_terms || "")}">
  </div>`;
}

function poLinesTable(lines) {
  const rows = lines.length ? lines : [{}];
  return `<div class="table-wrap"><table class="voucher-table po-line-table">
    <thead><tr>
      <th></th><th>商品</th><th>采购单位</th><th>数量</th><th>单价</th><th>金额</th><th></th>
    </tr></thead>
    <tbody id="po-lines">${rows.map((l) => poLineRow(l)).join("")}</tbody>
  </table></div>`;
}

function poLineRow(ln = {}) {
  return `<tr>
    <td class="col-idx"></td>
    <td class="col-product">
      <input type="hidden" name="product_id" value="${ln.product_id || ""}">
      <input name="product_name" value="${esc(ln.product_name || "")}" autocomplete="off">
    </td>
    <td class="col-qty"><input name="unit" value="${esc(ln.unit || "pcs")}" placeholder="单位"></td>
    <td class="col-qty"><input name="quantity" type="number" step="0.01" min="0" value="${ln.quantity ?? 1}"></td>
    <td class="col-price"><input name="unit_price" type="number" step="0.01" min="0" value="${ln.unit_price ?? ""}" placeholder="0.00"></td>
    <td class="po-amt">0.00</td>
    <td class="row-actions"><button type="button" class="ghost rm-line">删除</button></td>
  </tr>`;
}

function poPayModeIsFull(o = {}) {
  const orderAmt = Number(o.order_amount ?? o.total) || 0;
  const deposit = Number(o.deposit) || 0;
  return Boolean(o.pay_deposit) && orderAmt > 0 && deposit >= orderAmt - 0.005;
}

function poFooterHtml(o = {}) {
  const isFull = poPayModeIsFull(o);
  return `
    <div class="po-pay-split">
      <div class="po-pay-block">
        <label class="radio"><input type="radio" name="pay_mode" value="deposit" ${isFull ? "" : "checked"}> 订金</label>
        <label>订金金额<input name="deposit" type="number" step="0.01" min="0" value="${isFull ? 0 : o.deposit ?? 0}" ${isFull ? "disabled" : ""}></label>
      </div>
      <div class="po-pay-block">
        <label class="radio"><input type="radio" name="pay_mode" value="full" ${isFull ? "checked" : ""}> 全部</label>
        <p class="muted">按订单金额一次付清</p>
      </div>
    </div>
    <div class="voucher-sum">
      <span>订单金额 <b id="po-order-amt">0.00</b></span>
      <span>订金 <b id="po-deposit-amt">0.00</b></span>
      <span>剩余金额 <b id="po-remain-amt">0.00</b></span>
    </div>`;
}

function collectPoPayload(form) {
  const lines = $$("#po-lines tr")
    .map((tr) => ({
      product_id: $("[name=product_id]", tr).value ? Number($("[name=product_id]", tr).value) : null,
      product_name: ($("[name=product_name]", tr)?.value || "").trim(),
      unit: $("[name=unit]", tr).value,
      warehouse: "",
      quantity: Number($("[name=quantity]", tr).value),
      unit_price: Number($("[name=unit_price]", tr).value) || 0,
      tax_rate: 0,
    }))
    .filter((l) => l.quantity > 0 && (l.product_id || l.product_name));
  const goods = lines.reduce((s, l) => s + Math.round(l.quantity * l.unit_price * 100) / 100, 0);
  const freight = Number(form.freight.value) || 0;
  const extra = Number(form.extra_tax.value) || 0;
  const orderAmt = Math.round((goods + freight + extra) * 100) / 100;
  const payMode = form.pay_mode?.value || "deposit";
  const deposit = payMode === "full" ? orderAmt : Number(form.deposit?.value) || 0;
  return {
    sales_order_id: form.sales_order_id.value ? Number(form.sales_order_id.value) : null,
    supplier_name: form.supplier_name.value,
    supplier_bank: form.supplier_bank?.value || "",
    supplier_account: form.supplier_account?.value || "",
    contact_name: form.contact_name.value,
    contact_phone: form.contact_phone.value,
    payment_terms: form.payment_terms.value,
    expected_date: form.expected_date.value || null,
    shipping_warehouse: form.shipping_warehouse?.value || "",
    currency: form.currency.value,
    remark: form.remark.value,
    doc_date: form.doc_date.value || null,
    purchaser_id: form.purchaser_id.value ? Number(form.purchaser_id.value) : null,
    project: form.project.value,
    freight,
    extra_tax: extra,
    deposit,
    settle_method: "",
    pay_account: "",
    pay_deposit: payMode === "full" || deposit > 0,
    lines,
  };
}

function recalcPoLines() {
  let goods = 0;
  let qtySum = 0;
  $$("#po-lines tr").forEach((tr, i) => {
    const idx = tr.querySelector(".col-idx");
    if (idx) idx.textContent = i + 1;
    const qty = Number($("[name=quantity]", tr).value) || 0;
    const price = Number($("[name=unit_price]", tr).value) || 0;
    const amt = Math.round(qty * price * 100) / 100;
    const cell = $(".po-amt", tr);
    if (cell) cell.textContent = amt.toFixed(2);
    goods += amt;
    qtySum += qty;
  });
  const freight = Number($("#po-fill [name=freight]")?.value) || 0;
  const extra = Number($("#po-fill [name=extra_tax]")?.value) || 0;
  const payMode = $("#po-fill [name=pay_mode]:checked")?.value || "deposit";
  const depositInput = $("#po-fill [name=deposit]");
  if (depositInput) depositInput.disabled = payMode === "full";
  const orderAmt = Math.round((goods + freight + extra) * 100) / 100;
  const deposit = payMode === "full" ? orderAmt : Number(depositInput?.value) || 0;
  const remain = Math.round((orderAmt - deposit) * 100) / 100;
  const set = (id, v) => {
    const el = $(id);
    if (el) el.textContent = typeof v === "number" ? v.toFixed(2) : v;
  };
  set("#po-goods", goods);
  set("#po-qty-sum", qtySum);
  set("#po-order-amt", orderAmt);
  set("#po-deposit-amt", deposit);
  set("#po-remain-amt", remain);
}

function bindPoForm({ orders = [], meta = {}, onDraft, onSubmit }) {
  const addRow = (ln) => {
    $("#po-lines").insertAdjacentHTML("beforeend", poLineRow(ln || {}));
    recalcPoLines();
  };
  $("#add-po-line").onclick = () => addRow();
  $("#po-fill").addEventListener("click", (e) => {
    if (e.target.classList.contains("rm-line")) {
      const trs = $$("#po-lines tr");
      if (trs.length > 1) e.target.closest("tr").remove();
      recalcPoLines();
    }
  });
  $("#po-fill").addEventListener("input", (e) => {
    if (e.target.name === "product_name") {
      const hid = e.target.closest("tr")?.querySelector("[name=product_id]");
      if (hid) hid.value = "";
    }
    if (["quantity", "unit_price", "freight", "extra_tax", "deposit"].includes(e.target.name)) recalcPoLines();
  });
  $("#po-fill").addEventListener("change", (e) => {
    if (e.target.name === "pay_mode") recalcPoLines();
    recalcPoLines();
  });
  if ($("#po-so")) {
    $("#po-so").onchange = async () => {
      const id = $("#po-so").value;
      if (!id) return;
      const ord = await api("/api/orders/" + id);
      if (!ord.lines || !ord.lines.length) return;
      $("#po-lines").innerHTML = ord.lines
        .map((l) =>
          poLineRow({
            product_id: l.product_id,
            product_name: l.product_name || l.sku || "",
            unit: l.unit,
            quantity: l.quantity,
            unit_price: l.unit_price || 0,
          })
        )
        .join("");
      recalcPoLines();
    };
  }
  if ($("#po-draft") && onDraft) {
    $("#po-draft").onclick = async () => {
      try {
        await onDraft(collectPoPayload($("#po-fill")));
      } catch (err) {
        alert(err.message || "保存失败");
      }
    };
  }
  $("#po-fill").onsubmit = async (e) => {
    e.preventDefault();
    const payload = collectPoPayload(e.target);
    if (!payload.expected_date) {
      alert("请填写交货时间");
      return;
    }
    if (!(payload.supplier_bank || "").trim()) {
      alert("请填写开户行");
      return;
    }
    if (!(payload.supplier_account || "").trim()) {
      alert("请填写账号");
      return;
    }
    if (!payload.lines.length) {
      alert("请添加商品明细");
      return;
    }
    for (let i = 0; i < payload.lines.length; i++) {
      const l = payload.lines[i];
      if (!(l.product_id || l.product_name)) {
        alert(`第 ${i + 1} 行请填写商品名称`);
        return;
      }
      if (!l.unit) {
        alert(`第 ${i + 1} 行请填写采购单位`);
        return;
      }
      if (!(l.quantity > 0)) {
        alert(`第 ${i + 1} 行请填写数量`);
        return;
      }
      if (l.unit_price === "" || l.unit_price == null || Number.isNaN(l.unit_price)) {
        alert(`第 ${i + 1} 行请填写单价`);
        return;
      }
    }
    try {
      await onSubmit(payload);
    } catch (err) {
      alert(err.message || "提交失败");
    }
  };
  recalcPoLines();
}

async function viewPurchaseOrderDetail(id) {
  const o = await api("/api/purchase-orders/" + id);
  pageTitle("采购单 " + o.no);
  const meta = await api("/api/purchase-orders/meta");
  if (o.can_fill) await loadProducts(true);
  let orders = [];
  if (o.can_fill) {
    try {
      orders = await api("/api/orders");
    } catch {
      orders = [];
    }
  }
  const fillPanel = o.can_fill ? poSheetHtml(o, orders, meta, false) : "";
  $("#view").innerHTML = `
    <div class="panel flow-panel">
      <div class="flow-head">
        <h3>采购单流转</h3>
        <span class="pill ${o.status}">当前：${esc(o.status_label)}</span>
      </div>
      ${flowDiagram(o)}
    </div>
    ${o.can_delete ? `<div class="row-actions" style="margin-bottom:12px"><button type="button" class="danger" id="del-po">删除采购单</button></div>` : ""}
    ${
      o.status === "accepted"
        ? `<div class="panel">
            <h3>验收</h3>
            <p class="muted advance-desc">确认货物验收无误后，采购单进入已完成。</p>
            <button type="button" id="po-adv">验收成功</button>
          </div>`
        : ""
    }
    ${
      o.can_fill
        ? ""
        : `<div class="panel po-acc" id="po-acc">
      <h3>采购单信息</h3>
      <div class="kv kv-wide">
        <div><span>采购单号</span><b>${esc(o.no)}</b></div>
        <div><span>单据日期</span><b>${esc(o.doc_date) || "—"}</b></div>
        <div><span>供应商</span><b>${esc(o.supplier_name) || "待填写"}</b></div>
        <div><span>开户行</span><b>${esc(o.supplier_bank) || "—"}</b></div>
        <div><span>账号</span><b>${esc(o.supplier_account) || "—"}</b></div>
        <div><span>业务员</span><b>${esc(o.purchaser_name) || "—"}</b></div>
        <div><span>项目</span><b>${esc(o.project) || "—"}</b></div>
        <div><span>联系人</span><b>${esc(o.contact_name) || "—"}</b></div>
        <div><span>联系电话</span><b>${esc(o.contact_phone) || "—"}</b></div>
        <div><span>交货时间</span><b>${esc(o.expected_date) || "—"}</b></div>
        <div><span>发货仓库</span><b>${esc(o.shipping_warehouse) || "—"}</b></div>
        <div><span>销售订单</span><b>${esc(o.sales_order_no) || "—"}</b></div>
        <div><span>客户</span><b>${esc(o.customer_name)}</b></div>
        <div><span>订单金额</span><b>${fmtMoney(o.order_amount ?? o.total)} ${esc(o.currency)}</b></div>
        <div><span>运费 / 税费</span><b>${fmtMoney(o.freight)} / ${fmtMoney(o.extra_tax)}</b></div>
        <div><span>订金 / 剩余</span><b>${fmtMoney(o.deposit)} / ${fmtMoney(o.remaining)}</b></div>
        <div><span>创建人</span><b>${esc(o.creator_name)}</b></div>
      </div>
      ${
        o.payment_vouchers && o.payment_vouchers.length
          ? `<p class="muted" style="margin-top:12px">关联付款单 ${o.payment_vouchers
              .map((v) => `<a href="#/finance/payments/${v.id}">${esc(v.no)}</a>`)
              .join("　")}</p>`
          : ""
      }
      ${o.remark ? `<p class="muted" style="margin-top:12px">${esc(o.remark)}</p>` : ""}
      <button type="button" class="po-acc-toggle" id="po-acc-toggle" aria-expanded="false">
        <span>采购明细 · 共 ${(o.lines || []).length} 项</span>
        <span class="po-acc-hint" id="po-acc-hint">点击展开</span>
        <span class="po-acc-chevron" aria-hidden="true">▾</span>
      </button>
      <div class="po-acc-body" id="po-acc-body" hidden>
        <div class="table-wrap"><table class="voucher-table">
          <thead><tr><th>商品</th><th>采购单位</th><th>数量</th><th>单价</th><th>金额</th></tr></thead>
          <tbody>${
            (o.lines || []).length
              ? o.lines.map((l) => `<tr><td>${esc(l.product_name || l.sku)}</td><td>${esc(l.unit)}</td><td>${l.quantity}</td><td>${fmtMoney(l.unit_price)}</td><td>${fmtMoney(l.amount)}</td></tr>`).join("")
              : `<tr><td colspan="5" class="muted">暂无明细</td></tr>`
          }</tbody>
        </table></div>
      </div>
    </div>`
    }
    ${fillPanel}
    ${o.status === "pending_fill" && !o.can_fill ? `<div class="panel"><p class="muted">等待采购填写供应商与采购价后提交管理员审核。</p></div>` : ""}
    ${
      o.can_audit
        ? `<form id="po-audit" class="panel">
            <h3>管理员审核</h3>
            <p class="muted advance-desc">通过后采购单生效，并在资金管理生成一张关联付款单，供财务登记实际付款。</p>
            <label class="advance-field">审核说明<textarea name="remark"></textarea></label>
            <div class="row-actions form-footer">
              <button type="button" id="po-pass">审核通过</button>
              <button type="button" class="danger" id="po-reject">驳回</button>
            </div>
          </form>`
        : ""
    }
    ${
      o.status === "in_progress"
        ? `<div class="panel">
            <h3>物流更新记录</h3>
            ${
              o.can_logistics
                ? `<form id="po-logi" style="margin-top:20px">
                    <div class="form-grid inq-form">
                      <label>物流公司<input name="logistics_company"></label>
                      <label>运单号<input name="tracking_no"></label>
                      <label class="full">说明<input name="comment" placeholder="例如已订舱 / 已离港 / 预计到港时间"></label>
                    </div>
                    <div class="row-actions form-footer">
                      <button type="submit">添加更新</button>
                      ${o.can_advance ? `<button type="button" id="po-adv">确认收货</button>` : ""}
                    </div>
                  </form>`
                : o.can_advance
                  ? `<div class="row-actions form-footer" style="margin-top:16px"><button type="button" id="po-adv">确认收货</button></div>`
                  : ""
            }
          </div>`
        : ""
    }
    ${
      o.status === "received" || o.status === "inbound"
        ? `<div class="panel">
            <button type="button" id="po-adv">${o.status === "received" ? "确认入库" : "确认验收"}</button>
          </div>`
        : ""
    }
    <div class="panel">
      <h3>记录</h3>
      ${
        (o.logs || []).length
          ? `<ol class="timeline">${groupPoLogs(o.logs)
              .map((item) => {
                const lg = item.lg;
                const nested = poLogisticsNestedHtml(item.logistics);
                const title =
                  lg.to_status === "in_progress" && item.logistics.length
                    ? `${esc(lg.to_label)} · 物流 ${item.logistics.length} 条`
                    : esc(lg.to_label);
                const body = `${lg.comment ? `<div class="tl-comment">${esc(lg.comment)}</div>` : ""}${nested}`;
                return `<li><div class="tl-dot"></div>${timelineCardHtml(
                  title,
                  `<span>${esc(lg.created_at)}</span><span>${esc(lg.operator)}</span>`,
                  body
                )}</li>`;
              })
              .join("")}</ol>`
          : `<p class="muted">暂无记录</p>`
      }
    </div>`;
  const accBtn = $("#po-acc-toggle");
  if (accBtn) {
    accBtn.onclick = () => {
      const box = $("#po-acc");
      const body = $("#po-acc-body");
      const open = !box.classList.contains("is-open");
      box.classList.toggle("is-open", open);
      body.hidden = !open;
      $("#po-acc-hint").textContent = open ? "点击收起" : "点击展开";
      accBtn.setAttribute("aria-expanded", open ? "true" : "false");
    };
  }
  if ($("#po-pass")) {
    $("#po-pass").onclick = async () => {
      await api(`/api/purchase-orders/${id}/audit`, { method: "POST", json: { action: "pass", remark: $("#po-audit textarea").value } });
      viewPurchaseOrderDetail(id);
    };
  }
  if ($("#po-reject")) {
    $("#po-reject").onclick = async () => {
      await api(`/api/purchase-orders/${id}/audit`, { method: "POST", json: { action: "reject", remark: $("#po-audit textarea").value } });
      viewPurchaseOrderDetail(id);
    };
  }
  if ($("#po-logi")) {
    $("#po-logi").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        await api(`/api/purchase-orders/${id}/logistics`, { method: "POST", json: Object.fromEntries(fd.entries()) });
        viewPurchaseOrderDetail(id);
      } catch (err) {
        alert(err.message || "物流更新失败");
      }
    };
  }
  if ($("#po-adv")) {
    $("#po-adv").onclick = async () => {
      try {
        await api(`/api/purchase-orders/${id}/advance`, { method: "POST" });
        viewPurchaseOrderDetail(id);
      } catch (err) {
        alert(err.message || "推进失败");
      }
    };
  }
  if (o.can_fill) {
    bindPoForm({
      orders,
      meta,
      onDraft: async (payload) => {
        await api(`/api/purchase-orders/${id}/save`, { method: "POST", json: payload });
        viewPurchaseOrderDetail(id);
      },
      onSubmit: async (payload) => {
        await api(`/api/purchase-orders/${id}/submit`, { method: "POST", json: payload });
        viewPurchaseOrderDetail(id);
      },
    });
  }
  if ($("#del-po")) {
    $("#del-po").onclick = async () => {
      if (!confirm("确认删除该采购单？关联的仅指向本单的付款单会一并删除。")) return;
      try {
        await api("/api/purchase-orders/" + id, { method: "DELETE" });
        location.hash = "#/purchase-orders";
        route();
      } catch (err) {
        alert(err.message || "删除失败");
      }
    };
  }
  bindTimelineAccordions();
}

async function viewFinance() {
  if (me.role !== "admin" && me.role !== "finance") {
    location.hash = "#/home";
    return;
  }
  const tab = parseHash().params.get("tab") || "receipts";
  const tabs = [
    ["receipts", "收款单"],
    ["payments", "付款单"],
    ["profit", "订单盈利"],
    ["summary", "对账总览"],
  ];
  const qs = financeApiQs();
  const [orderRows] = await Promise.all([api("/api/orders")]);
  const filterBar = financeFilterBar(tab, orderRows);
  let body = "";
  if (tab === "profit") {
    const d = await api("/api/finance/profit" + qs);
    body = `
      ${filterBar}
      ${fxHint(d.fx)}
      <div class="table-wrap"><table>
        <thead><tr><th>采购单</th><th>状态</th><th>供应商</th><th>采购金额(人民币)</th><th>已付款(人民币)</th><th>销售订单</th><th>客户</th><th>销售金额(人民币)</th><th>已收款(人民币)</th><th>毛利(人民币)</th></tr></thead>
        <tbody>${
          d.items && d.items.length
            ? d.items
                .map(
                  (r) => `<tr>
            <td><a href="#/purchase-orders/${r.purchase_order_id}">${esc(r.po_no)}</a></td>
            <td>${pill(r.status, r.status_label || r.status)}</td>
            <td>${esc(r.supplier_name)}</td>
            <td>${fmtMoney(r.po_amount)}</td>
            <td>${fmtMoney(r.paid)}</td>
            <td>${r.sales_order_id ? `<a href="#/orders/${r.sales_order_id}">${esc(r.so_no)}</a>` : "—"}</td>
            <td>${esc(r.customer_name)}</td>
            <td>${fmtMoney(r.so_amount)}</td>
            <td>${fmtMoney(r.received)}</td>
            <td><b>${fmtMoney(r.profit)}</b></td>
          </tr>`
                )
                .join("")
            : `<tr><td colspan="10" class="muted">暂无符合条件的采购单</td></tr>`
        }</tbody>
      </table></div>`;
  } else if (tab === "summary") {
    const d = await api("/api/finance/summary" + qs);
    body = `
      ${filterBar}
      ${fxHint(d.fx)}
      <div class="cards" style="grid-template-columns:repeat(4,1fr);margin-bottom:20px">
        ${d.cards.map((c) => `<div class="card"><div class="n">${c.count}</div><div class="l">${esc(c.label)}</div></div>`).join("")}
      </div>
      <div class="panel"><h3>销售订单对账</h3>
        <div class="table-wrap"><table><thead><tr><th>销售单</th><th>客户</th><th>合同额</th><th>累计收款</th><th>已核销</th><th>未收</th></tr></thead>
        <tbody>${d.sales.length ? d.sales.map((r) => `<tr><td><a href="#/orders/${r.order_id}">${esc(r.no)}</a></td><td>${esc(r.customer_name)}</td><td>${fmtMoney(r.contract_amount)}</td><td>${fmtMoney(r.received)}</td><td>${fmtMoney(r.written_off)}</td><td>${fmtMoney(r.open_ar)}</td></tr>`).join("") : `<tr><td colspan="6" class="muted">暂无符合条件的销售单</td></tr>`}</tbody></table></div>
      </div>
      <div class="panel"><h3>采购订单对账</h3>
        <div class="table-wrap"><table><thead><tr><th>采购单</th><th>状态</th><th>供应商</th><th>合同额</th><th>累计付款</th><th>已核销</th><th>未付</th></tr></thead>
        <tbody>${d.purchases.length ? d.purchases.map((r) => `<tr><td><a href="#/purchase-orders/${r.purchase_order_id}">${esc(r.no)}</a></td><td>${pill(r.status, r.status_label || r.status)}</td><td>${esc(r.supplier_name)}</td><td>${fmtMoney(r.contract_amount)}</td><td>${fmtMoney(r.paid)}</td><td>${fmtMoney(r.written_off)}</td><td>${fmtMoney(r.open_ap)}</td></tr>`).join("") : `<tr><td colspan="7" class="muted">暂无符合条件的采购单</td></tr>`}</tbody></table></div>
      </div>
      ${financeLineChart(d.chart)}`;
  } else {
    const direction = tab === "payments" ? "payment" : "receipt";
    const rows = await api("/api/finance/vouchers" + financeApiQs({ direction }));
    const newHref = direction === "receipt" ? "#/finance/receipts/new" : "#/finance/payments/new";
    const title = direction === "receipt" ? "收款单" : "付款单";
    body = `
      ${filterBar}
      <div class="toolbar page-toolbar">
        <a class="btn" href="${newHref}">新建${title}</a>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>单号</th><th>类型</th><th>日期</th><th>往来单位</th><th>${direction === "payment" ? "采购单" : "销售订单"}</th><th>结算合计</th><th>现金折扣</th><th>本次金额</th><th>摘要</th><th>备注</th><th>操作人</th><th></th></tr></thead>
        <tbody>${
          rows.length
            ? rows
                .map(
                  (r) => `<tr>
            <td><a href="#/finance/${direction === "receipt" ? "receipts" : "payments"}/${r.id}">${esc(r.no)}</a></td>
            <td>${r.needs_fill ? `<span class="pill fill">待填写</span> ` : ""}${esc(r.type_label)}</td>
            <td>${esc(r.biz_date)}</td>
            <td>${esc(r.partner_name)}</td>
            <td>${esc(r.linked_docs || "—")}</td>
            <td>${fmtMoney(r.settle_total)} ${esc(r.currency || "")}</td>
            <td>${fmtMoney(r.cash_discount)}</td>
            <td>${fmtMoney(r.final_amount)}</td>
            <td>${esc(r.summary || "")}</td>
            <td>${esc(r.remark || "")}</td>
            <td>${esc(r.operator)}</td>
            <td><a href="#/finance/${direction === "receipt" ? "receipts" : "payments"}/${r.id}">修改</a></td>
          </tr>`
                )
                .join("")
            : `<tr><td colspan="12" class="empty-hint muted">暂无符合条件的${title}</td></tr>`
        }</tbody>
      </table></div>`;
  }
  pageTitle("资金管理");
  $("#view").innerHTML = `
    <div class="inq-page">
    <div class="toolbar">${tabs.map(([k, l]) => `<a class="btn ${tab === k ? "" : "ghost"}" href="${financeTabHref(k)}">${l}</a>`).join("")}</div>
    ${body}
    </div>`;
  bindFinanceFilter(tab);
}

function financeApiQs(extra = {}) {
  const p = parseHash().params;
  const q = new URLSearchParams(extra);
  if (p.get("from")) q.set("date_from", p.get("from"));
  if (p.get("to")) q.set("date_to", p.get("to"));
  if (p.get("order_id")) q.set("order_id", p.get("order_id"));
  const s = q.toString();
  return s ? "?" + s : "";
}

function financeTabHref(k) {
  const p = parseHash().params;
  const q = new URLSearchParams();
  q.set("tab", k);
  ["from", "to", "order_id"].forEach((key) => {
    if (p.get(key)) q.set(key, p.get(key));
  });
  return "#/finance?" + q.toString();
}

function financeFilterBar(tab, orders) {
  const p = parseHash().params;
  const oid = p.get("order_id") || "";
  return `<form class="toolbar finance-filters" id="fin-filter">
    <label>从<input type="date" name="from" value="${esc(p.get("from") || "")}"></label>
    <label>到<input type="date" name="to" value="${esc(p.get("to") || "")}"></label>
    <label>销售订单
      <select name="order_id">
        <option value="">全部</option>
        ${(orders || [])
          .map(
            (o) =>
              `<option value="${o.id}" ${String(o.id) === oid ? "selected" : ""}>${esc(o.no)}　${esc(o.customer_name || "")}</option>`
          )
          .join("")}
      </select>
    </label>
    <button type="submit">查询</button>
    <a class="btn ghost" href="#/finance?tab=${esc(tab)}">重置</a>
  </form>`;
}

function bindFinanceFilter(tab) {
  const form = $("#fin-filter");
  if (!form) return;
  form.onsubmit = (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const q = new URLSearchParams();
    q.set("tab", tab);
    if (fd.get("from")) q.set("from", fd.get("from"));
    if (fd.get("to")) q.set("to", fd.get("to"));
    if (fd.get("order_id")) q.set("order_id", fd.get("order_id"));
    location.hash = "#/finance?" + q.toString();
  };
}

function financeLineChart(chart) {
  const points = (chart && chart.points) || [];
  if (!points.length) {
    return `<div class="panel fin-chart"><h3>收付款金额趋势</h3><p class="muted">所选范围内暂无收付款记录</p></div>`;
  }
  const w = 800;
  const h = 240;
  const pad = { l: 56, r: 20, t: 20, b: 40 };
  const max = Math.max(1, ...points.map((p) => Math.max(Number(p.received) || 0, Number(p.paid) || 0)));
  const innerW = w - pad.l - pad.r;
  const innerH = h - pad.t - pad.b;
  const xAt = (i) => pad.l + (points.length === 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const yAt = (v) => pad.t + (1 - (Number(v) || 0) / max) * innerH;
  const toPath = (key) => points.map((p, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)},${yAt(p[key]).toFixed(1)}`).join(" ");
  const ticks = 4;
  const grid = Array.from({ length: ticks + 1 }, (_, i) => {
    const val = (max * (ticks - i)) / ticks;
    const yy = yAt(val);
    return `<line x1="${pad.l}" x2="${w - pad.r}" y1="${yy.toFixed(1)}" y2="${yy.toFixed(1)}" stroke="#e5e7eb"/>
      <text x="${pad.l - 8}" y="${yy + 4}" text-anchor="end" class="fin-chart-tick">${fmtMoney(val)}</text>`;
  }).join("");
  const step = Math.max(1, Math.ceil(points.length / 6));
  const xlabels = points
    .map((p, i) => {
      if (i % step && i !== points.length - 1) return "";
      const label = p.date.length > 7 ? p.date.slice(5) : p.date;
      return `<text x="${xAt(i).toFixed(1)}" y="${h - 12}" text-anchor="middle" class="fin-chart-tick">${esc(label)}</text>`;
    })
    .join("");
  const unit = chart.granularity === "month" ? "按月" : "按日";
  return `<div class="panel fin-chart">
    <div class="fin-chart-head">
      <h3>收付款金额趋势（人民币 · ${unit}）</h3>
      <div class="fin-chart-legend">
        <span><i class="lg rec"></i>收款</span>
        <span><i class="lg pay"></i>付款</span>
      </div>
    </div>
    <svg viewBox="0 0 ${w} ${h}" class="fin-chart-svg" role="img" aria-label="收付款折线图">${grid}
      <path d="${toPath("received")}" fill="none" stroke="#3B82F6" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
      <path d="${toPath("paid")}" fill="none" stroke="#F59E0B" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>
      ${xlabels}
    </svg>
  </div>`;
}

function fmtMoney(n) {
  return (Math.round((Number(n) || 0) * 100) / 100).toFixed(2);
}

function fxHint(fx) {
  if (!fx || !fx.rates) return "";
  const parts = Object.entries(fx.rates).map(([k, v]) => `1 ${k} = ${Number(v).toFixed(4)} RMB`);
  return parts.length ? `<p class="muted" style="margin:0 0 12px">金额已按最新汇率折合人民币。${parts.join("　")}${fx.as_of ? `　更新：${esc(fx.as_of)}` : ""}</p>` : "";
}

function settleRowHtml(meta, ln = {}) {
  const methods = (meta.settle_methods || []).map((m) => `<option ${m === (ln.method || "银行转账") ? "selected" : ""}>${esc(m)}</option>`).join("");
  const accounts = (meta.accounts || []).map((m) => `<option ${m === (ln.account || "") ? "selected" : ""}>${esc(m)}</option>`).join("");
  const currencies = meta.currencies || ["RMB", "USD", "EUR"];
  const cur = ln.currency || "RMB";
  return `<tr>
    <td class="col-idx"></td>
    <td><select name="method">${methods}</select></td>
    <td><select name="account"><option value="">请选择</option>${accounts}</select></td>
    <td><select name="currency">${currencies.map((c) => `<option ${c === cur ? "selected" : ""}>${c}</option>`).join("")}</select></td>
    <td><input name="amount" type="number" step="0.01" min="0" value="${ln.amount ?? ""}" placeholder="0.00"></td>
    <td><input name="sremark" value="${esc(ln.remark || "")}" placeholder="本批次备注"></td>
    <td><button type="button" class="ghost rm-settle">删除</button></td>
  </tr>`;
}

async function viewVoucherForm(direction, voucherId) {
  if (me.role !== "admin" && me.role !== "finance") {
    location.hash = "#/home";
    return;
  }
  const isReceipt = direction === "receipt";
  const title = isReceipt ? "收款单" : "付款单";
  pageTitle(voucherId ? "编辑" + title : "新建" + title);
  const [meta, linkable] = await Promise.all([
    api("/api/finance/meta"),
    api("/api/finance/linkable-docs?direction=" + direction),
  ]);
  const existing = voucherId ? await api("/api/finance/vouchers/" + voucherId) : null;
  const linkedId = existing
    ? isReceipt
      ? existing.allocs?.[0]?.order_id
      : existing.allocs?.[0]?.purchase_order_id
    : "";
  const linkDocs = [...(linkable || [])];
  if (existing && linkedId && !linkDocs.some((d) => String(d.id) === String(linkedId))) {
    const a = existing.allocs[0] || {};
    linkDocs.unshift({
      id: linkedId,
      no: a.doc_no || "",
      partner_name: a.partner_name || existing.partner_name || "",
      total: a.this_amount || 0,
    });
  }
  const bizTypes = isReceipt ? meta.biz_types_ar : meta.biz_types_ap;
  const typeCollect = isReceipt ? "收款" : "付款";
  const amountLabel = isReceipt ? "收款金额" : "付款金额";
  $("#view").innerHTML = `
    <form id="voucher-form" class="voucher-page">
      <div class="voucher-toolbar">
        <button type="submit">保存</button>
        <a class="btn ghost" href="#/finance?tab=${isReceipt ? "receipts" : "payments"}">${existing ? "返回列表" : "取消"}</a>
      </div>
      <div class="panel voucher-head">
        <div class="voucher-type-row">
          <label class="radio"><input type="radio" name="voucher_type" value="collect" ${!existing || existing.voucher_type === "collect" ? "checked" : ""}> ${typeCollect}</label>
          <label class="radio"><input type="radio" name="voucher_type" value="refund" ${existing && existing.voucher_type === "refund" ? "checked" : ""}> 退款</label>
        </div>
        <div class="form-grid voucher-meta">
          <label>单据日期<input name="biz_date" type="date" required value="${esc(existing?.biz_date || meta.today)}"></label>
          <label>单据编号<input value="${esc(existing?.no || "保存后自动生成")}" readonly></label>
          <label>${isReceipt ? "关联销售订单" : "关联采购单"}
            <select name="link_doc_id">
              <option value="">请选择</option>
              ${linkDocs
                .map(
                  (d) =>
                    `<option value="${d.id}" data-partner="${esc(d.partner_name)}" data-currency="${esc(d.currency || "RMB")}" ${String(linkedId) === String(d.id) ? "selected" : ""}>${esc(d.no)}　${esc(d.partner_name)}　${fmtMoney(d.total)}</option>`
                )
                .join("")}
            </select>
          </label>
          <label>往来单位
            <input name="partner_name" value="${esc(existing?.partner_name || "")}" placeholder="手动填写" autocomplete="off">
          </label>
          <label>业务类型
            <select name="biz_type">
              ${bizTypes.map((t) => `<option ${ (existing?.biz_type || bizTypes[0]) === t ? "selected" : ""}>${esc(t)}</option>`).join("")}
            </select>
          </label>
          <label>业务员
            <select name="salesperson_id">
              <option value="">请选择</option>
              ${(meta.salespeople || []).map((u) => `<option value="${u.id}" ${String(existing?.salesperson_id || "") === String(u.id) ? "selected" : ""}>${esc(u.name)}</option>`).join("")}
            </select>
          </label>
          <label>摘要<input name="summary" value="${esc(existing?.summary || "")}" placeholder="选填"></label>
          <label class="full">备注<textarea name="remark" rows="2" placeholder="本批次${typeCollect}备注，可随时修改">${esc(existing?.remark || "")}</textarea></label>
        </div>
      </div>
      <div class="panel">
        <div class="table-wrap"><table class="voucher-table settle-table">
          <thead><tr><th></th><th>结算方式</th><th>${isReceipt ? "收款账号" : "付款账号"}</th><th>币种</th><th>${amountLabel}</th><th>备注</th><th></th></tr></thead>
          <tbody id="settle-lines">${
            existing && existing.settles && existing.settles.length
              ? existing.settles.map((s) => settleRowHtml(meta, s)).join("")
              : settleRowHtml(meta)
          }</tbody>
        </table></div>
        <div class="row-actions form-footer"><button type="button" class="ghost" id="add-settle">再记一笔</button></div>
        ${fxHint(meta.fx)}
        <div class="voucher-sum">
          <span>${typeCollect}合计 <b id="settle-total">${fmtMoney(existing?.settle_total || 0)}</b> <span class="muted" id="settle-ccy">${esc(existing?.currency || "RMB")}</span></span>
          <span>折合人民币 <b id="settle-rmb">0.00</b></span>
          <span>+ 现金折扣 <input id="cash-discount" name="cash_discount" type="number" step="0.01" min="0" value="${existing?.cash_discount ?? 0}"></span>
          <span>= 本次${typeCollect} <b id="final-amount">${fmtMoney(existing?.final_amount || 0)}</b></span>
        </div>
      </div>
    </form>`;
  $$("#settle-lines tr").forEach(renumberSettle);
  bindVoucherForm(direction, meta, existing);
}

function renumberSettle(tr, i) {
  const idx = tr.querySelector(".col-idx");
  if (idx) idx.textContent = i + 1;
}

function bindVoucherForm(direction, meta, existing) {
  const form = $("#voucher-form");
  const isReceipt = direction === "receipt";

  const refreshSettleSum = () => {
    const rows = $$("#settle-lines tr");
    const total = rows.reduce((s, tr) => s + (Number($("[name=amount]", tr).value) || 0), 0);
    const disc = Number($("#cash-discount").value) || 0;
    const ccys = [...new Set(rows.map((tr) => $("[name=currency]", tr)?.value || "RMB"))];
    const ccy = ccys.length === 1 ? ccys[0] : "";
    const rates = meta.fx?.rates || {};
    const toRmb = (amt, code) => {
      if (!code || code === "RMB" || code === "CNY") return amt;
      const r = Number(rates[code]) || 0;
      return r ? amt * r : amt;
    };
    const rmb = rows.reduce((s, tr) => s + toRmb(Number($("[name=amount]", tr).value) || 0, $("[name=currency]", tr)?.value), 0);
    $("#settle-total").textContent = fmtMoney(total);
    if ($("#settle-ccy")) $("#settle-ccy").textContent = ccy || "多币种";
    if ($("#settle-rmb")) $("#settle-rmb").textContent = fmtMoney(rmb);
    $("#final-amount").textContent = fmtMoney(total + disc);
  };

  const applyLinkDoc = () => {
    const sel = form.link_doc_id;
    if (!sel || !sel.value) return;
    const partner = (sel.selectedOptions[0]?.dataset?.partner || "").trim();
    const input = form.partner_name;
    if (partner && input && !String(input.value || "").trim()) input.value = partner;
    const ccy = sel.selectedOptions[0]?.dataset?.currency || "";
    if (ccy) {
      $$("#settle-lines [name=currency]").forEach((el) => {
        el.value = ccy;
      });
      refreshSettleSum();
    }
  };

  $("#add-settle").onclick = () => {
    const last = $$("#settle-lines tr").slice(-1)[0];
    const ccy = last ? $("[name=currency]", last)?.value : "RMB";
    $("#settle-lines").insertAdjacentHTML("beforeend", settleRowHtml(meta, { currency: ccy }));
    $$("#settle-lines tr").forEach(renumberSettle);
  };
  form.addEventListener("click", (e) => {
    if (e.target.classList.contains("rm-settle")) {
      const trs = $$("#settle-lines tr");
      if (trs.length > 1) e.target.closest("tr").remove();
      $$("#settle-lines tr").forEach(renumberSettle);
      refreshSettleSum();
    }
  });
  form.addEventListener("input", (e) => {
    if (["amount", "cash_discount", "currency"].includes(e.target.name) || e.target.id === "cash-discount") refreshSettleSum();
  });
  form.addEventListener("change", (e) => {
    if (e.target.name === "currency") refreshSettleSum();
  });
  if (form.link_doc_id) form.link_doc_id.onchange = applyLinkDoc;
  form.querySelectorAll("[name=voucher_type]").forEach((r) => {
    r.onchange = () => {
      const refund = form.voucher_type.value === "refund";
      $("#cash-discount").readOnly = refund;
      if (refund) $("#cash-discount").value = "0";
      refreshSettleSum();
    };
  });
  form.onsubmit = async (e) => {
    e.preventDefault();
    const linkedId = Number(form.link_doc_id?.value || 0);
    if (!linkedId) {
      alert(isReceipt ? "请关联销售订单" : "请关联采购单");
      return;
    }
    const partnerName = (form.partner_name.value || "").trim();
    if (!partnerName) {
      alert("请填写往来单位");
      return;
    }
    const settles = $$("#settle-lines tr").map((tr) => ({
      method: $("[name=method]", tr).value,
      account: $("[name=account]", tr).value,
      currency: $("[name=currency]", tr)?.value || "RMB",
      amount: Number($("[name=amount]", tr).value) || 0,
      remark: $("[name=sremark]", tr).value,
    }));
    const ccys = [...new Set(settles.map((x) => x.currency))];
    if (ccys.length > 1) {
      alert("同一收付款单结算行币种须一致");
      return;
    }
    const settleTotal = settles.reduce((s, x) => s + (Number(x.amount) || 0), 0);
    const disc = Number($("#cash-discount").value) || 0;
    const allocs = [
      isReceipt
        ? { doc_type: "sales_order", order_id: linkedId, purchase_order_id: null, this_amount: settleTotal, discount_amount: disc }
        : { doc_type: "purchase_order", order_id: null, purchase_order_id: linkedId, this_amount: settleTotal, discount_amount: disc },
    ];
    const payload = {
      direction,
      voucher_type: form.voucher_type.value,
      biz_date: form.biz_date.value,
      partner_name: partnerName,
      biz_type: form.biz_type.value,
      salesperson_id: form.salesperson_id.value ? Number(form.salesperson_id.value) : null,
      summary: form.summary.value,
      remark: form.remark.value,
      cash_discount: disc,
      settles,
      allocs,
    };
    try {
      if (existing) await api("/api/finance/vouchers/" + existing.id, { method: "PUT", json: payload });
      else await api("/api/finance/vouchers", { method: "POST", json: payload });
      location.hash = `#/finance?tab=${direction === "receipt" ? "receipts" : "payments"}`;
    } catch (err) {
      alert(err.message || "保存失败");
    }
  };
  refreshSettleSum();
  if (form.link_doc_id?.value) applyLinkDoc();
}

async function viewUsers() {
  pageTitle("用户管理");
  const rows = await api("/api/users");
  $("#view").innerHTML = `
    <form id="uf" class="panel form-grid">
      <label>用户名<input name="username" required></label>
      <label>姓名<input name="name" required></label>
      <label>密码<input name="password" required minlength="6"></label>
      <label>角色<select name="role">
        <option value="sales">销售</option>
        <option value="purchase">采购</option>
        <option value="finance">财务</option>
        <option value="admin">管理员</option>
      </select></label>
      <div class="full"><button>新增用户</button></div>
    </form>
    <div class="table-wrap"><table>
      <thead><tr><th>用户名</th><th>姓名</th><th>角色</th><th>状态</th><th></th></tr></thead>
      <tbody>
        ${rows
          .map(
            (u) => `<tr>
            <td>${esc(u.username)}</td><td>${esc(u.name)}</td>
            <td>${esc(u.role_label)}</td>
            <td>${u.is_active ? "启用" : "停用"}</td>
            <td>
              <button class="ghost" data-toggle="${u.id}" data-active="${u.is_active}">${u.is_active ? "停用" : "启用"}</button>
              <button class="ghost" data-pwd="${u.id}">重置密码</button>
            </td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
  $("#uf").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await api("/api/users", { method: "POST", json: Object.fromEntries(fd.entries()) });
    viewUsers();
  };
  $$("[data-toggle]").forEach((b) => {
    b.onclick = async () => {
      await api("/api/users/" + b.dataset.toggle, {
        method: "PATCH",
        json: { is_active: b.dataset.active !== "true" },
      });
      viewUsers();
    };
  });
  $$("[data-pwd]").forEach((b) => {
    b.onclick = async () => {
      const password = prompt("新密码（至少 6 位）");
      if (!password) return;
      await api("/api/users/" + b.dataset.pwd, { method: "PATCH", json: { password } });
      alert("已重置");
    };
  });
}

async function route() {
  stopAssistantTimer();
  const { path } = parseHash();
  if (path === "#/login") {
    showLogin();
    return;
  }
  await ensureMe();
  if (!me) {
    showLogin();
    return;
  }
  showApp();
  $("#view").classList.remove("catalog-fill");
  document.querySelector(".workspace")?.classList.remove("catalog-mode");
  try {
    if (path === "#/home") await viewHome();
    else if (path === "#/products") await viewProducts();
    else if (path === "#/inquiries") await viewInquiries();
    else if (path === "#/inquiries/new") await viewInquiryNew();
    else if (path.startsWith("#/inquiries/")) await viewInquiryDetail(path.split("/")[2]);
    else if (path === "#/orders/new") await viewSalesOrderNew();
    else if (path === "#/orders") await viewOrders();
    else if (path.startsWith("#/orders/")) {
      const segs = path.replace(/^#\//, "").split("/");
      const id = segs[1];
      if (/^\d+$/.test(id)) await viewOrderDetail(id);
      else await viewOrders();
    }
    else if (path === "#/purchase-orders/new") await viewPurchaseOrderNew();
    else if (path === "#/purchase-orders") await viewPurchaseOrders();
    else if (path.startsWith("#/purchase-orders/")) await viewPurchaseOrderDetail(path.split("/")[2]);
    else if (path === "#/assistant") await viewAssistant();
    else if (path === "#/finance/receipts/new") await viewVoucherForm("receipt");
    else if (path.startsWith("#/finance/receipts/")) await viewVoucherForm("receipt", path.split("/")[3]);
    else if (path === "#/finance/payments/new") await viewVoucherForm("payment");
    else if (path.startsWith("#/finance/payments/")) await viewVoucherForm("payment", path.split("/")[3]);
    else if (path === "#/finance") await viewFinance();
    else if (path === "#/users") await viewUsers();
    else await viewHome();
  } catch (err) {
    $("#view").innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
  renderNav();
}

window.addEventListener("hashchange", route);
route();
