from __future__ import annotations

import logging
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Callable

from PIL import Image as PILImage

from entity.image_container import ImageContainer
from entity.image_processor import MarginProcessor
from entity.image_processor import PaddingToOriginalRatioProcessor
from entity.image_processor import ProcessorChain
from entity.image_processor import ShadowProcessor
from entity.image_processor import SimpleProcessor
from gen_video import generate_video
from init import ITEM_LIST
from init import LAYOUT_ITEMS
from init import config
import utils as runtime_utils

EXIF_BACKEND_PYTHON = getattr(runtime_utils, "EXIF_BACKEND_PYTHON", "python")
EXIF_BACKEND_EXIFTOOL = getattr(runtime_utils, "EXIF_BACKEND_EXIFTOOL", "exiftool")


def get_exif(path: str | Path, on_message: Callable[[str], None] | None = None) -> dict:
    reader = runtime_utils.get_exif
    if on_message is None:
        return reader(path)
    try:
        return reader(path, on_message=on_message)
    except TypeError as exc:
        if "on_message" not in str(exc):
            raise
        return reader(path)


def normalize_exif_backend(backend: str | None) -> str:
    normalizer = getattr(runtime_utils, "normalize_exif_backend", None)
    if callable(normalizer):
        return normalizer(backend)
    if str(backend or "").strip().lower() == EXIF_BACKEND_EXIFTOOL:
        return EXIF_BACKEND_EXIFTOOL
    return EXIF_BACKEND_PYTHON


def set_exif_backend(backend: str | None) -> None:
    setter = getattr(runtime_utils, "set_exif_backend", None)
    if callable(setter):
        setter(normalize_exif_backend(backend))


def get_exif_backend() -> str:
    getter = getattr(runtime_utils, "get_exif_backend", None)
    if callable(getter):
        return normalize_exif_backend(getter())
    return EXIF_BACKEND_PYTHON

logger = logging.getLogger(__name__)

LOCATION_KEYS = ("left_top", "right_top", "left_bottom", "right_bottom")
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}
_PREVIEW_EXIF_CACHE_MAX = 16
_preview_exif_cache: dict[str, tuple[tuple[int, int], dict]] = {}

# 使用 init.py 中已注册的布局信息，避免重复维护“布局ID -> 处理器类”的映射。
_LAYOUT_CLASS_MAP = {item.value: item.processor.__class__ for item in LAYOUT_ITEMS}


def _get_config_exif_backend(data: dict) -> str:
    exif_data = data.get("global", {}).get("exif", {})
    if not isinstance(exif_data, dict):
        return EXIF_BACKEND_PYTHON
    return normalize_exif_backend(exif_data.get("backend", EXIF_BACKEND_PYTHON))


set_exif_backend(_get_config_exif_backend(config.get_data()))


@dataclass
class ProcessSummary:
    total: int = 0
    success: int = 0
    failed: int = 0
    stopped: bool = False
    failed_files: list[str] = field(default_factory=list)


def get_layout_options() -> list[tuple[str, str]]:
    return [(item.name, item.value) for item in LAYOUT_ITEMS]


def get_element_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for item in ITEM_LIST:
        display_name = str(getattr(item, "name", "") or "")
        value = str(getattr(item, "value", "") or "")
        # 原始 ITEM_LIST 中存在仅空格的占位项，这里移除。
        if not display_name.strip():
            continue
        options.append((display_name, value))

    options.append(("拍摄者", "Photographer"))
    return options


def get_default_logo_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for make_key, make_config in config.get_data().get("logo", {}).get("makes", {}).items():
        label = make_config.get("id") or make_key
        options.append((label, make_config.get("path", "")))
    return options


