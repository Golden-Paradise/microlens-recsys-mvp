# PDF 必选项验收矩阵

本表只记录可复核证据。状态含义：`TODO` 尚未完成，`PASS` 已由命令或端到端验收证明。

| 模块 | 必选验收 | 自动化或人工证据 | 状态 |
|---|---|---|---|
| 数据处理 | 官方三文件可下载；输出用户/内容/交互/时间摘要 | `microlens prepare` + `tests/test_offline.py` | PASS |
| 时间切分 | 逐用户 train < valid < test，无未来交互进入训练 | `test_temporal_split_has_no_per_user_leakage` | PASS |
| 离线训练 | Random/Popularity baseline + 可学习 ALS | `microlens train` + 模型 manifest | PASS |
| 离线评估 | Recall@20、NDCG@20、Coverage@20，含口径和 Badcase | `reports/EVALUATION.md` | PASS |
| 多用户登录 | 3 个普通用户和 1 个管理员；刷新保持、退出失效 | API 测试 + 浏览器验收 | PASS |
| 权限隔离 | 普通用户不能访问 Dashboard 和运营写接口 | 403 接口测试 | PASS |
| 推荐信息流 | 个性化、热门、探索；分页、去重、已看过滤、fallback | Feed 接口测试 + 浏览器验收 | PASS |
| 曝光与行为 | request_id 关联 position；4 类事件齐全 | 事件/曝光数据库断言 | PASS |
| 画像更新 | 行为后 profile_version 和后续排序发生变化 | 行为前后排序指纹测试 | PASS |
| Dashboard | 用户/活跃/请求/曝光/点击/CTR/点赞/流占比/热门内容 | 聚合接口测试 + 浏览器验收 | PASS |
| 用户调试 | 最近行为、画像、最近 request_id 和返回内容 | 管理员接口与页面验收 | PASS |
| 模型运行 | 数据版本、训练时间、指标、发布状态；失败不覆盖 | 模型版本测试 | PASS |
| 内容运营 | 搜索、强推范围与有效期、下线、恢复、审计 | 运营端到端测试 | PASS |
| 下线权威 | 所有 Feed、强推和直接内容 API 最终过滤 | 冲突优先级测试 | PASS |
| 工程启动 | 干净环境按 README 启动，无真实密钥 | `v0.3.0` 匿名 fresh clone：frozen sync、70 tests、offline+online smoke | PASS |
| 文档视频 | README、API/DB、系统设计、完成度、3-5 分钟视频 | Release 最终视频 04:33.96、1280x720、VP8，22 个关键帧人工复核 | PASS |

## v0.2 可选加分项

| 加分能力 | 可复核证据 | 状态与边界 |
|---|---|---|
| Item-Item CF | Cosine/BM25 K=100、保存加载、checksum、全量 valid/test | PASS；交互共现，不是文本 BM25 |
| 多路融合实验 | ALS+BM25 等权 RRF、稳定去重、消融指标 | PASS；NDCG 未胜出，未作为线上默认 |
| Validation 选型 | ALS/Cosine/BM25/RRF 只按 valid NDCG@20 冻结 | PASS；BM25 入选后才统一跑 test |
| 线上模型消费 | Feed 返回 `itemcf_bm25`、分数、原因和 v0.2 模型版本 | PASS；反馈 bonus 有 10% 分数跨度上限 |
| Dashboard 时间范围 | 1h/6h/24h/all 同口径概览、诊断、流占比、热门内容 | PASS；UTC 半开区间 |
| 趋势折线图 | 5/30/60/1440 分钟补零桶、五指标 SVG、tooltip、空/错态 | PASS；无前端图表依赖 |
| 响应式验收 | 1280x720 与 390x844 目标 viewport、12 个真实 SVG 点、无横向溢出 | PASS |
| CI | Ubuntu/Python 3.11 frozen sync、Ruff、30 tests、smoke | PASS；main run 39 秒，零 annotations |
| 过程留痕 | Changelog、逐 Gate 日志、失败根因、修复和 run URL | PASS |
| v0.2 历史 Release | 36,866,255-byte bundle 的 digest 曾回验一致 | 历史记录；含用户交互衍生结构的 ZIP 与 checksum 已在公开前移除 |

