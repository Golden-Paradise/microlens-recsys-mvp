from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

import numpy as np
from scipy import sparse

from app.constants import FeedType
from app.recommendation import (
    ALSRecommendationEngine,
    DeterministicRecommendationEngine,
    RecommendationEngine,
)
from app.schemas import (
    ModelRuntimeResponse,
    RuntimeModelReference,
    RuntimeValidation,
)
from recsys.contracts import ArtifactPointer, ArtifactReference, ModelManifest
from recsys.model import load_model_bundle


class ArtifactValidationError(ValueError):
    """Raised when an artifact cannot be trusted for activation."""


class ArtifactNotFoundError(ArtifactValidationError):
    """Raised when a syntactically valid model version directory does not exist."""


class ModelActivationError(RuntimeError):
    """Raised when a valid runtime transition cannot be completed."""


class _PreparedModel:
    def __init__(
        self,
        *,
        reference: ArtifactReference,
        manifest: ModelManifest,
        engine: RecommendationEngine,
        validation_status: Literal["ok", "legacy_unverified"],
    ) -> None:
        self.reference = reference
        self.manifest = manifest
        self.engine = engine
        self.validation_status = validation_status


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelManager:
    """Single-process model activation with immutable per-request snapshots."""

    def __init__(
        self,
        artifact_root: Path,
        *,
        loader: Callable[[Path], Any] = load_model_bundle,
        engine_factory: Callable[[Any], RecommendationEngine] = ALSRecommendationEngine,
        fallback_engine: RecommendationEngine | None = None,
        warmup: Callable[[RecommendationEngine], None] | None = None,
        replace: Callable[[Path, Path], None] = os.replace,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.artifact_root = artifact_root.resolve()
        self.pointer_path = self.artifact_root / "latest.json"
        self._loader = loader
        self._engine_factory = engine_factory
        self._fallback_engine = fallback_engine or DeterministicRecommendationEngine()
        self._warmup = warmup or self._default_warmup
        self._replace = replace
        self._clock = clock
        self._mutation_lock = RLock()
        self._state_lock = RLock()

        now = self._clock()
        self._engine: RecommendationEngine = self._fallback_engine
        self._status: Literal["ready", "recovered", "fallback"] = "fallback"
        self._current: RuntimeModelReference | None = None
        self._previous: RuntimeModelReference | None = None
        self._loaded_at = now
        self._validation = RuntimeValidation(
            status="error",
            checked_at=now,
            errors=["Model runtime has not been initialized."],
        )
        self._initialize()

    def snapshot(self) -> RecommendationEngine:
        """Return one stable engine reference for the complete request lifetime."""
        with self._state_lock:
            return self._engine

    def runtime(self) -> ModelRuntimeResponse:
        with self._state_lock:
            return ModelRuntimeResponse(
                status=self._status,
                current=self._current.model_copy() if self._current else None,
                previous=self._previous.model_copy() if self._previous else None,
                loaded_at=self._loaded_at,
                validation=self._validation.model_copy(deep=True),
            )

    def publish(self, version: str) -> ModelRuntimeResponse:
        """Strictly validate and activate one direct child of the artifact root."""
        with self._mutation_lock:
            reference = ArtifactReference(model_version=version, path=version)
            prepared = self._prepare(reference, strict=True)
            with self._state_lock:
                previous = self._runtime_to_artifact(self._current)
                previous_runtime = self._current
            if previous == reference:
                return self.runtime()
            pointer = ArtifactPointer(
                current=reference,
                previous=previous,
                updated_at=self._clock(),
            )
            self._atomic_write_pointer(pointer)
            self._install(
                prepared,
                previous=previous_runtime,
                status="ready",
                errors=[],
            )
            return self.runtime()

    def rollback(self) -> ModelRuntimeResponse:
        """Swap current and previous after revalidating and warming the target."""
        with self._mutation_lock:
            with self._state_lock:
                current = self._runtime_to_artifact(self._current)
                previous = self._runtime_to_artifact(self._previous)
                old_current_runtime = self._current
            if previous is None:
                raise ModelActivationError("No previous model version is available for rollback.")

            prepared = self._prepare(previous, strict=False)
            pointer = ArtifactPointer(
                current=previous,
                previous=current,
                updated_at=self._clock(),
            )
            self._atomic_write_pointer(pointer)
            self._install(
                prepared,
                previous=old_current_runtime,
                status="ready",
                errors=[],
            )
            return self.runtime()

    def _initialize(self) -> None:
        try:
            pointer = ArtifactPointer.model_validate_json(
                self.pointer_path.read_text(encoding="utf-8")
            )
        except (FileNotFoundError, OSError, ValueError, KeyError) as exc:
            self._install_fallback([f"Could not read artifact pointer: {exc}"])
            return

        try:
            prepared = self._prepare(pointer.current, strict=False)
        except (ArtifactValidationError, OSError, ValueError, KeyError) as current_exc:
            if pointer.previous is None:
                self._install_fallback([f"Current artifact failed validation: {current_exc}"])
                return
            try:
                prepared = self._prepare(pointer.previous, strict=False)
            except (ArtifactValidationError, OSError, ValueError, KeyError) as previous_exc:
                self._install_fallback(
                    [
                        f"Current artifact failed validation: {current_exc}",
                        f"Previous artifact failed validation: {previous_exc}",
                    ]
                )
                return

            recovered_pointer = ArtifactPointer(
                current=pointer.previous,
                previous=pointer.current,
                updated_at=self._clock(),
            )
            errors = [f"Recovered after current artifact failed validation: {current_exc}"]
            try:
                self._atomic_write_pointer(recovered_pointer)
            except OSError as exc:
                errors.append(f"Could not persist recovered pointer: {exc}")
            self._install(
                prepared,
                previous=self._reference_with_policy(pointer.current),
                status="recovered",
                errors=errors,
            )
            return

        self._install(
            prepared,
            previous=self._reference_with_policy(pointer.previous),
            status="ready",
            errors=[],
        )

    def _prepare(self, reference: ArtifactReference, *, strict: bool) -> _PreparedModel:
        artifact_dir = self._resolve_version_path(reference.path)
        try:
            manifest, validation_status = self._validate_artifact(
                artifact_dir,
                expected_version=reference.model_version,
                strict=strict,
            )
            bundle = self._loader(artifact_dir)
            engine = self._engine_factory(bundle)
            if engine.model_version != manifest.model_version:
                raise ArtifactValidationError(
                    "Engine model version does not match the validated manifest."
                )
            self._warmup(engine)
        except ArtifactValidationError:
            raise
        except Exception as exc:
            raise ArtifactValidationError(f"Artifact load or warm-up failed: {exc}") from exc
        return _PreparedModel(
            reference=reference,
            manifest=manifest,
            engine=engine,
            validation_status=validation_status,
        )

    def _validate_artifact(
        self,
        artifact_dir: Path,
        *,
        expected_version: str,
        strict: bool,
    ) -> tuple[ModelManifest, Literal["ok", "legacy_unverified"]]:
        manifest_path = self._resolve_artifact_file(artifact_dir, "manifest.json")
        if not manifest_path.is_file():
            raise ArtifactValidationError("Artifact manifest.json is missing.")
        try:
            manifest = ModelManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise ArtifactValidationError(f"Artifact manifest is invalid: {exc}") from exc
        if manifest.model_version != expected_version:
            raise ArtifactValidationError(
                "Pointer model version does not match manifest model version."
            )

        required_keys = {"model", "user_items", "mappings", "popularity"}
        policy_keys = {
            "als": {"model"},
            "cosine": {"cosine_model"},
            "bm25": {"bm25_model"},
            "rrf": {"model", "bm25_model"},
            "bm25_content": {"bm25_model", "content_items", "content_config"},
        }
        if manifest.serving_policy not in policy_keys:
            raise ArtifactValidationError(
                f"Unsupported serving policy: {manifest.serving_policy!r}."
            )
        required_keys.update(policy_keys[manifest.serving_policy])
        missing_keys = required_keys - set(manifest.files)
        if missing_keys:
            raise ArtifactValidationError(
                f"Manifest is missing required file keys: {sorted(missing_keys)}"
            )

        resolved_files = {
            key: self._resolve_artifact_file(artifact_dir, relative_path)
            for key, relative_path in manifest.files.items()
        }
        missing_files = [key for key, path in resolved_files.items() if not path.is_file()]
        if missing_files:
            raise ArtifactValidationError(
                f"Manifest files are missing: {sorted(missing_files)}"
            )

        checksum_key = manifest.files.get("checksums")
        if checksum_key is None:
            if strict:
                raise ArtifactValidationError(
                    "Legacy artifact has no checksum manifest and cannot be published."
                )
            validation_status: Literal["ok", "legacy_unverified"] = "legacy_unverified"
        else:
            self._validate_checksums(
                artifact_dir,
                checksum_path=resolved_files["checksums"],
                required_paths={
                    relative_path
                    for key, relative_path in manifest.files.items()
                    if key != "checksums"
                },
                checksum_filename=checksum_key,
            )
            validation_status = "ok"

        self._validate_dimensions(manifest, resolved_files)
        return manifest, validation_status

    def _validate_checksums(
        self,
        artifact_dir: Path,
        *,
        checksum_path: Path,
        required_paths: set[str],
        checksum_filename: str,
    ) -> None:
        try:
            checksums = json.loads(checksum_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArtifactValidationError(f"Checksum manifest is invalid: {exc}") from exc
        if not isinstance(checksums, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in checksums.items()
        ):
            raise ArtifactValidationError(
                "Checksum manifest must map file names to SHA256 strings."
            )
        missing = required_paths - set(checksums)
        if missing:
            raise ArtifactValidationError(
                f"Checksum manifest does not cover declared files: {sorted(missing)}"
            )

        for relative_path, expected in checksums.items():
            if relative_path == checksum_filename:
                raise ArtifactValidationError("Checksum manifest cannot checksum itself.")
            if len(expected) != 64 or any(
                char not in "0123456789abcdefABCDEF" for char in expected
            ):
                raise ArtifactValidationError(f"Invalid SHA256 for {relative_path!r}.")
            target = self._resolve_artifact_file(artifact_dir, relative_path)
            if not target.is_file():
                raise ArtifactValidationError(f"Checksummed file is missing: {relative_path!r}.")
            actual = _sha256(target)
            if actual.lower() != expected.lower():
                raise ArtifactValidationError(f"SHA256 mismatch for {relative_path!r}.")

    def _validate_dimensions(
        self,
        manifest: ModelManifest,
        resolved_files: dict[str, Path],
    ) -> None:
        try:
            mappings = json.loads(resolved_files["mappings"].read_text(encoding="utf-8"))
            user_ids = mappings["user_ids"]
            item_ids = mappings["item_ids"]
            popularity = json.loads(resolved_files["popularity"].read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ArtifactValidationError(f"Artifact mappings are invalid: {exc}") from exc
        if not isinstance(user_ids, list) or not isinstance(item_ids, list):
            raise ArtifactValidationError(
                "Artifact mappings must contain user_ids and item_ids lists."
            )
        if not user_ids or not item_ids:
            raise ArtifactValidationError("Artifact mappings cannot be empty.")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in user_ids):
            raise ArtifactValidationError("Artifact user_ids must contain only integers.")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in item_ids):
            raise ArtifactValidationError("Artifact item_ids must contain only integers.")
        if len(set(user_ids)) != len(user_ids) or len(set(item_ids)) != len(item_ids):
            raise ArtifactValidationError("Artifact user_ids and item_ids must be unique.")
        if (
            not isinstance(popularity, list)
            or not all(
                isinstance(value, int) and not isinstance(value, bool) for value in popularity
            )
            or not set(popularity).issubset(set(item_ids))
        ):
            raise ArtifactValidationError("Popularity IDs must be a subset of mapped item IDs.")

        try:
            user_items = sparse.load_npz(resolved_files["user_items"])
        except (OSError, ValueError) as exc:
            raise ArtifactValidationError(f"User-item matrix is invalid: {exc}") from exc
        expected_shape = (len(user_ids), len(item_ids))
        if user_items.shape != expected_shape:
            raise ArtifactValidationError(
                f"User-item matrix shape {user_items.shape} does not match {expected_shape}."
            )

        try:
            with np.load(resolved_files["model"], allow_pickle=False) as model_payload:
                user_factors = model_payload["user_factors"]
                item_factors = model_payload["item_factors"]
        except (OSError, ValueError, KeyError) as exc:
            raise ArtifactValidationError(f"ALS model factors are invalid: {exc}") from exc
        expected_user_factors = (len(user_ids), manifest.factors)
        expected_item_factors = (len(item_ids), manifest.factors)
        if user_factors.shape != expected_user_factors:
            raise ArtifactValidationError(
                f"User factor shape {user_factors.shape} does not match {expected_user_factors}."
            )
        if item_factors.shape != expected_item_factors:
            raise ArtifactValidationError(
                f"Item factor shape {item_factors.shape} does not match {expected_item_factors}."
            )

        if manifest.content_retriever is not None:
            if not {"content_items", "content_config"} <= set(resolved_files):
                raise ArtifactValidationError(
                    "Content retriever manifest has no declared content artifacts."
                )
            try:
                content_items = sparse.load_npz(resolved_files["content_items"])
                content_config = json.loads(
                    resolved_files["content_config"].read_text(encoding="utf-8")
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ArtifactValidationError(
                    f"Content retriever artifacts are invalid: {exc}"
                ) from exc
            if content_items.shape[0] != len(item_ids):
                raise ArtifactValidationError(
                    "Content item vector rows do not match mapped item IDs."
                )
            if content_config.get("item_ids") != item_ids:
                raise ArtifactValidationError(
                    "Content item IDs do not match the shared artifact mapping."
                )
            if content_config.get("manifest") != manifest.content_retriever.model_dump(
                mode="json"
            ):
                raise ArtifactValidationError(
                    "Content config does not match the model manifest."
                )

    def _resolve_version_path(self, relative_path: str) -> Path:
        if (
            not relative_path
            or relative_path in {".", ".."}
            or "/" in relative_path
            or "\\" in relative_path
            or Path(relative_path).is_absolute()
        ):
            raise ArtifactValidationError("Model version must be one direct child directory.")
        candidate = (self.artifact_root / relative_path).resolve()
        if candidate.parent != self.artifact_root:
            raise ArtifactValidationError("Model version is outside the artifact root.")
        if not candidate.is_dir():
            raise ArtifactNotFoundError("Model version directory was not found.")
        return candidate

    @staticmethod
    def _resolve_artifact_file(artifact_dir: Path, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise ArtifactValidationError("Artifact file path must be relative.")
        candidate = (artifact_dir / relative_path).resolve()
        try:
            candidate.relative_to(artifact_dir)
        except ValueError as exc:
            raise ArtifactValidationError(
                "Artifact file path escapes its version directory."
            ) from exc
        return candidate

    def _atomic_write_pointer(self, pointer: ArtifactPointer) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=".latest.",
                suffix=".tmp",
                dir=self.artifact_root,
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(pointer.model_dump(mode="json"), stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._replace(temporary_path, self.pointer_path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def _install(
        self,
        prepared: _PreparedModel,
        *,
        previous: RuntimeModelReference | None,
        status: Literal["ready", "recovered"],
        errors: list[str],
    ) -> None:
        checked_at = self._clock()
        validation_status: Literal["ok", "legacy_unverified", "error"] = (
            "error" if errors else prepared.validation_status
        )
        with self._state_lock:
            self._engine = prepared.engine
            self._status = status
            self._current = RuntimeModelReference(
                model_version=prepared.reference.model_version,
                path=prepared.reference.path,
                serving_policy=prepared.manifest.serving_policy,
            )
            self._previous = previous.model_copy() if previous else None
            self._loaded_at = checked_at
            self._validation = RuntimeValidation(
                status=validation_status,
                checked_at=checked_at,
                errors=errors,
            )

    def _install_fallback(self, errors: list[str]) -> None:
        now = self._clock()
        with self._state_lock:
            self._engine = self._fallback_engine
            self._status = "fallback"
            self._current = None
            self._previous = None
            self._loaded_at = now
            self._validation = RuntimeValidation(status="error", checked_at=now, errors=errors)

    def _reference_with_policy(
        self, reference: ArtifactReference | None
    ) -> RuntimeModelReference | None:
        if reference is None:
            return None
        serving_policy = None
        try:
            artifact_dir = self._resolve_version_path(reference.path)
            manifest = ModelManifest.model_validate_json(
                (artifact_dir / "manifest.json").read_text(encoding="utf-8")
            )
            if manifest.model_version == reference.model_version:
                serving_policy = manifest.serving_policy
        except (ArtifactValidationError, FileNotFoundError, OSError, ValueError, KeyError):
            pass
        return RuntimeModelReference(
            model_version=reference.model_version,
            path=reference.path,
            serving_policy=serving_policy,
        )

    @staticmethod
    def _runtime_to_artifact(
        reference: RuntimeModelReference | None,
    ) -> ArtifactReference | None:
        if reference is None:
            return None
        return ArtifactReference(model_version=reference.model_version, path=reference.path)

    @staticmethod
    def _default_warmup(engine: RecommendationEngine) -> None:
        if not getattr(engine, "model_version", None):
            raise ArtifactValidationError("Engine warm-up found no model version.")
        if isinstance(engine, ALSRecommendationEngine):
            if not engine.bundle.user_ids:
                raise ArtifactValidationError("Engine warm-up found no mapped users.")
            engine.bundle.recommend(
                engine.bundle.user_ids[0],
                limit=1,
                exclude_item_ids=set(),
            )
            return
        engine.recommend(
            user_id=-1,
            feed_type=FeedType.PERSONALIZED,
            items=[],
            limit=1,
            feedback_by_bucket={},
            exposure_counts={},
        )