def get_font_options() -> list[tuple[str, str]]:
    """返回可选字体列表，优先扫描 qt_gui/fonts，并补充当前配置中的字体路径。"""
    fonts_dir = Path(__file__).resolve().parent.joinpath("fonts")
    options: list[tuple[str, str]] = []
    seen: set[str] = set()
    allowed_suffixes = {".ttf", ".otf", ".ttc", ".otc"}

    if fonts_dir.exists() and fonts_dir.is_dir():
        for font_file in sorted(fonts_dir.iterdir(), key=lambda item: item.name.lower()):
            if not font_file.is_file() or font_file.suffix.lower() not in allowed_suffixes:
                continue
            key = str(font_file)
            if key in seen:
                continue
            seen.add(key)
            options.append((font_file.name, key))

    base_data = config.get_data().get("base", {})
    for key_name in ("font", "bold_font", "alternative_font", "alternative_bold_font"):
        font_path = str(base_data.get(key_name, "") or "")
        if not font_path or font_path in seen:
            continue
        seen.add(font_path)
        options.append((Path(font_path).name, font_path))

    return options


def get_exif_backend_options() -> list[tuple[str, str]]:
    return [
        ("Python 包（默认）", EXIF_BACKEND_PYTHON),
        ("ExifTool", EXIF_BACKEND_EXIFTOOL),
    ]


def get_source_file_list(input_dir: str) -> list[Path]:
    return _get_source_file_list(input_dir)


def normalize_source_files(file_paths: list[str | Path] | None) -> list[Path]:
    if not file_paths:
        return []
    normalized: list[Path] = []
    seen: set[str] = set()
    for file_path in file_paths:
        path_obj = Path(file_path).resolve()
        if not path_obj.exists() or not path_obj.is_file():
            continue
        if path_obj.suffix not in SUPPORTED_SUFFIXES:
            continue
        key = str(path_obj)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path_obj)
    return normalized


def get_runtime_config_snapshot() -> dict:
    data = config.get_data()
    element_data = data["layout"]["elements"]

    return {
        "input_dir": data["base"].get("input_dir", "./input"),
        "output_dir": data["base"].get("output_dir", "./output"),
        "quality": int(data["base"].get("quality", 100)),
        "font_path": data["base"].get("font", ""),
        "bold_font_path": data["base"].get("bold_font", ""),
        "layout_type": data["layout"].get("type", "simple"),
        "logo_enable": bool(data["layout"].get("logo_enable", False)),
        "default_logo_path": data["logo"]["default"].get("path", ""),
        "white_margin": bool(data["global"]["white_margin"].get("enable", True)),
        "shadow": bool(data["global"]["shadow"].get("enable", False)),
        "equivalent_focal": bool(data["global"]["focal_length"].get("use_equivalent_focal_length", False)),
        "padding_ratio": bool(data["global"]["padding_with_original_ratio"].get("enable", False)),
        "exif_backend": _get_config_exif_backend(data),
        "elements": {
            location: {
                "name": element_data[location].get("name", ""),
                "custom_value": element_data[location].get("value", ""),
            }
            for location in LOCATION_KEYS
        },
    }


def apply_runtime_config_from_values(values: dict, save: bool = True, ensure_output_dir: bool = True) -> None:
    """将 GUI 输入的设置写回全局配置对象。"""
    data = config.get_data()

    base_data = data["base"]
    layout_data = data["layout"]
    global_data = data["global"]

    input_dir = values.get("input_dir", base_data.get("input_dir", "./input")).strip()
    output_dir = values.get("output_dir", base_data.get("output_dir", "./output")).strip()

    base_data["input_dir"] = input_dir
    base_data["output_dir"] = output_dir
    base_data["quality"] = int(values.get("quality", base_data.get("quality", 100)))

    font_path = str(values.get("font_path", base_data.get("font", "")) or "").strip()
    bold_font_path = str(values.get("bold_font_path", base_data.get("bold_font", "")) or "").strip()
    if font_path:
        base_data["font"] = font_path
        base_data["alternative_font"] = font_path
    if bold_font_path:
        base_data["bold_font"] = bold_font_path
        base_data["alternative_bold_font"] = bold_font_path

    if output_dir and ensure_output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    layout_data["type"] = values.get("layout_type", layout_data.get("type", "simple"))
    layout_data["logo_enable"] = bool(values.get("logo_enable", layout_data.get("logo_enable", False)))

    selected_logo_path = values.get("default_logo_path", "")
    if selected_logo_path and selected_logo_path != data["logo"]["default"].get("path", ""):
        data["logo"]["default"]["path"] = selected_logo_path
        if hasattr(config, "_logos"):
            config._logos.clear()

    global_data["white_margin"]["enable"] = bool(values.get("white_margin", global_data["white_margin"].get("enable", True)))
    global_data["shadow"]["enable"] = bool(values.get("shadow", global_data["shadow"].get("enable", False)))
    global_data["focal_length"]["use_equivalent_focal_length"] = bool(
        values.get("equivalent_focal", global_data["focal_length"].get("use_equivalent_focal_length", False))
    )
    global_data["padding_with_original_ratio"]["enable"] = bool(
        values.get("padding_ratio", global_data["padding_with_original_ratio"].get("enable", False))
    )
    exif_data = global_data.setdefault("exif", {})
    exif_backend = normalize_exif_backend(values.get("exif_backend", exif_data.get("backend", EXIF_BACKEND_PYTHON)))
    exif_data["backend"] = exif_backend
    set_exif_backend(exif_backend)

    element_values = values.get("elements", {})
    for location in LOCATION_KEYS:
        value = element_values.get(location, {})
        element_name = value.get("name", layout_data["elements"][location].get("name", ""))
        layout_data["elements"][location]["name"] = element_name
        if element_name == "Custom":
            layout_data["elements"][location]["value"] = value.get("custom_value", "")

    if save:
        config.save()


