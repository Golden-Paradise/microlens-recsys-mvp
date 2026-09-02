# Iteration Log

This document is chronological evidence, not a retrospective rewrite. Each Gate records
its decision, commands, result, failure and fix before the corresponding commit is created.

## v0.3 - Cold-start retrieval, reliable model publishing, and decision evidence

### 2026-09-02 - G0 baseline and contract freeze

- Branch: `feat/v0.3-coldstart-runtime`, based on clean `main@1039484` and matching
  `origin/main`.
- Local environment: Windows 10 10.0.19045 64-bit, Intel Core i5-11300H, Python 3.13.5,
  uv 0.9.30. The service and CI contract remain Python 3.11 compatible.
- Baseline commands: `uv run pytest -q` and `uv run ruff check app recsys tests`.
- Baseline result: 30 tests passed and Ruff passed. Existing warnings are the upstream
  Starlette TestClient deprecation and implicit's small synthetic COO-to-CSR conversions.
- Frozen scope: title TF-IDF pure-cold retrieval, validation-only quota selection, strict
  artifact validation, atomic single-worker activation/rollback, model evidence, recent
  request traces, and passive latency/fallback warnings.
- Compatibility: v0.1/v0.2 manifests default to no content retriever; the legacy flat
  `latest.json` pointer upgrades in memory to the v2 current/previous contract.
- Selection discipline: overall validation NDCG@20 remains authoritative. Pure-cold gains
  are reported separately and cannot force a serving-policy change. Formal test remains
  untouched until the analyzer and cold quota are frozen.
- G0 contract fixture freezes the runtime, evaluation, request trace, and observability JSON
  shapes before the offline, backend, and frontend implementations start.

### 2026-09-02 01:01 +08:00 - G1 title retrieval and validation integration

- Added Word `(1,2)` and `char_wb (3,5)` TF-IDF candidates with fixed `min_df=2`,
  `max_features=50000`, sublinear TF, L2 normalization and float32 sparse storage.
- The content profile uses the latest 10 interactions in `sequence_position` order while the
  full fit-split history remains authoritative for seen filtering. Only zero-interaction
  items in that fit split can enter the content ranking.
- Validation compares BM25 against tail quotas `0/1/2/3/5`; overall validation NDCG@20
  remains the only selection metric. Exact ties prefer the lower quota and then Word.
- Added explicit `pure_cold` beside the compatible `warm_item` metric. Formal test is not
  run at this Gate; the pipeline will evaluate only frozen BM25 and the selected candidate.
- Artifact changes: `title_tfidf_items.npz`, `content_config.json`, their SHA256 values,
  content selection metadata, and an atomically replaced v2 current/previous pointer. No
  vectorizer pickle is written.
- Review fix: static item ID indexes and cold candidate slices were changed to cached
  properties before official evaluation; rebuilding a 19,220-item map for every one of
  50,000 users would have hidden a severe full-data performance defect.
- Verification: 20 focused content/evaluation/offline/contract tests passed; the complete
  integrated tree later reached 61 tests with Ruff and Node syntax checks passing. G1 is
  committed before formal validation, so no exploratory metric is presented as final.

### 2026-09-02 01:05 +08:00 - G2 atomic model publishing and observability

- Replaced direct mutable engine access with one `ModelManager.snapshot()` at the start of
  each Feed request. Model loading and warm-up occur outside the short state lock, while a
  mutation lock serializes publish and rollback operations for the supported one-worker
  Uvicorn deployment.
- Strict publishing accepts only a version below the configured artifact root. It verifies
  the manifest/version match, checksum coverage and SHA256 values, ALS and CSR dimensions,
  content matrix rows, and the shared item mapping before changing serving state.
- Pointer writes use a same-directory temporary file, `flush`, `fsync`, and `os.replace`.
  Loading, warm-up, validation, or pointer-write failure leaves the last-known-good engine
  and pointer unchanged. Startup can recover the previous version or expose deterministic
  fallback when neither version is usable.
