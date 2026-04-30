from __future__ import annotations

import marshal
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


CHECKS = {
    "utils": ("get_exif 开始，当前 EXIF 后端", "Python EXIF 读取成功"),
    "semi_bridge": ("实时预览开始", "预览 EXIF 缓存未命中"),
    "init": ("Config path:", "Configured EXIF backend:"),
    "gen_video": ("subprocess_no_window_kwargs", "_run_ffmpeg"),
}


def walk(code):
    yield code
    for value in code.co_consts:
        if hasattr(value, "co_consts"):
            yield from walk(value)


def module_codes(pyz, module_name: str):
    return list(walk(marshal.loads(pyz.extract(module_name, raw=True))))


def module_tokens(pyz, module_name: str) -> list[str]:
    result: list[str] = []
    for code in module_codes(pyz, module_name):
        result.extend(value for value in code.co_consts if isinstance(value, str))
        result.extend(code.co_names)
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_packaged_modules.py <SemiUtilsQt.exe>")

    exe = Path(sys.argv[1]).resolve()
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    failures: list[str] = []

    for module_name, markers in CHECKS.items():
        tokens = module_tokens(pyz, module_name)
        for marker in markers:
            if not any(marker in token for token in tokens):
                failures.append(f"{module_name}: missing marker {marker!r}")

    utils_tokens = module_tokens(pyz, "utils")
    if any("get_exif error:" in token for token in utils_tokens):
        failures.append("utils: old parent-directory get_exif implementation detected")

    image_container_codes = module_codes(pyz, "entity.image_container")
    init_functions = [code for code in image_container_codes if code.co_name == "__init__"]
    if not init_functions or max(code.co_argcount for code in init_functions) < 3:
        failures.append("entity.image_container: staged ImageContainer.__init__(path, exif=None) not packaged")

    if failures:
        print("packaged source verification failed:")
        for failure in failures:
            print(f" - {failure}")
        raise SystemExit(1)

    print("packaged source verification passed.")


if __name__ == "__main__":
    main()
