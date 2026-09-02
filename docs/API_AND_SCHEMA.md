# API 与数据库

服务默认 `http://127.0.0.1:8000`，交互式 OpenAPI 位于 `/docs`。除登录和 health 外，身份均来自签名 session cookie；请求体不能指定 user ID。

## 核心接口

| 方法与路径 | 权限 | 作用 |
|---|---|---|
| `GET /api/health` | 公开 | 进程健康检查 |
| `POST /api/auth/login` | 公开 | 用户名/密码登录，写 HttpOnly session |
| `POST /api/auth/logout` | 登录 | 清除 session |
| `GET /api/auth/me` | 登录 | 当前用户，不接收目标 user ID |
| `GET /api/feeds/{personalized|popular|explore}` | 用户 | `page>=1`、`1<=page_size<=50`，返回 request_id、模型版本和候选 |
| `POST /api/events` | 用户 | 上报 click/like/not_interested；impression 由服务端自动写入 |
| `GET /api/profile/me` | 用户 | 当前用户画像版本和事件计数 |
| `GET /api/items/{item_id}` | 用户 | 读取在线内容；下线或不存在均为 404 |
| `GET /api/admin/dashboard?window=24h` | 管理员 | 时间范围概览、流占比、热门内容 |
| `GET /api/admin/feeds/diagnostics?window=24h` | 管理员 | 同范围各 Feed 请求/曝光/点击/CTR |
| `GET /api/admin/dashboard/trends?window=24h` | 管理员 | 补零后的请求/曝光/点击/点赞/CTR 趋势 |
| `GET /api/admin/users/{user_id}/debug` | 管理员 | 画像、近期行为/请求和最近曝光内容 |
| `GET /api/admin/request-traces?window=24h&limit=10` | 管理员 | 最近请求、Feed、模型、延迟、fallback 与行为计数 |
| `GET /api/admin/requests/{request_id}` | 管理员 | 单请求及其 exposure/event 链路 |
| `GET /api/admin/observability?window=24h` | 管理员 | nearest-rank P50/P95/max、fallback 与分组告警 |
| `GET /api/admin/models` | 管理员 | 扫描 artifact 并同步模型投影，返回候选/发布状态 |
| `GET /api/admin/models/runtime` | 管理员 | 内存/pointer current、previous、状态与最近校验 |
| `GET /api/admin/models/current/evaluation` | 管理员 | 当前 artifact 的 selection、validation 与 formal test |
| `POST /api/admin/models/{version}/publish` | 管理员 | 严格校验、warm-up、原子 pointer 与单 worker 热切换 |
| `POST /api/admin/models/rollback` | 管理员 | 严格校验 previous 后交换 current/previous |
| `GET /api/admin/contents` | 管理员 | `q` 按 ID/标题搜索，`status` 筛选 |
| `POST /api/admin/operations/{force|offline|restore}` | 管理员 | 运营操作并写审计 |
| `GET /api/admin/operations` | 管理员 | 倒序审计记录 |

Feed 响应示例：

```json
{
  "request_id": "uuid",
  "feed_type": "personalized",
  "model_version": "hybrid-bm25-f64-...",
  "page": 1,
  "page_size": 12,
  "has_more": true,
  "fallback_reason": null,
  "items": [{
    "item_id": 14377,
    "title": "...",
    "position": 1,
    "source": "itemcf_bm25",
    "score": 0.91,
    "reason": "Item-Item BM25 共现召回与实时行为重排",
    "likes": 10,
    "views": 100
  }]
}
```

个性化候选 `source` 取决于 manifest 的 validation 选型，可为 `als`、
`itemcf_cosine`、`itemcf_bm25`、`rrf:als+itemcf` 或
`hybrid:bm25+title_tfidf`。v0.3 正式 artifact 仍选择 `itemcf_bm25`；RRF 与内容 Hybrid
只作为已评估但未发布的候选，不会在 API 中冒充线上版本。

Dashboard `window` 只接受 `1h`、`6h`、`24h`、`all`，默认 `24h`，非法值返回
422。时间范围使用 UTC 半开区间 `[window_start, window_end)`，JSON 时间戳携带显式 UTC
offset（`Z`）；全局状态字段不随窗口变化。固定窗口 `1h/6h/24h` 分别按
`5/30/60` 分钟返回 `12/12/24` 个补零桶，并锚定返回的 `window_start`；`all` 返回
`window_start=null`、`bucket_minutes=1440`，从最早记录所在的 UTC 日开始。
趋势响应示例：

