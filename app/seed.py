import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from app.constants import ModelStatus, UserRole
from app.models import Item, ModelVersion, User
from app.security import hash_password
from recsys.data import load_prepared_dataset
from recsys.model import ModelBundle

DEMO_PASSWORD = "DemoPass123!"


def _seed_official_items(session: Session, processed_dir: Path) -> None:
    dataset_path = (
        processed_dir / "latest.json"
        if (processed_dir / "latest.json").is_file()
        else processed_dir
    )
    dataset = load_prepared_dataset(dataset_path)
    train_counts: Counter[int] = Counter()
    with (dataset.path / "train.csv").open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            train_counts[int(row["item_id"])] += 1

    existing = {item.id: item for item in session.exec(select(Item)).all()}
    with (dataset.path / "items.csv").open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            item_id = int(row["item_id"])
            values = {
                "title": row["title"].strip() or f"MicroLens 内容 {item_id}",
                "likes": int(row["likes"]),
                "views": int(row["views"]),
                "train_interactions": train_counts[item_id],
            }
            item = existing.get(item_id)
            if item is None:
                session.add(Item(id=item_id, **values))
                continue
            for field, value in values.items():
                setattr(item, field, value)
            session.add(item)


def _seed_small_catalog(session: Session) -> None:
    existing_item_ids = set(session.exec(select(Item.id)).all())
    for item_id in range(1, 41):
        if item_id in existing_item_ids:
            continue
        session.add(
            Item(
                id=item_id,
                title=f"MicroLens 示例短视频 {item_id:02d}",
                likes=(item_id * 37) % 503,
                views=1_000 + (item_id * 173) % 7_000,
                train_interactions=41 - item_id,
            )
        )


def _seed_model_versions(
    session: Session,
    *,
    artifact_dir: Path,
    model_bundle: ModelBundle | None,
) -> None:
    fallback = session.get(ModelVersion, "deterministic-v1")
    if fallback is None:
        fallback = ModelVersion(
            id="deterministic-v1",
            status=ModelStatus.CANDIDATE if model_bundle else ModelStatus.PUBLISHED,
            data_version="demo-seed-v1",
            artifact_path="builtin://deterministic",
            metrics_json=json.dumps(
                {"kind": "fallback", "recall@20": None, "ndcg@20": None},
                ensure_ascii=False,
            ),
            trained_at=datetime(2026, 9, 1),
            published_at=None if model_bundle else datetime(2026, 9, 1),
        )
    elif model_bundle is not None:
        fallback.status = ModelStatus.CANDIDATE
        fallback.published_at = None
    session.add(fallback)

    if model_bundle is None:
        return
    manifest = model_bundle.manifest
    model_row = session.get(ModelVersion, manifest.model_version)
    if model_row is None:
        model_row = ModelVersion(
            id=manifest.model_version,
            status=ModelStatus.PUBLISHED,
            data_version=manifest.data_version,
            artifact_path=str(artifact_dir / manifest.model_version),
            metrics_json=json.dumps(
                {
                    "algorithm": manifest.algorithm,
                    "factors": manifest.factors,
                    "metrics": {
                        key: value.model_dump(mode="json")
                        for key, value in manifest.metrics.items()
                    },
                },
                ensure_ascii=False,
            ),
            trained_at=manifest.created_at.replace(tzinfo=None),
            published_at=manifest.created_at.replace(tzinfo=None),
        )
        session.add(model_row)


def seed_demo_data(
    session: Session,
    password: str = DEMO_PASSWORD,
    *,
    processed_dir: Path = Path("data/processed"),
    artifact_dir: Path = Path("artifacts"),
    model_bundle: ModelBundle | None = None,
    seed_official_catalog: bool = True,
) -> None:
    demo_users = (
        ("alice", UserRole.USER, 10_001),
        ("bob", UserRole.USER, 10_002),
        ("carol", UserRole.USER, 10_003),
        ("admin", UserRole.ADMIN, None),
    )
    existing_usernames = set(session.exec(select(User.username)).all())
    for username, role, source_user_id in demo_users:
        if username not in existing_usernames:
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    source_user_id=source_user_id,
                )
            )

    if seed_official_catalog:
        try:
            _seed_official_items(session, processed_dir)
        except (FileNotFoundError, ValueError, KeyError):
            _seed_small_catalog(session)
    else:
        _seed_small_catalog(session)

    _seed_model_versions(
        session,
        artifact_dir=artifact_dir,
        model_bundle=model_bundle,
    )
    session.commit()
