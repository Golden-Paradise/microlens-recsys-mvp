# 测试与验收证据

## 自动化

2026-09-01 本机执行：

| 命令 | 结果 |
|---|---|
| `uv run pytest` | 23 passed；仅 FastAPI TestClient/httpx2 弃用警告 |
| `uv run ruff check app recsys tests` | passed |
| `uv run microlens offline-smoke` | 合成数据 prepare/train/save/load 成功 |
| `uv run microlens smoke` | `status=ok, scope=offline+online` |

测试覆盖时序无泄漏、指标公式、ALS 保存回载、认证/Session 防篡改、WAL/FK、用户差异、分页去重、曝光事件幂等、画像、Dashboard、请求链路、强推范围/时窗、下线/恢复优先级、fallback、页面错误/空态、响应式模板和 SQLAdmin 只读权限。

## 全量真实链路

- `prepare`：50,000 用户、19,220 内容、359,708 交互；259,708/50,000/50,000 split；本机 5.49 秒。
- `train/load`：`als-f64-764b7d14ce34-20260901T084159422095Z`，六份核心文件 checksum 回验一致。
- 在线 seed：SQLite 内容数 19,220，服务引擎 `ALSRecommendationEngine`。
- Alice 推荐前 8：`14377, 15037, 4072, 13637, 7242, 19112, 12207, 5422`。
- Bob 推荐前 8：`3533, 11754, 11350, 15525, 8796, 14732, 16708, 19557`。
- Carol 点赞 item 2514 后 profile_version=1；下一次前 8 全部进入被点赞的 bucket，证明在线反馈参与排序，不是只改页面。

## 浏览器与干净克隆

浏览器真实操作已完成：Alice/Bob 个性化不同；点赞后画像变化；popular/explore 来源正确；Dashboard 数字、流占比、热门内容和模型表可见；#40 强推后 Alice 首位为 `source=forced`，下线后从 Feed 消失，恢复后在线。桌面 1280x720 与移动 390x844 的 `documentWidth <= viewport`，控件裁切列表为空，console error/warning 均为 0。

截图：

- `reports/screenshots/alice-feed-desktop.png`
- `reports/screenshots/alice-feed-mobile-390x844.png`
- `reports/screenshots/admin-dashboard-desktop.png`
- `reports/screenshots/admin-dashboard-mobile-390x844.png`

视频：04:08、1280x720，抽查 10 个时间点，SHA256 为 `254E4EAFE0BAA2F464D20BAAB0E5926C3642006E09785C87538D495452B28CA4`。

全新 clone smoke 尚待最终 G4 commit 推送后执行，完成前不会在验收矩阵标为 PASS。
