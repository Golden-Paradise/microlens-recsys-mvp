# Changelog

All notable changes, compatibility notes, and verification evidence are recorded here.

## [Unreleased] - v0.2.0

### Added

- Add a versioned Item-Item BM25 collaborative retrieval artifact and validation-only
  serving-policy selection.
- Add deterministic equal-weight ALS + BM25 reciprocal-rank fusion as a measured candidate;
  BM25 remains the published policy because it won validation NDCG@20.
- Add shared `1h`, `6h`, `24h`, and `all` UTC windows to Dashboard overview, feed
  diagnostics, feed shares, and hot items.
- Add an API-driven, zero-filled trend series and responsive dependency-free SVG chart for
  requests, exposures, clicks, likes, and CTR.

### Planned

- Add GitHub Actions checks for locked dependencies, lint, tests, and synthetic smoke.

### Compatibility

- Preserve loading compatibility with the v0.1 ALS release bundle.

### Verification

- Baseline: 23 tests passed and Ruff passed on commit `1b0d21b`.
- G1: 30 tests passed, Ruff passed, offline smoke passed, and the full official-data
  pipeline selected BM25 on validation NDCG@20.
- G2: 30 tests passed; desktop and 390px browser checks rendered a nonblank 12-point 6h
  trend with no horizontal overflow or browser console errors.

## [0.1.0] - 2026-09-01

- Delivered the complete mandatory MicroLens MVP flow, reproducible ALS bundle, private
  GitHub Release, and 04:08 demonstration video.
