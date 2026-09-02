import { mkdir } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const baseUrl = (process.env.BASE_URL || "http://127.0.0.1:8001").replace(/\/$/, "");
const password = process.env.DEMO_PASSWORD || "DemoPass123!";
const itemId = Number(process.env.DEMO_ITEM_ID || 40);
const outputDir = path.resolve(
  process.env.EVIDENCE_DIR || "reports/screenshots/v0.3-final",
);
const playwrightUrl = process.env.PLAYWRIGHT_MODULE_URL || pathToFileURL(path.join(
  process.env.USERPROFILE || "",
  ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs",
)).href;
const { chromium } = await import(playwrightUrl);

await mkdir(outputDir, { recursive: true });

const chrome = await chromium.launch({
  executablePath: process.env.CHROME_PATH || path.join(
    process.env.PROGRAMFILES || "C:/Program Files",
    "Google/Chrome/Application/chrome.exe",
  ),
  headless: true,
});

const contexts = [];
const browserErrors = [];
let adminContext;
let aliceContext;
let bobContext;
let initialRuntime = null;
let initialItem = null;

const pause = (page, milliseconds = 500) => page.waitForTimeout(milliseconds);

async function createContext(viewport = { width: 1280, height: 720 }) {
  const context = await chrome.newContext({ viewport });
  context.on("page", (page) => {
    page.on("console", (message) => {
      if (["error", "warning"].includes(message.type())) {
        const location = message.location();
        browserErrors.push(
          `console.${message.type()}: ${message.text()} @ ${location.url || "unknown"}`,
        );
      }
    });
    page.on("pageerror", (error) => browserErrors.push(`pageerror: ${error.message}`));
  });
  contexts.push(context);
  return context;
}

async function login(context, username) {
  const page = await context.newPage();
  await loginPage(page, username);
  return page;
}

