# 离线评估与 Badcase

## 数据与协议

- 数据版本：`764b7d14ce34`，50,000 用户、19,220 内容、359,708 交互；缺失标题/统计均为 0，重复 user-item 为 0。
- 逐用户 leave-last-two：259,708 train、50,000 validation、50,000 test。官方只有用户内序列，绝对 timestamp 不可用。
- 每个评估用户只有 1 个 held-out target。推荐列表过滤训练历史和冷内容，`K=20`。
- Recall@20 是 target 是否进入 Top-20 的用户平均；NDCG@20 按命中位置做 `1/log2(rank+2)`；Coverage@20 是所有推荐过的不同内容数 / 19,220。
- Validation 固定比较 ALS factors 32/64、Cosine ItemCF、BM25 ItemCF 和
  ALS+BM25 等权 RRF；选择指标为 overall NDCG@20。选型冻结后用 train+validation 重训，
  所有冻结方案在同一次正式 test 运行中评估。Random 与 Popularity 使用相同过滤和口径。
- ItemCF 的 BM25 是交互共现矩阵加权，不是标题文本 BM25；所有协同方案都过滤 serving
  matrix 中无交互的纯冷 item。

## 结果

Validation 先在 ALS 内选择 64 因子，再比较四种 serving policy：

| Validation 策略 | Recall@20 | NDCG@20 | Coverage@20 | 选型状态 |
|---|---:|---:|---:|---|
| ALS-64 | 0.06826 | 0.026506 | 0.206608 | 未选 |
| Cosine ItemCF | 0.07200 | 0.030595 | 0.947242 | 未选 |
| **BM25 ItemCF** | 0.08328 | **0.037136** | 0.957440 | **选为 serving policy** |
| ALS + BM25 RRF | **0.08820** | 0.035926 | 0.956400 | 未选 |

RRF 的 Recall 更高，但 NDCG 低于 BM25；由于主指标在查看 test 前已经冻结为 NDCG，不能为了
展示“多路融合”而改用 RRF。这个结果作为负实验保留。

| Test 模型 | Recall@20 | NDCG@20 | Coverage@20 |
|---|---:|---:|---:|
| Random | 0.00118 | 0.000422 | 0.987253 |
| Popularity | 0.00540 | 0.002140 | 0.002706 |
| ALS-64 | 0.06154 | 0.023592 | 0.212019 |
| Cosine ItemCF | 0.06692 | 0.027464 | 0.963007 |
| **BM25 ItemCF（线上默认）** | 0.07822 | **0.033383** | **0.981998** |
| ALS + BM25 RRF | **0.08054** | 0.032154 | 0.981946 |

发布 BM25 相比同一 test 口径的 ALS，Recall@20 从 `0.06154` 增至 `0.07822`，NDCG@20
从 `0.023592` 增至 `0.033383`，Coverage@20 从 `0.212019` 增至 `0.981998`。这些是
离线 held-out 结果，不代表线上因果提升。Random 覆盖率也很高但相关性接近随机，说明 Coverage
不能单独作为选型指标；Popularity 仅覆盖约 0.27% 目录，暴露明显头部偏置。

Test 中 49,424/50,000 target 在 train+validation 为 warm；BM25 warm-target
Recall@20=`0.079132`、NDCG@20=`0.033772`。576 个纯冷 target 对 ALS 和 ItemCF 都没有
协同信号，按协议失败并计入 overall；v0.2 不把 ItemCF 宣称为纯冷启动方案。

## Badcase

完整 miss 明细由训练生成在 artifact 的 `badcases.csv`，含用户、target 是否 warm、最近 10 条历史和推荐列表。例如：

| user | target | warm | 近期历史长度 | 观察 |
|---:|---:|---|---:|---|
| 1 | 1707 | 是 | 4 | 历史很短，协同信号不足；Top-20 偏向共现更强的内容 |
| 2 | 5299 | 是 | 6 | target 已有因子但未进入 Top-20，可能是相似用户覆盖不足 |
| 3 | 18348 | 是 | 4 | 短序列导致用户向量不稳定，推荐集中在全局共现头部 |

主要错误来源仍是短历史、稀疏长尾 target 和纯冷 target。BM25 扩大了协同覆盖，但用户 1、2、3
等短序列 Badcase 的 held-out target 仍未进入 Top-20。下一轮真正针对 576 个纯冷 target 时，
应使用只依赖静态元数据的标题 TF-IDF/Embedding 召回，并继续只在 validation 调权。

## 可复现命令与产物

```powershell
uv run microlens download
uv run microlens prepare
uv run microlens train
```

v0.2 artifact 包含 `als_model.npz`、`cosine_model.npz`、`bm25_model.npz`、
`serving_user_items.npz`、mappings、Popularity、`metrics.json`、`badcases.csv`、
`checksums.json` 和 `manifest.json`。正式模型版本为
`hybrid-bm25-f64-764b7d14ce34-20260901T134041223913Z`。Release asset 为
`microlens-recsys-bundle-v0.2.0-bm25.zip`，36,866,255 bytes，SHA256：
`69479A2F04E90D133E9CE13579792C7781A909F5266E0447927FC331A8E9F7B6`。

正式 `uv run microlens train` 没有记录完整命令开始时间，因此不提供估算耗时；可证实的
artifact 目录创建到 `latest.json` 指针落盘阶段为 12.9172189 秒。该过程缺口和后续修正规则见
`docs/ITERATION_LOG.md`。