def _build_processor_chain() -> ProcessorChain:
    chain = ProcessorChain()
    layout_type = config.get_layout_type()

    # 处理顺序与原 CLI 一致：阴影 -> 主布局 -> 白边 -> 按比例补边。
    if config.has_shadow_enabled() and layout_type != "square":
        chain.add(ShadowProcessor(config))

    processor_cls = _LAYOUT_CLASS_MAP.get(layout_type, SimpleProcessor)
    layout_processor = processor_cls(config)

    # 原项目中 CustomWatermarkProcessor 对 logo_position 的初始化是 bool，这里修正为 left/right 字符串。
    if getattr(layout_processor, "LAYOUT_ID", "") == "custom_watermark":
        layout_processor.logo_position = "left" if config.is_logo_left() else "right"
        layout_processor.logo_enable = config.has_logo_enabled()

    chain.add(layout_processor)

    if config.has_white_margin_enabled() and "watermark" in layout_type:
        chain.add(MarginProcessor(config))

    if config.has_padding_with_original_ratio_enabled() and layout_type != "square":
        chain.add(PaddingToOriginalRatioProcessor(config))

    return chain


def _safe_close_container(container: ImageContainer) -> None:
    try:
        container.close()
    except Exception:
        try:
            container.get_img().close()
        except Exception:
            pass


def _resolve_target_path(source_path: Path) -> Path:
    output_dir = config.get_output_dir()
    if output_dir:
        return Path(output_dir).joinpath(source_path.name)

    source_target = source_path.parent.joinpath(source_path.name)
    if source_target.exists():
        stamp = datetime.now().strftime("%m%d-%H%M")
        return source_target.with_name(f"{source_target.stem}{stamp}{source_target.suffix}")
    return source_target


def _get_source_file_list(input_dir: str) -> list[Path]:
    source_dir = Path(input_dir)
    if not source_dir.exists() or not source_dir.is_dir():
        return []

    return [file_path for file_path in source_dir.iterdir() if file_path.is_file() and file_path.suffix in SUPPORTED_SUFFIXES]


def _process_one_image(
    source_path: Path,
    processor_chain: ProcessorChain,
    on_message: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    container = None
    runtime_backup: dict[str, tuple[str, str]] = {}
    try:
        source_exif = get_exif(source_path, on_message=on_message)
        container = ImageContainer(source_path, exif=source_exif)
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())
        runtime_backup = _apply_photographer_runtime_mapping(container)
        processor_chain.process(container)

        target_path = _resolve_target_path(source_path)
        container.save(target_path, quality=config.get_quality())

        return True, f"完成：{source_path.name} -> {target_path}"
    except Exception as exc:
        logger.exception("处理失败：%s", source_path)
        return False, f"失败：{source_path.name}，原因：{exc}"
    finally:
        _restore_element_runtime_mapping(runtime_backup)
        if container is not None:
            _safe_close_container(container)


