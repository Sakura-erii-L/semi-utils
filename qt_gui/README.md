# Qt GUI 使用说明

本目录提供一个基于 Qt（PySide6）的图形界面，完整整合 Semi-Utils 的已有能力：

- 图片批处理（水印布局、四角字段、白边、阴影、等效焦距、按比例填充）
- 输入输出路径配置与质量控制
- 支持输入目录或直接选择单张/多张图片进行处理
- 默认 Logo 选择
- 基于固定示例图 qt_gui/example.jpg 的实时预览（处理后效果展示）
- 四角元素与 Logo 行下方显示当前预览图的 EXIF 对应信息
- 视频生成（复用原 gen_video.py）
- 实时日志与进度显示

## 启动方式

在项目根目录执行：

python qt_gui/main_gui.py

也可以把 `qt_gui` 当作独立 Python 项目运行：

1. 进入 `qt_gui` 目录。
2. 安装本目录的项目定义（`pyproject.toml`）。
3. 通过命令行入口 `semi-utils-qt-gui` 启动。

## 依赖与资源

- 依赖由 `qt_gui/pyproject.toml` 管理。
- `qt_gui` 目录内已包含 `config.yaml`、`logos/`、`fonts/` 与 `exiftool/`，可用于单独打包。
- Windows 下会优先使用 `qt_gui/exiftool/exiftool.exe`，避免预览时 EXIF 读取失败。

## 打包建议

可在 `qt_gui` 目录执行：

- 构建 wheel: `python -m build`
- 可编辑安装: `pip install -e .`

## 设计原则

- 业务逻辑复用原项目模块：Config、ImageContainer、ProcessorChain、generate_video
- GUI 层只做交互和展示，核心处理在 semi_bridge.py
- 所有主要流程都提供中文日志和中文注释，便于维护
