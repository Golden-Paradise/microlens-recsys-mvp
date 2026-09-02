import { access, mkdir, mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const ciStatus = process.env.FINAL_CI_STATUS;
const ciRunUrl = process.env.FINAL_CI_RUN_URL || "";
const finalCommit = process.env.FINAL_COMMIT_SHA || "";
const repoUrl = (process.env.FINAL_REPO_URL || "").replace(/\/$/, "");
const output = process.env.DEMO_OUTPUT;
const validRunUrl = /^https:\/\/github\.com\/Golden-Paradise\/microlens-recsys-mvp\/actions\/runs\/\d+(?:\/job\/\d+)?$/.test(ciRunUrl);
if (ciStatus !== "success") throw new Error("FINAL_CI_STATUS must equal success.");
if (!validRunUrl) throw new Error("FINAL_CI_RUN_URL must be a real repository Actions run URL.");
if (!/^[0-9a-f]{7,40}$/i.test(finalCommit)) throw new Error("FINAL_COMMIT_SHA must be a 7-40 character Git SHA.");
if (repoUrl !== "https://github.com/Golden-Paradise/microlens-recsys-mvp") {
  throw new Error("FINAL_REPO_URL must be the public MicroLens repository URL.");
}
if (!output) throw new Error("DEMO_OUTPUT is required.");
try {
  await access(output);
  if (process.env.OVERWRITE_DEMO !== "1") {
    throw new Error("DEMO_OUTPUT already exists; set OVERWRITE_DEMO=1 to replace it.");
  }
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

const baseUrl = (process.env.BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "");
const password = process.env.DEMO_PASSWORD || "DemoPass123!";
const itemId = Number(process.env.DEMO_ITEM_ID || 40);
const playwrightUrl = process.env.PLAYWRIGHT_MODULE_URL || pathToFileURL(path.join(
  process.env.USERPROFILE || "",
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs",
)).href;
const { chromium } = await import(playwrightUrl);

await mkdir(path.dirname(path.resolve(output)), { recursive: true });
const tempRoot = path.resolve(os.tmpdir());
const recordDir = await mkdtemp(path.join(tempRoot, "microlens-final-demo-"));
const chrome = await chromium.launch({
  executablePath: process.env.CHROME_PATH || path.join(
    process.env.PROGRAMFILES || "C:/Program Files",
    "Google/Chrome/Application/chrome.exe",
  ),
  headless: true,
});
const context = await chrome.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: recordDir, size: { width: 1280, height: 720 } },
});
const page = await context.newPage();
const video = page.video();
let initialRuntime = null;
let initialItem = null;
let completed = false;

const wait = (milliseconds) => page.waitForTimeout(milliseconds);

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[character]);
}

async function api(route, options = {}) {
  const response = await context.request.fetch(`${baseUrl}${route}`, options);
  if (!response.ok()) {
    throw new Error(`${options.method || "GET"} ${route} failed: ${response.status()} ${await response.text()}`);
  }
  if (response.status() === 204) return null;
  return response.json();
}

async function showSlide(title, lines, milliseconds) {
  await page.setContent(`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>
    *{box-sizing:border-box}body{margin:0;background:#f3f6f4;color:#18231f;font-family:"Microsoft YaHei",Arial,sans-serif}
    main{height:720px;padding:64px 88px;display:flex;flex-direction:column;justify-content:center}.brand{color:#176b58;font-size:18px;font-weight:800;margin-bottom:20px}
    h1{font-size:42px;line-height:1.2;margin:0 0 24px}p{font-size:21px;line-height:1.55;margin:5px 0}code{font-family:Consolas,monospace;background:#fff;border:1px solid #d8e0dd;padding:3px 7px;border-radius:4px}
    strong{color:#176b58}footer{position:absolute;bottom:28px;color:#66736e;font-size:15px}
  </style></head><body><main><div class="brand">MICROLENS RECSYS MVP · v0.3</div><h1>${title}</h1>${lines.map((line) => `<p>${line}</p>`).join("")}<footer>Golden-Paradise/microlens-recsys-mvp · ${escapeHtml(finalCommit.slice(0, 12))}</footer></main></body></html>`);
  await wait(milliseconds);
}

async function openPublicEvidence(url, requiredPhrases) {
  const response = await page.goto(url, { waitUntil: "domcontentloaded" });
  if (!response?.ok()) throw new Error(`Public evidence failed to load: ${url}`);
  const body = await page.locator("body").innerText();
  for (const phrase of requiredPhrases) {
    if (!body.includes(phrase)) throw new Error(`Public evidence is missing ${phrase}: ${url}`);
  }
}

