# 离线评估与 Badcase

## 数据来源与切分协议

- 数据来自官方 [MicroLens](https://github.com/westlake-repl/MicroLens) 的 MicroLens-50K 三个文本文件：
  `MicroLens-50k_pairs.tsv`、`MicroLens-50k_titles.csv` 和
  `MicroLens-50k_likes_and_views.txt`。下载脚本记录每个源文件的 URL、字节数和 SHA256；原始数据、
  处理数据和封面包均不进入 Git。
- 正式数据版本为 `764b7d14ce34`：50,000 用户、19,220 内容、359,708 条隐式交互；缺失标题、
  缺失点赞/播放统计和重复 user-item 均为 0。
- 逐用户按官方 pairs 文件中的顺序执行 leave-last-two：259,708 条 train、50,000 条 validation、
  50,000 条 test。Validation 的模型和候选统计只拟合 train；确定策略后，正式 Test 模型只拟合
  train+validation。
- 官方文件没有可信绝对时间，只有用户内 `sequence_position`。因此本项目能证明每个用户
  `train < validation < test`，不能声称做了全站绝对时间切分；导出的 timestamp 只是明确标注的
  合成序号，不用于时间衰减或漂移结论。
- 这是正反馈隐式数据。未观测 user-item 被视为 unknown，不伪造显式负标签；Random、Popularity、
  ALS、ItemCF、RRF 和内容候选均使用同一 held-out target、seen 过滤和目录分母进行 Top-K 评估。
  若后续训练 pointwise 排序器，必须另行冻结时间一致的负采样策略。

## 配置与复现

正式配置为 `configs/als.toml`：随机种子 42，ALS factors 32/64、iterations 12、
regularization 0.05、alpha 20；ItemCF 邻居数 100，RRF `k=60`；标题 TF-IDF 比较 Word `(1,2)`
和 `char_wb (3,5)`，`min_df=2`、`max_features=50000`、sublinear TF、L2、float32，用户内容画像
只聚合最近 10 条拟合历史，cold quota 比较 1/2/3/5。

```powershell
uv sync --frozen --python 3.11
uv run --python 3.11 python -m recsys.cli download
uv run --python 3.11 python -m recsys.cli prepare
$env:OPENBLAS_NUM_THREADS='1'
uv run --python 3.11 python -m recsys.cli train --processed-path data/processed `
  --artifact-root artifacts --config configs/als.toml
```

正式训练环境：Windows 10、Intel Core i5-11300H、Python 3.13.5、uv 0.9.30、
scikit-learn 1.9.0、implicit 0.7.3、NumPy 2.5.2、SciPy 1.18.1。墙钟耗时 10 分 23 秒。
`train` 默认生成 candidate，不覆盖当前线上指针；只有首次 bootstrap 才应显式使用 `--activate`。

## 指标口径

- 每个评估用户只有 1 个 held-out target，`K=20`。
- Recall@20 是 target 是否进入 Top-20 的用户平均。
- NDCG@20 在单 target 口径下按命中位置计算 `1/log2(rank+2)`，越靠前越高。
- Coverage@20 是所有用户推荐列表中不同内容数除以完整 19,220 内容目录。
- `warm` 表示 target 在当前拟合矩阵中出现过；`pure-cold` 表示 target 对当前拟合矩阵是零交互内容。
  pure-cold Coverage 只表示推荐列表覆盖了多少目录内容，不能解释为冷内容 target 命中率。
- 唯一正式选型指标是 validation overall NDCG@20；切片指标用于解释取舍，不能覆盖主指标。

## Validation baseline 与协同模型

以下结果全部来自 validation，未使用 Test 调参：

| Candidate | Overall Recall@20 | Overall NDCG@20 | Overall Coverage@20 | 结论 |
|---|---:|---:|---:|---|
| Random | 0.000880 | 0.000293 | 0.962019 | 高覆盖但相关性接近随机 |
| Popularity | 0.007180 | 0.002790 | 0.002862 | 明显头部集中 |
| ALS-32 | 0.059320 | 0.022645 | 0.128668 | 未选 |
| ALS-64 | 0.068260 | 0.026506 | 0.206608 | ALS 内部胜出 |
| Cosine ItemCF | 0.072000 | 0.030595 | 0.947242 | 未选 |
| **BM25 ItemCF** | **0.083280** | **0.037136** | 0.957440 | **最终 serving policy** |
| ALS + BM25 RRF | 0.088200 | 0.035926 | 0.956400 | Recall 更高但主指标更低 |

这里的 BM25 是对 user-item 共现矩阵做 ItemCF 权重，不是标题文本 BM25。RRF 的 Recall 更高，
但 NDCG 低于 BM25；主指标在查看 Test 前已经冻结，不能为了展示更复杂的融合而改选 RRF。

## Validation 标题 TF-IDF 与 cold quota 消融

quota 0 不使用标题模型，因此 Word/q0 和 `char_wb`/q0 是同一个 BM25 control，而不是两次独立
训练。其余行只允许 TF-IDF 补充拟合矩阵中的 pure-cold item，并在 Top-20 尾部保留固定 quota。

| Analyzer / quota | Overall R@20 | Overall N@20 | Overall C@20 | Warm R@20 | Warm N@20 | Warm C@20 | Pure-cold R@20 | Pure-cold N@20 | Pure-cold C@20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Word / 0 (BM25 control) | 0.083280 | 0.037136 | 0.957440 | 0.084710 | 0.037773 | 0.957284 | 0.000000 | 0.000000 | 0.511290 |
| `char_wb` / 0 (same control) | 0.083280 | 0.037136 | 0.957440 | 0.084710 | 0.037773 | 0.957284 | 0.000000 | 0.000000 | 0.511290 |
| Word / 1 | 0.082560 | 0.036972 | 0.994797 | 0.083042 | 0.037393 | 0.994589 | 0.054502 | 0.012409 | 0.513736 |
| `char_wb` / 1 | 0.082360 | 0.036926 | 0.993913 | 0.083042 | 0.037393 | 0.993600 | 0.042654 | 0.009711 | 0.512747 |
| Word / 2 | 0.080900 | 0.036590 | 0.994433 | 0.081129 | 0.036951 | 0.994277 | 0.067536 | 0.015578 | 0.503850 |
| `char_wb` / 2 | 0.080900 | 0.036589 | 0.994173 | 0.081129 | 0.036951 | 0.994017 | 0.067536 | 0.015534 | 0.501821 |
| Word / 3 | 0.079040 | 0.036155 | 0.993861 | 0.078973 | 0.036443 | 0.993652 | 0.082938 | 0.019353 | 0.491207 |
| `char_wb` / 3 | 0.078940 | 0.036131 | 0.993809 | 0.078973 | 0.036443 | 0.993600 | 0.077014 | 0.017956 | 0.487929 |
| Word / 5 | 0.074660 | 0.035105 | 0.991779 | 0.074416 | 0.035340 | 0.991571 | 0.088863 | 0.021452 | 0.456868 |
| `char_wb` / 5 | 0.074720 | 0.035117 | 0.991831 | 0.074416 | 0.035340 | 0.991623 | **0.092417** | **0.022158** | 0.454631 |

Validation 有 50,000 个 target，其中 warm 49,156、pure-cold 844。最佳内容候选 Word/q1 将
pure-cold Recall/NDCG@20 提高到 `0.054502/0.012409`，但 overall NDCG@20=`0.036972`，仍低于
BM25 的 `0.037136`。`char_wb`/q5 的 pure-cold 指标最高，但 overall NDCG 进一步降到
`0.035117`。这是有价值的负向取舍实验，不是“内容召回已上线”或“线上效果提升”的证据。

## 冻结后的 Formal Test

Validation 完成选型后，用 train+validation 重训并只执行一次正式 Test。v0.3
`metrics.test` 只有冻结的 BM25 一个键；未入选候选没有 Test 数值，避免用 Test 反向挑模型。

| Slice | Targets | Recall@20 | NDCG@20 | Coverage@20 |
|---|---:|---:|---:|---:|
| Overall | 50,000 | 0.078220 | 0.033383 | 0.981998 |
| Warm | 49,424 | 0.079132 | 0.033772 | 0.981946 |
| Pure-cold | 576 | 0.000000 | 0.000000 | 0.398439 |

正式 Test 中 BM25 命中 3,911 个用户，未命中 46,089 个用户。pure-cold Recall/NDCG 仍为 0，
因此不能声称 validation 上的标题信号已经解决正式 Test 冷启动，也不能把 pure-cold Coverage
解释为命中率。所有结果都是离线 held-out 指标，不代表线上因果收益。

## 匿名 Badcase 聚合

完整本地 `badcases.csv` 含 46,089 条 miss，但包含用户、target、近期历史和推荐 item ID，不进入
Git 或公开 Release。公开报告只保留以下匿名聚合：

| 匿名分组 | Miss 数 | 占全部 miss |
|---|---:|---:|
| Warm target | 45,513 | 98.75% |
| Pure-cold target | 576 | 1.25% |
| 最近历史快照长度 <= 4 | 19,002 | 41.23% |
| 最近历史快照长度 5-6 | 15,452 | 33.53% |
| 最近历史快照长度 7-10 | 11,635 | 25.24% |

历史长度统计只针对 artifact 中保存的最近 10 条调试快照，不是用户完整历史长度。可验证的主要
问题包括：pure-cold target 缺少协同信号；短历史画像提供的个性化证据有限；扩大 cold quota
虽然改善冷切片，却会挤占 warm 候选并降低 overall 排序质量。下一步应继续在 validation 上验证
更好的内容表示与配额策略，而不是查看 Test 后调参。

## Artifact 与公开发布边界

本地完整 artifact：
`hybrid-bm25-f64-764b7d14ce34-20260901T173618808761Z`，创建时间
`2026-09-01T17:36:18.808761Z`，共 66,730,787 bytes。11 个 manifest 声明文件的 SHA256
独立回验全部匹配；`checksums.json` SHA256 为
`c2a7e56f285f7eae486af9dfba10a7315c846ad6e9dd39226ba00cecf821f28a`。

完整 runtime artifact 只用于本地/私有验收。公开最小模型包实行 allowlist，只含
`bm25_model.npz` 和不含 user ID 的 `item_ids.json`；明确排除 `serving_user_items.npz`、
`mappings.json` 中的 `user_ids`、`badcases.csv`、标题向量与内容配置。机器可读范围、文件哈希、
官方来源和重建命令见 `reports/model_release_manifest_v0.3.0.json`。模型文件不是不可复现的孤立
结果：源码、锁文件、配置、官方数据下载/处理脚本、完整评估协议和重建命令均随仓库提交。
仓库中的 release manifest 记录外层 ZIP 的大小与 SHA256；ZIP 内另有去除私有路径和外层哈希的
`model_manifest.json`，只描述三个包成员及其哈希，避免清单包含自身 archive hash 的循环依赖。
