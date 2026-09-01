# Architecture

This document will be completed at G4. The frozen boundaries are:

- `recsys/`: official-data ingestion, temporal split, baselines, ALS, evaluation, artifacts.
- `app/`: authentication, feed orchestration, events, profile updates, dashboard, operations.
- SQLite is authoritative for online state; model artifacts are immutable and versioned.
- Offline content always wins over force placement; model failures fall back to popularity.

