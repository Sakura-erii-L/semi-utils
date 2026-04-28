# Semi-Utils

> 批量为照片添加水印、白边、Logo 和 EXIF 信息的桌面工具，支持实时预览、批处理输出和图片转视频。

[![release](https://img.shields.io/github/v/release/Sakura-erii-L/semi-utils)](https://github.com/Sakura-erii-L/semi-utils/releases)
[![downloads](https://img.shields.io/github/downloads/Sakura-erii-L/semi-utils/total.svg)](https://github.com/Sakura-erii-L/semi-utils/releases)
[![license](https://img.shields.io/github/license/Sakura-erii-L/semi-utils)](LICENSE)
[![python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)

## 功能特性

- 图形界面：基于 PySide6，支持选择图片、实时预览、批量处理和日志查看。
- 水印布局：支持常规水印、黑色主题、自定义水印、正方形填充、简洁样式、背景模糊和纯白边框。
- EXIF 信息：自动读取相机、镜头、焦距、光圈、快门、ISO、拍摄时间、文件名和地理信息等字段。
- Logo 匹配：可按相机厂商自动匹配 Logo，也可以指定默认 Logo。
- 批量输出：支持 `jpg`、`jpeg`、`png`，可选择输入目录、手动选择图片和输出目录。
- 视频生成：可将输出目录中的图片合成为视频，支持设置图片切换间隔。
- 便携发布：Windows 版本可直接解压运行，不需要用户手动安装 Python。

## 效果预览

| 常规水印 | Logo 居右 | 黑色主题 |
| --- | --- | --- |
| ![](images/1.jpeg) | ![](images/2.jpeg) | ![](images/3.jpeg) |
| 自定义水印 | 正方形填充 | 简洁样式 |
| ![](images/5.jpeg) | ![](images/6.jpeg) | ![](images/7.jpeg) |
| 背景模糊 | 背景模糊 + 白框 |  |
| ![](images/8.jpeg) | ![](images/9.jpeg) |  |

## 快速开始

### Windows 便携版

1. 打开 [Releases](https://github.com/Sakura-erii-L/semi-utils/releases/latest)，下载 `SemiUtilsQt-windows.zip`。
2. 解压压缩包。
3. 进入解压后的 `SemiUtilsQt` 目录，双击 `SemiUtilsQt.exe`。
4. 在界面中选择输入图片或输入目录，设置输出目录、布局、Logo 和文字内容。
5. 查看右侧实时预览，确认效果后点击“开始批处理”。

如果双击后没有明显反应，可以运行同目录下的 `debug_run_with_log.bat`，再查看生成的 `runtime.log`。

### 从源码运行 Qt 图形界面

需要 Python 3.10 或更新版本。

```powershell
git clone https://github.com/Sakura-erii-L/semi-utils.git
cd semi-utils\qt_gui

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .

python main_gui.py
```

也可以安装后直接运行命令：

```powershell
semi-utils-qt-gui
```

Qt 图形界面默认使用 Python 包读取 EXIF。ExifTool 会作为兜底保留；Windows 下可以将 `exiftool.exe` 放到 `qt_gui/exiftool/exiftool.exe`，或确保 `exiftool.exe` 已加入 `PATH`；macOS/Linux 下可以安装系统版本的 `exiftool`。

### 使用命令行批处理

命令行版本保留在项目根目录，适合不需要图形界面的批处理场景。

```powershell
git clone https://github.com/Sakura-erii-L/semi-utils.git
cd semi-utils
pip install -r requirements.txt
python main.py
```

默认会读取 `input/` 中的图片，并将结果输出到 `output/`。运行时可以在菜单中调整布局、Logo、输出路径和更多选项。命令行版本同样依赖 ExifTool，Windows 下可放到 `exiftool/exiftool.exe`，macOS/Linux 下可放到 `exiftool/exiftool` 或安装到系统 `PATH`。

## 图形界面使用说明

- “图片处理”页用于设置输入、输出、布局、Logo、文字字段、字体、质量和批处理。
- “视频生成”页会读取当前输出目录中的 `jpg/jpeg/png` 图片并生成视频。
- “示例预览”页显示应用当前设置后的效果图。
- 修改任意配置后，预览会自动刷新；预览不会写入输出目录。
- 如果只想在源图旁生成新图，可以将输出目录留空。
- 自定义文字只在对应位置选择“自定义”时生效。
- “全局选项”中的“EXIF 读取”默认使用 Python 包；若部分机型镜头信息识别不完整，可切换为 ExifTool。

## 布局类型

| ID | 界面名称 | 说明 |
| --- | --- | --- |
| `watermark_left_logo` | normal | 常规水印，Logo 在左侧 |
| `watermark_right_logo` | normal(Logo 居右) | 常规水印，Logo 在右侧 |
| `dark_watermark_left_logo` | normal(黑红配色) | 深色背景水印，Logo 在左侧 |
| `dark_watermark_right_logo` | normal(黑红配色，Logo 居右) | 深色背景水印，Logo 在右侧 |
| `custom_watermark` | normal(自定义配置) | 使用配置中的颜色、粗体、Logo 开关和位置 |
| `square` | 1:1填充 | 将图片填充为正方形 |
| `simple` | 简洁 | 输出简洁的 Shot on 风格信息 |
| `background_blur` | 背景模糊 | 使用原图模糊背景承托照片 |
| `background_blur_with_white_border` | 背景模糊+白框 | 模糊背景叠加白色边框 |
| `pure_white_margin` | 白色边框 | 只添加纯白边框 |

## 可用文字字段

| 字段 | 含义 |
| --- | --- |
| `Model` | 相机型号 |
| `Make` | 相机厂商 |
| `LensModel` | 镜头型号 |
| `Param` | 拍摄参数，例如焦距、光圈、快门、ISO |
| `Datetime` | 拍摄日期时间 |
| `Date` | 拍摄日期 |
| `Custom` | 自定义文字 |
| `None` | 不显示 |
| `LensMake_LensModel` | 镜头厂商 + 镜头型号 |
| `CameraModel_LensModel` | 相机型号 + 镜头型号 |
| `TotalPixel` | 总像素 |
| `CameraMake_CameraModel` | 相机厂商 + 相机型号 |
| `Filename` | 文件名 |
| `Date_Filename` | 日期 + 文件名 |
| `Datetime_Filename` | 日期时间 + 文件名 |
| `GeoInfo` | 地理信息 |

## 配置文件

主要配置在 `config.yaml` 中，Qt 图形界面使用 `qt_gui/config.yaml`。常用配置包括：

```yaml
base:
  input_dir: ./input
  output_dir: ./output
  quality: 100

global:
  white_margin:
    enable: true
    width: 3
  shadow:
    enable: false
  focal_length:
    use_equivalent_focal_length: false
  exif:
    backend: python

layout:
  type: watermark_right_logo
  logo_enable: false
  logo_position: left
```

Logo 配置位于 `logo.makes`。新增 Logo 时，把图片放入 `logos/`，再在 `config.yaml` 中添加厂商 ID 和文件路径。便携版中建议保持相对路径，避免换电脑后资源失效。

## 项目结构

```text
.
├── main.py                 # 命令行入口
├── config.yaml             # 命令行版本默认配置
├── entity/                 # 图片容器、配置和处理器
├── enums/                  # 常量定义
├── fonts/                  # 字体资源
├── images/                 # README 示例图
├── logos/                  # 相机和品牌 Logo
├── input/                  # 默认输入目录
├── output/                 # 默认输出目录
└── qt_gui/
    ├── main_gui.py         # Qt 图形界面入口
    ├── semi_bridge.py      # GUI 与核心处理逻辑桥接
    ├── config.yaml         # Qt 图形界面配置
    ├── build_release.bat   # Windows 便携版打包脚本
    └── portable/           # 打包输出目录
```

## 打包 Windows 便携版

在 Windows 下进入 `qt_gui` 目录运行：

```powershell
cd qt_gui
.\build_release.bat
```

脚本会生成：

```text
portable/SemiUtilsQt/SemiUtilsQt.exe
portable/SemiUtilsQt-windows.zip
logs/build_release.log
```

如果本机存在 `semi-utils` conda 环境，脚本会优先使用该环境；否则使用当前 `PATH` 中的 Python。脚本要求 Python 3.10 或更新版本，并会安装或更新 `pip`、`setuptools`、`wheel`、`pyinstaller` 等打包依赖。

## 常见问题

### 预览或批处理提示找不到图片

确认输入目录中存在 `jpg`、`jpeg` 或 `png` 文件。当前只扫描输入目录第一层，不递归扫描子目录。

### Logo 没有按预期显示

检查 `config.yaml` 中的 `logo.makes` 是否包含对应厂商的 `id`，并确认 `path` 指向的图片存在。无法匹配厂商时会使用 `logo.default.path`。

### 视频无法生成

确认输出目录中已经有处理后的图片。视频功能依赖 ffmpeg；便携版可将 `ffmpeg.exe` 放入 `bin/` 目录。

### 程序运行失败或没有反应

优先查看界面右侧日志；便携版可运行 `debug_run_with_log.bat` 并查看同目录下的 `runtime.log`。源码运行时可查看 `logs/` 目录下的日志文件。

## 许可证

Semi-Utils 基于 [Apache License 2.0](LICENSE) 发布。

项目使用的 [ExifTool](https://exiftool.org/) 遵循其自身许可协议。
