# Changelog

All notable changes, compatibility notes, and verification evidence are recorded here.

## [0.3.0] - 2026-09-03

### Added

- Add sparse title TF-IDF pure-cold retrieval with fixed Word/`char_wb` analyzers, cold quota
  ablation, slice metrics, NPZ persistence and validation-only policy selection.
- Add a single-worker `ModelManager` with request snapshots, strict checksum/dimension
  validation, atomic pointer replacement, publish/rollback, previous recovery and
  deterministic last-known fallback.
- Add model decision evidence, current/previous runtime state, recent request list/detail,
  nearest-rank P50/P95, fallback rate and passive Dashboard warnings.
- Upgrade synthetic smoke to train two real artifacts and verify authenticated publish,
  new-request version switching and rollback in a clean temporary environment.
- Add content-derived static asset fingerprints and final 1280x720/390x844 UI evidence.

### Selection Decision

- BM25 remains the serving policy: validation overall NDCG@20 `0.03713558` versus
  `0.03697165` for the best content candidate, Word/q1.
- Word/q1 improves pure-cold validation Recall/NDCG@20 to `0.05450237/0.01240857`;
  `char_wb`/q5 reaches the best pure-cold Recall `0.09241706` but lowers overall NDCG to
  `0.03511726`. Both remain measured negative trade-off experiments, not online claims.
- Formal Test was run once after freezing and reports only BM25:
  Recall/NDCG/Coverage@20 `0.07822/0.03338273/0.98199792`.

### Compatibility

- v0.1/v0.2 manifests and flat pointers remain startup-compatible. A legacy bundle without
  a SHA256-covered `manifest.json` is marked `legacy_unverified` and cannot be republished
  through the management API.
- Runtime pointer and in-memory state are authoritative; the existing `model_versions` table
  remains a repairable Dashboard projection. No database table was added.
- Explicitly supports one Uvicorn worker. Multi-process activation consistency is not claimed.

### Verification

- Local: 70 tests, Ruff, Node syntax, diff check, synthetic publish/rollback smoke,
  full-runtime strict load/rollback and browser console checks passed.
- Official artifact: 66,730,787 bytes, 11 SHA256 entries verified; `checksums.json` SHA256
  `c2a7e56f285f7eae486af9dfba10a7315c846ad6e9dd39226ba00cecf821f28a`.
- The 77,575,939-byte full runtime remains local because it contains official user-history
  derivatives. The locally verified 10,535,942-byte public candidate contains only BM25
  weights, item IDs and a sanitized manifest; SHA256 is
  `c9eb3b87cc681b2c46ba366d1916222c413b7e682d769283fc446c037ee98b65`.
- Removed the historical v0.1/v0.2 runtime assets before making the repository public because
  they contained user-level interaction-derived structures. The v0.1 video remains clearly
  labeled as historical evidence.
- Public main CI run `33657938390` passed on Ubuntu/Python 3.11. An anonymous fresh clone of
  implementation commit `0c33477` passed frozen sync, 70 tests and both smoke paths without
  copying a database, official data or a model artifact.
- Two otherwise complete recordings were rejected at `05:09.40` and `04:29.72` for missing
  the duration Gate. The accepted 14,543,758-byte replacement is VP8/1280x720 at `04:33.96`,
  covers all five mandatory journeys and has SHA256
  `0a963e09f28b8aa340ad592d8198bf40d4e23d1ba1694e1975fff5f7422665ed`.
- Pin the project default to Python 3.11 and make pytest/CLI Gate commands use module startup,
  avoiding Windows editable-install path decoding failures in checkouts with non-ASCII names.

## [0.2.0] - 2026-09-01

### Added

- Add a versioned Item-Item BM25 collaborative retrieval artifact and validation-only
  serving-policy selection.
- Add deterministic equal-weight ALS + BM25 reciprocal-rank fusion as a measured candidate;
  BM25 remains the published policy because it won validation NDCG@20.
- Add shared `1h`, `6h`, `24h`, and `all` UTC windows to Dashboard overview, feed
  diagnostics, feed shares, and hot items.
- Add an API-driven, zero-filled trend series and responsive dependency-free SVG chart for
  requests, exposures, clicks, likes, and CTR.
- Add GitHub Actions checks for locked dependencies, lint, tests, and synthetic smoke.

### Compatibility

- Preserve loading compatibility with the v0.1 ALS release bundle.

### Verification

- Baseline: 23 tests passed and Ruff passed on commit `1b0d21b`.
- G1: 29 tests passed, Ruff passed, offline smoke passed, and the full official-data
  pipeline selected BM25 on validation NDCG@20.
- G2: 29 tests passed; desktop and 390px browser checks rendered a nonblank 12-point 6h
  trend with no horizontal overflow or browser console errors.
- G3 local: the CI contract runs on Ubuntu/Python 3.11 without official data, model
  downloads, database state, or secrets.
- G3 remote: GitHub Actions run `33517793682` passed its 29-test suite and every other step
  in 33 seconds with no annotations after upgrading to maintained Node 24 action releases.
- Pre-release review added an explicit UTC-offset API contract test; the local suite is now
  30 tests. Feature run `33521269946` and main run `33521419830` both passed the updated
  suite, Ruff and smoke with no annotations.
- G4 fresh clone at commit `714216e` completed frozen sync and offline+online smoke with a
  clean worktree.
- Published Release bundle: 36,866,255 bytes; SHA256
  `69479A2F04E90D133E9CE13579792C7781A909F5266E0447927FC331A8E9F7B6`.

## [0.1.0] - 2026-09-01

- Delivered the complete mandatory MicroLens MVP flow, reproducible ALS bundle, private
  GitHub Release, and 04:08 demonstration video.
