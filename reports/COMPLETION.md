# 完成度、Mock、风险与一周迭代

## 已完成

- 官方 MicroLens-50K 三个文本文件的下载、来源 URL/SHA256 记录、异常检查、逐用户顺序切分、
  内容元数据、用户历史、CSV/CSR 和数据摘要。
- Random/Popularity baseline、ALS-32/64、Cosine/BM25 ItemCF、固定 RRF、标题 Word/`char_wb`
  TF-IDF、cold quota 消融、overall/warm/pure-cold 三切片和 validation-only 选型。
- 冻结 BM25 后一次性执行 formal Test；生成模型、候选统计、指标、匿名可汇报 Badcase、manifest
  和 SHA256，并由线上 Feed 消费正式模型。
- 3 个普通账号和 1 个管理员；Argon2、HttpOnly session、退出/过期、服务端用户数据和管理权限
  隔离。
- 个性化、热门、探索三路 Feed；分页、去重、已看/不感兴趣过滤、来源/分数/理由/模型版本和
  deterministic fallback。
- request_id、position、impression/click/like/not_interested、事件幂等、曝光所有权与有界实时
  画像重排。
- 真实 SQLite 聚合 Dashboard：时间窗口、趋势、Feed 占比、热门内容、用户调试、单请求曝光/
  事件时间线、模型决策、P50/P95 与 fallback 被动告警。
- 内容搜索、按用户/Feed/全体强推、生效/失效时间、下线、恢复、服务端最终权威过滤和操作审计。
- 严格 artifact checksum/维度校验、candidate 默认不激活、原子 pointer、单 worker 模型发布/
  回滚、previous 启动恢复和 last-known-good 保护。
- 本地 70 项自动化测试、Ruff、Node syntax、diff check、双 artifact publish/rollback smoke 和
  1280x720/390x844 浏览器验收已通过。公开仓库、真实 CI 与匿名 fresh clone 均已验证；最终
  04:33.96 视频覆盖五段必选旅程，并通过运行断言、黑帧检测和 22 个关键帧复核。

## Mock 与未完成

| 项目 | 状态 | 边界 |
|---|---|---|
| 封面 | Mock | 使用本地占位图；未下载 637 MiB 官方封面包，题目明确允许 |
| synthetic smoke 数据 | Mock | 只验证干净环境链路；正式指标来自官方 50K 数据和正式 artifact |
| 本地演示账号与 SQLite | Demo seed | 账号和事件是可重置演示状态，不冒充真实业务用户或线上流量 |
| 绝对时间与全站时间切分 | 数据源不支持 | 官方仅有用户内顺序；不伪造真实时间衰减、漂移或全局窗口结论 |
| 自动增量重训 | 未做 | 在线事件已结构化记录，尚未自动导出并触发训练/评估/发布 |
| 多 worker/多机模型一致性 | 未做 | v0.3 明确只支持 `uvicorn --workers 1`；无分布式锁或外部版本协调 |
| Redis/异步任务 | 未做 | 当前单进程 SQLite 足够完成笔试闭环，不包装成高并发架构 |
| 主动告警通知 | 未做 | Dashboard 有阈值和被动警告，没有短信、邮件或 on-call 集成 |
| 神经召回、排序与多模态 | 未做 | DSSM/DeepFM、checkpoint/早停、图像/视频特征属于加分项 |
| 公网 Demo | 未做 | 本地 `127.0.0.1:8000` 可完整验收；不对外暴露带写权限的管理面 |
| v0.3 远端发布收口 | 已完成 | `v0.3.0` tag/Release、四附件、匿名下载、哈希、ZIP 结构和公开链接均已回验 |

标题 TF-IDF、checksum、模型发布/回滚和延迟/fallback 观测均已实现，不再列入未来功能。标题
TF-IDF 只在 validation pure-cold 切片显示正信号，因 overall NDCG 未胜出而没有成为正式
serving policy；这是选型结果，不是“功能未完成”。

## 最大技术风险

1. **时间语义有限**：只能证明用户内顺序无泄漏，无法验证真实全站时间漂移、季节性和时间衰减。
2. **正式 Test pure-cold 仍为零**：标题 TF-IDF 在 validation 有信号，但当前冻结 BM25 对 576 个
   formal Test pure-cold target 的 Recall/NDCG 均为 0；不能把覆盖率或 validation 消融包装成解决。
3. **反馈没有自动进入下一轮模型**：行为会即时改变轻量画像和排序，但批量导出、离线重训、评估
   Gate 与发布仍需人工执行。
4. **单机运行边界**：SQLite 与单 Uvicorn worker 适合演示，不适合高并发事件写入或多副本一致切版；
   本机 P50/P95 也不是生产 SLA。
5. **模型发布的数据最小化**：完整 artifact 含服务用户矩阵和 Badcase 明细，只能私有保存；公开
   Release 必须执行 allowlist，不能直接压缩整个 artifact 目录。

## 如果再给一周

| 时间 | 迭代 | 冻结验收 |
|---|---|---|
| Day 1 | 事件导出与训练样本回放，定义幂等水位 | 同一水位重复导出结果一致；不跨切分泄漏 |
| Day 2 | 调研可用绝对时间源，增加数据漂移与质量门禁 | 乱序、缺元数据、分布漂移和时间范围测试 |
| Day 3 | 冻结时间一致的负采样，训练轻量排序器 | 多 seed validation；PR-AUC/NDCG 与校准报告 |
| Day 4 | 改进内容表示和动态候选配额 | overall/warm/pure-cold 同时报告，不以 Test 调权 |
| Day 5 | 外部版本协调、多 worker 灰度与回滚 | 并发请求、坏 artifact、进程重启和切版一致性 |
| Day 6 | 结构化日志、负载测试与主动告警接入 | P50/P95/P99、fallback、告警触发/恢复演练 |
| Day 7 | 只读公网 Demo、真实封面缓存和交付复核 | 权限、隐私、数据许可证、fresh clone 与视频复查 |

一周迭代仍遵守 validation 选型、formal Test 只验收一次和服务端运营权威三个不变约束；离线提升
只有在固定协议、多 seed 和完整切片下稳定成立，才进入新的模型发布候选。
