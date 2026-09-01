"use strict";

const select = (selector, root = document) => root.querySelector(selector);
const selectAll = (selector, root = document) => [...root.querySelectorAll(selector)];

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

const SVG_NAMESPACE = "http://www.w3.org/2000/svg";

function svgElement(tag, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NAMESPACE, tag);
  Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
  if (text !== "") node.textContent = String(text);
  return node;
}

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "--";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4);
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function humanizeKey(key) {
  const labels = {
    users: "用户数",
    active_users: "活跃用户",
    requests: "推荐请求",
    exposures: "曝光数",
    clicks: "点击数",
    ctr: "CTR",
    likes: "点赞数",
    offline_items: "下线内容",
    current_model_version: "当前模型",
    profile_version: "画像版本",
    event_counts: "行为计数",
    feed_type: "信息流",
    model_version: "模型版本",
    fallback_reason: "回退原因",
    latency_ms: "延迟（ms）",
    trained_at: "训练时间",
    published_at: "发布时间",
    data_version: "数据版本",
    status: "状态",
    source_user_id: "数据用户 ID",
    username: "用户名",
    user: "用户",
  };
  return labels[key] || key.replaceAll("_", " ");
}

async function api(path, options = {}) {
  const requestOptions = { credentials: "same-origin", ...options };
  requestOptions.headers = { Accept: "application/json", ...(options.headers || {}) };
  if (requestOptions.body && !(requestOptions.body instanceof FormData)) {
    requestOptions.headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, requestOptions);
  let payload = null;
  if (response.status !== 204) {
    const contentType = response.headers.get("content-type") || "";
    payload = contentType.includes("application/json") ? await response.json() : await response.text();
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? payload.detail : payload;
    throw new ApiError(detail || `请求失败（${response.status}）`, response.status);
  }
  return payload || {};
}

function toast(message, type = "success") {
  const region = select("#toast-region");
  if (!region) return;
  const node = element("div", `toast ${type === "error" ? "error" : ""}`, message);
  region.append(node);
  window.setTimeout(() => node.remove(), 3200);
}

async function loadIdentity() {
  const page = document.body.dataset.page;
  if (page === "login") return null;
  try {
    const user = await api("/api/auth/me");
    const label = select("#current-user");
    if (label) label.textContent = `${user.username} · ${user.role === "admin" ? "管理员" : "用户"}`;
    if (user.role === "admin") selectAll("[data-admin-only]").forEach((node) => { node.hidden = false; });
    if ((page === "dashboard" || page === "contents") && user.role !== "admin") {
      window.location.replace("/feed");
    }
    return user;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      window.location.replace("/login");
      return null;
    }
    toast(error.message || "无法确认登录状态", "error");
    return null;
  }
}

function bindLogout() {
  const button = select("#logout-button");
  if (!button) return;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.replace("/login");
    }
  });
}

function setupLogin() {
  const form = select("#login-form");
  if (!form) return;
  const errorBox = select("#login-error");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.hidden = true;
    const submit = select("button[type='submit']", form);
    submit.disabled = true;
    try {
      const data = new FormData(form);
      const user = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: data.get("username"), password: data.get("password") }),
      });
      window.location.replace(user.role === "admin" ? "/admin/dashboard" : "/feed");
    } catch (error) {
      errorBox.textContent = error.message || "登录失败，请检查账号与密码。";
      errorBox.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
}

function setupFeed() {
  const grid = select("#feed-grid");
  if (!grid) return;
  const state = { feedType: "personalized", page: 1, pageSize: 12, loading: false, hasMore: false };
  const loading = select("#feed-loading");
  const errorPanel = select("#feed-error");
  const emptyPanel = select("#feed-empty");
  const loadMore = select("#load-more");

  function createFeedCard(item, requestId) {
    const card = element("article", "feed-card");
    card.dataset.itemId = item.item_id;
    const cover = element("div", "cover-frame");
    const image = element("img");
    image.src = "/static/placeholder-cover.svg";
    image.alt = "";
    image.width = 640;
    image.height = 360;
    const position = element("span", "position-badge", `#${item.position}`);
    const source = element("span", "source-badge", item.source || "unknown");
    cover.append(image, position, source);

    const body = element("div", "feed-card-body");
    body.append(element("h2", "feed-title", item.title || `内容 ${item.item_id}`));
    body.append(element("p", "reason", item.reason || "暂无推荐解释"));
    const stats = element("div", "card-stats");
    stats.append(
      element("span", "", `喜欢 ${Number(item.likes || 0).toLocaleString()}`),
      element("span", "", `浏览 ${Number(item.views || 0).toLocaleString()}`),
      element("span", "score", `分数 ${Number(item.score || 0).toFixed(4)}`),
    );
    body.append(stats);

    const actions = element("div", "feed-actions");
    const specs = [
      ["click", "打开", "记录点击"],
      ["like", "喜欢", "标记喜欢"],
      ["not_interested", "不感兴趣", "减少此类推荐"],
    ];
    specs.forEach(([eventType, label, title]) => {
      const button = element("button", "", label);
      button.type = "button";
      button.dataset.event = eventType;
      button.title = title;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          const result = await api("/api/events", {
            method: "POST",
            body: JSON.stringify({
              event_id: crypto.randomUUID(),
              request_id: requestId,
              item_id: item.item_id,
              event_type: eventType,
              client_timestamp: new Date().toISOString(),
            }),
          });
          if (eventType === "like") button.classList.add("is-active");
          if (eventType === "not_interested") card.remove();
          toast(`${label}已记录 · 画像版本 ${result.profile_version}`);
        } catch (error) {
          toast(error.message || "行为记录失败", "error");
        } finally {
          button.disabled = false;
        }
      });
      actions.append(button);
    });
    card.append(cover, body, actions);
    return card;
  }

  async function loadFeed(reset = false) {
    if (state.loading) return;
    state.loading = true;
    if (reset) {
      state.page = 1;
      grid.replaceChildren();
      loading.hidden = false;
    }
    errorPanel.hidden = true;
    emptyPanel.hidden = true;
    loadMore.disabled = true;
    try {
      const response = await api(`/api/feeds/${state.feedType}?page=${state.page}&page_size=${state.pageSize}`);
      select("#model-version").textContent = response.model_version || "--";
      select("#request-id").textContent = response.request_id || "--";
      const fallback = select("#fallback-note");
      fallback.textContent = response.fallback_reason ? `已回退：${response.fallback_reason}` : "";
      fallback.hidden = !response.fallback_reason;
      const items = Array.isArray(response.items) ? response.items : [];
      items.forEach((item) => grid.append(createFeedCard(item, response.request_id)));
      state.hasMore = Boolean(response.has_more);
      loadMore.hidden = !state.hasMore;
      if (!items.length && reset) emptyPanel.hidden = false;
    } catch (error) {
      select("#feed-error-message").textContent = error.message || "请稍后重试。";
      errorPanel.hidden = false;
      loadMore.hidden = true;
    } finally {
      state.loading = false;
      loading.hidden = true;
      loadMore.disabled = false;
    }
  }

  selectAll("[data-feed]").forEach((tab) => {
    tab.addEventListener("click", () => {
      selectAll("[data-feed]").forEach((node) => node.setAttribute("aria-selected", "false"));
      tab.setAttribute("aria-selected", "true");
      state.feedType = tab.dataset.feed;
      loadFeed(true);
    });
  });
  loadMore.addEventListener("click", () => { state.page += 1; loadFeed(false); });
  select("#retry-feed").addEventListener("click", () => loadFeed(true));
  loadFeed(true);
}

