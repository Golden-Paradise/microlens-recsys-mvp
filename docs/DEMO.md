# v0.3 最终演示

## 交付状态

v0.3 最终视频已在远端 CI、公开仓库和 fresh-clone smoke 完成后录制，并通过媒体、关键帧、
Release 上传和匿名回下载检查。

| 证据 | 当前值 |
|---|---|
| 最终视频 | <https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/download/v0.3.0/microlens-recsys-v0.3.0-demo.webm> |
| 视频时长、分辨率、编码和大小 | `04:33.96`、1280x720、VP8/yuv420p、25fps、14,543,758 bytes |
| 视频 SHA256 | `0a963e09f28b8aa340ad592d8198bf40d4e23d1ba1694e1975fff5f7422665ed` |
| v0.3 Release URL | <https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.3.0> |
| GitHub Actions run URL | 视频 Gate `33657938390`；tag Gate <https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33659874652> |
| GitHub Actions conclusion | 两个 run 均为 `success`；tag Gate Ubuntu/Python 3.11、30 秒、lint/70 tests/offline+online smoke |
| fresh-clone commit 与 smoke 结果 | `v0.3.0`/`ae24b15`；frozen sync、70 tests、offline smoke、publish/rollback smoke 全部通过 |

早期 `04:51` 候选视频因缺少 Bob、完整启动链路和强推/下线/恢复而被拒绝。公开后又有两段
完整候选分别因 `05:09.40` 超过 PDF 上限、`04:29.72` 低于内部 4:30 下限而被拒绝；只有上表
`04:33.96` 成片进入最终发布目录。

v0.1 的 `04:08` 视频仅是历史必选项证据，不代表 v0.3：
<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/download/v0.1.0-als/microlens-recsys-mvp-demo.webm>。
其 SHA256 为 `254E4EAFE0BAA2F464D20BAAB0E5926C3642006E09785C87538D495452B28CA4`。

## 最终单视频分镜

目标时长 `04:30-04:55`，一个视频同时覆盖 PDF 必选旅程和 v0.3 加分项。

| 时间 | 画面与操作 | 需要说清的证据边界 |
|---|---|---|
| 00:00-00:38 | 复现命令、公开 README、官方数据边界 | smoke 使用合成数据，不冒充官方全量训练；正式数据不随仓库或 Release 二次分发 |
| 00:38-01:16 | Alice 三路 Feed、点击/喜欢和画像 | request_id、模型版本、source/score/reason；反馈更新在线画像，不等于重训 ALS/ItemCF |
| 01:16-01:35 | Bob 个性化 Feed | Top 列表与 Alice 不同；这是用户差异证据，不宣称线上指标提升 |
| 01:35-02:24 | Dashboard、#40 强推首位、下线/API 过滤、恢复和审计 | 指标来自 SQLite；下线权威高于强推；操作真实落库并最终恢复 |
| 02:24-03:12 | 模型决策表、pure-cold 消融和固定 commit 评估报告 | BM25 赢 validation overall；TF-IDF pure-cold 有信号但 overall 未胜，未入选策略不跑正式 test |
| 03:12-03:43 | current/previous、实际 publish 和 rollback | 先校验路径/manifest/SHA256/矩阵；原子 pointer、请求 snapshot、单 worker 边界 |
| 03:43-04:14 | P50/P95、fallback、request_id 链路和真实 CI | Feed 构建延迟不等于 HTTP SLA；告警是被动状态；CI 对应视频中的固定 commit |
| 04:14-04:33 | 冻结后的 formal Test 与交付边界 | 离线结果不表述为线上因果收益，576 个 pure-cold Test target 仍未命中 |

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

## 发布后验证

发布前连续黑帧检测无命中，抽查 22 个关键帧覆盖开场、双用户、行为闭环、内容下线、模型
回滚、请求链路、CI 和结尾指标；文字可读，未显示 Token、`.env`、本机绝对路径或原始数据。
发布后匿名下载的视频仍为 14,543,758 bytes，SHA256 与上表一致，媒体信息仍为 04:33.96、
VP8、1280x720、25fps。