def process_images(
    source_files: list[str | Path] | None = None,
    on_progress: Callable[[int, int, str, bool, str], None] | None = None,
    on_message: Callable[[str], None] | None = None,
    stop_checker: Callable[[], bool] | None = None,
) -> ProcessSummary:
    summary = ProcessSummary()
    file_list = normalize_source_files(source_files) if source_files else _get_source_file_list(config.get_input_dir())
    summary.total = len(file_list)

    if summary.total == 0:
        if on_message:
            on_message("输入目录中没有可处理的图片（支持 jpg/jpeg/png）。")
        return summary

    if on_message:
        on_message(f"准备开始处理，共 {summary.total} 张图片。")

    processor_chain = _build_processor_chain()

    for index, source_path in enumerate(file_list, start=1):
        if stop_checker and stop_checker():
            summary.stopped = True
            if on_message:
                on_message("收到停止请求，任务已提前结束。")
            break

        ok, message = _process_one_image(source_path, processor_chain, on_message=on_message)
        if ok:
            summary.success += 1
        else:
            summary.failed += 1
            summary.failed_files.append(message)

        if on_progress:
            on_progress(index, summary.total, source_path.name, ok, message)
        if on_message:
            on_message(f"[{index}/{summary.total}] {message}")

    if not summary.stopped and on_message:
        on_message("图片处理流程已结束。")

    return summary


def _resize_for_preview(image: PILImage.Image, max_side: int = 960) -> PILImage.Image:
    preview = image.copy()
    preview.thumbnail((max_side, max_side), PILImage.Resampling.LANCZOS)
    return preview


def _get_cached_preview_exif(sample_file: Path, on_message: Callable[[str], None] | None = None) -> dict:
    stat = sample_file.stat()
    cache_key = f"{get_exif_backend()}:{sample_file.resolve()}"
    cache_token = (stat.st_mtime_ns, stat.st_size)
    cached = _preview_exif_cache.get(cache_key)
    if cached is not None and cached[0] == cache_token:
        return cached[1].copy()

    exif = get_exif(sample_file, on_message=on_message)
    _preview_exif_cache[cache_key] = (cache_token, exif.copy())
    while len(_preview_exif_cache) > _PREVIEW_EXIF_CACHE_MAX:
        _preview_exif_cache.pop(next(iter(_preview_exif_cache)))
    return exif


def _create_image_container(sample_file: Path, exif: dict | None = None) -> ImageContainer:
    if exif is None:
        return ImageContainer(sample_file)
    try:
        return ImageContainer(sample_file, exif=exif)
    except TypeError as exc:
        if "unexpected keyword argument 'exif'" not in str(exc):
            raise
        logger.warning("ImageContainer does not accept cached EXIF; falling back to direct EXIF read.")
        return ImageContainer(sample_file)


def _build_preview_container(sample_file: Path, max_side: int, exif: dict | None = None) -> ImageContainer:
    container = _create_image_container(sample_file, exif if exif is not None else _get_cached_preview_exif(sample_file))
    image = container.get_img()
    if max(image.width, image.height) <= max_side:
        return container

    preview_image = image.copy()
    preview_image.thumbnail((max_side, max_side), PILImage.Resampling.LANCZOS)
    image.close()
    container.img = preview_image
    container.watermark_img = None
    return container


def build_preview_images(
    sample_path: str | Path,
    values: dict,
    max_side: int = 960,
    exif: dict | None = None,
) -> tuple[PILImage.Image, PILImage.Image, str]:
    """基于当前设置处理一张示例图，并返回预览前后图像。"""
    sample_file = Path(sample_path)
    if not sample_file.exists() or not sample_file.is_file():
        raise FileNotFoundError(f"示例图片不存在：{sample_file}")

    apply_runtime_config_from_values(values, save=False, ensure_output_dir=False)

    container = None
    before = None
    after = None
    runtime_backup: dict[str, tuple[str, str]] = {}
    try:
        container = _build_preview_container(sample_file, max_side, exif=exif)
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())

        before = _resize_for_preview(container.get_img(), max_side=max_side)

        runtime_backup = _apply_photographer_runtime_mapping(container)
        processor_chain = _build_processor_chain()
        processor_chain.process(container)

        after = _resize_for_preview(container.get_watermark_img(), max_side=max_side)

        message = f"预览完成：{sample_file.name}"
        return before, after, message
    except Exception as exc:
        if before is not None:
            before.close()
        if after is not None:
            after.close()
        raise RuntimeError(f"预览生成失败：{exc}") from exc
    finally:
        _restore_element_runtime_mapping(runtime_backup)
        if container is not None:
            _safe_close_container(container)


