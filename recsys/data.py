from __future__ import annotations

import hashlib
import json
import shutil
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from recsys.contracts import DataSummary

OFFICIAL_BASE_URL = "https://recsys.westlake.edu.cn/MicroLens-50k-Dataset"
OFFICIAL_FILES = {
    "pairs": "MicroLens-50k_pairs.tsv",
    "titles": "MicroLens-50k_titles.csv",
    "stats": "MicroLens-50k_likes_and_views.txt",
}


@dataclass(frozen=True)
class PreparedDataset:
    path: Path
    data_version: str
    summary: DataSummary
    user_ids: list[int]
    item_ids: list[int]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_official_data(raw_dir: Path, *, force: bool = False) -> dict[str, dict[str, object]]:
    """Download the three small official text files, never the cover archive."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, object]] = {}
    for logical_name, filename in OFFICIAL_FILES.items():
        destination = raw_dir / filename
        if force or not destination.exists():
            temporary = destination.with_suffix(destination.suffix + ".part")
            request = urllib.request.Request(
                f"{OFFICIAL_BASE_URL}/{filename}",
                headers={"User-Agent": "microlens-recsys-mvp/0.1"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                    if response.status != 200:
                        raise RuntimeError(
                            f"download failed for {filename}: HTTP {response.status}"
                        )
                    with temporary.open("wb") as target:
                        shutil.copyfileobj(response, target)
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        manifest[logical_name] = {
            "filename": filename,
            "url": f"{OFFICIAL_BASE_URL}/{filename}",
            "bytes": destination.stat().st_size,
            "sha256": _sha256(destination),
        }
    (raw_dir / "download_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def _parse_pairs(path: Path) -> tuple[pd.DataFrame, int]:
    records: list[tuple[int, int, int]] = []
    seen_users: set[int] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            user_text, items_text = line.split("\t", maxsplit=1)
            user_id = int(user_text)
            item_ids = [int(value) for value in items_text.split()]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid pairs row at line {line_number}") from exc
        if user_id <= 0 or any(item_id <= 0 for item_id in item_ids):
            raise ValueError(f"IDs must be positive at pairs line {line_number}")
        if user_id in seen_users:
            raise ValueError(f"duplicate user row at pairs line {line_number}: {user_id}")
        if len(item_ids) < 3:
            raise ValueError(f"user {user_id} has fewer than 3 interactions")
        seen_users.add(user_id)
        records.extend((user_id, item_id, position) for position, item_id in enumerate(item_ids))

    frame = pd.DataFrame(records, columns=["user_id", "item_id", "sequence_position"])
    if frame.empty:
        raise ValueError("pairs file contains no interactions")
    duplicate_rows = int(frame.duplicated(["user_id", "item_id"], keep="last").sum())
    if duplicate_rows:
        frame = frame.drop_duplicates(["user_id", "item_id"], keep="last")
        frame = frame.sort_values(["user_id", "sequence_position"], kind="stable")
        too_short = frame.groupby("user_id", sort=False).size().lt(3)
        if too_short.any():
            bad_user = int(too_short[too_short].index[0])
            raise ValueError(f"user {bad_user} has fewer than 3 unique items after deduplication")
        frame["sequence_position"] = frame.groupby("user_id", sort=False).cumcount()
    return frame.reset_index(drop=True), duplicate_rows


def _parse_titles(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, encoding="utf-8")
    if not {"item", "title"} <= set(frame.columns):
        raise ValueError("titles CSV must contain item and title columns")
    frame = frame[["item", "title"]].rename(columns={"item": "item_id"})
    frame["item_id"] = pd.to_numeric(frame["item_id"], errors="raise").astype("int64")
    if frame["item_id"].le(0).any() or frame["item_id"].duplicated().any():
        raise ValueError("titles contain invalid or duplicate item IDs")
    frame["title"] = frame["title"].fillna("").astype(str).str.strip()
    return frame


def _parse_stats(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        sep="\t",
        names=["item_id", "likes", "views"],
        header=None,
        encoding="utf-8",
    )
    for column in ["item_id", "likes", "views"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    if (
        frame["item_id"].le(0).any()
        or frame[["likes", "views"]].lt(0).any().any()
        or frame["item_id"].duplicated().any()
    ):
        raise ValueError("stats contain invalid or duplicate values")
    return frame


def _data_version(raw_dir: Path, duplicate_rows: int) -> str:
    digest = hashlib.sha256()
    for filename in OFFICIAL_FILES.values():
        digest.update(_sha256(raw_dir / filename).encode("ascii"))
    digest.update(f"leave-last-two-v1:{duplicate_rows}".encode())
    return digest.hexdigest()[:12]


def _build_matrix(
    frame: pd.DataFrame,
    user_to_index: dict[int, int],
    item_to_index: dict[int, int],
) -> sparse.csr_matrix:
    rows = frame["user_id"].map(user_to_index).to_numpy(dtype=np.int32)
    columns = frame["item_id"].map(item_to_index).to_numpy(dtype=np.int32)
    values = np.ones(len(frame), dtype=np.float32)
    matrix = sparse.coo_matrix(
        (values, (rows, columns)), shape=(len(user_to_index), len(item_to_index))
    ).tocsr()
    matrix.sum_duplicates()
    return matrix


def prepare_dataset(raw_dir: Path, processed_root: Path) -> PreparedDataset:
    """Validate, chronological-split and materialise CSV/CSR artifacts."""
    missing_files = [name for name in OFFICIAL_FILES.values() if not (raw_dir / name).is_file()]
    if missing_files:
        raise FileNotFoundError(f"missing raw files: {', '.join(missing_files)}")

    interactions, duplicate_rows = _parse_pairs(raw_dir / OFFICIAL_FILES["pairs"])
    titles = _parse_titles(raw_dir / OFFICIAL_FILES["titles"])
    stats = _parse_stats(raw_dir / OFFICIAL_FILES["stats"])

    group_sizes = interactions.groupby("user_id", sort=False)["item_id"].transform("size")
    interactions["split"] = "train"
    interactions.loc[
        interactions["sequence_position"].eq(group_sizes - 2), "split"
    ] = "validation"
    interactions.loc[interactions["sequence_position"].eq(group_sizes - 1), "split"] = "test"
    # The official pairs file contains order only. This synthetic UTC value is an export aid,
    # while sequence_position remains the authoritative chronology field.
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    interactions["timestamp"] = interactions["sequence_position"].map(
        lambda position: (epoch + timedelta(seconds=int(position))).isoformat()
    )

    referenced_items = set(interactions["item_id"].unique().tolist())
    titled_items = set(titles.loc[titles["title"].ne(""), "item_id"].tolist())
    stats_items = set(stats["item_id"].tolist())
    missing_titles = len(referenced_items - titled_items)
    missing_stats = len(referenced_items - stats_items)

    all_items = sorted(referenced_items | set(titles["item_id"]) | stats_items)
    user_ids = sorted(interactions["user_id"].unique().tolist())
    item_ids = [int(item_id) for item_id in all_items]
    user_to_index = {int(user_id): index for index, user_id in enumerate(user_ids)}
    item_to_index = {item_id: index for index, item_id in enumerate(item_ids)}

    items = pd.DataFrame({"item_id": item_ids})
    items = items.merge(titles, how="left", on="item_id").merge(stats, how="left", on="item_id")
    items["title"] = items["title"].fillna("")
    items[["likes", "views"]] = items[["likes", "views"]].fillna(0).astype("int64")

    data_version = _data_version(raw_dir, duplicate_rows)
    output = processed_root / data_version
    output.mkdir(parents=True, exist_ok=True)
    export_columns = ["user_id", "item_id", "sequence_position", "timestamp", "split"]
    interactions.to_csv(output / "interactions.csv", columns=export_columns, index=False)
    for split in ["train", "validation", "test"]:
        interactions.loc[interactions["split"].eq(split), export_columns].to_csv(
            output / f"{split}.csv", index=False
        )
    train_histories = (
        interactions.loc[interactions["split"].eq("train")]
        .sort_values(["user_id", "sequence_position"], kind="stable")
        .groupby("user_id", sort=False)["item_id"]
        .apply(lambda values: json.dumps([int(value) for value in values]))
        .rename("history_item_ids")
        .reset_index()
    )
    train_histories.to_csv(output / "user_histories.csv", index=False)
    items.to_csv(output / "items.csv", index=False)

    matrices = {}
    for split in ["train", "validation", "test"]:
        matrices[split] = _build_matrix(
            interactions.loc[interactions["split"].eq(split)], user_to_index, item_to_index
        )
        sparse.save_npz(output / f"{split}_matrix.npz", matrices[split], compressed=True)

    summary = DataSummary(
        users=len(user_ids),
        items=len(item_ids),
        interactions=len(interactions),
        min_timestamp=epoch,
        max_timestamp=epoch + timedelta(seconds=int(interactions["sequence_position"].max())),
        train_interactions=int(interactions["split"].eq("train").sum()),
        validation_interactions=int(interactions["split"].eq("validation").sum()),
        test_interactions=int(interactions["split"].eq("test").sum()),
        duplicate_rows=duplicate_rows,
        missing_titles=missing_titles,
        missing_stats=missing_stats,
    )
    (output / "summary.json").write_text(
        json.dumps(
            {
                **summary.model_dump(mode="json"),
                "data_version": data_version,
                "ordering_basis": "per-user sequence from official pairs file",
                "absolute_timestamps_available": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output / "mappings.json").write_text(
        json.dumps({"user_ids": user_ids, "item_ids": item_ids}, ensure_ascii=False),
        encoding="utf-8",
    )
    (processed_root / "latest.json").write_text(
        json.dumps({"data_version": data_version, "path": data_version}, indent=2),
        encoding="utf-8",
    )
    return PreparedDataset(output, data_version, summary, user_ids, item_ids)


def load_prepared_dataset(path: Path) -> PreparedDataset:
    if path.name == "latest.json":
        pointer = json.loads(path.read_text(encoding="utf-8"))
        path = path.parent / pointer["path"]
    summary_payload = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    mappings = json.loads((path / "mappings.json").read_text(encoding="utf-8"))
    return PreparedDataset(
        path=path,
        data_version=summary_payload["data_version"],
        summary=DataSummary.model_validate(summary_payload),
        user_ids=[int(value) for value in mappings["user_ids"]],
        item_ids=[int(value) for value in mappings["item_ids"]],
    )
