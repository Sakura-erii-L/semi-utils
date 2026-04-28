import logging
import atexit
import platform
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

try:
    import exifread
except ImportError:
    exifread = None

from PIL import ExifTags
from PIL import Image
from PIL import ImageDraw
from PIL import ImageOps

from enums.constant import TRANSPARENT

_RUNTIME_DIR = Path(__file__).resolve().parent


def _resolve_exiftool_path():
    executable_name = 'exiftool.exe' if platform.system() == 'Windows' else 'exiftool'
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().parent.joinpath('exiftool', executable_name))
        pyinstaller_temp = getattr(sys, '_MEIPASS', None)
        if pyinstaller_temp:
            candidates.append(Path(pyinstaller_temp).joinpath('exiftool', executable_name))

    if platform.system() == 'Windows':
        candidates.extend([
            _RUNTIME_DIR.joinpath('qt_gui', 'exiftool', executable_name),
            _RUNTIME_DIR.joinpath('exiftool', executable_name),
        ])
        for candidate in candidates:
            if candidate.exists():
                return candidate
        system_exiftool = shutil.which(executable_name)
        if system_exiftool is not None:
            return Path(system_exiftool)
        return Path(executable_name)

    system_exiftool = shutil.which('exiftool')
    if system_exiftool is not None:
        return Path(system_exiftool)

    candidates.extend([
        _RUNTIME_DIR.joinpath('qt_gui', 'exiftool', executable_name),
        _RUNTIME_DIR.joinpath('exiftool', executable_name),
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(executable_name)


EXIFTOOL_PATH = _resolve_exiftool_path()
ENCODING = 'gbk' if platform.system() == 'Windows' else 'utf-8'
EXIF_BACKEND_PYTHON = 'python'
EXIF_BACKEND_EXIFTOOL = 'exiftool'
_EXIF_BACKEND = EXIF_BACKEND_PYTHON
_WINDOWS_NO_WINDOW_KWARGS = {}
if platform.system() == 'Windows':
    _WINDOWS_NO_WINDOW_KWARGS['creationflags'] = subprocess.CREATE_NO_WINDOW
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    _WINDOWS_NO_WINDOW_KWARGS['startupinfo'] = startupinfo

logger = logging.getLogger(__name__)


def _notify_exif_issue(message: str, on_message: Callable[[str], None] | None = None) -> None:
    logger.warning(message)
    if on_message is None:
        return
    try:
        on_message(message)
    except Exception:
        logger.exception('Failed to forward EXIF diagnostic message.')


def normalize_exif_backend(backend: str | None) -> str:
    if str(backend or '').strip().lower() == EXIF_BACKEND_EXIFTOOL:
        return EXIF_BACKEND_EXIFTOOL
    return EXIF_BACKEND_PYTHON


def set_exif_backend(backend: str | None) -> None:
    global _EXIF_BACKEND
    _EXIF_BACKEND = normalize_exif_backend(backend)


def get_exif_backend() -> str:
    return _EXIF_BACKEND


def subprocess_no_window_kwargs() -> dict:
    return dict(_WINDOWS_NO_WINDOW_KWARGS)


def check_output_no_window(args):
    return subprocess.check_output(args, **subprocess_no_window_kwargs())


class ExifToolSession:
    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._lock = threading.RLock()

    def _start_locked(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return

        self._process = subprocess.Popen(
            [EXIFTOOL_PATH, '-stay_open', 'True', '-@', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding='utf-8',
            errors='ignore',
            **subprocess_no_window_kwargs(),
        )

    def execute(self, args: list[str | Path]) -> str:
        with self._lock:
            try:
                self._start_locked()
                if self._process is None or self._process.stdin is None or self._process.stdout is None:
                    raise RuntimeError('exiftool stay_open session is unavailable')

                command = ''.join(f'{arg}\n' for arg in args)
                self._process.stdin.write(command)
                self._process.stdin.write('-execute\n')
                self._process.stdin.flush()

                lines: list[str] = []
                while True:
                    line = self._process.stdout.readline()
                    if line == '':
                        raise RuntimeError('exiftool stay_open session closed unexpectedly')
                    if line.strip().startswith('{ready'):
                        break
                    lines.append(line)
                return ''.join(lines)
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            if process is None:
                return
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write('-stay_open\nFalse\n')
                    process.stdin.flush()
            except Exception:
                pass
            try:
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


_EXIFTOOL_SESSION = ExifToolSession()


def close_exiftool_session() -> None:
    _EXIFTOOL_SESSION.close()


atexit.register(close_exiftool_session)


def send_exiftool_command(args: list[str | Path]) -> str:
    return _EXIFTOOL_SESSION.execute(args)


def _clean_exif_dict(exif_dict: dict) -> dict:
    for key, value in list(exif_dict.items()):
        text = str(value)
        exif_dict[key] = ''.join(c for c in text if ord(c) < 128)
    return exif_dict


def _parse_exiftool_output(output: str) -> dict:
    exif_dict = {}
    for line in output.splitlines():
        kv_pair = line.split(':')
        if len(kv_pair) < 2:
            continue
        key = kv_pair[0].strip()
        value = ':'.join(kv_pair[1:]).strip()
        key = re.sub(r'\s+', '', key)
        key = re.sub(r'/', '', key)
        exif_dict[key] = value
    return _clean_exif_dict(exif_dict)


def _get_exif_with_exiftool(path) -> dict:
    try:
        output = send_exiftool_command(['-d', '%Y-%m-%d %H:%M:%S%3f%z', path])
    except Exception:
        output_bytes = check_output_no_window([EXIFTOOL_PATH, '-d', '%Y-%m-%d %H:%M:%S%3f%z', path])
        output = output_bytes.decode('utf-8', errors='ignore')
    return _parse_exiftool_output(output)


def _value_text(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _ratio_parts(value) -> tuple[int, int] | None:
    if value is None:
        return None
    numerator = getattr(value, 'num', None)
    denominator = getattr(value, 'den', None)
    if numerator is not None and denominator not in (None, 0):
        return int(numerator), int(denominator)
    numerator = getattr(value, 'numerator', None)
    denominator = getattr(value, 'denominator', None)
    if numerator is not None and denominator not in (None, 0):
        return int(numerator), int(denominator)
    if isinstance(value, tuple) and len(value) == 2 and value[1] not in (None, 0):
        return int(value[0]), int(value[1])
    text = _value_text(value)
    if '/' in text:
        left, right = text.split('/', 1)
        try:
            denominator = int(right)
            if denominator == 0:
                return None
            return int(left), denominator
        except ValueError:
            return None
    return None


def _ratio_to_float(value) -> float | None:
    parts = _ratio_parts(value)
    if parts is not None:
        numerator, denominator = parts
        return numerator / denominator
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_value(value):
    values = getattr(value, 'values', None)
    if isinstance(values, (list, tuple)) and values:
        return values[0]
    return value


def _format_decimal(value, digits: int = 1) -> str:
    number = _ratio_to_float(_first_value(value))
    if number is None:
        return _value_text(value)
    return f'{number:.{digits}f}'


def _format_integer(value) -> str:
    number = _ratio_to_float(_first_value(value))
    if number is None:
        return _value_text(value)
    return str(int(round(number)))


def _format_exposure(value) -> str:
    first = _first_value(value)
    parts = _ratio_parts(first)
    if parts is not None:
        numerator, denominator = parts
        if denominator == 1:
            return str(numerator)
        return f'{numerator}/{denominator}'
    return _value_text(value)


def _orientation_from_code(value) -> str:
    try:
        code = int(_ratio_to_float(_first_value(value)) or 0)
    except (TypeError, ValueError):
        code = 0
    return {
        1: 'Rotate 0',
        3: 'Rotate 180',
        6: 'Rotate 90 CW',
        8: 'Rotate 270 CW',
    }.get(code, _value_text(value))


def _format_focal_length(focal_value, focal_35mm_value=None) -> str:
    focal = _format_decimal(focal_value)
    if not focal:
        return ''
    focal_35mm = _format_decimal(focal_35mm_value) if focal_35mm_value is not None else ''
    if focal_35mm:
        return f'{focal} mm (35 mm equivalent: {focal_35mm} mm)'
    return f'{focal} mm'


def _format_gps_coord(values, ref: str) -> str:
    if values is None or not ref:
        return ''
    coord_values = getattr(values, 'values', values)
    if not isinstance(coord_values, (list, tuple)) or len(coord_values) < 2:
        return ''
    degrees = int(_ratio_to_float(coord_values[0]) or 0)
    minutes = int(_ratio_to_float(coord_values[1]) or 0)
    seconds = _ratio_to_float(coord_values[2]) if len(coord_values) > 2 else 0.0
    seconds = 0.0 if seconds is None else seconds
    return f'{degrees} deg {minutes}\' {seconds:.2f}" {ref.upper()[0]}'


def _get_exifread_tag(tags: dict, *names: str):
    for name in names:
        if name in tags:
            return tags[name]
    return None


def _get_exif_with_exifread(path) -> dict:
    if exifread is None:
        raise RuntimeError('exifread is not installed')

    with open(path, 'rb') as image_file:
        tags = exifread.process_file(image_file, details=False)

    exif_dict = {}
    make = _get_exifread_tag(tags, 'Image Make')
    model = _get_exifread_tag(tags, 'Image Model')
    lens_model = _get_exifread_tag(tags, 'EXIF LensModel', 'MakerNote LensModel')
    lens_make = _get_exifread_tag(tags, 'EXIF LensMake')
    datetime_original = _get_exifread_tag(tags, 'EXIF DateTimeOriginal')
    focal = _get_exifread_tag(tags, 'EXIF FocalLength')
    focal_35mm = _get_exifread_tag(tags, 'EXIF FocalLengthIn35mmFilm', 'EXIF FocalLengthIn35mmFormat')
    f_number = _get_exifread_tag(tags, 'EXIF FNumber')
    iso = _get_exifread_tag(tags, 'EXIF ISOSpeedRatings', 'EXIF PhotographicSensitivity')
    exposure = _get_exifread_tag(tags, 'EXIF ExposureTime')
    shutter = _get_exifread_tag(tags, 'EXIF ShutterSpeedValue')
    orientation = _get_exifread_tag(tags, 'Image Orientation')

    if make:
        exif_dict['Make'] = _value_text(make)
    if model:
        exif_dict['Model'] = _value_text(model)
        exif_dict['CameraModelName'] = _value_text(model)
    if lens_model:
        lens_text = _value_text(lens_model)
        exif_dict['LensModel'] = lens_text
        exif_dict['Lens'] = lens_text
        exif_dict['LensID'] = lens_text
    if lens_make:
        exif_dict['LensMake'] = _value_text(lens_make)
    if datetime_original:
        exif_dict['DateTimeOriginal'] = _value_text(datetime_original)
    if focal:
        exif_dict['FocalLength'] = _format_focal_length(focal, focal_35mm)
    if focal_35mm:
        exif_dict['FocalLengthIn35mmFormat'] = f'{_format_integer(focal_35mm)} mm'
    if f_number:
        exif_dict['FNumber'] = _format_decimal(f_number)
    if iso:
        exif_dict['ISO'] = _format_integer(iso)
    if exposure:
        exposure_text = _format_exposure(exposure)
        exif_dict['ExposureTime'] = exposure_text
        exif_dict['ShutterSpeedValue'] = exposure_text
    elif shutter:
        exif_dict['ShutterSpeedValue'] = _value_text(shutter)
    if orientation:
        exif_dict['Orientation'] = _orientation_from_code(orientation)

    lat = _get_exifread_tag(tags, 'GPS GPSLatitude')
    lat_ref = _value_text(_get_exifread_tag(tags, 'GPS GPSLatitudeRef'))
    lng = _get_exifread_tag(tags, 'GPS GPSLongitude')
    lng_ref = _value_text(_get_exifread_tag(tags, 'GPS GPSLongitudeRef'))
    lat_text = _format_gps_coord(lat, lat_ref)
    lng_text = _format_gps_coord(lng, lng_ref)
    if lat_text and lng_text:
        exif_dict['GPSLatitude'] = lat_text
        exif_dict['GPSLongitude'] = lng_text
        exif_dict['GPSPosition'] = f'{lat_text}, {lng_text}'

    return _clean_exif_dict(exif_dict)


def _pillow_ifd(exif, ifd):
    try:
        return exif.get_ifd(ifd)
    except Exception:
        return {}


def _get_exif_with_pillow(path) -> dict:
    with Image.open(path) as image:
        exif = image.getexif()
        if not exif:
            return {}

        exif_ifd = _pillow_ifd(exif, ExifTags.IFD.Exif)
        gps_ifd = _pillow_ifd(exif, ExifTags.IFD.GPSInfo)

    exif_dict = {}
    make = exif.get(271)
    model = exif.get(272)
    orientation = exif.get(274)
    lens_make = exif_ifd.get(42035)
    lens_model = exif_ifd.get(42036)
    datetime_original = exif_ifd.get(36867)
    focal = exif_ifd.get(37386)
    focal_35mm = exif_ifd.get(41989)
    f_number = exif_ifd.get(33437)
    iso = exif_ifd.get(34855) or exif_ifd.get(34864)
    exposure = exif_ifd.get(33434)

    if make:
        exif_dict['Make'] = _value_text(make)
    if model:
        exif_dict['Model'] = _value_text(model)
        exif_dict['CameraModelName'] = _value_text(model)
    if lens_model:
        lens_text = _value_text(lens_model)
        exif_dict['LensModel'] = lens_text
        exif_dict['Lens'] = lens_text
        exif_dict['LensID'] = lens_text
    if lens_make:
        exif_dict['LensMake'] = _value_text(lens_make)
    if datetime_original:
        exif_dict['DateTimeOriginal'] = _value_text(datetime_original)
    if focal:
        exif_dict['FocalLength'] = _format_focal_length(focal, focal_35mm)
    if focal_35mm:
        exif_dict['FocalLengthIn35mmFormat'] = f'{_format_integer(focal_35mm)} mm'
    if f_number:
        exif_dict['FNumber'] = _format_decimal(f_number)
    if iso:
        exif_dict['ISO'] = _format_integer(iso)
    if exposure:
        exposure_text = _format_exposure(exposure)
        exif_dict['ExposureTime'] = exposure_text
        exif_dict['ShutterSpeedValue'] = exposure_text
    if orientation:
        exif_dict['Orientation'] = _orientation_from_code(orientation)

    lat_text = _format_gps_coord(gps_ifd.get(2), _value_text(gps_ifd.get(1)))
    lng_text = _format_gps_coord(gps_ifd.get(4), _value_text(gps_ifd.get(3)))
    if lat_text and lng_text:
        exif_dict['GPSLatitude'] = lat_text
        exif_dict['GPSLongitude'] = lng_text
        exif_dict['GPSPosition'] = f'{lat_text}, {lng_text}'

    return _clean_exif_dict(exif_dict)


def _get_exif_with_python(path) -> dict:
    errors = []
    try:
        return _get_exif_with_exifread(path)
    except Exception as exc:
        errors.append(f'exifread: {exc}')

    try:
        exif_dict = _get_exif_with_pillow(path)
        if exif_dict:
            logger.debug('EXIF read with Pillow fallback after Python reader issue: %s', '; '.join(errors))
            return exif_dict
    except Exception as exc:
        errors.append(f'pillow: {exc}')

    raise RuntimeError('; '.join(errors))


def get_file_list(path):
    """
    获取 jpg 文件列表
    :param path: 路径
    :return: 文件名
    """
    path = Path(path)
    return [file_path for file_path in path.iterdir()
            if file_path.is_file() and file_path.suffix in ['.jpg', '.jpeg', '.JPG', '.JPEG', '.png', '.PNG']]


def get_exif(path, on_message: Callable[[str], None] | None = None) -> dict:
    """
    获取exif信息
    :param path: 照片路径
    :return: exif信息
    """
    path_obj = Path(path)

    if get_exif_backend() == EXIF_BACKEND_EXIFTOOL:
        try:
            return _get_exif_with_exiftool(path)
        except Exception as e:
            message = f'ExifTool EXIF 读取失败：{path_obj.name}，原因：{e}'
            logger.error(message)
            if on_message is not None:
                on_message(message)
            return {}

    try:
        exif_dict = _get_exif_with_python(path)
        logger.debug('EXIF read with Python readers: %s', path)
        return exif_dict
    except Exception as python_error:
        _notify_exif_issue(
            f'Python EXIF 读取失败，将使用 ExifTool 兜底：{path_obj.name}，原因：{python_error}',
            on_message=on_message,
        )

    try:
        exif_dict = _get_exif_with_exiftool(path)
        logger.info('EXIF read with ExifTool fallback: %s', path)
        return exif_dict
    except Exception as e:
        message = f'ExifTool EXIF 读取失败：{path_obj.name}，原因：{e}'
        logger.error(message)
        if on_message is not None:
            on_message(message)
        return {}


def insert_exif(source_path, target_path) -> None:
    """
    复制照片的 exif 信息
    :param source_path: 源照片路径
    :param target_path: 目的照片路径
    """
    try:
        # 将 exif 信息转换为字节串
        check_output_no_window([EXIFTOOL_PATH, '-tagsfromfile', source_path, '-overwrite_original', target_path])
    except ValueError as e:
        logger.exception(f'ValueError: {source_path}: cannot insert exif {str(e)}')


TINY_HEIGHT = 800


def remove_white_edge(image):
    """
    移除图片白边
    :param image: 图片对象
    :return: 移除白边后的图片对象
    """
    # 获取像素信息
    pixels = image.load()

    # 获取图像大小
    width, height = image.size

    # 计算最小的 X、Y、最大的 X、Y 坐标
    min_x, min_y = width - 1, height - 1
    max_x, max_y = 0, 0
    for y in range(height):
        for x in range(width):
            if pixels[x, y] != (255, 255, 255):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    # 计算新的图像大小
    new_width = max_x - min_x + 1
    new_height = max_y - min_y + 1

    # 裁剪图像
    new_image = image.crop((min_x, min_y, max_x + 1, max_y + 1))
    return new_image


def concatenate_image(images, align='left'):
    """
    将多张图片拼接成一列
    :param images: 图片对象列表
    :param align: 对齐方向，left/center/right
    :return: 拼接后的图片对象
    """
    widths, heights = zip(*(i.size for i in images))

    sum_height = sum(heights)
    max_width = max(widths)

    new_img = Image.new('RGBA', (max_width, sum_height), color=TRANSPARENT)

    x_offset = 0
    y_offset = 0
    if 'left' == align:
        for img in images:
            new_img.paste(img, (0, y_offset))
            y_offset += img.height
    elif 'center' == align:
        for img in images:
            x_offset = int((max_width - img.width) / 2)
            new_img.paste(img, (x_offset, y_offset))
            y_offset += img.height
    elif 'right' == align:
        for img in images:
            x_offset = max_width - img.width  # 右对齐
            new_img.paste(img, (x_offset, y_offset))
            y_offset += img.height
    return new_img


def padding_image(image, padding_size, padding_location='tb', color=TRANSPARENT) -> Image.Image:
    """
    在图片四周填充白色像素
    :param image: 图片对象
    :param padding_size: 填充像素大小
    :param padding_location: 填充位置，top/bottom/left/right
    :return: 填充白色像素后的图片对象
    """
    if image is None:
        return None

    total_width, total_height = image.size
    x_offset, y_offset = 0, 0
    if 't' in padding_location:
        total_height += padding_size
        y_offset += padding_size
    if 'b' in padding_location:
        total_height += padding_size
    if 'l' in padding_location:
        total_width += padding_size
        x_offset += padding_size
    if 'r' in padding_location:
        total_width += padding_size

    padding_img = Image.new('RGBA', (total_width, total_height), color=color)
    padding_img.paste(image, (x_offset, y_offset))
    return padding_img


def square_image(image, auto_close=True) -> Image.Image:
    """
    将图片按照正方形进行填充
    :param auto_close: 是否自动关闭图片对象
    :param image: 图片对象
    :return: 填充后的图片对象
    """
    # 计算图片的宽度和高度
    width, height = image.size
    if width == height:
        return image

    # 计算需要填充的白色区域大小
    delta_w = abs(width - height)
    padding = (delta_w // 2, 0) if width < height else (0, delta_w // 2)

    square_img = ImageOps.expand(image, padding, fill='white')

    if auto_close:
        image.close()

    # 返回正方形图片对象
    return square_img


def resize_image_with_height(image, height, auto_close=True):
    """
    按照高度对图片进行缩放
    :param image: 图片对象
    :param height: 指定高度
    :return: 按照高度缩放后的图片对象
    """
    # 获取原始图片的宽度和高度
    width, old_height = image.size

    # 计算缩放后的宽度
    scale = height / old_height
    new_width = round(width * scale)

    # 进行等比缩放
    resized_image = image.resize((new_width, height), Image.LANCZOS)

    # 关闭图片对象
    if auto_close:
        image.close()

    # 返回缩放后的图片对象
    return resized_image


def resize_image_with_width(image, width, auto_close=True):
    """
    按照宽度对图片进行缩放
    :param image: 图片对象
    :param width: 指定宽度
    :return: 按照宽度缩放后的图片对象
    """
    # 获取原始图片的宽度和高度
    old_width, height = image.size

    # 计算缩放后的宽度
    scale = width / old_width
    new_height = round(height * scale)

    # 进行等比缩放
    resized_image = image.resize((width, new_height), Image.LANCZOS)

    # 关闭图片对象
    if auto_close:
        image.close()

    # 返回缩放后的图片对象
    return resized_image


def append_image_by_side(background, images, side='left', padding=200, is_start=False):
    """
    将图片横向拼接到背景图片中
    :param background: 背景图片对象
    :param images: 图片对象列表
    :param side: 拼接方向，left/right
    :param padding: 图片之间的间距
    :param is_start: 是否在最左侧添加 padding
    :return: 拼接后的图片对象
    """
    if 'right' == side:
        if is_start:
            x_offset = background.width - padding
        else:
            x_offset = background.width
        images.reverse()
        for i in images:
            if i is None:
                continue
            i = resize_image_with_height(i, background.height, auto_close=False)
            x_offset -= i.width
            x_offset -= padding
            background.paste(i, (x_offset, 0))
    else:
        if is_start:
            x_offset = padding
        else:
            x_offset = 0
        for i in images:
            if i is None:
                continue
            i = resize_image_with_height(i, background.height, auto_close=False)
            background.paste(i, (x_offset, 0))
            x_offset += i.width
            x_offset += padding


def text_to_image(content, font, bold_font, is_bold=False, fill='black') -> Image.Image:
    """
    将文字内容转换为图片
    """
    if is_bold:
        font = bold_font
    if content == '':
        content = '   '
    _, _, text_width, text_height = font.getbbox(content)
    image = Image.new('RGBA', (text_width, text_height), color=TRANSPARENT)
    draw = ImageDraw.Draw(image)
    draw.text((0, 0), content, fill=fill, font=font)
    return image


def merge_images(images, axis=0, align=0):
    """
    拼接多张图片
    :param images: 图片对象列表
    :param axis: 0 水平拼接，1 垂直拼接
    :param align: 0 居中对齐，1 底部/右对齐，2 顶部/左对齐
    :return: 拼接后的图片对象
    """
    # 获取每张图像的 size
    widths, heights = zip(*(img.size for img in images))

    # 计算输出图像的尺寸
    if axis == 0:  # 水平拼接
        total_width = sum(widths)
        max_height = max(heights)
    else:  # 垂直拼接
        total_width = max(widths)
        max_height = sum(heights)

    # 创建输出图像
    output_image = Image.new('RGBA', (total_width, max_height), color=TRANSPARENT)

    # 拼接图像
    x_offset, y_offset = 0, 0
    for img in images:
        if axis == 0:  # 水平拼接
            if align == 1:  # 底部对齐
                y_offset = max_height - img.size[1]
            elif align == 2:  # 顶部对齐
                y_offset = 0
            else:  # 居中排列
                y_offset = (max_height - img.size[1]) // 2
            output_image.paste(img, (x_offset, y_offset))
            x_offset += img.size[0]
        else:  # 垂直拼接
            if align == 1:  # 右对齐
                x_offset = total_width - img.size[0]
            elif align == 2:  # 左对齐
                x_offset = 0
            else:  # 居中排列
                x_offset = (total_width - img.size[0]) // 2
            output_image.paste(img, (x_offset, y_offset))
            y_offset += img.size[1]

    return output_image


def calculate_pixel_count(width: int, height: int) -> str:
    # 计算像素总数
    pixel_count = width * height
    # 计算百万像素数
    megapixel_count = pixel_count / 1000000.0
    # 返回结果字符串
    return f"{megapixel_count:.2f} MP"


def extract_attribute(data_dict: dict, *keys, default_value: str = '', prefix='', suffix='') -> str:
    """
    从字典中提取对应键的属性值

    :param data_dict: 包含属性值的字典
    :param keys: 一个或多个键
    :param default_value: 默认值，默认为空字符串
    :return: 对应的属性值或空字符串
    """
    for key in keys:
        if key in data_dict:
            return data_dict[key] + suffix
    return default_value


def extract_gps_lat_and_long(lat: str, long: str):
    # 提取出纬度和经度主要部分
    lat_deg, _, lat_min = re.findall(r"(\d+ deg \d+)", lat)[0].split()
    long_deg, _, long_min = re.findall(r"(\d+ deg \d+)", long)[0].split()

    # 提取出方向（北 / 南 / 东 / 西）
    lat_dir = re.findall(r"([NS])", lat)[0]
    long_dir = re.findall(r"([EW])", long)[0]

    latitude = f"{lat_deg}°{lat_min}'{lat_dir}"
    longitude = f"{long_deg}°{long_min}'{long_dir}"

    return latitude, longitude


def extract_gps_info(gps_info: str):
    lat, long = gps_info.split(", ")
    return extract_gps_lat_and_long(lat, long)
