# 测试与验收证据

> 状态口径：本文件区分 `LOCAL PASS`、`REMOTE PASS`、历史证据和 `PENDING`。只有命令已经
> 执行且输出已复核才标为通过；尚未发生的 v0.3 tag/Release 不用计划代替结果。

## v0.3 本地自动化 Gate

2026-09-03 在合并前的 v0.3 最终交付工作树执行；实现与文档准备提交为 `0c33477`：

| 命令 | 当前结果 |
|---|---|
| `$env:OPENBLAS_NUM_THREADS='1'; uv run --python 3.11 python -m pytest` | `LOCAL PASS`：70 tests，退出码 0 |
| `uv run --python 3.11 ruff check .` | `LOCAL PASS`：`All checks passed!` |
| `node --check app/static/app.js` | `LOCAL PASS`：退出码 0 |
| `$env:OPENBLAS_NUM_THREADS='1'; uv run --python 3.11 python -m recsys.cli offline-smoke` | `LOCAL PASS`：合成数据、训练、保存和加载成功 |
| `$env:OPENBLAS_NUM_THREADS='1'; uv run --python 3.11 python -m recsys.cli smoke` | `LOCAL PASS`：`status=ok, scope=offline+online` |
| `git diff --check` | `LOCAL PASS`：最终文档写入后无 whitespace error |

pytest warning 仅为上游 Starlette `TestClient` 弃用提示和 synthetic
fixture 中 implicit 将 COO 转成 CSR 的 `ParameterWarning`；没有项目断言失败。`smoke` 使用
临时目录训练两个严格 artifact，bootstrap 第一个，通过管理员 API 发布第二个，确认新 Feed
切换 `model_version`，再 rollback；随后继续验证登录、曝光/行为、画像、强推和下线权威。
它不读取本机官方数据、现有 artifact、SQLite 或 `.env`。

70 项测试覆盖时序切分与泄漏边界、Random/Popularity/ALS/ItemCF/RRF、标题 TF-IDF
pure-cold 与 quota 选型、checksum/维度、认证和权限、Feed/事件/画像、Dashboard、请求时间线、
P50/P95/fallback、模型 publish/rollback/恢复、运营权威、页面错误态、响应式 UI 和 SQLAdmin。

## v0.3 官方数据、模型与本地运行证据

- `prepare`：50,000 用户、19,220 内容、359,708 次隐式评论交互；按用户内
  `sequence_position` 留最后两条，得到 259,708/50,000/50,000 train/validation/test。
  官方 pairs 没有可信绝对时间，timestamp 只是明确标注的合成序号。
- v0.3 artifact `hybrid-bm25-f64-764b7d14ce34-20260901T173618808761Z` 为
  66,730,787 bytes；包含 `manifest.json` 在内的 11 个声明文件 SHA256 已匹配。
- Validation BM25 overall NDCG@20 `0.03713558`，高于最佳内容候选 Word/q1 的
  `0.03697165`。Word/q1 pure-cold Recall/NDCG@20 为 `0.05450237/0.01240857`，证明标题
  有信号但不证明整体更优，线上仍为 BM25。
- 冻结后 formal Test 只评估 BM25：Recall/NDCG/Coverage@20
  `0.07822/0.03338273/0.98199792`。未入选 TF-IDF Hybrid 没有 formal Test 结果。
- 本地 runtime 顺序 v0.2 -> v0.3 -> v0.2 -> v0.3 已通过 strict publish/rollback；24 条
  Feed trace 的 fallback rate 为 0%，Feed build P50/P95 为 `388.87/599.77 ms`。该延迟不含
  transaction commit 和 HTTP 序列化，是本机阶段性观测，不是端到端 SLA。
- 完整 runtime ZIP 为 77,575,939 bytes，SHA256
  `AE1E2D7FBF6DB8AC859125A8809D529F007276472026B7FB2F8B57010581F3EB`。它含用户历史和
  官方数据衍生结构，只作本地验收，不作为公开 Release 资产。

## v0.3 浏览器证据

真实浏览器使用 1280x720 和 390x844 viewport 验收：页面无 document 级横向溢出，最终
console warning/error 为 0；模型证据、运行状态、P95 warning、请求详情及 feedback timeline
均读取真实 API。第一组 8 张截图覆盖 v0.3 模型与观测区：

- `reports/screenshots/v0.3/dashboard-model-registry-desktop-1280x720.png`
- `reports/screenshots/v0.3/dashboard-model-registry-mobile-390x844.png`
- `reports/screenshots/v0.3/dashboard-model-decision-desktop-1280x720.png`
- `reports/screenshots/v0.3/dashboard-model-decision-mobile-390x844.png`
- `reports/screenshots/v0.3/dashboard-health-warning-desktop-1280x720.png`
- `reports/screenshots/v0.3/dashboard-health-trace-desktop-1280x720.png`
- `reports/screenshots/v0.3/dashboard-request-detail-mobile-390x844.png`
- `reports/screenshots/v0.3/dashboard-request-feedback-mobile-390x844.png`

最终交付另用无扩展的隔离 Chromium 重跑 Alice/Bob、行为、运营和审计闭环，保存 13 张：

