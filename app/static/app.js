/* 煤炉工作台：直接使用同源业务 API，不在浏览器保存业务数据或登录信息。 */
"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  box: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="M3 8v9l9 5 9-5V8M12 13v9M7.5 5.5l9 5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  bag: '<path d="M5 7h14l1 14H4L5 7ZM8 8V6a4 4 0 0 1 8 0v2"/>',
  truck:
    '<path d="M2 5h12v12H2zM14 9h4l4 5v3h-8"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  external:
    '<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 13 2l1 4M4 12l1 4a8 8 0 0 0 13 2"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  image:
    '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  chart: '<path d="M4 3v17h17M8 15l4-5 4 2 5-6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  alert: '<path d="m12 3 10 18H2L12 3ZM12 9v5M12 17h.01"/>',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.box}</svg>`;
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const safeURL = (url) => {
  if (typeof url !== "string" || !url.trim()) return "";
  try {
    const u = new URL(url, location.origin);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "";
  } catch {
    return "";
  }
};
const external = (url, label = "打开来源页面") =>
  safeURL(url)
    ? `<a class="external-link" href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} ${icon("external")}</a>`
    : '<span class="subtle">未填写链接</span>';
const n = (value, digits = 0) =>
  Number(value || 0).toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
const money = (value, currency = "JPY") =>
  value == null
    ? '<span class="subtle">—</span>'
    : `<span class="money"><span class="currency">${currency === "JPY" ? "¥" : "CN¥"}</span>${n(value, currency === "JPY" ? 0 : 2)}</span>`;
const dateText = (value) =>
  value
    ? new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date(value))
    : "—";
const statusNames = {
  cancelled: "已取消",
  withdrawn: "已下架",
  return_received: "退货已收",
  candidate: "待找货",
  sourcing: "找货中",
  matched: "已核验",
  listing_draft: "待上架",
  listed: "已上架",
  rejected: "已放弃",
  awaiting_purchase: "待采购",
  purchased: "已采购",
  awaiting_dispatch: "待发往日本",
  in_transit: "运往日本",
  received: "验收通过",
  inspection_issue: "验收异常",
  not_shipped: "待日本发货",
  shipped: "已发给买家",
  delivered: "已送达",
  confirmed: "同款已确认",
  pending: "待核验",
  available: "当前有货",
  unavailable: "当前无货",
  unknown: "供货未知",
};
const badge = (status, label) =>
  `<span class="status ${esc(status)}">${esc(label || statusNames[status] || status)}</span>`;
