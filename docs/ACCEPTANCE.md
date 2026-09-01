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
| 工程启动 | 干净环境按 README 启动，无真实密钥 | 全新 clone smoke | TODO |
| 文档视频 | README、API/DB、系统设计、完成度、3-5 分钟视频 | 04:08 Release 视频 + 抽帧 | PASS |

## 不接受项防线

- 推荐结果来自真实处理数据和训练产物，不使用前端固定 JSON。
- `user_id` 从服务端 session 推导，不能读取其他用户画像、行为或管理接口。
- Dashboard 只查询数据库聚合，不在页面写固定数字。
- 下线过滤位于服务端推荐流水线的最后权威步骤。
- 原始 MicroLens 数据、题目 PDF、真实密钥和本地数据库不提交到仓库。
