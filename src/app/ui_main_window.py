# ui_main_window.py (QMessageBoxによるエラー通知追加版)

import sys
import os
import platform
import subprocess

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter,
    QFormLayout, QPushButton, QHBoxLayout, QFrame
)
from PyQt6.QtGui import QAction, QFontMetrics
from PyQt6.QtCore import Qt, QTimer

from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient
from file_scanner import FileScanner
from ocr_orchestrator import OcrOrchestrator
from file_model import FileInfo

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING,
    LISTVIEW_UPDATE_INTERVAL_MS
)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.log_manager = LogManager()
        self.log_manager.debug("MainWindow initializing...", context="MAINWIN_LIFECYCLE")

        self.setWindowTitle("AI inside Cube Client Ver.0.0.12")

        self._initialize_core_components_and_config()
        self._connect_orchestrator_signals()
        self._setup_main_window_geometry()
        self._setup_ui_elements()
        self._load_previous_state_and_perform_initial_scan()
        self._restore_view_and_log_state()
        self._update_all_ui_controls_state()

        self.log_manager.info("Application initialized successfully.", context="SYSTEM_LIFECYCLE")

    def _initialize_core_components_and_config(self):
        self.config = ConfigManager.load()
        self.is_ocr_running = False
        self.processed_files_info: list[FileInfo] = []

        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget)

        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.file_scanner = FileScanner(self.log_manager, self.config)
        self.ocr_orchestrator = OcrOrchestrator(self.api_client, self.log_manager, self.config)

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.perform_batch_list_view_update)

        self.input_folder_path = ""

    def _connect_orchestrator_signals(self):
        if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator:
            self.ocr_orchestrator.ocr_process_started_signal.connect(self._handle_ocr_process_started_from_orchestrator)
            self.ocr_orchestrator.ocr_process_finished_signal.connect(self._handle_ocr_process_finished_from_orchestrator)
            self.ocr_orchestrator.original_file_status_update_signal.connect(self.on_original_file_status_update_from_worker)
            self.ocr_orchestrator.file_ocr_processed_signal.connect(self.on_file_ocr_processed)
            self.ocr_orchestrator.file_searchable_pdf_processed_signal.connect(self.on_file_searchable_pdf_processed)
            self.ocr_orchestrator.request_ui_controls_update_signal.connect(self.update_ocr_controls)
            self.ocr_orchestrator.request_list_view_update_signal.connect(self._handle_request_list_view_update)

    def _handle_request_list_view_update(self, updated_file_list: list[FileInfo]):
        self.log_manager.debug("MainWindow: Received request to update ListView from orchestrator.", context="UI_UPDATE")
        self.processed_files_info = updated_file_list
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        self.update_all_status_displays()

    def _setup_main_window_geometry(self):
        # (変更なし)
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700})
        state_cfg = self.config.get("window_state", "normal")
        pos_cfg = self.config.get("window_position")
        self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try:
                screen_geometry = QApplication.primaryScreen().geometry()
                self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e:
                self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e)
                self.move(100, 100)
        else:
            self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized":
            self.showMaximized()

    def _setup_ui_elements(self):
        # (変更なし)
        self._setup_central_widget_and_main_layout()
        self._setup_views_log_widget_and_splitter()
        self._setup_status_bar()
        self._setup_toolbars_and_folder_labels()

    def _setup_central_widget_and_main_layout(self):
        # (変更なし)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.setSpacing(0)

    def _setup_views_log_widget_and_splitter(self):
        # (変更なし)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.summary_view = SummaryView()
        self.summary_view.log_manager = self.log_manager
        self.list_view = ListView(self.processed_files_info)
        self.list_view.item_check_state_changed.connect(self.on_list_item_check_state_changed)
        self.stack.addWidget(self.summary_view)
        self.stack.addWidget(self.list_view)
        self.splitter.addWidget(self.stack)
        self.log_container = QWidget()
        log_layout_inner = QVBoxLayout(self.log_container)
        log_layout_inner.setContentsMargins(8, 8, 8, 8)
        log_layout_inner.setSpacing(0)
        self.log_header = QLabel("ログ：")
        self.log_header.setStyleSheet("margin-left: 6px; padding-bottom: 0px; font-weight: bold;")
        log_layout_inner.addWidget(self.log_header)
        self.log_widget.setStyleSheet("""
            QTextEdit { font-family: Consolas, Meiryo, monospace; font-size: 9pt; border: 1px solid #D0D0D0; margin: 0px; }
            QTextEdit QScrollBar:vertical { border: 1px solid #C0C0C0; background: #F0F0F0; width: 15px; margin: 0px; }
            QTextEdit QScrollBar::handle:vertical { background: #A0A0A0; min-height: 20px; border-radius: 7px; }
            QTextEdit QScrollBar::add-line:vertical, QTextEdit QScrollBar::sub-line:vertical { border: none; background: none; height: 0px; width: 0px; }
            QTextEdit QScrollBar::up-arrow:vertical, QTextEdit QScrollBar::down-arrow:vertical { height: 0px; width: 0px; background: none; }
            QTextEdit QScrollBar::add-page:vertical, QTextEdit QScrollBar::sub-page:vertical { background: none; }
        """)
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        log_layout_inner.addWidget(self.log_widget)
        self.log_container.setStyleSheet("margin: 0px 6px 6px 6px;")
        self.splitter.addWidget(self.log_container)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        splitter_sizes = self.config.get("splitter_sizes")
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0:
            self.splitter.setSizes(splitter_sizes)
        else:
            default_height = self.height()
            initial_splitter_sizes = [int(default_height * 0.65), int(default_height * 0.35)]
            self.splitter.setSizes(initial_splitter_sizes)
        self.main_layout.addWidget(self.splitter)

    def _setup_status_bar(self):
        # (変更なし)
        self.status_bar_frame = QFrame()
        self.status_bar_frame.setFrameShape(QFrame.Shape.NoFrame)
        self.status_bar_frame.setStyleSheet("""
            QFrame#StatusBarFrame { background-color: #ECECEC; border-top: 1px solid #B0B0B0; min-height: 26px; max-height: 26px; }
            QLabel#StatusBarLabel { padding: 3px 0px; font-size: 8pt; border: none; }
        """)
        self.status_bar_frame.setObjectName("StatusBarFrame")
        status_bar_layout = QHBoxLayout(self.status_bar_frame)
        status_bar_layout.setContentsMargins(15, 2, 15, 2)
        self.status_total_list_label = QLabel("リスト総数: 0")
        self.status_total_list_label.setObjectName("StatusBarLabel")
        self.status_selected_files_label = QLabel("選択中: 0")
        self.status_selected_files_label.setObjectName("StatusBarLabel")
        self.status_success_files_label = QLabel("成功: 0")
        self.status_success_files_label.setObjectName("StatusBarLabel")
        self.status_error_files_label = QLabel("エラー: 0")
        self.status_error_files_label.setObjectName("StatusBarLabel")
        status_bar_layout.addWidget(self.status_total_list_label)
        status_bar_layout.addSpacing(25)
        status_bar_layout.addWidget(self.status_selected_files_label)
        status_bar_layout.addStretch(1)
        status_bar_layout.addWidget(self.status_success_files_label)
        status_bar_layout.addSpacing(25)
        status_bar_layout.addWidget(self.status_error_files_label)
        self.main_layout.addWidget(self.status_bar_frame)

    def _setup_toolbars_and_folder_labels(self):
        # (変更なし)
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.input_folder_action = QAction("📂入力", self)
        self.input_folder_action.triggered.connect(self.select_input_folder)
        toolbar.addAction(self.input_folder_action)
        self.toggle_view_action = QAction("📑ビュー", self)
        self.toggle_view_action.triggered.connect(self.toggle_view)
        toolbar.addAction(self.toggle_view_action)
        self.option_action = QAction("⚙️設定", self)
        self.option_action.triggered.connect(self.show_option_dialog)
        toolbar.addAction(self.option_action)
        toolbar.addSeparator()
        self.start_ocr_action = QAction("▶️開始", self)
        self.start_ocr_action.triggered.connect(self.confirm_start_ocr)
        toolbar.addAction(self.start_ocr_action)
        self.resume_ocr_action = QAction("↪️再開", self)
        self.resume_ocr_action.setToolTip("未処理または失敗したファイルのOCR処理を再開します")
        self.resume_ocr_action.triggered.connect(self.confirm_resume_ocr)
        toolbar.addAction(self.resume_ocr_action)
        self.stop_ocr_action = QAction("⏹️中止", self)
        self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr)
        toolbar.addAction(self.stop_ocr_action)
        self.rescan_action = QAction("🔄再スキャン", self)
        self.rescan_action.triggered.connect(self.confirm_rescan_ui)
        self.rescan_action.setEnabled(False)
        toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        self.log_toggle_action = QAction("📄ログ表示", self)
        self.log_toggle_action.triggered.connect(self.toggle_log_display)
        toolbar.addAction(self.log_toggle_action)
        self.clear_log_action = QAction("🗑️ログクリア", self)
        self.clear_log_action.triggered.connect(self.clear_log_display)
        toolbar.addAction(self.clear_log_action)
        folder_label_toolbar = QToolBar("Folder Paths Toolbar")
        folder_label_toolbar.setMovable(False)
        folder_label_widget = QWidget()
        folder_label_layout = QFormLayout(folder_label_widget)
        folder_label_layout.setContentsMargins(5, 5, 5, 5)
        folder_label_layout.setSpacing(3)
        self.input_folder_button = QPushButton()
        self._update_folder_display()
        self.input_folder_button.setStyleSheet("""
            QPushButton { border: none; background: transparent; text-align: left; padding: 0px; margin: 0px; }
            QPushButton:hover { text-decoration: underline; color: blue; }
        """)
        self.input_folder_button.setFlat(True)
        self.input_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.input_folder_button.clicked.connect(self.open_input_folder_in_explorer)
        folder_label_layout.addRow("入力フォルダ:", self.input_folder_button)
        folder_label_toolbar.addWidget(folder_label_widget)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar)
        self.insertToolBarBreak(folder_label_toolbar)

    def _update_folder_display(self):
        # (変更なし)
        if hasattr(self, 'input_folder_button'):
            display_path = self.input_folder_path or "未選択"
            self.input_folder_button.setText(display_path)
            self.input_folder_button.setToolTip(self.input_folder_path if self.input_folder_path else "入力フォルダが選択されていません")

    def _load_previous_state_and_perform_initial_scan(self):
        # (変更なし)
        self.input_folder_path = self.config.get("last_target_dir", "")
        self._update_folder_display()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT")
            self.perform_initial_scan()
        elif self.input_folder_path:
            self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT")
            self.input_folder_path = ""
            self._update_folder_display()
            self._clear_and_update_file_list_display()
        else:
            self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT")
            self._update_folder_display()
            self._clear_and_update_file_list_display()

    def _clear_and_update_file_list_display(self):
        # (変更なし)
        self.processed_files_info = []
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        if hasattr(self, 'summary_view') and self.summary_view:
            self.summary_view.reset_summary()
        self.update_all_status_displays()

    def _restore_view_and_log_state(self):
        # (変更なし)
        self.current_view = self.config.get("current_view", 0)
        if hasattr(self, 'stack'):
            self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True)
        if hasattr(self, 'log_container'):
            self.log_container.setVisible(log_visible)

    def _update_all_ui_controls_state(self):
        # (変更なし)
        self.update_ocr_controls()

    def _handle_ocr_process_started_from_orchestrator(self, num_files_to_process: int, updated_file_list: list[FileInfo]):
        # (変更なし)
        self.log_manager.info(f"MainWindow: OCR process started signal received for {num_files_to_process} files.", context="OCR_FLOW_MAIN")
        self.is_ocr_running = True
        self.processed_files_info = updated_file_list
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'):
            self.summary_view.start_processing(num_files_to_process)
        self.update_status_bar()
        self.update_ocr_controls()

    def _handle_ocr_process_finished_from_orchestrator(self, was_interrupted: bool):
        # (変更なし)
        self.log_manager.info(f"MainWindow: OCR process finished signal received. Interrupted: {was_interrupted}", context="OCR_FLOW_MAIN")
        self.is_ocr_running = False
        if was_interrupted:
            self.log_manager.info("MainWindow: OCR processing was interrupted (from orchestrator signal).", context="OCR_FLOW_MAIN")
            current_config = self.config
            output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both")
            json_status_on_interrupt = "中断" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
            pdf_status_on_interrupt = "中断" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
            for file_info in self.processed_files_info:
                if file_info.ocr_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING] or \
                   (file_info.status == OCR_STATUS_PROCESSING and file_info.ocr_engine_status == OCR_STATUS_PROCESSING):
                    file_info.ocr_engine_status = OCR_STATUS_FAILED
                    file_info.status = "中断"
                    file_info.ocr_result_summary = "(処理が中止されました)"
                    file_info.json_status = json_status_on_interrupt
                    file_info.searchable_pdf_status = pdf_status_on_interrupt
        self.perform_batch_list_view_update()
        self.update_ocr_controls()
        final_message = "全てのファイルのOCR処理が完了しました。"
        if was_interrupted:
            final_message = "OCR処理が中止されました。"
        QMessageBox.information(self, "処理終了", final_message)

    def update_status_bar(self):
        # (変更なし)
        total_list_items = len(self.processed_files_info)
        selected_for_processing_count = 0
        ocr_success_count = self.summary_view.ocr_completed_count if hasattr(self, 'summary_view') else 0
        ocr_error_count = self.summary_view.ocr_error_count if hasattr(self, 'summary_view') else 0
        for file_info in self.processed_files_info:
            if file_info.is_checked and file_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                selected_for_processing_count += 1
        if hasattr(self, 'status_total_list_label'):
            self.status_total_list_label.setText(f"リスト総数: {total_list_items}")
            self.status_selected_files_label.setText(f"選択中: {selected_for_processing_count}")
            self.status_success_files_label.setText(f"成功: {ocr_success_count}")
            self.status_error_files_label.setText(f"エラー: {ocr_error_count}")

    def update_all_status_displays(self):
        # (変更なし)
        size_skipped_count = 0
        checked_and_processable_for_summary = 0
        for file_info in self.processed_files_info:
            if file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                size_skipped_count += 1
            elif file_info.is_checked:
                checked_and_processable_for_summary += 1
        if hasattr(self, 'summary_view'):
            self.summary_view.update_summary_counts(
                total_scanned=len(self.processed_files_info),
                total_ocr_target=checked_and_processable_for_summary,
                skipped_size=size_skipped_count
            )
        self.update_status_bar()

    def on_list_item_check_state_changed(self, row_index, is_checked):
        # (変更なし)
        if 0 <= row_index < len(self.processed_files_info):
            self.processed_files_info[row_index].is_checked = is_checked
            self.log_manager.debug(f"File '{self.processed_files_info[row_index].name}' check state in data model changed to: {is_checked}", context="UI_EVENT")
            self.update_all_status_displays()
            self.update_ocr_controls()

    def perform_initial_scan(self):
        # (変更なし)
        self.log_manager.info(f"スキャン開始: {self.input_folder_path}", context="FILE_SCAN_MAIN")
        if self.update_timer.isActive(): self.update_timer.stop()
        self.processed_files_info = []
        current_config = self.config
        collected_files_paths, max_files_info, depth_limited_folders = self.file_scanner.scan_folder(
            self.input_folder_path
        )
        if collected_files_paths:
            self.processed_files_info = self.file_scanner.create_initial_file_list(
                collected_files_paths, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_NOT_PROCESSED
            )
            processable_count = sum(1 for item in self.processed_files_info if item.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT)
            self.log_manager.info(f"MainWindow: Scan completed. {len(self.processed_files_info)} files loaded ({processable_count} processable).", context="FILE_SCAN_MAIN")
        else:
            self.log_manager.info("MainWindow: Scan completed. No files found or collected.", context="FILE_SCAN_MAIN")
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        warning_messages = []
        if max_files_info:
            msg = f"最大処理ファイル数 ({max_files_info['limit']}件) に達したため、フォルダ「{max_files_info['last_scanned_folder']}」以降の一部のファイルは読み込まれていません。"
            warning_messages.append(msg)
        if depth_limited_folders:
            folders_to_show = depth_limited_folders[:3]
            folders_str = ", ".join([os.path.basename(f) for f in folders_to_show])
            if len(depth_limited_folders) > 3:
                folders_str += f" など、計{len(depth_limited_folders)}フォルダ"
            msg = f"再帰検索の深さ制限により、サブフォルダ「{folders_str}」以降は検索されていません。"
            warning_messages.append(msg)
        if warning_messages:
            QMessageBox.warning(self, "スキャン結果の注意", "\n\n".join(warning_messages))
        if hasattr(self.summary_view, 'reset_summary'):
            self.summary_view.reset_summary()
        self.update_all_status_displays()
        self.update_ocr_controls()

    def append_log_message_to_widget(self, level, message):
        # (変更なし)
        if hasattr(self, 'log_widget') and self.log_widget:
            if level == LogLevel.ERROR: self.log_widget.append(f'<font color="red">{message}</font>')
            elif level == LogLevel.WARNING: self.log_widget.append(f'<font color="orange">{message}</font>')
            elif level == LogLevel.DEBUG: self.log_widget.append(f'<font color="gray">{message}</font>')
            else: self.log_widget.append(message)
            self.log_widget.ensureCursorVisible()

    def select_input_folder(self):
        # (変更なし)
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.log_manager.info(f"Input folder selected by user: {folder}", context="UI_EVENT")
            if folder != self.input_folder_path or not self.processed_files_info:
                self.input_folder_path = folder
                self._update_folder_display()
                self.log_manager.info(f"Performing rescan for newly selected folder: {folder}", context="UI_EVENT")
                self.perform_rescan()
            else:
                self.log_manager.info("Selected folder is the same as current and list is not empty. No rescan forced.", context="UI_EVENT")
        else:
            self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")
        self._update_folder_display()

    def open_input_folder_in_explorer(self):
        # (変更なし)
        self.log_manager.debug(f"Attempting to open folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            try:
                if platform.system() == "Windows": os.startfile(os.path.normpath(self.input_folder_path))
                elif platform.system() == "Darwin": subprocess.run(['open', self.input_folder_path], check=True)
                else: subprocess.run(['xdg-open', self.input_folder_path], check=True)
                self.log_manager.info(f"Successfully opened folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
            except Exception as e:
                self.log_manager.error(f"Failed to open folder '{self.input_folder_path}'. Error: {e}", context="UI_ACTION_OPEN_FOLDER_ERROR", exception_info=e)
                QMessageBox.warning(self, "フォルダを開けません", f"フォルダ '{self.input_folder_path}' を開けませんでした。\nエラー: {e}")
        else:
            self.log_manager.warning(f"Cannot open folder: Path is invalid or not set. Path: '{self.input_folder_path}'", context="UI_ACTION_OPEN_FOLDER_INVALID")
            QMessageBox.information(self, "フォルダ情報なし", "入力フォルダが選択されていないか、無効なパスです。")

    def toggle_view(self):
        # (変更なし)
        if hasattr(self, 'stack'):
            self.current_view = 1 - self.current_view
            self.stack.setCurrentIndex(self.current_view)
            self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")

    def toggle_log_display(self):
        # (変更なし)
        if hasattr(self, 'log_container'):
            visible = self.log_container.isVisible()
            self.log_container.setVisible(not visible)
            self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION")

    def show_option_dialog(self):
        # (変更なし)
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION")
        old_config_copy = self.config.copy()
        old_api_type_options = old_config_copy.get("options", {}).get(old_config_copy.get("api_type"), {})
        old_max_files = old_api_type_options.get("max_files_to_process")
        old_recursion_depth = old_api_type_options.get("recursion_depth")
        dialog = OptionDialog(self)
        if dialog.exec():
            self.config = ConfigManager.load()
            self.log_manager.info("Options saved and reloaded.", context="CONFIG_EVENT")
            self.api_client.config = self.config
            self.api_client.api_key = self.config.get("api_key")
            self.api_client.base_uri = self.config.get("base_uri", "")
            api_type_cfg = self.config.get("api_type", "cube_fullocr")
            self.api_client.endpoints = self.config.get("endpoints", {}).get(api_type_cfg, {})
            if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator:
                self.ocr_orchestrator.update_config(self.config)
            if hasattr(self, 'file_scanner') and self.file_scanner:
                 self.file_scanner.config = self.config
            new_api_type_options = self.config.get("options", {}).get(self.config.get("api_type"), {})
            new_max_files = new_api_type_options.get("max_files_to_process")
            new_recursion_depth = new_api_type_options.get("recursion_depth")
            rescan_needed_due_to_collection_settings = (old_max_files != new_max_files or old_recursion_depth != new_recursion_depth)
            if rescan_needed_due_to_collection_settings:
                if self.input_folder_path and os.path.isdir(self.input_folder_path):
                    QMessageBox.information(self, "設定変更の適用", "ファイル検索範囲に関する設定（最大ファイル数または再帰深度）が変更されたため、ファイルリストを再スキャンします。")
                    self.perform_rescan()
                else:
                    self.processed_files_info = []
                    if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info)
                    self.update_all_status_displays()
                    self.log_manager.info("File collection parameters changed, but no input folder selected. List cleared.", context="CONFIG_EVENT")
            else:
                self.log_manager.info(f"Settings changed (size limit or output format). Re-evaluating file statuses.", context="CONFIG_EVENT")
                new_upload_max_size_mb = new_api_type_options.get("upload_max_size_mb", 50)
                new_upload_max_bytes = new_upload_max_size_mb * 1024 * 1024
                new_file_actions_cfg = self.config.get("file_actions", {})
                new_output_format_cfg = new_file_actions_cfg.get("output_format", "both")
                default_json_status = "-" if new_output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
                default_pdf_status = "-" if new_output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
                items_status_updated = False
                for file_info in self.processed_files_info:
                    current_file_size = file_info.size
                    prev_ocr_engine_status = file_info.ocr_engine_status
                    prev_is_checked = file_info.is_checked
                    original_status_text = file_info.status
                    original_json_status = file_info.json_status
                    original_pdf_status = file_info.searchable_pdf_status
                    is_now_skipped_by_size = current_file_size > new_upload_max_bytes
                    if is_now_skipped_by_size:
                        if file_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                            file_info.status = "スキップ(サイズ上限)"
                            file_info.ocr_engine_status = OCR_STATUS_SKIPPED_SIZE_LIMIT
                            file_info.ocr_result_summary = f"ファイルサイズが上限 ({new_upload_max_size_mb}MB) を超過"
                            file_info.json_status = "スキップ"
                            file_info.searchable_pdf_status = "スキップ"
                            file_info.is_checked = False
                    else:
                        if file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                            file_info.status = "待機中"
                            file_info.ocr_engine_status = OCR_STATUS_NOT_PROCESSED
                            file_info.ocr_result_summary = ""
                            file_info.is_checked = True
                        if file_info.ocr_engine_status == OCR_STATUS_NOT_PROCESSED:
                            file_info.json_status = default_json_status
                            file_info.searchable_pdf_status = default_pdf_status
                    if (file_info.ocr_engine_status != prev_ocr_engine_status or
                        file_info.status != original_status_text or
                        file_info.json_status != original_json_status or
                        file_info.searchable_pdf_status != original_pdf_status or
                        file_info.is_checked != prev_is_checked):
                        items_status_updated = True
                        if prev_ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT and file_info.ocr_engine_status == OCR_STATUS_NOT_PROCESSED:
                             self.log_manager.debug(f"File '{file_info.name}' NO LONGER SKIPPED by size. Status reset.", context="CONFIG_EVENT")
                        elif prev_ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                             self.log_manager.debug(f"File '{file_info.name}' NOW SKIPPED due to new size limit.", context="CONFIG_EVENT")
                if items_status_updated:
                    if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info)
                self.update_all_status_displays()
            self.update_ocr_controls()
        else:
            self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

    def confirm_start_ocr(self):
        if hasattr(self, 'ocr_orchestrator'):
            self.ocr_orchestrator.confirm_and_start_ocr(self.processed_files_info, self.input_folder_path, self)

    def confirm_resume_ocr(self):
        if hasattr(self, 'ocr_orchestrator'):
            self.ocr_orchestrator.confirm_and_resume_ocr(self.processed_files_info, self.input_folder_path, self)

    def confirm_stop_ocr(self):
        if hasattr(self, 'ocr_orchestrator'):
            self.ocr_orchestrator.confirm_and_stop_ocr(self)

    def on_original_file_status_update_from_worker(self, original_file_path, status_message):
        target_file_info = next((item for item in self.processed_files_info if item.path == original_file_path), None)
        if target_file_info:
            self.log_manager.debug(f"UI Update for '{target_file_info.name}': {status_message}", context="UI_STATUS_UPDATE")
            target_file_info.status = status_message
            if status_message == OCR_STATUS_SPLITTING: target_file_info.ocr_engine_status = OCR_STATUS_SPLITTING
            elif OCR_STATUS_PART_PROCESSING in status_message: target_file_info.ocr_engine_status = OCR_STATUS_PART_PROCESSING
            elif status_message == OCR_STATUS_MERGING: target_file_info.ocr_engine_status = OCR_STATUS_MERGING
            if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)
        else:
            self.log_manager.warning(f"Status update received for unknown file: {original_file_path}", context="UI_STATUS_UPDATE_WARN")

    def on_file_ocr_processed(self, original_file_main_idx, original_file_path, ocr_result_data_for_original, ocr_error_info_for_original, json_save_status_for_original):
        # (変更なし)
        self.log_manager.debug(
            f"Original File OCR stage processed (MainWin): {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Success={not ocr_error_info_for_original}, JSON Status='{json_save_status_for_original}'",
            context="CALLBACK_OCR_ORIGINAL"
        )
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx} received. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return
            
        target_file_info = self.processed_files_info[original_file_main_idx]
        
        if ocr_error_info_for_original and isinstance(ocr_error_info_for_original, dict):
            target_file_info.status = "OCR失敗"
            target_file_info.ocr_engine_status = OCR_STATUS_FAILED
            err_msg = ocr_error_info_for_original.get('message', '不明なOCRエラー')
            err_code = ocr_error_info_for_original.get('code', '')
            err_detail = ocr_error_info_for_original.get('detail', '') # ★ 詳細も取得
            target_file_info.ocr_result_summary = f"エラー: {err_msg}"
            if err_code: target_file_info.ocr_result_summary += f" (コード: {err_code})"
            # ★ エラーダイアログ表示 (より重要なエラーの場合)
            if err_code not in ["USER_INTERRUPT"]: # ユーザー起因の中断などはダイアログ不要な場合も
                QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})", 
                                    f"ファイル「{target_file_info.name}」のOCR処理中にエラーが発生しました。\n\n"
                                    f"メッセージ: {err_msg}\n"
                                    f"コード: {err_code}\n"
                                    f"詳細: {err_detail if err_detail else 'N/A'}\n\n"
                                    "ログファイルをご確認ください。")
        elif ocr_result_data_for_original:
            # (成功時の処理は変更なし)
            target_file_info.status = "OCR成功"
            target_file_info.ocr_engine_status = OCR_STATUS_COMPLETED
            if isinstance(ocr_result_data_for_original, dict):
                if "detail" in ocr_result_data_for_original: target_file_info.ocr_result_summary = ocr_result_data_for_original["detail"]
                elif "message" in ocr_result_data_for_original: target_file_info.ocr_result_summary = ocr_result_data_for_original["message"]
                else:
                    fulltext = ocr_result_data_for_original.get("fulltext", "") or (ocr_result_data_for_original.get("result", {}) or {}).get("fulltext", "") or (ocr_result_data_for_original.get("result", {}) or {}).get("aGroupingFulltext", "")
                    target_file_info.ocr_result_summary = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
            elif isinstance(ocr_result_data_for_original, list) and len(ocr_result_data_for_original) > 0 :
                try:
                    first_page_result = ocr_result_data_for_original[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "") or first_page_result.get("aGroupingFulltext", "")
                    target_file_info.ocr_result_summary = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                except Exception: target_file_info.ocr_result_summary = "結果解析エラー(集約)"
            else: target_file_info.ocr_result_summary = "OCR結果あり(形式不明)"
        else:
            target_file_info.status = "OCR状態不明"
            target_file_info.ocr_engine_status = OCR_STATUS_FAILED
            target_file_info.ocr_result_summary = "APIレスポンスなし(OCR)"
            QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})",
                                f"ファイル「{target_file_info.name}」のOCR処理でAPIから有効な応答がありませんでした。")


        if isinstance(json_save_status_for_original, str): target_file_info.json_status = json_save_status_for_original
        elif ocr_error_info_for_original : target_file_info.json_status = "対象外(OCR失敗)"
        
        output_format = self.config.get("file_actions", {}).get("output_format", "both")
        if output_format == "json_only":
            if target_file_info.ocr_engine_status == OCR_STATUS_FAILED:
                if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=False)
            elif target_file_info.ocr_engine_status == OCR_STATUS_COMPLETED:
                if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=True)
                target_file_info.status = "完了"
            self.update_status_bar()
        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)


    def on_file_searchable_pdf_processed(self, original_file_main_idx, original_file_path, pdf_final_path, pdf_error_info):
        # (変更なし)
        self.log_manager.debug(f"Original File Searchable PDF processed: {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Path={pdf_final_path}, Error={pdf_error_info}", context="CALLBACK_PDF_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx} received. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return
        target_file_info = self.processed_files_info[original_file_main_idx]
        output_format = self.config.get("file_actions", {}).get("output_format", "both")
        ocr_engine_status_for_file = target_file_info.ocr_engine_status
        pdf_stage_final_success = False
        if output_format == "json_only": target_file_info.searchable_pdf_status = "作成しない(設定)"
        elif pdf_final_path and not pdf_error_info and os.path.exists(pdf_final_path):
            target_file_info.searchable_pdf_status = "PDF作成成功"; pdf_stage_final_success = True
            if ocr_engine_status_for_file == OCR_STATUS_COMPLETED: target_file_info.status = "完了"
        elif pdf_error_info and isinstance(pdf_error_info, dict):
            error_msg = pdf_error_info.get('message', 'PDF作成で不明なエラー'); error_code = pdf_error_info.get('code', '')
            err_detail = pdf_error_info.get('detail', '')
            target_file_info.searchable_pdf_status = f"PDFエラー: {error_msg}"
            if error_code: target_file_info.searchable_pdf_status += f" (コード: {error_code})"
            pdf_stage_final_success = False
            if error_code == "PARTS_COPIED_SUCCESS":
                target_file_info.searchable_pdf_status = error_msg; pdf_stage_final_success = True
                if ocr_engine_status_for_file == OCR_STATUS_COMPLETED: target_file_info.status = "完了"
            elif error_code in ["PARTS_COPIED_PARTIAL", "PARTS_COPY_ERROR", "NO_PARTS_TO_COPY"]:
                if ocr_engine_status_for_file == OCR_STATUS_COMPLETED: target_file_info.status = "部品PDFエラー"
            elif "作成対象外" in error_msg or "作成しない" in error_msg or "部品PDFは結合されません(設定)" in error_msg:
                 pass
            else:
                target_file_info.searchable_pdf_status = "PDF作成失敗"
                if ocr_engine_status_for_file == OCR_STATUS_COMPLETED:
                    target_file_info.status = "PDF作成失敗"
                    summary_prefix = target_file_info.ocr_result_summary
                    if summary_prefix and "部品のOCR完了" not in summary_prefix and "PDFエラー" not in summary_prefix:
                         target_file_info.ocr_result_summary = f"{summary_prefix} (PDFエラー: {error_msg})"
                    elif "部品のOCR完了" not in target_file_info.ocr_result_summary and "PDFエラー" not in target_file_info.ocr_result_summary:
                         target_file_info.ocr_result_summary = f"PDFエラー: {error_msg}"
                # ★ エラーダイアログ表示 (より重要なエラーの場合)
                if error_code not in ["USER_INTERRUPT_PDF", "PDF_NOT_REQUESTED", "PARTS_COPIED_SUCCESS", "NO_PARTS_TO_COPY"]: # ユーザー起因や情報メッセージは除く
                    QMessageBox.warning(self, f"PDF処理エラー ({target_file_info.name})",
                                        f"ファイル「{target_file_info.name}」のPDF処理中にエラーが発生しました。\n\n"
                                        f"メッセージ: {error_msg}\n"
                                        f"コード: {error_code}\n"
                                        f"詳細: {err_detail if err_detail else 'N/A'}\n\n"
                                        "ログファイルをご確認ください。")

        elif ocr_engine_status_for_file == OCR_STATUS_FAILED : target_file_info.searchable_pdf_status = "対象外(OCR失敗)"
        elif output_format in ["pdf_only", "both"]:
            target_file_info.searchable_pdf_status = "PDF状態不明"
            if ocr_engine_status_for_file == OCR_STATUS_COMPLETED: target_file_info.status = "PDF状態不明"
        else: target_file_info.searchable_pdf_status = "-"
        if output_format != "json_only":
            is_overall_success_for_summary = (ocr_engine_status_for_file == OCR_STATUS_COMPLETED and pdf_stage_final_success)
            if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=is_overall_success_for_summary)
            self.update_status_bar()
        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    # ... (on_all_files_processed から clear_log_display までは変更なし)
    def on_all_files_processed(self, was_interrupted_by_orchestrator: bool):
        self._handle_ocr_process_finished_from_orchestrator(was_interrupted_by_orchestrator)

    def handle_ocr_interruption_ui_update(self):
        self.log_manager.info("MainWindow: Handling UI update for OCR interruption.", context="UI_UPDATE_INTERRUPT")
        for file_info in self.processed_files_info:
            current_engine_status = file_info.ocr_engine_status
            if current_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING]:
                file_info.ocr_engine_status = OCR_STATUS_NOT_PROCESSED
                file_info.status = "待機中(中断)"
        self.perform_batch_list_view_update()
        self.update_ocr_controls()

    def update_ocr_controls(self):
        running = self.is_ocr_running
        has_checked_and_processable_for_start = any(
            f_info.is_checked and f_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT
            for f_info in self.processed_files_info
        )
        can_start_action = not running and has_checked_and_processable_for_start
        if hasattr(self, 'start_ocr_action') and self.start_ocr_action.isEnabled() != can_start_action:
            self.start_ocr_action.setEnabled(can_start_action)
        can_resume_action = False
        if not running and self.processed_files_info:
            has_checked_for_resume = any(
                f.is_checked and f.ocr_engine_status in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and \
                f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT
                for f in self.processed_files_info
            )
            eligible_checked_files_for_resume_check = [
                f for f in self.processed_files_info 
                if f.is_checked and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT
            ]
            all_eligible_checked_are_pristine_not_processed = False
            if eligible_checked_files_for_resume_check:
                all_eligible_checked_are_pristine_not_processed = all(
                    f.ocr_engine_status == OCR_STATUS_NOT_PROCESSED for f in eligible_checked_files_for_resume_check
                )
            if has_checked_for_resume and not all_eligible_checked_are_pristine_not_processed:
                can_resume_action = True
        if hasattr(self, 'resume_ocr_action') and self.resume_ocr_action.isEnabled() != can_resume_action:
            self.resume_ocr_action.setEnabled(can_resume_action)
        if hasattr(self, 'stop_ocr_action') and self.stop_ocr_action.isEnabled() != running:
            self.stop_ocr_action.setEnabled(running)
        can_rescan_action = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        if hasattr(self, 'rescan_action') and self.rescan_action.isEnabled() != can_rescan_action:
            self.rescan_action.setEnabled(can_rescan_action)
        enable_actions_if_not_running = not running
        if hasattr(self, 'input_folder_action') and self.input_folder_action.isEnabled() != enable_actions_if_not_running:
            self.input_folder_action.setEnabled(enable_actions_if_not_running)
        if hasattr(self, 'option_action') and self.option_action.isEnabled() != enable_actions_if_not_running:
            self.option_action.setEnabled(enable_actions_if_not_running)
        if hasattr(self, 'toggle_view_action') and not self.toggle_view_action.isEnabled():
            self.toggle_view_action.setEnabled(True)

    def perform_batch_list_view_update(self):
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE");
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        self.update_all_status_displays()
    
    def confirm_rescan_ui(self):
        self.log_manager.debug("Confirming UI rescan.", context="UI_ACTION")
        if self.is_ocr_running: QMessageBox.warning(self, "再スキャン不可", "OCR処理の実行中は再スキャンできません。"); return
        if not self.processed_files_info and not self.input_folder_path: QMessageBox.information(self, "再スキャン", "クリアまたは再スキャンする対象がありません。"); return
        if self.update_timer.isActive(): self.update_timer.stop()
        message = "入力フォルダが再スキャンされます。\n\n現在のリストと進捗状況はクリアされます。\n\nよろしいですか？";
        reply = QMessageBox.question(self, "再スキャン確認", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_manager.info("User confirmed UI rescan.", context="UI_ACTION")
            self.perform_rescan()
        else:
            self.log_manager.info("User cancelled UI rescan.", context="UI_ACTION")

    def perform_rescan(self):
        self.log_manager.info("Performing UI clear and input folder rescan.", context="UI_ACTION_RESCAN")
        if hasattr(self.summary_view, 'reset_summary'):
            self.summary_view.reset_summary()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"Rescanning input folder: {self.input_folder_path}", context="UI_ACTION_RESCAN")
            self.perform_initial_scan()
        else:
            self.log_manager.info("Rescan: Input folder not set or invalid. File list cleared.", context="UI_ACTION_RESCAN")
            self.processed_files_info = []
            if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info)
            self.update_all_status_displays()
        self._update_folder_display()
        if self.is_ocr_running: self.is_ocr_running = False
        self.update_ocr_controls()

    def closeEvent(self, event):
        self.log_manager.debug("Application closeEvent triggered.", context="SYSTEM_LIFECYCLE");
        if self.update_timer.isActive(): self.update_timer.stop()
        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？\n(進行中の処理は中断されます)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: event.ignore(); return
            else:
                if self.ocr_orchestrator:
                     self.log_manager.info("Close event: OCR running, attempting to stop worker via orchestrator before exit.", context="SYSTEM_LIFECYCLE")
                     self.ocr_orchestrator.confirm_and_stop_ocr(self)
        current_config_to_save = self.config.copy(); normal_geom = self.normalGeometry(); current_config_to_save["window_state"] = "maximized" if self.isMaximized() else "normal"; current_config_to_save["window_size"] = {"width": normal_geom.width(), "height": normal_geom.height()}
        if not self.isMaximized(): current_config_to_save["window_position"] = {"x": normal_geom.x(), "y": normal_geom.y()}
        elif "window_position" in current_config_to_save: del current_config_to_save["window_position"]
        current_config_to_save["last_target_dir"] = self.input_folder_path; current_config_to_save["current_view"] = self.current_view if hasattr(self, 'current_view') else 0
        current_config_to_save["log_visible"] = self.log_container.isVisible() if hasattr(self, 'log_container') else True
        if hasattr(self.splitter, 'sizes'): current_config_to_save["splitter_sizes"] = self.splitter.sizes()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'):
            current_config_to_save["column_widths"] = self.list_view.get_column_widths(); current_config_to_save["sort_order"] = self.list_view.get_sort_order()
        ConfigManager.save(current_config_to_save); self.log_manager.info("Settings saved. Exiting application.", context="SYSTEM_LIFECYCLE"); super().closeEvent(event)

    def clear_log_display(self):
        if hasattr(self, 'log_widget') and self.log_widget: self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました（ファイル記録は継続）。", context="UI_ACTION_CLEAR_LOG", emit_to_ui=False)