def build_preview_image_with_exif(
    sample_path: str | Path,
    values: dict,
    max_side: int = 960,
    exif: dict | None = None,
) -> tuple[PILImage.Image, dict, dict, str]:
    """基于当前设置处理一张示例图，并在同一次读取中返回处理后预览和 EXIF 预览。"""
    sample_file = Path(sample_path)
    if not sample_file.exists() or not sample_file.is_file():
        raise FileNotFoundError(f"示例图片不存在：{sample_file}")

    apply_runtime_config_from_values(values, save=False, ensure_output_dir=False)

    container = None
    after = None
    runtime_backup: dict[str, tuple[str, str]] = {}
    exif_messages: list[str] = []
    source_exif = exif.copy() if exif is not None else _get_cached_preview_exif(sample_file, on_message=exif_messages.append)
    try:
        container = _build_preview_container(sample_file, max_side, exif=source_exif)
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())

        exif_preview = _collect_exif_preview_from_container(container)

        runtime_backup = _apply_photographer_runtime_mapping(container)
        processor_chain = _build_processor_chain()
        processor_chain.process(container)

        after = _resize_for_preview(container.get_watermark_img(), max_side=max_side)

        message = "\n".join(exif_messages)
        return after, exif_preview, source_exif.copy(), message
    except Exception as exc:
        if after is not None:
            after.close()
        raise RuntimeError(f"预览生成失败：{exc}") from exc
    finally:
        _restore_element_runtime_mapping(runtime_backup)
        if container is not None:
            _safe_close_container(container)


def _format_param_exif(container: ImageContainer) -> str:
    focal = container.exif.get("FocalLength", "--")
    f_number = container.exif.get("FNumber", "--")
    exposure = container.exif.get("ExposureTime", "--")
    iso = container.exif.get("ISO", "--")
    return f"焦距={focal}; 光圈={f_number}; 快门={exposure}; ISO={iso}"


def _format_element_exif(container: ImageContainer, element_name: str, rendered_value: str, custom_value: str) -> str:
    exif = container.exif
    if element_name == "Model":
        return f"CameraModelName: {exif.get('CameraModelName', '--')}"
    if element_name == "Make":
        return f"Make: {exif.get('Make', '--')}"
    if element_name == "LensModel":
        lens_value = exif.get("LensModel") or exif.get("Lens") or exif.get("LensID") or "--"
        return f"LensModel/Lens/LensID: {lens_value}"
    if element_name == "Param":
        return _format_param_exif(container)
    if element_name in {"Datetime", "Date"}:
        return f"DateTimeOriginal: {exif.get('DateTimeOriginal', '--')}"
    if element_name == "GeoInfo":
        if "GPSPosition" in exif:
            return f"GPSPosition: {exif.get('GPSPosition', '--')}"
        lat = exif.get("GPSLatitude", "--")
        lng = exif.get("GPSLongitude", "--")
        return f"GPSLatitude/GPSLongitude: {lat} / {lng}"
    if element_name == "Photographer":
        return f"拍摄者: {_resolve_photographer_name(exif)}"
    if element_name == "Custom":
        return f"Custom: {custom_value or '--'}"
    if element_name == "None":
        return "当前元素未启用"
    return rendered_value or "--"