const state = {
  items: [],
  orders: [],
  japan: [],
  china: [],
  view: "dashboard",
  filter: "all",
  query: "",
  sort: "newest",
  page: 1,
  detail: null,
  detailTab: "overview",
  order: null,
  listingDefaults: null,
};
const views = {
  dashboard: [
    "业务概览",
    "OVERVIEW",
    "日本选品 → 中国找货 → 上架资料 → 订单履约，每件商品按流程向前。",
  ],
  items: [
    "商品工作台",
    "PRODUCT WORKSPACE",
    "集中查看商品来源、货源、图片、上架资料和当前阶段。",
  ],
  sourcing: [
    "中国找货",
    "CHINA SOURCING",
    "从已收录的日本商品出发，找同款货源并收集图片候选。",
  ],
  listings: [
    "上架资料",
    "LISTING PREPARATION",
    "核对货源与图片，整理日文资料、试算成本并准备 Shops 草稿。",
  ],
  orders: [
    "订单履约",
    "ORDER FULFILLMENT",
    "成交后采购，经过日本验收，再送到买家手中。",
  ],
  discovery: [
    "日本选品",
    "STEP 01 · JAPAN DISCOVERY",
    "搜索 Mercari 商品或采集商品 / 店铺页面，把合适的选品送入商品工作台。",
  ],
  sites: [
    "平台目录",
    "PLATFORM DIRECTORY",
    "查看当前接入的平台，以及各平台在业务流程中的用途。",
  ],
};
let toastTimer,
  refreshSerial = 0,
  drawerSerial = 0,
  returnFocus;

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 25000);
  try {
    const response = await fetch(path, {
      cache: "no-store",
      ...options,
      signal: controller.signal,
      headers:
        options.body instanceof FormData
          ? options.headers
          : { "Content-Type": "application/json", ...options.headers },
    });
    let data;
    try {
      data = await response.json();
    } catch {
      data = null;
    }
    if (!response.ok) {
      const detail = data?.detail;
      throw new Error(
        Array.isArray(detail)
          ? detail
              .map((d) => `${d.loc.slice(1).join(" / ")}：${d.msg}`)
              .join("\n")
          : typeof detail === "string"
            ? detail
            : `请求失败（${response.status}）`,
      );
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error("请求超时，请检查服务状态后重试。");
    if (error instanceof TypeError)
      throw new Error("无法连接本地服务，请确认应用仍在运行。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
const post = (url, data) =>
  api(url, {
    method: "POST",
    body: data instanceof FormData ? data : JSON.stringify(data),
  });
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast-root").innerHTML =
    `<div class="toast ${error ? "error" : ""}" role="status">${icon(error ? "alert" : "check")}${esc(message)}</div>`;
  toastTimer = setTimeout(
    () => $("#toast-root").replaceChildren(),
    error ? 6500 : 3300,
  );
}
function thumb(item, cls = "") {
  const src = item.thumbnail_image_id
    ? `/api/china/source-images/${encodeURIComponent(item.thumbnail_image_id)}/file?variant=listing`
    : safeURL(item.japan_image_url);
  return src
    ? `<img class="thumbnail ${cls}" src="${esc(src)}" alt="${esc(item.japan_title || "商品图片")}" loading="lazy" referrerpolicy="no-referrer">`
    : `<span class="thumbnail empty ${cls}">${icon("image")}</span>`;
}
function siteName(id) {
  return [...state.japan, ...state.china].find((s) => s.id === id)?.name || id;
}
function siteChip(id) {
  return `<span class="site-chip"><i class="site-dot ${esc(id)}"></i>${esc(siteName(id))}</span>`;
}
function stage(order) {
  if (order.order_status === "cancelled") return "cancelled";
  if (order.return_received_at) return "return_received";
  return order.domestic_status === "delivered"
    ? "delivered"
    : order.domestic_status === "shipped"
      ? "shipped"
      : order.inbound_status === "inspection_issue"
        ? "inspection_issue"
        : order.inbound_status === "received"
          ? "received"
          : order.inbound_status === "in_transit"
            ? "in_transit"
            : order.fulfillment_status;
}
function nav() {
  const groups = [
    {
      label: "商品流程",
      entries: [
        ["dashboard", "grid", "业务概览"],
        ["discovery", "search", "日本选品"],
        ["items", "box", "商品工作台", state.items.length],
        [
          "sourcing",
          "search",
          "中国找货",
          state.items.filter((x) => ["candidate", "sourcing"].includes(x.status)).length,
        ],
        [
          "listings",
          "bag",
          "上架资料",
          state.items.filter((x) => ["matched", "listing_draft"].includes(x.status)).length,
        ],
        [
          "orders",
          "truck",
          "订单履约",
          state.orders.filter((x) => !["delivered", "cancelled"].includes(stage(x))).length,
        ],
      ],
    },
    { label: "平台与设置", entries: [["sites", "globe", "平台目录"]] },
  ];
  $("#nav").innerHTML = groups
    .map(
      ({ label, entries }, groupIndex) =>
        `${groupIndex ? '<div class="nav-separator"></div>' : ""}<div class="nav-group-label">${label}</div>${entries
          .map(
            ([key, glyph, entryLabel, count]) =>
              `<a href="#${key}" class="nav-item ${state.view === key ? "active" : ""}" ${state.view === key ? 'aria-current="page"' : ""}>${icon(glyph)}<span>${entryLabel}</span>${count !== undefined ? `<span class="nav-count">${count}</span>` : ""}</a>`,
          )
          .join("")}`,
    )
    .join("");
  $("#breadcrumb").textContent = views[state.view][0];
}
async function refresh({ silent = false } = {}) {
  const serial = ++refreshSerial;
  $("#refresh").disabled = true;
  try {
    const [items, orders, japan, china, listingDefaults] = await Promise.all([
      api("/api/items"),
      api("/api/orders"),
      api("/api/japan/sites"),
      api("/api/china/sites"),
      api("/api/listing/defaults"),
    ]);
    if (serial !== refreshSerial) return;
    Object.assign(state, { items, orders, japan, china, listingDefaults });
    if (typeof refreshAutomation === "function") await refreshAutomation(false);
    $("#connection").className = "connection";
    $("#connection").innerHTML = "<i></i>本地服务已连接";
    render();
  } catch (error) {
    $("#connection").className = "connection offline";
    $("#connection").innerHTML = "<i></i>连接中断";
    if (!silent || !state.items.length)
      $("#main").innerHTML =
        `<div class="panel">${empty("本地服务暂时无法连接", error.message, "refresh", "重新连接")}</div>`;
    else toast(error.message, true);
  } finally {
    if (serial === refreshSerial) $("#refresh").disabled = false;
  }
}
function heading() {
  if (state.view === "discovery") return backendHeading();
  const [title, eyebrow, subtitle] = views[state.view];
  const actions =
    state.view === "orders"
      ? `<button class="button" data-action="shop-read-orders">${icon("refresh")}读取店铺订单</button><button class="button primary" data-action="new-order">${icon("plus")}登记订单</button>`
      : state.view === "listings"
        ? `<button class="button secondary-action" data-action="listing-defaults">通用上架设置</button><button class="button secondary-action" data-action="export">${icon("upload")}导出商品</button>`
        : state.view === "sourcing"
          ? `<a class="button primary" href="#discovery">${icon("search")}先去日本选品</a>`
          : state.view === "items"
            ? `<button class="button secondary-action" data-action="export">${icon("upload")}导出商品</button><button class="button primary" data-action="new-item">${icon("plus")}手动新增选品</button>`
            : state.view === "dashboard"
              ? `<a class="button primary" href="#discovery">${icon("search")}开始日本选品</a>`
              : "";
  return `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p class="subtitle">${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`;
}
function empty(title, subtitle, action, label) {
  return `<div class="empty-state"><div class="empty-illustration">${icon("box")}</div><h3>${esc(title)}</h3><p>${esc(subtitle)}</p>${action ? `<button class="button soft" data-action="${action}">${esc(label)}</button>` : ""}</div>`;
}
function stats() {
  const cards = [
    [
      "商品总数",
      state.items.length,
      "件",
      "box",
      "",
      `<b>${state.items.filter((i) => i.status === "listed").length}</b> 件已进入销售阶段`,
    ],
    [
      "找货与核验",
      state.items.filter((i) => ["candidate", "sourcing"].includes(i.status))
        .length,
      "件",
      "search",
      "amber",
      "为日本选品寻找中国同款",
    ],
    [
      "待上架商品",
      state.items.filter((i) => ["matched", "listing_draft"].includes(i.status))
        .length,
      "件",
      "bag",
      "blue",
      `<b>${state.items.filter((i) => i.status === "listing_draft").length}</b> 份草稿等待发布`,
    ],
    [
      "进行中订单",
      state.orders.filter((o) => !["delivered", "cancelled"].includes(stage(o)))
        .length,
      "单",
      "truck",
      "green",
      `<b>${state.orders.filter((o) => o.fulfillment_status === "awaiting_purchase" && o.order_status !== "cancelled").length}</b> 单待采购 · ${state.orders.filter((o) => stage(o) === "inspection_issue").length} 单验收异常`,
    ],
  ];
  return `<div class="stats">${cards.map(([title, value, unit, glyph, color, note]) => `<div class="stat"><div class="stat-top">${title}<span class="stat-icon ${color}">${icon(glyph)}</span></div><div class="stat-value">${value}<small>${unit}</small></div><div class="stat-bottom">${note}</div></div>`).join("")}</div>`;
}
function workflowOverview() {
  const stages = [
    {
      number: "01",
      title: "日本选品",
      detail: "搜索 Mercari，采集商品或店铺页面",
      metric: `${state.items.length} 件已入库`,
      href: "#discovery",
      action: "开始发现",
      icon: "search",
      tone: "coral",
    },
    {
      number: "02",
      title: "中国找货",
      detail: "按日本商品找同款并收集图片候选",
      metric: `${state.items.filter((i) => ["candidate", "sourcing"].includes(i.status)).length} 件待处理`,
      href: "#sourcing",
      action: "处理货源",
      icon: "box",
      tone: "amber",
    },
    {
      number: "03",
      title: "准备上架",
      detail: "整理日文资料、图片与利润试算",
      metric: `${state.items.filter((i) => ["matched", "listing_draft"].includes(i.status)).length} 件待准备`,
      href: "#listings",
      action: "查看上架资料",
      icon: "bag",
      tone: "blue",
    },
    {
      number: "04",
      title: "订单履约",
      detail: "成交后采购，验收并记录两段物流",
      metric: `${state.orders.filter((o) => !["delivered", "cancelled"].includes(stage(o))).length} 单进行中`,
      href: "#orders",
      action: "跟进订单",
      icon: "truck",
      tone: "green",
    },
  ];
  return `<section class="workflow-panel"><div class="workflow-panel-heading"><div><p class="eyebrow">从发现到履约</p><h2>一件商品，沿着同一条流程走完</h2><p>日本商品是起点；中国货源、上架资料和成交订单都关联回这件商品。</p></div><span class="workflow-total">${state.items.length} 件商品在流程中</span></div><div class="workflow-steps">${stages
    .map(
      (step) =>
        `<a class="workflow-step ${step.tone}" href="${step.href}"><span class="workflow-step-top"><span class="workflow-step-number">${step.number}</span><span class="workflow-step-icon">${icon(step.icon)}</span></span><strong>${step.title}</strong><span class="workflow-step-detail">${step.detail}</span><span class="workflow-step-bottom"><span>${step.metric}</span><span class="workflow-step-action">${step.action} ${icon("arrow")}</span></span></a>`,
    )
    .join("")}</div><div class="workflow-footnote"><span>${icon("check")}选品资料、找货搜索词和上架资料可自动整理</span><span>Mercari Shops 正式发布由你在店铺内完成</span></div></section>`;
}
function eligibleItems() {
  if (state.view === "items" && state.itemScope === "archived")
    return state.archivedItems || [];
  return state.items.filter((i) =>
    state.view === "sourcing"
      ? ["candidate", "sourcing", "matched"].includes(i.status)
      : state.view === "listings"
        ? ["matched", "listing_draft", "listed", "withdrawn"].includes(i.status)
        : true,
  );
}
function filteredItems() {
  return eligibleItems()
    .filter(
      (i) =>
        (state.filter === "all" || i.status === state.filter) &&
        `${i.japan_title} ${i.title_ja || ""} ${siteName(i.japan_site)} ${i.id} ${i.note}`
          .toLowerCase()
          .includes(state.query.toLowerCase()),
    )
    .sort((a, b) =>
      state.sort === "price-high"
        ? (b.price_jpy || b.japan_price_jpy || 0) -
          (a.price_jpy || a.japan_price_jpy || 0)
        : state.sort === "oldest"
          ? a.created_at.localeCompare(b.created_at)
          : b.created_at.localeCompare(a.created_at),
    );
}
function itemRow(item) {
  const action =
    {
      candidate: "去找货",
      sourcing: "核验货源",
      matched: "创建草稿",
      listing_draft: "查看草稿",
      listed: "商品详情",
    }[item.status] || "查看详情";
  const tab = ["candidate", "sourcing"].includes(item.status)
    ? "sources"
    : ["matched", "listing_draft"].includes(item.status)
      ? "listing"
      : "overview";
  return `<tr><td><button class="product-button product-cell" data-action="item" data-id="${esc(item.id)}">${thumb(item)}<span><span class="product-name" title="${esc(item.japan_title)}">${esc(item.japan_title)}</span><span class="product-code">PRD-${esc(item.id.slice(0, 8).toUpperCase())}</span></span></button></td><td>${siteChip(item.japan_site)}<div class="price-sub">${dateText(item.created_at)}</div></td><td>${money(item.price_jpy ?? item.japan_price_jpy)}<div class="price-sub">${item.draft_id ? "店铺售价" : "日本参考价"}</div></td><td>${item.source_count ? `${money(item.source_price_cny, "CNY")}<div class="price-sub">${item.source_count} 个候选货源${item.source_count > 1 ? " · 最低价" : ""}</div>` : '<span class="subtle">等待找货</span>'}</td><td>${badge(item.status)}</td><td>${item.estimated_profit_cny != null ? `<span class="profit ${item.estimated_profit_cny < 0 ? "negative" : ""}">${money(item.estimated_profit_cny, "CNY")}</span><div class="price-sub">利润率 ${n(item.estimated_margin_pct, 1)}%</div>` : '<span class="subtle">待试算</span>'}</td><td><button class="row-action" data-action="item" data-id="${esc(item.id)}" data-tab="${tab}">${action} ${icon("arrow")}</button></td></tr>`;
}
function itemTable() {
  const pool = eligibleItems(),
    allowed =
      state.view === "sourcing"
        ? ["candidate", "sourcing", "matched"]
        : state.view === "listings"
          ? ["matched", "listing_draft", "listed", "withdrawn"]
          : ["candidate", "sourcing", "matched", "listing_draft", "listed"];
  const list = filteredItems();
  state.page = Math.min(
    Math.max(1, state.page),
    Math.max(1, Math.ceil(list.length / 8)),
  );
  const rows = list.slice((state.page - 1) * 8, state.page * 8);
  return `<section class="panel"><div class="panel-header"><div class="panel-heading"><h2>${state.view === "dashboard" ? "商品动态" : state.view === "sourcing" ? "找货任务" : state.view === "listings" ? "上架商品" : "全部商品"}</h2><span class="subtle">${pool.length} 件商品，持续向前</span></div>${state.view === "dashboard" ? '<a class="button text" href="#items">查看全部 ' + icon("arrow") + "</a>" : '<span class="subtle">记录好物的每一步</span>'}</div><div class="tabs" role="tablist" aria-label="商品阶段">${[["all", "全部"], ...allowed.map((k) => [k, statusNames[k]])].map(([k, label]) => `<button class="tab ${state.filter === k ? "active" : ""}" data-action="filter" data-id="${k}" role="tab" aria-selected="${state.filter === k}">${label}<span class="count">${k === "all" ? pool.length : pool.filter((i) => i.status === k).length}</span></button>`).join("")}</div><div class="table-toolbar"><div class="search-wrap">${icon("search")}<input type="search" id="search" aria-label="搜索商品" placeholder="搜索商品名称、平台或编号…" value="${esc(state.query)}"></div><div class="toolbar-actions"><select class="filter-select" id="sort" aria-label="商品排序"><option value="newest" ${state.sort === "newest" ? "selected" : ""}>最近添加优先</option><option value="oldest" ${state.sort === "oldest" ? "selected" : ""}>最早添加优先</option><option value="price-high" ${state.sort === "price-high" ? "selected" : ""}>售价从高到低</option></select><button class="button small" data-action="reset-filters">清除筛选</button><button class="button small" data-action="refresh">${icon("refresh")}刷新</button></div></div>${rows.length ? `<div class="table-scroll"><table><thead><tr><th>商品信息</th><th>选品来源</th><th>日本价格</th><th>中国货源</th><th>业务阶段</th><th>预估利润</th><th>操作</th></tr></thead><tbody>${rows.map(itemRow).join("")}</tbody></table></div>` : empty(state.query || state.filter !== "all" ? "没有符合条件的商品" : "从第一件好物开始", state.query || state.filter !== "all" ? "试试其他关键词或切换商品阶段。" : "添加日本商品链接，开启选品、找货与上架流程。", state.query || state.filter !== "all" ? null : ["dashboard", "sourcing", "listings"].includes(state.view) ? "new-discovery" : "new-item", state.query || state.filter !== "all" ? "清除筛选" : ["dashboard", "sourcing", "listings"].includes(state.view) ? "去日本选品" : "新增选品")}<div class="table-footer"><span>共 ${list.length} 件商品${list.length ? ` · 显示 ${(state.page - 1) * 8 + 1}–${Math.min(state.page * 8, list.length)} 件` : ""}</span><div class="pagination"><button aria-label="上一页" data-action="prev-page" ${state.page <= 1 ? "disabled" : ""}>‹</button><span class="page-number">${state.page}</span><button aria-label="下一页" data-action="next-page" ${state.page * 8 >= list.length ? "disabled" : ""}>›</button></div></div></section>`;
}
function dashboardBottom() {
  const tasks = [
    [
      "search",
      "待补充中国货源",
      state.items.filter((i) => ["candidate", "sourcing"].includes(i.status))
        .length,
      "去找货",
      "#sourcing",
    ],
    [
      "bag",
      "待整理文案与发布",
      state.items.filter((i) => ["matched", "listing_draft"].includes(i.status))
        .length,
      "去上架",
      "#listings",
    ],
    [
      "truck",
      "待采购与物流跟进",
      state.orders.filter((o) => !["delivered", "cancelled"].includes(stage(o)))
        .length,
      "看订单",
      "#orders",
    ],
  ];
  return `<div class="bottom-grid"><section class="panel"><div class="panel-header"><h2>接下来，做这些</h2><span class="subtle">让业务有序向前</span></div>${tasks.map(([glyph, title, count, label, href]) => `<div class="task-row"><span class="task-bullet">${icon(glyph)}</span><div><h3>${title}</h3><p>${count ? `${count} 件任务等待处理` : "当前没有待处理任务"}</p></div><a class="button small" href="${href}">${label} ${icon("arrow")}</a></div>`).join("")}</section><section class="panel"><div class="panel-header"><h2>好物的旅程</h2><span class="subtle">采购与履约</span></div><div class="route-card"><div class="country">CN<small>中国采购</small></div><div class="route-line">跨境运输</div><div class="country">JP<small>日本验收</small></div><div class="route-line">境内配送</div><div class="country">♡<small>送达买家</small></div></div><div class="note-strip">订单产生后采购，商品经日本收货验收后发给买家。</div></section></div>`;
}
function ordersTable() {
  let rows = state.orders.filter(
    (o) =>
      (state.filter === "all" ||
        (state.filter === "active"
          ? !["delivered", "cancelled"].includes(stage(o))
          : stage(o) === state.filter)) &&
      `${o.mercari_order_id} ${state.items.find((i) => i.id === o.item_id)?.japan_title || ""}`
        .toLowerCase()
        .includes(state.query.toLowerCase()),
  );
  const count = rows.length;
  state.page = Math.min(
    Math.max(1, state.page),
    Math.max(1, Math.ceil(count / 8)),
  );
  rows = rows.slice((state.page - 1) * 8, state.page * 8);
  return `<section class="panel"><div class="panel-header"><h2>全部订单</h2><span class="subtle">两段物流 · 全程有记录</span></div><div class="tabs" role="tablist" aria-label="订单状态">${[
    ["all", "全部订单"],
    ["active", "进行中"],
    ["awaiting_purchase", "待采购"],
    ["inspection_issue", "验收异常"],
    ["delivered", "已送达"],
    ["cancelled", "已取消"],
  ]
    .map(
      ([k, label]) =>
        `<button class="tab ${state.filter === k ? "active" : ""}" data-action="filter" data-id="${k}" role="tab" aria-selected="${state.filter === k}">${label}<span class="count">${state.orders.filter((o) => k === "all" || (k === "active" ? !["delivered", "cancelled"].includes(stage(o)) : stage(o) === k)).length}</span></button>`,
    )
    .join(
      "",
    )}</div><div class="table-toolbar"><div class="search-wrap">${icon("search")}<input type="search" id="search" aria-label="搜索订单" placeholder="搜索订单号或商品名称…" value="${esc(state.query)}"></div><button class="button small" data-action="reset-filters">清除筛选</button><button class="button small" data-action="refresh">${icon("refresh")}刷新</button></div>${
    rows.length
      ? `<div class="table-scroll"><table><thead><tr><th>订单 / 商品</th><th>成交金额</th><th>中国采购</th><th>中国 → 日本</th><th>日本 → 买家</th><th>操作</th></tr></thead><tbody>${rows
          .map((o) => {
            const item = state.items.find((i) => i.id === o.item_id);
            return `<tr><td><button class="product-button" data-action="order" data-id="${esc(o.id)}"><span class="product-name">${esc(o.mercari_order_id)}</span><span class="product-code">${esc(item?.japan_title || "商品")} · ${o.quantity} 件</span></button></td><td>${money(o.sold_price_jpy)}<div class="price-sub">${dateText(o.created_at)}</div></td><td>${badge(o.fulfillment_status)}${o.actual_purchase_price_cny ? `<div class="price-sub">实付 CN¥ ${n(o.actual_purchase_price_cny, 2)}</div>` : ""}</td><td>${badge(o.inbound_status)}<div class="price-sub">${esc(o.china_tracking_number || "尚未登记运单")}</div></td><td>${badge(o.domestic_status)}</td><td><button class="row-action" data-action="order" data-id="${esc(o.id)}">跟进订单 ${icon("arrow")}</button></td></tr>`;
          })
          .join("")}</tbody></table></div>`
      : empty(
          count || state.query || state.filter !== "all"
            ? "没有符合条件的订单"
            : "等待第一笔成交",
          state.query || state.filter !== "all"
            ? "切换筛选条件查看其他订单。"
            : "商品发布后，在这里登记订单并跟进采购与物流。",
          state.query || state.filter !== "all" ? null : "new-order",
          state.query || state.filter !== "all" ? "清除筛选" : "登记订单",
        )
  }<div class="table-footer"><span>共 ${count} 单</span><div class="pagination"><button aria-label="上一页" data-action="prev-page" ${state.page <= 1 ? "disabled" : ""}>‹</button><span class="page-number">${state.page}</span><button aria-label="下一页" data-action="next-page" ${state.page * 8 >= count ? "disabled" : ""}>›</button></div></div></section>`;
}
function siteDirectory() {
  return `<div class="notice">闲鱼支持通过本机浏览器自动搜索；搜索结果需人工核对。同款确认、供货核实和商品发布由你最终确认，记录统一保存在本工作台。</div><h2 class="site-section">日本 · 发现值得带回的好物</h2><div class="site-grid">${state.japan.map((s) => `<article class="panel site-card"><div class="panel-header"><span class="site-letter">${esc(s.name[0])}</span><span class="status">${esc(s.phase)}</span></div><h3>${esc(s.name)}</h3><p>${esc(s.kind)} · 已录入 ${state.items.filter((i) => i.japan_site === s.id).length} 件</p>${external(s.url, "前往选品")}</article>`).join("")}</div><h2 class="site-section">中国 · 为选品寻找同款货源</h2><div class="site-grid">${state.china.map((s) => `<article class="panel site-card"><div class="panel-header"><span class="site-letter">${esc(s.name[0])}</span><span class="status">人工核验</span></div><h3>${esc(s.name)}</h3><p>${esc(s.mode)}</p>${external({ xianyu: "https://www.goofish.com/", xiaohongshu: "https://www.xiaohongshu.com/", dewu: "https://www.dewu.com/" }[s.id], "前往找货")}</article>`).join("")}</div>`;
}
function render() {
  nav();
  $("#main").innerHTML =
    heading() +
    (state.view === "discovery"
      ? discoveryView()
      : state.view === "sites"
        ? siteDirectory()
        : state.view === "orders"
          ? `${stats()}${typeof shopImportSection === "function" ? shopImportSection() : ""}${ordersTable()}`
          : `${state.view === "dashboard" ? workflowOverview() + stats() : ""}${itemTable()}${state.view === "dashboard" ? dashboardBottom() : ""}`);
  if (typeof enhanceBusinessView === "function") enhanceBusinessView();
}
function updateTableResults() {
  // Keep the search input mounted while typing, preserving IME composition and focus.
  const toolbar = $("#main .table-toolbar");
  if (!toolbar) return;
  const staging = document.createElement("div");
  staging.innerHTML = state.view === "orders" ? ordersTable() : itemTable();
  const nextToolbar = $(".table-toolbar", staging);
  toolbar.nextElementSibling.replaceWith(nextToolbar.nextElementSibling);
  const footer = $(".table-footer", toolbar.closest(".panel"));
  footer.replaceWith($(".table-footer", staging));
  $$('.tab[data-action="filter"]', toolbar.closest(".panel")).forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.id === state.filter);
    tab.setAttribute("aria-selected", String(tab.dataset.id === state.filter));
  });
}
function route() {
  const key = location.hash.slice(1);
  state.view = views[key] ? key : "dashboard";
  state.filter = "all";
  state.query = "";
  state.page = 1;
  $("#sidebar").classList.remove("open");
  render();
}

