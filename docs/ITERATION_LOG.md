# v0.2 Iteration Log

This document is chronological evidence, not a retrospective rewrite. Each Gate records
its decision, commands, result, failure and fix before the corresponding commit is created.

## 2026-09-01 21:16 +08:00 - G0 baseline and contract freeze

- Branch: `feat/v0.2-bonus`, based on `1b0d21b`.
- Local environment: Windows 10 10.0.19045 64-bit, Intel Core i5-11300H
  (4 cores/8 logical processors), Python 3.13.5, uv 0.9.30.
- Baseline commands: `uv run pytest -q` and `uv run ruff check app recsys tests`.
- Baseline result: 23 tests passed; Ruff passed. The only pytest warning is the upstream
  Starlette `TestClient` deprecation notice.
- Scope frozen: Item-Item BM25 CF and fixed RRF experiment, Dashboard windows/trends,
  GitHub Actions CI, and complete process evidence. No v0.2 video will be recorded.
- Compatibility decision: v0.1 manifests omit the new fields, so defaults must preserve
  `serving_policy=als`, `retrievers=[als]`, and successful loading of the old bundle.
- Dashboard decision: `1h`, `6h`, `24h`, and `all` use one shared UTC boundary across
  overview, feed diagnostics, hot items, feed shares, and trends. Catalog/model counters
  remain global because they are state rather than activity.

### Exploratory validation evidence

The following values came from a read-only validation exploration before implementation.
They are not formal test results and cannot be used as a release claim.

| Candidate | Recall@20 | NDCG@20 | Coverage@20 |
|---|---:|---:|---:|
| ALS-64 | 0.06826 | 0.02651 | 0.20661 |
| ItemCF Cosine | 0.07200 | 0.03059 | 0.94724 |
| ItemCF BM25 | 0.08328 | 0.03714 | 0.95744 |
| ALS + ItemCF equal RRF | 0.08820 | 0.03593 | 0.95640 |

- Selection rule: highest validation overall NDCG@20. Test remains unopened for the new
  candidates until the serving policy is frozen and retrained on train+validation.
- Known limitation: collaborative ItemCF cannot retrieve a target with no interaction in
  the serving matrix; it is not presented as a pure-item cold-start solution.

## Gate record template

Each subsequent entry must include:

- Local time, base commit and responsible Agent.
- Data version, split, configuration, seed, command, duration and machine/runtime.
- Validation/test metrics with overall and warm-item scopes clearly separated.
- Selected/rejected status and the decision reason.
- Artifact path, SHA256, model version and final commit SHA.
- Failure symptom, root cause, fix and verification command when a failure occurs.
- Browser screenshot paths or GitHub Actions run URL where applicable.

## 2026-09-01 21:40 +08:00 - G1 ItemCF, RRF and serving integration

- Responsible Agent: Offline subagent for `recsys/`; main Agent for public contracts,
  online source/reason mapping, bounded feedback integration and review.
- Data version: `764b7d14ce34`; 50,000 users, 19,220 items, 359,708 interactions.
- Split: 259,708 train, 50,000 validation and 50,000 test interactions. Validation has
  49,156 warm targets; test has 49,424 warm targets.
- Command: `uv run microlens train`; configuration `configs/als.toml`; seed 42; ALS
  factors 32/64; ItemCF K=100; RRF K=60; evaluation K=20.
- Timing evidence: the exact command start time was not captured, so no full wall-clock is
  claimed. Artifact serialization started at 21:40:41.223913 and `manifest.json` plus
  `latest.json` finished at 21:40:54.140861, a verifiable 12.917-second publish stage.
  This is recorded as a process miss; future formal commands must use a timestamped wrapper.
- Validation overall NDCG@20: ALS-64 `0.026506`, Cosine `0.030595`, BM25 `0.037136`,
  RRF `0.035926`. BM25 was frozen before the formal test evaluation.
- Test overall Recall/NDCG/Coverage@20: ALS `0.061540/0.023592/0.212019`, Cosine
  `0.066920/0.027464/0.963007`, selected BM25 `0.078220/0.033383/0.981998`, and RRF
  `0.080540/0.032154/0.981946`.
- Decision: publish BM25. RRF improved Recall but reduced the primary selection metric, so
  it remains a measured rejected candidate rather than the online default.
- Artifact: `artifacts/hybrid-bm25-f64-764b7d14ce34-20260901T134041223913Z`;
  model version has the same directory name. Eight artifact-file SHA256 values are recorded
  in its `checksums.json`; the Git commit SHA is added by the next log entry after commit.
- Verification: `uv run pytest -q` -> 30 passed; `uv run ruff check .` -> passed;
  `uv run microlens offline-smoke` -> passed; model reload, known-user filtering and
  unknown-user popularity fallback -> passed.
- Failure and fix: `implicit.ItemItemRecommender` expands N internally when `filter_items`
  is present, which could exceed the requested limit. Both the offline helper and Bundle
  output now hard-truncate after seen/cold/excluded filtering; a regression test covers all
  four serving policies.
- Known warnings: implicit converts an internal COO matrix to CSR; FastAPI TestClient emits
  an upstream httpx2 migration warning. Neither changes results or test status.
- Known limitation: all four collaborative policies still miss the 576 pure-cold test
  targets; ItemCF is not described as a pure-item cold-start solution.