function appendMetrics(container, entries) {
  container.replaceChildren();
  entries.forEach(([label, value, compact = false]) => {
    const card = element("div", "metric-card");
    card.append(element("div", "metric-label", label));
    card.append(element("div", `metric-value ${compact ? "metric-value-small" : ""}`, displayValue(value)));
    container.append(card);
  });
}

function renderRecord(container, payload) {
  container.replaceChildren();
  if (!payload || typeof payload !== "object") {
    container.append(element("div", "state-panel", "暂无数据"));
    return;
  }
  const records = Array.isArray(payload) ? payload : [payload];
  if (!records.length) {
    container.append(element("div", "state-panel", "暂无数据"));
    return;
  }
  if (records.every((record) => record && typeof record === "object" && !Array.isArray(record))) {
    const keys = [...new Set(records.flatMap((record) => Object.keys(record)))].slice(0, 10);
    const wrap = element("div", "table-wrap");
    const table = element("table", "data-table");
    const head = element("thead");
    const headRow = element("tr");
    keys.forEach((key) => headRow.append(element("th", "", humanizeKey(key))));
    head.append(headRow);
    const body = element("tbody");
    records.forEach((record) => {
      const row = element("tr");
      keys.forEach((key) => row.append(element("td", "", displayValue(record[key]))));
      body.append(row);
    });
    table.append(head, body);
    wrap.append(table);
    container.append(wrap);
  } else {
    container.append(element("pre", "", displayValue(payload)));
  }
}

const TREND_METRICS = {
  requests: "请求",
  exposures: "曝光",
  clicks: "点击",
  likes: "点赞",
  ctr: "CTR",
};

