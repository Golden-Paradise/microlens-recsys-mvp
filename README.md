# MicroLens Recsys MVP

基于官方 MicroLens-50K 的 CPU-first 推荐系统闭环：时序数据处理 -> ALS/ItemCF/RRF/标题
TF-IDF validation 选型 -> 多用户 Feed 与反馈 -> 时间趋势 Dashboard -> checksum 校验、原子发布与
回滚 -> 请求链路和运行告警。

- 公开仓库：<https://github.com/Golden-Paradise/microlens-recsys-mvp>
- v0.3 Release（tag 后发布）：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.3.0>
- 最终视频：04:33.96、1280x720、VP8；Release 上传后提供直链
- v0.2 Release：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.2.0>
- v0.1 历史视频 Release：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.1.0-als>
- 本地 Demo：<http://127.0.0.1:8000/login>
- OpenAPI：<http://127.0.0.1:8000/docs>

## 1. 最快验收：无数据 smoke

前置：Git、[uv](https://docs.astral.sh/uv/)，Python 3.11-3.13。Windows PowerShell：

```powershell
git clone https://github.com/Golden-Paradise/microlens-recsys-mvp.git
Set-Location microlens-recsys-mvp
uv sync --frozen --python 3.11
$env:OPENBLAS_NUM_THREADS='1'
uv run --python 3.11 python -m recsys.cli smoke
```

`smoke` 在临时目录生成 4 用户/6 内容数据并训练两个微型严格校验 artifact：bootstrap 第一个，
通过管理员 API 发布第二个，验证新 Feed 的 `model_version` 已切换，再 rollback 恢复第一个；之后
继续验证登录、曝光、点赞、画像、强推和下线权威。它不读取当前数据库、官方数据或已有模型。

## 2. v0.3 公开模型证据包

MicroLens 官方禁止修改数据后的二次下载。因此公开 Release 只提供选中的 BM25 模型权重、
item 索引、模型清单和聚合评估，不包含用户交互矩阵、用户 ID、逐用户 Badcase、标题向量或
任何原始/处理数据：

```powershell
gh release download v0.3.0 --pattern "microlens-bm25-model-v0.3.0.zip" --dir tmp/release
Expand-Archive tmp/release/microlens-bm25-model-v0.3.0.zip tmp/release/model -Force
```

这个压缩包是可核验的模型产物，不是脱离官方用户历史即可启动的 runtime。无数据的完整功能
验收使用上一节的 synthetic smoke；基于官方 50K 数据的线上模型按下一节在本地重建。

## 3. 从官方数据完整复现

只下载官方三份文本数据，不下载或上传 637 MiB 封面包：

```powershell
uv run --python 3.11 python -m recsys.cli download
uv run --python 3.11 python -m recsys.cli prepare
$env:OPENBLAS_NUM_THREADS='1'
uv run --python 3.11 python -m recsys.cli train --activate
Copy-Item .env.example .env
uv run --python 3.11 python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

数据来源：<https://github.com/westlake-repl/MicroLens>。`prepare` 逐用户留最后两条为
validation/test，输出 split CSV/CSR、`items.csv`、历史、映射和摘要。官方 pairs 只有
`sequence_position`，没有可信绝对时间；timestamp 仅为明确标注的合成序号。

`train` 在 validation 比较 ALS-32/64、Cosine/BM25 ItemCF、固定 RRF，以及标题 Word
`(1,2)` / `char_wb (3,5)` 与 cold quota `1/2/3/5`。主指标固定为 overall NDCG@20；冻结后
用 train+validation 重训，formal test 只运行一次。这里使用 `--activate` 完成首次 bootstrap；
日常训练默认只创建 candidate，不改 `latest.json`，再由 Dashboard 管理 API 严格校验后发布。

本机正式 v0.3 训练耗时 10 分 23 秒，产出 66,730,787-byte artifact。标题 TF-IDF 改善
pure-cold validation，但未赢 overall NDCG，因此正式服务仍是 BM25，不能写成“内容召回已上线”。

## 4. 账号与演示路径

默认密码均为 `DemoPass123!`，只用于本地 Demo，可通过 `APP_DEMO_PASSWORD` 修改。

| 账号 | 角色 | 官方用户映射 |
|---|---|---:|
| `alice` | 普通用户 | 10001 |
| `bob` | 普通用户 | 10002 |
| `carol` | 普通用户 | 10003 |
| `admin` | 管理员 | 无 |

1. Alice/Bob 登录 `/login`，切换个性化、热门、探索；个性化来源为 `itemcf_bm25`。
2. 点击、喜欢、不感兴趣后查看 `/profile`；反馈与曝光由同一 `request_id` 关联并进入有界重排。
3. Admin 在 `/admin/dashboard` 查看 validation/test 模型决策表、current/previous、P50/P95、
   fallback 告警和最近请求；点击请求可查看曝光顺序与事件时间线。
4. 在模型运行区选择 candidate 发布并回滚。失败返回 404/409，last-known-good 不变。
5. 在 `/admin/contents` 搜索、强推、下线和恢复；下线优先于任何强推和直接内容 API。
6. `/db-admin/` 是独立管理员认证的只读数据库审计页。

## 5. 指标与质量门禁

```powershell
uv run --python 3.11 python -m pytest
uv run --python 3.11 ruff check .
node --check app/static/app.js
uv run --python 3.11 python -m recsys.cli offline-smoke
uv run --python 3.11 python -m recsys.cli smoke
```

本地最终结果为 70 tests passed、Ruff/Node/diff check/smoke passed。官方 formal Test 只报告冻结
BM25：Recall@20=`0.07822`、NDCG@20=`0.03338273`、Coverage@20=`0.98199792`。
Validation 有 844 个 pure-cold target，Test 有 576 个；Word/q1 pure-cold Recall/NDCG@20
达到 `0.05450/0.01241`，但 overall NDCG=`0.03697` 低于 BM25 的 `0.03714`，故不上线。

CI 在 Ubuntu/Python 3.11 执行 frozen sync、Ruff、pytest 和包含真实 publish/rollback 的 synthetic
smoke。最终视频对应的 main run `33657938390` 在 33 秒内全绿：
<https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33657938390>。公开仓库的匿名
fresh clone 已在新系统临时目录对实现提交 `0c33477` 完成 frozen sync、70 tests、offline smoke
和 online publish/rollback smoke；最终 tag 仍会再做一次独立复验。

## 6. 环境变量

| 变量 | 用途 |
|---|---|
| `APP_SECRET_KEY` | Session 签名密钥，部署时必须替换 |
| `APP_DATABASE_URL` | SQLite URL，默认 `sqlite:///var/app.db` |
| `APP_PROCESSED_DIR` | 处理数据根目录 |
| `APP_ARTIFACT_DIR` | 含 `latest.json` 的模型根目录 |
| `APP_COOKIE_SECURE` | HTTPS 部署时设为 `true` |
| `APP_SESSION_MAX_AGE_SECONDS` | 登录有效期 |
| `APP_SEED_DEMO_DATA` | 是否初始化账号、内容与模型投影 |
| `APP_SEED_OFFICIAL_CATALOG` | 有处理数据时是否导入完整内容表 |
| `APP_DEMO_PASSWORD` | 本地测试账号初始密码 |
| `OPENBLAS_NUM_THREADS` | 限制 CPU 数值库线程数 |

## 7. 文档与边界

- 架构与失败恢复：`docs/ARCHITECTURE.md`
- API 与数据库：`docs/API_AND_SCHEMA.md`
- PDF 必选/可选验收：`docs/ACCEPTANCE.md`
- 评估与 Badcase：`reports/EVALUATION.md`
- 完成/Mock/风险：`reports/COMPLETION.md`
- 自动化、浏览器、CI、fresh clone：`reports/TEST_EVIDENCE.md`
- AI/subagent 边界：`docs/AI_COLLABORATION.md`
- 视频与分镜：`docs/DEMO.md`
- 逐 Gate 失败与修复：`docs/ITERATION_LOG.md`

当前 Mock 只有本地封面占位图与 synthetic smoke 小数据。包含官方用户历史的完整 runtime 只在
本地生成和验证，不通过公开仓库或 Release 二次分发。v0.3 明确只支持单 Uvicorn worker；
SQLite、被动 Dashboard 告警和本机 latency 不能包装成生产 SLA。未做公网部署、Redis、异步训练、
多 worker 一致性、真实告警通知、神经召回或多模态特征。离线结果不代表线上因果收益。
