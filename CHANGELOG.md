# Changelog

All notable changes, compatibility notes, and verification evidence are recorded here.

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