function parseUtcTimestamp(value) {
  if (!value) return null;
  const timestamp = String(value);
  const normalized = /(?:Z|[+-]\d\d:\d\d)$/.test(timestamp) ? timestamp : `${timestamp}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatTrendTime(value, includeDate = true) {
  const parsed = parseUtcTimestamp(value);
  if (!parsed) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    ...(includeDate ? { month: "2-digit", day: "2-digit" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(parsed);
}

function formatTrendValue(metric, value) {
  const numeric = Number(value || 0);
  if (metric === "ctr") return `${(numeric * 100).toFixed(2)}%`;
  return Math.round(numeric).toLocaleString();
}

function renderTrendChart(payload, metric) {
  const points = Array.isArray(payload?.points) ? payload.points : [];
  const plot = select("#dashboard-trend-plot");
  const chart = select("#trend-chart");
  const tooltip = select("#trend-tooltip");
  if (!plot || !chart || !tooltip || !points.length) return;

  const svg = select("#dashboard-trend-svg");
  const width = Math.max(chart.clientWidth, 320);
  const height = Math.max(chart.clientHeight, 240);
  const bounds = {
    left: width < 600 ? 52 : 66,
    right: width < 600 ? 14 : 24,
    top: 22,
    bottom: 46,
  };
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const plotWidth = width - bounds.left - bounds.right;
  const plotHeight = height - bounds.top - bounds.bottom;
  const values = points.map((point) => Number(point[metric] || 0));
  const observedMax = Math.max(...values, 0);
  const upperBound = observedMax > 0 ? observedMax * 1.12 : 1;
  const xFor = (index) => (
    points.length === 1
      ? bounds.left + plotWidth / 2
      : bounds.left + (index / (points.length - 1)) * plotWidth
  );
  const yFor = (value) => bounds.top + plotHeight - (value / upperBound) * plotHeight;

  plot.replaceChildren();
  tooltip.hidden = true;
  select("#dashboard-trend-title").textContent = `${TREND_METRICS[metric]}趋势`;
  select("#dashboard-trend-desc").textContent = (
    `共 ${points.length} 个时间桶，当前最高值 ${formatTrendValue(metric, observedMax)}`
  );

  for (let step = 0; step <= 4; step += 1) {
    const ratio = step / 4;
    const y = bounds.top + plotHeight - ratio * plotHeight;
    plot.append(svgElement("line", {
      x1: bounds.left,
      y1: y,
      x2: width - bounds.right,
      y2: y,
      class: "trend-grid-line",
    }));
    plot.append(svgElement("text", {
      x: bounds.left - 12,
      y: y + 4,
      class: "trend-axis-label trend-axis-label-y",
      "text-anchor": "end",
    }, formatTrendValue(metric, upperBound * ratio)));
  }

  const labelDivisions = width < 600 ? 2 : 4;
  const labelIndexes = new Set([0, points.length - 1]);
  for (let step = 1; step < labelDivisions; step += 1) {
    labelIndexes.add(Math.round(((points.length - 1) * step) / labelDivisions));
  }
  [...labelIndexes].sort((left, right) => left - right).forEach((index) => {
    plot.append(svgElement("text", {
      x: xFor(index),
      y: height - 15,
      class: "trend-axis-label",
      "text-anchor": index === 0 ? "start" : (index === points.length - 1 ? "end" : "middle"),
    }, formatTrendTime(points[index].bucket_start, points.length > 12)));
  });

  const coordinates = points.map((point, index) => [xFor(index), yFor(values[index]), point]);
  const lineDefinition = coordinates
    .map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`)
    .join(" ");
  if (coordinates.length > 1) {
    const areaDefinition = (
      `${lineDefinition} L ${coordinates.at(-1)[0].toFixed(2)} ${(bounds.top + plotHeight).toFixed(2)}`
      + ` L ${coordinates[0][0].toFixed(2)} ${(bounds.top + plotHeight).toFixed(2)} Z`
    );
    plot.append(svgElement("path", { d: areaDefinition, class: "trend-area" }));
  }
  plot.append(svgElement("path", { d: lineDefinition, class: "trend-line" }));

  const showTooltip = (point, x, y) => {
    tooltip.textContent = (
      `${formatTrendTime(point.bucket_start)} · ${TREND_METRICS[metric]} `
      + formatTrendValue(metric, point[metric])
    );
    tooltip.hidden = false;
    const chartWidth = chart.getBoundingClientRect().width;
    const left = Math.min(Math.max(x, 86), chartWidth - 86);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(y - 42, 8)}px`;
  };
  const hideTooltip = () => { tooltip.hidden = true; };

  coordinates.forEach(([x, y, point]) => {
    const marker = svgElement("circle", {
      cx: x,
      cy: y,
      r: points.length > 80 ? 2.8 : 4,
      class: "trend-point",
      tabindex: "0",
      "aria-label": (
        `${formatTrendTime(point.bucket_start)}，${TREND_METRICS[metric]}，`
        + `${formatTrendValue(metric, point[metric])}`
      ),
    });
    marker.addEventListener("pointerenter", () => showTooltip(point, x, y));
    marker.addEventListener("focus", () => showTooltip(point, x, y));
    marker.addEventListener("pointerleave", hideTooltip);
    marker.addEventListener("blur", hideTooltip);
    plot.append(marker);
  });
}

function setupProfile() {
  const summary = select("#profile-summary");
  if (!summary) return;
  async function loadProfile() {
    const loading = select("#profile-loading");
    const errorBox = select("#profile-error");
    loading.hidden = false;
    errorBox.hidden = true;
    try {
      const profile = await api("/api/profile/me");
      const eventCounts = profile.event_counts || {};
      const totalEvents = Object.values(eventCounts).reduce((sum, value) => sum + Number(value || 0), 0);
      appendMetrics(summary, [
        ["画像版本", profile.profile_version ?? 0],
        ["累计行为", totalEvents],
        ["喜欢", eventCounts.like ?? eventCounts.likes ?? 0],
        ["不感兴趣", eventCounts.not_interested ?? 0],
      ]);
      summary.hidden = false;
      const details = select("#profile-details");
      details.replaceChildren();
      Object.entries(profile).forEach(([key, value]) => {
        const row = element("div", "detail-row");
        row.append(element("div", "detail-key", humanizeKey(key)));
        row.append(element("div", "detail-value", displayValue(value)));
        details.append(row);
      });
    } catch (error) {
      errorBox.textContent = error.message || "画像读取失败";
      errorBox.hidden = false;
    } finally {
      loading.hidden = true;
    }
  }
  select("#refresh-profile").addEventListener("click", loadProfile);
  loadProfile();
}

const RELIABILITY_API = Object.freeze({
  runtime: "/api/admin/models/runtime",
  evaluation: "/api/admin/models/current/evaluation",
  requests: "/api/admin/request-traces",
  observability: "/api/admin/observability",
  rollback: "/api/admin/models/rollback",
});

const OPERATION_MESSAGES = Object.freeze({
  publishing: "发布中：正在校验并加载候选模型…",
  published: "发布成功：新请求已切换到目标模型。",
  publish_failed: "发布失败：当前运行模型保持不变。",
  rolling_back: "回滚中：正在恢复上一稳定版本…",
  rolled_back: "回滚成功：新请求已使用上一稳定版本。",
  rollback_failed: "回滚失败：当前运行模型保持不变。",
});

function setAsyncRegionState(target, mode, message) {
  const region = typeof target === "string" ? select(target) : target;
  if (!region) return;
  region.dataset.state = mode;
  region.replaceChildren(element("div", "compact-state", message));
}

function formatAdminTime(value) {
  return formatTrendTime(value, true);
}

function formatRate(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : "--";
}

function formatLatency(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${numeric.toFixed(1)} ms` : "--";
}

function dashboardWindowLabel(windowName) {
  return { "1h": "近1小时", "6h": "近6小时", "24h": "近24小时", all: "全部历史" }[windowName]
    || String(windowName || "当前范围");
}

function metricTriplet(metrics, missingLabel) {
  if (!metrics) return element("span", "muted", missingLabel);
  const group = element("div", "metric-triplet");
  [
    ["R@20", metrics.recall_at_20],
    ["N@20", metrics.ndcg_at_20],
    ["C@20", metrics.coverage_at_20],
  ].forEach(([label, value]) => {
    const row = element("span");
    const numeric = Number(value);
    row.append(`${label} `, element("strong", "", Number.isFinite(numeric) ? numeric.toFixed(4) : "--"));
    group.append(row);
  });
  return group;
}