- Added admin runtime, publish, rollback, frozen-evaluation, request-trace, and observability
  APIs. Feed build latency is kept distinct from HTTP end-to-end latency. Nearest-rank
  P50/P95 and fallback warnings require at least 20 samples before thresholds apply.
- Compatibility: legacy flat pointers and bundles remain loadable at startup, but a bundle
  without complete checksums cannot be republished through the management API.
- Integration test: a newly trained synthetic content bundle must pass both the regular
  loader and `ModelManager` strict validation, then publish by its manifest version.
- Review failure/fix: the first API adapter inferred 404 from the word `missing`, which also
  misclassified a present-but-incomplete artifact. A dedicated not-found exception now maps
  only an absent version directory to 404; manifest/checksum/file validation failures map to
  409 and leave the active model unchanged.
- Formal official-data validation/test is still untouched at this Gate.

### 2026-09-02 01:23 +08:00 - Cross-Gate review failures and invariant fixes

- Rawls review found that online Hybrid requested Top-100 from the bundle and then truncated
  to the display limit, which placed every cold quota item beyond the visible page. Hybrid
  now constructs its quota at the actual display K before behavior reordering; a regression
  test verifies the engine no longer requests 100 for this policy.
- Rawls also found CSV blank titles becoming the token `nan`, and content tie-breaking
  depending on TOML analyzer order. Titles are filled before string conversion, a real CSV
  blank-title row must remain a zero vector, and analyzer preference is explicitly ordered as
  Word then `char_wb` after the lower-quota rule.
- Huygens review found offline training still overwriting the runtime pointer. Training now
  creates a candidate by default; only explicit `--activate` bootstraps `latest.json`.
  Runtime publish/rollback remains authoritative, and the database model table is refreshed
  as a Dashboard projection from artifact manifests plus current runtime state.
- Huygens also found that v0.3 checksums omitted `manifest.json`, non-ALS item matrices lacked
  dimension checks, and startup deterministic fallback requests were counted as successful
  model requests. v0.3 checksum coverage now includes the manifest, Cosine/BM25 shapes must
  match the shared item mapping, and managed startup fallback records its reason in traces.
- Feed build latency now stops after recommendation response items and trace children are
  constructed and flushed, but before transaction commit and HTTP serialization. It is still
  not described as end-to-end HTTP latency.
- Review regression: 68 total tests passed; Ruff, Node syntax, and `git diff --check` passed.
  Existing warnings remain limited to upstream Starlette TestClient deprecation and implicit
  synthetic BLAS/COO conversion notices.

### 2026-09-02 01:25 +08:00 - G3 recommendation decision evidence

- Added unframed Dashboard section bands for runtime publish/rollback, validation-first model
  evidence, Feed build P50/P95/fallback health, and recent recommendation request traces.
- Model evidence shows overall, warm, and pure-cold slices. A missing Test payload is rendered
  as `not formally tested`, rather than implying that the policy is disabled. Validation and
  frozen Test remain visually and semantically distinct.
- Frontend review found that the first implementation paired health with the request list,
  while request details still lived in an older section above. The request section now uses a
  true desktop list/detail grid and a stacked mobile layout; selecting a keyboard-accessible
  request row renders ordered exposures plus the complete event timeline in place. Manual
  UUID lookup remains in the same detail pane.
- Frontend review also replaced the hidden `/api/admin/requests` list alias with the canonical
  `/api/admin/request-traces` endpoint, distinguishes fewer than 20 samples from a healthy
  no-alert state, and reports click/like/not-interested rates with exposures as their shared
  denominator instead of drawing a false strict funnel.
- Removed border, background, and shadow from the outer operations panels so metric tiles and
  tables are not nested inside decorative cards. Desktop table overflow and the 780/480 px
  stacking rules remain explicit.
- Static verification: UI/contract tests, the 68-test integrated suite, Ruff, Node syntax, and
  diff checks passed. Browser verification at 1280x720 and 390x844 is still pending and is not
  replaced by source-string assertions.

### 2026-09-02 01:26:26 +08:00 - G4 official evaluation started

- Data: official prepared version `764b7d14ce34`; split remains per-user leave-last-two with
  train-only validation fitting and train+validation formal-test fitting.
