from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated

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
) -> None:
    output = train_pipeline(processed_path, artifact_root, config)
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
    artifact = train_pipeline(prepared.path, artifact_root, config)
    typer.echo(
        json.dumps(
            {
                "status": "ok",
                "data_version": prepared.data_version,
                "artifact_path": str(artifact),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    app()
