from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 允许通过 `python qt_gui/main_gui.py` 直接启动。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import QObject
from PySide6.QtCore import Qt
from PySide6.QtCore import QThread
from PySide6.QtCore import QTimer
from PySide6.QtCore import Signal
from PySide6.QtCore import Slot
from PySide6.QtGui import QFont
from PySide6.QtGui import QImage
from PySide6.QtGui import QIcon
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QComboBox
from PySide6.QtWidgets import QFileDialog
from PySide6.QtWidgets import QFormLayout
from PySide6.QtWidgets import QGroupBox
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QLineEdit
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QMessageBox
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QProgressBar
from PySide6.QtWidgets import QScrollArea
from PySide6.QtWidgets import QSpinBox
from PySide6.QtWidgets import QSplitter
from PySide6.QtWidgets import QTabWidget
from PySide6.QtWidgets import QTextBrowser
from PySide6.QtWidgets import QTextEdit
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtWidgets import QWidget

from qt_gui.semi_bridge import apply_runtime_config_from_values
from qt_gui.semi_bridge import build_preview_images
from qt_gui.semi_bridge import generate_video_with_logs
from qt_gui.semi_bridge import get_default_logo_options
from qt_gui.semi_bridge import get_element_options
from qt_gui.semi_bridge import get_layout_options
from qt_gui.semi_bridge import get_runtime_config_snapshot
from qt_gui.semi_bridge import process_images

LOCATION_LABELS = {
    "left_top": "左上角",
    "right_top": "右上角",
    "left_bottom": "左下角",
    "right_bottom": "右下角",
}

PREVIEW_IMAGE_PATH = Path(__file__).resolve().parent.joinpath("example.jpg")