// 表单和详情层。
const field = (
  name,
  label,
  {
    type = "text",
    value = "",
    placeholder = "",
    required = false,
    min,
    max,
    step,
    full = false,
    hint = "",
    options,
    rows = 3,
  } = {},
) => {
  const attrs = `name="${esc(name)}" id="f-${esc(name)}" ${required ? "required" : ""} ${min != null ? `min="${min}"` : ""} ${max != null ? (type === "text" || type === "textarea" ? `maxlength="${max}"` : `max="${max}"`) : ""} ${step ? `step="${step}"` : ""}`;
  const control = options
    ? `<select ${attrs}>${options
        .map((o) => {
          const [v, t] = Array.isArray(o) ? o : [o, o];
          return `<option value="${esc(v)}" ${String(value) === String(v) ? "selected" : ""}>${esc(t)}</option>`;
        })
        .join("")}</select>`
    : type === "textarea"
      ? `<textarea ${attrs} rows="${rows}" placeholder="${esc(placeholder)}">${esc(value)}</textarea>`
      : `<input ${attrs} type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${type === "url" ? 'inputmode="url"' : ""}>`;
  return `<label class="field ${full ? "full" : ""}"><span>${esc(label)}${required ? '<i class="required">*</i>' : ""}</span>${control}${hint ? `<small>${esc(hint)}</small>` : ""}</label>`;
};
const errorBox = '<div class="form-error" role="alert"></div>';
const formActions = (label = "保存", cancel = true) =>
  `${errorBox}<div class="form-actions">${cancel ? '<button class="button" type="button" data-action="close-modal">取消</button>' : ""}<button class="button primary" type="submit">${icon("check")}${label}</button></div>`;
function updateInert() {
  const open = !!$(".overlay");
  $(".app-shell").inert = open;
  $("#sidebar").inert = open;
  const drawer = $(".drawer-overlay");
  if (drawer) drawer.inert = !!$(".modal-overlay");
  document.body.style.overflow = open ? "hidden" : "";
}
function focusFirst(root) {
  setTimeout(
    () =>
      $(
        "input:not([type=hidden]):not([type=checkbox]), select, textarea, button",
        root,
      )?.focus(),
    30,
  );
}
function modal(title, subtitle, body, wide = false) {
  closeModal(false);
  returnFocus = document.activeElement;
  const layer = document.createElement("div");
  layer.className = "overlay modal-overlay";
  layer.innerHTML = `<section class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-header"><div><h2>${esc(title)}</h2><p class="modal-subtitle">${esc(subtitle)}</p></div><button class="icon-button" data-action="close-modal" aria-label="关闭弹窗">${icon("close")}</button></div><div class="modal-body">${body}</div></section>`;
  $("#overlay-root").append(layer);
  updateInert();
  focusFirst($(".modal-body", layer));
}
function closeModal(focus = true, force = false) {
  if (!force && $('.modal-overlay form[data-busy="true"]')) {
    toast("正在保存，请稍候。");
    return;
  }
  $(".modal-overlay")?.remove();
  updateInert();
  if (focus && returnFocus?.isConnected) returnFocus.focus();
}
function closeDrawer() {
  if ($(".modal-overlay")) {
    closeModal();
    return;
  }
  if ($('.drawer-overlay form[data-busy="true"]')) {
    toast("正在保存，请稍候。");
    return;
  }
  drawerSerial++;
  $(".drawer-overlay")?.remove();
  state.detail = null;
  state.order = null;
  updateInert();
  $("#main").focus({ preventScroll: true });
}
function newItem() {
  modal(
    "新增日本选品",
    "先记下好物，接下来一起找到合适的中国货源。",
    `<form data-form="candidate"><div class="form-grid">${field("japan_site", "选品平台", { options: state.japan.map((s) => [s.id, s.name]), required: true })}${field("japan_price_jpy", "日本参考价（JPY）", { type: "number", min: 1, step: 1, placeholder: "例如 3980" })}${field("japan_title", "商品名称", { required: true, full: true, placeholder: "输入日本商品标题" })}${field("japan_url", "日本商品链接", { type: "url", required: true, full: true, placeholder: "https://jp.mercari.com/item/…" })}${field("japan_image_url", "参考图片链接", { type: "url", full: true, placeholder: "可选，填写图片的完整链接" })}${field("note", "选品备注", { type: "textarea", full: true, placeholder: "值得参考的款式、规格、同行信息…" })}</div>${formActions("添加选品")}</form>`,
  );
}
async function openItem(id, tab = "overview") {
  const serial = ++drawerSerial;
  state.order = null;
  state.detailTab = tab;
  $(".drawer-overlay")?.remove();
  const layer = document.createElement("div");
  layer.className = "overlay drawer-overlay";
  layer.innerHTML = `<section class="drawer" role="dialog" aria-modal="true" aria-label="商品详情"><div class="drawer-header"><h2>商品详情</h2><button class="icon-button" data-action="close-drawer" aria-label="关闭商品详情">${icon("close")}</button></div><div class="drawer-body"><div class="loading"><span class="spinner"></span>读取商品详情…</div></div></section>`;
  $("#overlay-root").prepend(layer);
  updateInert();
  try {
    const detail = await api(`/api/items/${encodeURIComponent(id)}`);
    if (serial !== drawerSerial) return;
    state.detail = detail;
    renderItemDetail();
    $(".drawer-header button")?.focus();
  } catch (error) {
    if (serial !== drawerSerial) return;
    $(".drawer-body").innerHTML = empty(
      "读取商品失败",
      error.message,
      "retry-item",
      "重试",
    );
    $(".drawer-body").dataset.retry = id;
  }
}
async function reloadDetail(tab = state.detailTab) {
  if (!state.detail) return;
  const id = state.detail.item.id,
    serial = drawerSerial;
  const detail = await api(`/api/items/${encodeURIComponent(id)}`);
  if (serial !== drawerSerial) return;
  state.detail = detail;
  state.detailTab = tab;
  renderItemDetail();
}
function renderItemDetail() {
  const { item, china_sources: sources, listing_draft: draft } = state.detail;
  const thumbItem = state.items.find((i) => i.id === item.id) || item;
  const tabs = [
    ["overview", "商品概况"],
    ["sources", `中国货源 (${sources.length})`],
    ["listing", "上架草稿"],
    ["orders", "关联订单"],
  ];
  $(".drawer").innerHTML =
    `<div class="drawer-header"><div><h2>商品详情</h2><p class="drawer-subtitle">PRD-${esc(item.id.slice(0, 8).toUpperCase())} · ${dateText(item.created_at)}</p></div><button class="icon-button" data-action="close-drawer" aria-label="关闭商品详情">${icon("close")}</button></div><div class="tabs drawer-tabs" role="tablist" aria-label="商品详情页签">${tabs.map(([k, t]) => `<button class="tab ${state.detailTab === k ? "active" : ""}" data-action="detail-tab" data-id="${k}" role="tab" aria-selected="${state.detailTab === k}">${t}</button>`).join("")}</div><div class="drawer-body"><div class="detail-summary">${thumb(thumbItem)}<div><h3>${esc(item.japan_title)}</h3>${badge(item.status)}${siteChip(item.japan_site)}</div></div>${state.detailTab === "sources" ? sourceDetails() : state.detailTab === "listing" ? listingDetail() : state.detailTab === "orders" ? itemOrders() : overviewDetail()}</div>`;
  if (typeof appendItemTools === "function") appendItemTools();
  if (state.detailTab === "listing" && !draft) {
    syncVariants();
    updateProfit();
  }
}
const kv = (label, value) =>
  `<div class="kv"><small>${esc(label)}</small><span>${value}</span></div>`;