- Command: `$env:OPENBLAS_NUM_THREADS='1'; uv run microlens train --processed-path
  data/processed --artifact-root artifacts --config configs/als.toml`.
- Environment: Windows 10 10.0.19045, Intel Core i5-11300H, Python 3.13.5, uv 0.9.30,
  scikit-learn 1.9.0, implicit 0.7.3, NumPy 2.5.2, and SciPy 1.18.1.
- Frozen search space: Word `(1,2)` and `char_wb (3,5)` with cold quotas `1/2/3/5`, plus
  the quota-0 BM25 control. Highest overall validation NDCG@20 is authoritative; exact
  content ties prefer lower quota and then Word.
- The existing v0.2 pointer remains unchanged while training creates a candidate artifact.
  This command performs the one permitted official v0.3 formal Test evaluation only after
  validation selects and freezes the candidate.

### 2026-09-02 01:36:49 +08:00 - G4 official evaluation completed

- Wall time: 10 minutes 23 seconds. Candidate artifact:
  `hybrid-bm25-f64-764b7d14ce34-20260901T173618808761Z` (66,730,787 bytes).
- Validation decision: BM25 remained selected at overall NDCG@20 `0.03713558`. The best
  content candidate, Word with quota 1, reached `0.03697165`; it improved pure-cold
  Recall/NDCG to `0.05450237/0.01240857` but did not win the authoritative overall metric.
- The strongest pure-cold Recall was `0.09241706` from `char_wb` quota 5, with pure-cold
  NDCG `0.02215794`; its overall NDCG fell to `0.03511726`. This is retained as a useful
  negative trade-off experiment, not promoted as the serving policy.
- Target slices: validation `50,000` overall / `49,156` warm / `844` pure-cold; formal Test
  `50,000` overall / `49,424` warm / `576` pure-cold.
- Formal Test was run once after selection and contains only the frozen BM25 policy because
  the selected policy and baseline are identical: overall Recall/NDCG/Coverage@20
  `0.07822/0.03338273/0.98199792`; pure-cold Recall/NDCG remain `0/0`.
- Artifact policy is therefore `bm25`, not `bm25_content`. All 11 declared SHA256 entries,
  including `manifest.json`, matched. `checksums.json` SHA256 is
  `c2a7e56f285f7eae486af9dfba10a7315c846ad6e9dd39226ba00cecf821f28a`.
- The pre-existing v0.2 pointer still referenced
  `hybrid-bm25-f64-764b7d14ce34-20260901T134041223913Z`; no implicit activation occurred.

### 2026-09-02 - G4 local runtime and responsive browser acceptance

- Used a dedicated single-worker service at `127.0.0.1:8001` and isolated
  `var/app-v03.db`, leaving the existing port-8000 demo database untouched.
- Runtime sequence passed: v0.2 current -> v0.3 publish -> v0.2 rollback -> v0.3 rollback
  again. Each state reported checksum validation `ok`; the final v2 pointer holds v0.3 as
  current and v0.2 as previous.
- Generated 24 real Feed traces across alice/bob/carol and all three Feed types. Observed
  fallback rate was `0%`; local P50/P95 Feed build latency was `388.87/599.77 ms`, so the
  passive P95 warning fired after the 20-sample threshold. This is a local staged observation,
  not a general production SLA.
- Evidence-script failure/fix: PowerShell parsed `$feedType?page_size` as a variable named
  `feedType?`, producing `/feeds/=6` and no request rows. Bracing `${feedType}` and enabling
  stop-on-error produced the intended 24 valid traces.
- Browser acceptance used real 1280x720 and 390x844 viewports. Desktop had a true request
  list/detail grid, zero visible-overflow elements, and zero console warnings/errors. Mobile
  stacked to one column with no document overflow; the selected request retained keyboard
  button semantics and rendered its exposure/event timeline.
- Visual fix: the first mobile screenshot showed model registry columns squeezing IDs into
  one-character lines. The table now has a stable 720 px minimum width inside its own
  horizontal scroll container; this preserves readable columns without page-level overflow.