function renderModelDecision(payload) {
  const target = select("#model-decision-table");
  const policies = Array.isArray(payload?.policies) ? payload.policies : [];
  if (!policies.length) {
    setAsyncRegionState(target, "empty", "当前模型没有可展示的评估记录。");
    return;
  }

  const meta = select("#model-decision-meta");
  meta.textContent = (
    `${payload.model_version || "未知版本"} · 选型指标 ${payload.selection_metric || "--"}`
    + ` · 当前策略 ${payload.selected_policy || "--"}`
  );

  const wrap = element("div", "table-wrap");
  const table = element("table", "data-table decision-table");
  const head = element("thead");
  const headRow = element("tr");
  [
    "策略", "选型", "Validation / Overall", "Validation / Warm",
    "Validation / Pure cold", "Test / Overall", "Test / Warm", "Test / Pure cold",
  ].forEach((label) => headRow.append(element("th", "", label)));
  head.append(headRow);
  const body = element("tbody");
  policies.forEach((policy) => {
    const row = element("tr", policy.selected ? "is-selected" : "");
    row.append(element("td", "", policy.policy || "--"));
    const decision = element("td");
    decision.append(element(
      "span",
      `decision-badge ${policy.selected ? "is-selected" : "is-rejected"}`,
      policy.selected ? "已选" : "未选",
    ));
    row.append(decision);
    [
      [policy.validation?.overall, "Validation 数据缺失"],
      [policy.validation?.warm, "Validation 数据缺失"],
      [policy.validation?.pure_cold, "Validation 数据缺失"],
      [policy.test?.overall, "未正式测试"],
      [policy.test?.warm, "未正式测试"],
      [policy.test?.pure_cold, "未正式测试"],
    ].forEach(([metrics, missingLabel]) => {
      const cell = element("td");
      cell.append(metricTriplet(metrics, missingLabel));
      row.append(cell);
    });
    body.append(row);
  });
  table.append(head, body);
  wrap.append(table);
  target.dataset.state = "ready";
  target.replaceChildren(wrap);
}

function runtimePresentation(payload) {
  const runtimeState = ["ready", "recovered", "fallback"].includes(payload?.status)
    ? payload.status
    : "fallback";
  if (runtimeState === "ready" && payload?.validation?.status === "legacy_unverified") {
    return ["legacy", "旧版未校验"];
  }
  const labels = { ready: "运行正常", recovered: "已恢复", fallback: "Fallback 运行" };
  return [runtimeState, labels[runtimeState]];
}

function renderRuntime(payload, dashboardState) {
  const target = select("#model-runtime");
  const badge = select("#runtime-status-badge");
  const [presentation, label] = runtimePresentation(payload);
  target.dataset.state = presentation;
  badge.className = `runtime-badge is-${presentation}`;
  badge.textContent = label;

  const current = payload.current;
  const previous = payload.previous;
  const summary = element("dl", "runtime-summary");
  [
    ["当前版本", current?.model_version || "确定性 fallback"],
    ["服务策略", current?.serving_policy || "deterministic"],
    ["上一版本", previous?.model_version || "无可回滚版本"],
    ["加载时间", formatAdminTime(payload.loaded_at)],
  ].forEach(([term, value]) => {
    const field = element("div", "runtime-field");
    field.append(element("dt", "", term), element("dd", "", value));
    summary.append(field);
  });

  const validation = payload.validation || {};
  const errors = Array.isArray(validation.errors) ? validation.errors.filter(Boolean) : [];
  const validationClass = validation.status === "error"
    ? "is-error"
    : validation.status === "legacy_unverified" ? "is-warning" : "";
  const validationLabels = {
    ok: "Artifact 校验通过",
    legacy_unverified: "Legacy artifact：缺少完整 checksum 证据",
    error: "Artifact 校验失败",
  };
  const validationNote = element("p", `runtime-validation ${validationClass}`.trim());
  validationNote.textContent = (
    `${validationLabels[validation.status] || "Artifact 状态未知"}`
    + ` · ${formatAdminTime(validation.checked_at)}`
    + (errors.length ? ` · ${errors.join("；")}` : "")
  );
  target.replaceChildren(summary, validationNote);
  dashboardState.runtime = payload;
}

function renderModelRegistry(payload, dashboardState) {
  const target = select("#model-list");
  const records = Array.isArray(payload) ? payload : (payload?.items || []);
  dashboardState.models = records;
  if (!records.length) {
    setAsyncRegionState(target, "empty", "当前没有可发布的模型版本。");
  } else {
    target.dataset.state = "ready";
    renderRecord(target, records);
  }

  const selector = select("#publish-model-version");
  const currentVersion = dashboardState.runtime?.current?.model_version;
  const selectedBefore = selector.value;
  const candidates = records.filter((record) => {
    const version = record.id || record.model_version;
    return version && version !== currentVersion && record.status !== "published";
  });
  selector.replaceChildren();
  if (!candidates.length) {
    selector.append(element("option", "", "没有可发布的候选版本"));
    selector.value = "";
  } else {
    candidates.forEach((record) => {
      const version = record.id || record.model_version;
      const option = element("option", "", `${version} · ${record.status || "candidate"}`);
      option.value = version;
      selector.append(option);
    });
    if (candidates.some((record) => (record.id || record.model_version) === selectedBefore)) {
      selector.value = selectedBefore;
    }
  }
  dashboardState.candidates = candidates;
}

