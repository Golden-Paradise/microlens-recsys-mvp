import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

import numpy as np
import pytest
from scipy import sparse

from app.model_manager import ArtifactValidationError, ModelManager
from recsys.contracts import ArtifactPointer, ModelManifest


@dataclass
class FakeBundle:
    manifest: ModelManifest


@dataclass
class FakeEngine:
    model_version: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artifact(
    root: Path,
    version: str,
    *,
    checksums: bool = True,
    matrix_shape: tuple[int, int] = (2, 3),
    content: bool = False,
) -> Path:
    artifact = root / version
    artifact.mkdir(parents=True)
    np.savez(
        artifact / "als_model.npz",
        user_factors=np.ones((2, 2), dtype=np.float32),
        item_factors=np.ones((3, 2), dtype=np.float32),
    )
    sparse.save_npz(artifact / "serving_user_items.npz", sparse.csr_matrix(matrix_shape))
    (artifact / "mappings.json").write_text(
        json.dumps({"user_ids": [10, 20], "item_ids": [1, 2, 3]}), encoding="utf-8"
    )
    (artifact / "popularity.json").write_text("[1, 2, 3]", encoding="utf-8")
    (artifact / "metrics.json").write_text("{}", encoding="utf-8")
    (artifact / "badcases.csv").write_text("user_id,item_id\n", encoding="utf-8")

    files = {
        "model": "als_model.npz",
        "user_items": "serving_user_items.npz",
        "mappings": "mappings.json",
        "popularity": "popularity.json",
        "metrics": "metrics.json",
        "badcases": "badcases.csv",
    }
    content_manifest = None
    if content:
        sparse.save_npz(
            artifact / "title_tfidf_items.npz",
            sparse.csr_matrix(np.ones((3, 2), dtype=np.float32)),
        )
        np.savez(artifact / "bm25_model.npz", weights=np.ones((3, 3)))
        content_manifest = {
            "analyzer": "word",
            "ngram_min": 1,
            "ngram_max": 2,
            "min_df": 2,
            "max_features": 50000,
            "sublinear_tf": True,
            "history_limit": 10,
            "candidate_pool": 100,
            "cold_quota": 1,
        }
        (artifact / "content_config.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "manifest": content_manifest,
                    "item_ids": [1, 2, 3],
                    "cold_item_ids": [3],
                    "user_histories": {"10": [1], "20": [2]},
                }
            ),
            encoding="utf-8",
        )
        files.update(
            {
                "bm25_model": "bm25_model.npz",
                "content_items": "title_tfidf_items.npz",
                "content_config": "content_config.json",
            }
        )
    if checksums:
        checksum_targets = set(files.values())
        (artifact / "checksums.json").write_text(
            json.dumps({name: _sha256(artifact / name) for name in checksum_targets}),
            encoding="utf-8",
        )
        files["checksums"] = "checksums.json"

    manifest = {
        "model_version": version,
        "data_version": "fixture-v1",
        "created_at": "2026-09-02T00:00:00Z",
        "algorithm": "fixture",
        "factors": 2,
        "iterations": 1,
        "regularization": 0.01,
        "alpha": 1.0,
        "top_k": 20,
        "files": files,
        "metrics": {},
        "serving_policy": "bm25_content" if content else "als",
        "content_retriever": content_manifest,
    }
    (artifact / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return artifact


def _write_pointer(root: Path, current: str, previous: str | None = None) -> None:
    payload: dict[str, object] = {
        "schema_version": 2,
        "current": {"model_version": current, "path": current},
        "previous": (
            {"model_version": previous, "path": previous} if previous is not None else None
        ),
    }
    (root / "latest.json").write_text(json.dumps(payload), encoding="utf-8")


def _loader(path: Path) -> FakeBundle:
    manifest = ModelManifest.model_validate_json(
        (path / "manifest.json").read_text(encoding="utf-8")
    )
    return FakeBundle(manifest)


def _manager(root: Path, **kwargs: object) -> ModelManager:
    kwargs.setdefault("warmup", lambda engine: None)
    return ModelManager(
        root,
        loader=_loader,
        engine_factory=lambda bundle: FakeEngine(bundle.manifest.model_version),
        fallback_engine=FakeEngine("deterministic-v1"),
        **kwargs,
    )


def test_publish_and_rollback_swap_pointer_while_old_snapshot_stays_stable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "v1")
    _write_artifact(root, "v2")
    (root / "latest.json").write_text(
        json.dumps({"model_version": "v1", "path": "v1"}), encoding="utf-8"
    )
    manager = _manager(root)
    old_snapshot = manager.snapshot()

    published = manager.publish("v2")

    assert old_snapshot.model_version == "v1"
    assert manager.snapshot().model_version == "v2"
    assert published.current.model_version == "v2"
    assert published.previous.model_version == "v1"
    pointer = ArtifactPointer.model_validate_json((root / "latest.json").read_text())
    assert pointer.current.model_version == "v2"
    assert pointer.previous.model_version == "v1"

    rolled_back = manager.rollback()
    assert manager.snapshot().model_version == "v1"
    assert rolled_back.current.model_version == "v1"
    assert rolled_back.previous.model_version == "v2"


