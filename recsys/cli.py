from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer

from recsys.data import OFFICIAL_FILES, download_official_data, prepare_dataset
from recsys.model import train_pipeline

app = typer.Typer(no_args_is_help=True, help="MicroLens offline data and ALS pipeline.")


@app.command()
def download(
    raw_dir: Annotated[Path, typer.Option(help="Raw data directory.")] = Path("data/raw"),
    force: Annotated[bool, typer.Option(help="Replace existing official files.")] = False,
) -> None:
    typer.echo(json.dumps(download_official_data(raw_dir, force=force), indent=2))


@app.command()
def prepare(
    raw_dir: Annotated[Path, typer.Option(help="Raw data directory.")] = Path("data/raw"),
    processed_root: Annotated[
        Path, typer.Option(help="Versioned processed data root.")
    ] = Path("data/processed"),
) -> None:
    result = prepare_dataset(raw_dir, processed_root)
    typer.echo(
        json.dumps(
            {"data_version": result.data_version, "path": str(result.path)}, indent=2
        )
    )


@app.command()
def train(
    processed_path: Annotated[
        Path, typer.Option(help="Prepared version directory or root with latest.json.")
    ] = Path("data/processed"),
    artifact_root: Annotated[Path, typer.Option(help="Versioned model root.")] = Path(
        "artifacts"
    ),
    config: Annotated[Path, typer.Option(help="Training TOML config.")] = Path(
        "configs/als.toml"
    ),
    activate: Annotated[
        bool,
        typer.Option(help="Bootstrap latest.json immediately instead of publishing via admin."),
    ] = False,
) -> None:
    output = train_pipeline(processed_path, artifact_root, config, activate=activate)
    typer.echo(json.dumps({"artifact_path": str(output)}, indent=2))


def _write_smoke_raw(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / OFFICIAL_FILES["pairs"]).write_text(
        "1\t1 2 3 4 5\n"
        "2\t2 3 1 5 6\n"
        "3\t3 1 2 6 4\n"
        "4\t1 3 2 4 6\n",
        encoding="utf-8",
    )
    (raw_dir / OFFICIAL_FILES["titles"]).write_text(
        "item,title\n" + "".join(f'{item},"Item {item}"\n' for item in range(1, 7)),
        encoding="utf-8",
    )
    (raw_dir / OFFICIAL_FILES["stats"]).write_text(
        "".join(f"{item}\t{item * 10}\t{item * 100}\n" for item in range(1, 7)),
        encoding="utf-8",
    )


@app.command("offline-smoke")
def offline_smoke(
    work_dir: Annotated[
        Path | None,
        typer.Option(help="Persistent smoke output; defaults to a temporary directory."),
    ] = None,
) -> None:
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="microlens-offline-smoke-"))
    data_version, _, artifact, _ = _build_smoke_artifact(work_dir)
    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "data_version": data_version,
                "artifact_path": str(artifact),
            },
            indent=2,
        )
    )


def _build_smoke_artifact(
    work_dir: Path,
    *,
    activate: bool = False,
) -> tuple[str, Path, Path, Path]:
    raw_dir = work_dir / "raw"
    processed_root = work_dir / "processed"
    artifact_root = work_dir / "artifacts"
    config = work_dir / "smoke.toml"
    _write_smoke_raw(raw_dir)
    config.write_text(
        "[data]\nseed = 42\n\n"
        "[model]\nfactors = [2, 3]\niterations = 2\n"
        "regularization = 0.05\nalpha = 10.0\ntop_k = 2\n",
        encoding="utf-8",
    )
    prepared = prepare_dataset(raw_dir, processed_root)
    artifact = train_pipeline(
        prepared.path,
        artifact_root,
        config,
        activate=activate,
    )
    return prepared.data_version, prepared.path, artifact, config