function overviewDetail() {
  const { item, china_sources: sources, listing_draft: draft } = state.detail;
  const next = ["candidate", "sourcing"].includes(item.status)
    ? ["sources", "完善中国货源"]
    : item.status === "matched"
      ? ["listing", "创建上架草稿"]
      : item.status === "listing_draft"
        ? ["listing", "检查草稿与登记发布"]
        : ["orders", "查看关联订单"];
  return `<section class="detail-card"><div class="detail-card-header"><h3>日本选品信息</h3>${external(item.japan_url, "查看日本商品")}</div><div class="detail-grid">${kv("选品平台", siteChip(item.japan_site))}${kv("参考价格", money(item.japan_price_jpy))}${kv("中国货源", `${sources.length} 个候选 · ${sources.filter((s) => s.match_status === "confirmed").length} 个已核验`)}${kv("当前阶段", badge(item.status))}</div>${item.note ? `<div class="form-section">选品备注</div><p class="description">${esc(item.note)}</p>` : ""}</section>${draft ? `<section class="detail-card"><div class="detail-card-header"><h3>销售与利润</h3>${draft.listing_url ? external(draft.listing_url, "查看店铺商品") : badge("listing_draft")}</div><div class="detail-grid">${kv("店铺售价", money(draft.price_jpy))}${kv("预估利润", `<span class="profit ${draft.estimated_profit_cny < 0 ? "negative" : ""}">${money(draft.estimated_profit_cny, "CNY")}</span>`)}${kv("销售库存", `${draft.inventory_quantity} 件`)}${kv("销售方式", draft.reservation_sale ? "预约销售" : "普通销售")}</div></section>` : ""}<div class="detail-card"><div class="detail-card-header"><div><h3>继续推进这件好物</h3><p class="muted-note">${item.status === "listed" ? "成交后登记订单，再跟进采购与物流。" : "已保存的信息会沿着商品流程保留。"}</p></div><button class="button soft" data-action="detail-tab" data-id="${next[0]}">${next[1]} ${icon("arrow")}</button></div></div>`;
}
function sourcePhotoStats(images = []) {
  const active = images.filter(image => !image.excluded_at);
  const uniqueCount = new Set(active.map(image => image.sha256 || image.id)).size;
  const realCount = new Set(active.filter(image => image.image_role === "real_photo").map(image => image.sha256 || image.id)).size;
  return {uniqueCount, realCount, targetMet: uniqueCount >= 5 && realCount >= 1};
}
function sourceImageTile(im, canEdit) {
  const excluded = Boolean(im.excluded_at);
  const role = {real_photo:"货源实拍",catalog:"商品图",screenshot:"页面截图",other:"其他"}[im.image_role];
  const vision = im.vision_review || {};
  const visionAction = {keep:"模型已保留",exclude:"模型已排除"}[vision.decision || vision.suggested_action];
  const visionKind = {catalog:"商品图",real_photo:"疑似实物拍摄",screenshot:"页面截图",promotional:"宣传图",recommendation:"疑似推荐商品图",packaging:"包装图",other:"其他",uncertain:"无法判断"}[vision.image_kind];
  const visionSummary = visionAction ? `<p class="muted-note"><strong>千问处理结果：${esc(visionAction)}</strong>${visionKind ? ` · ${esc(visionKind)}` : ""}${vision.relevance_score != null ? ` · 相关度 ${esc(vision.relevance_score)}` : ""}${vision.quality_score != null ? ` · 清晰度 ${esc(vision.quality_score)}` : ""}${vision.duplicate_of ? ` · 疑似重复 ${esc(vision.duplicate_of)}` : ""}${vision.reason ? `<br>${esc(vision.reason)}` : ""}${vision.real_photo_likelihood === "likely" ? "<br>已自动标记为实物图；上架前可再检查。" : ""}</p>` : "";
  const buttons = !canEdit ? "" : excluded
    ? `<button class="button small" data-action="restore-source-image" data-id="${esc(im.id)}">恢复为待核对图片</button>`
    : `<button class="button small" data-action="${im.image_role === "real_photo" ? "unset-image-real" : "set-image-real"}" data-id="${esc(im.id)}">${im.image_role === "real_photo" ? "取消实物图标记" : "核实为实物图"}</button><button class="button small" data-action="exclude-source-image" data-id="${esc(im.id)}">排除此图</button>`;
  return `<div class="image-tile ${excluded ? "excluded-image" : ""}"><a href="${esc(im.source_file_url)}" target="_blank" rel="noopener"><img src="${esc(im.listing_file_url)}" loading="lazy" alt="${esc(im.original_filename)}"></a><small>${excluded ? "已排除 · " : ""}${esc(role)} · ${im.width}×${im.height}</small>${im.collection_note ? `<p class="muted-note">${esc(im.collection_note)}</p>` : ""}${visionSummary}${excluded ? `<p class="muted-note">${esc(im.exclusion_reason)}</p>` : ""}${buttons}</div>`;
}
function sourceDetails() {
  const { item, china_sources: sources } = state.detail;
  const canEdit =
    !item.archived_at &&
    ["candidate", "sourcing", "matched", "listing_draft", "listed", "withdrawn"].includes(
      item.status,
    );
  return `<div class="section-title"><h3>中国候选货源</h3>${canEdit ? `<div class="inline-actions"><button class="button small primary" data-action="china-search">${icon("search")}自动找货</button><button class="button small" data-action="new-source">${icon("plus")}手工录入货源</button></div>` : ""}</div>${sources.length ? sources.map((s) => `<section class="detail-card" data-source-id="${esc(s.id)}"><div class="detail-card-header"><div>${siteChip(s.china_site)} <span style="margin-left:8px">${badge(s.match_status)}</span></div>${external(s.source_url, "查看货源")}</div><h3>${esc(s.source_title || "未填写货源标题")}</h3><div class="detail-grid">${kv("页面价格", money(s.price_cny, "CNY"))}${kv("供货情况", badge(s.availability_status))}${s.account_note ? kv("账号备注", esc(s.account_note)) : ""}${s.availability_checked_at ? kv("最近核验", dateText(s.availability_checked_at)) : ""}</div>${s.match_note ? `<p class="description" style="margin-top:15px">${esc(s.match_note)}</p>` : ""}<div class="form-section"><div class="section-title"><span>可用图片 · ${sourcePhotoStats(s.images).uniqueCount} 张${s.images.some(im => im.excluded_at) ? ` · 已排除 ${s.images.filter(im => im.excluded_at).length} 张` : ""}</span><div class="inline-actions">${canEdit && state.imageReviewAvailable ? `<button class="button small" data-action="review-source-images" data-id="${esc(s.id)}">${icon("search")}千问筛图</button>` : ""}<button class="button small" data-action="upload-image" data-id="${esc(s.id)}">${icon("upload")}上传图片</button></div></div></div>${s.images.length ? `<div class="image-grid">${s.images.map((im) => sourceImageTile(im, canEdit)).join("")}</div>` : '<p class="muted-note">导入闲鱼货源后会自动采集商品详情图候选；如有评论区实拍，也会一并尝试读取。也可上传本地图片或截图。</p>'}${canEdit ? `<div class="form-actions"><button class="button ${s.match_status === "confirmed" ? "" : "soft"}" data-action="confirm-source" data-id="${esc(s.id)}">${icon("check")}${s.match_status === "confirmed" ? "更新核验信息" : "确认同款与页面价格"}</button></div>` : ""}</section>`).join("") : empty("还没有中国货源", "点“自动找货”，系统会按当前日本商品的标题和说明生成搜索词并读取闲鱼候选。只有你已找到具体货源页面时，才需要手工录入链接。", null, null)}<p class="muted-note">搜索结果需要人工核对是否同款、规格和成色；确认后再记录价格。订单产生后再核实并采购。</p>`;
}
function newSource() {
  modal(
    "手工登记已找到的货源",
    "仅在你已经找到具体的中国商品页面时填写。自动找货会根据当前日本商品生成搜索词，不需要填写货源链接。",
    `<form data-form="source"><div class="form-grid">${field("china_site", "货源平台", { options: state.china.map((s) => [s.id, s.name]), required: true })}${field("price_cny", "页面价格（CNY）", { type: "number", min: 0.01, step: 0.01, placeholder: "例如 85.00" })}${field("source_url", "已找到的货源页面链接", { type: "url", required: true, full: true, placeholder: "https://…" })}${field("source_title", "货源标题", { full: true, placeholder: "商品名、型号与规格" })}${field("account_note", "账号 / 代购备注", { type: "textarea", full: true, placeholder: "小红书或得物代购账号、卖家信息…" })}</div>${formActions("保存手工货源")}</form>`,
  );
}
function confirmSource(id) {
  const source = state.detail.china_sources.find((s) => s.id === id);
  modal(
    "确认同款与页面价格",
    "核对颜色、尺寸、版本和成色，记录本次人工核验依据。",
    `<form data-form="confirm-source" data-id="${esc(id)}"><div class="notice">${esc(source.source_title || "当前货源")}<br>请打开来源页面确认当前信息：${external(source.source_url, "查看货源")}</div><div class="form-grid">${field(
      "availability_status",
      "当前供货情况",
      {
        options: [
          ["available", "当前有货"],
          ["unknown", "暂不确定"],
          ["unavailable", "当前无货"],
        ],
        value: source.availability_status,
        required: true,
      },
    )}${field("price_cny", "当前页面价格（CNY）", { type: "number", min: 0.01, step: 0.01, value: source.price_cny ?? "", hint: "确认有货时必须填写当前价格" })}${field("match_note", "同款核验依据", { type: "textarea", full: true, required: true, value: source.match_note, placeholder: "例如：与日本候选颜色、尺寸、包装和版本一致" })}</div>${formActions("保存核验结果")}</form>`,
  );
}
function uploadImage(id) {
  const source = state.detail.china_sources.find((s) => s.id === id);
  modal(
    "上传货源图片",
    "支持 JPEG、PNG、WebP；单张不超过 20 MB。",
    `<form data-form="upload" data-id="${esc(id)}"><div class="form-grid"><label class="field full"><span>选择图片<i class="required">*</i></span><input type="file" name="file" accept="image/jpeg,image/png,image/webp" required multiple><small>可同时选择多张；保留来源原图并生成白底 JPEG。</small></label>${field(
      "image_role",
      "图片类型",
      {
        value: "other",
        options: [
          ["real_photo", "货源实拍"],
          ["catalog", "商品图"],
          ["screenshot", "页面截图"],
          ["other", "其他"],
        ],
      },
    )}${field("source_page_url", "来源页面", { type: "url", required: true, value: source.source_url, full: true })}${field("source_asset_url", "原图链接（选填）", { type: "url", full: true, placeholder: "https://…", hint: "多张图片若各有原图链接，请分次上传。" })}</div><div id="upload-progress" class="form-hint" aria-live="polite"></div>${formActions("上传并生成上架版")}</form>`,
  );
}

