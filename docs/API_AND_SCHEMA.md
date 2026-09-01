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
| `GET /api/admin/requests/{request_id}` | 管理员 | 单请求及其 exposure/event 链路 |
| `GET /api/admin/models` | 管理员 | 模型版本、数据版本、指标与状态 |
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
`itemcf_cosine`、`itemcf_bm25` 或 `rrf:als+itemcf`。v0.2 正式 artifact 选择
`itemcf_bm25`；RRF 只作为已评估但未发布的候选，不会在 API 中冒充线上版本。

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

典型错误：未登录 401、普通用户访问管理接口 403、曝光不属于当前用户 404、重复 event_id
的不同 payload 409、强推离线内容 409、无效运营时窗或 Dashboard window 422。

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
