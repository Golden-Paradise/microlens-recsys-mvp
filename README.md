# MicroLens Recsys MVP

基于官方 MicroLens-50K 的 CPU-first 推荐系统闭环：数据处理与 ALS 训练 -> 多用户登录 -> 个性化/热门/探索三路 Feed -> 曝光与行为回传 -> Dashboard -> 强推、下线、恢复与审计。

- 私有仓库：<https://github.com/Golden-Paradise/microlens-recsys-mvp>
- ALS Release：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.1.0-als>
- 4:08 演示视频：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/download/v0.1.0-als/microlens-recsys-mvp-demo.webm>
- 本地 Demo：<http://127.0.0.1:8000/login>
- OpenAPI：<http://127.0.0.1:8000/docs>

## 1. 最快验收：无数据 smoke

前置：Git、[uv](https://docs.astral.sh/uv/)，Python 3.11-3.13。Windows PowerShell：

```powershell
git clone https://github.com/Golden-Paradise/microlens-recsys-mvp.git
Set-Location microlens-recsys-mvp
uv sync --frozen
uv run microlens smoke
```

`smoke` 在临时目录生成 4 用户/6 内容的离线数据并训练微型 ALS，然后验证登录、个性化 Feed、曝光、点赞、画像更新、强推和下线权威。它不依赖本机数据库、官方数据或已有模型。

## 2. 直接运行已训练 ALS

私有仓库协作者可用 GitHub CLI 下载约 20.6 MB 的模型 bundle：

```powershell
gh release download v0.1.0-als --pattern "microlens-als-bundle-*.zip" --dir artifacts/download
Expand-Archive artifacts/download/microlens-als-bundle-f64-764b7d14ce34.zip artifacts -Force
Copy-Item .env.example .env
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Bundle SHA256：`12900F9FD1894018134493876A9404D8895FB8F28F5296D0B0EDDFF2F9E7E229`。模型能立即加载；若尚未准备官方内容元数据，服务会以 40 条本地种子内容运行。要展示完整 19,220 条内容，请继续执行第 3 节的数据命令。

## 3. 从官方数据完整复现

只下载官方三份文本数据，不下载、不上传 637 MiB 封面包：

```powershell
uv run microlens download
uv run microlens prepare
uv run microlens train
Copy-Item .env.example .env
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

数据来源：<https://github.com/westlake-repl/MicroLens>。目录约定：原始文件在 `data/raw/`，版本化处理结果在 `data/processed/<data_version>/`，模型在 `artifacts/<model_version>/`；这些均被 Git 忽略。

`prepare` 解析 pairs、title、likes/views，逐用户按官方序列留最后两条为 validation/test，输出 split CSV、CSR 矩阵、`items.csv`、`user_histories.csv`、映射和摘要。本机最近一次全量处理为 5.49 秒。官方 pairs 没有绝对时间，因此 `sequence_position` 才是切分依据；导出的 timestamp 仅为明确标注的合成序号。

`train` 在 validation 上比较 32/64 因子，以 NDCG@20 选型，再用 train+validation 重训并只评估一次 test。建议普通 CPU 预留 5-15 分钟和 2 GB 内存，实际随硬件变化；配置见 `configs/als.toml`。

## 4. 测试账号与演示路径

所有账号默认密码均为 `DemoPass123!`，只用于本地 Demo，可通过 `APP_DEMO_PASSWORD` 修改。

| 账号 | 角色 | 官方数据用户映射 |
|---|---|---:|
| `alice` | 普通用户 | 10001 |
| `bob` | 普通用户 | 10002 |
| `carol` | 普通用户 | 10003 |
| `admin` | 管理员 | 无 |

1. Alice 和 Bob 分别登录 `/login`，切换个性化、热门、探索；个性化结果来自各自 ALS 历史。
2. 点击“打开/喜欢/不感兴趣”，再查看 `/profile`；行为与曝光由同一 `request_id` 关联，画像版本递增并参与下一次排序。
3. Admin 登录 `/admin/dashboard` 查看真实聚合、用户调试、请求链路和模型版本。
4. 在 `/admin/contents` 按 ID/标题搜索，配置强推范围和时窗；下线后 Feed、强推和 `/api/items/{id}` 均不可返回，恢复后重新进入候选。
5. `/db-admin/` 是独立管理员认证的只读数据库审计页。

## 5. 测试与质量门禁

```powershell
uv run pytest
uv run ruff check app recsys tests
uv run microlens offline-smoke
uv run microlens smoke
```

当前证据：23 项自动化测试通过；全量数据为 50,000 用户、19,220 内容、359,708 交互；Test ALS Recall@20=`0.06154`、NDCG@20=`0.02359`、Coverage@20=`0.21202`。详见 `reports/EVALUATION.md` 和 `docs/ACCEPTANCE.md`。

## 6. 环境变量

| 变量 | 用途 |
|---|---|
| `APP_SECRET_KEY` | Session 签名密钥，部署时必须替换 |
| `APP_DATABASE_URL` | SQLite URL，默认 `sqlite:///var/app.db` |
| `APP_PROCESSED_DIR` | 处理数据根目录 |
| `APP_ARTIFACT_DIR` | 含 `latest.json` 的模型根目录 |
| `APP_COOKIE_SECURE` | HTTPS 部署时设为 `true` |
| `APP_SESSION_MAX_AGE_SECONDS` | 登录有效期 |
| `APP_SEED_DEMO_DATA` | 是否初始化账号、内容与模型版本 |
| `APP_SEED_OFFICIAL_CATALOG` | 有处理数据时是否导入完整内容表 |
| `APP_DEMO_PASSWORD` | 本地测试账号初始密码 |
| `OPENBLAS_NUM_THREADS` | 限制 CPU 数值库线程数 |

## 7. 文档与边界

- 架构、数据流、失败恢复：`docs/ARCHITECTURE.md`
- API 与数据库：`docs/API_AND_SCHEMA.md`
- PDF 必选项矩阵：`docs/ACCEPTANCE.md`
- 完成/Mock/风险/一周迭代：`reports/COMPLETION.md`
- AI/subagent 协作：`docs/AI_COLLABORATION.md`
- 演示视频与分镜：`docs/DEMO.md`

当前 Mock 仅为封面占位图和无官方数据时的 smoke 小目录；全量切分、ALS、在线推荐、事件、Dashboard 和运营规则都使用真实服务端链路。当前未做公网部署、原始封面、Redis/异步训练、自动增量重训等加分项。