- Browser screenshots are stored under `reports/screenshots/v0.3/`. A long full-page capture
  showed browser stitching duplication, so viewport screenshots, DOM section counts, and
  overflow measurements are the authoritative visual evidence.

### 2026-09-02 05:38 +08:00 - G4 final reliability review and evidence freeze

- Backend review found that v0.2 bundles with a `checksums.json` but no checksum for
  `manifest.json` were still considered strictly publishable. Startup compatibility is now
  preserved as `legacy_unverified`, while every management-API publish or rollback requires
  the manifest itself to be SHA256-covered. A new regression fixture covers this exact v0.2
  compatibility boundary.
- The local v0.2 rollback candidate was hardened by adding its existing manifest SHA256 to
  its local checksum manifest; no model file, metric, manifest field, v0.2 Release asset, or
  Git history changed. The strict API sequence then passed again:
  `v0.3 -> hardened v0.2 -> rollback v0.3`, ending with validation `ok` and v0.3 current.
- Publish/rollback already make the pointer and in-memory manager authoritative before the
  SQLite Dashboard projection runs. Projection failure now rolls back only the failed DB
  session and returns the successful runtime with `projection_warning`, instead of returning
  a misleading HTTP 500 after the model has switched.
- CI smoke now trains two strict synthetic artifacts, bootstraps the first, publishes the
  second through the authenticated admin API, verifies a new Feed reports the second model
  version, rolls back to the first, and then continues the existing event/force/offline loop.
  It still uses only a temporary database, data directory and artifact root.
- Static assets now share a 12-character SHA256 content fingerprint computed from the final
  CSS and JavaScript, rather than a manually maintained version string. The final browser
  loaded `?v=2890e372edbd`; this fixed the stale generic model-table renderer observed during
  QA and is protected by a rendered-HTML test.
- Final browser measurements: desktop viewport `1280x720`, document width `1265`; mobile
  viewport `390x844`, document width `375`; both have no page-level horizontal overflow.
  The final selected request contains 6 impressions plus click, like and not-interested
  events. Browser console warning/error count remained zero.
- Authoritative final screenshots are the eight files under `reports/screenshots/v0.3/`:
  model registry and model decision at desktop/mobile sizes, desktop P95 warning, desktop
  list/detail trace, mobile detail, and mobile feedback timeline. Five stale, stitched, or
  pre-fix screenshots were removed before staging so no image exposes a local artifact path
  or contradicts the final renderer.
- Focused verification after these fixes: 33 model-manager/admin/UI tests passed, 5 contract
  tests passed, Ruff passed, Node syntax passed, `git diff --check` passed, and the upgraded
  offline+online runtime smoke passed. The full-suite result and G4 commit SHA are recorded
  immediately after the final Gate command completes.
- Final G4 command result: `OPENBLAS_NUM_THREADS=1 uv run pytest` passed all 70 tests in
  26.64 seconds; Ruff, Node syntax, `git diff --check`, and the upgraded synthetic
  offline+online publish/rollback smoke all passed. The 13 warnings are limited to the
  documented upstream Starlette TestClient deprecation and synthetic implicit COO-to-CSR
  conversions. G4 commit SHA is filled by the Git history itself after this entry is staged.

### 2026-09-02 23:23 +08:00 - Final delivery and redistribution audit

- Re-rendered and visually reviewed all eight pages of the assignment PDF. The eleven
  mandatory deliverables and six scoring dimensions were checked against the working tree;
  document requirements were treated as evidence, not as instructions overriding the direct
  delivery request.
- Re-ran the current local Gate: 70 tests passed with exit code 0. The 13 warnings are one
  upstream Starlette `TestClient` deprecation plus twelve implicit COO-to-CSR conversions.
  Ruff, Node syntax, the synthetic offline+online smoke and the final documentation diff
  check also passed.
- The historical v0.1 04:08 video was reclassified. It does not prove all five mandatory
  video journeys, especially a complete source/data-to-start sequence and actual
  training/evaluation commands with key output. It remains historical evidence, but must not
  be described as satisfying the final v0.3 video requirement.
