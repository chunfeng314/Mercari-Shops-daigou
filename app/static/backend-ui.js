/* Business management and the local browser job console. */
"use strict";
Object.assign(state, {
  jobs: [],
  watches: [],
  shopImports: [],
  archivedItems: [],
  itemScope: "active",
  selectedResults: {},
  activeJobId: null,
  shopSettings: {},
});
const jobNames = {
  browser_session: "打开工作台专用浏览器",
  browser_close: "关闭专用浏览器并保留登录",
  shop_cdp_open: "打开 CDP Chrome 登录窗口",
  china_search: "闲鱼自动找货",
  china_source_images: "采集闲鱼货源图片",
  china_image_review: "千问筛选货源图片",
  japan_search: "Mercari 关键词搜索",
  japan_shop: "店铺商品采集",
  japan_item: "商品详情采集",
  listing_prepare: "自动整理上架资料",
  shop_session: "连接店铺会话",
  shop_close_session: "断开店铺会话",
  shop_inspect_form: "检查店铺上架表单",
  shop_fill_draft: "填写店铺草稿",
  shop_read_orders: "读取店铺订单",
};
Object.assign(statusNames, {
  queued: "排队中",
  running: "正在执行",
  waiting_login: "等待手动登录",
  waiting_review: "等待页面核对",
  succeeded: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
});
let automationSignature = "",
  automationPolling = false;

