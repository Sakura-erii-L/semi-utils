# Semi-Utils Qt GUI 快速上下文

本目录是一个可独立运行和打包的 PySide6 图形界面项目。它已包含原 Semi-Utils GUI 运行所需的业务模块副本，不再依赖上一级源码目录。

## 入口

- 主入口：`main_gui.py`
- GUI 和处理桥接：`semi_bridge.py`
- 全局配置：`config.yaml`
- 打包脚本：`build_release.bat`
- 打包说明：`BUILD_EXE.md`

运行：

```powershell
conda activate semi-utils
python main_gui.py
```

或安装当前目录项目：

```powershell
pip install -e .
semi-utils-qt-gui
```

## 目录结构

- `entity/`：从原项目复制来的核心对象和处理器。
  - `config.py`：配置加载、Logo 加载、路径保存。
  - `image_container.py`：用 Pillow 打开图片，用 exiftool 读取 EXIF，并按 Orientation 修正方向。
  - `image_processor.py`：水印、Logo、白边、阴影等布局处理器。
- `enums/`：常量定义。
- `utils.py`：EXIF、图片拼接、文字转图、尺寸处理等工具函数。
- `init.py`：初始化全局 `config`、布局菜单项、元素菜单项。
- `gen_video.py`：把输出目录图片生成视频。
- `fonts/`、`logos/`、`exiftool/`：运行和打包资源。
- `portable/`：`build_release.bat` 生成的便携版输出目录。
- `temp/`：构建中间产物临时目录，脚本结束时清理。

## 配置与路径

`main_gui.py` 会优先设置：

```python
SEMI_UTILS_CONFIG = qt_gui/config.yaml
```

`config.yaml` 中资源路径应保持相对路径，例如：

```yaml
font: fonts/Roboto-Regular.ttf
path: logos/nsp_w.png
output_dir: output
```

`entity/config.py` 加载配置时会把相对资源路径解析成绝对路径供运行使用；保存配置时会把 `fonts/` 和 `logos/` 下的路径转回相对路径，避免破坏便携性。

## 图片来源

支持格式由 `semi_bridge.SUPPORTED_SUFFIXES` 控制：

- `.jpg`
- `.jpeg`
- `.png`
- 大写扩展名同样支持

批处理来源：

- 如果用户点“选择图片”，使用手选文件列表。
- 如果没有手选文件，扫描输入目录第一层文件，不递归。

预览来源优先级：

1. 手选图片的第一张
2. 输入目录中的第一张支持图片
3. `example.jpg` 兜底

## 预览线程

实时预览由单独的后台线程执行，主线程只接收最新一份预览结果并更新界面。

流程：

1. GUI 收集表单设置。
2. `_resolve_preview_source_path()` 决定预览源。
3. `build_preview_image_with_exif()` 生成处理后预览图和 EXIF 摘要。
4. 后台线程把 PIL 图像转成 RGBA 像素数据，主线程用 `_preview_rgba_to_qpixmap()` 轻量更新 Qt 预览图。

如果配置连续变化，预览不会排队渲染所有历史状态，只保留最新一次待刷新请求。

预览不会写入输出目录。

## Logo 行为

Logo 下拉框来自 `semi_bridge.get_default_logo_options()`，读取 `config.yaml` 中的 `logo.makes`。

当前 NSP Logo：

- `NSP-W` -> `logos/nsp_w.png`
- `NSP-Y` -> `logos/nsp_y.png`

默认兜底 Logo：

```yaml
logo:
  default:
    id: NSP-W
    path: logos/nsp_w.png
```

行为规则：

- 首次加载某张预览图时，会按 EXIF 厂商自动选择一次 Logo。
- 同一张图后续刷新不会覆盖用户手动选择。
- 用户手动选择 Logo 后，预览和批处理都会使用当前选择的 Logo。
- 当照片厂商为空或无法匹配时，使用 `logo.default.path`。

相关代码：

- `main_gui._auto_select_logo_once_for_source()`
- `semi_bridge._resolve_logo_info()`
- `entity.config.Config.load_logo()`

## 交互限制

为避免误操作：

- `NoWheelComboBox` 禁止滚轮改选项。
- `NoWheelSpinBox` 禁止滚轮改数值。
- 下拉框和数值框主要靠点击或键盘输入修改。

## 批处理

入口：`semi_bridge.process_images()`

核心流程：

1. `normalize_source_files()` 或 `_get_source_file_list()` 得到待处理文件。
2. 每张图创建 `ImageContainer`。
3. `_build_processor_chain()` 根据当前配置创建处理器链。
4. `_process_one_image()` 执行处理并保存。

输出路径：

- 如果 `output_dir` 非空，输出到该目录。
- 如果 `output_dir` 为空，则按原项目逻辑输出到源图旁边，并避免覆盖。

## 视频生成

入口：`semi_bridge.generate_video_with_logs()`。

它调用 `gen_video.generate_video()`，读取当前输出目录中的 jpg/jpeg/png 图片生成视频。若需要离线使用视频功能，可在便携版中放入：

```text
bin/ffmpeg.exe
```

## 打包

推荐使用：

```powershell
conda activate semi-utils
.\build_release.bat
```

输出：

```text
portable/SemiUtilsQt/SemiUtilsQt.exe
portable/SemiUtilsQt/
portable/SemiUtilsQt-windows.zip
```

默认使用 Nuitka standalone 文件夹模式。入口仍是 exe，但不会像单文件 exe 那样每次启动先解压运行库，因此优先保证启动速度；zip 只用于分享压缩。

构建日志：

```text
build_release.log
```

构建中间产物：

```text
temp/
```

脚本结束时会删除 `temp/`、旧版 `build_release/`、`*.egg-info` 和 `__pycache__`。

便携版中会生成 `run_with_log.bat`。如果双击 `SemiUtilsQt.exe` 没有明显反应，运行它并查看同目录的 `runtime.log`。

## 常见维护点

- 新增 Logo：把文件放入 `logos/`，再在 `config.yaml -> logo.makes` 添加条目。
- 改默认 Logo：修改 `config.yaml -> logo.default.path`。
- 改预览来源：看 `main_gui._resolve_preview_source_path()`。
- 改支持格式：看 `semi_bridge.SUPPORTED_SUFFIXES`。
- 改打包资源：看 `build_release.bat` 的 Nuitka `--include-data-*` 参数。
- 保持便携性：不要把 `config.yaml` 中的资源路径改成本机绝对路径。
