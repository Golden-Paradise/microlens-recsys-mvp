# 离线评估与 Badcase

## 数据与协议

- 数据版本：`764b7d14ce34`，50,000 用户、19,220 内容、359,708 交互；缺失标题/统计均为 0，重复 user-item 为 0。
- 逐用户 leave-last-two：259,708 train、50,000 validation、50,000 test。官方只有用户内序列，绝对 timestamp 不可用。
- 每个评估用户只有 1 个 held-out target。推荐列表过滤训练历史和冷内容，`K=20`。
- Recall@20 是 target 是否进入 Top-20 的用户平均；NDCG@20 按命中位置做 `1/log2(rank+2)`；Coverage@20 是所有推荐过的不同内容数 / 19,220。
- 先以 validation overall NDCG@20 在 ALS factors 32/64 中选型，再用 train+validation 重训，test 只评估一次。Random 与 Popularity 使用同样的已看过滤和口径。

## 结果

Validation：64 因子 ALS NDCG@20=`0.026506`，高于 32 因子的 `0.022645`，因此正式选择 64 因子。

| Test 模型 | Recall@20 | NDCG@20 | Coverage@20 |
|---|---:|---:|---:|
| Random | 0.00118 | 0.000422 | 0.987253 |
| Popularity | 0.00540 | 0.002140 | 0.002706 |
| ALS-64 | **0.06154** | **0.023592** | 0.212019 |

ALS Recall 是 Popularity 的约 11.4 倍，说明用户协同信号有效；Random 的覆盖率最高但相关性接近随机，不能把 Coverage 单独当成效果。Popularity 只覆盖约 0.27% 目录，暴露明显头部偏置。Test 中 49,424/50,000 target 在 train+validation 为 warm；ALS warm-target Recall@20=`0.062257`、NDCG@20=`0.023867`。576 个纯冷 target 无协同因子，按协议会失败并计入 overall，这一差异被显式保留。

## Badcase

完整 miss 明细由训练生成在 artifact 的 `badcases.csv`，含用户、target 是否 warm、最近 10 条历史和推荐列表。例如：

| user | target | warm | 近期历史长度 | 观察 |
|---:|---:|---|---:|---|
| 1 | 1707 | 是 | 4 | 历史很短，协同信号不足；Top-20 偏向共现更强的内容 |
| 2 | 5299 | 是 | 6 | target 已有因子但未进入 Top-20，可能是相似用户覆盖不足 |
| 3 | 18348 | 是 | 4 | 短序列导致用户向量不稳定，推荐集中在全局共现头部 |

主要错误来源：短历史、长尾 target 的交互稀疏、纯冷 target 无因子，以及单阶段 ALS 只使用 ID 协同信息。下一步会先为 cold target 加标题 embedding/item-item 召回，再在 validation 固定口径比较多路融合；不会直接用 test 调权。

## 可复现命令与产物

```powershell
uv run microlens download
uv run microlens prepare
uv run microlens train
```

每个 artifact 包含 `als_model.npz`、`serving_user_items.npz`、mappings、Popularity、`metrics.json`、`badcases.csv`、`checksums.json` 和 `manifest.json`。Release bundle SHA256 为 `12900F9FD1894018134493876A9404D8895FB8F28F5296D0B0EDDFF2F9E7E229`。