async function refreshAutomation(update = true) {
  const previousJobs = state.jobs;
  const [jobs, watches, imports, allItems, shopSettings, automationStatus] = await Promise.all([
    api("/api/automation/jobs"),
    api("/api/automation/watches"),
    api("/api/automation/shop-order-imports"),
    api("/api/items?include_archived=true"),
    api("/api/automation/shops/settings"),
    api("/api/automation/status"),
  ]);
  Object.assign(state, {
    jobs,
    watches,
    shopImports: imports,
    shopSettings,
    automationStatus,
    imageReviewAvailable: Boolean(automationStatus.image_review_enabled && automationStatus.image_review_configured),
    archivedItems: allItems.filter((i) => i.archived_at),
  });
  const signature = JSON.stringify([jobs, watches, imports]);
  if (update && signature !== automationSignature) {
    const host = $("#automation-data");
    if (host) host.innerHTML = automationData();
    const importsHost = $("#shop-import-data");
    if (importsHost) importsHost.outerHTML = shopImportSection();
    if ($(".job-modal-content") && state.activeJobId) {
      const job = jobs.find((j) => j.id === state.activeJobId);
      if (job) $(".job-modal-content").innerHTML = jobBody(job);
    }
  }
  automationSignature = signature;
  const justFinishedReview = jobs.some((job) => job.kind === "china_image_review" && job.status === "succeeded" &&
    !["succeeded", "failed", "cancelled"].includes(previousJobs.find((old) => old.id === job.id)?.status));
  if (justFinishedReview && state.detail) await reloadDetail("sources");
}
function backendHeading() {
  return `<div class="page-heading"><div><p class="eyebrow">STEP 01 · JAPAN DISCOVERY</p><h1>日本选品</h1><p class="subtitle">从 Mercari 找到合适商品，采集详情后加入商品工作台，再进入中国找货。日本商品售价需高于 9,999 日元。</p></div><div class="heading-actions"><button class="button" data-action="new-watch">${icon("clock")}定时监控</button><button class="button primary" data-action="new-discovery">${icon("search")}发现日本商品</button></div></div>`;
}
function discoveryView() {
  return `<div class="notice">搜索和参考店铺采集使用公开页面；监控在本应用运行期间执行。默认使用工作台专用浏览器，首次登录后自动复用；正常采集不需要接管日常 Chrome。</div><section class="discovery-start"><span class="stat-icon">${icon("search")}</span><div><p class="eyebrow">第一步 · 建立日本商品候选</p><h2>先找到值得继续跟进的商品</h2><p>可用日文关键词搜索，也可直接采集 Mercari 商品详情或参考店铺；导入后商品会进入工作台并关联后续找货记录。</p></div><div class="discovery-start-actions"><button class="button primary" data-action="new-discovery">${icon("search")}开始日本选品</button><button class="button" data-action="shop-session">${icon("bag")}连接 Shops</button></div></section><div id="automation-data">${automationData()}</div>`;
}
function automationData() {
  const jobs = state.jobs;
  const watches = state.watches;
  const jobRows = jobs.map((job) => `<tr><td><strong>${esc(jobNames[job.kind] || job.kind)}</strong><div class="price-sub">${esc(job.kind === "china_search" ? `日本资料生成搜索词 · ${job.payload.item_title || ""}` : job.payload.query || job.payload.url || (job.kind === "listing_prepare" ? "已核验商品资料" : "工作台浏览器任务"))}</div></td><td>${badge(job.status)}</td><td class="wrap-cell">${esc(job.progress || "等待执行")}${job.result?.count != null ? `<div class="price-sub">处理 ${job.result.count} 条</div>` : ""}</td><td>${dateText(job.created_at)}</td><td><button class="row-action" data-action="view-job" data-id="${esc(job.id)}">${["waiting_login", "waiting_review"].includes(job.status) ? "继续任务" : "查看结果"} ${icon("arrow")}</button></td></tr>`).join("");
  const watchRows = watches.map((watch) => {
    const preparing = watch.kind === "listing_prepare";
    return `<div class="task-row"><span class="task-bullet">${icon(preparing || watch.kind === "japan_shop" ? "bag" : "search")}</span><div class="task-text"><h3>${esc(watch.name)}</h3><p>${preparing ? `已核验商品上架资料 · 每次最多 ${watch.result_limit} 件` : esc(watch.query || watch.url)} · 每 ${watch.interval_minutes} 分钟 · ${watch.enabled ? "运行中" : "已暂停"}</p></div><div class="inline-actions"><button class="button small" data-action="${preparing ? "watch-run" : "watch-changes"}" data-id="${esc(watch.id)}">${preparing ? "立即整理" : "变化记录"}</button>${preparing ? "" : `<button class="button small" data-action="watch-run" data-id="${esc(watch.id)}">${icon("refresh")}立即执行</button>`}<button class="button small" data-action="watch-toggle" data-id="${esc(watch.id)}">${watch.enabled ? "暂停" : "启用"}</button><button class="icon-button" data-action="watch-archive" data-id="${esc(watch.id)}" aria-label="归档定时任务">${icon("close")}</button></div></div>`;
  }).join("");
  return `<section class="panel"><div class="panel-header"><div><h2>采集任务记录</h2><p class="panel-kicker">查看日本选品、中国找货、图片分析和上架资料整理的执行状态</p></div><div class="inline-actions"><button class="button small" data-action="shop-inspect">检查上架表单</button><button class="button small" data-action="shop-disconnect">断开店铺会话</button><button class="button small" data-action="refresh-automation">${icon("refresh")}刷新</button></div></div>${jobs.length ? `<div class="table-scroll"><table><thead><tr><th>任务</th><th>执行状态</th><th>进度</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${jobRows}</tbody></table></div>` : empty("还没有自动化任务", "先搜索日本商品并导入工作台，再从商品详情发起中国找货。", "new-discovery", "开始日本选品")}</section><section class="panel"><div class="panel-header"><div><h2>定时采集与资料整理</h2><p class="panel-kicker">每次间隔至少 1 小时；应用运行时执行，可定时发现商品或整理已核验商品的上架资料</p></div><button class="button small" data-action="new-watch">${icon("plus")}新增定时任务</button></div>${watches.length ? watchRows : empty("还没有定时任务", "可以定时采集 Mercari 新商品，或批量整理已核验商品的上架资料。")}</section>`;
}
function shopImportSection() {
  return `<section class="panel" id="shop-import-data"><div class="panel-header"><div><h2>Mercari Shops 订单同步</h2><p class="panel-kicker">读取店铺订单后，先核对商品、数量和金额，再登记到履约流程</p></div><button class="button small" data-action="shop-read-orders">${icon("refresh")}读取店铺订单</button></div>${state.shopImports.length ? `<div class="table-scroll"><table><thead><tr><th>店铺订单 / 商品</th><th>数量与金额</th><th>关联状态</th><th>操作</th></tr></thead><tbody>${state.shopImports.map((row) => `<tr><td class="wrap-cell"><strong>${esc(row.external_order_id)}</strong><div class="price-sub">${esc(row.title || "请核对商品")}</div></td><td>${row.quantity ? `${row.quantity} 件` : "数量待确认"}<div>${money(row.amount_jpy)}</div></td><td>${badge(row.local_order_id ? "confirmed" : "pending", row.local_order_id ? "已关联本地订单" : "待核对关联")}</td><td><button class="row-action" data-action="${row.local_order_id ? "order" : "map-shop-order"}" data-id="${esc(row.local_order_id || row.id)}">${row.local_order_id ? "查看订单" : "核对并导入"} →</button></td></tr>`).join("")}</tbody></table></div>` : empty("尚未读取店铺订单", "登录后在浏览器中打开订单列表，再执行读取；不会修改店铺订单。")}</section>`;
}
function newDiscovery() {
  modal(
    "采集 Mercari 商品",
    "选择关键词、商品链接或参考店铺，取回真实页面资料。",
    `<form data-form="backend-discovery"><div class="form-grid"><p class="form-hint full">价格硬性条件：只保留售价高于 9,999 日元的商品；无法读取价格的商品也不会进入候选。</p>${field(
      "kind",
      "采集方式",
      {
        full: true,
        options: [
          ["search", "关键词搜索"],
          ["item", "单件商品详情"],
          ["shop", "参考店铺商品"],
        ],
      },
    )}${field("query", "关键词", { required: true, full: true, placeholder: "例如 中国限定 スターバックス" })}<div class="full hidden" id="collection-url-field">${field("url", "商品 / 店铺链接", { type: "url", placeholder: "https://jp.mercari.com/…" })}</div>${field("limit", "最多读取（件）", { type: "number", value: 20, min: 1, max: 100, step: 1, required: true })}${field(
      "sort",
      "关键词搜索排序",
      {
        options: [
          ["newest", "最新发布优先"],
          ["price_low", "价格从低到高"],
          ["price_high", "价格从高到低"],
          ["recommended", "平台推荐"],
        ],
      },
    )}<label class="switch-row"><input type="checkbox" name="available_only" checked>仅搜索在售商品</label></div>${formActions("开始采集")}</form>`,
  );
}
function newChinaSearch(item) {
  modal(
    "闲鱼自动找货",
    `依据日本平台采集的标题和商品说明，为“${esc(item.title_ja || item.japan_title)}”自动生成搜索词；不需要你找链接或手填关键词。`,
    `<form data-form="backend-china-search" data-id="${esc(item.id)}"><div class="form-grid">${field("browser_mode", "浏览器会话", {value:"managed", options:[["managed","工作台专用 · 保留登录（推荐）"],["existing_chrome","手动接管日常浏览器 · 需授权"]]})}${field("browser_channel", "浏览器", {options:[["chrome","Google Chrome"],["msedge","Microsoft Edge"]]})}${field("limit", "最多读取商品（件）", {type:"number", value:20, min:1, max:50, step:1, required:true})}</div><p class="form-hint">搜索词自动来自日本商品资料。专用浏览器首次登录后保存在本机，后续任务复用窗口，不需要反复允许接管。登录过期或平台要求验证码时再处理。</p><button type="button" class="button" data-action="china-browser-open">打开专用浏览器 / 首次登录</button>${formActions("自动生成搜索词并开始找货")}</form>`,
  );
}
function newWatch() {
  modal(
    "新增定时任务",
    "Mercari 搜索与店铺监控只收集售价高于 9,999 日元的商品；应用运行时按间隔执行，不会自动发布商品。",
    `<form data-form="backend-watch"><div class="form-grid">${field("name", "监控名称", { full: true, required: true, placeholder: "例如 中国限定保温杯" })}${field(
      "kind",
      "监控对象",
      {
        full: true,
        options: [
          ["japan_search", "搜索关键词"],
          ["japan_shop", "参考店铺"],
          ["listing_prepare", "自动整理上架资料"],
        ],
      },
    )}${field("query", "关键词", { full: true, placeholder: "关键词监控时填写" })}<div id="watch-url-field" class="hidden">${field("url", "参考店铺链接", { type: "url", full: true, placeholder: "店铺监控时填写" })}</div>${field("interval_minutes", "执行间隔（分钟）", { type: "number", min: 60, max: 43200, step: 1, required: true, value: 360 })}${field("result_limit", "每次最多处理商品（件）", { type: "number", min: 1, max: 100, step: 1, required: true, value: 20, hint: "采集任务读取数量；资料整理任务处理已确认同款且尚未创建草稿的商品。" })}</div>${formActions("创建定时任务")}</form>`,
  );
}
function jobBody(job) {
  const waiting = ["waiting_login", "waiting_review"].includes(job.status),
    terminal = ["succeeded", "failed", "cancelled"].includes(job.status),
    beforeFill = job.result?.stage === "before_fill",
    chinaSearch = job.kind === "china_search",
    items = job.result?.items || [],
    searchQueries = job.result?.search_queries || job.payload?.queries || [],
    selection = state.selectedResults[job.id] || [];
  const rows = items.map((item, index) => `<label class="result-row"><input type="checkbox" class="result-select" data-job="${esc(job.id)}" value="${index}" ${selection.includes(index) ? "checked" : ""}><span class="result-thumb">${thumb({ japan_title: item.title, japan_image_url: item.image_url })}</span><span class="result-info"><strong>${esc(item.title)}</strong>${item.assessment ? `<span class="subtle">${item.assessment.status === "attribute_match" ? "文字属性符合，待核实同款" : "需核对规格/目标款价格"} · ${esc((item.assessment.reasons.length ? item.assessment.reasons : item.assessment.evidence).join("；"))}</span>` : ""}<span>${money(item.price, item.currency || "JPY")}${item.sold ? " · 已售出" : ""}${item.image_url ? "" : " · 图片未取得"}</span><a class="external-link" href="${esc(safeURL(item.url))}" target="_blank" rel="noopener">来源页面 ↗</a></span></label>`).join("");
  const importAction = chinaSearch ? "import-china-results" : "import-results";
  const importLabel = chinaSearch ? "加入待核验货源" : "导入选中的商品";
  const screening = chinaSearch && job.result?.read_count != null
    ? `<p class="form-hint">页面读取 ${job.result.read_count} 条 · 排除品牌/容量/配件不符 ${job.result.excluded_count || 0} 条 · 保留 ${items.length} 条待核验</p>${job.result.excluded_items?.length ? `<details><summary>查看排除原因</summary>${job.result.excluded_items.map(item => `<div class="review-row"><strong>${esc(item.title)}</strong><p>${esc(item.assessment.reasons.join("；"))}</p>${external(item.url,"查看原商品")}</div>`).join("")}</details>` : ""}`
    : "";
  const priceFilter = ["japan_search", "japan_shop"].includes(job.kind) && job.result?.price_filter
    ? `<p class="form-hint">价格条件：售价高于 9,999 日元 · 扫描 ${job.result.price_filter.scanned_count} 件 · 排除低价 ${job.result.price_filter.excluded_below_price_count} 件 · 排除无价格 ${job.result.price_filter.excluded_unknown_price_count} 件</p>`
    : "";
  return `<div class="section-title">${badge(job.status)}<span class="subtle">${dateText(job.created_at)}</span></div><p class="description">${esc(job.progress || "等待执行")}</p>${priceFilter}${job.error ? `<div class="form-error visible" style="margin:16px 0">${esc(job.error)}</div>` : ""}${waiting ? `<div class="notice" style="margin-top:17px">${job.status === "waiting_review" ? beforeFill ? "请先核对以下资料。点击开始填写后，平台会自动保存草稿。" : "请在店铺浏览器检查图片、分类、配送与库存，补全后保存草稿。" : "请在所选浏览器完成登录或连接授权，再点击继续。"}</div><button class="button primary" data-action="resume-job" data-id="${esc(job.id)}">${icon("check")}${job.status === "waiting_review" ? beforeFill ? "确认资料，开始填写" : "已核对，保存店铺草稿" : "已完成页面操作，继续"}</button>` : ""}${job.kind === "browser_session" && job.result?.note ? `<div class="notice">${esc(job.result.note)}</div>` : ""}${job.kind === "shop_cdp_open" && job.result?.note ? `<div class="notice">${esc(job.result.note)}</div>` : ""}${job.kind === "shop_cdp_open" && job.status === "succeeded" ? '<div class="form-actions"><button class="button primary" data-action="shop-cdp-connect">已登录，连接店铺</button></div>' : ""}${job.kind === "china_image_review" && job.result ? `<div class="notice">${esc(job.result.message || "图片决策已应用")}${job.result.reviewed_count != null ? ` · 已处理 ${job.result.reviewed_count} 张` : ""}。模型判断已直接更新用途与排除状态，可在上架环节检查。</div>` : ""}${job.result?.image_preview?.length ? `<div class="image-grid">${job.result.image_preview.map(im=>`<div class="image-tile"><img src="${esc(im.url)}" alt="待填写的商品图片"><small>${esc(im.note || "闲鱼图片候选")}</small></div>`).join("")}</div>` : ""}${job.result?.sources?.length ? `<div class="form-section">货源图片采集结果</div>${job.result.sources.map(row=>`<div class="review-row"><strong>${esc(row.title || row.source_id)}</strong><p>详情图 ${row.found ?? 0} 张${row.filtered_count ? ` · 排除推荐图 ${row.filtered_count} 张` : ""} · 新增 ${row.collected ?? 0} 张${row.duplicates ? ` · 重复 ${row.duplicates} 张` : ""}${row.total_images !== undefined ? ` · 共 ${row.total_images} 张` : ""}${row.error ? ` · ${esc(row.error)}` : ""}${row.note ? ` · ${esc(row.note)}` : ""}${row.vision_review ? ` · 千问识图：${esc(row.vision_review.message || row.vision_review.status)}` : ""}</p>${row.errors?.length ? `<p>${row.errors.map(esc).join("；")}</p>` : ""}</div>`).join("")}` : ""}${job.result?.description_ja ? `<div class="description">${esc(job.result.description_ja)}</div>` : ""}${job.result?.preview?.length ? `<div class="form-section">本次待填写资料</div><div class="detail-grid">${job.result.preview.map(row => kv(esc(row.label), esc(row.value))).join("")}</div>` : ""}${job.result?.fields?.length ? `<div class="form-section">表单检查</div>${job.result.fields.map(row => `<div class="review-row"><strong>${esc(row.label)}</strong><p>${row.recognized ? "✓ 已识别" : "待人工适配"} · ${esc(row.platform_label)}</p></div>`).join("")}` : ""}${job.result?.prepared?.length ? `<div class="form-section">资料包处理结果 · ${job.result.count} 件 · 更新 ${job.result.refreshed} 件 · 未变化 ${job.result.unchanged} 件</div>${job.result.prepared.map(row => `<div class="review-row"><strong>${esc(row.title)}</strong><p>${row.status === "ready_for_review" ? "必填资料齐全" : `待核对：${esc(row.missing.join("、") || "商品资料")}`} · 已收图 ${row.photo_collection.unique_count} 张，实物图 ${row.photo_collection.real_photo_count} 张</p></div>`).join("")}` : ""}${job.result?.category_fields?.length ? `<div class="form-section">分类专属字段 · 选择分类后从店铺表单读取</div>${job.result.category_fields.map(field => `<div class="review-row"><strong>${esc(field.label)} · ${field.required ? "必填" : "选填"}${field.status === "filled" ? " · 已填写" : field.status === "missing_required" ? " · 缺资料" : field.status === "missing_optional" ? " · 留空" : field.status === "needs_manual" ? " · 需核对" : ""}</strong><p>${field.options?.length ? `可选项：${field.options.map(option => esc(option.label)).join("、")}` : "文本属性"}${field.value !== undefined ? ` · 值：${esc(field.value)}` : ""}${field.evidence?.source ? ` · 依据：${esc(field.evidence.source)}` : ""}</p></div>`).join("")}` : ""}${job.result?.needs_manual?.length ? `<div class="form-section">需要人工核对</div>${job.result.needs_manual.map((row) => `<div class="review-row"><strong>${esc(row.label || row.field)}</strong><p>${esc(row.reason)}${row.value ? `：${esc(row.value)}` : ""}${row.options?.length ? ` · 可选项：${row.options.map(option => esc(option.label)).join("、")}` : ""}</p></div>`).join("")}` : ""}${job.result?.filled?.length ? `<p class="form-hint">已填写：${job.result.filled.map(esc).join("、")}</p>` : ""}${job.result?.saved ? '<div class="notice">店铺草稿保存已得到页面确认。正式公开仍在店铺中由你完成。</div>' : ""}${chinaSearch && searchQueries.length ? `<div class="form-section">日本采集资料自动生成的搜索词</div><p class="form-hint">${searchQueries.map(esc).join(" · ")} · 本地词典生成，未使用 AI</p>` : ""}${screening}${items.length ? `<div class="form-section">${chinaSearch ? "闲鱼搜索结果" : "采集结果"} · ${items.length} 件</div><div class="result-list">${rows}</div><div class="form-actions"><button class="button" data-action="select-results" data-id="${esc(job.id)}">全选 / 取消</button><button class="button primary" data-action="${importAction}" data-id="${esc(job.id)}">${importLabel}</button></div>${chinaSearch ? '<p class="form-hint">导入后只会保存为待核验货源；系统会自动抓取闲鱼商品详情中的图片候选，实物图仍需人工核验。</p>' : ""}` : chinaSearch && job.status === "succeeded" ? '<div class="notice">本次搜索没有可用候选；如页面已读取商品，请查看规格排除原因，否则检查平台登录或验证状态。</div>' : ""}${!terminal ? `<div class="form-actions"><button class="button" data-action="cancel-job" data-id="${esc(job.id)}">取消此任务</button></div>` : ""}`;
}function viewJob(id) {
  const job = state.jobs.find((j) => j.id === id);
  if (!job) return;
  state.activeJobId = id;
  modal(
    jobNames[job.kind] || "任务详情",
    "任务进度与结果会自动更新。",
    `<div class="job-modal-content">${jobBody(job)}</div>`,
    true,
  );
}
async function startJob(path, payload = {}, method = "POST") {
  const job = await api(path, {method, body: JSON.stringify(payload)});
  closeModal(true, true);
  await refreshAutomation();
  viewJob(job.id);
  toast("任务已创建，进度会自动更新。");
}
api("/api/automation/status").then((status) => {
  state.imageReviewAvailable = Boolean(status.image_review_enabled && status.image_review_configured);
  if (state.detail && state.detailTab === "sources") renderItemDetail();
}).catch(() => {});
function shopTaskForm(kind, draftId = "") {
  const title = {fill: "填写 Mercari Shops 草稿", orders: "读取店铺订单", inspect: "检查店铺上架表单", session: "连接店铺会话"}[kind];
  const explanation = kind === "fill" ? "先展示本地资料供核对，确认后开始填写。平台编辑会自动保存为草稿。" : kind === "inspect" ? "读取商品表单、检查必填项识别结果。" : "推荐使用工作台专用浏览器，首次登录后自动复用。";
  const saved = state.shopSettings;
  modal(
    title,
    explanation,
    `<form data-form="backend-shop-task" data-kind="${kind}" data-id="${esc(draftId)}"><div class="form-grid">${field("browser_mode", "连接方式", {value: saved.browser_mode || "managed", options: [["managed", "工作台专用 · 保留登录（推荐）"], ["existing_chrome", "CDP Chrome · 复用会话"], ["temporary", "临时会话 · 关闭后需重登"]]})}${field("browser_channel", "浏览器", {value: saved.browser_channel || "chrome", options: [["chrome", "Google Chrome"], ["msedge", "Microsoft Edge"]]})}${field("url", "店铺管理页面链接", { type: "url", full: true, value: saved.url || "", placeholder: "https://mercari-shops.com/seller/shops/…", hint: "保存后用于自动进入指定店铺。" })}</div><p class="form-hint">${kind === "session" ? "点击下方按钮会打开启用 CDP 的独立 Chrome 窗口。请在新窗口人工登录，然后回到任务结果点击“已登录，连接店铺”；工作台会验证指定店铺并接管会话。CDP 仅绑定本机，登录状态保存在本机独立配置中。" : "连接方式与店铺地址会按本机设置复用。如需人工登录，请从“连接店铺”窗口打开 CDP Chrome 登录窗口。"}</p>${kind === "session" ? '<div class="form-actions"><button type="button" class="button" data-action="shop-cdp-open">打开 CDP Chrome 登录窗口</button></div>' : ""}${formActions(kind === "fill" ? "检查资料并准备填写" : kind === "orders" ? "开始读取订单" : kind === "inspect" ? "检查表单" : "连接店铺")}</form>`,
  );
}