- Delivery decision: make the source repository public before evaluator handoff so access
  does not depend on a private collaborator invitation. At this audit point the remote is
  still private; the visibility change is an external action and remains `PENDING`.
- The PDF forbids publicly repackaging the official MicroLens dataset. Raw and processed data
  remain excluded. Conservatively, the 77,575,939-byte full runtime bundle will also remain
  private because it contains user mappings, histories, badcases and other interaction-derived
  structures.
- The public model evidence package is limited to `bm25_model.npz`, `item_ids.json`, and
  `model_release_manifest_v0.3.0.json`, optionally with aggregate evaluation JSON. It excludes
  `serving_user_items`, every `user_ids` mapping, `badcases.csv`,
  `title_tfidf_items`/`content_config`, and all raw or processed data.
- This compact package is model evidence, not a standalone official-data runtime. The clean,
  no-data executable path is `microlens smoke`, which trains strict synthetic artifacts in a
  temporary directory and verifies publish, version switching, rollback, events and content
  operations.
- Current Gate status: local implementation, artifact validation, browser evidence and
  automation are complete. v0.3 branch push, current-SHA GitHub Actions, public visibility,
  compact Release publication and final-ref fresh clone are all `PENDING`; none may be marked
  PASS before the corresponding remote command finishes.

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
  factors 32/64; ItemCF neighbor K=100; RRF rank constant `rrf_k=60`; evaluation K=20.
- Timing evidence: the exact command start time was not captured, so no full wall-clock is
  claimed. The artifact directory was created at 13:40:41.2236423Z, manifest `created_at`
  is 13:40:41.223913Z, and `manifest.json` plus `latest.json` were last written at
  13:40:54.1408612Z. Directory creation through pointer write is a verifiable
  12.9172189-second artifact publication stage, not the full training duration. This is
  recorded as a process miss; future formal commands must use a timestamped wrapper.
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
- Verification: `uv run pytest -q` -> 29 passed; `uv run ruff check .` -> passed;
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

## 2026-09-01 22:00 +08:00 - G2 time-windowed Dashboard and trends

- Base commit: `e209da5`; responsible Agents: Online subagent for API/aggregation,
  Frontend subagent for templates/JS/CSS, main Agent for role semantics, browser QA and
  screenshots.
- API decision: `1h`, `6h`, `24h`, and `all` use UTC half-open intervals `[start, end)`.
  Their bucket sizes are 5, 30, 60 and 1,440 minutes. Fixed windows return 12, 12 and
  24 zero-filled buckets; `all` starts at the earliest recorded UTC day.
- Scope decision: users, offline items and current model are global state. Active users,
  requests, exposures, clicks, CTR, likes, feed shares, diagnostics and hot items use the
  selected activity window.
- Commands: `uv run pytest tests/test_online.py -q`, `uv run pytest tests/test_ui.py -q`,
  `uv run ruff check .`, and `node --check app/static/app.js`.
- Result: online tests 9 passed, UI tests 11 passed, full suite 29 passed, Ruff and Node
  syntax checks passed.
- Browser evidence: administrator changed 24h to 6h; all three aggregate requests used
  `window=6h`; the API and SVG contained 12 points at 30 minutes per point. Browser console
  warnings/errors were empty.
- Desktop 1280x720: document scroll width 1,265 within 1,280 CSS pixels. Mobile 390x844:
  document scroll width 375 within 390 pixels; chart width 345.33 pixels with 12 visible
  points and no overlap.
- Screenshots: `reports/screenshots/v0.2/admin-dashboard-trends-6h-1280x720.png`,
  `admin-dashboard-chart-6h-1280x720.png`, `admin-dashboard-trends-6h-390x844.png`, and
  `admin-dashboard-chart-6h-390x844.png`. Names record target browser viewports; page-content
  captures are 1265x712 and 375x812 pixels after browser chrome and scrollbars.
- Failure and fix: browser QA showed 3 ordinary users but 4 active users because an admin
  had opened a Feed. Active-user aggregation now joins `users` and filters `role=user`;
  a regression assertion requires one active ordinary user in the API fixture. The real
  Dashboard now reports 3 users and 3 active users.
