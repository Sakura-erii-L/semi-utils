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

logger = logging.getLogger(__name__)

LOCATION_KEYS = ("left_top", "right_top", "left_bottom", "right_bottom")
SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"}

# 使用 init.py 中已注册的布局信息，避免重复维护“布局ID -> 处理器类”的映射。
_LAYOUT_CLASS_MAP = {item.value: item.processor.__class__ for item in LAYOUT_ITEMS}


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
    return [(item.name, item.value) for item in ITEM_LIST]


def get_default_logo_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for make_key, make_config in config.get_data().get("logo", {}).get("makes", {}).items():
        label = make_config.get("id") or make_key
        options.append((label, make_config.get("path", "")))
    return options


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
        "layout_type": data["layout"].get("type", "simple"),
        "logo_enable": bool(data["layout"].get("logo_enable", False)),
        "default_logo_path": data["logo"]["default"].get("path", ""),
        "white_margin": bool(data["global"]["white_margin"].get("enable", True)),
        "shadow": bool(data["global"]["shadow"].get("enable", False)),
        "equivalent_focal": bool(data["global"]["focal_length"].get("use_equivalent_focal_length", False)),
        "padding_ratio": bool(data["global"]["padding_with_original_ratio"].get("enable", False)),
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

    if output_dir and ensure_output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    layout_data["type"] = values.get("layout_type", layout_data.get("type", "simple"))
    layout_data["logo_enable"] = bool(values.get("logo_enable", layout_data.get("logo_enable", False)))

    selected_logo_path = values.get("default_logo_path", "")
    if selected_logo_path:
        data["logo"]["default"]["path"] = selected_logo_path

    global_data["white_margin"]["enable"] = bool(values.get("white_margin", global_data["white_margin"].get("enable", True)))
    global_data["shadow"]["enable"] = bool(values.get("shadow", global_data["shadow"].get("enable", False)))
    global_data["focal_length"]["use_equivalent_focal_length"] = bool(
        values.get("equivalent_focal", global_data["focal_length"].get("use_equivalent_focal_length", False))
    )
    global_data["padding_with_original_ratio"]["enable"] = bool(
        values.get("padding_ratio", global_data["padding_with_original_ratio"].get("enable", False))
    )

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


def _process_one_image(source_path: Path, processor_chain: ProcessorChain) -> tuple[bool, str]:
    container = None
    try:
        container = ImageContainer(source_path)
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())
        processor_chain.process(container)

        target_path = _resolve_target_path(source_path)
        container.save(target_path, quality=config.get_quality())

        return True, f"完成：{source_path.name} -> {target_path}"
    except Exception as exc:
        logger.exception("处理失败：%s", source_path)
        return False, f"失败：{source_path.name}，原因：{exc}"
    finally:
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

        ok, message = _process_one_image(source_path, processor_chain)
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


def _resize_for_preview(image: PILImage.Image, max_side: int = 1200) -> PILImage.Image:
    preview = image.copy()
    preview.thumbnail((max_side, max_side), PILImage.Resampling.LANCZOS)
    return preview


def build_preview_images(sample_path: str | Path, values: dict) -> tuple[PILImage.Image, PILImage.Image, str]:
    """基于当前设置处理一张示例图，并返回预览前后图像。"""
    sample_file = Path(sample_path)
    if not sample_file.exists() or not sample_file.is_file():
        raise FileNotFoundError(f"示例图片不存在：{sample_file}")

    apply_runtime_config_from_values(values, save=False, ensure_output_dir=False)

    container = None
    before = None
    after = None
    try:
        container = ImageContainer(sample_file)
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())

        before = _resize_for_preview(container.get_img())

        processor_chain = _build_processor_chain()
        processor_chain.process(container)

        after = _resize_for_preview(container.get_watermark_img())

        message = f"预览完成：{sample_file.name}"
        return before, after, message
    except Exception as exc:
        if before is not None:
            before.close()
        if after is not None:
            after.close()
        raise RuntimeError(f"预览生成失败：{exc}") from exc
    finally:
        if container is not None:
            _safe_close_container(container)


def _format_param_exif(container: ImageContainer) -> str:
    focal = container.exif.get("FocalLength", "--")
    f_number = container.exif.get("FNumber", "--")
    exposure = container.exif.get("ExposureTime", "--")
    iso = container.exif.get("ISO", "--")
    return f"FocalLength={focal}; FNumber={f_number}; ExposureTime={exposure}; ISO={iso}"


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
    if element_name == "Custom":
        return f"Custom: {custom_value or '--'}"
    if element_name == "None":
        return "当前元素未启用"
    return f"派生值: {rendered_value or '--'}"


def _resolve_logo_info(make: str) -> str:
    logo_config = config.get_data().get("logo", {})
    makes = logo_config.get("makes", {})
    default_path = logo_config.get("default", {}).get("path", "")
    normalized_make = (make or "").lower()
    for make_key, make_item in makes.items():
        make_id = (make_item.get("id") or "").lower()
        if make_id and make_id in normalized_make:
            return f"Make={make or '--'}; 匹配logo={make_key}; Path={make_item.get('path', '')}"
    return f"Make={make or '--'}; 使用默认logo; Path={default_path}"


def get_image_exif_preview(sample_path: str | Path, values: dict) -> dict:
    sample_file = Path(sample_path)
    if not sample_file.exists() or not sample_file.is_file():
        raise FileNotFoundError(f"示例图片不存在：{sample_file}")

    apply_runtime_config_from_values(values, save=False, ensure_output_dir=False)

    container = None
    try:
        container = ImageContainer(sample_file)
        container.is_use_equivalent_focal_length(config.use_equivalent_focal_length())

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
            rendered_value = container.get_attribute_str(getter())
            exif_text = _format_element_exif(container, element_name, rendered_value, custom_value)
            element_info[location] = f"当前值: {rendered_value or '--'} | EXIF: {exif_text}"

        return {
            "logo": _resolve_logo_info(container.make),
            "elements": element_info,
        }
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