class ImagePreviewLabel(QLabel):
    """用于展示预览图，保持宽高比缩放。"""

    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self._origin_pixmap: QPixmap | None = None
        self._placeholder = placeholder
        self.setObjectName("PreviewImageLabel")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(260, 260)
        self.setWordWrap(True)

    def set_preview_pixmap(self, pixmap: QPixmap | None) -> None:
        self._origin_pixmap = pixmap
        if pixmap is None:
            self.setPixmap(QPixmap())
            self.setText(self._placeholder)
            return
        self._refresh_scaled_pixmap()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_scaled_pixmap()

    def _refresh_scaled_pixmap(self) -> None:
        if self._origin_pixmap is None:
            return
        scaled = self._origin_pixmap.scaled(
            max(80, self.width() - 18),
            max(80, self.height() - 18),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setText("")
        self.setPixmap(scaled)


class ProcessWorker(QObject):
    """图片批处理线程工作对象。"""

    progress = Signal(int, int, str, bool, str)
    message = Signal(str)
    finished = Signal(dict)
    crashed = Signal(str)

    def __init__(self, settings: dict):
        super().__init__()
        self.settings = settings
        self.stop_requested = False

    @Slot()
    def run(self) -> None:
        try:
            apply_runtime_config_from_values(self.settings, save=True)
            summary = process_images(
                on_progress=self._emit_progress,
                on_message=self.message.emit,
                stop_checker=lambda: self.stop_requested,
            )
            self.finished.emit(
                {
                    "total": summary.total,
                    "success": summary.success,
                    "failed": summary.failed,
                    "stopped": summary.stopped,
                    "failed_files": summary.failed_files,
                }
            )
        except Exception as exc:
            self.crashed.emit(str(exc))

    def request_stop(self) -> None:
        self.stop_requested = True

    def _emit_progress(self, index: int, total: int, filename: str, ok: bool, message: str) -> None:
        self.progress.emit(index, total, filename, ok, message)


class VideoWorker(QObject):
    """视频生成线程工作对象。"""

    message = Signal(str)
    finished = Signal(str)
    crashed = Signal(str)

    def __init__(self, settings: dict, gap_seconds: int):
        super().__init__()
        self.settings = settings
        self.gap_seconds = gap_seconds

    @Slot()
    def run(self) -> None:
        try:
            apply_runtime_config_from_values(self.settings, save=True)
            output_dir, logs = generate_video_with_logs(self.gap_seconds)
            if logs:
                self.message.emit(logs)
            self.finished.emit(output_dir)
        except Exception as exc:
            self.crashed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Semi-Utils Qt 图形界面")
        self.resize(1360, 860)

        icon_path = PROJECT_ROOT.joinpath("logo.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.processing_thread: QThread | None = None
        self.processing_worker: ProcessWorker | None = None
        self.video_thread: QThread | None = None
        self.video_worker: VideoWorker | None = None
        self.realtime_preview_paused = False
        self.preview_busy = False
        self.preview_pending = False

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._refresh_preview_now)

        self.element_controls: dict[str, dict[str, QWidget]] = {}

        self._build_ui()
        self._apply_styles()
        self._bind_events()
        self._load_config_to_form()

    def _build_ui(self) -> None:
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 16, 20, 16)
        root_layout.setSpacing(14)

        header_card = QWidget()
        header_card.setObjectName("HeaderCard")
        header_layout = QVBoxLayout(header_card)
        header_layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Semi-Utils 图像处理工作台")
        title.setObjectName("TitleText")
        title.setFont(QFont("Microsoft YaHei UI", 18, QFont.Weight.Bold))
        subtitle = QLabel("同一界面完成配置、批处理、视频生成与结果追踪")
        subtitle.setObjectName("SubtitleText")

        project_info = QLabel(
            "基于开源项目：<a href=\"https://github.com/leslievan/semi-utils\">"
            "https://github.com/leslievan/semi-utils</a>"
        )
        project_info.setObjectName("HeaderMetaText")
        project_info.setOpenExternalLinks(True)

        integrator_info = QLabel("GUI整合：Sakura")
        integrator_info.setObjectName("HeaderMetaText")

        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        header_layout.addWidget(project_info)
        header_layout.addWidget(integrator_info)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setChildrenCollapsible(False)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        body_splitter.addWidget(left_panel)
        body_splitter.addWidget(right_panel)
        body_splitter.setSizes([840, 520])

        root_layout.addWidget(header_card)
        root_layout.addWidget(body_splitter, stretch=1)

        self.setCentralWidget(central)

    def _build_left_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(self._build_processing_tab(), "图片处理")
        self.left_tabs.addTab(self._build_video_tab(), "视频生成")
        layout.addWidget(self.left_tabs)
        return container

    def _build_processing_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 8, 8)
        content_layout.setSpacing(12)

        content_layout.addWidget(self._build_path_group())
        content_layout.addWidget(self._build_layout_group())
        content_layout.addWidget(self._build_element_group())
        content_layout.addWidget(self._build_global_group())
        content_layout.addWidget(self._build_action_group())
        content_layout.addWidget(self._build_preview_group())
        content_layout.addStretch(1)

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def _build_video_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        video_group = QGroupBox("视频生成")
        form = QFormLayout(video_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.video_gap_spin = QSpinBox()
        self.video_gap_spin.setRange(1, 20)
        self.video_gap_spin.setValue(2)
        self.video_gap_spin.setSuffix(" 秒")

        self.video_run_btn = QPushButton("开始生成视频")
        self.video_run_btn.setObjectName("PrimaryButton")

        form.addRow("图片切换间隔", self.video_gap_spin)
        form.addRow("执行", self.video_run_btn)

        tips = QTextBrowser()
        tips.setObjectName("TipsText")
        tips.setOpenExternalLinks(True)
        tips.setHtml(
            """
            <h3>视频生成说明</h3>
            <p>1. 会读取当前输出目录中的 jpg/jpeg 图片。</p>
            <p>2. 若存在 <b>bgm.mp3</b>，会自动尝试添加背景音乐。</p>
            <p>3. 若系统中没有 ffmpeg，工具会按原项目逻辑尝试下载。</p>
            <p>4. 控制台输出会同步显示在右侧日志面板。</p>
            """
        )

        layout.addWidget(video_group)
        layout.addWidget(tips, stretch=1)
        return page

    def _build_right_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.right_tabs = QTabWidget()

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("LogText")
        self.log_output.setPlaceholderText("这里会显示运行日志、错误信息和处理进度。")

        self.preview_tab = self._build_preview_tab()

        guide = QTextBrowser()
        guide.setObjectName("GuideText")
        guide.setOpenExternalLinks(True)
        guide.setHtml(self._build_guide_html())

        self.right_tabs.addTab(self.log_output, "运行日志")
        self.right_tabs.addTab(self.preview_tab, "示例预览")
        self.right_tabs.addTab(guide, "使用指南")
        self.right_tabs.setCurrentWidget(self.preview_tab)

        layout.addWidget(self.right_tabs)
        return container

    def _build_path_group(self) -> QGroupBox:
        group = QGroupBox("路径与质量")
        form = QFormLayout(group)

        self.input_dir_edit = QLineEdit()
        self.output_dir_edit = QLineEdit()

        self.input_browse_btn = QPushButton("浏览")
        self.output_browse_btn = QPushButton("浏览")

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_dir_edit)
        input_row.addWidget(self.input_browse_btn)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir_edit)
        output_row.addWidget(self.output_browse_btn)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)

        form.addRow("输入目录", self._wrap_layout(input_row))
        form.addRow("输出目录", self._wrap_layout(output_row))
        form.addRow("输出质量", self.quality_spin)

        return group

    def _build_layout_group(self) -> QGroupBox:
        group = QGroupBox("布局与 Logo")
        form = QFormLayout(group)

        self.layout_combo = QComboBox()
        self.logo_enable_check = QCheckBox("启用 Logo")
        self.default_logo_combo = QComboBox()

        form.addRow("布局样式", self.layout_combo)
        form.addRow("Logo 开关", self.logo_enable_check)
        form.addRow("默认 Logo", self.default_logo_combo)
        return group

    def _build_element_group(self) -> QGroupBox:
        group = QGroupBox("四角文字元素")
        form = QFormLayout(group)

        for location_key, location_name in LOCATION_LABELS.items():
            row = QHBoxLayout()

            combo = QComboBox()
            custom_edit = QLineEdit()
            custom_edit.setPlaceholderText("当选择“自定义”时，在此输入自定义文字")
            custom_edit.setEnabled(False)

            row.addWidget(combo, stretch=2)
            row.addWidget(custom_edit, stretch=3)

            self.element_controls[location_key] = {
                "combo": combo,
                "custom": custom_edit,
            }
            form.addRow(location_name, self._wrap_layout(row))

        return group

    def _build_global_group(self) -> QGroupBox:
        group = QGroupBox("全局选项")
        row = QHBoxLayout(group)
        row.setSpacing(16)

        self.white_margin_check = QCheckBox("白色边框")
        self.shadow_check = QCheckBox("阴影")
        self.equivalent_check = QCheckBox("等效焦距")
        self.padding_check = QCheckBox("按原图比例填充")

        row.addWidget(self.white_margin_check)
        row.addWidget(self.shadow_check)
        row.addWidget(self.equivalent_check)
        row.addWidget(self.padding_check)
        row.addStretch(1)

        return group

    def _build_action_group(self) -> QGroupBox:
        group = QGroupBox("执行控制")
        layout = QVBoxLayout(group)

        button_row = QHBoxLayout()
        self.save_btn = QPushButton("保存配置")
        self.save_btn.setObjectName("SecondaryButton")

        self.run_btn = QPushButton("开始批处理")
        self.run_btn.setObjectName("PrimaryButton")

        self.stop_btn = QPushButton("停止")
        self.stop_btn.setObjectName("DangerButton")
        self.stop_btn.setEnabled(False)

        button_row.addWidget(self.save_btn)
        button_row.addWidget(self.run_btn)
        button_row.addWidget(self.stop_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("未开始")

        self.status_label = QLabel("状态：等待执行")
        self.status_label.setObjectName("StatusText")

        layout.addLayout(button_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        return group

    def _build_preview_group(self) -> QGroupBox:
        group = QGroupBox("示例图预览（实时）")
        form = QFormLayout(group)

        self.preview_path_label = QLabel(str(PREVIEW_IMAGE_PATH))
        self.preview_path_label.setObjectName("PreviewPathText")
        self.preview_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.preview_status_label = QLabel("状态：等待实时预览")
        self.preview_status_label.setObjectName("PreviewTipText")

        form.addRow("固定示例图", self.preview_path_label)
        form.addRow("状态", self.preview_status_label)
        return group

    def _build_preview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        self.preview_meta_label = QLabel("预览区：固定示例图 qt_gui/example.jpg（仅展示应用当前设置后的效果）。")
        self.preview_meta_label.setObjectName("PreviewTipText")

        after_group = QGroupBox("应用当前设置后的预览图")
        after_layout = QVBoxLayout(after_group)
        self.after_preview_label = ImagePreviewLabel("暂无处理后预览")
        self.after_preview_label.setMinimumSize(520, 420)
        after_layout.addWidget(self.after_preview_label)

        layout.addWidget(self.preview_meta_label)
        layout.addWidget(after_group, stretch=1)

        return page

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #f6fafb, stop:1 #eef3f6);
            }
            QWidget {
                font-family: "Microsoft YaHei UI";
                font-size: 13px;
                color: #102027;
            }
            QWidget#HeaderCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #eaf6ff, stop:1 #f5fcff);
                border: 1px solid #c8dde8;
                border-radius: 14px;
            }
            QLabel#TitleText {
                color: #1c4f66;
            }
            QLabel#SubtitleText {
                color: #2e6b7f;
            }
            QLabel#HeaderMetaText {
                color: #2f6071;
                font-size: 12px;
            }
            QLabel#HeaderMetaText a {
                color: #2a7ea3;
                text-decoration: underline;
            }
            QTabWidget::pane {
                border: 1px solid #cfd8dc;
                border-radius: 10px;
                background: #ffffff;
            }
            QTabBar::tab {
                background: #e7eff2;
                padding: 8px 14px;
                margin: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                color: #0f2f39;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border: 1px solid #cfd8dc;
                border-bottom-color: #ffffff;
                font-weight: 600;
            }
            QGroupBox {
                border: 1px solid #d8e2e6;
                border-radius: 12px;
                margin-top: 12px;
                background: #ffffff;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #0f2f39;
            }
            QLineEdit, QComboBox, QSpinBox, QTextEdit, QTextBrowser {
                border: 1px solid #c4d3da;
                border-radius: 8px;
                padding: 6px 8px;
                background: #fdfefe;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #1c8f7d;
            }
            QPushButton {
                border-radius: 9px;
                padding: 8px 12px;
                border: 1px solid #b6c9cf;
                background: #f1f7f8;
            }
            QPushButton:hover {
                background: #e1eff2;
            }
            QPushButton#PrimaryButton {
                background: #157a6e;
                border: 1px solid #0f6b60;
                color: white;
                font-weight: 600;
            }
            QPushButton#PrimaryButton:hover {
                background: #0f6b60;
            }
            QPushButton#SecondaryButton {
                background: #dceaf0;
                border: 1px solid #b7cad2;
                color: #12313a;
            }
            QPushButton#DangerButton {
                background: #c43e3e;
                border: 1px solid #b13434;
                color: white;
                font-weight: 600;
            }
            QPushButton#DangerButton:hover {
                background: #a83434;
            }
            QProgressBar {
                border: 1px solid #c0d0d7;
                border-radius: 8px;
                text-align: center;
                background: #f3f7f8;
            }
            QProgressBar::chunk {
                border-radius: 7px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #1f8a70, stop:1 #2aa38a);
            }
            QLabel#StatusText {
                color: #23434d;
                font-weight: 600;
            }
            QTextEdit#LogText {
                background: #0f172a;
                color: #dbeafe;
                font-family: Consolas, "Microsoft YaHei UI";
            }
            QTextBrowser#GuideText, QTextBrowser#TipsText {
                background: #f8fbfc;
                color: #0f2f39;
            }
            QLabel#PreviewImageLabel {
                border: 1px dashed #b8c8cf;
                border-radius: 10px;
                background: #f4f8fa;
                color: #43606a;
            }
            QLabel#PreviewTipText {
                color: #23434d;
            }
            QLabel#PreviewPathText {
                color: #23434d;
                background: #f4f8fa;
                border: 1px solid #d0dde3;
                border-radius: 8px;
                padding: 5px 8px;
            }
            """
        )

    def _bind_events(self) -> None:
        self.input_browse_btn.clicked.connect(self._browse_input_dir)
        self.output_browse_btn.clicked.connect(self._browse_output_dir)

        self.save_btn.clicked.connect(self._save_config)
        self.run_btn.clicked.connect(self._start_processing)
        self.stop_btn.clicked.connect(self._stop_processing)
        self.video_run_btn.clicked.connect(self._start_video)

        # 任意配置变化都会触发预览防抖刷新。
        self.input_dir_edit.textChanged.connect(self._schedule_realtime_preview)
        self.output_dir_edit.textChanged.connect(self._schedule_realtime_preview)
        self.quality_spin.valueChanged.connect(self._schedule_realtime_preview)
        self.layout_combo.currentIndexChanged.connect(self._schedule_realtime_preview)
        self.logo_enable_check.stateChanged.connect(self._schedule_realtime_preview)
        self.default_logo_combo.currentIndexChanged.connect(self._schedule_realtime_preview)
        self.white_margin_check.stateChanged.connect(self._schedule_realtime_preview)
        self.shadow_check.stateChanged.connect(self._schedule_realtime_preview)
        self.equivalent_check.stateChanged.connect(self._schedule_realtime_preview)
        self.padding_check.stateChanged.connect(self._schedule_realtime_preview)

        for location_key, controls in self.element_controls.items():
            combo = controls["combo"]
            custom_edit: QLineEdit = controls["custom"]  # type: ignore[assignment]
            combo.currentIndexChanged.connect(lambda _idx, key=location_key: self._on_element_combo_changed(key))
            custom_edit.textChanged.connect(self._schedule_realtime_preview)

    def _load_config_to_form(self) -> None:
        self._populate_static_options()

        state = get_runtime_config_snapshot()

        self.input_dir_edit.setText(state["input_dir"])
        self.output_dir_edit.setText(state["output_dir"])
        self.quality_spin.setValue(state["quality"])

        self._set_combo_by_data(self.layout_combo, state["layout_type"])
        self.logo_enable_check.setChecked(state["logo_enable"])
        self._set_combo_by_data(self.default_logo_combo, state["default_logo_path"])

        self.white_margin_check.setChecked(state["white_margin"])
        self.shadow_check.setChecked(state["shadow"])
        self.equivalent_check.setChecked(state["equivalent_focal"])
        self.padding_check.setChecked(state["padding_ratio"])

        for location_key, controls in self.element_controls.items():
            element_state = state["elements"][location_key]
            combo = controls["combo"]
            custom_edit = controls["custom"]

            self._set_combo_by_data(combo, element_state.get("name", ""))
            custom_edit.setText(element_state.get("custom_value", ""))
            self._toggle_custom_input(location_key)

        self._schedule_realtime_preview()

        self._append_log("配置已加载，可直接开始处理。")

    def _populate_static_options(self) -> None:
        self.layout_combo.clear()
        for display_name, value in get_layout_options():
            self.layout_combo.addItem(display_name, value)

        self.default_logo_combo.clear()
        for display_name, path in get_default_logo_options():
            self.default_logo_combo.addItem(f"{display_name} ({path})", path)

        element_options = get_element_options()
        for controls in self.element_controls.values():
            combo = controls["combo"]
            combo.clear()
            for display_name, value in element_options:
                combo.addItem(display_name, value)

    def _collect_form_settings(self) -> dict:
        elements = {}
        for location_key, controls in self.element_controls.items():
            combo: QComboBox = controls["combo"]  # type: ignore[assignment]
            custom_edit: QLineEdit = controls["custom"]  # type: ignore[assignment]
            elements[location_key] = {
                "name": combo.currentData(),
                "custom_value": custom_edit.text().strip(),
            }

        return {
            "input_dir": self.input_dir_edit.text().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
            "quality": int(self.quality_spin.value()),
            "layout_type": self.layout_combo.currentData(),
            "logo_enable": self.logo_enable_check.isChecked(),
            "default_logo_path": self.default_logo_combo.currentData(),
            "white_margin": self.white_margin_check.isChecked(),
            "shadow": self.shadow_check.isChecked(),
            "equivalent_focal": self.equivalent_check.isChecked(),
            "padding_ratio": self.padding_check.isChecked(),
            "elements": elements,
        }

    def _validate_settings(self, settings: dict) -> tuple[bool, str]:
        input_dir = Path(settings["input_dir"])
        if not input_dir.exists() or not input_dir.is_dir():
            return False, "输入目录不存在，请检查路径。"

        output_dir = settings["output_dir"]
        if output_dir:
            output_path = Path(output_dir)
            try:
                output_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return False, f"输出目录创建失败：{exc}"

        return True, ""

    def _save_config(self) -> None:
        settings = self._collect_form_settings()
        ok, message = self._validate_settings(settings)
        if not ok:
            QMessageBox.warning(self, "参数错误", message)
            return

        apply_runtime_config_from_values(settings, save=True)
        self._append_log("配置保存成功。")
        QMessageBox.information(self, "完成", "配置已保存。")

    def _start_processing(self) -> None:
        if self.processing_thread is not None:
            QMessageBox.information(self, "提示", "图片处理任务正在运行中。")
            return
        if self.video_thread is not None:
            QMessageBox.information(self, "提示", "视频生成任务进行中，请稍后再启动图片处理。")
            return

        settings = self._collect_form_settings()
        ok, message = self._validate_settings(settings)
        if not ok:
            QMessageBox.warning(self, "参数错误", message)
            return

        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")
        self.status_label.setText("状态：处理中...")

        self.processing_thread = QThread(self)
        self.processing_worker = ProcessWorker(settings)
        self.processing_worker.moveToThread(self.processing_thread)

        self.processing_thread.started.connect(self.processing_worker.run)
        self.processing_worker.message.connect(self._append_log)
        self.processing_worker.progress.connect(self._on_process_progress)
        self.processing_worker.finished.connect(self._on_process_finished)
        self.processing_worker.crashed.connect(self._on_process_crashed)

        self.processing_worker.finished.connect(self.processing_thread.quit)
        self.processing_worker.crashed.connect(self.processing_thread.quit)
        self.processing_thread.finished.connect(self._on_process_thread_finished)

        self.run_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.video_run_btn.setEnabled(False)
        self._set_realtime_preview_paused(True, "批处理进行中，实时预览已暂停")

        self._append_log("开始执行图片批处理任务。")
        self.processing_thread.start()

    def _stop_processing(self) -> None:
        if self.processing_worker is None:
            return
        self.processing_worker.request_stop()
        self._append_log("已发送停止请求，当前图片处理完成后会退出。")
        self.stop_btn.setEnabled(False)

    def _start_video(self) -> None:
        if self.video_thread is not None:
            QMessageBox.information(self, "提示", "视频生成任务正在运行中。")
            return
        if self.processing_thread is not None:
            QMessageBox.information(self, "提示", "图片处理任务进行中，请稍后再生成视频。")
            return

        settings = self._collect_form_settings()
        ok, message = self._validate_settings(settings)
        if not ok:
            QMessageBox.warning(self, "参数错误", message)
            return

        gap_seconds = int(self.video_gap_spin.value())

        self.video_thread = QThread(self)
        self.video_worker = VideoWorker(settings, gap_seconds)
        self.video_worker.moveToThread(self.video_thread)

        self.video_thread.started.connect(self.video_worker.run)
        self.video_worker.message.connect(self._append_log)
        self.video_worker.finished.connect(self._on_video_finished)
        self.video_worker.crashed.connect(self._on_video_crashed)

        self.video_worker.finished.connect(self.video_thread.quit)
        self.video_worker.crashed.connect(self.video_thread.quit)
        self.video_thread.finished.connect(self._on_video_thread_finished)

        self.video_run_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self._set_realtime_preview_paused(True, "视频生成进行中，实时预览已暂停")
        self._append_log(f"开始生成视频，图片间隔：{gap_seconds} 秒。")
        self.video_thread.start()

    def _on_process_progress(self, index: int, total: int, filename: str, ok: bool, _msg: str) -> None:
        if total <= 0:
            return
        percent = int(index * 100 / total)
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(f"{percent}%")

        state_text = "成功" if ok else "失败"
        self.status_label.setText(f"状态：处理中 ({index}/{total}) - {filename} [{state_text}]")

    def _on_process_finished(self, result: dict) -> None:
        stopped_text = "（已手动停止）" if result.get("stopped") else ""
        summary = (
            f"处理完成{stopped_text}：总数 {result.get('total', 0)}，"
            f"成功 {result.get('success', 0)}，失败 {result.get('failed', 0)}"
        )
        self.status_label.setText("状态：处理结束")
        self._append_log(summary)

        failed_files = result.get("failed_files", [])
        if failed_files:
            self._append_log("失败明细：")
            for item in failed_files:
                self._append_log(f"  - {item}")

        QMessageBox.information(self, "批处理完成", summary)

    def _on_process_crashed(self, message: str) -> None:
        self.status_label.setText("状态：处理异常")
        self._append_log(f"处理任务异常：{message}")
        QMessageBox.critical(self, "处理失败", message)

    def _on_process_thread_finished(self) -> None:
        if self.processing_worker is not None:
            self.processing_worker.deleteLater()
            self.processing_worker = None
        if self.processing_thread is not None:
            self.processing_thread.deleteLater()
            self.processing_thread = None

        self.run_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.video_run_btn.setEnabled(True)
        self._set_realtime_preview_paused(False)

    def _on_video_finished(self, output_dir: str) -> None:
        self._append_log(f"视频生成完成，请检查目录：{output_dir}")
        QMessageBox.information(self, "视频生成完成", f"视频输出目录：{output_dir}")

    def _on_video_crashed(self, message: str) -> None:
        self._append_log(f"视频生成异常：{message}")
        QMessageBox.critical(self, "视频生成失败", message)

    def _on_video_thread_finished(self) -> None:
        if self.video_worker is not None:
            self.video_worker.deleteLater()
            self.video_worker = None
        if self.video_thread is not None:
            self.video_thread.deleteLater()
            self.video_thread = None

        self.video_run_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.save_btn.setEnabled(True)
        self._set_realtime_preview_paused(False)

    def _browse_input_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输入目录", self.input_dir_edit.text().strip() or ".")
        if selected:
            self.input_dir_edit.setText(selected)

    def _browse_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_edit.text().strip() or ".")
        if selected:
            self.output_dir_edit.setText(selected)

    def _on_element_combo_changed(self, location_key: str) -> None:
        self._toggle_custom_input(location_key)
        self._schedule_realtime_preview()

    def _set_realtime_preview_paused(self, paused: bool, reason: str | None = None) -> None:
        self.realtime_preview_paused = paused
        if paused:
            self.preview_status_label.setText(f"状态：{reason or '实时预览已暂停'}")
            return
        self.preview_status_label.setText("状态：任务结束，正在刷新实时预览...")
        self._schedule_realtime_preview()

    def _schedule_realtime_preview(self, *_args) -> None:
        if self.realtime_preview_paused:
            return
        self.preview_timer.start(350)

    def _refresh_preview_now(self) -> None:
        if self.realtime_preview_paused:
            return
        if self.processing_thread is not None or self.video_thread is not None:
            return
        if self.preview_busy:
            self.preview_pending = True
            return

        if not PREVIEW_IMAGE_PATH.exists() or not PREVIEW_IMAGE_PATH.is_file():
            self.after_preview_label.set_preview_pixmap(None)
            self.preview_meta_label.setText("预览区：未找到固定示例图，无法生成实时预览。")
            self.preview_status_label.setText(f"状态：缺少示例图 {PREVIEW_IMAGE_PATH}")
            return

        self.preview_busy = True
        before_image = None
        after_image = None
        try:
            settings = self._collect_form_settings()
            before_image, after_image, _message = build_preview_images(PREVIEW_IMAGE_PATH, settings)

            after_pixmap = self._pil_to_qpixmap(after_image)

            self.after_preview_label.set_preview_pixmap(after_pixmap)
            self.preview_meta_label.setText(
                f"示例图：{PREVIEW_IMAGE_PATH.name} | 预览尺寸：{after_image.width}x{after_image.height}"
            )
            self.preview_status_label.setText("状态：实时预览已更新")
        except Exception as exc:
            self.preview_status_label.setText(f"状态：实时预览失败：{exc}")
            self._append_log(f"实时预览失败：{exc}")
        finally:
            if before_image is not None:
                before_image.close()
            if after_image is not None:
                after_image.close()
            self.preview_busy = False

        if self.preview_pending:
            self.preview_pending = False
            self.preview_timer.start(120)

    def _toggle_custom_input(self, location_key: str) -> None:
        controls = self.element_controls[location_key]
        combo: QComboBox = controls["combo"]  # type: ignore[assignment]
        custom_edit: QLineEdit = controls["custom"]  # type: ignore[assignment]
        is_custom = combo.currentData() == "Custom"
        custom_edit.setEnabled(is_custom)
        if not is_custom and custom_edit.text().strip() == "":
            custom_edit.clear()

    def _set_combo_by_data(self, combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {text}")

    @staticmethod
    def _pil_to_qpixmap(image) -> QPixmap:
        rgba_image = image.convert("RGBA")
        data = rgba_image.tobytes("raw", "RGBA")
        q_image = QImage(data, rgba_image.width, rgba_image.height, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(q_image.copy())

    def _build_guide_html(self) -> str:
        return """
        <h2>Semi-Utils GUI 使用指南</h2>
        <h3>一、快速开始</h3>
        <p>1. 在 <b>路径与质量</b> 中设置输入目录与输出目录。</p>
        <p>2. 在 <b>布局与 Logo</b> 选择需要的布局和 Logo 开关。</p>
        <p>3. 在 <b>四角文字元素</b> 配置左上/右上/左下/右下显示内容。</p>
        <p>4. 修改任意设置后，系统会基于固定示例图 <b>qt_gui/example.jpg</b> 自动刷新预览。</p>
        <p>5. 点击 <b>开始批处理</b>，进度与结果会显示在日志面板。</p>

        <h3>二、功能分区说明</h3>
        <p><b>图片处理页</b>：负责所有图片输出配置与批处理执行。</p>
        <p><b>视频生成页</b>：把输出目录图片拼成视频，可设置切换间隔。</p>
        <p><b>示例预览页</b>：仅展示应用当前设置后的预览图效果。</p>
        <p><b>运行日志页</b>：查看实时进度、报错和任务结果。</p>

        <h3>三、实用建议</h3>
        <p>1. 若只想在原目录旁生成新图，可将输出目录留空。</p>
        <p>2. 自定义文字仅在对应位置选择“自定义”时生效。</p>
        <p>3. 实时预览仅用于效果观察，不会写入输出目录。</p>
        <p>4. 视频功能依赖 ffmpeg，首次使用可能会自动准备。</p>

        <h3>四、故障排查</h3>
        <p>1. 若提示输入目录无图片，请确认扩展名是 jpg/jpeg/png。</p>
        <p>2. 若处理失败，请先看右侧日志，再看 logs 目录下日志文件。</p>
        <p>3. 若视频未生成，先检查输出目录中是否存在图片。</p>
        """

    @staticmethod
    def _wrap_layout(layout: QHBoxLayout) -> QWidget:
        widget = QWidget()
        widget.setLayout(layout)
        return widget


def main() -> None:
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