- Boundary review: an earlier implementation used an inclusive end condition. It was
  changed to `< window_end` so overview and trend buckets cannot disagree at the boundary.
- G1 commit: `e209da5`. The G2 commit SHA is added in the G3 entry after commit.

## 2026-09-01 22:03 +08:00 - G3 clean-environment CI definition

- Base commit: `d97aa8a`; responsible Agent: Online subagent for the workflow, main Agent
  for review, remote execution and evidence.
- Workflow: Ubuntu latest, Python 3.11, uv dependency cache, `uv sync --frozen`,
  `ruff check .`, `pytest`, and `microlens smoke`.
- Isolation: no official MicroLens download, Release artifact, existing SQLite database,
  `.env`, credentials or paid service is available to the job. Smoke creates its own
  temporary data and artifact.
- Safety: workflow permissions are read-only; concurrent superseded runs on the same ref
  are cancelled; timeout is 20 minutes; OpenBLAS is limited to one thread.
- Local evidence before commit: full pytest 29 passed, Ruff passed, synthetic offline and
  online smoke passed, and `git diff --check` passed.
- G2 commit: `d97aa8a`. Remote Actions URL, conclusion, duration and G3 commit SHA are
  intentionally pending until the pushed workflow finishes; they must be added before G3
  is marked complete.

### First remote run and platform-warning fix

- G3 commit: `a11616d`; first run:
  `https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33517217987`.
- Result: all steps passed in 30 seconds, but GitHub annotated that checkout v4,
  setup-python v5 and setup-uv v6 target deprecated Node.js 20 and were being forced onto
  Node.js 24.
- Root cause: the workflow copied formerly stable major versions rather than checking the
  current maintained releases on the 2026 runner platform.
- Verification source: GitHub release APIs reported checkout `v7.0.1`, setup-python
  `v7.0.0`, and setup-uv `v10.0.1`, all from their official repositories.
- Fix: pin the maintained compatible majors `actions/checkout@v7`,
  `actions/setup-python@v7`, and `astral-sh/setup-uv@v10`. A second clean remote run must
  pass without the Node.js 20 annotation before G3 is complete.

### Second remote run and exact-tag fix

- Maintenance-update commit: `bc71748`; second run:
  `https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33517566938`.
- Result: failed during action resolution before dependency installation or project tests.
  GitHub could not resolve `astral-sh/setup-uv@v10`.
- Root cause: setup-uv publishes release tag `v10.0.1` but does not expose a resolvable
  floating `v10` action tag. The release lookup was correct; the assumed major alias was not.
- Fix: use the exact maintained release tag `astral-sh/setup-uv@v10.0.1`. The next remote
  run must execute every project step and finish without the Node.js 20 annotation.

### Third remote run - G3 passed

- Exact-tag commit: `5d9fc83`; final run:
  `https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33517793682`.
- Environment: GitHub-hosted Ubuntu 24.04, Python 3.11, read-only token permissions.
- Result: every setup, frozen install, Ruff, 29-test suite and synthetic smoke step passed.
  Job ran from 14:09:51Z to 14:10:24Z (33 seconds); annotations endpoint returned `[]`.
- A first `git push` for `5d9fc83` failed with a transient TLS connect error. No history was
  rewritten; retrying the identical push succeeded and triggered the recorded run.
- G3 status: PASS.

## 2026-09-01 22:13 +08:00 - G4 release artifact preparation

- Selected artifact:
  `hybrid-bm25-f64-764b7d14ce34-20260901T134041223913Z`.
- Bundle: `tmp/microlens-recsys-bundle-v0.2.0-bm25.zip`, 36,866,255 bytes, containing
  only `artifacts/latest.json` and the selected version directory. Archive listing confirms
  there is no dataset, SQLite database, environment file, secret or video.
- Bundle SHA256:
  `69479A2F04E90D133E9CE13579792C7781A909F5266E0447927FC331A8E9F7B6`.
- Release, final regression, main-branch CI and fresh-clone evidence remain pending and are
  appended only after the corresponding commands finish.

