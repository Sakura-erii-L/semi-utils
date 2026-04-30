from __future__ import annotations

import os
import shutil
from pathlib import Path


SOURCE_MODULES = (
    "main_gui.py",
    "semi_bridge.py",
    "init.py",
    "utils.py",
    "gen_video.py",
    "__init__.py",
)

SOURCE_PACKAGES = ("entity", "enums")


def _require_under(path: Path, parent: Path, label: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise RuntimeError(f"{label} must stay under qt_gui: {path}") from exc


def main() -> None:
    root = Path(os.environ["SEMI_QT_STAGE_ROOT"]).resolve()
    stage = Path(os.environ["SEMI_QT_STAGE_DIR"]).resolve()

    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"qt_gui root does not exist: {root}")

    _require_under(stage, root, "stage directory")

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    for filename in SOURCE_MODULES:
        source = root / filename
        if not source.is_file():
            raise RuntimeError(f"required qt_gui module missing: {source}")
        shutil.copy2(source, stage / filename)

    for package_name in SOURCE_PACKAGES:
        source = root / package_name
        if not source.is_dir():
            raise RuntimeError(f"required qt_gui package missing: {source}")
        shutil.copytree(
            source,
            stage / package_name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )

    print(f"staged_root={stage}")
    for path in sorted(stage.rglob("*.py")):
        print(path.relative_to(stage).as_posix())


if __name__ == "__main__":
    main()
