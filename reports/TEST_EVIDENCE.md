# 测试与验收证据

## 自动化

2026-09-01 本机执行：

| 命令 | 结果 |
|---|---|
| `uv run pytest` | 30 passed；仅上游 implicit 转换与 FastAPI TestClient 弃用警告 |
| `uv run ruff check .` | passed |
| `uv run microlens offline-smoke` | 合成数据 prepare/train/save/load 成功 |
| `uv run microlens smoke` | `status=ok, scope=offline+online` |

测试覆盖时序无泄漏、指标公式、ALS/ItemCF/RRF、旧 manifest 兼容、保存回载、认证/Session
防篡改、WAL/FK、用户差异、分页去重、曝光事件幂等、画像、Dashboard 时间窗口/补零趋势、
请求链路、强推范围/时窗、下线/恢复优先级、fallback、页面错误/空态、响应式模板和 SQLAdmin。

## 全量真实链路

- `prepare`：50,000 用户、19,220 内容、359,708 交互；259,708/50,000/50,000 split；本机 5.49 秒。
- `train/load`：`hybrid-bm25-f64-764b7d14ce34-20260901T134041223913Z`，八份核心
  文件 checksum 回验一致，旧 v0.1 ALS manifest 仍可加载。
- 正式 test：BM25 Recall/NDCG/Coverage@20=`0.07822/0.033383/0.981998`；ALS 对照
  `0.06154/0.023592/0.212019`。
- 在线 seed：SQLite 内容数 19,220，manifest serving policy 为 `bm25`，Feed 来源为
  `itemcf_bm25`。
- Alice 推荐前 8：`14377, 15037, 4072, 13637, 7242, 19112, 12207, 5422`。
- Bob 推荐前 8：`3533, 11754, 11350, 15525, 8796, 14732, 16708, 19557`。
- Carol 点赞 item 2514 后 profile_version=1；下一次前 8 全部进入被点赞的 bucket，证明在线反馈参与排序，不是只改页面。

## 浏览器与干净克隆

浏览器真实操作已完成：Alice/Bob 个性化不同；点赞后画像变化；popular/explore 来源正确；
Dashboard 数字、流占比、热门内容和模型表可见；6h 窗口的 overview/diagnostics/trends 同步
刷新，SVG 返回 12 个非空点；#40 强推、下线、恢复闭环保持。桌面 1280x720 与移动
390x844 目标 viewport 均无横向溢出，console error/warning 为 0；页面有效截图受浏览器 chrome
与滚动条影响分别为 1265x712 和 375x812 像素。浏览器还发现并修复了管理员被计入
active_users 的口径问题。

截图：

- `reports/screenshots/alice-feed-desktop.png`
- `reports/screenshots/alice-feed-mobile-390x844.png`
- `reports/screenshots/admin-dashboard-desktop.png`
- `reports/screenshots/admin-dashboard-mobile-390x844.png`
- `reports/screenshots/v0.2/admin-dashboard-chart-6h-1280x720.png`
- `reports/screenshots/v0.2/admin-dashboard-chart-6h-390x844.png`

GitHub Actions：最终 run
<https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33517793682> 在 Ubuntu
24.04/Python 3.11 上执行 frozen sync、Ruff、29 tests、smoke，33 秒成功且 annotations 为空。
发布前 UTC 契约测试把本地 suite 增至 30；对应远端 run 在 feature commit 推送后补记。

v0.1 必选项视频：04:08、1280x720，抽查 10 个时间点，SHA256 为
`254E4EAFE0BAA2F464D20BAAB0E5926C3642006E09785C87538D495452B28CA4`。它只证明 PDF
必选旅程；v0.2 加分能力由正式指标、30 项本地测试、远端 CI 与四张响应式截图证明，本轮不重录。

v0.1 基线曾从私有 GitHub 的 `4d070a6` 完成全新 clone smoke。v0.2 将在 feature
分支合入 `main` 后另建临时目录重跑；在该命令实际完成前，不沿用 v0.1 结果冒充 v0.2
干净环境证据。