@app.command()
def smoke() -> None:
    """Run the synthetic offline pipeline and the complete online API loop."""
    work_dir = Path(tempfile.mkdtemp(prefix="microlens-smoke-"))
    offline_root = work_dir / "offline"
    data_version, processed_path, current_artifact, config = _build_smoke_artifact(
        offline_root,
        activate=True,
    )
    candidate_artifact = train_pipeline(
        processed_path,
        offline_root / "artifacts",
        config,
    )
    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "data_version": data_version,
                "artifact_path": str(current_artifact),
                "candidate_path": str(candidate_artifact),
            },
            indent=2,
        )
    )

    os.environ["APP_DATABASE_URL"] = f"sqlite:///{(work_dir / 'app.db').as_posix()}"
    os.environ["APP_SEED_OFFICIAL_CATALOG"] = "false"
    os.environ["APP_ARTIFACT_DIR"] = str(offline_root / "artifacts")
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app
    from app.seed import DEMO_PASSWORD

    application = create_app(settings=Settings())
    with TestClient(application) as client:
        assert client.get("/api/health").status_code == 200
        assert client.post(
            "/api/auth/login",
            json={"username": "alice", "password": DEMO_PASSWORD},
        ).status_code == 200
        feed = client.get("/api/feeds/personalized?page_size=4")
        assert feed.status_code == 200 and len(feed.json()["items"]) == 4
        first_item = feed.json()["items"][0]
        behavior = client.post(
            "/api/events",
            json={
                "event_id": str(uuid4()),
                "request_id": feed.json()["request_id"],
                "item_id": first_item["item_id"],
                "event_type": "like",
            },
        )
        assert behavior.status_code == 200
        assert client.post("/api/auth/logout").status_code == 204

        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": DEMO_PASSWORD},
        ).status_code == 200
        runtime = client.get("/api/admin/models/runtime")
        assert runtime.status_code == 200
        assert runtime.json()["current"]["model_version"] == current_artifact.name
        publish = client.post(
            f"/api/admin/models/{candidate_artifact.name}/publish"
        )
        assert publish.status_code == 200
        assert publish.json()["current"]["model_version"] == candidate_artifact.name
        assert client.post("/api/auth/logout").status_code == 204

        assert client.post(
            "/api/auth/login",
            json={"username": "bob", "password": DEMO_PASSWORD},
        ).status_code == 200
        switched_feed = client.get("/api/feeds/personalized?page_size=4")
        assert switched_feed.status_code == 200
        assert switched_feed.json()["model_version"] == candidate_artifact.name
        assert client.post("/api/auth/logout").status_code == 204

        assert client.post(
            "/api/auth/login",
            json={"username": "admin", "password": DEMO_PASSWORD},
        ).status_code == 200
        rollback = client.post("/api/admin/models/rollback")
        assert rollback.status_code == 200
        assert rollback.json()["current"]["model_version"] == current_artifact.name
        force = client.post(
            "/api/admin/operations/force",
            json={"item_id": 40, "reason": "smoke force", "scope": "all"},
        )
        assert force.status_code == 200
        assert client.post("/api/auth/logout").status_code == 204

        client.post(
            "/api/auth/login",
            json={"username": "bob", "password": DEMO_PASSWORD},
        )
        forced_feed = client.get("/api/feeds/explore?page_size=4").json()
        assert forced_feed["items"][0]["item_id"] == 40
        assert forced_feed["items"][0]["source"] == "forced"
        client.post("/api/auth/logout")

        client.post(
            "/api/auth/login",
            json={"username": "admin", "password": DEMO_PASSWORD},
        )
        offline = client.post(
            "/api/admin/operations/offline",
            json={"item_id": 40, "reason": "smoke offline"},
        )
        assert offline.status_code == 200
        client.post("/api/auth/logout")
        client.post(
            "/api/auth/login",
            json={"username": "carol", "password": DEMO_PASSWORD},
        )
        assert client.get("/api/items/40").status_code == 404

    typer.echo(json.dumps({"status": "ok", "scope": "offline+online"}, indent=2))


if __name__ == "__main__":
    app()
