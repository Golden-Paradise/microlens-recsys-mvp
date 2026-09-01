# AI 协作记录

## 工具与边界

- 主工具：Codex。
- AI 用途：架构拆分、代码实现、测试生成、命令执行、浏览器验收和文档整理。
- 人工责任：确认产品取舍、逐项核对 PDF、审查公共接口、运行测试、检查页面、确认数据和结论边界。
- 数据边界：只从 MicroLens 官方地址下载；不让 AI 重新打包或公开数据。

## 本轮关键任务

| 角色 | 任务范围 | 禁止修改 | 复核方式 |
|---|---|---|---|
| 主 Agent | 公共 Schema、依赖、集成、Git、全量测试与交付 | 不伪造测试或指标 | 统一 pytest/ruff、全量数据、浏览器和全新 clone |
| Offline subagent | 下载、切分、baseline、ALS、评估和模型产物 | 在线 API 和公共契约 | 离线单测、真实数据训练、产物重载 |
| Online subagent | SQLite、认证、Feed、事件、Dashboard、运营服务 | 离线算法和公共契约 | API 集成测试、权限与冲突测试 |
| Frontend subagent | Jinja 页面、静态资源、只读 SQLAdmin | 领域写逻辑和公共契约 | 模板测试、真实浏览器交互和截图 |

## 人工 review 检查点

1. PDF 必选项是否逐项有实现和测试证据。
2. 时间切分、训练特征和指标是否存在未来信息泄漏。
3. 推荐是否因用户和行为真实变化，而非写死或只改前端。
4. request_id、曝光、行为、Dashboard 是否来自同一数据库链路。
5. 强推与下线冲突是否始终由服务端执行“下线优先”。
6. README 是否能在新目录复现，Git 是否排除数据、密钥和本机状态。

## 关键 prompt 摘要

1. 先冻结公共 schema、目录边界和验收矩阵；每个 Gate 先测试再提交。
2. 离线 Agent 只负责官方数据、时序切分、baseline、ALS、指标和 artifact，不改在线契约。
3. 在线 Agent 只负责 session、Feed、曝光/事件、Dashboard 和运营规则，不复制训练逻辑。
4. 前端 Agent 只消费 API，提供真实错误/空态、响应式页面和只读 SQLAdmin，不在前端写死指标或推荐列表。
5. 主 Agent 负责真实 ALS 接入、官方内容 seed、跨模块测试、浏览器、Git/Release 和 PDF 必选项逐条收口。

AI 生成了大部分实现首稿、测试和文档草稿，约占代码编写工作 85%；比例不代表正确性。架构边界、验收口径、数据结论和每次合入均由主 Agent 基于命令、产物、浏览器和 PDF 复核。用户负责最终业务取舍、仓库公开/授权和对外交付决定。

## 人工/主 Agent review 后的典型修复

- 首次真实启动虽然显示 ALS 版本，但 SQLite 只有 40 条 fixture。根因是 seed 传了 processed 根目录而非 `latest.json`；修复后实测 19,220 内容。
- 子模块最初都通过单测，但 `app.main` 尚未加载 ALS、也未注册 Web/SQLAdmin；主 Agent 完成 source_user_id 映射、artifact 加载和公共集成。
- PDF 明确要求用户历史、Feed 占比和热门内容；逐项复核后新增 `user_histories.csv` 及真实 Dashboard 聚合，而非在文档中模糊带过。
- 行为变化不能只靠“已看过滤”解释；真实运行确认点赞 bucket 后下一页 8/8 内容进入对应桶，证明反馈进入服务端重排。
- 编辑 smoke CLI 时曾把离线训练尾段插入错误函数位置；全量 pytest/ruff/smoke 立即发现并修正。
- 浏览器验证了 #40 强推 -> 下线 -> Feed 消失 -> 恢复；桌面/移动无溢出，console 无错误。视频首轮因 Windows ESM 路径、第二轮因缺 ffmpeg 失败，均未伪报成功；安装官方编码器后生成并抽帧检查。

## 最终验证方法

- 每个 Gate 独立 commit/push；`pytest`、Ruff、synthetic smoke、官方全量训练/回载、模型 checksum。
- FastAPI TestClient 覆盖认证、权限、事件幂等、运营冲突和 fallback；真实浏览器覆盖主要旅程与响应式布局。
- v0.1 私有 Release 同时提供 ALS bundle 与 04:08 视频，分别记录 SHA256；原数据、PDF、
  数据库和密钥不上传。v0.2 Release 只提供模型 bundle 与独立 SHA256 文件，不上传新视频。

## v0.2 并行迭代记录

| 角色 | 独占范围 | 输出 | 主 Agent review |
|---|---|---|---|
| Offline subagent | `recsys/model.py`、评估、配置、离线测试 | Cosine/BM25 ItemCF、RRF、artifact、正式指标 | 矩阵方向、过滤、test 边界、兼容、线上接入 |
| Online subagent | Dashboard service/API/在线测试、CI | UTC 窗口、补零趋势、Ubuntu workflow | 角色口径、边界条件、远端 Actions |
| Frontend subagent | Dashboard 模板、JS/CSS、UI 测试 | 分段控件、原生 SVG、tooltip/空/错态 | 1280/390 浏览器、像素与 console |
| 主 Agent | 公共契约、文档、Git/Release | manifest/schema、集成、留痕、交付 | 全量 pytest/Ruff/smoke、fresh clone |

关键 prompt 边界：三个 subagent 不得修改公共 schema、文档、Git 或彼此文件；离线任务不得查看
test 后再调策略；前端只能消费真实 API；主 Agent 在每个 Gate 测试和日志完成后才提交。

Gate/commit 映射：G1=`e209da5`；G2=`d97aa8a`；G3 workflow=`a11616d`，Node 24
维护升级=`bc71748`，setup-uv 精确标签修复=`5d9fc83`。Frontend focused suite 为 11 passed、
在线 focused suite 在 UTC 契约补测后为 10 passed，当前全仓为 30 passed，Node syntax passed。

v0.2 人工/主 Agent 修复：

1. `implicit.ItemItemRecommender` 使用 `filter_items` 时会内部扩大 N；离线 helper 和 Bundle
   出口增加二次硬截断，并覆盖四种 serving policy。
2. 原在线引擎把所有个性化结果写成 `source=als`；改为按 manifest 输出
   `itemcf_bm25` 等真实来源，反馈 bonus 限制为模型分数跨度的 10%。
3. 浏览器发现普通用户数 3、活跃用户 4；原因是管理员 Feed 请求进入 distinct user 聚合，
   修复为 join users 并过滤 `role=user`。
4. Dashboard 截止边界最初使用 `<= end`，与趋势桶不一致；统一改为 UTC `[start,end)`。
5. 首次 CI 虽全绿，但旧 action major 触发 Node.js 20 弃用 annotation；查询官方 Release 后
   升级。第二次又因 setup-uv 没有浮动 `v10` 标签失败，最终精确固定 `v10.0.1` 后全绿且
   annotations 为空。
6. 一次 `git push` 遇到瞬时 TLS connect error；没有改写提交，原命令重试后成功。
7. 正式训练没有记录完整开始时间。文档只写可证实的 artifact 发布时间，并将时间戳 wrapper
   固定为后续实验门禁，没有反推或伪造 wall-clock。

v0.2 代码首稿仍主要由 AI/subagent 生成；指标口径、选型、修复、浏览器、远端 CI、Release
和对外结论由主 Agent 基于真实命令与产物复核。RRF 的 Recall 更高但
NDCG 更低，因此没有为了
展示复杂架构而冒充线上最优方案。