```json
{
  "window": "6h",
  "window_start": "2026-09-01T08:00:00Z",
  "window_end": "2026-09-01T14:00:00Z",
  "bucket_minutes": 30,
  "points": [{
    "bucket_start": "2026-09-01T08:00:00Z",
    "requests": 3,
    "exposures": 36,
    "clicks": 1,
    "likes": 0,
    "ctr": 0.0277777778
  }]
}
```

## 模型运行、发布与评估

`runtime.status` 为 `ready|recovered|fallback`，校验状态为
`ok|legacy_unverified|error`。`current`/`previous` 路径均为 artifact root 下的相对路径；
服务只支持单 Uvicorn worker。pointer 与内存 manager 是运行权威，`model_versions` 是
Dashboard 投影。投影提交失败时模型切换不会被回滚，响应仍返回真实 runtime，并带非空
`projection_warning`；后续启动或 `GET /api/admin/models` 可修复投影。

Publish/rollback 的状态码：版本目录不存在 404；路径非法、manifest/version 不一致、缺文件、
checksum/维度/warm-up/pointer 失败、无 previous 均为 409。旧 bundle 可以启动；若
`manifest.json` 没有被 SHA256 覆盖，则标记 `legacy_unverified`，不得经管理 API 重新激活。

评估接口返回 `selection_metric=validation.overall.ndcg_at_20`、selected policy，以及每个策略的
overall/warm/pure-cold 指标。未进入冻结 formal Test 的策略，其 `test` 必须是 `null`，前端显示
“未正式测试”，不能用空对象或 0 冒充测试结果。

## 请求链路与观测

`request-traces` 支持同一 Dashboard `window`、可选 `feed_type`、`limit=1..50`。兼容别名
`GET /api/admin/requests` 不出现在 OpenAPI，新代码使用 canonical endpoint。每条请求的
click/like/not_interested 均以 exposures 为共同分母；单请求详情返回有序 exposure 与按时间排序
event，不把三种行为画成严格漏斗。

`observability` 使用 nearest-rank 百分位。样本少于 20 时只返回“样本不足”，不判断健康；达到
20 后，fallback rate `>=5%` 或 P95 `>=500ms` 产生 warning。`feed_build_latency_ms` 从 Feed
构建开始计到响应 item、trace 子记录构造并 flush，不含 transaction commit 和 HTTP 序列化，
不能称为完整端到端延迟。告警仅在 Dashboard 展示，不发送短信、邮件或 webhook。

事件请求必须引用该用户拥有的曝光：

```json
{
  "event_id": "独立 UUID",
  "request_id": "Feed 的 UUID",
  "item_id": 14377,
  "event_type": "like",
  "client_timestamp": "2026-09-01T09:00:00Z"
}
```

强推请求示例：

```json
{
  "item_id": 40,
  "scope": "user",
  "scope_value": "alice",
  "feed_type": "personalized",
  "reason": "新内容冷启动",
  "starts_at": "2026-09-01T09:00:00Z",
  "ends_at": "2026-09-02T09:00:00Z"
}
```

典型错误：未登录 401、普通用户访问管理接口 403、曝光不属于当前用户 404、模型版本目录不存在
404、模型校验/发布/回滚冲突 409、重复 event_id 的不同 payload 409、强推离线内容 409、
无效运营时窗、Dashboard window、feed_type 或 limit 422。

## 核心表

| 表 | 主键/关键索引 | 关键字段与职责 |
|---|---|---|
| `users` | `id`；username 唯一；source_user_id 索引 | 密码哈希、role、官方用户映射、profile_version |
| `items` | `id`；status/train_interactions 索引 | 标题、likes、views、online/offline、更新时间 |
| `recommendation_requests` | UUID `id`；user/feed/time 索引 | Feed、模型版本、页码、延迟、fallback 原因 |
| `exposures` | 自增 id；`request_id+item_id` 唯一 | user/item/position/source/score/reason/time |
| `events` | 自增 id；event_id 唯一；user/time 索引 | request/user/item/position/type/source/client/server time |
| `operations` | 自增 id；admin/item/type 索引 | scope、feed、时窗、原因、active、前后状态、时间 |
| `model_versions` | 字符串 version | status、data_version、artifact_path、metrics、训练/发布时间 |

外键在 SQLite connection 建立时强制开启。曝光父 request 先 flush 再写 exposure/event；行为写入和 profile_version 递增同事务。`events.event_id` 提供幂等，`exposures(request_id,item_id)` 防止一次响应重复内容。

## 在线事件到后续训练

当前实时事件立即更新轻量画像并影响在线重排；SQLite 保留带 request/item/position/source/timestamp 的训练所需字段。下一周期可按 `created_at` 增量导出正/负反馈并与官方历史按用户合并。MVP 尚未自动把线上事件触发 ALS 重训，避免把在线反馈与离线官方时序静默混在一起。