function enhanceBusinessView() {
  if (state.view === "items") {
    const toolbar = $(".toolbar-actions");
    if (toolbar && !$("#item-scope"))
      toolbar.insertAdjacentHTML(
        "afterbegin",
        `<select id="item-scope" class="filter-select" aria-label="商品归档范围"><option value="active" ${state.itemScope === "active" ? "selected" : ""}>当前商品</option><option value="archived" ${state.itemScope === "archived" ? "selected" : ""}>已归档商品</option></select>`,
      );
  }
}
function appendItemTools() {
  if (!state.detail || state.order) return;
  const item = state.detail.item,
    draft = state.detail.listing_draft,
    body = $(".drawer-body");
  if (draft?.status === 'withdrawn') {
    $$('[data-action="new-order"]', body).forEach(button => button.closest('.detail-card')?.remove());
  }
  body.insertAdjacentHTML(
    "afterbegin",
    `<div class="inline-actions management-toolbar">${item.archived_at ? `<span class="status">已归档</span><button class="button small" data-action="restore-item" data-id="${esc(item.id)}">恢复商品</button>` : `<button class="button small" data-action="edit-item">编辑选品资料</button><button class="button small" data-action="china-search">闲鱼自动找货</button>${item.status !== "listed" ? '<button class="button small" data-action="archive-item">归档商品</button>' : ""}`}${draft?.status === "draft" ? `<button class="button small soft" data-action="fill-shop" data-id="${esc(draft.id)}">${icon("bag")}填写店铺草稿</button>` : ""}${draft?.status === "listed" ? `<button class="button small" data-action="stock-confirm">回填店铺库存</button><button class="button small" data-action="withdraw-listing">登记已下架</button>` : ""}<button class="button small" data-action="item-history">操作记录</button></div>`,
  );
  $$(".detail-card[data-source-id]", body).forEach((card) => {
    const source = state.detail.china_sources.find(
      (s) => s.id === card.dataset.sourceId,
    );
    if (!source) return;
    const used =
      draft?.china_source_id === source.id ||
      state.orders.some((o) => o.china_source_id === source.id);
    const controls = source.archived_at
      ? `<span class="status">已归档货源</span><button class="button small" data-action="restore-source" data-id="${esc(source.id)}">恢复货源</button>`
      : `<button class="button small" data-action="edit-source" data-id="${esc(source.id)}">编辑货源</button>${!used ? `<button class="button small" data-action="archive-source" data-id="${esc(source.id)}">归档货源</button>` : ""}`;
    card.insertAdjacentHTML(
      "afterbegin",
      `<div class="inline-actions source-toolbar">${controls}</div>`,
    );
    const photoStats = sourcePhotoStats(source.images);
    const photoCount = photoStats.realCount;
    const photoReady = photoStats.targetMet;
    const grid = $(".image-grid", card);
    if (grid) {
      grid.insertAdjacentHTML("beforebegin", `<p class="form-hint">收图要求：至少 5 张不同图片，包含实物图。当前可用 ${photoStats.uniqueCount} 张 · 实物图 ${photoCount} 张 · ${photoReady ? "收图数量已达标" : "需要继续补图"}。第三方实拍仅作同款参考，不能证明当前卖家的库存或成色。</p>`);
      $$(".image-tile", grid).forEach((tile, index) => {
        const image = source.images[index];
        if (!image) return;
        const isReference = image.source_page_url !== source.source_url;
        const label = image.image_role === "real_photo" ? (isReference ? "第三方实物参考图" : "货源实拍") : ({catalog:"商品图",screenshot:"页面截图",other:"其他"}[image.image_role] || "图片");
        const caption = $("small", tile);
        if (caption) caption.textContent = `${image.excluded_at ? "已排除 · " : ""}${label} · ${image.width}×${image.height}`;
        if (image.source_page_url) tile.insertAdjacentHTML("beforeend", `<div>${external(image.source_page_url,"图片来源")}</div>`);
      });
    }
    if (source.archived_at) {
      $$(
        '[data-action="confirm-source"],[data-action="upload-image"]',
        card,
      ).forEach((button) => (button.disabled = true));
    }
  });
}
function appendOrderTools() {
  if (!state.order) return;
  const o = state.order;
  $(".drawer-body").insertAdjacentHTML(
    "beforeend",
    `<section class="detail-card"><h3>订单处理与记录</h3><p class="muted-note">这些操作记录实际处理结果，不会在店铺自动退款或取消订单。</p><div class="inline-actions" style="margin-top:15px">${o.order_status !== "cancelled" ? '<button class="button small" data-action="cancel-order">登记订单取消</button>' : ""}${["shipped", "delivered"].includes(o.domestic_status) && !o.return_received_at ? '<button class="button small" data-action="return-receipt">登记退货收货</button>' : ""}<button class="button small" data-action="refund-order">登记实际退款</button><button class="button small" data-action="order-history">操作记录</button><button class="button small" data-action="order-sources">补充替代货源</button></div><p class="form-hint">已登记退款：JPY ${n(o.refunded_amount_jpy || 0)}</p></section>`,
  );
}
function editItem() {
  const i = state.detail.item;
  modal(
    "编辑选品资料",
    "修改来源资料和备注，销售与履约记录会保留。",
    `<form data-form="backend-item" data-id="${esc(i.id)}"><div class="form-grid">${field("japan_title", "商品名称", { value: i.japan_title, required: true, full: true })}${field("japan_url", "日本商品链接", { type: "url", value: i.japan_url, required: true, full: true })}${field("japan_price_jpy", "日本参考价（JPY）", { type: "number", value: i.japan_price_jpy ?? "", min: 1, step: 1 })}${field("japan_image_url", "参考图片链接", { type: "url", value: i.japan_image_url || "" })}${field("note", "选品备注", { type: "textarea", full: true, value: i.note })}</div>${formActions("保存资料")}</form>`,
  );
}
function editSource(id) {
  const s = state.detail.china_sources.find((source) => source.id === id),
    used =
      state.detail.listing_draft?.china_source_id === id ||
      state.orders.some((o) => o.china_source_id === id);
  modal(
    "编辑中国货源",
    used
      ? "该货源已用于上架或采购，可更新价格与账号备注。"
      : "修改货源商品或链接后，需要重新核验同款。",
    `<form data-form="backend-source" data-id="${esc(id)}"><div class="form-grid">${!used ? field("source_title", "货源标题", { value: s.source_title, full: true }) + field("source_url", "货源页面链接", { type: "url", required: true, value: s.source_url, full: true }) : ""}${field("price_cny", "页面价格（CNY）", { type: "number", min: 0.01, step: 0.01, value: s.price_cny ?? "" })}${field("account_note", "账号 / 代购备注", { type: "textarea", full: true, value: s.account_note })}</div>${formActions("保存货源修改")}</form>`,
  );
}
function archiveForm(kind, id) {
  modal(
    kind === "item" ? "归档商品" : "归档货源",
    "归档后会从当前列表隐藏，已有图片与历史记录保留，可以恢复。",
    `<form data-form="backend-archive" data-kind="${kind}" data-id="${esc(id)}"><div class="notice">归档不会在 Mercari 店铺执行删除或下架。</div>${formActions("确认归档")}</form>`,
  );
}
async function history(kind, id) {
  const detail = await api(
    kind === "item" ? `/api/items/${id}` : `/api/orders/${id}`,
  );
  const names = {
    updated: "选品资料修改",
    archived: "商品归档",
    restored: "商品恢复",
    source_updated: "货源修改",
    source_added: "添加货源",
    source_confirmed: "核对同款与供货",
    candidate_created: "登记选品",
    draft_created: "创建上架草稿",
    draft_updated: "修改上架草稿",
    listing_published: "登记店铺发布",
    source_archived: "货源归档",
    source_restored: "货源恢复",
    created: "登记订单",
    purchase_confirmed: "确认采购",
    china_shipment: "发往日本",
    japan_receipt: "日本收货验收",
    domestic_shipment: "发给买家",
    delivered: "确认送达",
    cancelled: "订单取消",
    return_received: "退货收货",
    refund_recorded: "登记退款",
    imported: "采集导入",
    japan_image_backfilled: "补齐日本商品图片",
    inventory_confirmed: "店铺库存核对",
    withdrawn: "登记下架",
  };
  modal(
    "操作记录",
    "按时间保留资料变更与履约记录。",
    detail.events?.length
      ? detail.events
          .map(
            (event) =>
              `<div class="review-row"><div class="section-title"><strong>${esc(names[event.action] || event.action)}</strong><span class="subtle">${dateText(event.created_at)}</span></div>${Object.entries(
                event.details || {},
              )
                .map(
                  ([key, value]) =>
                    `<p class="history-line">${esc(historyLabel(key))}：${esc(
                      typeof value === "object"
                        ? Object.entries(value || {})
                            .map(([k, v]) => `${historyLabel(k)}：${v}`)
                            .join("；")
                        : value,
                    )}</p>`,
                )
                .join("")}</div>`,
          )
          .join("")
      : empty("暂无操作记录", "此版本开始记录后续修改与履约操作。"),
    true,
  );
}
function historyLabel(key) {
  return (
    {
      reason: "原因",
      quantity: "数量",
      sold_price_jpy: "成交金额 JPY",
      actual_price_cny: "实付采购 CNY",
      actual_china_to_japan_shipping_cny: "跨境运费 CNY",
      carrier: "物流公司",
      tracking_number: "运单号",
      inspection_result: "验收结果",
      inspection_note: "验收记录",
      note: "备注",
      release_inventory: "释放库存",
      amount_jpy: "金额 JPY",
      refund_reference: "退款流水号",
      remaining_quantity: "剩余可售库存",
      occupied_quantity: "已占用数量",
      changes: "修改内容",
      source_id: "货源编号",
      japan_title: "商品名",
      japan_url: "日本链接",
      source_url: "货源链接",
      source_title: "货源标题",
      price_cny: "页面价格 CNY",
      account_note: "账号备注",
      japan_price_jpy: "日本参考价",
      japan_image_url: "参考图片",
      job_id: "采集任务",
    }[key] || key
  );
}
function orderProcessForm(kind) {
  const o = state.order,
    config = {
      cancel: ["登记订单取消", "cancel"],
      refund: ["登记实际退款", "refund"],
      return: ["登记买家退货收货", "return"],
    }[kind];
  let fields = "";
  if (kind === "cancel")
    fields = `<div class="notice warm">请先在店铺完成实际取消。商品已发给买家时，需要先登记退货收货。</div>${field("reason", "取消原因", { type: "textarea", required: true })}<label class="switch-row"><input type="checkbox" name="release_inventory">已确认可以重新出售，释放本订单占用库存</label>`;
  if (kind === "refund")
    fields = `<div class="notice">这里只登记已完成的退款，不会发起资金操作。可分次登记，累计不得超过成交金额。</div><div class="form-grid">${field("refund_reference", "退款流水号 / 凭证编号", { required: true, full: true })}${field("amount_jpy", "本次已退金额（JPY）", { type: "number", required: true, min: 1, max: o.sold_price_jpy, step: 1 })}${field("reason", "退款原因", { type: "textarea", required: true, full: true })}</div>`;
  if (kind === "return")
    fields = field("note", "退货收货与检查记录", {
      type: "textarea",
      required: true,
      placeholder: "记录买家退回商品的数量、成色及检查结果…",
    });
  modal(
    config[0],
    "保留订单、采购成本与物流历史。",
    `<form data-form="backend-order-process" data-kind="${config[1]}" data-id="${esc(o.id)}">${fields}${formActions("保存处理记录")}</form>`,
  );
}
function stockForm() {
  modal(
    "回填店铺可售库存",
    "先在店铺核对实际剩余可售数量，再回填本工作台。",
    `<form data-form="backend-stock" data-id="${esc(state.detail.listing_draft.id)}"><div class="form-grid">${field("remaining_quantity", "店铺当前剩余可售数量", { type: "number", min: 0, step: 1, required: true })}${field("note", "库存核对依据", { type: "textarea", full: true, required: true })}</div>${formActions("保存库存核对")}</form>`,
  );
}
function withdrawalForm() {
  modal(
    "登记店铺已下架",
    "请先在店铺完成实际下架，这里保留原销售和订单履约记录。",
    `<form data-form="backend-withdraw" data-id="${esc(state.detail.listing_draft.id)}">${field("reason", "实际下架原因", { type: "textarea", required: true })}${formActions("确认已下架")}</form>`,
  );
}
function mapShopOrder(id) {
  const row = state.shopImports.find((r) => r.id === id),
    listed = state.items.filter((i) => i.status === "listed");
  modal(
    "核对并关联店铺订单",
    `订单 ${row.external_order_id}，请核对商品、数量和对应成交金额。`,
    `<form data-form="backend-map-order" data-id="${esc(id)}"><div class="form-grid">${field("item_id", "对应本地已上架商品", { full: true, required: true, options: [["", "请选择商品"], ...listed.map((i) => [i.id, i.title_ja || i.japan_title])] })}${field("quantity", "成交数量（件）", { type: "number", min: 1, step: 1, required: true, value: row.quantity || "" })}${field("amount_jpy", "对应商品成交金额（JPY）", { type: "number", min: 1, step: 1, required: true, value: row.amount_jpy || "" })}</div>${formActions("确认并导入本地订单")}</form>`,
  );
}

