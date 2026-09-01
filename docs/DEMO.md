# 3-5 分钟演示

> 版本边界：本视频录制于 v0.1，覆盖 PDF 全部必选旅程。v0.2 新增的 ItemCF、时间趋势和
> GitHub Actions 由正式指标、自动化测试、v0.2 Release 和截图证明，暂不重复录制；
> 待 v0.3 候选功能冻结后统一更新视频。

## 视频链接

私有 GitHub Release 直链：<https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/download/v0.1.0-als/microlens-recsys-mvp-demo.webm>

- 时长：`04:08`；分辨率：`1280x720`；25 fps；VP8/WebM；12,412,150 bytes。
- SHA256：`254E4EAFE0BAA2F464D20BAAB0E5926C3642006E09785C87538D495452B28CA4`。
- 已抽查开场、Bob、Dashboard、强推、下线、恢复和结尾指标时间点，画面非黑屏且文字可读。

## 约 4 分钟分镜

| 时间 | 操作 | 必须口述/展示的证据 |
|---|---|---|
| 00:00-00:35 | 展示仓库 README，运行 `uv sync --frozen` 与 `uv run microlens smoke` | 干净环境、smoke 不依赖本机数据，offline+online 均 ok |
| 00:35-01:20 | Alice 登录，切换三路 Feed，点赞一条并查看画像 | `als-f64` 模型版本、request_id、来源/分数、画像版本变化 |
| 01:20-01:50 | Bob 登录个性化 Feed | 与 Alice 列表不同，用户隔离；普通用户看不到管理接口 |
| 01:50-02:35 | Admin Dashboard | 请求/曝光/点击/CTR/点赞真实变化；用户调试与 request 链路 |
| 02:35-03:25 | 内容运营强推 #40，再下线并刷新 Feed/API，最后恢复 | 强推来源、下线最终权威、恢复与审计前后状态 |
| 03:25-04:00 | 展示全量 `prepare/train` 命令、metrics 与 Release | 50K 用户、留二切分、ALS/baseline、三项 Test 指标与 Badcase |

录制时不要展示 `.env` 的真实密钥、GitHub token、本机绝对个人目录或原始数据内容。公开视频前应将仓库设为 public 或单独授权面试官，并确认 Release 访问权限。