## 2026-09-01 22:39 +08:00 - Pre-release evidence and UTC contract review

- Read-only review of run `33517793682` found that its raw log says `29 passed`, not the 30
  previously copied into draft documentation. Historical G1-G3 counts above were corrected;
  no test result was changed or rerun retroactively.
- API review found Dashboard calculations were UTC-naive internally, so Pydantic serialized
  timestamps without an offset even though the contract described UTC. SQLite comparisons
  remain naive UTC, while the response boundary now adds explicit UTC awareness and serializes
  `Z` for overview bounds, trend bounds and every bucket start.
- Added `test_dashboard_time_contract_serializes_explicit_utc_offsets`; focused online tests
  are now 10 passed and the full local suite is 30 passed. Ruff passed after line-length review.
- This contract fix and documentation audit are included in the next feature-branch commit;
  its remote CI run is recorded only after push.

## 2026-09-01 23:04 +08:00 - G4 publish and fresh-clone acceptance

- Pre-release commit: `714216e`. Feature run
  `https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33521269946`
  passed frozen sync, Ruff, 30 tests and offline+online smoke in about 38 seconds with no
  annotations.
- `main` was fast-forwarded from `1b0d21b` to `714216e`; no merge commit or history rewrite
  was used. Main run
  `https://github.com/Golden-Paradise/microlens-recsys-mvp/actions/runs/33521419830`
  passed the same checks in about 39 seconds with no annotations.
- Release URL: `https://github.com/Golden-Paradise/microlens-recsys-mvp/releases/tag/v0.2.0`;
  published at 2026-09-01T15:00:58Z. Tag `v0.2.0` resolves to `714216e`.
- Assets: 36,866,255-byte bundle plus a 106-byte `.sha256` file. GitHub reports the bundle
  state as `uploaded` and digest as
  `sha256:69479a2f04e90d133e9ce13579792c7781a909f5266e0447927fc331a8e9f7b6`,
  exactly matching the local hash. The `.sha256` asset was downloaded into a separate temp
  directory and its content matched the same value. No v0.2 video was uploaded.
- Release failure and fix: the first create request ended with an API `EOF`. Its retry
  created a draft, but proxy-routed asset uploads had zero I/O and the direct debug request
  confirmed another `EOF` from `api.uploads.github.com`. After confirming the draft had no
  partial bundle, upload traffic for that asset host bypassed the local proxy; both assets
  uploaded successfully, were checksum-verified, and only then was the draft published.
- Fresh-clone commands in a new OS temp directory: `git clone`, `uv sync --frozen`, and
  `uv run microlens smoke`. The clone resolved to `714216e`, installed 61 locked packages,
  returned offline `status=ok` plus online `scope=offline+online`, and ended with a clean
  `main...origin/main` worktree. No existing database, model artifact or official data was
  copied; `data/raw` contained only `.gitkeep`.
- G4 evidence is complete. This log, Changelog, acceptance matrix and completion report are
  frozen in the final documentation commit; the commit is pushed only after local diff,
  test, lint and smoke revalidation.

## 2026-09-02 - Python 3.11 Windows path regression found during final Gate

- Command: set an isolated `UV_PROJECT_ENVIRONMENT` under the checkout, run
  `uv sync --frozen --python 3.11`, then `uv run --frozen --python 3.11 pytest -q`.
- Failure: all nine test modules failed during collection with `ModuleNotFoundError` for
  `app`/`recsys`; no business assertion had run. The same interpreter could import both
  packages from `python -c` because `sys.path[0]` was the current directory.
- Root cause: on this Windows host, Python 3.11 decoded the editable `.pth` entry for the
  Chinese checkout path incorrectly. The `pytest.exe` entrypoint starts with its `Scripts`
  directory on `sys.path`, so it could not rely on the current directory fallback.
- Fix: add `pythonpath = ["."]` to the repository pytest configuration. This makes the test
  root explicit and independent of editable-install path decoding. Verification is repeated
  in the same isolated Python 3.11 environment before the preparation commit.