function renderObservabilityGroups(target, groups) {
  if (!Array.isArray(groups) || !groups.length) {
    setAsyncRegionState(target, "empty", "暂无分组请求。");
    return;
  }
  const list = element("dl", "health-group-list");
  groups.forEach((group) => {
    const row = element("div", "health-group-row");
    row.append(
      element("dt", "", group.key || "--"),
      element("dd", "", `${Number(group.requests || 0).toLocaleString()} 次`),
      element("dd", "", `回退 ${formatRate(group.fallback_rate)}`),
      element("dd", "", `P95 ${formatLatency(group.latency_ms?.p95)}`),
    );
    list.append(row);
  });
  target.dataset.state = "ready";
  target.replaceChildren(list);
}

function renderObservability(payload) {
  const target = select("#observability-health");
  const latency = payload.latency_ms || {};
  const metrics = element("div", "health-metrics");
  [
    ["请求", Number(payload.requests || 0).toLocaleString()],
    ["Fallback", `${Number(payload.fallback_count || 0).toLocaleString()} · ${formatRate(payload.fallback_rate)}`],
    ["P50", formatLatency(latency.p50)],
    ["P95", formatLatency(latency.p95)],
  ].forEach(([label, value]) => {
    const item = element("div", "health-metric");
    item.append(element("span", "", label), element("strong", "", value));
    metrics.append(item);
  });

  const alerts = element("ul", "health-alerts");
  const alertItems = Array.isArray(payload.alerts) ? payload.alerts : [];
  const requestCount = Number(payload.requests || 0);
  if (requestCount < 20) {
    alerts.append(element(
      "li",
      "is-insufficient",
      `样本不足，暂不判断告警 · ${requestCount}/20 个请求 · 最大延迟 ${formatLatency(latency.max)}`,
    ));
  } else if (!alertItems.length) {
    alerts.append(element("li", "is-healthy", `未触发被动告警 · 最大延迟 ${formatLatency(latency.max)}`));
  } else {
    alertItems.forEach((alert) => alerts.append(element("li", "", alert.message || alert.code)));
  }
  target.dataset.state = "ready";
  target.replaceChildren(metrics, alerts);
  select("#health-window-meta").textContent = dashboardWindowLabel(payload.window);
  renderObservabilityGroups(select("#observability-by-feed"), payload.by_feed);
  renderObservabilityGroups(select("#observability-by-model"), payload.by_model);
}

function renderRequestTimeline(payload, onSelect) {
  const target = select("#request-timeline");
  const items = Array.isArray(payload?.items) ? payload.items : [];
  select("#request-timeline-meta").textContent = dashboardWindowLabel(payload?.window);
  if (!items.length) {
    setAsyncRegionState(target, "empty", "当前范围暂无推荐请求。");
    return;
  }

  const timeline = element("ol", "request-timeline");
  items.forEach((item) => {
    const hasFallback = Boolean(item.fallback_reason);
    const entry = element("li", `request-timeline-item ${hasFallback ? "has-fallback" : ""}`.trim());
    const selectButton = element("button", "request-timeline-button");
    selectButton.type = "button";
    selectButton.title = "查看该请求的曝光与行为详情";
    selectButton.setAttribute("aria-pressed", "false");
    const heading = element("div", "trace-heading");
    const requestId = element("code", "", item.request_id || "--");
    requestId.title = item.request_id || "";
    heading.append(
      requestId,
      element("span", `trace-badge ${hasFallback ? "is-fallback" : ""}`.trim(), hasFallback ? "Fallback" : "正常"),
    );
    const meta = element("div", "trace-meta");
    meta.append(
      element("span", "", formatAdminTime(item.created_at)),
      element("span", "", item.username || "--"),
      element("span", "", item.feed_type || "--"),
      element("span", "", item.model_version || "--"),
      element("span", "", formatLatency(item.feed_build_latency_ms)),
    );
    const counts = element("div", "trace-counts");
    const exposureCount = Number(item.exposures || 0);
    const behaviorLabel = (label, value) => {
      const count = Number(value || 0);
      return `${label} ${count} · ${exposureCount ? formatRate(count / exposureCount) : "--"}`;
    };
    counts.append(
      element("span", "", `曝光 ${exposureCount}`),
      element("span", "", behaviorLabel("点击", item.clicks)),
      element("span", "", behaviorLabel("点赞", item.likes)),
      element("span", "", behaviorLabel("不感兴趣", item.not_interested)),
    );
    selectButton.append(heading, meta, counts);
    if (hasFallback) {
      selectButton.append(element("p", "trace-fallback-reason", `原因：${item.fallback_reason}`));
    }
    selectButton.addEventListener("click", () => {
      selectAll(".request-timeline-button").forEach((button) => {
        button.setAttribute("aria-pressed", "false");
      });
      selectButton.setAttribute("aria-pressed", "true");
      onSelect(item.request_id);
    });
    entry.append(selectButton);
    timeline.append(entry);
  });
  target.dataset.state = "ready";
  target.replaceChildren(timeline);
}

function renderRequestTraceDetail(payload) {
  const target = select("#request-trace-result");
  const request = payload?.request || {};
  const exposures = Array.isArray(payload?.exposures) ? payload.exposures : [];
  const events = Array.isArray(payload?.events) ? payload.events : [];
  const summary = element("dl", "trace-detail-summary");
  [
    ["请求 ID", request.id || "--"],
    ["Feed", request.feed_type || "--"],
    ["模型", request.model_version || "--"],
    ["构建延迟", formatLatency(request.latency_ms)],
    ["创建时间", formatAdminTime(request.created_at)],
    ["Fallback", request.fallback_reason || "无"],
  ].forEach(([term, value]) => {
    const field = element("div", "trace-detail-field");
    field.append(element("dt", "", term), element("dd", "", value));
    summary.append(field);
  });

  const exposureSection = element("section", "trace-detail-section");
  exposureSection.append(element("h4", "", `曝光顺序 · ${exposures.length}`));
  if (!exposures.length) {
    exposureSection.append(element("p", "muted", "该请求没有曝光记录。"));
  } else {
    const exposureList = element("ol", "trace-detail-timeline");
    exposures.forEach((exposure) => {
      const row = element("li");
      row.append(
        element("strong", "", `#${exposure.position ?? "--"} · Item ${exposure.item_id ?? "--"}`),
        element("span", "", `${exposure.source || "--"} · 分数 ${Number(exposure.score || 0).toFixed(4)}`),
        element("span", "", exposure.reason || "无推荐理由"),
      );
      exposureList.append(row);
    });
    exposureSection.append(exposureList);
  }

  const eventSection = element("section", "trace-detail-section");
  eventSection.append(element("h4", "", `事件时间线 · ${events.length}`));
  if (!events.length) {
    eventSection.append(element("p", "muted", "该请求尚无后续事件。"));
  } else {
    const eventList = element("ol", "trace-detail-timeline event-timeline");
    events.forEach((event) => {
      const row = element("li");
      row.append(
        element("strong", "", `${humanizeKey(event.event_type)} · Item ${event.item_id ?? "--"}`),
        element("span", "", `${formatAdminTime(event.created_at)} · 位置 ${event.position ?? "--"}`),
      );
      eventList.append(row);
    });
    eventSection.append(eventList);
  }
  target.classList.remove("muted");
  target.dataset.state = "ready";
  target.replaceChildren(summary, exposureSection, eventSection);
}

