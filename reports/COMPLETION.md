# 完成度、Mock、风险与一周迭代

## 已完成

- 官方三文件下载、校验、异常检查、逐用户时序切分、内容元数据、用户历史、CSV/CSR 与摘要。
- Random/Popularity baseline、32/64 因子 ALS 选型、Test Recall/NDCG/Coverage、warm slice、Badcase、版本化保存/加载与 SHA256。
- 3 个普通账号 + 1 个管理员，Argon2、HttpOnly session、退出、过期配置和服务端权限隔离。
- 个性化/热门/探索三路 Feed，分页/加载更多、去重、已看/不感兴趣过滤、来源/分数/解释/模型版本和 fallback。
- request_id、position、impression/click/like/not_interested、事件幂等、曝光所有权和实时画像重排。
- 真实数据库 Dashboard、Feed 诊断、热门内容、流占比、用户调试、单请求链路和模型运行状态。
- 内容搜索、按用户/Feed/全体强推、时窗、下线、恢复、最终权威过滤和操作审计。
- 本地页面、只读 SQLAdmin、自动化测试、smoke、文档、私有 GitHub 分 Gate 提交、模型 Release。

## Mock 与未完成

| 项目 | 状态 | 边界 |
|---|---|---|
| 封面 | Mock | 使用本地占位图；未下载 637 MiB 官方封面包，题目允许 |
| smoke 数据 | Mock | 仅用于无网络 CI；全量指标和在线正式运行使用官方数据/artifact |
| 公网地址 | 未做 | 本地 `127.0.0.1:8000` 已闭环；不让部署阻塞必选项 |
| 自动增量重训 | 未做 | 在线事件已具备导出字段，当前只即时更新轻量画像 |
| Redis/异步任务/时间图表 | 未做 | 均为加分项，不属于当前闭环必要依赖 |
| 原始视频/多模态 | 未做 | 不下载、不托管，避免资源和数据授权风险 |

## 最大技术风险

1. 官方 pairs 没有绝对时间，只有用户内顺序；因此可以证明逐用户无未来泄漏，但不能模拟全站同一时间窗口、真实时间衰减或漂移。
2. ALS 对 576 个 test 纯冷 target 无法召回；当前 cold-start 线上依靠 Popularity/Explore，离线相关性仍有提升空间。
3. SQLite + 单进程适合 Demo，不适合高并发写事件；模型启动加载也尚未做双版本热切换。
4. `item_id % 5` 是可解释但粗粒度的实时画像代理，证明反馈闭环，不代表正式标签/embedding 画像。

## 再给一周

| 时间 | 迭代 | 冻结验收 |
|---|---|---|
| Day 1 | 事件导出、数据漂移/质量门禁、正式绝对时间源调研 | 重复/乱序/缺元数据测试 |
| Day 2 | 标题 embedding + item-item CF cold recall | validation warm/cold slice 提升 |
| Day 3 | 多路候选分数归一化、配额与多样性 | 固定 3 seeds，不看 test 调参 |
| Day 4 | 轻量排序器与负样本策略 | Recall/NDCG 外增加 ranking 指标 |
| Day 5 | PostgreSQL/Redis、异步事件写入、模型双版本原子热切 | 压测、故障注入、回滚 |
| Day 6 | Docker Compose、CI、结构化日志/延迟分位数 | 全新环境一键 E2E |
| Day 7 | 公网只读 Demo、真实封面缓存、视频与交付 review | 权限/隐私/数据许可证复核 |