- `reports/screenshots/v0.3-final/alice-personalized-before-feedback-1280x720.png`
- `reports/screenshots/v0.3-final/alice-personalized-feedback-1280x720.png`
- `reports/screenshots/v0.3-final/alice-popular-1280x720.png`
- `reports/screenshots/v0.3-final/alice-explore-1280x720.png`
- `reports/screenshots/v0.3-final/bob-personalized-1280x720.png`
- `reports/screenshots/v0.3-final/admin-dashboard-after-feedback-1280x720.png`
- `reports/screenshots/v0.3-final/content-40-forced-first-1280x720.png`
- `reports/screenshots/v0.3-final/content-40-offline-1280x720.png`
- `reports/screenshots/v0.3-final/content-40-restored-1280x720.png`
- `reports/screenshots/v0.3-final/content-operations-audit-1280x720.png`
- `reports/screenshots/v0.3-final/model-decision-1280x720.png`
- `reports/screenshots/v0.3-final/request-trace-1280x720.png`
- `reports/screenshots/v0.3-final/runtime-health-mobile-390x844.png`

脚本断言 Alice/Bob Top-6 不同、#40 强推为首位、下线后 Feed API 不含 #40、恢复后重新在线，
并在异常时恢复内容和模型。无效的带浏览器扩展截图与登录页误截图已移至 Git 忽略的 `tmp/`，
未进入交付目录。

## 视频证据边界

- 历史 v0.1 视频：04:08、1280x720，SHA256
  `254E4EAFE0BAA2F464D20BAAB0E5926C3642006E09785C87538D495452B28CA4`。按 PDF 五项旅程
  重新核对后，它不能证明全部必选项，尤其没有完整展示从下载源码和官方数据开始启动，以及
  训练/评估命令的实际执行与关键输出，不能再写成“覆盖全部必选旅程”。
- 首版 v0.3 视频：291.24 秒、1280x720、13,138,718 bytes，SHA256
  `5FF1D5524FD9655B65DF059ABB3CABDB43DED0DB8A1DCC6A62F34636AD501ECB`。本地文件和五个抽帧
  已核验，但因缺少 Bob、完整启动链路和强推/下线/恢复等旅程而被拒绝，不能作为最终交付。
  替换视频已在远端 CI、公开仓库与 fresh clone 真实完成后重录。
- 最终 v0.3 视频：`04:33.96`、VP8/yuv420p、1280x720、25fps、14,543,758 bytes，SHA256
  `0a963e09f28b8aa340ad592d8198bf40d4e23d1ba1694e1975fff5f7422665ed`。脚本对双用户差异、
  #40 强推首位、下线 API 过滤、恢复和模型 publish/rollback 逐项断言；`blackdetect` 无连续黑帧
  命中，22 个开场到结尾关键帧已人工检查。两段完整候选分别因 `05:09.40` 超过 PDF 上限和
  `04:29.72` 低于内部下限而被拒绝，未作为发布资产。

## v0.3 远端交付状态

| Gate | 状态 | 当前证据/完成条件 |
|---|---|---|
| v0.3 分支与 main 推送 | `REMOTE PASS` | feature/main 均包含 v0.3；视频 Gate commit 为 `06dde32` |
| 当前 v0.3 SHA 的 GitHub Actions | `REMOTE PASS` | run `33657938390`，Ubuntu/Python 3.11，33 秒，全绿 |
| `v0.3.0` tag/Release | `PENDING` | 当前没有该 tag 或 Release；本地文件不等于上传 |
| 公开精简模型证据包 | `LOCAL PASS` | 10,535,942 bytes；3 成员 allowlist、CSR 结构与成员哈希通过，远端回验待发布 |
| v0.3 fresh clone | `REMOTE PASS / final tag 待复验` | 匿名 clone `0c33477`，frozen sync、70 tests、offline+online smoke 全部通过 |
| 仓库可访问性 | `REMOTE PASS` | GitHub visibility=`PUBLIC`；未带凭据的网页请求返回 200 |

公开精简 ZIP 只包含 `bm25_model.npz`、`item_ids.json` 和包内清洗后的
`model_manifest.json`；仓库中的 `model_release_manifest_v0.3.0.json` 另行记录外层 ZIP 哈希，
聚合 evaluation JSON 是独立 Release 资产。明确排除
`serving_user_items`、全部 `user_ids`、`badcases.csv`、`title_tfidf_items`/
`content_config` 以及原始/处理数据。它是模型证据包，不宣称可脱离官方历史直接启动；无数据
可运行验收由 synthetic smoke 完成。

公开前对 20 个历史提交扫描：密钥模式和本机绝对路径命中均为 0，最大 blob 为 269,663 bytes；
历史路径规则只命中两个 `.gitkeep`。v0.1 ALS runtime、v0.2 runtime ZIP 及其 checksum 已从旧
Release 删除，v0.1 视频保留但 Release 标题/正文已标注为历史记录。

## 历史 v0.2 自动化

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

## 历史 v0.2 全量真实链路

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

## 历史 v0.2 浏览器与干净克隆

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

GitHub Actions：feature run
<https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33521269946> 与 main run
<https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33521419830> 均在 Ubuntu
24.04/Python 3.11 上执行 frozen sync、Ruff、30 tests 和 smoke；原始日志确认分别约 38/39 秒
成功且 annotations 为空。

v0.1 历史视频的文件、时长和 SHA256 已验证，但上文复核已明确它不能证明 PDF 全部五项视频
旅程；v0.2 指标、30 项测试、CI 和截图只能作为相应功能证据，不能补成一次完整演示视频。

v0.2 全新 clone：从私有 GitHub 的 `main` 克隆 `714216e` 到新的 `%TEMP%` 目录，未复制当前
工作目录的 `.venv`、数据、artifact 或 SQLite。`uv sync --frozen` 新建环境并安装 61 个锁定
包；`uv run microlens smoke` 返回离线 `status=ok` 和在线 `scope=offline+online`。结束时
`git status` 只有 `main...origin/main`，无未提交文件；`data/raw` 只有版本化 `.gitkeep`。
