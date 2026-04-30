from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


MODULES = (
    "main_gui",
    "semi_bridge",
    "init",
    "utils",
    "gen_video",
    "entity.config",
    "entity.image_container",
    "entity.image_processor",
    "entity.menu",
    "enums.constant",
)


def main() -> None:
    root = Path(os.environ["SEMI_QT_STAGE_DIR"]).resolve()
    if not root.is_dir():
        raise RuntimeError(f"staged source directory does not exist: {root}")

    sys.path[:] = [str(root)] + [p for p in sys.path if p not in ("", str(root))]

    failures: list[str] = []
    print(f"staged_import_root={root}")
    for module_name in MODULES:
        spec = importlib.util.find_spec(module_name)
        origin = Path(spec.origin).resolve() if spec and spec.origin else None
        print(f"{module_name}: {origin}")
        if origin is None:
            failures.append(f"{module_name}: missing")
            continue
        try:
            origin.relative_to(root)
        except ValueError:
            failures.append(f"{module_name}: resolves outside qt_gui staging: {origin}")

    if failures:
        print("staged import verification failed:")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)

    print("staged import verification passed.")


if __name__ == "__main__":
    main()
