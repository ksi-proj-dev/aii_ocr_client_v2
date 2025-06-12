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
from api_client import OCRApiClient
from file_scanner import FileScanner
from ocr_orchestrator import OcrOrchestrator
from file_model import FileInfo
from ui_dialogs import OcrConfirmationDialog, SortConfigDialog

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING,
    LISTVIEW_UPDATE_INTERVAL_MS
)

APP_VERSION = "0.0.16"


class ApiSelectionDialog(QDialog):
    def __init__(self, api_profiles: list[dict], current_profile_id: Optional[str], parent=None, initial_selection_filter: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("APIプロファイル選択")
        self.selected_profile_id: Optional[str] = None
        self.log_manager = LogManager()

        layout = QVBoxLayout(self)
        label = QLabel("使用するAPIプロファイルを選択してください:")
        layout.addWidget(label)

        self.combo_box = QComboBox()

        profiles_to_display = []
        if initial_selection_filter:
            temp_ids_in_dialog = set()
            for profile_id_to_filter in initial_selection_filter:
                if profile_id_to_filter in temp_ids_in_dialog:
                    continue
                profile = next((p for p in api_profiles if p.get("id") == profile_id_to_filter), None)
                if profile:
                    profiles_to_display.append(profile)
                    temp_ids_in_dialog.add(profile_id_to_filter)
            
            if not profiles_to_display:
                self.log_manager.warning(f"ApiSelectionDialog: initial_selection_filterで有効なプロファイルが見つかりませんでした。全プロファイルを表示します。Filter: {initial_selection_filter}", context="UI_DIALOG_WARN")
                profiles_to_display = api_profiles
        else:
            profiles_to_display = api_profiles

        selected_text_to_set = None
        if initial_selection_filter and profiles_to_display:
            # フィルタリングされたリストの最初の項目を選択状態にする
            selected_text_to_set = profiles_to_display[0].get("name", profiles_to_display[0].get("id"))
        elif not initial_selection_filter and current_profile_id:
             profile = next((p for p in profiles_to_display if p.get("id") == current_profile_id), None)
             if profile:
                selected_text_to_set = profile.get("name", profile.get("id"))

        for profile in profiles_to_display:
            profile_id = profile.get("id")
            profile_name = profile.get("name", profile_id)
            if profile_id:
                self.combo_box.addItem(profile_name, userData=profile_id)
        
        if selected_text_to_set:
            self.combo_box.setCurrentText(selected_text_to_set)
        elif self.combo_box.count() > 0 :
            self.combo_box.setCurrentIndex(0)

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
        self.log_manager.info(f"AI inside OCR Client Ver.{APP_VERSION} 起動処理開始...", context="SYSTEM_LIFECYCLE")

        self.config = ConfigManager.load()
        self.cli_args = cli_args
        self.active_api_profile: Optional[Dict[str, Any]] = None

        self._handle_api_profile_selection()

        if self.active_api_profile is None:
            self.log_manager.critical("アクティブなAPIプロファイルが設定できませんでした。アプリケーションを終了します。", context="SYSTEM_LIFECYCLE_CRITICAL")
            QMessageBox.critical(None, "致命的な設定エラー", "利用可能なAPIプロファイルの読み込みまたは選択に失敗しました。\n設定ファイルを確認するか、管理者に連絡してください。")
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
        available_profiles = self.config.get("api_profiles", [])
        if not available_profiles:
            self.log_manager.critical("設定にAPIプロファイルが定義されていません。アプリケーションを終了します。", context="CONFIG_ERROR_CRITICAL")
            QMessageBox.critical(None, "設定エラー", "利用可能なAPIプロファイルが設定ファイルに定義されていません。")
            sys.exit(1)

        current_saved_profile_id = self.config.get("current_api_profile_id")
        cli_profile_ids: Optional[List[str]] = getattr(self.cli_args, 'api', None)

        target_profile_id_from_cli: Optional[str] = None
        ids_for_dialog_filter: Optional[List[str]] = None

        if cli_profile_ids is not None:
            if not cli_profile_ids:
                self.log_manager.info("--api オプションがIDなしで指定されたため、プロファイル選択ダイアログを表示します。", context="SYSTEM_INIT_CLI")
            else:
                valid_cli_ids_set = set()
                invalid_cli_ids_for_msg = []
                processed_invalid_ids_for_msg = set()

                for cli_id in cli_profile_ids:
                    is_valid_profile = any(p.get("id") == cli_id for p in available_profiles)
                    if is_valid_profile:
                        valid_cli_ids_set.add(cli_id)
                    elif cli_id not in processed_invalid_ids_for_msg:
                        invalid_cli_ids_for_msg.append(cli_id)
                        processed_invalid_ids_for_msg.add(cli_id)
                
                valid_cli_ids = list(valid_cli_ids_set)

                if invalid_cli_ids_for_msg:
                    invalid_ids_str = ", ".join(invalid_cli_ids_for_msg)
                    msg = f"コマンドラインで指定された以下のAPIプロファイルIDは無効（未実装など）です:\n{invalid_ids_str}\n\n"
                    if valid_cli_ids:
                        msg += "有効なIDでの処理を続行しますか？\n（「キャンセル」でアプリケーションを終了します）"
                        reply = QMessageBox.warning(None, "無効なプロファイルID", msg,
                                                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                                                    QMessageBox.StandardButton.Ok)
                        if reply == QMessageBox.StandardButton.Cancel:
                            self.log_manager.warning(f"ユーザーが無効なプロファイルID警告後にキャンセルを選択しました。アプリを終了します。Invalid IDs: {invalid_ids_str}", context="SYSTEM_INIT_CLI_CANCEL")
                            sys.exit(0)
                        self.log_manager.info(f"無効なプロファイルID ({invalid_ids_str}) がありましたが、ユーザーは処理継続を選択しました。", context="SYSTEM_INIT_CLI")
                    else:
                        msg += "有効なプロファイルIDが一つも指定されませんでした。アプリケーションを終了します。"
                        self.log_manager.error(msg, context="SYSTEM_INIT_CLI_ERROR")
                        QMessageBox.critical(None, "プロファイル指定エラー", msg)
                        sys.exit(1)
                
                if len(valid_cli_ids) == 1:
                    target_profile_id_from_cli = valid_cli_ids[0]
                    self.log_manager.info(f"コマンドラインからAPIプロファイル '{target_profile_id_from_cli}' が指定されました。", context="SYSTEM_INIT_CLI")
                elif len(valid_cli_ids) > 1:
                    self.log_manager.info(f"コマンドラインから複数の有効なAPIプロファイル {valid_cli_ids} が指定されたため、選択ダイアログを表示します。", context="SYSTEM_INIT_CLI")
                    ids_for_dialog_filter = valid_cli_ids
        
        if target_profile_id_from_cli:
            self.active_api_profile = ConfigManager.get_api_profile(self.config, target_profile_id_from_cli)
            if self.active_api_profile:
                if current_saved_profile_id != target_profile_id_from_cli:
                    self.config["current_api_profile_id"] = target_profile_id_from_cli
                    ConfigManager.save(self.config)
                return
            else:
                self.log_manager.error(f"CLIで指定された有効なはずのプロファイルID '{target_profile_id_from_cli}' がConfigManagerで見つかりませんでした。", context="SYSTEM_INIT_CRITICAL")

        elif len(available_profiles) == 1 and not ids_for_dialog_filter:
            self.active_api_profile = available_profiles[0]
            profile_id_to_save = self.active_api_profile.get("id")
            if current_saved_profile_id != profile_id_to_save:
                self.config["current_api_profile_id"] = profile_id_to_save
                ConfigManager.save(self.config)
            self.log_manager.info(f"単一のAPIプロファイル '{self.active_api_profile.get('name')}' を自動選択しました。", context="SYSTEM_INIT_AUTO")
        else:
            initial_dialog_selection_id = current_saved_profile_id
            if ids_for_dialog_filter:
                if not (current_saved_profile_id in ids_for_dialog_filter) and ids_for_dialog_filter:
                     initial_dialog_selection_id = ids_for_dialog_filter[0]
            
            profiles_for_dialog_display = [p for p in available_profiles if ids_for_dialog_filter is None or p.get("id") in ids_for_dialog_filter]
            if not profiles_for_dialog_display:
                self.log_manager.error("ダイアログに表示できる有効なAPIプロファイルがありませんでした。アプリを終了します。", context="SYSTEM_INIT_CRITICAL")
                QMessageBox.critical(None, "設定エラー", "選択可能なAPIプロファイルがありません。")
                sys.exit(1)

            dialog = ApiSelectionDialog(profiles_for_dialog_display, initial_dialog_selection_id, self)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_profile_id:
                selected_id = dialog.selected_profile_id
                self.active_api_profile = ConfigManager.get_api_profile(self.config, selected_id)
                if self.active_api_profile:
                    if current_saved_profile_id != selected_id:
                        self.config["current_api_profile_id"] = selected_id
                        ConfigManager.save(self.config)
                    self.log_manager.info(f"ユーザーがAPIプロファイル '{self.active_api_profile.get('name')}' を選択しました。", context="SYSTEM_INIT_DIALOG")
                else:
                    self.log_manager.error(f"ダイアログで選択されたプロファイルID '{selected_id}' が見つかりませんでした。アプリを終了します。", context="SYSTEM_INIT_CRITICAL")
                    QMessageBox.critical(None, "内部エラー", "選択されたプロファイルの読み込みに失敗しました。")
                    sys.exit(1)
            else:
                self.log_manager.warning("APIプロファイル選択がキャンセルされました。アプリケーションを終了します。", context="SYSTEM_INIT_DIALOG_CANCEL")
                sys.exit(0)

    def _initialize_core_components_based_on_profile(self):
        self.is_ocr_running = False
        self.processed_files_info: list[FileInfo] = []

        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget)

        if not self.active_api_profile:
            self.log_manager.critical("アクティブAPIプロファイルが未設定でコンポーネント初期化不可。", context="MAINWIN_LIFECYCLE_CRITICAL")
            return

        self.api_client = OCRApiClient(
            config=self.config,
            log_manager=self.log_manager,
            api_profile_schema=self.active_api_profile
        )
        self.file_scanner = FileScanner(self.log_manager, self.config)
        self.ocr_orchestrator = OcrOrchestrator(
            api_client=self.api_client,
            log_manager=self.log_manager,
            config=self.config,
            api_profile=self.active_api_profile
        )

        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self.perform_batch_list_view_update)
        self.input_folder_path = ""

    def _update_window_title(self):
        profile_name = "プロファイル未選択"
        if hasattr(self, 'active_api_profile') and self.active_api_profile and "name" in self.active_api_profile:
            profile_name = self.active_api_profile.get("name", "N/A")
        mode = self.config.get("api_execution_mode", "demo").upper()
        self.setWindowTitle(f"AI inside OCR Client Ver.{APP_VERSION} - {profile_name} ({mode} MODE)")

    def _connect_orchestrator_signals(self):
        if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator:
            self.ocr_orchestrator.ocr_process_started_signal.connect(self._handle_ocr_process_started_from_orchestrator)
            self.ocr_orchestrator.ocr_process_finished_signal.connect(self._handle_ocr_process_finished_from_orchestrator)
            self.ocr_orchestrator.original_file_status_update_signal.connect(self.on_original_file_status_update_from_worker)
            self.ocr_orchestrator.file_ocr_processed_signal.connect(self.on_file_ocr_processed)
            self.ocr_orchestrator.file_auto_csv_processed_signal.connect(self.on_file_auto_csv_processed)
            self.ocr_orchestrator.file_searchable_pdf_processed_signal.connect(self.on_file_searchable_pdf_processed)

            # ★★★ 仕分け用シグナルの接続を追加 ★★★
            self.ocr_orchestrator.sort_process_started_signal.connect(self.on_sort_process_started)
            self.ocr_orchestrator.sort_process_finished_signal.connect(self.on_sort_process_finished)

            self.ocr_orchestrator.request_ui_controls_update_signal.connect(self.update_ocr_controls)
            self.ocr_orchestrator.request_list_view_update_signal.connect(self._handle_request_list_view_update)

    def _handle_request_list_view_update(self, updated_file_list: List[FileInfo]):
        self.log_manager.debug("MainWindow: Received request to update ListView from orchestrator.", context="UI_UPDATE")
        self.processed_files_info = updated_file_list
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info, self.is_ocr_running)
        self.update_all_status_displays()

    def _setup_main_window_geometry(self):
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700})
        state_cfg = self.config.get("window_state", "normal")
        pos_cfg = self.config.get("window_position")
        self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try:
                screen = QApplication.primaryScreen()
                if screen:
                    screen_geometry = screen.geometry()
                    self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
                else:
                    self.move(100,100)
            except Exception as e:
                self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e)
                self.move(100, 100)
        else:
            self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized":
            self.showMaximized()

    def _setup_ui_elements(self):
        self._setup_central_widget_and_main_layout()
        self._setup_views_log_widget_and_splitter()
        self._setup_status_bar()
        self._setup_toolbars_and_folder_labels()

    def _setup_central_widget_and_main_layout(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.main_layout.setSpacing(0)

    def _setup_views_log_widget_and_splitter(self):
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.summary_view = SummaryView()
        self.summary_view.log_manager = self.log_manager
        self.list_view = ListView(self.processed_files_info)
        self.list_view.item_check_state_changed.connect(self.on_list_item_check_state_changed)
        self.list_view.table.itemSelectionChanged.connect(self.update_ocr_controls) # ★★★ この行を追加 ★★★
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
            QTextEdit { 
                font-family: Consolas, Meiryo, monospace; 
                font-size: 9pt; 
                border: 1px solid #D0D0D0; 
                margin: 0px; 
            }
        """)
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        log_layout_inner.addWidget(self.log_widget)
        self.splitter.addWidget(self.log_container)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        splitter_sizes = self.config.get("splitter_sizes")
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0:
            self.splitter.setSizes(splitter_sizes)
        else:
            default_height = self.height() if self.height() > 100 else 700
            initial_splitter_sizes = [int(default_height * 0.65), int(default_height * 0.35)]
            if sum(initial_splitter_sizes) == 0 and default_height > 0 :
                initial_splitter_sizes = [200,100]
            self.splitter.setSizes(initial_splitter_sizes)
        self.main_layout.addWidget(self.splitter)

    def _setup_status_bar(self):
        self.status_bar_frame = QFrame()
        self.status_bar_frame.setObjectName("StatusBarFrame")
        self.status_bar_frame.setFrameShape(QFrame.Shape.NoFrame)
        self.status_bar_frame.setStyleSheet("""
            QFrame#StatusBarFrame { background-color: #ECECEC; border-top: 1px solid #B0B0B0; min-height: 26px; max-height: 26px; }
            QLabel#StatusBarLabel { padding: 3px 0px; font-size: 8pt; border: none; }
        """)
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
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.input_folder_action = QAction("📂入力", self); self.input_folder_action.triggered.connect(self.select_input_folder); toolbar.addAction(self.input_folder_action)
        self.toggle_view_action = QAction("📑ビュー", self); self.toggle_view_action.triggered.connect(self.toggle_view); toolbar.addAction(self.toggle_view_action)
        self.option_action = QAction("⚙️設定", self); self.option_action.triggered.connect(self.show_option_dialog); toolbar.addAction(self.option_action)
        toolbar.addSeparator()
        self.start_ocr_action = QAction("▶️開始", self); self.start_ocr_action.triggered.connect(self.confirm_start_ocr); toolbar.addAction(self.start_ocr_action)
        self.resume_ocr_action = QAction("↪️再開", self); self.resume_ocr_action.setToolTip("未処理または失敗したファイルのOCR処理を再開します"); self.resume_ocr_action.triggered.connect(self.confirm_resume_ocr); toolbar.addAction(self.resume_ocr_action)
        self.stop_ocr_action = QAction("⏹️中止", self); self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr); toolbar.addAction(self.stop_ocr_action)

        self.rescan_action = QAction("🔄再スキャン", self)
        self.rescan_action.triggered.connect(self.confirm_rescan_ui)
        toolbar.addAction(self.rescan_action)

        toolbar.addSeparator()

        # ★★★ ここから「仕分け実行」ボタンを追加 ★★★
        self.start_sort_action = QAction("📊仕分け", self)
        self.start_sort_action.setToolTip("選択したファイルで仕分け処理を開始します。")
        self.start_sort_action.triggered.connect(self.on_start_sort_clicked)
        toolbar.addAction(self.start_sort_action)
        toolbar.addSeparator()
        # ★★★ ここまで追加 ★★★

        self.download_csv_action = QAction("💾CSV", self)
        self.download_csv_action.setToolTip("選択した完了済みファイルのOCR結果をCSV形式でダウンロードします。")
        self.download_csv_action.triggered.connect(self.on_download_csv_clicked)
        toolbar.addAction(self.download_csv_action)
        
        toolbar.addSeparator()
        # ★★★ ここまで変更 ★★★

        self.log_toggle_action = QAction("📄ログ表示", self); self.log_toggle_action.triggered.connect(self.toggle_log_display); toolbar.addAction(self.log_toggle_action)
        self.clear_log_action = QAction("🗑️ログクリア", self); self.clear_log_action.triggered.connect(self.clear_log_display); toolbar.addAction(self.clear_log_action)
        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); toolbar.addWidget(spacer)
        self.api_mode_toggle_button = QPushButton(); self.api_mode_toggle_button.setCheckable(False); self.api_mode_toggle_button.clicked.connect(self._toggle_api_mode); self.api_mode_toggle_button.setMinimumWidth(120)

        # ★★★ ここを変更 ★★★
        # paddingを元に戻し、margin を上下に 2px ずつ追加します
        self.api_mode_toggle_button.setStyleSheet("""
            QPushButton { 
                padding: 4px 8px; 
                margin-top: 2px;
                margin-bottom: 2px;
                border: 1px solid #8f8f8f; 
                border-radius: 4px; 
                font-weight: bold; 
            }
            QPushButton[apiMode="live"] { background-color: #e6fff2; color: #006400; }
            QPushButton[apiMode="demo"] { background-color: #e6f7ff; color: #005f9e; }
            QPushButton:disabled { background-color: #f0f0f0; color: #a0a0a0; }
        """)
        # ★★★ ここまで変更 ★★★

        toolbar.addWidget(self.api_mode_toggle_button)
        right_spacer = QWidget(); right_spacer.setFixedWidth(10); toolbar.addWidget(right_spacer)
        folder_label_toolbar = QToolBar("Folder Paths Toolbar"); folder_label_toolbar.setMovable(False); folder_label_widget = QWidget(); folder_label_layout = QFormLayout(folder_label_widget); folder_label_layout.setContentsMargins(5,5,5,5); folder_label_layout.setSpacing(3)
        self.input_folder_button = QPushButton(); self.input_folder_button.setStyleSheet("QPushButton { border: none; background: transparent; text-align: left; padding: 0px; margin: 0px; } QPushButton:hover { text-decoration: underline; color: blue; }"); self.input_folder_button.setFlat(True); self.input_folder_button.setCursor(Qt.CursorShape.PointingHandCursor); self.input_folder_button.clicked.connect(self.open_input_folder_in_explorer); folder_label_layout.addRow("入力フォルダ:", self.input_folder_button); folder_label_toolbar.addWidget(folder_label_widget); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar); self.insertToolBarBreak(folder_label_toolbar)

    def _update_api_mode_toggle_button_display(self):
        if not hasattr(self, 'api_mode_toggle_button'): return
        current_mode = self.config.get("api_execution_mode", "demo")
        if current_mode == "live": self.api_mode_toggle_button.setText("🔴 Live モード"); self.api_mode_toggle_button.setToolTip("現在 Live モードです。クリックして Demo モードに切り替えます。"); self.api_mode_toggle_button.setProperty("apiMode", "live")
        else: self.api_mode_toggle_button.setText("🔵 Demo モード"); self.api_mode_toggle_button.setToolTip("現在 Demo モードです。クリックして Live モードに切り替えます。"); self.api_mode_toggle_button.setProperty("apiMode", "demo")
        self.api_mode_toggle_button.style().unpolish(self.api_mode_toggle_button); self.api_mode_toggle_button.style().polish(self.api_mode_toggle_button); self.api_mode_toggle_button.update()

    def _toggle_api_mode(self):
        if self.is_ocr_running: QMessageBox.warning(self, "モード変更不可", "OCR処理の実行中はAPIモードを変更できません。"); return
        current_mode = self.config.get("api_execution_mode", "demo"); new_mode = "live" if current_mode == "demo" else "demo"
        if new_mode == "live":
            active_api_key = ConfigManager.get_active_api_key(self.config)
            if not active_api_key or not active_api_key.strip():
                active_profile_name = self.active_api_profile.get("name", "不明なプロファイル") if self.active_api_profile else "不明なプロファイル"
                QMessageBox.warning(self, "APIキー未設定", f"Liveモードに切り替えるには、まず「⚙️設定」から\n現在アクティブなプロファイル「{active_profile_name}」用のAPIキーを設定してください。"); return
        msg_box = QMessageBox(self); msg_box.setWindowTitle("APIモード変更の確認"); msg_box.setText(f"API実行モードを「{current_mode.upper()}」から「{new_mode.upper()}」に変更しますか？"); msg_box.setInformativeText("変更を保存し、関連コンポーネントに適用します。"); msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No); msg_box.setDefaultButton(QMessageBox.StandardButton.No); msg_box.setIcon(QMessageBox.Icon.Question)
        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            self.config["api_execution_mode"] = new_mode; ConfigManager.save(self.config); self.log_manager.info(f"API execution mode changed to: {new_mode.upper()}", context="CONFIG_CHANGE_MAIN")
            if hasattr(self, 'api_client') and self.api_client: self.api_client.update_config(self.config, self.active_api_profile)
            if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator: self.ocr_orchestrator.update_config(self.config, self.active_api_profile)
            self._update_window_title(); self._update_api_mode_toggle_button_display(); self.update_ocr_controls(); self.log_manager.info(f"MainWindow components updated for {new_mode.upper()} mode.", context="CONFIG_CHANGE_MAIN")

    def _update_folder_display(self):
        if hasattr(self, 'input_folder_button'): display_path = self.input_folder_path or "未選択"; self.input_folder_button.setText(display_path); self.input_folder_button.setToolTip(self.input_folder_path if self.input_folder_path else "入力フォルダが選択されていません")

    def _load_previous_state_and_perform_initial_scan(self):
        self.input_folder_path = self.config.get("last_target_dir", ""); self._update_folder_display()
        if self.input_folder_path and os.path.isdir(self.input_folder_path): self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT"); self.perform_initial_scan()
        elif self.input_folder_path: self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT"); self.input_folder_path = ""; self._update_folder_display(); self._clear_and_update_file_list_display()
        else: self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT"); self._update_folder_display(); self._clear_and_update_file_list_display()
        if hasattr(self, 'api_mode_toggle_button'): self._update_api_mode_toggle_button_display()

    def _clear_and_update_file_list_display(self):
        self.processed_files_info = [];
        if hasattr(self, 'list_view'): self.list_view.update_files(self.processed_files_info, self.is_ocr_running)
        if hasattr(self, 'summary_view'): self.summary_view.reset_summary()
        self.update_all_status_displays()

    def _restore_view_and_log_state(self):
        self.current_view = self.config.get("current_view", 0)
        if hasattr(self, 'stack'): self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True)
        if hasattr(self, 'log_container'): self.log_container.setVisible(log_visible)

    def _update_all_ui_controls_state(self): self.update_ocr_controls()

    def _handle_ocr_process_started_from_orchestrator(self, num_files_to_process: int, updated_file_list: List[FileInfo]):
        self.log_manager.info(f"MainWindow: OCR process started signal received for {num_files_to_process} files.", context="OCR_FLOW_MAIN"); self.is_ocr_running = True; self.processed_files_info = updated_file_list
        if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info, self.is_ocr_running)
        if hasattr(self.summary_view, 'start_processing'): self.summary_view.start_processing(num_files_to_process)
        self.update_status_bar(); self.update_ocr_controls()

    def _handle_ocr_process_finished_from_orchestrator(self, was_interrupted: bool, fatal_error_info: Optional[dict] = None):
        self.log_manager.info(f"MainWindow: OCR process finished signal received. Interrupted: {was_interrupted}, FatalError: {fatal_error_info}", context="OCR_FLOW_MAIN"); self.is_ocr_running = False; reason = ""
        if fatal_error_info and isinstance(fatal_error_info, dict): reason = fatal_error_info.get("message", "不明な致命的エラー"); self.log_manager.error(f"MainWindow: OCR processing stopped due to a fatal error from worker: {reason}", context="OCR_FLOW_MAIN")
        elif was_interrupted: reason = "ユーザーによる中止"; self.log_manager.info(f"MainWindow: OCR processing was interrupted by user (from orchestrator signal).", context="OCR_FLOW_MAIN")
        if was_interrupted or fatal_error_info:
            output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both"); json_interrupt_status = "中断" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"; pdf_interrupt_status = "中断" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
            for file_info in self.processed_files_info:
                if file_info.ocr_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING] or (file_info.status == OCR_STATUS_PROCESSING and file_info.ocr_engine_status == OCR_STATUS_PROCESSING):
                    file_info.ocr_engine_status = OCR_STATUS_FAILED; file_info.status = "中断" if was_interrupted else "エラー(停止)"; file_info.ocr_result_summary = f"(処理が中止/停止されました: {reason})" if reason else "(処理が中止/停止されました)"; file_info.json_status = json_interrupt_status; file_info.searchable_pdf_status = pdf_interrupt_status
        self.perform_batch_list_view_update()
        if hasattr(self, 'list_view'): self.list_view.set_checkboxes_enabled(True)
        self.update_ocr_controls()

        # ★★★ ここからCSVエクスポートの呼び出し処理を追加 ★★★
        if not was_interrupted and not fatal_error_info:
            # 正常終了した場合のみCSVエクスポートを試みる
            try:
                self.ocr_orchestrator.export_results_to_csv(self.processed_files_info, self.input_folder_path)
            except Exception as e:
                self.log_manager.error(f"CSVエクスポート処理中に予期せぬエラーが発生しました: {e}", context="CSV_EXPORT_ERROR", exc_info=True)
                QMessageBox.critical(self, "CSVエクスポートエラー", f"CSVファイルのエクスポートに失敗しました。\n詳細はログを確認してください。\n\nエラー: {e}")
        # ★★★ ここまで追加 ★★★

        final_message = "全てのファイルのOCR処理が完了しました。"
        if fatal_error_info and isinstance(fatal_error_info, dict):
            final_message = f"OCR処理がエラーにより停止しました。\n理由: {fatal_error_info.get('message', '不明なエラー')}"
            if fatal_error_info.get("code") in ["NOT_IMPLEMENTED_LIVE_API", "NOT_IMPLEMENTED_LIVE_API_PDF", "NOT_IMPLEMENTED_API_CALL", "NOT_IMPLEMENTED_API_CALL_PDF"]: final_message += "\n\nLiveモードでのAPI呼び出しは現在実装されていません。\nDemoモードで実行するか、APIクライアントの実装をご確認ください。"
            QMessageBox.critical(self, "処理停止 (致命的エラー)", final_message)
        elif was_interrupted: QMessageBox.information(self, "処理終了", "OCR処理が中止されました。")
        else: QMessageBox.information(self, "処理終了", final_message)

    def update_status_bar(self):
        total_list_items = len(self.processed_files_info); selected_for_processing_count = 0; ocr_success_count = self.summary_view.ocr_completed_count if hasattr(self, 'summary_view') else 0; ocr_error_count = self.summary_view.ocr_error_count if hasattr(self, 'summary_view') else 0
        for file_info in self.processed_files_info:
            if file_info.is_checked and file_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT: selected_for_processing_count += 1
        if hasattr(self, 'status_total_list_label'): self.status_total_list_label.setText(f"リスト総数: {total_list_items}"); self.status_selected_files_label.setText(f"選択中: {selected_for_processing_count}"); self.status_success_files_label.setText(f"成功: {ocr_success_count}"); self.status_error_files_label.setText(f"エラー: {ocr_error_count}")

    def update_all_status_displays(self):
        size_skipped_count = 0; checked_and_processable_for_summary = 0
        for file_info in self.processed_files_info:
            if file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT: size_skipped_count += 1
            elif file_info.is_checked: checked_and_processable_for_summary += 1
        if hasattr(self, 'summary_view'): self.summary_view.update_summary_counts(total_scanned=len(self.processed_files_info), total_ocr_target=checked_and_processable_for_summary, skipped_size=size_skipped_count)
        self.update_status_bar()

    def on_list_item_check_state_changed(self, row_index, is_checked):
        if 0 <= row_index < len(self.processed_files_info):
            self.processed_files_info[row_index].is_checked = is_checked; self.log_manager.debug(f"File '{self.processed_files_info[row_index].name}' check state in data model changed to: {is_checked}", context="UI_EVENT"); self.update_all_status_displays(); self.update_ocr_controls()
    
    def perform_initial_scan(self):
        self.log_manager.info(f"スキャン開始: {self.input_folder_path}", context="FILE_SCAN_MAIN"); self.processed_files_info = []; self.list_view.update_files([], self.is_ocr_running) if hasattr(self, 'list_view') else None
        collected_files_paths, max_files_info, depth_limited_folders = self.file_scanner.scan_folder(self.input_folder_path)
        if collected_files_paths:
            self.processed_files_info = self.file_scanner.create_initial_file_list(collected_files_paths, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_NOT_PROCESSED)
            processable_count = sum(1 for item in self.processed_files_info if item.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT); self.log_manager.info(f"MainWindow: Scan completed. {len(self.processed_files_info)} files loaded ({processable_count} processable).", context="FILE_SCAN_MAIN")
        else: self.log_manager.info("MainWindow: Scan completed. No files found or collected.", context="FILE_SCAN_MAIN")
        if hasattr(self, 'list_view') and self.list_view: self.list_view.update_files(self.processed_files_info, self.is_ocr_running)
        if max_files_info or depth_limited_folders:
            warning_messages = []
            if max_files_info: warning_messages.append(f"最大処理ファイル数 ({max_files_info['limit']}件) に達したため、フォルダ「{max_files_info['last_scanned_folder']}」以降の一部のファイルは読み込まれていません。")
            if depth_limited_folders: folders_str = ", ".join([os.path.basename(f) for f in depth_limited_folders[:3]]); folders_str += f" など、計{len(depth_limited_folders)}フォルダ" if len(depth_limited_folders) > 3 else ""; warning_messages.append(f"再帰検索の深さ制限により、サブフォルダ「{folders_str}」以降は検索されていません。")
            QMessageBox.warning(self, "スキャン結果の注意", "\n\n".join(warning_messages))
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        self.update_all_status_displays(); self.update_ocr_controls()    

    def append_log_message_to_widget(self, level, message):
        # ★★★ ここから変更 ★★★
        if hasattr(self, 'log_widget') and self.log_widget:
            # 設定から現在のログ表示レベルを取得
            log_settings = self.config.get("log_settings", {})
            
            # 設定に基づいて表示するかどうかを判断
            if level == LogLevel.INFO and not log_settings.get("log_level_info_enabled", True):
                return # INFO非表示設定なら、ここで処理を終了
            if level == LogLevel.WARNING and not log_settings.get("log_level_warning_enabled", True):
                return # WARNING非表示設定なら、ここで処理を終了
            if level == LogLevel.DEBUG and not log_settings.get("log_level_debug_enabled", False):
                return # DEBUG非表示設定なら、ここで処理を終了
            # ERRORは常に表示するため、フィルタリングしない

            # 色付けと表示処理
            color_map = {
                LogLevel.ERROR: "red",
                LogLevel.WARNING: "orange",
                LogLevel.DEBUG: "gray",
                LogLevel.INFO: "black"
            }
            color = color_map.get(level, "black") # 未知のレベルは黒で表示

            self.log_widget.append(f'<font color="{color}">{message}</font>')
            self.log_widget.ensureCursorVisible()
        # ★★★ ここまで変更 ★★★
    def select_input_folder(self):
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION"); last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.log_manager.info(f"Input folder selected by user: {folder}", context="UI_EVENT")
            if folder != self.input_folder_path or not self.processed_files_info: self.input_folder_path = folder; self._update_folder_display(); self.log_manager.info(f"Performing rescan for newly selected folder: {folder}", context="UI_EVENT"); self.perform_rescan()
            else: self.log_manager.info("Selected folder is the same as current and list is not empty. No rescan forced.", context="UI_EVENT")
        else: self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")
        self._update_folder_display()

    def open_input_folder_in_explorer(self):
        self.log_manager.debug(f"Attempting to open folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            try:
                if platform.system() == "Windows": os.startfile(os.path.normpath(self.input_folder_path))
                elif platform.system() == "Darwin": subprocess.run(['open', self.input_folder_path], check=True)
                else: subprocess.run(['xdg-open', self.input_folder_path], check=True)
                self.log_manager.info(f"Successfully opened folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
            except Exception as e: self.log_manager.error(f"Failed to open folder '{self.input_folder_path}'. Error: {e}", context="UI_ACTION_OPEN_FOLDER_ERROR", exc_info=True); QMessageBox.warning(self, "フォルダを開けません", f"フォルダ '{self.input_folder_path}' を開けませんでした。\nエラー: {e}")
        else: self.log_manager.warning(f"Cannot open folder: Path is invalid or not set. Path: '{self.input_folder_path}'", context="UI_ACTION_OPEN_FOLDER_INVALID"); QMessageBox.information(self, "フォルダ情報なし", "入力フォルダが選択されていないか、無効なパスです。")

    def toggle_view(self):
        if hasattr(self, 'stack'): self.current_view = 1 - self.stack.currentIndex(); self.stack.setCurrentIndex(self.current_view); self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")

    def toggle_log_display(self):
        if hasattr(self, 'log_container'): visible = self.log_container.isVisible(); self.log_container.setVisible(not visible); self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION"); self.log_toggle_action.setText("📄ログ非表示" if not visible else "📄ログ表示")

    def show_option_dialog(self):
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION"); active_profile_id = self.config.get("current_api_profile_id"); options_schema = ConfigManager.get_active_api_options_schema(self.config); current_option_values = ConfigManager.get_active_api_options_values(self.config)
        if options_schema is None: QMessageBox.warning(self, "設定エラー", f"現在アクティブなAPIプロファイル '{active_profile_id}' のオプション定義の取得に失敗しました。\n設定ファイルが破損しているか、プロファイル定義に問題がある可能性があります。"); self.log_manager.error(f"オプションスキーマの取得に失敗 (None)。Profile ID: {active_profile_id}", context="CONFIG_ERROR"); return
        if current_option_values is None: self.log_manager.warning(f"アクティブプロファイル '{active_profile_id}' のオプション値(current_option_values)が取得できませんでした。空のオプションでダイアログを開きます。", context="CONFIG_WARN"); current_option_values = {}
        dialog = OptionDialog(
            options_schema=options_schema,
            current_option_values=current_option_values,
            global_config=self.config,
            api_profile=self.active_api_profile,
            api_client=self.api_client, # ★★★ この引数を追加 ★★★
            parent=self
        )
        if dialog.exec():
            updated_profile_specific_options, updated_global_config = dialog.get_saved_settings()
            if active_profile_id and updated_profile_specific_options is not None: self.config["options_values_by_profile"][active_profile_id] = updated_profile_specific_options
            if updated_global_config is not None:
                if "file_actions" in updated_global_config: self.config["file_actions"] = updated_global_config["file_actions"]
                if "log_settings" in updated_global_config: self.config["log_settings"] = updated_global_config["log_settings"]
            ConfigManager.save(self.config); self.log_manager.info("Options saved.", context="CONFIG_EVENT")
            self.active_api_profile = ConfigManager.get_active_api_profile(self.config); self.api_client.update_config(self.config, self.active_api_profile); self.ocr_orchestrator.update_config(self.config, self.active_api_profile); self.file_scanner.config = self.config
            self._update_window_title(); self._update_api_mode_toggle_button_display()
            self.log_manager.info(f"Settings changed. Re-evaluating file statuses based on new options.", context="CONFIG_EVENT")
            new_upload_max_mb = ConfigManager.get_active_api_options_values(self.config).get("upload_max_size_mb", 60); new_upload_max_bytes = new_upload_max_mb * 1024 * 1024; new_file_actions_cfg = self.config.get("file_actions", {}); new_output_format = new_file_actions_cfg.get("output_format", "both")
            default_json_status = "-" if new_output_format in ["json_only", "both"] else "作成しない(設定)"; default_pdf_status = "-" if new_output_format in ["pdf_only", "both"] else "作成しない(設定)"
            items_updated = False
            for file_info in self.processed_files_info:
                prev_engine_status = file_info.ocr_engine_status; prev_checked = file_info.is_checked; orig_status = file_info.status; orig_json = file_info.json_status; orig_pdf = file_info.searchable_pdf_status
                is_now_skipped = file_info.size > new_upload_max_bytes
                if is_now_skipped:
                    if file_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT: file_info.status = "スキップ(サイズ上限)"; file_info.ocr_engine_status = OCR_STATUS_SKIPPED_SIZE_LIMIT; file_info.ocr_result_summary = f"ファイルサイズが上限 ({new_upload_max_mb}MB) を超過"; file_info.json_status = "スキップ"; file_info.searchable_pdf_status = "スキップ"; file_info.is_checked = False
                else: 
                    if file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT: file_info.status = "待機中"; file_info.ocr_engine_status = OCR_STATUS_NOT_PROCESSED; file_info.ocr_result_summary = ""; file_info.is_checked = True
                    if file_info.ocr_engine_status == OCR_STATUS_NOT_PROCESSED: file_info.json_status = default_json_status; file_info.searchable_pdf_status = default_pdf_status
                if (file_info.ocr_engine_status != prev_engine_status or file_info.status != orig_status or file_info.json_status != orig_json or file_info.searchable_pdf_status != orig_pdf or file_info.is_checked != prev_checked): items_updated = True
            if items_updated: self.list_view.update_files(self.processed_files_info, self.is_ocr_running)
            self.update_all_status_displays(); self.update_ocr_controls()
        else: self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

    def confirm_start_ocr(self):
        if hasattr(self, 'ocr_orchestrator'): sorted_list_to_process = self.list_view.get_sorted_file_info_list(); self.ocr_orchestrator.confirm_and_start_ocr(sorted_list_to_process, self.input_folder_path, self)

    def confirm_resume_ocr(self):
        if hasattr(self, 'ocr_orchestrator'): sorted_list_to_process = self.list_view.get_sorted_file_info_list(); self.ocr_orchestrator.confirm_and_resume_ocr(sorted_list_to_process, self.input_folder_path, self)

    def confirm_stop_ocr(self):
        if hasattr(self, 'ocr_orchestrator'): self.ocr_orchestrator.confirm_and_stop_ocr(self)

    def on_start_sort_clicked(self):
        """仕分け実行ボタンがクリックされたときの処理"""
        if self.is_ocr_running:
            QMessageBox.warning(self, "処理中", "現在別の処理が実行中です。")
            return

        files_to_process = [item for item in self.processed_files_info if item.is_checked]
        if not files_to_process:
            QMessageBox.information(self, "対象ファイルなし", "仕分け対象として選択（チェック）されているファイルがありません。")
            return

        dialog = SortConfigDialog(self)
        if dialog.exec():
            sort_config_id = dialog.get_sort_config_id()
            
            # ★★★ ここから確認ダイアログを追加 ★★★
            reply = QMessageBox.question(self, "仕分け実行の確認",
                                        f"{len(files_to_process)} 件のファイルで仕分け処理を開始します。\n\n"
                                        f"仕分けルールID: {sort_config_id}\n\n"
                                        "よろしいですか？",
                                        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                                        QMessageBox.StandardButton.Ok)

            if reply == QMessageBox.StandardButton.Ok:
                self.log_manager.info(f"仕分け処理を開始します。SortConfigID: {sort_config_id}", context="SORT_FLOW")
                self.ocr_orchestrator.confirm_and_start_sort(files_to_process, sort_config_id, self.input_folder_path)
            else:
                self.log_manager.info("ユーザーによって仕分け処理がキャンセルされました。", context="SORT_FLOW")
            # ★★★ ここまで修正 ★★★

    def on_download_csv_clicked(self):
        """CSVダウンロードボタンがクリックされたときの処理"""
        if not hasattr(self, 'list_view') or not self.list_view.table.selectedItems():
            return

        selected_row = self.list_view.table.currentRow()
        if not (0 <= selected_row < len(self.processed_files_info)):
            return
            
        file_info = self.processed_files_info[selected_row]

        # 念のため再度条件をチェック
        if not (file_info.ocr_engine_status == OCR_STATUS_COMPLETED and file_info.job_id):
            QMessageBox.information(self, "ダウンロード不可", "このファイルのCSVはダウンロードできません。\n（処理が完了していないか、ジョブIDがありません）")
            return
            
        # ファイル保存ダイアログを開く
        default_filename = f"{os.path.splitext(file_info.name)[0]}.csv"
        save_path, _ = QFileDialog.getSaveFileName(self, "CSVを保存", os.path.join(self.input_folder_path, default_filename), "CSVファイル (*.csv)")

        if not save_path:
            self.log_manager.info("CSV保存がユーザーによってキャンセルされました。", context="CSV_DOWNLOAD")
            return

        # APIを呼び出してCSVデータを取得
        self.log_manager.info(f"'{file_info.name}' のCSVダウンロードを開始します (Unit ID: {file_info.job_id})", context="CSV_DOWNLOAD")
        csv_data, error = self.api_client.download_standard_csv(file_info.job_id)

        if error:
            self.log_manager.error(f"CSVダウンロードAPIエラー: {error}", context="CSV_DOWNLOAD")
            QMessageBox.critical(self, "ダウンロード失敗", f"CSVのダウンロードに失敗しました。\n\nエラー: {error.get('message', '詳細不明')}")
            return

        # ファイルに書き込み
        try:
            with open(save_path, 'wb') as f:
                f.write(csv_data)
            self.log_manager.info(f"CSVを正常に保存しました: {save_path}", context="CSV_DOWNLOAD")
            QMessageBox.information(self, "保存完了", f"CSVファイルを以下の場所に保存しました。\n\n{save_path}")
        except IOError as e:
            self.log_manager.error(f"CSVファイルの書き込みに失敗: {e}", context="CSV_DOWNLOAD")
            QMessageBox.critical(self, "ファイル保存エラー", f"ファイルの書き込みに失敗しました。\n\nエラー: {e}")

    def on_original_file_status_update_from_worker(self, original_file_path, status_message):
        target_file_info = next((item for item in self.processed_files_info if item.path == original_file_path), None)
        if target_file_info:
            self.log_manager.debug(f"UI Update for '{target_file_info.name}': {status_message}", context="UI_STATUS_UPDATE"); target_file_info.status = status_message
            if status_message == OCR_STATUS_SPLITTING: target_file_info.ocr_engine_status = OCR_STATUS_SPLITTING
            elif OCR_STATUS_PART_PROCESSING in status_message: target_file_info.ocr_engine_status = OCR_STATUS_PART_PROCESSING
            elif status_message == OCR_STATUS_MERGING: target_file_info.ocr_engine_status = OCR_STATUS_MERGING
            elif status_message == OCR_STATUS_PROCESSING and target_file_info.ocr_engine_status == OCR_STATUS_NOT_PROCESSED : target_file_info.ocr_engine_status = OCR_STATUS_PROCESSING
            if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)
        else: self.log_manager.warning(f"Status update received for unknown file: {original_file_path}", context="UI_STATUS_UPDATE_WARN")

    def on_file_ocr_processed(self, original_file_main_idx, original_file_path, ocr_result_data_for_original, ocr_error_info_for_original, json_save_status_for_original, job_id: Optional[str]):
        self.log_manager.debug(f"Original File OCR stage processed (MainWin): {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Success={not ocr_error_info_for_original}, JSON Status='{json_save_status_for_original}'", context="CALLBACK_OCR_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx}. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return
            
        target_file_info = self.processed_files_info[original_file_main_idx]

        # ★★★ ここから修正 ★★★
        # シグナルから直接渡されたjob_idを保存する
        if job_id:
            target_file_info.job_id = str(job_id)
            self.log_manager.debug(f"Job ID '{job_id}' saved for file '{target_file_info.name}'.", context="JOB_ID_STORE")
        # ★★★ ここまで修正 ★★★
                
        if ocr_error_info_for_original and isinstance(ocr_error_info_for_original, dict):
            target_file_info.status = "OCR失敗"
            target_file_info.ocr_engine_status = OCR_STATUS_FAILED
            err_msg = ocr_error_info_for_original.get('message', '不明なOCRエラー')
            err_code = ocr_error_info_for_original.get('code', '')
            # (以降のコードは変更ありません)
            err_detail = ocr_error_info_for_original.get('detail', '')
            target_file_info.ocr_result_summary = f"エラー: {err_msg}" + (f" (コード: {err_code})" if err_code else "")
            if err_code not in ["USER_INTERRUPT", "NOT_IMPLEMENTED_LIVE_API", "NOT_IMPLEMENTED_API_CALL", "FATAL_ERROR_STOP", "PART_PROCESSING_ERROR", "DXSUITE_REGISTER_HTTP_ERROR_NON_JSON", "DXSUITE_GETRESULT_HTTP_ERROR_NON_JSON", "DXSUITE_REGISTER_REQUEST_FAIL", "DXSUITE_GETRESULT_REQUEST_FAIL", "DXSUITE_REGISTER_UNEXPECTED_ERROR", "DXSUITE_GETRESULT_UNEXPECTED_ERROR", "DXSUITE_BASE_URI_NOT_CONFIGURED"] and not ("DXSUITE_API_" in err_code):
                 QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})", f"ファイル「{target_file_info.name}」のOCR処理中にエラーが発生しました。\n\nメッセージ: {err_msg}\nコード: {err_code}\n詳細: {err_detail if err_detail else 'N/A'}\n\nログファイルをご確認ください。")
        elif ocr_result_data_for_original:
            target_file_info.status = "OCR成功"
            target_file_info.ocr_engine_status = OCR_STATUS_COMPLETED
            fulltext = ""
            if isinstance(ocr_result_data_for_original, dict):
                if ocr_result_data_for_original.get("status") == "ocr_registered":
                    fulltext = f"(登録成功 Job ID: {target_file_info.job_id or 'N/A'})"
                    target_file_info.status = "OCR登録済 (結果待機中)"
                    target_file_info.ocr_engine_status = OCR_STATUS_PROCESSING
                elif ocr_result_data_for_original.get("status") == "done":
                    results_list = ocr_result_data_for_original.get("results", [])
                    fulltext = " ".join(filter(None, [page.get("fulltext", "") for page in (results_list[0].get("pages") if results_list and isinstance(results_list, list) and results_list[0].get("pages") else [])])) if results_list else "結果解析エラー(DX Suite)"
                elif "dataItems" in ocr_result_data_for_original:
                    num_items = len(ocr_result_data_for_original.get("dataItems", []))
                    fulltext = f"成功 ({num_items}項目)"
                elif "detail" in ocr_result_data_for_original:
                    fulltext = ocr_result_data_for_original["detail"]
                elif "message" in ocr_result_data_for_original:
                    fulltext = ocr_result_data_for_original["message"]
                else:
                    fulltext_parts = [ocr_result_data_for_original.get("fulltext", ""), (ocr_result_data_for_original.get("result", {}) or {}).get("fulltext", ""), (ocr_result_data_for_original.get("result", {}) or {}).get("aGroupingFulltext", "")]
                    fulltext = " / ".join(filter(None, fulltext_parts))
            elif isinstance(ocr_result_data_for_original, list) and ocr_result_data_for_original:
                try:
                    first_page_res = ocr_result_data_for_original[0].get("result", {})
                    fulltext_parts = [first_page_res.get("fulltext", ""), first_page_res.get("aGroupingFulltext", "")]
                    fulltext = " / ".join(filter(None, fulltext_parts))
                except Exception:
                    fulltext = "結果解析エラー(集約)"
            else:
                fulltext = "OCR結果あり(形式不明)"
            target_file_info.ocr_result_summary = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
        else:
            target_file_info.status = "OCR状態不明"
            target_file_info.ocr_engine_status = OCR_STATUS_FAILED
            target_file_info.ocr_result_summary = "APIレスポンスなし(OCR)"
            QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})", f"ファイル「{target_file_info.name}」のOCR処理でAPIから有効な応答がありませんでした。")
        
        if isinstance(json_save_status_for_original, str):
            target_file_info.json_status = json_save_status_for_original
        elif ocr_error_info_for_original:
            target_file_info.json_status = "エラー(OCR失敗)"
            
        output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both")
        if output_format_cfg == "json_only":
            if target_file_info.ocr_engine_status == OCR_STATUS_COMPLETED:
                if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=True)
                target_file_info.status = "完了"
            elif target_file_info.ocr_engine_status == OCR_STATUS_FAILED:
                if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=False)
            self.update_status_bar()
            
        if not self.update_timer.isActive():
            self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_file_searchable_pdf_processed(self, original_file_main_idx, original_file_path, pdf_final_path, pdf_error_info):
        self.log_manager.debug(f"Original File Searchable PDF processed: {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Path={pdf_final_path}, Error={pdf_error_info}", context="CALLBACK_PDF_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)): self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx}. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR"); return
        target_file_info = self.processed_files_info[original_file_main_idx]; output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both"); ocr_engine_status_before_pdf = target_file_info.ocr_engine_status; pdf_stage_final_success = False
        if output_format_cfg == "json_only": target_file_info.searchable_pdf_status = "作成しない(設定)"
        elif pdf_final_path and not pdf_error_info and os.path.exists(pdf_final_path): target_file_info.searchable_pdf_status = "PDF作成成功"; pdf_stage_final_success = True; target_file_info.status = "完了" if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED else target_file_info.status
        elif pdf_error_info and isinstance(pdf_error_info, dict):
            error_msg = pdf_error_info.get('message', 'PDF作成不明エラー'); error_code = pdf_error_info.get('code', ''); err_detail = pdf_error_info.get('detail', '')
            target_file_info.searchable_pdf_status = f"PDFエラー: {error_msg}" + (f" (コード: {error_code})" if error_code else "")
            if error_code == "PARTS_COPIED_SUCCESS": pdf_stage_final_success = True; target_file_info.status = "完了" if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED else target_file_info.status
            elif error_code in ["PARTS_COPIED_PARTIAL", "PARTS_COPY_ERROR", "NO_PARTS_TO_COPY"] and ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED: target_file_info.status = "部品PDFエラー"
            elif not ("作成対象外" in error_msg or "作成しない" in error_msg or "部品PDFは結合されません(設定)" in error_msg or "PDF_NOT_REQUESTED" == error_code):
                if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED:
                    target_file_info.status = "PDF作成失敗"
                    if target_file_info.ocr_result_summary and "エラー" not in target_file_info.ocr_result_summary and "部品のOCR完了" not in target_file_info.ocr_result_summary and "登録成功 Job ID" not in target_file_info.ocr_result_summary and "PDFエラー" not in target_file_info.ocr_result_summary: target_file_info.ocr_result_summary += f" (PDFエラー: {error_msg})"
                    elif not target_file_info.ocr_result_summary: target_file_info.ocr_result_summary = f"PDFエラー: {error_msg}"
                popup_exclusions_pdf = ["USER_INTERRUPT_PDF", "PDF_NOT_REQUESTED", "PARTS_COPIED_SUCCESS", "NO_PARTS_TO_COPY", "PDF_CREATION_FAIL_DUE_TO_OCR_ERROR", "FATAL_ERROR_STOP_PDF", "NOT_IMPLEMENTED_API_CALL_PDF", "NOT_IMPLEMENTED_API_CALL_DX_SPDF"]
                if error_code not in popup_exclusions_pdf: QMessageBox.warning(self, f"PDF処理エラー ({target_file_info.name})", f"ファイル「{target_file_info.name}」のPDF処理中にエラーが発生しました。\n\nメッセージ: {error_msg}\nコード: {error_code}\n詳細: {err_detail or 'N/A'}\n\nログファイルをご確認ください。")
        elif ocr_engine_status_before_pdf == OCR_STATUS_FAILED: target_file_info.searchable_pdf_status = "対象外(OCR失敗)"
        elif output_format_cfg in ["pdf_only", "both"]: target_file_info.searchable_pdf_status = "PDF状態不明"; target_file_info.status = "PDF状態不明" if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED else target_file_info.status
        else: target_file_info.searchable_pdf_status = "-"
        if output_format_cfg != "json_only":
            is_overall_success = (ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED and pdf_stage_final_success)
            if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=is_overall_success)
            self.update_status_bar()
        if not self.update_timer.isActive(): self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_all_files_processed(self, was_interrupted_by_orchestrator: bool, fatal_error_info: Optional[dict] = None):
        self._handle_ocr_process_finished_from_orchestrator(was_interrupted_by_orchestrator, fatal_error_info)

    def handle_ocr_interruption_ui_update(self):
        self.log_manager.info("MainWindow: Handling UI update for OCR interruption.", context="UI_UPDATE_INTERRUPT")
        for file_info in self.processed_files_info:
            if file_info.ocr_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING]: file_info.ocr_engine_status = OCR_STATUS_NOT_PROCESSED; file_info.status = "待機中(中断)"
        self.perform_batch_list_view_update()
        self.update_ocr_controls()

    def update_ocr_controls(self):
        running = self.is_ocr_running
        if hasattr(self, 'api_mode_toggle_button'):
            self.api_mode_toggle_button.setEnabled(not running)

        can_start = not running and any(f.is_checked and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT for f in self.processed_files_info)
        if hasattr(self, 'start_ocr_action'):
            self.start_ocr_action.setEnabled(can_start)

        can_resume = False
        if not running and self.processed_files_info:
            eligible_resume = [f for f in self.processed_files_info if f.is_checked and f.ocr_engine_status in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT]
            if eligible_resume and not all(f.ocr_engine_status == OCR_STATUS_NOT_PROCESSED for f in eligible_resume):
                can_resume = True
        if hasattr(self, 'resume_ocr_action'):
            self.resume_ocr_action.setEnabled(can_resume)

        if hasattr(self, 'stop_ocr_action'):
            self.stop_ocr_action.setEnabled(running)

        can_rescan = not running and (bool(self.processed_files_info) or bool(self.input_folder_path))
        if hasattr(self, 'rescan_action'):
            self.rescan_action.setEnabled(can_rescan)
        
        # ★★★ ここからロジックを修正 ★★★
        # CSVダウンロードボタンの状態制御
        can_download_csv = False
        if not running and hasattr(self, 'list_view'):
            # 「選択された行」のリストを取得する
            selected_rows = self.list_view.table.selectionModel().selectedRows()
            # 選択されている行が1つだけの場合に有効化を検討
            if len(selected_rows) == 1:
                selected_row_index = selected_rows[0].row()
                if 0 <= selected_row_index < len(self.processed_files_info):
                    file_info = self.processed_files_info[selected_row_index]
                    # 完了済み、job_idがあり、現在のプロファイルがdx_standard_v2の場合のみ
                    if (file_info.ocr_engine_status == OCR_STATUS_COMPLETED and
                        file_info.job_id and
                        self.active_api_profile and
                        self.active_api_profile.get('id') == 'dx_standard_v2'):
                        can_download_csv = True
        
        if hasattr(self, 'download_csv_action'):
            self.download_csv_action.setEnabled(can_download_csv)
        # ★★★ ここまで修正 ★★★

        enable_others = not running
        if hasattr(self, 'input_folder_action'):
            self.input_folder_action.setEnabled(enable_others)
        if hasattr(self, 'option_action'):
            self.option_action.setEnabled(enable_others)
        if hasattr(self, 'toggle_view_action') and not self.toggle_view_action.isEnabled():
            self.toggle_view_action.setEnabled(True)

    def perform_batch_list_view_update(self):
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE"); self.list_view.update_files(self.processed_files_info, self.is_ocr_running) if hasattr(self, 'list_view') else None; self.update_all_status_displays()
    
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
        else: self.log_manager.info("Rescan: Input folder not set or invalid. File list cleared.", context="UI_ACTION_RESCAN"); self.processed_files_info = []; self.list_view.update_files([], self.is_ocr_running) if hasattr(self, 'list_view') else None; self.update_all_status_displays()
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

    def on_file_auto_csv_processed(self, original_file_main_idx, original_file_path, status_info):
        self.log_manager.debug(f"Original File Auto CSV processed: {os.path.basename(original_file_path)}, Status: {status_info}", context="CALLBACK_CSV_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            return # エラーログは省略
        
        target_file_info = self.processed_files_info[original_file_main_idx]
        if status_info and isinstance(status_info, dict):
            target_file_info.auto_csv_status = status_info.get("message", "状態不明")

        if not self.update_timer.isActive():
            self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    # ★★★ ここから仕分け処理用のスロットを追加 ★★★
    def on_sort_process_started(self, message: str):
        self.log_manager.info(f"MainWindow: Sort process started. Msg: {message}", context="SORT_FLOW_MAIN")
        self.is_ocr_running = True
        # UI上の他のボタンを無効化
        self.update_ocr_controls()
        # ★★★ 確認は移動したため、この行を削除またはコメントアウト ★★★
        # QMessageBox.information(self, "仕分け処理開始", message)

    def on_sort_process_finished(self, success: bool, result_or_error: object):
        self.log_manager.info(f"MainWindow: Sort process finished. Success: {success}", context="SORT_FLOW_MAIN")
        self.is_ocr_running = False
        # UI上のボタンを再度有効化
        self.update_ocr_controls()
        
        if success and isinstance(result_or_error, dict):
            final_status = result_or_error.get('statusName', '不明')
            msg = f"仕分け処理が正常に完了しました。\n\n最終ステータス: {final_status}"
            QMessageBox.information(self, "処理完了", msg)
        elif not success and isinstance(result_or_error, dict):
            error_msg = result_or_error.get('message', '不明なエラー')
            msg = f"仕分け処理中にエラーが発生しました。\n\n詳細: {error_msg}"
            QMessageBox.critical(self, "処理エラー", msg)
        else:
            QMessageBox.warning(self, "処理終了", "仕分け処理が予期せず終了しました。")
    # ★★★ ここまで追加 ★★★
