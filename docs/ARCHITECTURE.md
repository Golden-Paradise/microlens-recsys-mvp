# 系统设计

## 总体架构

```mermaid
flowchart LR
  O[MicroLens 官方三文件] --> P[prepare: 校验/逐用户留二切分]
  P --> D[CSV + CSR + 用户历史 + 摘要]
  D --> T[ALS/ItemCF/RRF/标题 TF-IDF 训练评估]
  T --> A[版本化 Artifact + Manifest + SHA256]
  A --> R[ModelManager 校验/原子发布/回滚]
  R --> S[FastAPI 推荐服务]
  U[HTTP-only Session 用户] --> S
  S --> Q[(SQLite WAL)]
  Q --> B[Dashboard/用户调试/请求链路]
  M[管理员运营] --> B
  B --> Q
  Q --> S
```

`recsys/` 负责官方数据、切分、baseline、ALS、ItemCF、RRF、标题 TF-IDF、评估和版本化
artifact；`app/` 负责身份、Feed 编排、在线反馈、ModelManager、时间范围 Dashboard 与运营。
SQLite 是事件/运营状态权威，pointer 与内存 ModelManager 是运行模型权威，`model_versions`
只是可修复的 Dashboard 投影。单进程设计适合笔试 Demo；不宣称多 worker 切换一致性。

## 离线数据与防泄漏

官方 pairs 只有每个用户内的交互顺序，没有可信绝对时间。每个用户去重后至少 3 条：最后一条为 test、倒数第二条为 validation、其余为 train，满足 `max(train_position) < validation_position < test_position`。模型选择只看 validation；选定 64 因子后以 train+validation 重训，test 只使用一次。

输出包括三份 split CSV/CSR、完整交互、内容元数据、训练用户历史、映射和摘要。ALS 和 ItemCF
将观测交互视为隐式正反馈，未观测项是未知而非显式负样本，因此没有伪造负标签。Validation
固定比较 ALS-32/64、Cosine ItemCF、BM25 ItemCF 和 ALS+BM25 等权 RRF；选择指标是
overall NDCG@20，test 不参与选型。协同策略过滤已见和 fit split 中零交互的纯冷内容；标题
TF-IDF 恰好只允许这些 pure-cold item，并用最近 10 条历史标题向量形成用户画像。Coverage
分母固定为完整 19,220 内容目录；overall、warm 和 pure-cold 三切片同时报告。

Validation 比较 Word `(1,2)`、`char_wb (3,5)` 与 cold quota `0/1/2/3/5`。Hybrid 保留
BM25 头部，只在 Top-20 尾部预留 cold slots；同分优先更小 quota，再优先 Word。正式结果中
BM25 overall NDCG 胜出，因此内容矩阵保存在 artifact 供复核，`serving_policy` 仍为 `bm25`。

## 在线召回、排序和混排

```text
在线内容 -> 已曝光/不感兴趣过滤
  personalized: request 开始 snapshot engine -> manifest 选定 ALS/ItemCF/RRF/Hybrid -> 有界反馈重排
  popular: train_interactions + likes + views
  explore: 全局低曝光优先 + 用户稳定散列
-> 有效期/范围匹配的运营强推
-> 最终 online 权威过滤 + 去重
-> request + exposures + impression 同事务落库
```

三个 Demo 用户映射到不同 MicroLens 用户，v0.3 manifest 仍选择 BM25 ItemCF 并返回业务 item ID。
ALS、Cosine、BM25 和固定 RRF 均保存在同一 bundle，便于复核和消融，但不会绕过 validation 结果
强行上线。点击权重 `0.5`、喜欢权重 `1.5` 累计到 `item_id % 5` 的轻量画像桶；反馈 bonus
最大为当前模型候选分数跨度的 10%，能调整邻近候选但不能压倒整个召回。这是在线重排，不冒充
重新训练。新用户或未知 source ID 走训练集热门回退；模型失败则降级到确定性热门流，并记录
`fallback_reason`。

## 一致性与可观测性