function setupDashboard() {
  const overview = select("#overview-metrics");
  if (!overview) return;
  const state = {
    window: "24h",
    metric: "requests",
    trends: null,
    requestVersion: 0,
    reliabilityRequestVersion: 0,
    runtime: null,
    models: [],
    candidates: [],
    operationState: "idle",
  };

  function showTrendState(mode, message = "") {
    const loading = select("#trend-loading");
    const error = select("#trend-error");
    const empty = select("#trend-empty");
    const chart = select("#trend-chart");
    loading.hidden = mode !== "loading";
    error.hidden = mode !== "error";
    empty.hidden = mode !== "empty";
    chart.hidden = mode !== "chart";
    if (mode === "error") error.textContent = message || "趋势数据读取失败";
  }

  function updateTrendMeta(payload) {
    const labels = { "1h": "近1小时", "6h": "近6小时", "24h": "近24小时", all: "全部历史" };
    const start = payload.window_start ? formatTrendTime(payload.window_start) : null;
    const end = formatTrendTime(payload.window_end);
    const range = start ? `${start} - ${end}` : labels[payload.window] || labels[state.window];
    select("#trend-window-meta").textContent = (
      `${range} · ${Number(payload.bucket_minutes || 0).toLocaleString()} 分钟/点`
    );
  }

  function displayTrends(payload) {
    state.trends = payload;
    updateTrendMeta(payload);
    if (!Array.isArray(payload.points) || !payload.points.length) {
      showTrendState("empty");
      return;
    }
    showTrendState("chart");
    renderTrendChart(payload, state.metric);
  }

  function setAggregateControlsDisabled(disabled) {
    selectAll("[data-window]").forEach((button) => { button.disabled = disabled; });
    select("#refresh-dashboard").disabled = disabled;
  }

  function showRegionError(container, message) {
    const gridClass = container === overview ? " dashboard-grid-state" : "";
    container.replaceChildren(element("div", `state-panel state-error${gridClass}`, message));
  }

  async function loadDashboard() {
    const errorBox = select("#dashboard-error");
    const requestVersion = state.requestVersion + 1;
    state.requestVersion = requestVersion;
    errorBox.hidden = true;
    setAggregateControlsDisabled(true);
    showTrendState("loading");
    const query = `window=${encodeURIComponent(state.window)}`;
    const [summaryResult, diagnosticsResult, trendsResult] = await Promise.allSettled([
      api(`/api/admin/dashboard?${query}`),
      api(`/api/admin/feeds/diagnostics?${query}`),
      api(`/api/admin/dashboard/trends?${query}`),
    ]);
    if (requestVersion !== state.requestVersion) return;

    if (summaryResult.status === "fulfilled") {
      const summary = summaryResult.value;
      appendMetrics(overview, [
        ["用户数", summary.users], ["活跃用户", summary.active_users],
        ["推荐请求", summary.requests], ["曝光数", summary.exposures],
        ["点击数", summary.clicks], ["CTR", `${(Number(summary.ctr || 0) * 100).toFixed(2)}%`],
        ["点赞数", summary.likes], ["下线内容", summary.offline_items],
        ["当前模型", summary.current_model_version, true],
      ]);
      renderRecord(select("#feed-shares"), summary.feed_shares || {});
      renderRecord(select("#hot-items"), summary.hot_items || []);
    } else {
      const message = summaryResult.reason?.message || "概览指标读取失败";
      errorBox.textContent = message;
      errorBox.hidden = false;
      showRegionError(overview, message);
      showRegionError(select("#feed-shares"), message);
      showRegionError(select("#hot-items"), message);
    }

    if (diagnosticsResult.status === "fulfilled") {
      const diagnostics = diagnosticsResult.value;
      renderRecord(select("#feed-diagnostics"), diagnostics.items || diagnostics);
    } else {
      showRegionError(
        select("#feed-diagnostics"),
        diagnosticsResult.reason?.message || "信息流诊断读取失败",
      );
    }

    if (trendsResult.status === "fulfilled") {
      displayTrends(trendsResult.value);
    } else {
      state.trends = null;
      showTrendState("error", trendsResult.reason?.message || "趋势数据读取失败");
    }
    setAggregateControlsDisabled(false);
  }

  function updateOperationControls() {
    const pending = ["publishing", "rolling_back"].includes(state.operationState);
    const selector = select("#publish-model-version");
    const publish = select("#publish-model-button");
    const rollback = select("#rollback-model-button");
    selector.disabled = pending || !state.candidates.length;
    publish.disabled = pending || !selector.value;
    rollback.disabled = pending || !state.runtime?.previous;
    publish.textContent = state.operationState === "publishing" ? "发布中…" : "发布";
    rollback.textContent = state.operationState === "rolling_back" ? "回滚中…" : "回滚";
    publish.setAttribute("aria-busy", state.operationState === "publishing" ? "true" : "false");
    rollback.setAttribute("aria-busy", state.operationState === "rolling_back" ? "true" : "false");
  }

  function setOperationStatus(operationState, detail = "") {
    state.operationState = operationState;
    const target = select("#model-operation-status");
    target.dataset.state = operationState;
    target.textContent = `${OPERATION_MESSAGES[operationState] || ""}${detail ? ` ${detail}` : ""}`.trim();
    target.hidden = operationState === "idle";
    updateOperationControls();
  }

  function setReliabilityLoading() {
    select("#runtime-status-badge").className = "runtime-badge is-loading";
    select("#runtime-status-badge").textContent = "加载中";
    setAsyncRegionState("#model-runtime", "loading", "正在读取运行状态…");
    setAsyncRegionState("#model-list", "loading", "正在读取模型版本…");
    setAsyncRegionState("#model-decision-table", "loading", "正在读取评估证据…");
    setAsyncRegionState("#observability-health", "loading", "正在计算延迟与回退率…");
    setAsyncRegionState("#observability-by-feed", "loading", "正在读取…");
    setAsyncRegionState("#observability-by-model", "loading", "正在读取…");
    setAsyncRegionState("#request-timeline", "loading", "正在读取请求时间线…");
  }

  async function loadRequestTrace(requestId) {
    const target = select("#request-trace-result");
    select("#trace-request-id").value = requestId || "";
    setAsyncRegionState(target, "loading", "正在查询请求链路…");
    try {
      const result = await api(`/api/admin/requests/${encodeURIComponent(requestId)}`);
      renderRequestTraceDetail(result);
    } catch (error) {
      setAsyncRegionState(target, "error", error.message || "请求链路读取失败");
    }
  }

  async function loadReliabilityDashboard() {
    const requestVersion = state.reliabilityRequestVersion + 1;
    state.reliabilityRequestVersion = requestVersion;
    setReliabilityLoading();
    const query = `window=${encodeURIComponent(state.window)}`;
    const results = await Promise.allSettled([
      api(RELIABILITY_API.runtime),
      api(RELIABILITY_API.evaluation),
      api(`${RELIABILITY_API.requests}?${query}`),
      api(`${RELIABILITY_API.observability}?${query}`),
      api("/api/admin/models"),
    ]);
    if (requestVersion !== state.reliabilityRequestVersion) return;

    const [runtimeResult, evaluationResult, requestsResult, observabilityResult, modelsResult] = results;
    if (runtimeResult.status === "fulfilled") {
      renderRuntime(runtimeResult.value, state);
    } else {
      state.runtime = null;
      const message = runtimeResult.reason?.message || "运行状态读取失败";
      setAsyncRegionState("#model-runtime", "error", message);
      select("#runtime-status-badge").className = "runtime-badge is-error";
      select("#runtime-status-badge").textContent = "读取失败";
    }

    if (modelsResult.status === "fulfilled") {
      renderModelRegistry(modelsResult.value, state);
    } else {
      state.models = [];
      state.candidates = [];
      setAsyncRegionState("#model-list", "error", modelsResult.reason?.message || "模型版本读取失败");
      const selector = select("#publish-model-version");
      selector.replaceChildren(element("option", "", "候选版本读取失败"));
    }

    if (evaluationResult.status === "fulfilled") {
      renderModelDecision(evaluationResult.value);
    } else {
      setAsyncRegionState(
        "#model-decision-table",
        "error",
        evaluationResult.reason?.message || "评估证据读取失败",
      );
    }

    if (requestsResult.status === "fulfilled") {
      renderRequestTimeline(requestsResult.value, loadRequestTrace);
    } else {
      setAsyncRegionState("#request-timeline", "error", requestsResult.reason?.message || "请求时间线读取失败");
    }

    if (observabilityResult.status === "fulfilled") {
      renderObservability(observabilityResult.value);
    } else {
      const message = observabilityResult.reason?.message || "在线可靠性指标读取失败";
      setAsyncRegionState("#observability-health", "error", message);
      setAsyncRegionState("#observability-by-feed", "error", message);
      setAsyncRegionState("#observability-by-model", "error", message);
    }
    updateOperationControls();
  }

  async function publishSelectedModel() {
    const selector = select("#publish-model-version");
    const version = selector.value;
    if (!version || !window.confirm(`确认发布模型 ${version}？`)) return;
    setOperationStatus("publishing");
    try {
      await api(`/api/admin/models/${encodeURIComponent(version)}/publish`, { method: "POST" });
      setOperationStatus("published", `目标版本：${version}`);
      toast(`模型 ${version} 发布成功`);
      await loadReliabilityDashboard();
    } catch (error) {
      setOperationStatus("publish_failed", error.message || "请检查 artifact 后重试。");
      toast(error.message || "模型发布失败", "error");
    }
  }

  async function rollbackModel() {
    const previous = state.runtime?.previous?.model_version;
    if (!previous || !window.confirm(`确认回滚到 ${previous}？`)) return;
    setOperationStatus("rolling_back");
    try {
      await api(RELIABILITY_API.rollback, { method: "POST" });
      setOperationStatus("rolled_back", `目标版本：${previous}`);
      toast(`已回滚到 ${previous}`);
      await loadReliabilityDashboard();
    } catch (error) {
      setOperationStatus("rollback_failed", error.message || "请检查上一版本后重试。");
      toast(error.message || "模型回滚失败", "error");
    }
  }

  selectAll("[data-window]").forEach((button) => {
    button.addEventListener("click", () => {
      state.window = button.dataset.window;
      selectAll("[data-window]").forEach((node) => node.setAttribute("aria-selected", "false"));
      button.setAttribute("aria-selected", "true");
      loadDashboard();
      loadReliabilityDashboard();
    });
  });
  selectAll("[data-trend-metric]").forEach((button) => {
    button.addEventListener("click", () => {
      state.metric = button.dataset.trendMetric;
      selectAll("[data-trend-metric]").forEach((node) => node.setAttribute("aria-selected", "false"));
      button.setAttribute("aria-selected", "true");
      if (state.trends?.points?.length) renderTrendChart(state.trends, state.metric);
    });
  });
  select("#refresh-dashboard").addEventListener("click", () => {
    loadDashboard();
    loadReliabilityDashboard();
  });
  select("#publish-model-version").addEventListener("change", updateOperationControls);
  select("#publish-model-button").addEventListener("click", publishSelectedModel);
  select("#rollback-model-button").addEventListener("click", rollbackModel);
  let resizeTimer = null;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (state.trends?.points?.length && !select("#trend-chart").hidden) {
        renderTrendChart(state.trends, state.metric);
      }
    }, 120);
  });
  select("#user-debug-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const target = select("#user-debug-result");
    const userId = new FormData(event.currentTarget).get("user_id");
    target.textContent = "正在查询…";
    try {
      const result = await api(`/api/admin/users/${encodeURIComponent(userId)}/debug`);
      renderRecord(target, result.items || result);
    } catch (error) {
      target.textContent = error.message || "用户调试信息读取失败";
    }
  });
  select("#request-trace-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const requestId = new FormData(event.currentTarget).get("request_id");
    await loadRequestTrace(requestId);
  });
  loadDashboard();
  loadReliabilityDashboard();
}

