# ui_main_window.py

import sys
import os
import platform
import subprocess
from typing import Optional, Any, List, Dict 
import argparse

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter,
    QFormLayout, QPushButton, QHBoxLayout, QFrame, QSizePolicy, 
    QDialog, QDialogButtonBox, QComboBox
)
from PyQt6.QtGui import QAction, QFontMetrics, QIcon
from PyQt6.QtCore import Qt, QTimer, QSize

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

APP_VERSION = "0.0.14" 

class ApiSelectionDialog(QDialog):
    def __init__(self, api_profiles: list[dict], current_profile_id: Optional[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("APIプロファイル選択")
        self.selected_profile_id: Optional[str] = None
        
        layout = QVBoxLayout(self)
        label = QLabel("使用するAPIプロファイルを選択してください:")
        layout.addWidget(label)
        
        self.combo_box = QComboBox()
        self.profile_map = {} 
        
        for profile in api_profiles:
            profile_id = profile.get("id")
            profile_name = profile.get("name", profile_id) 
            if profile_id:
                self.combo_box.addItem(profile_name, userData=profile_id)
                self.profile_map[profile_name] = profile_id
                if profile_id == current_profile_id:
                    self.combo_box.setCurrentText(profile_name)
        
        layout.addWidget(self.combo_box)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def accept(self):
        self.selected_profile_id = self.combo_box.currentData()
        super().accept()

class MainWindow(QMainWindow):
    def __init__(self, cli_args: Optional[argparse.Namespace] = None):
        super().__init__()
        self.log_manager = LogManager()
        self.log_manager.info(f"AI inside Cube Client Ver.{APP_VERSION} 起動処理開始...", context="SYSTEM_LIFECYCLE")

        self.config = ConfigManager.load()
        self.cli_args = cli_args
        
        self._handle_api_profile_selection() 

        if not hasattr(self, 'active_api_profile') or self.active_api_profile is None:
            self.log_manager.critical("アクティブなAPIプロファイルが設定できませんでした。アプリケーションを終了します。", context="SYSTEM_LIFECYCLE")
            QMessageBox.critical(None, "致命的なエラー", "APIプロファイルの読み込みまたは選択に失敗しました。\n設定ファイルを確認するか、管理者に連絡してください。")
            sys.exit(1) 

        self.log_manager.debug(f"MainWindow initializing with API Profile: {self.active_api_profile.get('name')}", context="MAINWIN_LIFECYCLE")

        self._initialize_core_components_based_on_profile()
        self._update_window_title()
        self._connect_orchestrator_signals()
        self._setup_main_window_geometry()
        self._setup_ui_elements()
        self._load_previous_state_and_perform_initial_scan()
        self._restore_view_and_log_state()
        self._update_all_ui_controls_state()

        self.log_manager.info(f"Application initialized. API: {self.active_api_profile.get('name')}, Mode: {self.config.get('api_execution_mode', 'demo').upper()}", context="SYSTEM_LIFECYCLE")

    def _handle_api_profile_selection(self):
        # (変更なし)
        selected_profile_id_from_cli = getattr(self.cli_args, 'api', None)
        available_profiles = self.config.get("api_profiles", [])
        if not available_profiles: self.log_manager.error("設定にAPIプロファイルが定義されていません。", context="CONFIG_ERROR"); self.active_api_profile = None; return
        current_saved_profile_id = self.config.get("current_api_profile_id")
        if selected_profile_id_from_cli:
            if any(p.get("id") == selected_profile_id_from_cli for p in available_profiles):
                self.log_manager.info(f"コマンドラインからAPIプロファイル指定: {selected_profile_id_from_cli}", context="SYSTEM_INIT")
                if current_saved_profile_id != selected_profile_id_from_cli: self.config["current_api_profile_id"] = selected_profile_id_from_cli; ConfigManager.save(self.config)
                self.active_api_profile = ConfigManager.get_api_profile(self.config, selected_profile_id_from_cli); return
            else: self.log_manager.warning(f"コマンドライン指定APIプロファイルID '{selected_profile_id_from_cli}' は無効。", context="SYSTEM_INIT")
        if len(available_profiles) == 1:
            self.active_api_profile = available_profiles[0]
            if current_saved_profile_id != self.active_api_profile.get("id"): self.config["current_api_profile_id"] = self.active_api_profile.get("id"); ConfigManager.save(self.config)
            self.log_manager.info(f"単一APIプロファイル '{self.active_api_profile.get('name')}' を自動選択。", context="SYSTEM_INIT")
        else: 
            dialog = ApiSelectionDialog(available_profiles, current_saved_profile_id, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_profile_id:
                if current_saved_profile_id != dialog.selected_profile_id: self.config["current_api_profile_id"] = dialog.selected_profile_id; ConfigManager.save(self.config)
                self.active_api_profile = ConfigManager.get_api_profile(self.config, dialog.selected_profile_id); self.log_manager.info(f"ユーザー選択APIプロファイル: '{self.active_api_profile.get('name')}'", context="SYSTEM_INIT")
            else: 
                self.log_manager.warning("APIプロファイル選択キャンセルまたは失敗。保存設定を使用。", context="SYSTEM_INIT"); self.active_api_profile = ConfigManager.get_active_api_profile(self.config)
                if not self.active_api_profile and available_profiles: self.active_api_profile = available_profiles[0]; self.config["current_api_profile_id"] = self.active_api_profile.get("id"); ConfigManager.save(self.config); self.log_manager.info(f"フォールバックAPIプロファイル: '{self.active_api_profile.get('name')}'", context="SYSTEM_INIT")

    def _initialize_core_components_based_on_profile(self):
        # (変更なし)
        self.is_ocr_running = False; self.processed_files_info: list[FileInfo] = []
        self.log_widget = QTextEdit(); self.log_widget.setReadOnly(True)
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget)
        if not self.active_api_profile: self.log_manager.critical("アクティブAPIプロファイル未設定でコンポーネント初期化不可。", context="MAINWIN_LIFECYCLE"); return
        self.api_client = CubeApiClient(config=self.config, log_manager=self.log_manager, api_profile=self.active_api_profile)
        self.file_scanner = FileScanner(self.log_manager, self.config)
        self.ocr_orchestrator = OcrOrchestrator(api_client=self.api_client, log_manager=self.log_manager, config=self.config, api_profile=self.active_api_profile)
        self.update_timer = QTimer(self); self.update_timer.setSingleShot(True); self.update_timer.timeout.connect(self.perform_batch_list_view_update)
        self.input_folder_path = ""

    def perform_batch_list_view_update(self): # (変更なし)
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE")
        if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info)
        self.update_all_status_displays()

    def append_log_message_to_widget(self, level: str, message: str): # (変更なし)
        if hasattr(self, 'log_widget') and self.log_widget:
            color_map = {LogLevel.ERROR: "red", LogLevel.WARNING: "orange", LogLevel.DEBUG: "gray"}; color = color_map.get(level)
            escaped_message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self.log_widget.append(f'<font color="{color}">{escaped_message}</font>' if color else escaped_message)
            self.log_widget.ensureCursorVisible()

    def _update_window_title(self): # (変更なし)
        profile_name = "プロファイル未選択"; 
        if hasattr(self, 'active_api_profile') and self.active_api_profile and "name" in self.active_api_profile: profile_name = self.active_api_profile.get("name", "N/A")
        mode = self.config.get("api_execution_mode", "demo").upper()
        self.setWindowTitle(f"AI inside Cube Client Ver.{APP_VERSION} - {profile_name} ({mode} MODE)")

    def _connect_orchestrator_signals(self): # (変更なし)
        if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator:
            self.ocr_orchestrator.ocr_process_started_signal.connect(self._handle_ocr_process_started_from_orchestrator)
            self.ocr_orchestrator.ocr_process_finished_signal.connect(self._handle_ocr_process_finished_from_orchestrator)
            self.ocr_orchestrator.original_file_status_update_signal.connect(self.on_original_file_status_update_from_worker)
            self.ocr_orchestrator.file_ocr_processed_signal.connect(self.on_file_ocr_processed)
            self.ocr_orchestrator.file_searchable_pdf_processed_signal.connect(self.on_file_searchable_pdf_processed)
            self.ocr_orchestrator.request_ui_controls_update_signal.connect(self.update_ocr_controls) 
            self.ocr_orchestrator.request_list_view_update_signal.connect(self._handle_request_list_view_update)

    def _handle_request_list_view_update(self, updated_file_list: List[FileInfo]): # (変更なし)
        self.log_manager.debug("MainWindow: Received request to update ListView from orchestrator.", context="UI_UPDATE")
        self.processed_files_info = updated_file_list 
        if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info) 
        self.update_all_status_displays() 

    def on_original_file_status_update_from_worker(self, original_file_path: str, status_message: str): # (変更なし)
        target_file_info = next((item for item in self.processed_files_info if item.path == original_file_path), None)
        if target_file_info:
            self.log_manager.debug(f"UI Update for '{target_file_info.name}': {status_message}", context="UI_STATUS_UPDATE")
            target_file_info.status = status_message 
            if status_message == OCR_STATUS_SPLITTING: target_file_info.ocr_engine_status = OCR_STATUS_SPLITTING
            elif OCR_STATUS_PART_PROCESSING in status_message: target_file_info.ocr_engine_status = OCR_STATUS_PART_PROCESSING
            elif status_message == OCR_STATUS_MERGING: target_file_info.ocr_engine_status = OCR_STATUS_MERGING
            if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)
        else: self.log_manager.warning(f"Status update received for unknown file: {original_file_path}", context="UI_STATUS_UPDATE_WARN")

    def update_ocr_controls(self): # (変更なし)
        running = self.is_ocr_running
        if hasattr(self, 'api_mode_toggle_button'): self.api_mode_toggle_button.setEnabled(not running)
        can_start = not running and any(f.is_checked and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT for f in self.processed_files_info)
        if hasattr(self, 'start_ocr_action'): self.start_ocr_action.setEnabled(can_start)
        can_resume = False
        if not running and self.processed_files_info:
            eligible_resume = [f for f in self.processed_files_info if f.is_checked and f.ocr_engine_status in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT]
            if eligible_resume and not all(f.ocr_engine_status == OCR_STATUS_NOT_PROCESSED for f in eligible_resume): can_resume = True
        if hasattr(self, 'resume_ocr_action'): self.resume_ocr_action.setEnabled(can_resume)
        if hasattr(self, 'stop_ocr_action'): self.stop_ocr_action.setEnabled(running)
        can_rescan = not running and (bool(self.processed_files_info) or bool(self.input_folder_path))
        if hasattr(self, 'rescan_action'): self.rescan_action.setEnabled(can_rescan)
        enable_others = not running
        if hasattr(self, 'input_folder_action'): self.input_folder_action.setEnabled(enable_others)
        if hasattr(self, 'option_action'): self.option_action.setEnabled(enable_others)
        if hasattr(self, 'toggle_view_action') and not self.toggle_view_action.isEnabled(): self.toggle_view_action.setEnabled(True)

    # ★★★★★ select_input_folder メソッドを追加 ★★★★★
    def select_input_folder(self):
        self.log_manager.debug("入力フォルダ選択ダイアログを開きます。", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): 
            last_dir = os.path.expanduser("~")
            
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        
        if folder:
            self.log_manager.info(f"ユーザーが入力フォルダを選択しました: {folder}", context="UI_EVENT")
            if folder != self.input_folder_path or not self.processed_files_info:
                self.input_folder_path = folder
                self._update_folder_display() 
                self.log_manager.info(f"新しい入力フォルダのため再スキャンを実行します: {folder}", context="UI_EVENT")
                self.perform_rescan() 
            else:
                self.log_manager.info("選択されたフォルダは現在の入力フォルダと同じで、ファイルリストは空ではありません。強制的な再スキャンは行いません。", context="UI_EVENT")
        else:
            self.log_manager.info("入力フォルダの選択がキャンセルされました。", context="UI_EVENT")
        self._update_folder_display() 
        
    # ★★★★★ toggle_view メソッドを追加 ★★★★★
    def toggle_view(self):
        """サマリービューとリストビューを切り替える"""
        if hasattr(self, 'stack') and self.stack is not None:
            current_index = self.stack.currentIndex()
            next_index = 1 - current_index # 0 と 1 をトグル
            self.stack.setCurrentIndex(next_index)
            self.current_view = next_index # 設定保存用に現在のビューインデックスを更新
            self.log_manager.info(f"表示ビューを切り替えました: {'リストビュー' if next_index == 1 else 'サマリービュー'}", context="UI_ACTION")
        else:
            self.log_manager.warning("ビューの切り替えに失敗しました。スタックウィジェットが見つかりません。", context="UI_ERROR")

    def _setup_main_window_geometry(self): # (変更なし)
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700}); state_cfg = self.config.get("window_state", "normal"); pos_cfg = self.config.get("window_position")
        self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try: screen_geometry = QApplication.primaryScreen().geometry(); self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e: self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e); self.move(100, 100)
        else: self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized": self.showMaximized()

    def _setup_ui_elements(self): # (変更なし)
        self._setup_central_widget_and_main_layout(); self._setup_views_log_widget_and_splitter(); self._setup_status_bar(); self._setup_toolbars_and_folder_labels()

    def _setup_central_widget_and_main_layout(self): # (変更なし)
        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget); self.main_layout.setContentsMargins(2, 2, 2, 2); self.main_layout.setSpacing(0)

    def _setup_views_log_widget_and_splitter(self): # (変更なし)
        self.splitter = QSplitter(Qt.Orientation.Vertical); self.stack = QStackedWidget()
        self.summary_view = SummaryView(); self.summary_view.log_manager = self.log_manager
        self.list_view = ListView(self.processed_files_info); self.list_view.item_check_state_changed.connect(self.on_list_item_check_state_changed)
        self.stack.addWidget(self.summary_view); self.stack.addWidget(self.list_view); self.splitter.addWidget(self.stack)
        self.log_container = QWidget(); log_layout_inner = QVBoxLayout(self.log_container); log_layout_inner.setContentsMargins(8, 8, 8, 8); log_layout_inner.setSpacing(0)
        self.log_header = QLabel("ログ："); self.log_header.setStyleSheet("margin-left: 6px; padding-bottom: 0px; font-weight: bold;"); log_layout_inner.addWidget(self.log_header)
        self.log_widget.setStyleSheet("QTextEdit { font-family: Consolas, Meiryo, monospace; font-size: 9pt; border: 1px solid #D0D0D0; margin: 0px; } /* ... */ ")
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded); self.log_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        log_layout_inner.addWidget(self.log_widget); self.log_container.setStyleSheet("margin: 0px 6px 6px 6px;"); self.splitter.addWidget(self.log_container)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        splitter_sizes = self.config.get("splitter_sizes"); default_h = self.height()
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0: self.splitter.setSizes(splitter_sizes)
        else: self.splitter.setSizes([int(default_h * 0.65), int(default_h * 0.35)])
        self.main_layout.addWidget(self.splitter)

    def _setup_status_bar(self): # (変更なし)
        self.status_bar_frame = QFrame(); self.status_bar_frame.setFrameShape(QFrame.Shape.NoFrame); self.status_bar_frame.setObjectName("StatusBarFrame")
        self.status_bar_frame.setStyleSheet("QFrame#StatusBarFrame { background-color: #ECECEC; border-top: 1px solid #B0B0B0; min-height: 26px; max-height: 26px; } QLabel#StatusBarLabel { padding: 3px 0px; font-size: 8pt; border: none; }")
        status_bar_layout = QHBoxLayout(self.status_bar_frame); status_bar_layout.setContentsMargins(15, 2, 15, 2)
        self.status_total_list_label = QLabel("リスト総数: 0"); self.status_total_list_label.setObjectName("StatusBarLabel")
        self.status_selected_files_label = QLabel("選択中: 0"); self.status_selected_files_label.setObjectName("StatusBarLabel")
        self.status_success_files_label = QLabel("成功: 0"); self.status_success_files_label.setObjectName("StatusBarLabel")
        self.status_error_files_label = QLabel("エラー: 0"); self.status_error_files_label.setObjectName("StatusBarLabel")
        status_bar_layout.addWidget(self.status_total_list_label); status_bar_layout.addSpacing(25); status_bar_layout.addWidget(self.status_selected_files_label); status_bar_layout.addStretch(1)
        status_bar_layout.addWidget(self.status_success_files_label); status_bar_layout.addSpacing(25); status_bar_layout.addWidget(self.status_error_files_label)
        self.main_layout.addWidget(self.status_bar_frame)

    def _setup_toolbars_and_folder_labels(self): # (変更なし)
        toolbar = QToolBar("Main Toolbar"); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.input_folder_action = QAction("📂入力", self); self.input_folder_action.triggered.connect(self.select_input_folder); toolbar.addAction(self.input_folder_action)
        self.toggle_view_action = QAction("📑ビュー", self); self.toggle_view_action.triggered.connect(self.toggle_view); toolbar.addAction(self.toggle_view_action)
        self.option_action = QAction("⚙️設定", self); self.option_action.triggered.connect(self.show_option_dialog); toolbar.addAction(self.option_action)
        toolbar.addSeparator()
        self.start_ocr_action = QAction("▶️開始", self); self.start_ocr_action.triggered.connect(self.confirm_start_ocr); toolbar.addAction(self.start_ocr_action)
        self.resume_ocr_action = QAction("↪️再開", self); self.resume_ocr_action.setToolTip("未処理または失敗したファイルのOCR処理を再開します"); self.resume_ocr_action.triggered.connect(self.confirm_resume_ocr); toolbar.addAction(self.resume_ocr_action)
        self.stop_ocr_action = QAction("⏹️中止", self); self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr); toolbar.addAction(self.stop_ocr_action)
        self.rescan_action = QAction("🔄再スキャン", self); self.rescan_action.triggered.connect(self.confirm_rescan_ui); self.rescan_action.setEnabled(False); toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        self.log_toggle_action = QAction("📄ログ表示", self); self.log_toggle_action.triggered.connect(self.toggle_log_display); toolbar.addAction(self.log_toggle_action)
        self.clear_log_action = QAction("🗑️ログクリア", self); self.clear_log_action.triggered.connect(self.clear_log_display); toolbar.addAction(self.clear_log_action)
        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); toolbar.addWidget(spacer)
        self.api_mode_toggle_button = QPushButton(); self.api_mode_toggle_button.setCheckable(False); self.api_mode_toggle_button.clicked.connect(self._toggle_api_mode); self.api_mode_toggle_button.setMinimumWidth(120)
        self.api_mode_toggle_button.setStyleSheet("QPushButton { padding: 4px 8px; border: 1px solid #8f8f8f; border-radius: 4px; font-weight: bold; } QPushButton[apiMode=\"live\"] { background-color: #e6fff2; color: #006400; } QPushButton[apiMode=\"demo\"] { background-color: #e6f7ff; color: #005f9e; } QPushButton:disabled { background-color: #f0f0f0; color: #a0a0a0; }")
        toolbar.addWidget(self.api_mode_toggle_button)
        right_spacer = QWidget(); right_spacer.setFixedWidth(10) ; toolbar.addWidget(right_spacer)
        folder_label_toolbar = QToolBar("Folder Paths Toolbar"); folder_label_toolbar.setMovable(False)
        folder_label_widget = QWidget(); folder_label_layout = QFormLayout(folder_label_widget); folder_label_layout.setContentsMargins(5, 5, 5, 5); folder_label_layout.setSpacing(3)
        self.input_folder_button = QPushButton(); self._update_folder_display()
        self.input_folder_button.setStyleSheet("QPushButton { border: none; background: transparent; text-align: left; padding: 0px; margin: 0px; } QPushButton:hover { text-decoration: underline; color: blue; }")
        self.input_folder_button.setFlat(True); self.input_folder_button.setCursor(Qt.CursorShape.PointingHandCursor); self.input_folder_button.clicked.connect(self.open_input_folder_in_explorer)
        folder_label_layout.addRow("入力フォルダ:", self.input_folder_button); folder_label_toolbar.addWidget(folder_label_widget)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar); self.insertToolBarBreak(folder_label_toolbar)

    def _update_api_mode_toggle_button_display(self): # (変更なし)
        if not hasattr(self, 'api_mode_toggle_button'): return 
        current_mode = self.config.get("api_execution_mode", "demo")
        if current_mode == "live": self.api_mode_toggle_button.setText("🔴 Live モード"); self.api_mode_toggle_button.setToolTip("現在 Live モードです。クリックして Demo モードに切り替えます。"); self.api_mode_toggle_button.setProperty("apiMode", "live")
        else: self.api_mode_toggle_button.setText("🔵 Demo モード"); self.api_mode_toggle_button.setToolTip("現在 Demo モードです。クリックして Live モードに切り替えます。"); self.api_mode_toggle_button.setProperty("apiMode", "demo")
        self.api_mode_toggle_button.style().unpolish(self.api_mode_toggle_button); self.api_mode_toggle_button.style().polish(self.api_mode_toggle_button); self.api_mode_toggle_button.update()

    def _toggle_api_mode(self): # (変更なし)
        if self.is_ocr_running: QMessageBox.warning(self, "モード変更不可", "OCR処理の実行中はAPIモードを変更できません。"); return
        current_mode = self.config.get("api_execution_mode", "demo"); new_mode = "live" if current_mode == "demo" else "demo"
        if new_mode == "live" and not self.config.get("api_key", "").strip(): QMessageBox.warning(self, "APIキー未設定", "Liveモードに切り替えるには、まず「⚙️設定」からAPIキーを設定してください。"); return
        msg_box = QMessageBox(self); msg_box.setWindowTitle("APIモード変更の確認"); msg_box.setText(f"API実行モードを「{current_mode.upper()}」から「{new_mode.upper()}」に変更しますか？")
        msg_box.setInformativeText("変更を保存し、関連コンポーネントに適用します。"); msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No); msg_box.setDefaultButton(QMessageBox.StandardButton.No); msg_box.setIcon(QMessageBox.Icon.Question)
        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            self.config["api_execution_mode"] = new_mode; ConfigManager.save(self.config); self.log_manager.info(f"API execution mode changed to: {new_mode.upper()}", context="CONFIG_CHANGE_MAIN")
            if hasattr(self, 'api_client') and self.api_client: self.api_client.update_config(self.config, self.active_api_profile)
            if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator: self.ocr_orchestrator.update_config(self.config, self.active_api_profile)
            self._update_window_title(); self._update_api_mode_toggle_button_display(); self.update_ocr_controls(); self.log_manager.info(f"MainWindow components updated for {new_mode.upper()} mode.", context="CONFIG_CHANGE_MAIN")

    def _update_folder_display(self): # (変更なし)
        if hasattr(self, 'input_folder_button'): display_path = self.input_folder_path or "未選択"; self.input_folder_button.setText(display_path); self.input_folder_button.setToolTip(self.input_folder_path if self.input_folder_path else "入力フォルダが選択されていません")

    def _load_previous_state_and_perform_initial_scan(self): # (変更なし)
        self.input_folder_path = self.config.get("last_target_dir", "")
        self._update_folder_display()
        if self.input_folder_path and os.path.isdir(self.input_folder_path): self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT"); self.perform_initial_scan()
        elif self.input_folder_path: self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT"); self.input_folder_path = ""; self._update_folder_display(); self._clear_and_update_file_list_display()
        else: self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT"); self._update_folder_display(); self._clear_and_update_file_list_display()
        if hasattr(self, 'api_mode_toggle_button'): self._update_api_mode_toggle_button_display()

    def _clear_and_update_file_list_display(self): # (変更なし)
        self.processed_files_info = []; self.list_view.update_files([]) if hasattr(self, 'list_view') else None; self.summary_view.reset_summary() if hasattr(self, 'summary_view') else None; self.update_all_status_displays()

    def _restore_view_and_log_state(self): # (変更なし)
        self.current_view = self.config.get("current_view", 0); self.stack.setCurrentIndex(self.current_view) if hasattr(self, 'stack') else None
        log_visible = self.config.get("log_visible", True); self.log_container.setVisible(log_visible) if hasattr(self, 'log_container') else None

    def _update_all_ui_controls_state(self): self.update_ocr_controls() # (変更なし)

    def _handle_ocr_process_started_from_orchestrator(self, num_files_to_process: int, updated_file_list: List[FileInfo]): # (変更なし)
        self.log_manager.info(f"MainWindow: OCR process started signal received for {num_files_to_process} files.", context="OCR_FLOW_MAIN"); self.is_ocr_running = True; self.processed_files_info = updated_file_list
        if hasattr(self, 'list_view'): self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'): self.summary_view.start_processing(num_files_to_process)
        self.update_status_bar(); self.update_ocr_controls()

    def _handle_ocr_process_finished_from_orchestrator(self, was_interrupted: bool, fatal_error_info: Optional[Dict[str, Any]] = None): # (変更なし)
        self.log_manager.info(f"MainWindow: OCR process finished signal received. Interrupted: {was_interrupted}, FatalError: {fatal_error_info}", context="OCR_FLOW_MAIN"); self.is_ocr_running = False; reason = ""
        if fatal_error_info and isinstance(fatal_error_info, dict): reason = fatal_error_info.get("message", "不明な致命的エラー"); self.log_manager.error(f"OCR停止(致命的エラー): {reason}", context="OCR_FLOW_MAIN")
        elif was_interrupted: reason = "ユーザーによる中止"; self.log_manager.info("OCR処理が中止されました。", context="OCR_FLOW_MAIN")
        if was_interrupted or fatal_error_info:
            output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both"); json_status = "中断" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"; pdf_status = "中断" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
            for fi in self.processed_files_info:
                if fi.ocr_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING] or (fi.status == OCR_STATUS_PROCESSING and fi.ocr_engine_status == OCR_STATUS_PROCESSING):
                    fi.ocr_engine_status = OCR_STATUS_FAILED; fi.status = "中断" if was_interrupted else "エラー(停止)"; fi.ocr_result_summary = f"(処理中止/停止: {reason})" if reason else "(処理中止/停止)"; fi.json_status = json_status; fi.searchable_pdf_status = pdf_status
        self.perform_batch_list_view_update(); self.update_ocr_controls()
        final_msg = "全てのファイルのOCR処理が完了しました。"
        if fatal_error_info and isinstance(fatal_error_info, dict): final_msg = f"OCR処理がエラーにより停止しました。\n理由: {fatal_error_info.get('message', '不明なエラー')}" + (("\n\nLiveモードAPI未実装です。" if fatal_error_info.get("code") in ["NOT_IMPLEMENTED_LIVE_API", "NOT_IMPLEMENTED_LIVE_API_PDF", "NOT_IMPLEMENTED_API_CALL", "NOT_IMPLEMENTED_API_CALL_PDF"] else "")) ; QMessageBox.critical(self, "処理停止 (致命的エラー)", final_msg)
        elif was_interrupted: final_msg = "OCR処理が中止されました。"; QMessageBox.information(self, "処理終了", final_msg)
        else: QMessageBox.information(self, "処理終了", final_msg)

    def update_status_bar(self): # (変更なし)
        total = len(self.processed_files_info); selected = sum(1 for f in self.processed_files_info if f.is_checked and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT)
        success = getattr(self.summary_view, 'ocr_completed_count', 0); error = getattr(self.summary_view, 'ocr_error_count', 0)
        if hasattr(self, 'status_total_list_label'): self.status_total_list_label.setText(f"リスト総数: {total}"); self.status_selected_files_label.setText(f"選択中: {selected}"); self.status_success_files_label.setText(f"成功: {success}"); self.status_error_files_label.setText(f"エラー: {error}")

    def update_all_status_displays(self): # (変更なし)
        skipped = sum(1 for f in self.processed_files_info if f.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT); checked_processable = sum(1 for f in self.processed_files_info if f.is_checked and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT)
        if hasattr(self, 'summary_view'): self.summary_view.update_summary_counts(total_scanned=len(self.processed_files_info), total_ocr_target=checked_processable, skipped_size=skipped)
        self.update_status_bar()

    def on_list_item_check_state_changed(self, row_index, is_checked): # (変更なし)
        if 0 <= row_index < len(self.processed_files_info): self.processed_files_info[row_index].is_checked = is_checked; self.log_manager.debug(f"File '{self.processed_files_info[row_index].name}' check state: {is_checked}", context="UI_EVENT"); self.update_all_status_displays(); self.update_ocr_controls()
    
    def on_file_ocr_processed(self, original_file_main_idx: int, original_file_path: str, ocr_result_data_for_original: Any, ocr_error_info_for_original: Optional[Dict[str, Any]], json_save_status_for_original: Any): # (変更なし - 前回の修正適用済み)
        self.log_manager.debug(f"Original File OCR stage processed (MainWin): {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Success={not ocr_error_info_for_original}, JSON Status='{json_save_status_for_original}'", context="CALLBACK_OCR_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)): self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx}. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR"); return
        target_file_info = self.processed_files_info[original_file_main_idx]; processed_as_error = False
        if ocr_error_info_for_original and isinstance(ocr_error_info_for_original, dict):
            target_file_info.status = "OCR失敗"; target_file_info.ocr_engine_status = OCR_STATUS_FAILED; err_msg = ocr_error_info_for_original.get('message', '不明なOCRエラー'); err_code = ocr_error_info_for_original.get('code', ''); err_detail = ocr_error_info_for_original.get('detail', '')
            target_file_info.ocr_result_summary = f"エラー ({err_code})" if err_code else "エラー (詳細はログ参照)"; self.log_manager.error(f"OCR処理エラー詳細 (ファイル: {target_file_info.name}): Msg='{err_msg}', Code='{err_code}', Detail='{err_detail}'", context="OCR_PROCESS_ERROR_DETAIL")
            if err_code not in ["USER_INTERRUPT", "NOT_IMPLEMENTED_LIVE_API", "NOT_IMPLEMENTED_API_CALL", "FATAL_ERROR_STOP", "PART_PROCESSING_ERROR"]: QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})", f"ファイル「{target_file_info.name}」のOCR処理中にエラーが発生しました。\n\nメッセージ: {err_msg}\nコード: {err_code}\n詳細: {err_detail if err_detail else 'N/A'}\n\nログファイルをご確認ください。"); processed_as_error = True
        if not processed_as_error and ocr_result_data_for_original:
            target_file_info.status = "OCR成功"; target_file_info.ocr_engine_status = OCR_STATUS_COMPLETED; fulltext_to_log = ""
            if isinstance(ocr_result_data_for_original, dict) and ocr_result_data_for_original.get("status") == "parts_processed_ok": target_file_info.ocr_result_summary = "成功 (分割処理)"; detail_message = ocr_result_data_for_original.get('detail', ''); self.log_manager.info(f"ファイル '{target_file_info.name}' のOCR処理(分割): {detail_message}", context="OCR_PROCESS_DETAIL")
            else:
                extracted_fulltext = ""; 
                if isinstance(ocr_result_data_for_original, list) and ocr_result_data_for_original:
                    try: first_page_content = ocr_result_data_for_original[0]; result_field = first_page_content.get("result", {}); fulltext_parts = []; extracted_fulltext = " / ".join(filter(None, [result_field.get("fulltext"), result_field.get("aGroupingFulltext")]))
                    except Exception as e: extracted_fulltext = ""; self.log_manager.error(f"OCR結果(リスト)の解析中にエラー: {e} (データ: {ocr_result_data_for_original})", context="UI_OCR_RESULT_PARSE", exc_info=True)
                elif isinstance(ocr_result_data_for_original, dict):
                    results_list = ocr_result_data_for_original.get("results", []); 
                    if results_list and isinstance(results_list, list) and results_list[0].get("pages"): first_page = results_list[0]["pages"][0] if results_list[0]["pages"] else {}; extracted_fulltext = first_page.get("fulltext", "")
                    elif "fulltext" in ocr_result_data_for_original: extracted_fulltext = ocr_result_data_for_original.get("fulltext", "")
                    else: self.log_manager.warning(f"OCR結果(辞書)の形式が予期したものではありません: {ocr_result_data_for_original}", context="UI_OCR_RESULT_PARSE")
                else: self.log_manager.warning(f"OCR結果の形式がリストでも辞書でもありません: {type(ocr_result_data_for_original)}", context="UI_OCR_RESULT_PARSE")
                fulltext_to_log = extracted_fulltext
                if extracted_fulltext: target_file_info.ocr_result_summary = "成功 (テキストあり)"; log_text = (fulltext_to_log[:200] + '...') if len(fulltext_to_log) > 200 else fulltext_to_log; self.log_manager.debug(f"ファイル '{target_file_info.name}' の抽出テキスト(一部): {log_text}", context="OCR_EXTRACTED_TEXT_DETAIL")
                else: target_file_info.ocr_result_summary = "成功 (テキストなし)"
        if not processed_as_error and not ocr_result_data_for_original: target_file_info.status = "OCR状態不明"; target_file_info.ocr_engine_status = OCR_STATUS_FAILED; target_file_info.ocr_result_summary = "応答なし(OCR)" 
        if isinstance(json_save_status_for_original, str): target_file_info.json_status = json_save_status_for_original
        elif ocr_error_info_for_original: target_file_info.json_status = "対象外(OCR失敗)"
        if self.config.get("file_actions", {}).get("output_format", "both") == "json_only":
            if target_file_info.ocr_engine_status == OCR_STATUS_FAILED: self.summary_view.update_for_processed_file(is_success=False) if hasattr(self, 'summary_view') else None
            elif target_file_info.ocr_engine_status == OCR_STATUS_COMPLETED: self.summary_view.update_for_processed_file(is_success=True) if hasattr(self, 'summary_view') else None; target_file_info.status = "完了"
            self.update_status_bar()
        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_file_searchable_pdf_processed(self, original_file_main_idx: int, original_file_path: str, pdf_final_path: Optional[str], pdf_error_info: Optional[Dict[str, Any]]):
        self.log_manager.debug(f"Original File Searchable PDF processed: {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Path={pdf_final_path}, Error={pdf_error_info}", context="CALLBACK_PDF_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)): self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx}. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR"); return
        target_file_info = self.processed_files_info[original_file_main_idx]; output_format = self.config.get("file_actions", {}).get("output_format", "both"); ocr_engine_status = target_file_info.ocr_engine_status; pdf_stage_final_success = False
        if output_format == "json_only": target_file_info.searchable_pdf_status = "作成しない(設定)"
        elif pdf_final_path and not pdf_error_info and os.path.exists(pdf_final_path): 
            target_file_info.searchable_pdf_status = "PDF作成成功"
            pdf_stage_final_success = True
            if ocr_engine_status == OCR_STATUS_COMPLETED: target_file_info.status = "完了"
        elif pdf_error_info and isinstance(pdf_error_info, dict):
            error_msg = pdf_error_info.get('message', 'PDF作成不明エラー'); error_code = pdf_error_info.get('code', ''); err_detail = pdf_error_info.get('detail', '')
            if error_code == "PARTS_COPIED_SUCCESS": 
                 target_file_info.searchable_pdf_status = error_msg 
                 pdf_stage_final_success = True
                 if ocr_engine_status == OCR_STATUS_COMPLETED: target_file_info.status = "完了"
            elif "作成しない" in error_msg or "対象外" in error_msg or "部品PDFは結合されません(設定)" in error_msg : 
                target_file_info.searchable_pdf_status = error_msg 
            else: 
                target_file_info.searchable_pdf_status = f"PDFエラー ({error_code})" if error_code else "PDFエラー (ログ参照)"
                self.log_manager.error(f"PDF処理エラー詳細 (ファイル: {target_file_info.name}): Msg='{error_msg}', Code='{error_code}', Detail='{err_detail}'", context="PDF_PROCESS_ERROR_DETAIL")
            if ocr_engine_status == OCR_STATUS_COMPLETED and not pdf_stage_final_success and error_code not in ["PARTS_COPIED_SUCCESS", "NO_PARTS_TO_COPY", "PDF_NOT_REQUESTED"]: 
                target_file_info.status = "PDF作成失敗"
            if error_code not in ["USER_INTERRUPT_PDF", "PDF_NOT_REQUESTED", "PARTS_COPIED_SUCCESS", "NO_PARTS_TO_COPY", "PDF_CREATION_FAIL_DUE_TO_OCR_ERROR", "NOT_IMPLEMENTED_LIVE_API_PDF", "NOT_IMPLEMENTED_API_CALL_PDF", "FATAL_ERROR_STOP_PDF"]: 
                QMessageBox.warning(self, f"PDF処理エラー ({target_file_info.name})", f"ファイル「{target_file_info.name}」のPDF処理エラー。\n\nメッセージ: {error_msg}\nコード: {error_code}\n詳細: {err_detail or 'N/A'}\n\nログ参照。")
        elif ocr_engine_status == OCR_STATUS_FAILED: 
            target_file_info.searchable_pdf_status = "対象外(OCR失敗)"
        elif output_format in ["pdf_only", "both"]: 
            target_file_info.searchable_pdf_status = "PDF状態不明"
            if ocr_engine_status == OCR_STATUS_COMPLETED: target_file_info.status = "PDF状態不明"
        else: 
            target_file_info.searchable_pdf_status = "-" 
        
        if output_format != "json_only":
            is_overall_success = (ocr_engine_status == OCR_STATUS_COMPLETED and pdf_stage_final_success)
            if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=is_overall_success)
            self.update_status_bar()
        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_all_files_processed(self, was_interrupted_by_orchestrator: bool, fatal_error_info: Optional[dict] = None):
        self._handle_ocr_process_finished_from_orchestrator(was_interrupted_by_orchestrator, fatal_error_info)

    def handle_ocr_interruption_ui_update(self):
        self.log_manager.info("MainWindow: Handling UI update for OCR interruption.", context="UI_UPDATE_INTERRUPT")
        for file_info in self.processed_files_info:
            if file_info.ocr_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING]: file_info.ocr_engine_status = OCR_STATUS_NOT_PROCESSED; file_info.status = "待機中(中断)"
        self.perform_batch_list_view_update(); self.update_ocr_controls()

    def confirm_rescan_ui(self):
        self.log_manager.debug("Confirming UI rescan.", context="UI_ACTION")
        if self.is_ocr_running: QMessageBox.warning(self, "再スキャン不可", "OCR処理の実行中は再スキャンできません。"); return
        if not self.processed_files_info and not self.input_folder_path: QMessageBox.information(self, "再スキャン", "クリアまたは再スキャンする対象がありません。"); return
        if self.update_timer.isActive(): self.update_timer.stop()
        reply = QMessageBox.question(self, "再スキャン確認", "入力フォルダが再スキャンされます。\n\n現在のリストと進捗状況はクリアされます。\n\nよろしいですか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: self.log_manager.info("User confirmed UI rescan.", context="UI_ACTION"); self.perform_rescan()
        else: self.log_manager.info("User cancelled UI rescan.", context="UI_ACTION")

    def perform_rescan(self):
        self.log_manager.info("Performing UI clear and input folder rescan.", context="UI_ACTION_RESCAN")
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        if self.input_folder_path and os.path.isdir(self.input_folder_path): self.log_manager.info(f"Rescanning input folder: {self.input_folder_path}", context="UI_ACTION_RESCAN"); self.perform_initial_scan()
        else: self.log_manager.info("Rescan: Input folder not set or invalid. File list cleared.", context="UI_ACTION_RESCAN"); self.processed_files_info = []; self.list_view.update_files([]) if hasattr(self, 'list_view') else None; self.update_all_status_displays()
        self._update_folder_display(); self.is_ocr_running = False; self.update_ocr_controls()

    def closeEvent(self, event):
        self.log_manager.debug("Application closeEvent triggered.", context="SYSTEM_LIFECYCLE")
        if self.update_timer.isActive(): self.update_timer.stop()
        if self.is_ocr_running:
            if QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？\n(進行中の処理は中断されます)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.No: event.ignore(); return
            if self.ocr_orchestrator: self.log_manager.info("Close event: OCR running, stopping worker.", context="SYSTEM_LIFECYCLE"); self.ocr_orchestrator.confirm_and_stop_ocr(self)
        
        cfg = self.config.copy(); geom = self.normalGeometry()
        cfg["window_state"] = "maximized" if self.isMaximized() else "normal"; cfg["window_size"] = {"width": geom.width(), "height": geom.height()}
        if not self.isMaximized(): cfg["window_position"] = {"x": geom.x(), "y": geom.y()}
        elif "window_position" in cfg: del cfg["window_position"]
        cfg["last_target_dir"] = self.input_folder_path; cfg["current_view"] = getattr(self, 'current_view', 0)
        cfg["log_visible"] = getattr(self.log_container, 'isVisible', lambda: True)()
        if hasattr(self.splitter, 'sizes'): cfg["splitter_sizes"] = self.splitter.sizes()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'): cfg["column_widths"] = self.list_view.get_column_widths(); cfg["sort_order"] = self.list_view.get_sort_order()
        ConfigManager.save(cfg); self.log_manager.info("Settings saved. Exiting application.", context="SYSTEM_LIFECYCLE"); super().closeEvent(event)

    def clear_log_display(self):
        if hasattr(self, 'log_widget'): self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました（ファイル記録は継続）。", context="UI_ACTION_CLEAR_LOG", emit_to_ui=False)