def _resolve_photographer_name(exif: dict) -> str:
    for key in ("Artist", "Author", "Creator", "By-line", "XPAuthor", "Copyright"):
        value = exif.get(key)
        if isinstance(value, bytes):
            for encoding in ("utf-16-le", "utf-8", "latin1"):
                try:
                    value = value.decode(encoding, errors="ignore")
                    break
                except Exception:
                    continue
        text = str(value or "").strip().strip("\x00")
        if text:
            return text
    return "--"


def _apply_photographer_runtime_mapping(container: ImageContainer) -> dict[str, tuple[str, str]]:
    """把 Photographer 临时映射为 Custom，便于复用原有渲染链。"""
    layout_elements = config.get_data().get("layout", {}).get("elements", {})
    photographer = _resolve_photographer_name(container.exif)
    backup: dict[str, tuple[str, str]] = {}

    for location in LOCATION_KEYS:
        element_cfg = layout_elements.get(location, {})
        if element_cfg.get("name") != "Photographer":
            continue
        old_name = str(element_cfg.get("name", "") or "")
        old_value = str(element_cfg.get("value", "") or "")
        backup[location] = (old_name, old_value)
        element_cfg["name"] = "Custom"
        element_cfg["value"] = "" if photographer == "--" else photographer

    return backup


def _restore_element_runtime_mapping(backup: dict[str, tuple[str, str]]) -> None:
    if not backup:
        return
    layout_elements = config.get_data().get("layout", {}).get("elements", {})
    for location, (old_name, old_value) in backup.items():
        if location not in layout_elements:
            continue
        layout_elements[location]["name"] = old_name
        layout_elements[location]["value"] = old_value


def _resolve_logo_info(make: str) -> dict:
    logo_config = config.get_data().get("logo", {})
    makes = logo_config.get("makes", {})
    default_logo = logo_config.get("default", {})
    normalized_make = (make or "").lower()

    for make_key, make_item in makes.items():
        make_id = (make_item.get("id") or "").lower()
        if make_id and make_id in normalized_make:
            return {
                "make": make or "--",
                "matched_logo_key": make_key,
                "matched_logo_path": make_item.get("path", ""),
                "matched_logo_label": make_item.get("id") or make_key,
            }

    default_path = default_logo.get("path", "")
    default_label = default_logo.get("id", "") or Path(default_path).stem or "default"
    return {
        "make": make or "--",
        "matched_logo_key": "default",
        "matched_logo_path": default_path,
        "matched_logo_label": default_label,
    }


def _collect_exif_preview_from_container(container: ImageContainer) -> dict:
    data = config.get_data().get("layout", {}).get("elements", {})
    location_to_element_getter = {
        "left_top": config.get_left_top,
        "right_top": config.get_right_top,
        "left_bottom": config.get_left_bottom,
        "right_bottom": config.get_right_bottom,
    }

    element_info: dict[str, str] = {}
    for location in LOCATION_KEYS:
        getter = location_to_element_getter[location]
        element_name = data.get(location, {}).get("name", "")
        custom_value = data.get(location, {}).get("value", "")
        if element_name == "Photographer":
            rendered_value = _resolve_photographer_name(container.exif)
        else:
            rendered_value = container.get_attribute_str(getter())
        exif_text = _format_element_exif(container, element_name, rendered_value, custom_value)
        element_info[location] = exif_text

    return {
        "logo": _resolve_logo_info(container.make),
        "elements": element_info,
    }


def get_image_exif_preview(sample_path: str | Path, values: dict) -> dict:
    sample_file = Path(sample_path)
    if not sample_file.exists() or not sample_file.is_file():
        raise FileNotFoundError(f"示例图片不存在：{sample_file}")

    apply_runtime_config_from_values(values, save=False, ensure_output_dir=False)

    container = None
    try:
        container = _create_image_container(sample_file, _get_cached_preview_exif(sample_file))
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())
        return _collect_exif_preview_from_container(container)
    finally:
        if container is not None:
            _safe_close_container(container)


def generate_video_with_logs(gap_seconds: int) -> tuple[str, str]:
    """执行视频生成，并把控制台输出作为文本返回给 GUI 展示。"""
    target_dir = config.get_output_dir() or config.get_input_dir()

    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        generate_video(target_dir, gap_seconds)

    return target_dir, output_buffer.getvalue().strip()