- 每次 Feed 生成 UUID `request_id`，先写 recommendation request，再写有位置、来源、分数、解释的 exposures 和自动 impression。
- 客户端 click/like/not_interested 必须引用当前用户拥有的 exposure；`event_id` 唯一，同 payload 重试返回 duplicate，冲突 payload 返回 409。
- SQLite 启用 foreign keys、WAL、NORMAL synchronous；事件与画像版本在同一事务提交。
- Dashboard 从数据库实时聚合用户、活跃用户、请求、曝光、点击、CTR、点赞、流占比和热门
  内容；1h/6h/24h/all 使用 UTC 半开窗口，趋势按固定时间桶补零。用户/内容/模型状态保持
  全局口径，活跃用户排除管理员；请求链路可回查 exposure 与 event。
- 每个请求记录模型版本、Feed、页码、Feed 构建延迟和 fallback 原因。nearest-rank
  P50/P95/max 按 Feed/模型聚合；至少 20 样本后才对 fallback rate `>=5%` 或 P95
  `>=500ms` 显示 Dashboard 被动 warning。该延迟不含完整 HTTP 序列化，不是端到端 SLA。

## 模型发布

训练先完整写入新的 `artifacts/<model_version>/`，生成 ALS、Cosine、BM25、标题 TF-IDF、
CSR、映射、Popularity、metrics、Badcase、checksums 和 manifest。默认只形成 candidate；仅首次
bootstrap 使用 `--activate`，正常上线由管理 API 完成。

`ModelManager.publish()` 只接受 artifact root 的直接子目录，拒绝绝对路径、穿越和
manifest/version 不一致。它验证 manifest 引用、完整 SHA256、ALS/CSR/ItemCF/内容矩阵维度，
在状态锁外加载和 warm-up；随后先以同目录临时文件 `flush + fsync + os.replace` 更新 pointer，
再以短锁切换 engine。请求开始时只取一次 snapshot，因此切换前开始的请求完整使用旧模型。

pointer schema v2 保存 current/previous；rollback 重新严格校验 previous 后交换，允许再次切回。
启动 current 损坏时尝试 previous 并修复 pointer；两者都坏才使用 deterministic fallback。
旧 pointer 自动升级；旧 bundle 可兼容启动，但缺 manifest checksum 时标为
`legacy_unverified` 且不能通过管理 API 重发。大二进制不进入 Git；包含官方用户历史的完整
runtime 也不公开分发。公开 Release 只提供选中 BM25 权重、item 索引、合规模型清单、聚合评估、
视频和统一 SHA256SUMS，完整 runtime 由官方数据在本地重建。

## 权限与运营优先级

- 密码用 Argon2 哈希；应用登录态为签名 HttpOnly、SameSite=Lax Session。普通用户身份只从服务端 session 读取，不能提交任意 user ID。
- 所有 `/api/admin/*` 在服务端校验 admin 角色；SQLAdmin 另用独立管理员 cookie，所有视图禁用新增、修改、删除。
- 强推支持全体、指定用户名/本地用户 ID、指定 Feed，以及开始/结束时间。强推只在第一页注入并保留来源/原因。
- 下线是最终权威：候选生成后再检查 `Item.status`；离线内容无法新建强推、不能出现在任何 Feed，直接内容 API 返回 404。恢复只恢复可候选状态，不绕过正常排序。每次操作记录管理员、原因、前后状态和时间。

## 失败恢复与已知问题

| 故障 | 当前行为 | 后续扩展 |
|---|---|---|
| 官方文件缺失/格式错 | prepare 明确失败，不覆盖版本指针 | 下载重试与 schema 告警 |
| 训练中断 | candidate 不改 pointer，current 继续服务 | 异步训练状态机 |
| 候选缺失/篡改/维度错 | publish 409，pointer 与内存不变 | 集中制品签名服务 |
| current 启动损坏 | 严格校验 previous，成功则 recovered 并修复 pointer | 跨机器制品副本 |
| current/previous 均坏 | deterministic fallback，trace 可查原因 | 熔断与真实外部告警 |
| 候选不足/已看过多 | 热门/探索补位；返回空态而非白屏 | cursor 与多路候选池 |
| SQLite 不可用 | 请求失败并返回 HTTP 错误，不伪造数据 | PostgreSQL 主从与队列 |
| 多 worker/多机 | 明确不支持一致热切换，只运行 `--workers 1` | 外部版本协调与分布式锁 |

最大数据风险是官方序列缺少绝对时间，不能分析真实日历时间衰减或跨用户同时段漂移；文档和产物均明确把 timestamp 标记为合成值。