async function caption(text, milliseconds) {
  await page.evaluate((value) => {
    document.querySelector("#demo-caption")?.remove();
    const node = document.createElement("div");
    node.id = "demo-caption";
    node.textContent = value;
    Object.assign(node.style, {
      position: "fixed", left: "24px", right: "24px", bottom: "20px", zIndex: "99999",
      padding: "14px 18px", borderRadius: "6px", background: "rgba(15,31,26,.94)",
      color: "white", font: "600 19px Microsoft YaHei, sans-serif", boxShadow: "0 8px 30px rgba(0,0,0,.24)",
    });
    document.body.append(node);
  }, text);
  await wait(milliseconds);
  await page.evaluate(() => document.querySelector("#demo-caption")?.remove());
}

async function login(username) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(username === "admin" ? "**/admin/dashboard" : "**/feed");
  await page.locator(username === "admin" ? "#overview-metrics" : "#feed-grid [data-item-id]").first().waitFor();
}

async function openAudit() {
  await page.goto(`${baseUrl}/db-admin/operation/list`, { waitUntil: "domcontentloaded" });
  if (page.url().includes("/db-admin/login")) {
    await page.locator('input[name="username"]').fill("admin");
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole("button", { name: "Login", exact: true }).click();
    await page.waitForURL("**/db-admin/**");
    await page.goto(`${baseUrl}/db-admin/operation/list`, { waitUntil: "networkidle" });
  }
  await page.getByText("运营审计", { exact: true }).first().waitFor();
}

async function logout() {
  await page.getByRole("button", { name: "退出登录" }).click();
  await page.waitForURL("**/login");
}

async function feedIds(limit = 6) {
  return page.locator("#feed-grid [data-item-id]").evaluateAll(
    (nodes, count) => nodes.slice(0, count).map((node) => Number(node.dataset.itemId)),
    limit,
  );
}