async function loginPage(page, username) {
  await page.goto(`${baseUrl}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("用户名").fill(username);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(username === "admin" ? "**/admin/dashboard" : "**/feed");
}

async function openAudit(page) {
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

async function json(context, route, options = {}) {
  const response = await context.request.fetch(`${baseUrl}${route}`, options);
  if (!response.ok()) {
    throw new Error(`${options.method || "GET"} ${route} failed: ${response.status()} ${await response.text()}`);
  }
  if (response.status() === 204) return null;
  return response.json();
}

async function screenshot(page, name) {
  await pause(page, 700);
  const viewport = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  if (viewport.scrollWidth > viewport.clientWidth + 1) {
    throw new Error(`${name} has document-level horizontal overflow: ${JSON.stringify(viewport)}`);
  }
  const target = path.join(outputDir, name);
  await page.screenshot({ path: target, fullPage: false });
  console.log(target);
}

async function waitForFeed(page) {
  await page.locator("#feed-grid [data-item-id]").first().waitFor();
  await pause(page, 350);
}

async function feedIds(page, limit = 6) {
  return page.locator("#feed-grid [data-item-id]").evaluateAll(
    (nodes, count) => nodes.slice(0, count).map((node) => Number(node.dataset.itemId)),
    limit,
  );
}

async function openContent(page) {
  await page.goto(`${baseUrl}/admin/contents`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("搜索标题或内容 ID").fill(String(itemId));
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  const row = page.locator("#contents-body tr").filter({
    has: page.locator("td:first-child", { hasText: new RegExp(`^${itemId}$`) }),
  });
  await row.waitFor();
  return row;
}

async function operateFromUi(page, type, reason) {
  const row = await openContent(page);
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
  await pause(page, 500);
}

async function restoreState() {
  if (adminContext && initialItem) {
    await adminContext.request.post(`${baseUrl}/api/auth/login`, {
      data: { username: "admin", password },
    }).catch(() => undefined);
    const currentItems = await json(adminContext, `/api/admin/contents?q=${itemId}`)
      .catch(() => []);
    const current = currentItems.find((item) => item.id === itemId);
    if (current && current.status !== initialItem.status) {
      const type = initialItem.status === "online" ? "restore" : "offline";
      await json(adminContext, `/api/admin/operations/${type}`, {
        method: "POST",
        data: {
          item_id: itemId,
          scope: "all",
          reason: "最终证据脚本异常恢复",
        },
      }).catch((error) => console.error(`content restore failed: ${error.message}`));
    }
  }
  if (adminContext && initialRuntime?.current?.model_version) {
    const runtime = await json(adminContext, "/api/admin/models/runtime").catch(() => null);
    if (runtime?.current?.model_version !== initialRuntime.current.model_version) {
      await json(
        adminContext,
        `/api/admin/models/${encodeURIComponent(initialRuntime.current.model_version)}/publish`,
        { method: "POST" },
      ).catch((error) => console.error(`model restore failed: ${error.message}`));
    }
  }
}

try {
  adminContext = await createContext();
  const adminPage = await login(adminContext, "admin");
  initialRuntime = await json(adminContext, "/api/admin/models/runtime");
  const matchingItems = await json(adminContext, `/api/admin/contents?q=${itemId}`);
  initialItem = matchingItems.find((item) => item.id === itemId);
  if (!initialItem) throw new Error(`Content #${itemId} was not found.`);
  if (initialItem.status !== "online") {
    throw new Error(`Content #${itemId} must be online before capture; current=${initialItem.status}.`);
  }

  aliceContext = await createContext();
  const alicePage = await login(aliceContext, "alice");
  await waitForFeed(alicePage);
  const aliceIds = await feedIds(alicePage);
  await screenshot(alicePage, "alice-personalized-before-feedback-1280x720.png");

  await alicePage.getByRole("button", { name: "打开", exact: true }).first().click();
  await alicePage.getByRole("button", { name: "喜欢", exact: true }).nth(1).click();
  await pause(alicePage, 350);
  await screenshot(alicePage, "alice-personalized-feedback-1280x720.png");

  await alicePage.getByRole("tab", { name: "热门", exact: true }).click();
  await waitForFeed(alicePage);
  await screenshot(alicePage, "alice-popular-1280x720.png");
  await alicePage.getByRole("tab", { name: "探索", exact: true }).click();
  await waitForFeed(alicePage);
  await screenshot(alicePage, "alice-explore-1280x720.png");

  bobContext = await createContext();
  const bobPage = await login(bobContext, "bob");
  await waitForFeed(bobPage);
  const bobIds = await feedIds(bobPage);
  if (JSON.stringify(aliceIds) === JSON.stringify(bobIds)) {
    throw new Error("Alice and Bob personalized Top-6 are identical; personalization evidence is invalid.");
  }
  await screenshot(bobPage, "bob-personalized-1280x720.png");

  await adminPage.goto(`${baseUrl}/admin/dashboard`, { waitUntil: "domcontentloaded" });
  await adminPage.getByRole("region", { name: "业务概览" }).waitFor();
  await screenshot(adminPage, "admin-dashboard-after-feedback-1280x720.png");

  await operateFromUi(adminPage, "force", "v0.3 最终证据强推");
  await bobPage.goto(`${baseUrl}/feed`, { waitUntil: "domcontentloaded" });
  await waitForFeed(bobPage);
  const forcedIds = await feedIds(bobPage, 1);
  if (forcedIds[0] !== itemId) throw new Error(`Forced item #${itemId} is not ranked first.`);
  await screenshot(bobPage, "content-40-forced-first-1280x720.png");

  await operateFromUi(adminPage, "offline", "v0.3 最终证据下线");
  const offlineFeed = await json(bobContext, "/api/feeds/personalized?page=1&page_size=20");
  if (offlineFeed.items.some((item) => item.item_id === itemId)) {
    throw new Error(`Offline item #${itemId} is still present in the Feed API.`);
  }
  await openContent(adminPage);
  await screenshot(adminPage, "content-40-offline-1280x720.png");

  await operateFromUi(adminPage, "restore", "v0.3 最终证据恢复");
  await openContent(adminPage);
  await screenshot(adminPage, "content-40-restored-1280x720.png");
  await openAudit(adminPage);
  await screenshot(adminPage, "content-operations-audit-1280x720.png");

  await loginPage(adminPage, "admin");
  await adminPage.getByRole("region", { name: "模型决策表" }).scrollIntoViewIfNeeded();
  await screenshot(adminPage, "model-decision-1280x720.png");
  await adminPage.getByRole("region", { name: "最近推荐请求" }).scrollIntoViewIfNeeded();
  const requestRow = adminPage.locator(".request-timeline-button").first();
  await requestRow.click();
  await pause(adminPage, 500);
  await screenshot(adminPage, "request-trace-1280x720.png");

  await adminPage.setViewportSize({ width: 390, height: 844 });
  await adminPage.getByRole("region", { name: "在线可靠性" }).scrollIntoViewIfNeeded();
  await screenshot(adminPage, "runtime-health-mobile-390x844.png");
  if (browserErrors.length) {
    throw new Error(`Browser console/page errors: ${browserErrors.join(" | ")}`);
  }
} finally {
  await restoreState();
  await Promise.allSettled(contexts.map((context) => context.close()));
  await chrome.close();
}