function listingDetail() {
  const { item, listing_draft: draft, china_sources: sources } = state.detail;
  if (draft) return savedListing(draft);
  if (item.status !== "matched")
    return empty(
      "先完成同款核验",
      "添加中国货源，确认同款与价格后，即可整理上架草稿。",
      "go-sources",
      "查看中国货源",
    );
  const confirmed = sources.filter(
    (s) =>
      s.match_status === "confirmed" && s.price_cny != null && !s.archived_at,
  );
  if (!confirmed.length)
    return empty(
      "还没有可用的核验货源",
      "请选择一个货源记录当前价格，再创建上架草稿。",
      "go-sources",
      "核验中国货源",
    );
  return `${preparationSummary()}<div class="detail-card">${draftForm(null, confirmed)}</div>`;
}
function preparationSummary() {
  const p = state.detail.listing_preparation;
  if (!p) return "";
  const status = p.automation?.status,
    generated = p.automation?.generated_at
      ? `已自动生成 · ${dateText(p.automation.generated_at)}`
      : status === "stale"
        ? "选品、货源或图片有更新，需要重新生成"
        : "规则资料已整理，待保存自动生成记录";
  return `<section class="detail-card"><div class="detail-card-header"><div><h3>自动生成的上架资料包</h3><p class="muted-note">${esc(generated)} · 普通销售、单规格</p></div><button class="button small" data-action="refresh-preparation" data-id="${esc(state.detail.item.id)}">${icon("refresh")}重新生成</button></div><p class="muted-note">系统根据已核验的日本选品、中国货源和通用设置生成标题、说明、分类建议及管理码。售价仅作建议，库存预填 1；成色和图片需要核对。</p><div class="detail-grid" style="margin-top:14px">${p.fields.map(f => kv(f.label, `${f.ready ? "✓ 已带入" : "待补充"}<small class="subtle" style="display:block">${esc(f.origin)}</small>`)).join("")}</div><p class="form-hint">已收集 ${p.photo_collection.unique_count} 张不同图片，其中实物图 ${p.photo_collection.real_photo_count} 张；收图目标为至少 5 张且有实物图。已核验的图片不会自动勾选上架。</p>${p.notes.map(note => `<div class="notice warm">${esc(note)}</div>`).join("")}</section>`;
}
function imagePicker(sourceId, selected = []) {
  const source = state.detail.china_sources.find((s) => s.id === sourceId);
  const images = (source?.images || []).filter(im => !im.excluded_at);
  return images.length
    ? `<div class="image-grid">${images.map((im) => `<label class="image-tile image-pick"><input type="checkbox" name="image_asset_ids" value="${esc(im.id)}" ${selected.includes(im.id) ? "checked" : ""} aria-label="选择图片 ${esc(im.original_filename)}"><img src="${esc(im.listing_file_url)}" alt="${esc(im.original_filename)}"><small>${esc(im.original_filename)}</small></label>`).join("")}</div>`
    : `<div class="notice warm">这个货源还没有图片。请先到“中国货源”上传至少一张图片，再创建草稿。</div>`;
}
function draftForm(draft, confirmed) {
  const d = draft || state.detail.listing_preparation?.values || {},
    sourceId = d.china_source_id || confirmed[0].id;
  const v = (key, defaultValue = "") => d[key] ?? defaultValue;
  return `<form data-form="draft" ${draft ? `data-id="${esc(draft.id)}"` : ""}><h3>${draft ? "编辑上架草稿" : "创建上架草稿"}</h3><p class="muted-note" style="margin:5px 0 18px">整理商品资料与定价，保存后可继续编辑，正式发布由你在店铺完成。店铺编辑会自动保存草稿，开始自动填写前会再次展示资料。</p><div class="form-grid">${field("china_source_id", "使用的中国货源", { full: true, required: true, value: sourceId, options: confirmed.map((s) => [s.id, `${siteName(s.china_site)} · ${s.source_title || "未命名货源"} · CN¥ ${n(s.price_cny, 2)}`]) })}</div><div class="form-section">商品图片 <span class="subtle">勾选需要用于本次上架的图片</span></div><div id="draft-images">${imagePicker(sourceId, d.image_asset_ids || [])}</div>${d.image_refs?.length ? `<p class="form-hint">保留 ${d.image_refs.length} 张此前登记的外部图片。</p>` : ""}<div class="form-section">日文商品资料</div><div class="form-grid">${field("title_ja", "日文商品名", { required: true, full: true, value: v("title_ja", state.detail.item.japan_title), max: 130, hint: "最多 130 字符，请核对型号与规格" })}${field("description_ja", "日文商品说明", { type: "textarea", full: true, value: v("description_ja"), max: 3000, rows: 5, placeholder: "商品の状態、サイズ、内容物、発送について…" })}${field("category", "分类", { required: true, value: v("category"), placeholder: "大分类 > 中分类 > 末级分类", hint: "使用平台完整分类路径，已生成的分类建议请核对" })}${field("brand", "品牌", { value: v("brand"), placeholder: "选填" })}${field("condition", "商品状态 / 成色", { required: true, value: v("condition"), options: [["", "请选择并核对成色"], ...["新品、未使用", "未使用に近い", "目立った傷や汚れなし", "やや傷や汚れあり", "傷や汚れあり", "全体的に状態が悪い"].map(v => [v, v])] })}${field("inventory_quantity", "店铺库存（件）", { type: "number", required: true, min: 1, step: 1, value: v("inventory_quantity", 1) })}${field("max_quantity_per_order", "每单限购（件）", { type: "number", min: 1, step: 1, value: v("max_quantity_per_order"), placeholder: "不限制时留空" })}${field("management_code", "商品管理码", { value: v("management_code") })}${field("jan_code", "JAN 码", { value: v("jan_code") })}</div><details class="form-section"><summary>分类专属属性（按证据填写）</summary><p class="form-hint">选择的 Mercari 分类可能要求不同属性。填写日本商品页或中国货源明确提供的信息；未知项留空，不要猜。字段名可以用表单检查时显示的日文键或标签。</p>${field("category_attributes_json", "属性 JSON", { type: "textarea", full: true, rows: 5, value: JSON.stringify(v("category_attributes", {}), null, 2), placeholder: '{"attributes.material":{"value":"PVC","source":"货源详情","evidence":"材质：PVC"}}' })}</details><label class="switch-row"><input type="checkbox" name="multi_variant" ${d.multi_variant ? "checked" : ""}>包含多个规格</label><div id="variant-fields" class="${d.multi_variant ? "" : "hidden"}">${variantEditor(d)}</div><div class="form-section">销售方式</div><label class="switch-row"><input type="checkbox" name="reservation_sale" ${d.reservation_sale ? "checked" : ""}>启用预约销售</label><div id="reservation-fields" class="${d.reservation_sale ? "" : "hidden"}"><p class="form-hint">预约日期按日本时间核验，开始日须晚于今天。启用后请填写完整日期。</p><div class="form-grid">${field("reservation_start_date", "预约开始日", { type: "date", value: v("reservation_start_date") })}${field("reservation_end_date", "预约结束日", { type: "date", value: v("reservation_end_date") })}${field("reservation_release_date", "发售日", { type: "date", value: v("reservation_release_date") })}${field("reservation_cancel_deadline", "取消期限", { type: "date", value: v("reservation_cancel_deadline") })}${field(
    "reservation_delivery_timing",
    "预计送达时点",
    {
      value: v("reservation_delivery_timing", "after_release"),
      options: [
        ["after_release", "发售日之后"],
        ["release_date", "发售日当天"],
      ],
    },
  )}</div></div><div class="form-section">配送设置</div><div class="form-grid">${field("shipping_method", "配送方式", { required: true, value: v("shipping_method", state.listingDefaults?.shipping_method), placeholder: "填写店铺配送方式" })}${field("shipping_payer", "运费承担方", { required: true, value: v("shipping_payer", state.listingDefaults?.shipping_payer), placeholder: "填写店铺对应选项" })}${field("shipping_origin", "日本发货地区", { required: true, value: v("shipping_origin", state.listingDefaults?.shipping_origin), placeholder: "例如 東京都" })}${field("handling_days", "发货所需天数", { required: true, value: v("handling_days", state.listingDefaults?.handling_days), placeholder: "填写店铺对应选项" })}</div><div class="form-section">销售价格</div><p class="form-hint">售价先带入日本参考价作为建议，请确认本次实际售价。</p><div class="form-grid">${field("price_jpy", "店铺售价（JPY）", { type: "number", required: true, min: 300, max: 9999999, step: 1, value: v("price_jpy", state.detail.item.japan_price_jpy || ""), placeholder: "300–9,999,999" })}</div><details class="form-section"><summary>内部利润核算（选填，可稍后补充）</summary><p class="form-hint">这些数值不会填写到店铺。成本未补齐时显示“待核算”，留空不会按零成本计算。</p><div class="form-grid">${field("exchange_rate_cny_per_jpy", "1 日元折合人民币", { type: "number", min: 0.000001, step: "any", value: v("exchange_rate_cny_per_jpy"), placeholder: "填写实际汇率，如 0.047" })}${field("mercari_fee_percent", "店铺手续费率（%）", { type: "number", required: true, min: 0, max: 99.999, step: "any", value: d.mercari_fee_rate != null ? Number((d.mercari_fee_rate * 100).toFixed(6)) : Number(((state.listingDefaults?.mercari_fee_rate ?? 0) * 100).toFixed(6)), placeholder: "填写本次实际费率" })}${field("estimated_china_to_japan_shipping_cny", "中国 → 日本运费（CNY）", { type: "number", min: 0, step: 0.01, value: v("estimated_china_to_japan_shipping_cny") })}${field("shipping_jpy", "日本境内运费（JPY）", { type: "number", min: 0, step: 1, value: v("shipping_jpy") })}${field("other_costs_jpy", "其他费用（JPY）", { type: "number", min: 0, step: 1, value: v("other_costs_jpy") })}</div></details><div id="profit-preview" aria-live="polite"></div>${formActions(draft ? "保存修改" : "保存上架草稿", !!draft)}</form>`;
}
async function editListingDefaults() {
  const defaults = state.listingDefaults || (await api("/api/listing/defaults"));
  state.listingDefaults = defaults;
  modal(
    "通用上架设置",
    "保存后会自动填入新建草稿；每件商品仍可单独修改。",
    `<form data-form="listing-defaults"><div class="form-section">配送默认值</div><div class="form-grid">${field("shipping_method", "配送方式", { required: true, value: defaults.shipping_method })}${field("shipping_payer", "运费承担方", { required: true, value: defaults.shipping_payer })}${field("shipping_origin", "日本发货地区", { required: true, value: defaults.shipping_origin })}${field("handling_days", "发货所需天数", { required: true, value: defaults.handling_days })}${field("mercari_fee_percent", "店铺手续费率（%）", { type: "number", required: true, min: 0, max: 99.999, step: "any", value: Number((defaults.mercari_fee_rate * 100).toFixed(6)) })}</div><p class="form-hint">当前值来自之前保存的上架草稿；新建草稿时自动填入，可逐件修改。</p>${formActions("保存通用设置", false)}</form>`,
    false,
  );
}
function updateProfit() {
  const form = $('form[data-form="draft"]');
  if (!form) return;
  const fd = new FormData(form),
    number = (k) => Number(fd.get(k) || 0);
  const source = state.detail.china_sources.find(
    (s) => s.id === fd.get("china_source_id"),
  );
  const price = number("price_jpy"),
    rate = number("exchange_rate_cny_per_jpy"),
    fee = number("mercari_fee_percent") / 100;
  const ready =
    rate > 0 && price >= 300 && ["mercari_fee_percent", "estimated_china_to_japan_shipping_cny", "shipping_jpy", "other_costs_jpy"].every(k => fd.get(k) !== "");
  const revenue = price * rate,
    cost =
      (price * fee + number("shipping_jpy") + number("other_costs_jpy")) *
        rate +
      (source?.price_cny || 0) +
      number("estimated_china_to_japan_shipping_cny");
  const profit = Math.round((revenue - cost) * 100) / 100,
    margin = revenue ? (profit / revenue) * 100 : 0;
  $("#profit-preview").innerHTML =
    `<div class="profit-preview"><div><small>单件预估利润 · CNY</small><strong class="${ready && profit < 0 ? "negative" : ""}">${ready ? `¥ ${n(profit, 2)}` : "待核算"}</strong><p>${ready ? `货源成本 CN¥ ${n(source?.price_cny, 2)} · 已计入填写的费用` : "补齐汇率及各项成本后试算，可稍后补充"}</p></div><div><small>预估利润率</small><strong class="margin-value ${ready && profit < 0 ? "negative" : ""}">${ready ? `${n(margin, 1)}%` : "—"}</strong></div></div>`;
}
function variantRow(variant = {}) {
  return `<div class="variant-row" data-original="${esc(JSON.stringify(variant))}"><label class="field"><span>规格名称</span><input name="variant_name" value="${esc(variant.name || variant.title || "")}" placeholder="例如 红色 / 473ml"></label><label class="field"><span>库存数量</span><input name="variant_stock" type="number" min="0" step="1" value="${esc(variant.inventory_quantity ?? variant.quantity ?? 0)}"></label><button class="icon-button" type="button" data-action="remove-variant" aria-label="移除此规格">${icon("close")}</button></div>`;
}
function variantEditor(draft) {
  const variants = draft.inventory_variants?.length
    ? draft.inventory_variants
    : [{}];
  return `<div class="variant-list">${variants.map(variantRow).join("")}</div><button class="button small" type="button" data-action="add-variant">${icon("plus")}添加规格</button><p class="form-hint">店铺总库存自动汇总各规格数量，保存后可继续修改。</p>`;
}
function syncVariants() {
  const form = $('form[data-form="draft"]');
  if (!form) return;
  const enabled = form.elements.multi_variant.checked;
  const stock = form.elements.inventory_quantity;
  stock.readOnly = enabled;
  $$(".variant-row input", form).forEach((input) => {
    input.disabled = !enabled;
    input.required = enabled;
  });
  if (enabled)
    stock.value = $$('.variant-row input[name="variant_stock"]', form).reduce(
      (total, input) => total + Number(input.value || 0),
      0,
    );
}
function savedListing(d) {
  const source = state.detail.china_sources.find(
    (s) => s.id === d.china_source_id,
  );
  const images = (d.image_asset_ids || [])
    .map((id) => source?.images.find((im) => im.id === id))
    .filter(Boolean);
  const inventoryWarning = source?.availability_status === "unknown"
    ? `<div class="notice warm">中国货源库存尚未核实；草稿库存 ${d.inventory_quantity} 件仅为本地测试占位，店铺填表前请确认实际供货数量。</div>`
    : source?.availability_status === "unavailable"
      ? `<div class="notice warm">中国货源当前标记为无货；草稿库存 ${d.inventory_quantity} 件仅为占位，请勿据此发布。</div>`
      : "";
  return `<section class="detail-card"><div class="detail-card-header"><h3>${d.status === "listed" ? "已发布商品" : d.status === "withdrawn" ? "已下架商品" : "待发布草稿"}</h3>${d.status === "draft" ? `<button class="button small" data-action="edit-draft">编辑草稿</button>` : external(d.listing_url, "查看店铺商品")}</div>${inventoryWarning}${images.length ? `<div class="image-grid" style="margin-bottom:20px">${images.map((im) => `<a class="image-tile" href="${esc(im.listing_file_url)}" target="_blank" rel="noopener"><img src="${esc(im.listing_file_url)}" alt="上架商品图"></a>`).join("")}</div>` : ""}<div class="section-title"><h3>${esc(d.title_ja)}</h3><button class="copy-button" data-action="copy-title">${icon("copy")}复制</button></div><div class="description">${esc(d.description_ja || "未填写商品说明")}</div>${d.description_ja ? '<button class="copy-button" data-action="copy-description" style="margin-top:9px">复制说明</button>' : ""}<div class="profit-preview"><div><small>单件预估利润 · CNY</small><strong class="${d.estimated_profit_cny < 0 ? "negative" : ""}">${d.estimated_profit_cny == null ? "待核算" : `¥ ${n(d.estimated_profit_cny, 2)}`}</strong></div><div><small>店铺售价 · JPY</small><strong class="margin-value">¥ ${n(d.price_jpy)}</strong></div><div><small>利润率</small><strong class="margin-value ${d.estimated_profit_cny < 0 ? "negative" : ""}">${d.estimated_margin_pct == null ? "—" : `${n(d.estimated_margin_pct, 1)}%`}</strong></div></div>${d.multi_variant ? `<div class="form-section">商品规格</div><div class="detail-grid">${d.inventory_variants.map((variant) => kv(variant.name || variant.title || "未命名规格", `${Number(variant.inventory_quantity ?? variant.quantity ?? 0)} 件`)).join("")}</div>` : ""}<div class="form-section">商品与配送</div><div class="detail-grid">${kv("分类 / 品牌", `${esc(d.category)}${d.brand ? " · " + esc(d.brand) : ""}`)}${kv("成色", esc(d.condition))}${kv("店铺库存 / 每单限购", `${d.inventory_quantity} 件 / ${d.max_quantity_per_order || "不限"}`)}${kv("销售方式", d.reservation_sale ? "预约销售" : "普通销售")}${kv("配送方式", esc(d.shipping_method))}${kv("发货地区 / 时效", `${esc(d.shipping_origin)} / ${esc(d.handling_days)}`)}${kv("运费承担方", esc(d.shipping_payer))}${kv("中国货源价格", money(d.estimated_source_price_cny, "CNY"))}${kv("汇率 / 手续费", `${d.exchange_rate_cny_per_jpy == null ? "待补充" : `${d.exchange_rate_cny_per_jpy} CNY/JPY`} · ${n(d.mercari_fee_rate * 100, 2)}%`)}${kv("中国 → 日本 / 日本境内运费", `${d.estimated_china_to_japan_shipping_cny == null ? "待补充" : `CN¥ ${n(d.estimated_china_to_japan_shipping_cny, 2)}`} / ${d.shipping_jpy == null ? "待补充" : `JPY ${n(d.shipping_jpy)}`}`)}${kv("其他费用", d.other_costs_jpy == null ? "待补充" : `${n(d.other_costs_jpy)} JPY`)}${kv("管理码 / JAN", `${esc(d.management_code || "—")} / ${esc(d.jan_code || "—")}`)}</div>${d.reservation_sale ? `<div class="form-section">预约日期</div><div class="detail-grid">${kv("预约期间", `${esc(d.reservation_start_date)} → ${esc(d.reservation_end_date)}`)}${kv("发售日", esc(d.reservation_release_date))}${kv("取消期限", esc(d.reservation_cancel_deadline))}${kv("送达时点", d.reservation_delivery_timing === "release_date" ? "发售日当天" : "发售日之后")}</div>` : ""}</section>${d.status === "draft" ? `<section class="detail-card"><h3>完成店铺发布后，登记商品链接</h3><p class="muted-note" style="margin-bottom:14px">先在 Mercari Shops 检查并发布商品，再将实际链接填入这里，完成上架记录。</p><form data-form="publish" data-id="${esc(d.id)}">${field("listing_url", "已发布商品链接", { type: "url", required: true, placeholder: "https://mercari-shops.com/products/…" })}${formActions("登记为已上架", false)}</form></section>` : `<section class="detail-card"><div class="detail-card-header"><div><h3>收到订单后，开始跟进履约</h3><p class="muted-note">采购、运往日本、验收和境内发货逐步登记。</p></div><button class="button soft" data-action="new-order" data-id="${esc(d.item_id)}">${icon("plus")}登记订单</button></div></section>`}`;
}
function editDraft() {
  const draft = state.detail.listing_draft;
  const sources = state.detail.china_sources.filter(
    (s) =>
      s.match_status === "confirmed" && s.price_cny != null && !s.archived_at,
  );
  modal(
    "编辑上架草稿",
    "更新商品资料、图片与定价，保存后同步更新利润试算。",
    draftForm(draft, sources),
    true,
  );
  syncVariants();
  updateProfit();
}
function itemOrders() {
  const orders = state.orders.filter((o) => o.item_id === state.detail.item.id);
  return `<div class="section-title"><h3>关联订单 · ${orders.length} 单</h3>${state.detail.item.status === "listed" ? `<button class="button small" data-action="new-order" data-id="${esc(state.detail.item.id)}">${icon("plus")}登记订单</button>` : ""}</div>${orders.length ? orders.map((o) => `<section class="detail-card"><div class="detail-card-header"><div><h3>${esc(o.mercari_order_id)}</h3><p class="muted-note">${o.quantity} 件 · ${dateText(o.created_at)}</p></div>${badge(stage(o))}</div><div class="detail-card-header">${money(o.sold_price_jpy)}<button class="button small" data-action="order" data-id="${esc(o.id)}">跟进订单 ${icon("arrow")}</button></div></section>`).join("") : empty("暂无关联订单", "商品在店铺成交后，即可登记订单并跟进采购。")}`;
}
function newOrder(itemId = "") {
  const listed = state.items.filter((i) => i.status === "listed");
  if (!listed.length) {
    toast("请先登记至少一件商品为已上架，再创建订单。", true);
    return;
  }
  const item = listed.find((i) => i.id === itemId);
  modal(
    "登记店铺订单",
    "按店铺实际成交信息录入，随后跟进中国采购与物流。",
    `<form data-form="new-order"><div class="form-grid">${field("item_id", "成交商品", { options: [["", "请选择已上架商品"], ...listed.map((i) => [i.id, i.title_ja || i.japan_title])], required: true, full: true, value: item?.id || "" })}${field("mercari_order_id", "Mercari 订单号", { required: true, full: true, placeholder: "填写店铺订单编号" })}${field("quantity", "成交数量（件）", { type: "number", required: true, min: 1, step: 1, value: 1 })}${field("sold_price_jpy", "成交金额（JPY）", { type: "number", required: true, min: 1, step: 1, value: item?.price_jpy || "", hint: "填写本条商品对应的实际成交金额" })}</div>${formActions("登记订单")}</form>`,
  );
}
async function openOrder(id) {
  const order = state.orders.find((o) => o.id === id);
  if (!order) return;
  const serial = ++drawerSerial;
  state.order = order;
  state.detail = null;
  $(".drawer-overlay")?.remove();
  const layer = document.createElement("div");
  layer.className = "overlay drawer-overlay";
  layer.innerHTML = `<section class="drawer" role="dialog" aria-modal="true" aria-label="订单详情"><div class="drawer-header"><div><h2>订单详情</h2><p class="drawer-subtitle">${esc(order.mercari_order_id)}</p></div><button class="icon-button" data-action="close-drawer" aria-label="关闭订单详情">${icon("close")}</button></div><div class="drawer-body"><div class="loading"><span class="spinner"></span>读取订单信息…</div></div></section>`;
  $("#overlay-root").prepend(layer);
  updateInert();
  try {
    const detail = await api(`/api/items/${encodeURIComponent(order.item_id)}`);
    if (serial !== drawerSerial) return;
    state.detail = detail;
    renderOrder();
    $(".drawer-header button")?.focus();
  } catch (error) {
    if (serial !== drawerSerial) return;
    $(".drawer-body").innerHTML = empty(
      "读取订单失败",
      error.message,
      "retry-order",
      "重试",
    );
    $(".drawer-body").dataset.retry = id;
  }
}
function renderOrder() {
  const o = state.order;
  if (!o || !state.detail) return;
  const item = state.detail.item,
    st = stage(o);
  const stepIndex = {
    awaiting_purchase: 0,
    purchased: 1,
    in_transit: 2,
    inspection_issue: 3,
    received: 3,
    shipped: 4,
    delivered: 5,
  }[st];
  const steps = [
    "中国采购",
    "发往日本",
    "跨境运输",
    "日本验收",
    "发给买家",
    "买家收货",
  ];
  const source = state.detail.china_sources.find(
    (s) => s.id === o.china_source_id,
  );
  $(".drawer-body").innerHTML =
    `<div class="detail-summary">${thumb(state.items.find((i) => i.id === item.id) || item)}<div><h3>${esc(item.japan_title)}</h3>${badge(st)} <span class="subtle">${o.quantity} 件</span></div></div><div class="timeline">${steps.map((label, index) => `<div class="timeline-step ${index < stepIndex || st === "delivered" ? "done" : index === stepIndex ? "current" : ""}"><span>${index < stepIndex || st === "delivered" ? "✓" : index + 1}</span>${label}</div>`).join("")}</div><section class="detail-card"><div class="detail-card-header"><h3>成交信息</h3><span class="subtle">${dateText(o.created_at)}</span></div><div class="detail-grid">${kv("Mercari 订单号", esc(o.mercari_order_id))}${kv("成交金额", money(o.sold_price_jpy))}${kv("采购货源", esc(source?.source_title || siteName(source?.china_site || "")))}${kv("实际采购成本", money(o.actual_purchase_price_cny, "CNY"))}${o.actual_purchase_price_cny ? kv("实际中国 → 日本运费", money(o.actual_china_to_japan_shipping_cny, "CNY")) : ""}</div>${source ? `<p style="margin-top:12px">${external(source.source_url, "查看采购货源")}</p>` : ""}</section>${orderNextForm(o)}${o.china_tracking_number ? `<section class="detail-card"><h3>中国 → 日本物流</h3><div class="detail-grid">${kv("物流公司", esc(o.china_carrier))}${kv("运单号", esc(o.china_tracking_number))}${kv("发货时间", dateText(o.china_shipped_at))}${kv("收货 / 验收时间", dateText(o.received_at_japan))}</div>${o.inspection_note ? `<div class="form-section">验收记录</div><p class="description">${esc(o.inspection_note)}</p>` : ""}</section>` : ""}${o.japan_tracking_number ? `<section class="detail-card"><h3>日本 → 买家物流</h3><div class="detail-grid">${kv("物流公司", esc(o.japan_carrier))}${kv("运单号", esc(o.japan_tracking_number))}${kv("日本发货时间", dateText(o.shipped_to_buyer_at))}${kv("送达时间", dateText(o.delivered_at))}</div></section>` : ""}`;
  if (typeof appendOrderTools === "function") appendOrderTools();
}
function orderNextForm(o) {
  if (o.order_status === "cancelled")
    return `<section class="detail-card"><h3>订单已取消</h3><p class="description">${esc(o.cancel_reason)}</p><p class="muted-note">${o.inventory_released ? "已释放占用库存" : "保留库存占用"}，采购与物流记录已保留。</p></section>`;
  if (o.return_received_at)
    return `<section class="detail-card"><h3>买家退货已收到</h3><p class="description">${esc(o.return_note)}</p><p class="muted-note">请在下方处理订单取消或登记实际退款。</p></section>`;
  let title, content, endpoint, submit;
  if (
    o.fulfillment_status === "awaiting_purchase" &&
    o.order_status !== "cancelled"
  ) {
    const sources = state.detail.china_sources.filter(
      (s) => s.match_status === "confirmed",
    );
    title = "第一步 · 登记中国采购";
    endpoint = "purchase-confirmation";
    submit = "确认已采购";
    content = `<p class="muted-note" style="margin-bottom:16px">重新确认同款与供货情况，完成采购后记录实际实付金额。</p><div class="form-grid">${field("china_source_id", "实际采购货源", { full: true, required: true, value: o.china_source_id, options: sources.map((s) => [s.id, `${siteName(s.china_site)} · ${s.source_title || "已核验货源"}`]) })}${field("actual_price_cny", "实付采购金额（CNY）", { type: "number", required: true, min: 0.01, step: 0.01, placeholder: "填写本次实际实付金额" })}${field("actual_china_to_japan_shipping_cny", "中国 → 日本实际运费（CNY）", { type: "number", required: true, min: 0, step: 0.01, value: 0 })}</div>`;
  } else if (o.inbound_status === "awaiting_dispatch") {
    title = "第二步 · 登记发往日本";
    endpoint = "china-shipment";
    submit = "登记跨境发货";
    content = `<div class="form-grid">${field("carrier", "物流公司", { required: true, placeholder: "例如 顺丰 / 转运公司" })}${field("tracking_number", "中国 → 日本运单号", { required: true, placeholder: "填写实际运单号" })}</div>`;
  } else if (["in_transit", "inspection_issue"].includes(o.inbound_status)) {
    title =
      o.inbound_status === "inspection_issue"
        ? "处理验收异常"
        : "第三步 · 日本收货与验收";
    endpoint = "japan-receipt";
    submit = "保存验收结果";
    content = `${o.inbound_status === "inspection_issue" ? '<div class="notice warm">当前存在验收异常。处理后可重新登记验收结果，通过后再向买家发货。</div>' : ""}<div class="form-grid">${field(
      "inspection_result",
      "验收结果",
      {
        required: true,
        options: [
          ["passed", "验收通过"],
          ["issue", "存在问题，暂停境内发货"],
        ],
      },
    )}${field("inspection_note", "验收记录", { type: "textarea", full: true, placeholder: "记录数量、外观、规格、包装或异常处理结果…" })}</div>`;
  } else if (o.domestic_status === "not_shipped") {
    title = "第四步 · 登记日本境内发货";
    endpoint = "domestic-shipment";
    submit = "登记发给买家";
    content = `<div class="notice">商品已在日本验收通过，可登记日本发给买家的运单。</div><div class="form-grid">${field("carrier", "日本物流公司", { required: true, placeholder: "例如 ヤマト運輸" })}${field("tracking_number", "日本境内运单号", { required: true, placeholder: "填写发给买家的实际运单号" })}</div>`;
  } else if (o.domestic_status === "shipped") {
    title = "最后一步 · 确认买家收货";
    endpoint = "delivery-confirmation";
    submit = "确认已送达";
    content =
      '<div class="notice">请核对买家收货或物流送达记录，确认后此订单将标记为已送达。</div>';
  } else
    return '<section class="detail-card"><div class="notice" style="margin:0">✓ 这件好物已送达。采购、跨境运输与日本境内配送记录已完整保留。</div></section>';
  return `<section class="detail-card"><h3>${title}</h3><form data-form="order-step" data-id="${esc(o.id)}" data-endpoint="${endpoint}">${content}${formActions(submit, false)}</form></section>`;
}