- Verification: the same isolated CPython 3.11.14 environment then passed all 70 tests.
  Direct console-script startup remained affected by the editable `.pth` path, so release and
  CI commands were standardized on `uv run --python 3.11 python -m recsys.cli ...`; both
  `offline-smoke` and the publish/rollback online smoke returned `status=ok`. The project
  `.python-version` was changed from 3.13 to 3.11 so default resolution matches CI and README.

## 2026-09-03 - Final browser evidence correction

- The first manual capture used the app browser's 1494x782 content viewport and included a
  translation-extension control. A nominal 390x844 `runtime-health` image also showed the
  Dashboard header instead of the named section. Both were rejected and moved to ignored
  `tmp/invalid-screenshots-v03`.
- A clean headless Chromium run then produced exact 1280x720/390x844 images and asserted
  Alice/Bob list differences plus force/offline/API-filter/restore behavior.
- Failure: the first clean `content-operations-audit` image was only the SQLAdmin login page.
  Root cause: SQLAdmin deliberately uses a separate administrator session. The evidence and
  video scripts now perform that second login and wait for the audit table.
- Failure: after SQLAdmin authentication, returning to the application Dashboard lost the API
  administrator session in this browser flow, causing a 401 during recovery. The scripts now
  log back into the application explicitly and reacquire an admin session in `finally` before
  restoring content/model state.
- Final result: the clean evidence script exited 0 and wrote all 13 named screenshots. Visual
  inspection confirmed real audit rows, the model decision table, request detail, runtime
  warning, and no extension overlay or incoherent overlap.
- The verified capture and final-video scripts were moved from ignored `tmp/` into tracked
  `tools/`; otherwise the documented commands would not exist in a fresh clone.
- A stricter console Gate then found one 404 at `/favicon.ico`. It was the browser's automatic
  icon request, not a Feed/API failure, but still violated the zero-error acceptance rule. The
  base template now declares the existing static SVG favicon; the clean capture is rerun with
  console/page-error collection and document-overflow assertions enabled.
- The first rerun against a newly started Python 3.11 service rejected the force assertion.
  The script had formatted a UTC ISO timestamp for a `datetime-local` control, making the
  expiry eight hours old in Asia/Shanghai. An older active force had hidden this mistake on the
  long-running service. Both evidence and video scripts now convert to local wall time before
  filling the control; the assertion is rerun on the new service.
- The next force assertion still rejected for Alice even though the operation was active.
  Her persistent demo history already contained negative feedback for item 40, and the service
  correctly protects explicit `not_interested` feedback from a forced insertion. The operation
  journey now uses Bob, while Alice remains the behavior/profile example; offline filtering is
  checked through Bob's authenticated Feed API as well.
- Final verification on the new CPython 3.11 service: the evidence script exited 0 after all
  13 screenshots, with zero collected console warnings/errors and every document-width
  assertion passing. Bob received item 40 at rank 1 after force; the subsequent authenticated
  Feed omitted it after offline; restore and SQLAdmin audit were both visible.
- Post-fix local Gate: `70 passed, 7 warnings in 29.20s`; the warnings remain limited to the
  documented upstream Starlette and implicit conversions. Ruff, three Node syntax checks,
  lock check, diff check, offline smoke and publish/rollback online smoke all exited 0.

## 2026-09-03 - Final-video duration Gate correction

- The first post-publication recording completed every scripted assertion and restored the
  initial model/content state, but media inspection measured `00:05:09.40`. It was rejected
  because the PDF requires a 3-5 minute video. The rejected file was 16,470,507 bytes with
  SHA256 `8c30951d6a4f855ef0e9763810ea63423734c6a3a7f07a3d73f4b8429b342118`.
- Root cause: 269 seconds of explicit slide/caption waits plus approximately 40 seconds of
  real navigation, authentication and API work. Seven explanatory holds were reduced by 28
  seconds without removing any of the five mandatory journeys or their runtime assertions.
- Verification discipline: run `node --check tools/record_final_demo_v03.mjs`, push this fix,
  wait for the matching main CI, then record again with that commit/run URL. Accept the
  replacement only after codec, 1280x720 geometry, duration, black-frame and sampled-frame
  inspection all pass.
