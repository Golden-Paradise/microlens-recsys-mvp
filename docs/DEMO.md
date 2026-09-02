# v0.3 最终演示

## 交付状态

v0.3 最终视频在远端 CI、公开仓库和 fresh-clone smoke 全部完成后录制，再作为最终 Release
资产发布。目前不得把待办项写成已完成。

| 证据 | 当前值 |
|---|---|
| 最终视频 | `PENDING` |
| 视频时长、分辨率、编码和大小 | `PENDING` |
| 视频 SHA256 | `PENDING` |
| v0.3 Release URL | `PENDING` |
| GitHub Actions run URL | `PENDING` |
| GitHub Actions conclusion | `PENDING` |
| fresh-clone commit 与 smoke 结果 | `PENDING` |

本地已有一段 `04:51` 的 v0.3 候选视频，但它没有完整覆盖 Bob 个性化差异、内容运营强推/下线/恢复、仓库启动与训练命令，因此已拒绝，不能作为最终 Gate PASS 或发布资产。

v0.1 的 `04:08` 视频仅是历史必选项证据，不代表 v0.3：
<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/download/v0.1.0-als/microlens-recsys-mvp-demo.webm>。
其 SHA256 为 `254E4EAFE0BAA2F464D20BAAB0E5926C3642006E09785C87538D495452B28CA4`。

## 最终单视频分镜

目标时长 `04:30-04:55`，一个视频同时覆盖 PDF 必选旅程和 v0.3 加分项。

| 时间 | 画面与操作 | 需要说清的证据边界 |
|---|---|---|
| 00:00-00:35 | README 的 clone、`uv sync --frozen`、`python -m recsys.cli smoke`、download/prepare/train/serve 命令 | smoke 使用合成数据，不冒充官方全量训练；正式数据不随仓库或 Release 二次分发 |
| 00:35-01:25 | Alice 登录，依次切换个性化/热门/探索，记录点击与喜欢，再看画像 | 三路 Feed、request_id、模型版本、source/score/reason；反馈更新在线画像，不等于重训 ALS/ItemCF |
| 01:25-01:45 | Bob 登录并展示个性化 Feed | 与 Alice 的 Top 列表不同；这是用户差异证据，不宣称线上指标提升 |
| 01:45-02:15 | Admin Dashboard 顶部、趋势和行为后的指标 | 请求/曝光/点击/点赞来自 SQLite；点击、点赞、负反馈都以曝光为共同分母 |
| 02:15-03:10 | 对内容 #40 强推，验证 Feed 首位；下线后验证 Feed/API 不再返回；恢复并打开运营审计 | 下线权威高于强推；操作均真实落库；最终恢复内容在线 |
| 03:10-03:50 | 模型决策表与 pure-cold 消融 | BM25 validation overall NDCG@20 胜出；TF-IDF 改善 pure-cold validation，但 overall 未胜，所以没有强行上线，未入选策略不跑正式 test |
| 03:50-04:25 | 展示 checksum、current/previous，实际 publish 后再 rollback | 路径、manifest、SHA256 和矩阵维度先校验；pointer 原子替换；单请求 snapshot；仅支持单 Uvicorn worker |
| 04:25-04:50 | 请求链路、P50/P95、fallback 告警、正式 test、公开仓库与 CI | 延迟是 Feed 构建延迟，不是完整 HTTP 延迟；告警是 Dashboard 被动告警；离线结果不表述为线上因果收益 |

## 录制门禁

录制前必须同时满足：

1. v0.3 代码与文档已冻结，工作树中不存在未解释的改动。
2. `uv run --python 3.11 ruff check .`、`uv run --python 3.11 python -m pytest` 和
   `uv run --python 3.11 python -m recsys.cli smoke` 本地通过。
3. GitHub Actions 对最终 commit 的 conclusion 为 `success`，并取得真实 run URL。
4. 从 GitHub 新目录 clone 后，`uv sync --frozen --python 3.11` 与 smoke 通过。
5. 内容 #40 在线，current/previous 均可校验，管理员确认脚本可以在异常时恢复状态。

最终录制脚本还有机器门禁。以下变量缺失或不合法时，它会在启动浏览器前退出，不产生视频：

```powershell
$env:FINAL_CI_STATUS = 'success'
$env:FINAL_CI_RUN_URL = 'https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/<run-id>'
$env:FINAL_COMMIT_SHA = '<final-commit-sha>'
$env:FINAL_REPO_URL = 'https://github.com/Golden-Paradise/microlens-recsys-mvp'
$env:DEMO_OUTPUT = '<output-webm-path>'
node tools/record_final_demo_v03.mjs
```

截图证据可在最终 CI 前生成；脚本使用独立浏览器上下文，并在 `finally` 中恢复内容状态和初始模型版本：

```powershell
$env:BASE_URL = 'http://127.0.0.1:8001'
node tools/capture_final_evidence_v03.mjs
```

## 发布后回填

只有真实发生后才把本页顶部的 `PENDING` 替换为：最终视频直链、时长、分辨率、编码、字节数、SHA256、Release URL、Actions run URL/conclusion，以及 fresh-clone commit/smoke 结果。发布前还要抽查开场、双用户、行为闭环、内容下线、模型回滚和结尾指标帧，确认非黑屏、文字可读、无密码、Token、`.env`、本机绝对路径或原始数据泄露。