function draftPayload(form) {
  const fd = new FormData(form),
    data = Object.fromEntries(fd);
  try {
    data.category_attributes = JSON.parse(data.category_attributes_json || "{}");
  } catch {
    throw new Error("分类专属属性不是有效的 JSON，请修正格式或留空。");
  }
  if (!data.category_attributes || Array.isArray(data.category_attributes) || typeof data.category_attributes !== "object")
    throw new Error("分类专属属性必须是 JSON 对象。");
  delete data.category_attributes_json;
  const numberFields = [
    "inventory_quantity",
    "price_jpy",
    "exchange_rate_cny_per_jpy",
    "estimated_china_to_japan_shipping_cny",
    "shipping_jpy",
    "other_costs_jpy",
  ];
  numberFields.forEach((k) => (data[k] = data[k] === "" && !["inventory_quantity", "price_jpy"].includes(k) ? null : Number(data[k])));
  data.max_quantity_per_order = data.max_quantity_per_order
    ? Number(data.max_quantity_per_order)
    : null;
  data.mercari_fee_rate = Number(data.mercari_fee_percent) / 100;
  delete data.mercari_fee_percent;
  data.reservation_sale = fd.has("reservation_sale");
  data.multi_variant = fd.has("multi_variant");
  data.image_asset_ids = fd.getAll("image_asset_ids");
  data.image_refs = form.dataset.id
    ? state.detail.listing_draft?.image_refs || []
    : [];
  if (!data.image_asset_ids.length && !data.image_refs.length)
    throw new Error("请至少选择一张货源图片。没有图片时，先在“中国货源”上传。");
  data.inventory_variants = data.multi_variant
    ? $$(".variant-row", form).map((row) => {
        const base = JSON.parse(row.dataset.original || "{}");
        const name = $('input[name="variant_name"]', row).value.trim();
        const quantity = Number($('input[name="variant_stock"]', row).value);
        if (!name || !Number.isInteger(quantity) || quantity < 0)
          throw new Error("请填写各规格名称及有效的非负整数库存。");
        return {
          ...base,
          name,
          inventory_quantity: quantity,
          ...("quantity" in base ? { quantity } : {}),
        };
      })
    : [];
  delete data.variant_name;
  delete data.variant_stock;
  if (
    data.multi_variant &&
    (!data.inventory_variants.length ||
      data.inventory_variants.reduce(
        (sum, variant) => sum + variant.inventory_quantity,
        0,
      ) < 1)
  )
    throw new Error("多规格商品至少需要一个规格，且总库存必须大于零。");
  [
    "reservation_start_date",
    "reservation_end_date",
    "reservation_release_date",
    "reservation_cancel_deadline",
  ].forEach((k) => (data[k] = data.reservation_sale ? data[k] || null : null));
  if (!data.reservation_sale)
    data.reservation_delivery_timing = "after_release";
  return data;
}
async function submitForm(form) {
  if (form.dataset.busy === "true") return;
  form.dataset.busy = "true";
  const button = $('button[type="submit"]', form),
    original = button.innerHTML,
    error = $(".form-error", form);
  error.classList.remove("visible");
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>正在保存…';
  const fd = new FormData(form),
    data = Object.fromEntries(fd),
    kind = form.dataset.form;
  try {
    if (kind === "candidate") {
      data.japan_price_jpy = data.japan_price_jpy
        ? Number(data.japan_price_jpy)
        : null;
      data.japan_image_url = data.japan_image_url || null;
      const item = await post("/api/japan/candidates", data);
      closeModal(true, true);
      await refresh({ silent: true });
      toast("选品已添加，接下来可以寻找中国货源。");
      await openItem(item.id, "sources");
    } else if (kind === "source") {
      data.price_cny = data.price_cny ? Number(data.price_cny) : null;
      await post(
        `/api/china/items/${encodeURIComponent(state.detail.item.id)}/sources`,
        data,
      );
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail("sources");
      toast("中国货源已保存。");
    } else if (kind === "confirm-source") {
      data.price_cny = data.price_cny ? Number(data.price_cny) : null;
      // Preserve optional commitments already recorded by API users.
      const source = state.detail.china_sources.find(
        (s) => s.id === form.dataset.id,
      );
      if (
        source.availability_commitment &&
        data.availability_status === "available"
      )
        Object.assign(data, {
          availability_commitment: true,
          committed_quantity: source.committed_quantity,
          commitment_valid_until: source.commitment_valid_until,
        });
      await post(
        `/api/china/sources/${encodeURIComponent(form.dataset.id)}/confirm`,
        data,
      );
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail("sources");
      toast("同款与价格核验结果已保存，系统已自动生成上架资料包。");
    } else if (kind === "upload") {
      const files = fd.getAll("file").filter((file) => file.size > 0);
      if (!files.length) throw new Error("请选择要上传的图片。");
      if (files.some((file) => file.size > 20 * 1024 * 1024))
        throw new Error("单张图片不能超过 20 MB，请检查选中的文件。");
      let uploaded = 0;
      for (const file of files) {
        const payload = new FormData();
        ["image_role", "source_page_url", "source_asset_url"].forEach((k) =>
          payload.set(k, fd.get(k) || ""),
        );
        payload.set("file", file);
        $("#upload-progress").textContent =
          `正在上传第 ${uploaded + 1} / ${files.length} 张图片…`;
        try {
          await post(
            `/api/china/sources/${encodeURIComponent(form.dataset.id)}/images`,
            payload,
          );
          uploaded++;
        } catch (error) {
          if (uploaded) {
            await refresh({ silent: true });
            await reloadDetail("sources");
            throw new Error(
              `已成功上传 ${uploaded} 张；${error.message} 请重新选择剩余文件。`,
            );
          }
          throw error;
        }
      }
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail("sources");
      toast(`${uploaded} 张图片已保存，上架版已生成。`);
    } else if (kind === "draft") {
      const payload = draftPayload(form);
      if (form.dataset.id)
        await api(
          `/api/listing/drafts/${encodeURIComponent(form.dataset.id)}`,
          { method: "PUT", body: JSON.stringify(payload) },
        );
      else
        await post(
          `/api/listing/items/${encodeURIComponent(state.detail.item.id)}/drafts`,
          payload,
        );
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail("listing");
      toast("上架草稿已保存。");
    } else if (kind === "listing-defaults") {
      data.mercari_fee_rate = Number(data.mercari_fee_percent) / 100;
      delete data.mercari_fee_percent;
      state.listingDefaults = await api("/api/listing/defaults", {
        method: "PUT",
        body: JSON.stringify(data),
      });
      closeModal(true, true);
      toast("通用上架设置已保存，新建草稿会自动带入。");
    } else if (kind === "publish") {
      await post(
        `/api/listing/drafts/${encodeURIComponent(form.dataset.id)}/publish-confirmation`,
        data,
      );
      await refresh({ silent: true });
      await reloadDetail("listing");
      toast("已登记为上架，收到订单后可开始跟进履约。");
    } else if (kind === "new-order") {
      data.quantity = Number(data.quantity);
      data.sold_price_jpy = Number(data.sold_price_jpy);
      const order = await post("/api/orders", data);
      closeModal(true, true);
      await refresh({ silent: true });
      await openOrder(order.id);
      toast("订单已登记，等待中国采购。");
    } else if (kind === "order-step") {
      ["actual_price_cny", "actual_china_to_japan_shipping_cny"].forEach(
        (k) => {
          if (k in data) data[k] = Number(data[k]);
        },
      );
      await post(
        `/api/orders/${encodeURIComponent(form.dataset.id)}/${form.dataset.endpoint}`,
        data,
      );
      await refresh({ silent: true });
      state.order = state.orders.find((o) => o.id === form.dataset.id);
      renderOrder();
      toast("订单进度已更新。");
    }
  } catch (err) {
    if (error.isConnected) {
      error.textContent = err.message;
      error.classList.add("visible");
      error.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else toast(err.message, true);
  } finally {
    delete form.dataset.busy;
    if (button.isConnected) {
      button.disabled = false;
      button.innerHTML = original;
    }
  }
}
function exportItems() {
  const items = filteredItems();
  if (!items.length) {
    toast("当前没有可导出的商品。");
    return;
  }
  const headers = [
    "商品编号",
    "商品名称",
    "日本平台",
    "日本链接",
    "日本参考价JPY",
    "阶段",
    "中国货源数",
    "最低货源价CNY",
    "店铺售价JPY",
    "预估利润CNY",
    "煤炉链接",
    "备注",
  ];
  const cell = (value) =>
    `"${String(value ?? "")
      .replace(/^[=+\-@\t\r]/, "'$&")
      .replace(/"/g, '""')}"`;
  const csv =
    "\uFEFF" +
    [
      headers,
      ...items.map((i) => [
        i.id,
        i.japan_title,
        siteName(i.japan_site),
        i.japan_url,
        i.japan_price_jpy,
        statusNames[i.status],
        i.source_count,
        i.source_price_cny,
        i.price_jpy,
        i.estimated_profit_cny,
        i.listing_url,
        i.note,
      ]),
    ]
      .map((row) => row.map(cell).join(","))
      .join("\r\n");
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `煤炉商品-${new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" })}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  toast(`已导出 ${items.length} 件商品。`);
}
async function act(action, id, target) {
  if ($('form[data-busy="true"]')) {
    toast("正在保存，请稍候。");
    return;
  }
  if (
    typeof backendAction === "function" &&
    (await backendAction(action, id, target))
  )
    return;
  switch (action) {
    case "new-item":
      newItem();
      break;
    case "listing-defaults":
      await editListingDefaults();
      break;
    case "item":
      await openItem(id, target.dataset.tab || "overview");
      break;
    case "retry-item":
      await openItem($(".drawer-body").dataset.retry, state.detailTab);
      break;
    case "retry-order":
      await openOrder($(".drawer-body").dataset.retry);
      break;
    case "close-drawer":
      closeDrawer();
      break;
    case "close-modal":
      closeModal();
      break;
    case "detail-tab":
      state.detailTab = id;
      renderItemDetail();
      break;
    case "go-sources":
      state.detailTab = "sources";
      renderItemDetail();
      break;
    case "new-source":
      newSource();
      break;
    case "confirm-source":
      confirmSource(id);
      break;
    case "refresh-preparation":
      await post(`/api/listing/items/${encodeURIComponent(id)}/preparation`, {});
      await reloadDetail("listing");
      toast("上架资料已根据当前货源、图片和通用设置重新生成。");
      break;
    case "upload-image":
      uploadImage(id);
      break;
    case "exclude-source-image":
    case "restore-source-image":
      await api(`/api/china/source-images/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({excluded: action === "exclude-source-image", exclusion_reason: "人工排除：图片与本次商品不符或来源待核实"}),
      });
      await reloadDetail("sources");
      toast(action === "exclude-source-image" ? "已排除此图，文件保留且可恢复。" : "已恢复，请重新核对图片用途。");
      break;
    case "set-image-real":
    case "unset-image-real":
      await api(`/api/china/source-images/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ image_role: action === "set-image-real" ? "real_photo" : "other" }),
      });
      await reloadDetail("sources");
      toast(action === "set-image-real" ? "已将人工核实的图片标记为实物图。" : "已取消实物图标记。");
      break;
    case "edit-draft":
      editDraft();
      break;
    case "add-variant":
      $(".variant-list").insertAdjacentHTML("beforeend", variantRow());
      syncVariants();
      break;
    case "remove-variant":
      target.closest(".variant-row").remove();
      syncVariants();
      break;
    case "new-order":
      newOrder(id);
      break;
    case "order":
      await openOrder(id);
      break;
    case "filter":
      state.filter = id;
      state.page = 1;
      updateTableResults();
      break;
    case "pipeline":
      state.filter = id;
      state.query = "";
      state.page = 1;
      render();
      $(".table-toolbar")?.scrollIntoView({
        block: "center",
        behavior: "smooth",
      });
      break;
    case "reset-filters":
      state.filter = "all";
      state.query = "";
      state.page = 1;
      $("#search").value = "";
      updateTableResults();
      break;
    case "next-page":
      state.page++;
      render();
      break;
    case "prev-page":
      state.page--;
      render();
      break;
    case "refresh":
      await refresh();
      break;
    case "export":
      exportItems();
      break;
    case "copy-title":
    case "copy-description":
      try {
        await navigator.clipboard.writeText(
          state.detail.listing_draft[
            action === "copy-title" ? "title_ja" : "description_ja"
          ],
        );
        toast("已复制到剪贴板。");
      } catch {
        toast("复制失败，请手动选择文字复制。", true);
      }
      break;
  }
}
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (target && !target.disabled) {
    event.preventDefault();
    act(target.dataset.action, target.dataset.id, target).catch((error) =>
      toast(error.message, true),
    );
  }
  if (event.target.classList.contains("overlay")) {
    if (event.target.classList.contains("modal-overlay")) closeModal();
    else closeDrawer();
  }
  if (
    $("#sidebar").classList.contains("open") &&
    !event.target.closest("#sidebar") &&
    !event.target.closest("#mobile-menu")
  )
    $("#sidebar").classList.remove("open");
});
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (
    form.matches("form[data-form]") &&
    !form.dataset.form.startsWith("backend-")
  ) {
    event.preventDefault();
    if (form.reportValidity()) submitForm(form);
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "search") {
    state.query = event.target.value;
    state.page = 1;
    updateTableResults();
  }
  if (event.target.closest('form[data-form="draft"]')) updateProfit();
  if (event.target.closest(".variant-row")) syncVariants();
});
document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.id === "sort") {
    state.sort = input.value;
    state.page = 1;
    updateTableResults();
  }
  if (
    input.name === "china_source_id" &&
    input.closest('form[data-form="draft"]')
  ) {
    $("#draft-images").innerHTML = imagePicker(input.value);
    updateProfit();
  }
  if (input.name === "reservation_sale") {
    $("#reservation-fields").classList.toggle("hidden", !input.checked);
    $$('#reservation-fields input[type="date"]').forEach(
      (date) => (date.required = input.checked),
    );
  }
  if (input.name === "multi_variant") {
    $("#variant-fields").classList.toggle("hidden", !input.checked);
    syncVariants();
  }
  if (
    input.name === "item_id" &&
    input.closest('form[data-form="new-order"]')
  ) {
    const item = state.items.find((i) => i.id === input.value);
    $("#f-sold_price_jpy").value = item?.price_jpy || "";
  }
});
document.addEventListener("keydown", (event) => {
  const layer = $(".modal-overlay") || $(".drawer-overlay");
  if (event.key === "Escape") {
    if ($(".modal-overlay")) closeModal();
    else if (layer) closeDrawer();
    else $("#sidebar").classList.remove("open");
  }
  if (event.key === "Tab" && layer) {
    const controls = $$(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
      layer,
    ).filter((el) => el.getClientRects().length);
    const first = controls[0],
      last = controls.at(-1);
    if (!first) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});
document.addEventListener(
  "error",
  (event) => {
    if (event.target.tagName === "IMG") {
      const placeholder = document.createElement("span");
      placeholder.className = "thumbnail empty";
      placeholder.setAttribute("aria-label", "图片暂不可用");
      placeholder.innerHTML = icon("image");
      event.target.replaceWith(placeholder);
    }
  },
  true,
);
window.addEventListener("hashchange", () => {
  closeModal(false);
  closeDrawer();
  route();
});
$("#refresh").innerHTML = icon("refresh");
$("#refresh").addEventListener("click", () => refresh());
$("#mobile-menu").addEventListener("click", () =>
  $("#sidebar").classList.toggle("open"),
);
$("#today").textContent = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "long",
  day: "numeric",
  weekday: "long",
}).format(new Date());
state.view = views[location.hash.slice(1)]
  ? location.hash.slice(1)
  : "dashboard";
refresh();
