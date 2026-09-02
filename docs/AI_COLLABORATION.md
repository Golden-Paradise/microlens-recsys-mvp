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
- v0.1 私有阶段 Release 同时提供 ALS bundle 与 04:08 视频，分别记录 SHA256；原始数据、PDF、
  数据库和密钥未上传。最终公开审计进一步确认 v0.1/v0.2 的旧模型 bundle 含用户交互衍生
  结构，因此必须在 visibility 改为 public 前移除，不能把“无原始 TSV”误写成“无用户数据”。

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

## v0.3 并行迭代与主 Agent review

| 角色 | 独占范围 | 首稿/审查输出 | 主 Agent 收口 |
|---|---|---|---|
| Rawls（Offline） | 内容召回模块与离线测试 | TF-IDF、pure-cold、quota、保存回载；正式指标审计 | 公共 manifest、线上 Hybrid K、正式 test 纪律、评估文档 |
| Huygens（Backend） | ModelManager/观测聚合只读审查 | 锁、pointer、checksum、启动恢复、API/CI 缺口 | 公共 schema、API 注册、投影语义、runtime smoke |
| Newton（Frontend） | Dashboard JS/CSS/UI 测试与只读 QA | 决策表、健康区、请求双栏/移动时间线审查 | 真实浏览器、缓存指纹、截图清理和证据命名 |
| 主 Agent | 跨模块契约、正式训练、Git/Release | 集成、失败修复、70-test Gate、视频和 bundle | validation/test/线上边界与最终对外结论 |

关键 prompt 约束：subagent 不自行 commit；Rawls 不改公共 manifest/engine，Huygens 不改模板，
Newton 不改领域服务；正式 Test 只能在 validation 冻结后由主 Agent运行一次。二次审计均为只读，
避免覆盖主线未提交改动。

主 Agent review 后的代表性修复：

1. Hybrid 最初向 bundle 取 Top-100 再截 Top-20，导致尾部 cold quota 在线不可见；改为按最终
   展示 K 混排，并补真实 Engine 回归测试。
2. CSV 空标题被 pandas 转成字符串 `nan`，且 analyzer 同分规则依赖配置顺序；改为先填空，
   并显式执行“小 quota 优先、Word 优先”。
3. 训练默认写 `latest.json` 会绕过管理发布；改为 candidate 默认，只有显式 `--activate`
   才 bootstrap。
4. v0.3 初稿未 checksum `manifest.json`，也未校验 BM25/Cosine 维度；两项均进入 strict Gate。
   旧 artifact 可启动，但无 manifest checksum 不可经 publish/rollback 重新激活。
5. 发布成功后若 SQLite 模型投影失败，旧 API 会返回 500，造成“模型已切但接口说失败”；现在
   pointer/内存保持权威，响应附 `projection_warning`，投影可由后续 GET/启动修复。
6. 前端最初把健康区与请求列表做成双栏，详情仍在旧区域；改为请求列表/详情同 section 双栏，
   移动端纵向时间线。`test=null` 改为“未正式测试”，低于 20 样本改为“不判断告警”。
7. 浏览器缓存仍加载旧通用 registry；最终使用 CSS+JS 内容 SHA，而不是手工版本号。修复前、
   长页拼接和包含本机路径的截图均在 staging 前删除。
8. 首轮 v0.3 视频因 headless UI 按钮没有发出 publish POST 而中止。日志确认后删除部分视频，
   第二轮通过同一登录 session 调正式 API、重载 UI 展示状态，并用 `finally` 保证回滚。

v0.3 对外措辞由证据约束：TF-IDF 是 validation 上的 pure-cold 正收益、overall 负实验；正式
Test 只有 BM25；24 请求 latency 是本机阶段性观测；Dashboard warning 是被动状态，不是生产
告警；系统只保证单 worker。AI 参与实现不等于这些结论自动成立，所有结论均由产物、命令和
浏览器复核；远端 Release hash 只有在 G5 实际发布并重新下载后才记录。

最终公开审计发现，本地完整 runtime 含 `serving_user_items.npz` 和逐用户 Badcase，不能随公开
仓库提供二次下载。主 Agent据此否决原 runtime Release 方案：完整 bundle 保持本地且被 Git
忽略；公开附件只保留 BM25 权重、无用户信息的 item 索引、模型清单和聚合指标。这个调整优先
满足 MicroLens 数据边界，不把“模型可下载”建立在重新分发官方交互数据之上。