v0.2 历史 Release：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.2.0>。
旧 ZIP 没有原始 TSV，但含用户交互衍生结构，不符合最终公开边界，已在仓库转 public 前从
Release 移除。v0.1 的 04:08 视频只作为历史过程证据，不再认定满足最终必选视频；最终
v0.3 视频已在公开仓库、真实 CI 和 fresh-clone smoke 完成后重录并通过媒体检查。

## v0.3 可选加分项

| 加分能力 | 可复核证据 | 状态与边界 |
|---|---|---|
| 标题 TF-IDF 冷启动 | Word/char_wb、recent-10 画像、cold-only、NPZ 回载和 checksum 测试 | PASS；只在 validation 调 analyzer/quota |
| Cold quota 消融 | quota 0/1/2/3/5，overall/warm/pure-cold 三切片 | PASS；pure-cold 提升但 overall 未胜，未上线 |
| 正式 Test 纪律 | 冻结后 train+validation 重训，`metrics.test` 只含 BM25 | PASS；未入选策略显示“未正式测试” |
| 模型完整性 | manifest/声明文件 SHA256、ALS/CSR/ItemCF/内容矩阵维度 | PASS；缺失/篡改/维度错均 409 |
| 原子发布与回滚 | request snapshot、临时 pointer、fsync/replace、current/previous 交换 | PASS；单 Uvicorn worker |
| 启动恢复 | current 坏尝试 previous；均坏 deterministic fallback 可查 | PASS；旧 bundle 启动兼容，未完整校验者不可重发 |
| 决策证据 | validation/test 分栏、选型指标、BM25/TF-IDF 消融表 | PASS；DB 表是投影，不是运行权威 |
| 请求时间线 | 列表/详情双栏，曝光顺序、来源、分数、理由和后续事件 | PASS；点击/点赞/负反馈共享曝光分母 |
| 运行可观测性 | nearest-rank P50/P95/max、fallback rate、Feed/模型分组 | PASS；20 样本后被动告警，不是短信/邮件 |
| 响应式 UI | 1280x720 与 390x844，SHA 静态缓存键，console 0 error/warning | PASS；表格局部横滚，页面无横向溢出 |
| 真实 runtime smoke | 两个微型严格 artifact，publish、新请求切版、rollback | PASS；临时目录，不复用本机状态 |
| 最终单视频 | 4:30-4:55，覆盖 PDF 五段必选旅程和 v0.3 决策/发布证据 | PASS；04:33.96，运行断言 + 黑帧检测 + 22 个关键帧复核 |
| 本地完整 runtime | 双版本 + v2 pointer，解压后 strict load/publish/rollback | PASS（仅本地）；含官方用户历史衍生物，不公开上传 |
| 公开 BM25 模型包 | 权重、item 索引、模型清单；排除用户矩阵/Badcase/标题向量 | REMOTE PASS；匿名下载后 3 成员/CSR/隐私标志/哈希复验通过 |

正式 v0.3 结论：内容召回证明“pure-cold 有信号”，没有证明“overall 更优”。因此线上仍为
BM25；这项负实验与未运行的 Test 均保留在 artifact、Dashboard 和评估报告中。

## 不接受项防线

- 推荐结果来自真实处理数据和训练产物，不使用前端固定 JSON。
- `user_id` 从服务端 session 推导，不能读取其他用户画像、行为或管理接口。
- Dashboard 只查询数据库聚合，不在页面写固定数字。
- 下线过滤位于服务端推荐流水线的最后权威步骤。
- 原始 MicroLens 数据、题目 PDF、真实密钥和本地数据库不提交到仓库。
