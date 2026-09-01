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

function setupDashboard() {
  const overview = select("#overview-metrics");
  if (!overview) return;
  async function loadDashboard() {
    const errorBox = select("#dashboard-error");
    errorBox.hidden = true;
    try {
      const [summary, diagnostics, models] = await Promise.all([
        api("/api/admin/dashboard"),
        api("/api/admin/feeds/diagnostics"),
        api("/api/admin/models"),
      ]);
      appendMetrics(overview, [
        ["用户数", summary.users], ["活跃用户", summary.active_users],
        ["推荐请求", summary.requests], ["曝光数", summary.exposures],
        ["点击数", summary.clicks], ["CTR", `${(Number(summary.ctr || 0) * 100).toFixed(2)}%`],
        ["点赞数", summary.likes], ["下线内容", summary.offline_items],
        ["当前模型", summary.current_model_version, true],
      ]);
      renderRecord(select("#feed-diagnostics"), diagnostics.items || diagnostics);
      renderRecord(select("#feed-shares"), summary.feed_shares || {});
      renderRecord(select("#hot-items"), summary.hot_items || []);
      renderRecord(select("#model-list"), models.items || models);
    } catch (error) {
      errorBox.textContent = error.message || "看板数据读取失败";
      errorBox.hidden = false;
    }
  }
  select("#refresh-dashboard").addEventListener("click", loadDashboard);
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
    const target = select("#request-trace-result");
    const requestId = new FormData(event.currentTarget).get("request_id");
    target.textContent = "正在查询…";
    try {
      const result = await api(`/api/admin/requests/${encodeURIComponent(requestId)}`);
      renderRecord(target, result);
    } catch (error) {
      target.textContent = error.message || "请求链路读取失败";
    }
  });
  loadDashboard();
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
