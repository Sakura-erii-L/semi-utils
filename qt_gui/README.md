# Qt GUI 使用说明

本目录提供一个基于 Qt（PySide6）的图形界面，完整整合 Semi-Utils 的已有能力：

- 图片批处理（水印布局、四角字段、白边、阴影、等效焦距、按比例填充）
- 输入输出路径配置与质量控制
- 默认 Logo 选择
- 基于固定示例图 qt_gui/example.jpg 的实时预览（处理后效果展示）
- 视频生成（复用原 gen_video.py）
- 实时日志与进度显示

## 启动方式

在项目根目录执行：

python qt_gui/main_gui.py

## 依赖

已在 requirements.txt 中补充 PySide6。

## 设计原则

- 业务逻辑复用原项目模块：Config、ImageContainer、ProcessorChain、generate_video
- GUI 层只做交互和展示，核心处理在 semi_bridge.py
- 所有主要流程都提供中文日志和中文注释，便于维护
