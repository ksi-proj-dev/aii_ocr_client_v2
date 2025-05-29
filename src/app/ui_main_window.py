# ui_main_window.py (完全版)

import sys
import os
import platform
import subprocess

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter,
    QFormLayout, QPushButton, QHBoxLayout, QFrame
)
from PyQt6.QtGui import QAction, QFontMetrics # QFontMetrics をインポート
from PyQt6.QtCore import Qt, QTimer

# アプリケーション内モジュールのインポート
from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView 
from config_manager import ConfigManager
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING,
    LISTVIEW_UPDATE_INTERVAL_MS
)
from ui_dialogs import OcrConfirmationDialog
from ocr_worker import OcrWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.log_manager = LogManager()
        self.log_manager.debug("MainWindow initializing...", context="MAINWIN_LIFECYCLE")
        self.setWindowTitle("AI inside Cube Client Ver.0.0.12")
        self.config = ConfigManager.load()
        self.is_ocr_running = False
        self.processed_files_info = []
        self.log_widget = QTextEdit()
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget)
        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.ocr_worker = None
        self.update_timer = QTimer(self); self.update_timer.setSingleShot(True); self.update_timer.timeout.connect(self.perform_batch_list_view_update)
        
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700}); state_cfg = self.config.get("window_state", "normal"); pos_cfg = self.config.get("window_position"); self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try: screen_geometry = QApplication.primaryScreen().geometry(); self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e: self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e); self.move(100, 100)
        else: self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized": self.showMaximized()

        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget); self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(2, 2, 2, 2) 
        self.main_layout.setSpacing(0) 

        self.splitter = QSplitter(Qt.Orientation.Vertical); self.stack = QStackedWidget(); self.summary_view = SummaryView(); 
        self.summary_view.log_manager = self.log_manager 

        self.list_view = ListView(self.processed_files_info)
        self.list_view.item_check_state_changed.connect(self.on_list_item_check_state_changed) 
        self.stack.addWidget(self.summary_view); self.stack.addWidget(self.list_view); self.splitter.addWidget(self.stack)
        self.log_container = QWidget(); log_layout_inner = QVBoxLayout(self.log_container); log_layout_inner.setContentsMargins(8,8,8,8); log_layout_inner.setSpacing(0)
        self.log_header = QLabel("ログ："); self.log_header.setStyleSheet("margin-left: 6px; padding-bottom: 0px; font-weight: bold;"); log_layout_inner.addWidget(self.log_header)
        self.log_widget.setReadOnly(True)
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
        self.splitter.addWidget(self.log_container); self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        splitter_sizes = self.config.get("splitter_sizes");
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0 : self.splitter.setSizes(splitter_sizes)
        else: default_height = self.height(); initial_splitter_sizes = [int(default_height * 0.65), int(default_height * 0.35)]; self.splitter.setSizes(initial_splitter_sizes)
        self.main_layout.addWidget(self.splitter)
        
        # ステータス行のセットアップ
        self.status_bar_frame = QFrame() 
        self.status_bar_frame.setFrameShape(QFrame.Shape.NoFrame) # フレーム形状をなしに
        self.status_bar_frame.setStyleSheet("""
            QFrame#StatusBarFrame { 
                background-color: #ECECEC; /* やや明るいグレー */
                border-top: 1px solid #B0B0B0; /* 上境界線のみで区別 */
                min-height: 26px; 
                max-height: 26px; /* 高さを固定 */
            }
            QLabel#StatusBarLabel { 
                padding: 3px 0px; 
                font-size: 8pt; /* フォントサイズを少し小さめに */
                border: none; /* ラベル自体の枠線はなし */
            }
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
        
        self.input_folder_path = self.config.get("last_target_dir", "")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT")
        elif self.input_folder_path: 
            self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT")
            self.input_folder_path = ""
        else: 
            self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT")

        self.setup_toolbar_and_folder_labels()

        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.perform_initial_scan() 
        else:
            self.list_view.update_files(self.processed_files_info) 
            if hasattr(self.summary_view, 'reset_summary'):
                self.summary_view.reset_summary()
            self.update_all_status_displays() 

        self.current_view = self.config.get("current_view", 0); self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True); self.log_container.setVisible(log_visible)
        self.update_ocr_controls(); 
        self.log_manager.info("Application initialized successfully.", context="SYSTEM_LIFECYCLE")

    def update_status_bar(self):
        total_list_items = len(self.processed_files_info)
        selected_for_processing_count = 0
        
        ocr_success_count = self.summary_view.ocr_completed_count
        ocr_error_count = self.summary_view.ocr_error_count

        for item_info in self.processed_files_info:
            if item_info.get("is_checked", False) and \
               item_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                selected_for_processing_count += 1
        
        self.status_total_list_label.setText(f"リスト総数: {total_list_items}")
        self.status_selected_files_label.setText(f"選択中: {selected_for_processing_count}")
        self.status_success_files_label.setText(f"成功: {ocr_success_count}")
        self.status_error_files_label.setText(f"エラー: {ocr_error_count}")

    def update_all_status_displays(self):
        size_skipped_count = 0
        checked_and_processable_for_summary = 0 
        
        for item_info in self.processed_files_info:
            if item_info.get("ocr_engine_status") == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                size_skipped_count += 1
            elif item_info.get("is_checked", False): 
                checked_and_processable_for_summary += 1
        
        self.summary_view.update_summary_counts(
            total_scanned=len(self.processed_files_info),
            total_ocr_target=checked_and_processable_for_summary,
            skipped_size=size_skipped_count
        )
        self.update_status_bar()

    def on_list_item_check_state_changed(self, row_index, is_checked):
        if 0 <= row_index < len(self.processed_files_info):
            self.processed_files_info[row_index]["is_checked"] = is_checked
            self.log_manager.debug(f"File '{os.path.basename(self.processed_files_info[row_index]['path'])}' check state in data model changed to: {is_checked}", context="UI_EVENT")
            
            self.update_all_status_displays() 
            self.update_ocr_controls()

    def _collect_files_from_input_folder(self):
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            self.log_manager.warning("File collection skipped: Input folder invalid.", context="FILE_SCAN")
            return [], None, [] 

        current_config = ConfigManager.load()
        file_actions_config = current_config.get("file_actions", {})
        excluded_folder_names = [name for name in [
            file_actions_config.get("success_folder_name"),
            file_actions_config.get("failure_folder_name"),
            file_actions_config.get("results_folder_name")
        ] if name and name.strip()]
        
        options_cfg = current_config.get("options", {}).get(current_config.get("api_type"), {})
        max_files = options_cfg.get("max_files_to_process", 100)
        recursion_depth_limit = options_cfg.get("recursion_depth", 5)

        self.log_manager.info(f"File collection started: In='{self.input_folder_path}', Max={max_files}, DepthLimit={recursion_depth_limit}, Exclude={excluded_folder_names}", context="FILE_SCAN")
        
        collected_files = []
        supported_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        
        max_files_reached_info = None
        depth_limited_folders = set()

        for root, dirs, files in os.walk(self.input_folder_path, topdown=True, followlinks=False):
            norm_root = os.path.normpath(root)
            norm_input_root = os.path.normpath(self.input_folder_path)
            relative_path_from_input = os.path.relpath(norm_root, norm_input_root)
            current_depth = 0 if relative_path_from_input == "." else len(relative_path_from_input.split(os.sep))

            if current_depth >= recursion_depth_limit:
                for d_name in dirs: 
                    depth_limited_folders.add(os.path.join(norm_root, d_name))
                self.log_manager.debug(f"Recursion depth limit ({recursion_depth_limit}) reached at '{norm_root}'. Skipping subdirectories: {dirs}", context="FILE_SCAN_DEPTH")
                dirs[:] = [] 
                continue
            
            dirs_to_remove_from_walk = [d for d in dirs if d in excluded_folder_names]
            for d_to_remove in dirs_to_remove_from_walk:
                if d_to_remove in dirs: dirs.remove(d_to_remove)
            
            for filename in sorted(files):
                if len(collected_files) >= max_files:
                    if max_files_reached_info is None: 
                         max_files_reached_info = {
                             "limit": max_files,
                             "last_scanned_folder": norm_root 
                         }
                    break 
                file_path = os.path.join(root, filename)
                if os.path.islink(file_path): continue
                if os.path.splitext(filename)[1].lower() in supported_extensions:
                    collected_files.append(file_path)
            
            if max_files_reached_info is not None: 
                break

        unique_sorted_files = sorted(list(set(collected_files)))
        self.log_manager.info(f"File collection finished: Found {len(unique_sorted_files)} files.", context="FILE_SCAN", count=len(unique_sorted_files))
        return unique_sorted_files, max_files_reached_info, list(depth_limited_folders)

    def perform_initial_scan(self):
        self.log_manager.info(f"スキャン開始: {self.input_folder_path}", context="FILE_SCAN")
        if self.update_timer.isActive(): self.update_timer.stop()
        self.processed_files_info = []
        
        collected_files_paths, max_files_info, depth_limited_folders = self._collect_files_from_input_folder()
        
        current_config = ConfigManager.load()
        ocr_options = current_config.get("options", {}).get(current_config.get("api_type"), {})
        upload_max_size_mb = ocr_options.get("upload_max_size_mb", 50)
        upload_max_bytes = upload_max_size_mb * 1024 * 1024
        output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both")
        initial_json_status_default = "作成しない(設定)"
        if output_format_cfg == "json_only" or output_format_cfg == "both": 
            initial_json_status_default = "-"
        initial_pdf_status_default = "作成しない(設定)"
        if output_format_cfg == "pdf_only" or output_format_cfg == "both": 
            initial_pdf_status_default = "-"
        
        if collected_files_paths:
            for i, f_path in enumerate(collected_files_paths):
                try:
                    f_size = os.path.getsize(f_path)
                    is_skipped_by_size = f_size > upload_max_bytes
                    
                    file_info_item = {
                        "no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size,
                        "status": "スキップ(サイズ上限)" if is_skipped_by_size else "待機中",
                        "ocr_engine_status": OCR_STATUS_SKIPPED_SIZE_LIMIT if is_skipped_by_size else OCR_STATUS_NOT_PROCESSED,
                        "ocr_result_summary": f"ファイルサイズが上限 ({upload_max_size_mb}MB) を超過" if is_skipped_by_size else "", 
                        "json_status": "スキップ" if is_skipped_by_size else initial_json_status_default, 
                        "searchable_pdf_status": "スキップ" if is_skipped_by_size else initial_pdf_status_default,
                        "is_checked": not is_skipped_by_size 
                    }
                    if is_skipped_by_size:
                        self.log_manager.warning(f"ファイル '{file_info_item['name']}' ({f_size/(1024*1024):.2f}MB) はアップロード上限 ({upload_max_size_mb}MB) 超過のためスキップ。", context="FILE_SCAN")
                    self.processed_files_info.append(file_info_item)
                except OSError as e:
                    self.log_manager.error(f"ファイル '{f_path}' の情報取得に失敗しました。スキップします。エラー: {e}", context="FILE_SCAN_ERROR")
            
            self.list_view.update_files(self.processed_files_info)
            processable_by_size_count = sum(1 for item in self.processed_files_info if item["ocr_engine_status"] != OCR_STATUS_SKIPPED_SIZE_LIMIT)
            self.log_manager.info(f"スキャン完了: {len(self.processed_files_info)}件のファイル情報を読み込み ({processable_by_size_count}件サイズ上限内)。", context="FILE_SCAN", total_found=len(self.processed_files_info), processable_by_size=processable_by_size_count)
        else: 
            self.list_view.update_files(self.processed_files_info);
            self.log_manager.info("スキャン: 対象ファイルは見つかりませんでした。", context="FILE_SCAN")
        
        warning_messages = []
        if max_files_info:
            msg = f"最大処理ファイル数 ({max_files_info['limit']}件) に達したため、フォルダ「{max_files_info['last_scanned_folder']}」以降の一部のファイルは読み込まれていません。"
            warning_messages.append(msg)
            self.log_manager.warning(msg, context="FILE_SCAN_LIMIT")
        
        if depth_limited_folders:
            folders_to_show = depth_limited_folders[:3] 
            folders_str = ", ".join([os.path.basename(f) for f in folders_to_show])
            if len(depth_limited_folders) > 3:
                folders_str += f" など、計{len(depth_limited_folders)}フォルダ"
            
            msg = f"再帰検索の深さ制限により、サブフォルダ「{folders_str}」以降は検索されていません。"
            warning_messages.append(msg)
            self.log_manager.warning(msg, context="FILE_SCAN_LIMIT", limited_folders_count=len(depth_limited_folders), example_folders=folders_to_show)

        if warning_messages:
            QMessageBox.warning(self, "スキャン結果の注意", "\n\n".join(warning_messages))
        
        if hasattr(self.summary_view, 'reset_summary'): 
            self.summary_view.reset_summary() 
        
        self.update_all_status_displays() 
        self.update_ocr_controls()

    def append_log_message_to_widget(self, level, message):
        if self.log_widget:
            if level == LogLevel.ERROR: self.log_widget.append(f'<font color="red">{message}</font>')
            elif level == LogLevel.WARNING: self.log_widget.append(f'<font color="orange">{message}</font>')
            elif level == LogLevel.DEBUG: self.log_widget.append(f'<font color="gray">{message}</font>')
            else: self.log_widget.append(message)
            self.log_widget.ensureCursorVisible()

    def setup_toolbar_and_folder_labels(self):
        toolbar = QToolBar("Main Toolbar"); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.input_folder_action = QAction("📂入力", self); self.input_folder_action.triggered.connect(self.select_input_folder); toolbar.addAction(self.input_folder_action)
        self.toggle_view_action = QAction("📑ビュー", self); self.toggle_view_action.triggered.connect(self.toggle_view); toolbar.addAction(self.toggle_view_action)
        self.option_action = QAction("⚙️設定", self); self.option_action.triggered.connect(self.show_option_dialog); toolbar.addAction(self.option_action)
        toolbar.addSeparator()
        self.start_ocr_action = QAction("▶️開始", self); self.start_ocr_action.triggered.connect(self.confirm_start_ocr); toolbar.addAction(self.start_ocr_action)
        self.resume_ocr_action = QAction("↪️再開", self)
        self.resume_ocr_action.setToolTip("未処理または失敗したファイルのOCR処理を再開します")
        self.resume_ocr_action.triggered.connect(self.confirm_resume_ocr)
        toolbar.addAction(self.resume_ocr_action)
        self.stop_ocr_action = QAction("⏹️中止", self); self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr); toolbar.addAction(self.stop_ocr_action)
        self.rescan_action = QAction("🔄再スキャン", self); self.rescan_action.triggered.connect(self.confirm_rescan_ui); self.rescan_action.setEnabled(False); toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        self.log_toggle_action = QAction("📄ログ表示", self); self.log_toggle_action.triggered.connect(self.toggle_log_display); toolbar.addAction(self.log_toggle_action)
        self.clear_log_action = QAction("🗑️ログクリア", self); self.clear_log_action.triggered.connect(self.clear_log_display); toolbar.addAction(self.clear_log_action)
        folder_label_toolbar = QToolBar("Folder Paths Toolbar"); folder_label_toolbar.setMovable(False)
        folder_label_widget = QWidget(); folder_label_layout = QFormLayout(folder_label_widget)
        folder_label_layout.setContentsMargins(5, 5, 5, 5); folder_label_layout.setSpacing(3)
        self.input_folder_button = QPushButton(f"{self.input_folder_path or '未選択'}")
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

    def select_input_folder(self):
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.log_manager.info(f"Input folder selected by user: {folder}", context="UI_EVENT")
            if folder != self.input_folder_path or not self.processed_files_info:
                self.input_folder_path = folder
                self.input_folder_button.setText(folder) 
                self.log_manager.info(f"Performing rescan for newly selected folder: {folder}", context="UI_EVENT")
                self.perform_rescan()
            else:
                self.log_manager.info("Selected folder is the same as current and list is not empty. No rescan forced.", context="UI_EVENT")
        else:
            self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")

    def open_input_folder_in_explorer(self):
        self.log_manager.debug(f"Attempting to open folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            try:
                if platform.system() == "Windows":
                    norm_path = os.path.normpath(self.input_folder_path)
                    os.startfile(norm_path)
                elif platform.system() == "Darwin":
                    subprocess.run(['open', self.input_folder_path], check=True)
                else:
                    subprocess.run(['xdg-open', self.input_folder_path], check=True)
                self.log_manager.info(f"Successfully opened folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
            except Exception as e:
                self.log_manager.error(f"Failed to open folder '{self.input_folder_path}'. Error: {e}", context="UI_ACTION_OPEN_FOLDER_ERROR", exception_info=e)
                QMessageBox.warning(self, "フォルダを開けません", f"フォルダ '{self.input_folder_path}' を開けませんでした。\nエラー: {e}")
        else:
            self.log_manager.warning(f"Cannot open folder: Path is invalid or not set. Path: '{self.input_folder_path}'", context="UI_ACTION_OPEN_FOLDER_INVALID")
            QMessageBox.information(self, "フォルダ情報なし", "入力フォルダが選択されていないか、無効なパスです。")

    def toggle_view(self):
        self.current_view = 1 - self.current_view; self.stack.setCurrentIndex(self.current_view); self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")
    
    def toggle_log_display(self):
        visible = self.log_container.isVisible(); self.log_container.setVisible(not visible); self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION")

    def show_option_dialog(self):
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION")
        
        old_config = self.config.copy()
        old_api_type_options = old_config.get("options", {}).get(old_config.get("api_type"), {})
        old_max_files = old_api_type_options.get("max_files_to_process")
        old_recursion_depth = old_api_type_options.get("recursion_depth")

        dialog = OptionDialog(self)
        if dialog.exec():
            self.config = ConfigManager.load() 
            self.log_manager.info("Options saved and reloaded.", context="CONFIG_EVENT")
            self.api_client = CubeApiClient(self.config, self.log_manager)
            
            new_api_type_options = self.config.get("options", {}).get(self.config.get("api_type"), {})
            new_max_files = new_api_type_options.get("max_files_to_process")
            new_recursion_depth = new_api_type_options.get("recursion_depth")
            
            rescan_needed_due_to_collection_settings = (old_max_files != new_max_files or 
                                                        old_recursion_depth != new_recursion_depth)

            if rescan_needed_due_to_collection_settings:
                if self.input_folder_path and os.path.isdir(self.input_folder_path):
                    QMessageBox.information(self, "設定変更の適用", 
                                            "ファイル検索範囲に関する設定（最大ファイル数または再帰深度）が変更されたため、ファイルリストを再スキャンします。")
                    self.perform_rescan() 
                else:
                    self.processed_files_info = [] 
                    self.list_view.update_files(self.processed_files_info)
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
                
                for item_info in self.processed_files_info:
                    current_file_size = item_info.get("size", 0)
                    prev_ocr_engine_status = item_info.get("ocr_engine_status")
                    prev_is_checked = item_info.get("is_checked", True) 
                    original_status_text = item_info["status"] 
                    original_json_status = item_info["json_status"]
                    original_pdf_status = item_info["searchable_pdf_status"]

                    is_now_skipped_by_size = current_file_size > new_upload_max_bytes

                    if is_now_skipped_by_size:
                        if item_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                            item_info["status"] = "スキップ(サイズ上限)"
                            item_info["ocr_engine_status"] = OCR_STATUS_SKIPPED_SIZE_LIMIT
                            item_info["ocr_result_summary"] = f"ファイルサイズが上限 ({new_upload_max_size_mb}MB) を超過"
                            item_info["json_status"] = "スキップ"
                            item_info["searchable_pdf_status"] = "スキップ"
                            item_info["is_checked"] = False 
                    else: 
                        if item_info.get("ocr_engine_status") == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                            item_info["status"] = "待機中"
                            item_info["ocr_engine_status"] = OCR_STATUS_NOT_PROCESSED
                            item_info["ocr_result_summary"] = ""
                            item_info["is_checked"] = True 
                        
                        if item_info.get("ocr_engine_status") == OCR_STATUS_NOT_PROCESSED:
                            item_info["json_status"] = default_json_status
                            item_info["searchable_pdf_status"] = default_pdf_status
                    
                    if (item_info.get("ocr_engine_status") != prev_ocr_engine_status or
                        item_info.get("status") != original_status_text or
                        item_info.get("json_status") != original_json_status or
                        item_info.get("searchable_pdf_status") != original_pdf_status or
                        item_info.get("is_checked") != prev_is_checked):
                        items_status_updated = True
                        if prev_ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT and item_info.get("ocr_engine_status") == OCR_STATUS_NOT_PROCESSED:
                             self.log_manager.debug(f"File '{item_info['name']}' NO LONGER SKIPPED by size. Status reset.", context="CONFIG_EVENT")
                        elif prev_ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and item_info.get("ocr_engine_status") == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                             self.log_manager.debug(f"File '{item_info['name']}' NOW SKIPPED due to new size limit.", context="CONFIG_EVENT")

                if items_status_updated:
                    self.list_view.update_files(self.processed_files_info)
                
                self.update_all_status_displays()
            self.update_ocr_controls()
        else:
            self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

    def _create_confirmation_summary(self, files_to_process_count):
        current_config = ConfigManager.load()
        file_actions_cfg = current_config.get("file_actions", {})
        api_type_key = current_config.get("api_type", "cube_fullocr")
        ocr_opts = current_config.get("options", {}).get(api_type_key, {})

        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]
        summary_lines.append("<strong>【基本設定】</strong>")
        summary_lines.append(f"入力フォルダ: {self.input_folder_path or '未選択'}")
        summary_lines.append("<br>")

        summary_lines.append("<strong>【ファイル処理後の出力と移動】</strong>")
        output_format_value = file_actions_cfg.get("output_format", "both")
        output_format_display_map = {
            "json_only": "JSONのみ",
            "pdf_only": "サーチャブルPDFのみ",
            "both": "JSON と サーチャブルPDF (両方)"
        }
        output_format_display = output_format_display_map.get(output_format_value, "未設定/不明")
        summary_lines.append(f"出力形式: <strong>{output_format_display}</strong>")

        results_folder_name = file_actions_cfg.get("results_folder_name", "(未設定)")
        summary_lines.append(f"OCR結果サブフォルダ名: <strong>{results_folder_name}</strong>")
        summary_lines.append(f"  <small>(備考: 元ファイルの各場所に '{results_folder_name}' サブフォルダを作成し結果を保存)</small>")

        move_on_success = file_actions_cfg.get("move_on_success_enabled", False)
        success_folder_name_cfg = file_actions_cfg.get("success_folder_name", "(未設定)")
        summary_lines.append(f"成功ファイル移動: {'<strong>する</strong>' if move_on_success else 'しない'}")
        if move_on_success:
            summary_lines.append(f"  移動先サブフォルダ名: <strong>{success_folder_name_cfg}</strong>")
            summary_lines.append(f"    <small>(備考: 元ファイルの各場所に '{success_folder_name_cfg}' サブフォルダを作成し移動)</small>")

        move_on_failure = file_actions_cfg.get("move_on_failure_enabled", False)
        failure_folder_name_cfg = file_actions_cfg.get("failure_folder_name", "(未設定)")
        summary_lines.append(f"失敗ファイル移動: {'<strong>する</strong>' if move_on_failure else 'しない'}")
        if move_on_failure:
            summary_lines.append(f"  移動先サブフォルダ名: <strong>{failure_folder_name_cfg}</strong>")
            summary_lines.append(f"    <small>(備考: 元ファイルの各場所に '{failure_folder_name_cfg}' サブフォルダを作成し移動)</small>")
        
        if move_on_success or move_on_failure:
            collision_map = {"overwrite": "上書き", "rename": "リネームする (例: file.pdf --> file (1).pdf)", "skip": "スキップ"}
            collision_act_key = file_actions_cfg.get("collision_action", "rename")
            collision_act_display = collision_map.get(collision_act_key, "リネームする (例: file.pdf --> file (1).pdf)")
            summary_lines.append(f"ファイル名衝突時 (移動先): {collision_act_display}")
        summary_lines.append("<br>")

        summary_lines.append("<strong>【ファイル検索設定】</strong>")
        summary_lines.append(f"最大処理ファイル数: {ocr_opts.get('max_files_to_process', 100)}")
        summary_lines.append(f"再帰検索の深さ (入力フォルダ自身を0): {ocr_opts.get('recursion_depth', 5)}")
        summary_lines.append(f"アップロード上限サイズ: {ocr_opts.get('upload_max_size_mb', 50)} MB")
        
        if ocr_opts.get('split_large_files_enabled', False):
            summary_lines.append(f"ファイル分割: <strong>有効</strong> (分割サイズ目安: {ocr_opts.get('split_chunk_size_mb',10)} MB)")
            if ocr_opts.get('merge_split_pdf_parts', True): 
                 summary_lines.append(f"  <small>分割PDF部品の結合: <strong>有効</strong></small>")
            else:
                 summary_lines.append(f"  <small>分割PDF部品の結合: <strong>無効</strong> (部品ごとに出力)</small>")
        else:
            summary_lines.append("ファイル分割: 無効")
        
        summary_lines.append(f"処理対象ファイル数 (選択結果): {files_to_process_count} 件")
        summary_lines.append("<br>")

        summary_lines.append("<strong>【主要OCRオプション】</strong>")
        summary_lines.append(f"回転補正: {'ON' if ocr_opts.get('adjust_rotation', 0) == 1 else 'OFF'}")
        summary_lines.append(f"OCRモデル: {ocr_opts.get('ocr_model', 'katsuji')}")
        summary_lines.append("<br>上記内容で処理を開始します。")
        
        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])

    def confirm_start_ocr(self):
        self.log_manager.debug("Confirming OCR start...", context="OCR_FLOW")
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            self.log_manager.warning("OCR start aborted: Input folder invalid.", context="OCR_FLOW")
            QMessageBox.warning(self, "入力フォルダエラー", "入力フォルダが選択されていないか、無効なパスです。")
            return
        if self.is_ocr_running:
            self.log_manager.info("OCR start aborted: Already running.", context="OCR_FLOW")
            return
        
        files_eligible_for_ocr_info = [
            item for item in self.processed_files_info 
            if item.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT and \
               item.get("is_checked", False) 
        ]

        if not files_eligible_for_ocr_info:
            self.log_manager.info("OCR start aborted: No eligible and checked files to process.", context="OCR_FLOW")
            QMessageBox.information(self,"対象ファイルなし", "処理対象として選択（チェック）されているファイル（サイズ上限内）が見つかりませんでした。")
            self.update_ocr_controls()
            return

        ocr_already_attempted_in_eligible_list = any(
            item.get("ocr_engine_status") not in [OCR_STATUS_NOT_PROCESSED, None] 
            for item in files_eligible_for_ocr_info 
        )
        
        if ocr_already_attempted_in_eligible_list:
            message = "選択されたファイルの中に、既に処理が試みられた（未処理ではない）ファイルが含まれています。\n" \
                        "これらのファイルのOCR処理状態がリセットされ、最初から処理されます。\n\n" \
                        "よろしいですか？"
            reply = QMessageBox.question(self, "OCR再実行の確認", message,
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                self.log_manager.info("OCR re-execution cancelled by user.", context="OCR_FLOW")
                return
        
        confirmation_summary = self._create_confirmation_summary(len(files_eligible_for_ocr_info)) 
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, self)
        if not confirm_dialog.exec():
            self.log_manager.info("OCR start cancelled by user (final confirmation dialog).", context="OCR_FLOW")
            return

        self.log_manager.info(f"User confirmed. Starting OCR process for {len(files_eligible_for_ocr_info)} eligible and checked files...", context="OCR_FLOW")
        current_config_for_run = ConfigManager.load()
        self.is_ocr_running = True
        
        files_to_send_to_worker_tuples = []
        output_format_cfg = current_config_for_run.get("file_actions", {}).get("output_format", "both")
        initial_json_status_ui = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
        initial_pdf_status_ui = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"

        for original_idx, item_info in enumerate(self.processed_files_info):
            if item_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT and \
               item_info.get("is_checked", False): 
                item_info["status"] = OCR_STATUS_PROCESSING 
                item_info["ocr_engine_status"] = OCR_STATUS_PROCESSING 
                item_info["ocr_result_summary"] = "" 
                item_info["json_status"] = initial_json_status_ui 
                item_info["searchable_pdf_status"] = initial_pdf_status_ui 
                files_to_send_to_worker_tuples.append((item_info["path"], original_idx))
        
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'):
            self.summary_view.start_processing(len(files_to_send_to_worker_tuples)) 
            self.update_status_bar() 
        
        self.log_manager.info(f"Instantiating OcrWorker for {len(files_to_send_to_worker_tuples)} files.", context="OCR_FLOW")
        self.ocr_worker = OcrWorker(
            api_client=self.api_client,
            files_to_process_tuples=files_to_send_to_worker_tuples,
            input_root_folder=self.input_folder_path,
            log_manager=self.log_manager,
            config=current_config_for_run
        )
        self.ocr_worker.original_file_status_update.connect(self.on_original_file_status_update_from_worker)
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()
        self.update_ocr_controls()

    def confirm_resume_ocr(self):
        self.log_manager.debug("Confirming OCR resume...", context="OCR_FLOW")
        if self.is_ocr_running:
            self.log_manager.info("OCR resume aborted: OCR is already running.", context="OCR_FLOW")
            return

        files_to_resume_tuples = []
        for original_idx, item_info in enumerate(self.processed_files_info):
            if item_info.get("is_checked", False) and \
               item_info.get("ocr_engine_status") in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and \
               item_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                files_to_resume_tuples.append((item_info["path"], original_idx))

        if not files_to_resume_tuples:
            self.log_manager.info("OCR resume: No checked files found with 'Not Processed' or 'Failed' OCR status.", context="OCR_FLOW")
            QMessageBox.information(self, "再開対象なし", "OCR未処理または失敗状態で、かつチェックされているファイル（サイズ上限内）が見つかりませんでした。")
            self.update_ocr_controls()
            return
        
        message = f"{len(files_to_resume_tuples)} 件の選択されたファイルに対してOCR処理を再開します。\n\n" \
                    "よろしいですか？"
        reply = QMessageBox.question(self, "OCR再開の確認", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            self.log_manager.info("OCR resume cancelled by user.", context="OCR_FLOW")
            return
            
        self.log_manager.info(f"User confirmed. Resuming OCR process for {len(files_to_resume_tuples)} files.", context="OCR_FLOW")
        current_config_for_run = ConfigManager.load()
        self.is_ocr_running = True
        output_format_cfg = current_config_for_run.get("file_actions", {}).get("output_format", "both")
        initial_json_status_ui = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
        initial_pdf_status_ui = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"

        for path, original_idx in files_to_resume_tuples:
            item_info = self.processed_files_info[original_idx]
            item_info["ocr_engine_status"] = OCR_STATUS_PROCESSING
            item_info["status"] = f"{OCR_STATUS_PROCESSING}(再開)" 
            item_info["ocr_result_summary"] = ""
            item_info["json_status"] = initial_json_status_ui
            item_info["searchable_pdf_status"] = initial_pdf_status_ui
        
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'):
            self.summary_view.start_processing(len(files_to_resume_tuples))
            self.update_status_bar()

        self.log_manager.info(f"Instantiating OcrWorker for {len(files_to_resume_tuples)} files (resume).", context="OCR_FLOW")
        self.ocr_worker = OcrWorker(
            api_client=self.api_client,
            files_to_process_tuples=files_to_resume_tuples,
            input_root_folder=self.input_folder_path,
            log_manager=self.log_manager,
            config=current_config_for_run
        )
        self.ocr_worker.original_file_status_update.connect(self.on_original_file_status_update_from_worker)
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()
        self.update_ocr_controls()

    def on_original_file_status_update_from_worker(self, original_file_path, status_message):
        target_file_info = next((item for item in self.processed_files_info if item["path"] == original_file_path), None)
        if target_file_info:
            self.log_manager.debug(f"UI Update for '{os.path.basename(original_file_path)}': {status_message}", context="UI_STATUS_UPDATE")
            target_file_info["status"] = status_message
            
            if status_message == OCR_STATUS_SPLITTING:
                target_file_info["ocr_engine_status"] = OCR_STATUS_SPLITTING
            elif OCR_STATUS_PART_PROCESSING in status_message:
                target_file_info["ocr_engine_status"] = OCR_STATUS_PART_PROCESSING
            elif status_message == OCR_STATUS_MERGING:
                target_file_info["ocr_engine_status"] = OCR_STATUS_MERGING

            if not self.update_timer.isActive():
                self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS) 
        else:
            self.log_manager.warning(f"Status update received for unknown file: {original_file_path}", context="UI_STATUS_UPDATE_WARN")

    def confirm_stop_ocr(self):
        self.log_manager.debug("Confirming OCR stop...", context="OCR_FLOW")
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(self, "OCR中止確認", "OCR処理を中止しますか？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("User confirmed OCR stop. Requesting worker to stop.", context="OCR_FLOW")
                self.ocr_worker.stop()
            else:
                self.log_manager.info("User cancelled OCR stop.", context="OCR_FLOW")
        else:
            self.log_manager.debug("Stop OCR requested, but OCR is not running or worker is None.", context="OCR_FLOW")
            if self.is_ocr_running:
                self.log_manager.warning("OCR stop: UI state was 'running' but worker not active. Resetting UI state as interrupted.", context="OCR_FLOW_STATE_MISMATCH")
                self.is_ocr_running = False 
                for item_info in self.processed_files_info:
                    current_engine_status = item_info.get("ocr_engine_status")
                    if current_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING]:
                        item_info["ocr_engine_status"] = OCR_STATUS_NOT_PROCESSED 
                        item_info["status"] = "待機中(中断)"
                self.perform_batch_list_view_update() 
                self.update_ocr_controls()
                QMessageBox.information(self, "処理状態", "OCR処理は既に停止されているか、開始されていませんでした。UIを整合しました。")
            else:
                self.update_ocr_controls()

    def update_ocr_controls(self):
        running = self.is_ocr_running
        
        has_checked_and_processable_for_start = any(
            f_info.get("is_checked", False) and \
            f_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
            for f_info in self.processed_files_info
        )
        can_start_action = not running and has_checked_and_processable_for_start

        if self.start_ocr_action.isEnabled() != can_start_action:
            self.start_ocr_action.setEnabled(can_start_action)

        can_resume_action = False
        if not running and self.processed_files_info:
            has_checked_for_resume = any(
                f.get("is_checked", False) and \
                f.get("ocr_engine_status") in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and \
                f.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
                for f in self.processed_files_info
            )
            
            eligible_checked_files_for_resume_check = [
                f for f in self.processed_files_info 
                if f.get("is_checked", False) and f.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
            ]
            all_eligible_checked_are_pristine_not_processed = False
            if eligible_checked_files_for_resume_check: 
                all_eligible_checked_are_pristine_not_processed = all(
                    f.get("ocr_engine_status") == OCR_STATUS_NOT_PROCESSED for f in eligible_checked_files_for_resume_check
                )

            if has_checked_for_resume and not all_eligible_checked_are_pristine_not_processed:
                can_resume_action = True
        
        if hasattr(self, 'resume_ocr_action') and self.resume_ocr_action.isEnabled() != can_resume_action:
            self.resume_ocr_action.setEnabled(can_resume_action)

        if self.stop_ocr_action.isEnabled() != running:
            self.stop_ocr_action.setEnabled(running)
        
        can_rescan_action = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        if self.rescan_action.isEnabled() != can_rescan_action:
            self.rescan_action.setEnabled(can_rescan_action)
        
        enable_actions_if_not_running = not running
        if self.input_folder_action.isEnabled() != enable_actions_if_not_running:
            self.input_folder_action.setEnabled(enable_actions_if_not_running)
        if self.option_action.isEnabled() != enable_actions_if_not_running:
            self.option_action.setEnabled(enable_actions_if_not_running)
        
        if not self.toggle_view_action.isEnabled(): 
            self.toggle_view_action.setEnabled(True)

    def perform_batch_list_view_update(self):
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE");
        if self.list_view: self.list_view.update_files(self.processed_files_info)
        self.update_all_status_displays() 

    def on_file_ocr_processed(self, original_file_main_idx, original_file_path, ocr_result_data_for_original, ocr_error_info_for_original, json_save_status_for_original):
        self.log_manager.debug(
            f"Original File OCR stage processed (MainWin): {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Success={not ocr_error_info_for_original}, JSON Status='{json_save_status_for_original}'",
            context="CALLBACK_OCR_ORIGINAL"
        )
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx} received in on_file_ocr_processed. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return
            
        target_file_info = self.processed_files_info[original_file_main_idx]
        
        ocr_stage_successful = False 
        if ocr_error_info_for_original:
            target_file_info["status"] = "OCR失敗" 
            target_file_info["ocr_engine_status"] = OCR_STATUS_FAILED
            target_file_info["ocr_result_summary"] = ocr_error_info_for_original.get('message', '不明なOCRエラー')
        elif ocr_result_data_for_original:
            target_file_info["status"] = "OCR成功" 
            target_file_info["ocr_engine_status"] = OCR_STATUS_COMPLETED 
            ocr_stage_successful = True
            
            if isinstance(ocr_result_data_for_original, dict):
                if "detail" in ocr_result_data_for_original:
                    target_file_info["ocr_result_summary"] = ocr_result_data_for_original["detail"]
                elif "message" in ocr_result_data_for_original:
                    target_file_info["ocr_result_summary"] = ocr_result_data_for_original["message"]
                else: 
                    fulltext = ocr_result_data_for_original.get("fulltext", "") or \
                               (ocr_result_data_for_original.get("result", {}) or {}).get("fulltext", "") or \
                               (ocr_result_data_for_original.get("result", {}) or {}).get("aGroupingFulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
            elif isinstance(ocr_result_data_for_original, list) and len(ocr_result_data_for_original) > 0 : 
                try:
                    first_page_result = ocr_result_data_for_original[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "") or first_page_result.get("aGroupingFulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                except Exception: target_file_info["ocr_result_summary"] = "結果解析エラー(集約)"
            else:
                target_file_info["ocr_result_summary"] = "OCR結果あり(形式不明)"
        else: 
            target_file_info["status"] = "OCR状態不明"
            target_file_info["ocr_engine_status"] = OCR_STATUS_FAILED 
            target_file_info["ocr_result_summary"] = "APIレスポンスなし(OCR)"

        if isinstance(json_save_status_for_original, str):
            target_file_info["json_status"] = json_save_status_for_original
        elif ocr_error_info_for_original :
             target_file_info["json_status"] = "対象外(OCR失敗)"
        
        output_format = self.config.get("file_actions", {}).get("output_format", "both")
        if output_format == "json_only": 
            if target_file_info.get("ocr_engine_status") == OCR_STATUS_FAILED:
                self.summary_view.update_for_processed_file(is_success=False)
            elif target_file_info.get("ocr_engine_status") == OCR_STATUS_COMPLETED:
                self.summary_view.update_for_processed_file(is_success=True)
                target_file_info["status"] = "完了" 
            self.update_status_bar() 

        self.update_ocr_controls()
        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS) 


    def on_file_searchable_pdf_processed(self, original_file_main_idx, original_file_path, pdf_final_path, pdf_error_info):
        self.log_manager.debug(f"Original File Searchable PDF processed: {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Path={pdf_final_path}, Error={pdf_error_info}", context="CALLBACK_PDF_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx} received in on_file_searchable_pdf_processed. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return
            
        target_file_info = self.processed_files_info[original_file_main_idx]
        
        output_format = self.config.get("file_actions", {}).get("output_format", "both")
        ocr_engine_status_for_file = target_file_info.get("ocr_engine_status") 

        pdf_stage_final_success = False

        if output_format == "json_only": 
            target_file_info["searchable_pdf_status"] = "作成しない(設定)"
        elif pdf_final_path and not pdf_error_info and os.path.exists(pdf_final_path): 
            target_file_info["searchable_pdf_status"] = "PDF作成成功"
            pdf_stage_final_success = True
            if ocr_engine_status_for_file == OCR_STATUS_COMPLETED:
                target_file_info["status"] = "完了" 
        elif pdf_error_info: 
            error_msg = pdf_error_info.get('message', 'PDF作成で不明なエラー')
            error_code = pdf_error_info.get('code', '')

            if error_code == "PARTS_COPIED_SUCCESS":
                target_file_info["searchable_pdf_status"] = error_msg 
                pdf_stage_final_success = True 
                if ocr_engine_status_for_file == OCR_STATUS_COMPLETED:
                    target_file_info["status"] = "完了" 
            elif error_code in ["PARTS_COPIED_PARTIAL", "PARTS_COPY_ERROR", "NO_PARTS_TO_COPY"]:
                target_file_info["searchable_pdf_status"] = error_msg
                pdf_stage_final_success = False 
                if ocr_engine_status_for_file == OCR_STATUS_COMPLETED:
                     target_file_info["status"] = "部品PDFエラー" 
            elif "作成対象外" in error_msg or "作成しない" in error_msg or "部品PDFは結合されません(設定)" in error_msg: 
                target_file_info["searchable_pdf_status"] = error_msg
            else: 
                target_file_info["searchable_pdf_status"] = "PDF作成失敗"
                pdf_stage_final_success = False
            
            if ocr_engine_status_for_file == OCR_STATUS_COMPLETED and not pdf_stage_final_success:
                if target_file_info["searchable_pdf_status"] == "PDF作成失敗": 
                    target_file_info["status"] = "PDF作成失敗"
                    if target_file_info["ocr_result_summary"] and \
                       "部品のOCR完了" not in target_file_info["ocr_result_summary"] and \
                       "PDFエラー" not in target_file_info["ocr_result_summary"]: 
                         target_file_info["ocr_result_summary"] += f" (PDFエラー: {error_msg})"
                    elif "部品のOCR完了" not in target_file_info.get("ocr_result_summary","") and \
                         "PDFエラー" not in target_file_info["ocr_result_summary"]:
                         target_file_info["ocr_result_summary"] = f"PDFエラー: {error_msg}"
        elif ocr_engine_status_for_file == OCR_STATUS_FAILED : 
            target_file_info["searchable_pdf_status"] = "対象外(OCR失敗)"
        elif output_format in ["pdf_only", "both"]: 
            target_file_info["searchable_pdf_status"] = "PDF状態不明"
            if ocr_engine_status_for_file == OCR_STATUS_COMPLETED:
                 target_file_info["status"] = "PDF状態不明"
        else: 
            target_file_info["searchable_pdf_status"] = "-"

        if output_format != "json_only":
            is_overall_success_for_summary = (ocr_engine_status_for_file == OCR_STATUS_COMPLETED and pdf_stage_final_success)
            self.summary_view.update_for_processed_file(is_success=is_overall_success_for_summary)
            self.update_status_bar() 

        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS) 


    def on_all_files_processed(self):
        self.log_manager.info("All files processing finished by worker.", context="OCR_FLOW_COMPLETE");
        if self.update_timer.isActive(): self.update_timer.stop()
        was_interrupted_by_user = False
        if self.ocr_worker and self.ocr_worker.user_stopped:
            was_interrupted_by_user = True
        if was_interrupted_by_user:
            self.log_manager.info("OCR processing was interrupted by user.", context="OCR_FLOW_COMPLETE")
            current_config = ConfigManager.load()
            output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both")
            json_status_on_interrupt = "中断" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
            pdf_status_on_interrupt = "中断" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
            for item_info in self.processed_files_info:
                current_engine_status = item_info.get("ocr_engine_status")
                if current_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING] or \
                   (item_info.get("status") == OCR_STATUS_PROCESSING and current_engine_status == OCR_STATUS_PROCESSING):
                    item_info["ocr_engine_status"] = OCR_STATUS_FAILED 
                    item_info["status"] = "中断"
                    item_info["ocr_result_summary"] = "(処理が中止されました)"
                    item_info["json_status"] = json_status_on_interrupt
                    item_info["searchable_pdf_status"] = pdf_status_on_interrupt
        self.is_ocr_running = False
        self.perform_batch_list_view_update() 
        self.update_ocr_controls()
        final_message = "全てのファイルのOCR処理が完了しました。"
        if was_interrupted_by_user:
            final_message = "OCR処理が中止されました。"
        QMessageBox.information(self, "処理終了", final_message)
        if self.ocr_worker:
            try: 
                self.ocr_worker.original_file_status_update.disconnect(self.on_original_file_status_update_from_worker)
            except (TypeError, RuntimeError): pass 
            try:
                self.ocr_worker.file_processed.disconnect(self.on_file_ocr_processed)
            except (TypeError, RuntimeError): pass
            try:
                self.ocr_worker.searchable_pdf_processed.disconnect(self.on_file_searchable_pdf_processed)
            except (TypeError, RuntimeError): pass
            try:
                self.ocr_worker.all_files_processed.disconnect(self.on_all_files_processed)
            except (TypeError, RuntimeError): pass
            self.ocr_worker = None
    
    def confirm_rescan_ui(self):
        self.log_manager.debug("Confirming UI rescan.", context="UI_ACTION")
        if self.is_ocr_running: QMessageBox.warning(self, "再スキャン不可", "OCR処理の実行中は再スキャンできません。"); return
        if not self.processed_files_info and not self.input_folder_path: QMessageBox.information(self, "再スキャン", "クリアまたは再スキャンする対象がありません。"); return
        if self.update_timer.isActive(): self.update_timer.stop()
        message = "入力フォルダが再スキャンされます。\n\n現在のリストと進捗状況はクリアされます。\n\nよろしいですか？";
        reply = QMessageBox.question(self, "再スキャン確認", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: self.log_manager.info("User confirmed UI rescan.", context="UI_ACTION"); self.perform_rescan()
        else: self.log_manager.info("User cancelled UI rescan.", context="UI_ACTION")

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
            self.list_view.update_files(self.processed_files_info)
            self.update_all_status_displays() 
        if self.is_ocr_running: self.is_ocr_running = False
        self.update_ocr_controls()

    def closeEvent(self, event):
        self.log_manager.debug("Application closeEvent triggered.", context="SYSTEM_LIFECYCLE");
        if self.update_timer.isActive(): self.update_timer.stop()
        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？\n(進行中の処理は中断されます)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: event.ignore(); return
            else:
                if self.ocr_worker and self.ocr_worker.isRunning(): self.log_manager.info("Close event: OCR running, stopping worker before exit.", context="SYSTEM_LIFECYCLE"); self.ocr_worker.stop()
        current_config_to_save = self.config.copy(); normal_geom = self.normalGeometry(); current_config_to_save["window_state"] = "maximized" if self.isMaximized() else "normal"; current_config_to_save["window_size"] = {"width": normal_geom.width(), "height": normal_geom.height()}
        if not self.isMaximized(): current_config_to_save["window_position"] = {"x": normal_geom.x(), "y": normal_geom.y()}
        elif "window_position" in current_config_to_save: del current_config_to_save["window_position"]
        current_config_to_save["last_target_dir"] = self.input_folder_path; current_config_to_save["current_view"] = self.current_view; current_config_to_save["log_visible"] = self.log_container.isVisible()
        if hasattr(self.splitter, 'sizes'): current_config_to_save["splitter_sizes"] = self.splitter.sizes()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'): current_config_to_save["column_widths"] = self.list_view.get_column_widths(); current_config_to_save["sort_order"] = self.list_view.get_sort_order()
        ConfigManager.save(current_config_to_save); self.log_manager.info("Settings saved. Exiting application.", context="SYSTEM_LIFECYCLE"); super().closeEvent(event)

    def clear_log_display(self):
        self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました（ファイル記録のみ）。", context="UI_ACTION_CLEAR_LOG", emit_to_ui=False)