async function contentRow() {
  await page.goto(`${baseUrl}/admin/contents`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("搜索标题或内容 ID").fill(String(itemId));
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  const row = page.locator("#contents-body tr").filter({
    has: page.locator("td:first-child", { hasText: new RegExp(`^${itemId}$`) }),
  });
  await row.waitFor();
  return row;
}

async function operate(type, reason) {
  const row = await contentRow();
  const label = { force: "强推", offline: "下线", restore: "恢复" }[type];
  await row.getByRole("button", { name: label, exact: true }).click();
  await page.getByLabel("操作原因").fill(reason);
  if (type === "force") {
    await page.getByLabel("强推范围").selectOption("all");
    await page.getByLabel("信息流").selectOption("personalized");
    const expiresAt = new Date(Date.now() + 10 * 60 * 1000);
    const expires = new Date(expiresAt.getTime() - expiresAt.getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 16);
    await page.getByLabel("失效时间").fill(expires);
  }
  await page.getByRole("button", { name: "确认执行", exact: true }).click();
  await page.locator("#operation-dialog").waitFor({ state: "hidden" });
}

async function ensureInitialState() {
  await context.request.post(`${baseUrl}/api/auth/login`, {
    data: { username: "admin", password },
  }).catch(() => undefined);
  if (initialItem) {
    const items = await api(`/api/admin/contents?q=${itemId}`).catch(() => []);
    const item = items.find((entry) => entry.id === itemId);
    if (item && item.status !== initialItem.status) {
      await api(`/api/admin/operations/${initialItem.status === "online" ? "restore" : "offline"}`, {
        method: "POST",
        data: { item_id: itemId, scope: "all", reason: "最终视频异常恢复" },
      }).catch(() => undefined);
    }
  }
  if (initialRuntime?.current?.model_version) {
    const runtime = await api("/api/admin/models/runtime").catch(() => null);
    if (runtime?.current?.model_version !== initialRuntime.current.model_version) {
      await api(`/api/admin/models/${encodeURIComponent(initialRuntime.current.model_version)}/publish`, {
        method: "POST",
      }).catch(() => undefined);
    }
  }
}

try {
  const health = await context.request.get(`${baseUrl}/api/health`);
  if (!health.ok()) throw new Error(`Health check failed: ${health.status()}`);

  await showSlide("从可运行 MVP 到可解释、可回滚的推荐系统", [
    "三路 Feed 与行为闭环 · 内容运营与审计 · 时间趋势 Dashboard",
    "ALS / ItemCF / RRF / 标题 TF-IDF：<strong>validation 负责选型，formal test 只验证冻结策略</strong>",
    "checksum 校验 · 原子 pointer · 请求级 snapshot · last-known-good 回滚",
  ], 13000);
  await showSlide("干净环境与复现入口", [
    "<code>git clone ... && uv sync --frozen --python 3.11</code>",
    "<code>uv run --python 3.11 python -m recsys.cli smoke</code>：合成 offline + online 闭环",
    "官方全量链路：<code>python -m recsys.cli download → prepare → train --activate</code>",
    "原始数据、SQLite、密钥与题目 PDF 不进入 Git 或公开 Release",
  ], 20000);
  await openPublicEvidence(repoUrl, ["MicroLens", "uv sync --frozen", "python -m recsys.cli smoke"]);
  await caption("这里是真实公开仓库 README，而不是自制命令页：clone、frozen sync、synthetic smoke 和官方数据链路都可以由评审者直接复现。", 14000);

  await login("alice");
  const aliceIds = await feedIds();
  await caption("Alice 个性化 Feed：响应展示模型版本和 request_id；每条结果保留 source、score、reason，便于追踪一次推荐是怎么来的。", 10000);
  await page.getByRole("tab", { name: "热门", exact: true }).click();
  await page.locator("#feed-grid [data-item-id]").first().waitFor();
  await caption("热门 Feed 使用稳定流行度信号，是未知用户和模型不可用时的可解释回退，不冒充个性化模型。", 7000);
  await page.getByRole("tab", { name: "探索", exact: true }).click();
  await page.locator("#feed-grid [data-item-id]").first().waitFor();
  await caption("探索 Feed 从非热门候选中稳定取样，和个性化、热门是三条独立入口。", 7000);
  await page.getByRole("tab", { name: "个性化", exact: true }).click();
  await page.locator("#feed-grid [data-item-id]").first().waitFor();
  await page.getByRole("button", { name: "打开", exact: true }).first().click();
  await page.getByRole("button", { name: "喜欢", exact: true }).nth(1).click();
  await page.getByRole("link", { name: "我的画像", exact: true }).click();
  await caption("点击与喜欢必须引用 Alice 自己的曝光；画像版本实时增加并参与后续有界重排，但这不是在线重训 ALS 或 ItemCF。", 11000);

  await logout();
  await login("bob");
  const bobIds = await feedIds();
  if (JSON.stringify(aliceIds) === JSON.stringify(bobIds)) {
    throw new Error("Alice and Bob personalized Top-6 are identical.");
  }
  await caption("Bob 的个性化 Top 列表与 Alice 不同，证明用户历史与会话隔离生效；这里只陈述行为差异，不把它包装成线上收益。", 10000);

  await logout();
  await login("admin");
  initialRuntime = await api("/api/admin/models/runtime");
  const matches = await api(`/api/admin/contents?q=${itemId}`);
  initialItem = matches.find((item) => item.id === itemId);
  if (!initialItem || initialItem.status !== "online") {
    throw new Error(`Content #${itemId} must be online before recording.`);
  }
  await caption("Dashboard 的请求、曝光、点击、点赞和趋势来自当前 SQLite。点击、点赞、负反馈共享曝光分母，因此没有绘制错误的严格漏斗。", 12000);

  await operate("force", "v0.3 最终视频强推");
  await logout();
  await login("bob");
  const forced = await feedIds(1);
  if (forced[0] !== itemId) throw new Error(`Forced item #${itemId} is not first.`);
  await caption("管理员把 #40 强推到个性化 Feed 后，它真实出现在 Bob 首位，source 为 forced，原因来自运营操作。", 10000);

  await logout();
  await login("admin");
  await operate("offline", "v0.3 最终视频下线");
  await logout();
  await login("bob");
  const afterOffline = await api("/api/feeds/personalized?page=1&page_size=20");
  if (afterOffline.items.some((item) => item.item_id === itemId)) {
    throw new Error(`Offline item #${itemId} is still returned.`);
  }
  await caption("下线优先级高于强推：刷新 Feed 与 API 都不再返回 #40。脚本在结束或异常时都会恢复内容状态。", 10000);

  await logout();
  await login("admin");
  await operate("restore", "v0.3 最终视频恢复");
  await openAudit();
  await caption("恢复后 #40 重新在线；强推、下线、恢复三次操作都写入只读审计，保留操作人、原因、前后状态与时间。", 11000);

  await login("admin");
  await page.getByRole("region", { name: "模型决策表" }).scrollIntoViewIfNeeded();
  await caption("选型只看 validation overall NDCG@20：BM25 为 0.03714，Word/q1 为 0.03697。TF-IDF 虽把 pure-cold Recall@20 提到 0.05450，但 overall 未胜，所以没有上线。", 18000);
  await caption("char_wb/q5 的 pure-cold Recall@20 达到 0.09242，但进一步牺牲 warm 与 overall。未入选策略的 Test 明确显示“未正式测试”，防止 test 泄漏进选型。", 14000);
  await openPublicEvidence(`${repoUrl}/blob/${finalCommit}/reports/EVALUATION.md`, [
    "Validation", "Formal Test", "0.037", "0.033",
  ]);
  await caption("仓库中固定 commit 的 EVALUATION 报告保留 validation 选型表和冻结后的 formal-test 表，区分 overall、warm、pure-cold 与未正式测试策略。", 14000);
  await page.goto(`${baseUrl}/admin/dashboard`, { waitUntil: "domcontentloaded" });
  await page.locator("#model-runtime").waitFor();

  await page.getByRole("region", { name: "模型运行与发布" }).scrollIntoViewIfNeeded();
  const previous = initialRuntime.previous?.model_version;
  if (!previous) throw new Error("A previous model is required for publish/rollback evidence.");
  await page.getByLabel("候选模型").selectOption(previous);
  await caption("发布前校验版本目录、manifest/version、全部 SHA256、稀疏矩阵维度和 item 映射；加载与 warm-up 在状态锁外完成。", 10000);
  const published = await api(`/api/admin/models/${encodeURIComponent(previous)}/publish`, { method: "POST" });
  if (published.current?.model_version !== previous) throw new Error("Publish did not switch current.");
  await page.reload();
  await page.getByRole("region", { name: "模型运行与发布" }).scrollIntoViewIfNeeded();
  await caption("pointer 先 flush、fsync、os.replace，再用短锁切换 engine。已开始请求继续使用旧 snapshot，新请求读取新版本。", 10000);
  const rolledBack = await api("/api/admin/models/rollback", { method: "POST" });
  if (rolledBack.current?.model_version !== initialRuntime.current.model_version) {
    throw new Error("Rollback did not restore the initial current model.");
  }
  await page.reload();
  await page.getByRole("region", { name: "模型运行与发布" }).scrollIntoViewIfNeeded();
  await caption("rollback 重新校验 previous 后交换 current/previous；失败继续服务 last-known-good。当前实现明确只支持单 Uvicorn worker。", 10000);

  await page.getByRole("region", { name: "在线可靠性" }).scrollIntoViewIfNeeded();
  await caption("P50/P95 是 Feed 构建延迟，不是完整 HTTP 延迟；至少 20 个样本后，fallback≥5% 或 P95≥500ms 才显示 Dashboard 被动告警。", 12000);
  await page.getByRole("region", { name: "最近推荐请求" }).scrollIntoViewIfNeeded();
  await page.locator(".request-timeline-button").first().click();
  await caption("点击最近请求可沿 request_id 回查曝光顺序、模型版本、source/score/reason，以及后续点击、喜欢和负反馈事件。", 12000);

  await openPublicEvidence(ciRunUrl, ["Actions", "CI"]);
  await caption("这里是真实最终 commit 对应的 GitHub Actions run；只有 conclusion 为 success，录制门禁才允许走到本画面。", 12000);

  await showSlide("v0.3 冻结结论与交付边界", [
    "Formal Test BM25：Recall@20 <strong>0.07822</strong> · NDCG@20 <strong>0.03338</strong> · Coverage@20 <strong>0.98200</strong>",
    "576 个 pure-cold Test target 仍未被正式策略命中；TF-IDF 是 validation 正信号、overall 负实验",
    `<strong>GitHub Actions: success</strong> · <code>${escapeHtml(ciRunUrl.replace("https://github.com/Golden-Paradise/microlens-recsys-mvp/", ""))}</code>`,
    "边界：本地单 worker + SQLite Demo + 被动告警；不宣称线上因果收益或通用 SLA",
  ], 22000);
  completed = true;
} finally {
  await ensureInitialState();
  await page.close().catch(() => undefined);
  await context.close().catch(() => undefined);
  if (completed && video) await video.saveAs(path.resolve(output));
  await chrome.close().catch(() => undefined);
  const safeRecordDir = path.dirname(path.resolve(recordDir)) === tempRoot
    && path.basename(recordDir).startsWith("microlens-final-demo-");
  if (safeRecordDir) {
    await rm(recordDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

if (completed) console.log(path.resolve(output));