async function backendAction(action, id, target) {
  switch (action) {
    case "china-browser-open": {
      const channel = $('[data-form="backend-china-search"] [name="browser_channel"]')?.value || "chrome";
      await startJob("/api/automation/browser/open", {scope:"china", browser_channel:channel});
      return true;
    }
    case "china-search":
      if (state.detail?.item) newChinaSearch(state.detail.item);
      return true;
    case "new-discovery":
      newDiscovery();
      return true;
    case "new-watch":
      newWatch();
      return true;
    case "refresh-automation":
      await refreshAutomation();
      toast("任务列表已刷新。");
      return true;
    case "view-job":
      viewJob(id);
      return true;
    case "resume-job":
      await post(`/api/automation/jobs/${id}/resume`, {});
      toast("已继续执行，请等待页面确认。");
      await refreshAutomation();
      return true;
    case "cancel-job":
      await post(`/api/automation/jobs/${id}/cancel`, {});
      await refreshAutomation();
      return true;
    case "select-results": {
      const job = state.jobs.find((j) => j.id === id),
        all = job?.result?.items || [];
      state.selectedResults[id] =
        (state.selectedResults[id] || []).length === all.length
          ? []
          : all.map((_, index) => index);
      $(".job-modal-content").innerHTML = jobBody(job);
      return true;
    }
    case "import-results": {
      const indexes = state.selectedResults[id] || [];
      if (!indexes.length) {
        toast("请先选择要导入的商品。", true);
        return true;
      }
      const result = await post(`/api/automation/jobs/${id}/import`, {
        indexes,
      });
      toast(
        `已导入 ${result.imported.length} 件，跳过 ${result.skipped.length} 件（重复、价格不符合条件或未读取到价格）${result.images_updated?.length ? `，并补齐 ${result.images_updated.length} 件已有商品的图片` : ""}。`,
      );
      await refresh({ silent: true });
      return true;
    }
    case "import-china-results": {
      const indexes = state.selectedResults[id] || [];
      if (!indexes.length) {
        toast("请先选择要加入的闲鱼货源。", true);
        return true;
      }
      const result = await post(`/api/automation/jobs/${id}/import-china-sources`, {indexes});
      toast(`已加入 ${result.imported.length} 条待核验货源，跳过 ${result.skipped.length} 条重复结果。${result.image_job ? "图片候选采集任务已自动排队。" : ""}`);
      await refresh({silent:true});
      if (state.detail) await reloadDetail("sources");
      if (result.image_job) {
        await refreshAutomation();
        const imageJob = state.jobs.find((job) => job.id === result.image_job.id);
        if (imageJob) viewJob(imageJob.id);
      }
      return true;
    }
    case "review-source-images": {
      const job = await api(`/api/china/sources/${encodeURIComponent(id)}/image-review`, {method: "POST", body: JSON.stringify({})});
      await refreshAutomation();
      viewJob(job.id);
      toast("图片识别任务已排队；完成后货源详情会自动刷新。");
      return true;
    }
    case "watch-toggle": {
      const watch = state.watches.find((w) => w.id === id);
      await api(`/api/automation/watches/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !watch.enabled }),
      });
      await refreshAutomation();
      return true;
    }
    case "watch-run": {
      const job = await post(`/api/automation/watches/${id}/run`, {});
      await refreshAutomation();
      viewJob(job.id);
      return true;
    }
    case "watch-archive":
      await api(`/api/automation/watches/${id}`, { method: "DELETE" });
      await refreshAutomation();
      return true;
    case "watch-changes": {
      const changes = await api(`/api/automation/watches/${id}/changes`);
      modal(
        "监控变化记录",
        "记录新出现商品和每次价格变化。",
        changes.length
          ? changes
              .map(
                (change) =>
                  `<div class="review-row"><h3>${esc(change.title)}</h3><p>${change.change_type === "new" ? "首次发现" : `价格变化：JPY ${n(change.previous_price)} → ${n(change.current_price)}`} · ${dateText(change.created_at)}</p>${external(change.url)}</div>`,
              )
              .join("")
          : empty("暂无变化记录", "监控运行后会记录新商品与价格变化。"),
        true,
      );
      return true;
    }
    case "shop-session":
      shopTaskForm("session");
      return true;
    case "shop-cdp-open": {
      const form = $('form[data-form="backend-shop-task"]');
      if (!form) return true;
      const data = Object.fromEntries(new FormData(form));
      if (!data.url?.trim()) {
        toast("请先填写 Mercari Shops 店铺管理页面链接。", true);
        return true;
      }
      if (data.browser_channel !== "chrome") {
        toast("CDP 登录窗口目前使用 Google Chrome，请先选择 Chrome。", true);
        return true;
      }
      await startJob("/api/automation/shops/cdp-browser/open", {
        url: data.url,
        browser_channel: "chrome",
        browser_mode: "existing_chrome",
      });
      return true;
    }
    case "shop-cdp-connect":
      await startJob("/api/automation/shops/session", state.shopSettings);
      return true;
    case "shop-read-orders":
      shopTaskForm("orders");
      return true;
    case "shop-inspect":
      shopTaskForm("inspect");
      return true;
    case "shop-disconnect":
      await startJob("/api/automation/shops/session", {}, "DELETE");
      return true;
    case "fill-shop":
      shopTaskForm("fill", id);
      return true;
    case "map-shop-order":
      mapShopOrder(id);
      return true;
    case "edit-item":
      editItem();
      return true;
    case "archive-item":
      archiveForm("item", state.detail.item.id);
      return true;
    case "restore-item":
      await post(`/api/items/${id}/restore`, {});
      closeDrawer();
      await refresh();
      return true;
    case "edit-source":
      editSource(id);
      return true;
    case "archive-source":
      archiveForm("source", id);
      return true;
    case "restore-source":
      await post(`/api/china/sources/${id}/restore`, {});
      await refresh({ silent: true });
      await reloadDetail("sources");
      return true;
    case "item-history":
      await history("item", state.detail.item.id);
      return true;
    case "order-history":
      await history("order", state.order.id);
      return true;
    case "cancel-order":
      orderProcessForm("cancel");
      return true;
    case "refund-order":
      orderProcessForm("refund");
      return true;
    case "return-receipt":
      orderProcessForm("return");
      return true;
    case "order-sources":
      await openItem(state.order.item_id, "sources");
      return true;
    case "stock-confirm":
      stockForm();
      return true;
    case "withdraw-listing":
      withdrawalForm();
      return true;
    default:
      return false;
  }
}
async function submitBackendForm(form) {
  if (form.dataset.busy === "true") return;
  const button = $('button[type="submit"]', form),
    original = button.innerHTML,
    error = $(".form-error", form),
    kind = form.dataset.form;
  const fd = new FormData(form),
    data = Object.fromEntries(fd);
  form.dataset.busy = "true";
  button.disabled = true;
  button.innerHTML = '<span class="spinner"></span>正在处理…';
  error.classList.remove("visible");
  try {
    if (kind === "backend-discovery") {
      const mode = data.kind;
      delete data.kind;
      data.limit = Number(data.limit);
      data.available_only = fd.has("available_only");
      await startJob(
        mode === "search" ? "/api/japan/search" : `/api/japan/collect/${mode}`,
        data,
      );
    } else if (kind === "backend-china-search") {
      data.limit = Number(data.limit);
      await startJob("/api/china/search", {item_id: form.dataset.id, ...data});
    } else if (kind === "backend-watch") {
      data.interval_minutes = Number(data.interval_minutes);
      data.result_limit = Number(data.result_limit);
      await post("/api/automation/watches", data);
      closeModal(true, true);
      await refreshAutomation();
      if (state.view !== "discovery") location.hash = "discovery";
      toast("监控已创建，应用运行期间会按间隔检查。");
    } else if (kind === "backend-shop-task") {
      const mode = form.dataset.kind,
        path =
          mode === "fill"
            ? `/api/listing/drafts/${form.dataset.id}/fill-shop`
            : mode === "inspect"
              ? "/api/automation/shops/inspect-form"
            : mode === "orders"
              ? "/api/automation/shops/read-orders"
              : "/api/automation/shops/session";
      state.shopSettings = await api("/api/automation/shops/settings", {method: "PUT", body: JSON.stringify(data)});
      await startJob(path, data);
    } else if (kind === "backend-item") {
      data.japan_price_jpy = data.japan_price_jpy
        ? Number(data.japan_price_jpy)
        : null;
      data.japan_image_url = data.japan_image_url || null;
      await api(`/api/items/${form.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail();
      toast("选品资料已更新。");
    } else if (kind === "backend-source") {
      data.price_cny = data.price_cny ? Number(data.price_cny) : null;
      await api(`/api/china/sources/${form.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail("sources");
      toast("货源已修改。");
    } else if (kind === "backend-archive") {
      const isItem = form.dataset.kind === "item";
      await post(
        isItem
          ? `/api/items/${form.dataset.id}/archive`
          : `/api/china/sources/${form.dataset.id}/archive`,
        {},
      );
      closeModal(true, true);
      if (isItem) {
        closeDrawer();
      }
      await refresh({ silent: true });
      if (!isItem) await reloadDetail("sources");
      toast("已归档，历史记录保留。");
    } else if (kind === "backend-order-process") {
      const id = form.dataset.id,
        type = form.dataset.kind;
      if (type === "cancel")
        data.release_inventory = fd.has("release_inventory");
      if (type === "refund") data.amount_jpy = Number(data.amount_jpy);
      const endpoint = {
        cancel: "cancellation",
        refund: "refund-confirmation",
        return: "return-receipt",
      }[type];
      await post(`/api/orders/${id}/${endpoint}`, data);
      closeModal(true, true);
      await refresh({ silent: true });
      await openOrder(id);
      toast("处理记录已保存。");
    } else if (kind === "backend-map-order") {
      data.quantity = Number(data.quantity);
      data.amount_jpy = Number(data.amount_jpy);
      const order = await post(
        `/api/automation/shop-order-imports/${form.dataset.id}/confirm`,
        data,
      );
      closeModal(true, true);
      await refresh({ silent: true });
      await openOrder(order.id);
      toast("店铺订单已关联到本地履约。");
    } else if (kind === "backend-stock" || kind === "backend-withdraw") {
      if (kind === "backend-stock")
        data.remaining_quantity = Number(data.remaining_quantity);
      await post(
        `/api/listing/drafts/${form.dataset.id}/${kind === "backend-stock" ? "inventory-confirmation" : "withdrawal-confirmation"}`,
        data,
      );
      closeModal(true, true);
      await refresh({ silent: true });
      await reloadDetail("overview");
      toast("店铺处理结果已登记。");
    }
  } catch (problem) {
    if (error.isConnected) {
      error.textContent = problem.message;
      error.classList.add("visible");
      error.scrollIntoView({ block: "nearest" });
    } else toast(problem.message, true);
  } finally {
    delete form.dataset.busy;
    if (button.isConnected) {
      button.disabled = false;
      button.innerHTML = original;
    }
  }
}
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.matches('form[data-form^="backend-"]')) {
    event.preventDefault();
    if (form.reportValidity()) submitBackendForm(form);
  }
});
document.addEventListener("change", (event) => {
  const input = event.target;
  if (input.id === "item-scope") {
    state.itemScope = input.value;
    state.filter = "all";
    state.query = "";
    state.page = 1;
    render();
  }
  if (input.classList.contains("result-select")) {
    const selected = new Set(state.selectedResults[input.dataset.job] || []);
    input.checked
      ? selected.add(Number(input.value))
      : selected.delete(Number(input.value));
    state.selectedResults[input.dataset.job] = [...selected];
  }
  if (
    input.name === "kind" &&
    input.closest('form[data-form="backend-discovery"]')
  ) {
    const form = input.form,
      isSearch = input.value === "search";
    form.elements.query.closest(".field").classList.toggle("hidden", !isSearch);
    form.elements.query.required = isSearch;
    $("#collection-url-field").classList.toggle("hidden", isSearch);
    form.elements.url.required = !isSearch;
  }
  if (
    input.name === "kind" &&
    input.closest('form[data-form="backend-watch"]')
  ) {
    const form = input.form,
      prepareOnly = input.value === "listing_prepare",
      query = form.elements.query,
      url = form.elements.url;
    query.closest(".field").classList.toggle("hidden", prepareOnly || input.value === "japan_shop");
    $("#watch-url-field", form).classList.toggle("hidden", prepareOnly || input.value === "japan_search");
    query.required = input.value === "japan_search";
    url.required = input.value === "japan_shop";
  }
});
setInterval(async () => {
  if (
    document.hidden ||
    automationPolling ||
    !(
      state.view === "discovery" ||
      (state.activeJobId && $(".job-modal-content")) ||
      state.jobs.some(
        (j) => !["succeeded", "failed", "cancelled"].includes(j.status),
      )
    )
  )
    return;
  automationPolling = true;
  try {
    await refreshAutomation();
  } catch {
    /* Keep form state when the local service is restarting. */
  } finally {
    automationPolling = false;
  }
}, 3000);