def test_publish_rejects_checksum_tamper_and_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "v1")
    candidate = _write_artifact(root, "v2")
    _write_pointer(root, "v1")
    manager = _manager(root)
    pointer_before = (root / "latest.json").read_bytes()
    (candidate / "popularity.json").write_text("[3]", encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="SHA256 mismatch"):
        manager.publish("v2")
    with pytest.raises(ArtifactValidationError, match="direct child"):
        manager.publish("../outside")

    assert manager.snapshot().model_version == "v1"
    assert (root / "latest.json").read_bytes() == pointer_before


def test_atomic_replace_failure_leaves_pointer_and_runtime_unchanged(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "v1")
    _write_artifact(root, "v2")
    _write_pointer(root, "v1")
    pointer_before = (root / "latest.json").read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError(f"replace failed: {source.name} -> {destination.name}")

    manager = _manager(root, replace=fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        manager.publish("v2")

    assert manager.snapshot().model_version == "v1"
    assert (root / "latest.json").read_bytes() == pointer_before
    assert not list(root.glob(".latest.*.tmp"))


def test_snapshot_remains_available_while_candidate_warmup_is_blocked(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "v1")
    _write_artifact(root, "v2")
    _write_pointer(root, "v1")
    warmup_started = Event()
    allow_warmup_to_finish = Event()

    def blocking_warmup(engine: FakeEngine) -> None:
        if engine.model_version == "v2":
            warmup_started.set()
            assert allow_warmup_to_finish.wait(timeout=2)

    manager = _manager(root, warmup=blocking_warmup)
    publish_errors: list[BaseException] = []

    def publish() -> None:
        try:
            manager.publish("v2")
        except BaseException as exc:  # pragma: no cover - asserted after joining
            publish_errors.append(exc)

    publisher = Thread(target=publish)
    publisher.start()
    assert warmup_started.wait(timeout=2)

    assert manager.snapshot().model_version == "v1"
    allow_warmup_to_finish.set()
    publisher.join(timeout=2)

    assert not publisher.is_alive()
    assert publish_errors == []
    assert manager.snapshot().model_version == "v2"


def test_startup_recovers_previous_when_current_is_corrupt(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    broken = _write_artifact(root, "broken")
    _write_artifact(root, "good")
    _write_pointer(root, "broken", "good")
    (broken / "popularity.json").write_text("[999]", encoding="utf-8")

    manager = _manager(root)

    assert manager.snapshot().model_version == "good"
    assert manager.runtime().status == "recovered"
    assert manager.runtime().validation.status == "error"
    pointer = ArtifactPointer.model_validate_json((root / "latest.json").read_text())
    assert pointer.current.model_version == "good"
    assert pointer.previous.model_version == "broken"


def test_startup_falls_back_when_current_and_previous_are_invalid(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    first = _write_artifact(root, "first")
    second = _write_artifact(root, "second")
    _write_pointer(root, "first", "second")
    (first / "popularity.json").write_text("[]", encoding="utf-8")
    (second / "popularity.json").write_text("[]", encoding="utf-8")

    manager = _manager(root)

    assert manager.snapshot().model_version == "deterministic-v1"
    assert manager.runtime().status == "fallback"
    assert len(manager.runtime().validation.errors) == 2


def test_legacy_artifact_can_start_but_cannot_be_published(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "legacy", checksums=False)
    _write_pointer(root, "legacy")
    manager = _manager(root)

    assert manager.snapshot().model_version == "legacy"
    assert manager.runtime().validation.status == "legacy_unverified"
    with pytest.raises(ArtifactValidationError, match="cannot be published"):
        manager.publish("legacy")


def test_publish_rejects_dimension_mismatch_even_with_valid_checksums(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "v1")
    _write_artifact(root, "bad-shape", matrix_shape=(1, 3))
    _write_pointer(root, "v1")
    manager = _manager(root)

    with pytest.raises(ArtifactValidationError, match="matrix shape"):
        manager.publish("bad-shape")

    assert manager.snapshot().model_version == "v1"


def test_publish_rejects_content_mapping_mismatch_with_valid_checksum(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    _write_artifact(root, "v1")
    candidate = _write_artifact(root, "content", content=True)
    _write_pointer(root, "v1")
    config_path = candidate / "content_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["item_ids"] = [3, 2, 1]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    checksums_path = candidate / "checksums.json"
    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
    checksums["content_config.json"] = _sha256(config_path)
    checksums_path.write_text(json.dumps(checksums), encoding="utf-8")
    manager = _manager(root)

    with pytest.raises(ArtifactValidationError, match="Content item IDs"):
        manager.publish("content")

    assert manager.snapshot().model_version == "v1"