function setupContents() {
  const tableBody = select("#contents-body");
  if (!tableBody) return;
  const dialog = select("#operation-dialog");
  const form = select("#operation-form");

  function openOperation(type, itemId) {
    form.reset();
    select("#operation-type").value = type;
    select("#operation-item-id").value = itemId;
    const labels = { force: "设置强推", offline: "下线内容", restore: "恢复内容" };
    select("#operation-title").textContent = `${labels[type]} · #${itemId}`;
    select("#force-fields").hidden = type !== "force";
    select("#operation-error").hidden = true;
    dialog.showModal();
  }

  async function loadContents() {
    const params = new URLSearchParams();
    const query = select("#content-query").value.trim();
    const status = select("#content-status").value;
    if (query) params.set("q", query);
    if (status) params.set("status", status);
    tableBody.innerHTML = '<tr><td colspan="6" class="table-state">正在加载内容…</td></tr>';
    select("#contents-error").hidden = true;
    try {
      const payload = await api(`/api/admin/contents?${params}`);
      const items = Array.isArray(payload) ? payload : (payload.items || []);
      tableBody.replaceChildren();
      if (!items.length) {
        const row = element("tr");
        const cell = element("td", "table-state", "没有符合条件的内容");
        cell.colSpan = 6;
        row.append(cell);
        tableBody.append(row);
        return;
      }
      items.forEach((item) => {
        const row = element("tr");
        row.append(element("td", "", item.id));
        row.append(element("td", "", item.title || "--"));
        const statusCell = element("td");
        statusCell.append(element("span", `status-badge ${item.status === "offline" ? "offline" : ""}`, item.status === "offline" ? "已下线" : "在线"));
        row.append(statusCell);
        row.append(element("td", "", Number(item.train_interactions || 0).toLocaleString()));
        row.append(element("td", "", `${Number(item.likes || 0).toLocaleString()} / ${Number(item.views || 0).toLocaleString()}`));
        const actionCell = element("td");
        const actions = element("div", "table-actions");
        const force = element("button", "table-action", "强推");
        force.type = "button";
        force.addEventListener("click", () => openOperation("force", item.id));
        actions.append(force);
        const type = item.status === "offline" ? "restore" : "offline";
        const statusAction = element("button", `table-action ${type === "offline" ? "table-action-danger" : ""}`, type === "offline" ? "下线" : "恢复");
        statusAction.type = "button";
        statusAction.addEventListener("click", () => openOperation(type, item.id));
        actions.append(statusAction);
        actionCell.append(actions);
        row.append(actionCell);
        tableBody.append(row);
      });
    } catch (error) {
      const errorBox = select("#contents-error");
      errorBox.textContent = error.message || "内容列表读取失败";
      errorBox.hidden = false;
      tableBody.replaceChildren();
    }
  }

  selectAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => dialog.close()));
  select("#content-search-form").addEventListener("submit", (event) => { event.preventDefault(); loadContents(); });
  select("#content-status").addEventListener("change", loadContents);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const type = values.get("operation_type");
    const toIso = (value) => value ? new Date(value).toISOString() : null;
    const payload = {
      item_id: Number(values.get("item_id")),
      scope: type === "force" ? values.get("scope") : "all",
      scope_value: type === "force" && values.get("scope_value") ? values.get("scope_value") : null,
      feed_type: type === "force" && values.get("feed_type") ? values.get("feed_type") : null,
      reason: values.get("reason"),
      starts_at: type === "force" ? toIso(values.get("starts_at")) : null,
      ends_at: type === "force" ? toIso(values.get("ends_at")) : null,
    };
    const errorBox = select("#operation-error");
    errorBox.hidden = true;
    try {
      await api(`/api/admin/operations/${type}`, { method: "POST", body: JSON.stringify(payload) });
      dialog.close();
      toast("运营操作已执行并写入审计记录");
      loadContents();
    } catch (error) {
      errorBox.textContent = error.message || "操作失败";
      errorBox.hidden = false;
    }
  });
  loadContents();
}

document.addEventListener("DOMContentLoaded", async () => {
  const page = document.body.dataset.page;
  if (page === "login") {
    setupLogin();
    return;
  }
  bindLogout();
  const user = await loadIdentity();
  if (!user) return;
  if (page === "feed") setupFeed();
  if (page === "profile") setupProfile();
  if (page === "dashboard") setupDashboard();
  if (page === "contents") setupContents();
});
