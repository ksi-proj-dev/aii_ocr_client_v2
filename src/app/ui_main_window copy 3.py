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
from PyQt6.QtGui import QAction, QFontMetrics, QIcon # QIcon をインポートリストに追加
from PyQt6.QtCore import Qt, QTimer, QSize

from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager, LogLevel
from api_client import OCRApiClient # ★ CubeApiClient から OCRApiClient に変更
from file_scanner import FileScanner
from ocr_orchestrator import OcrOrchestrator
from file_model import FileInfo

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING,
    LISTVIEW_UPDATE_INTERVAL_MS
)

APP_VERSION = "0.0.16" # ★ バージョン更新

class ApiSelectionDialog(QDialog):
    def __init__(self, api_profiles: list[dict], current_profile_id: Optional[str], parent=None, initial_selection_filter: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("APIプロファイル選択")
        self.selected_profile_id: Optional[str] = None
        self.log_manager = LogManager() # 簡易的なログ用 (MainWindowのものを渡すのがベターだが、ここでは簡略化)

        layout = QVBoxLayout(self)
        label = QLabel("使用するAPIプロファイルを選択してください:")
        layout.addWidget(label)

        self.combo_box = QComboBox()

        profiles_to_display = []
        if initial_selection_filter:
            temp_ids_in_dialog = set() # 重複表示を防ぐ
            for profile_id_to_filter in initial_selection_filter:
                if profile_id_to_filter in temp_ids_in_dialog:
                    continue
                profile = next((p for p in api_profiles if p.get("id") == profile_id_to_filter), None)
                if profile:
                    profiles_to_display.append(profile)
                    temp_ids_in_dialog.add(profile_id_to_filter)
            
            if not profiles_to_display: # フィルタ結果が空なら、全プロファイルを表示（エラーケースのフォールバック）
                self.log_manager.warning(f"ApiSelectionDialog: initial_selection_filterで有効なプロファイルが見つかりませんでした。全プロファイルを表示します。Filter: {initial_selection_filter}", context="UI_DIALOG_WARN")
                profiles_to_display = api_profiles
        else:
            profiles_to_display = api_profiles

        selected_text_to_set = None
        if initial_selection_filter and profiles_to_display and profiles_to_display[0].get("id") == initial_selection_filter[0]:
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
        elif self.combo_box.count() > 0 : # 何も選択候補がない場合、最初のアイテムを選択
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
                invalid_cli_ids_for_msg = [] # メッセージ表示用の重複なし無効IDリスト
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
                return # プロファイル確定
            else: # CLIで指定されたIDが get_api_profile で見つからなかった場合（基本的には起こらないはず）
                self.log_manager.error(f"CLIで指定された有効なはずのプロファイルID '{target_profile_id_from_cli}' がConfigManagerで見つかりませんでした。", context="SYSTEM_INIT_CRITICAL")
                # この場合、active_api_profileはNoneのままなので、__init__の最後のエラーチェックで終了する

        elif len(available_profiles) == 1 and not ids_for_dialog_filter:
            self.active_api_profile = available_profiles[0]
            profile_id_to_save = self.active_api_profile.get("id")
            if current_saved_profile_id != profile_id_to_save:
                self.config["current_api_profile_id"] = profile_id_to_save
                ConfigManager.save(self.config)
            self.log_manager.info(f"単一のAPIプロファイル '{self.active_api_profile.get('name')}' を自動選択しました。", context="SYSTEM_INIT_AUTO")
        else:
            initial_dialog_selection_id = current_saved_profile_id
            if ids_for_dialog_filter: # CLIフィルターがある場合
                if not (current_saved_profile_id in ids_for_dialog_filter) and ids_for_dialog_filter:
                     initial_dialog_selection_id = ids_for_dialog_filter[0] # フィルタの先頭を選択候補に
            
            # ダイアログに表示するプロファイルリスト（ids_for_dialog_filterがNoneなら全件）
            profiles_for_dialog_display = [p for p in available_profiles if ids_for_dialog_filter is None or p.get("id") in ids_for_dialog_filter]
            if not profiles_for_dialog_display: # 万が一表示できるプロファイルがない場合
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
                else: # ダイアログで選択されたIDが何らかの理由で取得できない場合
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
            return # __init__の最終チェックで終了するはず

        self.api_client = OCRApiClient(
            config=self.config,
            log_manager=self.log_manager,
            api_profile_schema=self.active_api_profile # ★キーワード引数名を修正済み
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
            self.ocr_orchestrator.file_searchable_pdf_processed_signal.connect(self.on_file_searchable_pdf_processed)
            self.ocr_orchestrator.request_ui_controls_update_signal.connect(self.update_ocr_controls)
            self.ocr_orchestrator.request_list_view_update_signal.connect(self._handle_request_list_view_update)

    def _handle_request_list_view_update(self, updated_file_list: List[FileInfo]):
        self.log_manager.debug("MainWindow: Received request to update ListView from orchestrator.", context="UI_UPDATE")
        self.processed_files_info = updated_file_list
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
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
                else: # フォールバック
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

        # ★★★ この行をコメントアウトまたは削除します ★★★
        # self.log_container.setStyleSheet("margin: 0px 6px 6px 6px;")

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
        self.status_bar_frame.setObjectName("StatusBarFrame") # ObjectNameを設定
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
        toolbar.addAction(self.rescan_action) # Enabled state set in update_ocr_controls

        toolbar.addSeparator()

        self.log_toggle_action = QAction("📄ログ表示", self)
        self.log_toggle_action.triggered.connect(self.toggle_log_display)
        toolbar.addAction(self.log_toggle_action)

        self.clear_log_action = QAction("🗑️ログクリア", self)
        self.clear_log_action.triggered.connect(self.clear_log_display)
        toolbar.addAction(self.clear_log_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.api_mode_toggle_button = QPushButton()
        self.api_mode_toggle_button.setCheckable(False) # It's not a toggle in appearance
        self.api_mode_toggle_button.clicked.connect(self._toggle_api_mode)
        self.api_mode_toggle_button.setMinimumWidth(120) # Ensure text fits
        self.api_mode_toggle_button.setStyleSheet("""
            QPushButton { padding: 4px 8px; border: 1px solid #8f8f8f; border-radius: 4px; font-weight: bold; }
            QPushButton[apiMode="live"] { background-color: #e6fff2; color: #006400; }
            QPushButton[apiMode="demo"] { background-color: #e6f7ff; color: #005f9e; }
            QPushButton:disabled { background-color: #f0f0f0; color: #a0a0a0; }
        """)
        toolbar.addWidget(self.api_mode_toggle_button)
        
        right_spacer = QWidget()
        right_spacer.setFixedWidth(10)
        toolbar.addWidget(right_spacer)


        folder_label_toolbar = QToolBar("Folder Paths Toolbar")
        folder_label_toolbar.setMovable(False) # Prevent moving
        folder_label_widget = QWidget()
        folder_label_layout = QFormLayout(folder_label_widget)
        folder_label_layout.setContentsMargins(5,5,5,5) # Adjust margins
        folder_label_layout.setSpacing(3) # Adjust spacing

        self.input_folder_button = QPushButton() # Text set in _update_folder_display
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
        self.insertToolBarBreak(folder_label_toolbar) # Ensures this toolbar is on a new line

    def _update_api_mode_toggle_button_display(self):
        if not hasattr(self, 'api_mode_toggle_button'): return
        current_mode = self.config.get("api_execution_mode", "demo")
        if current_mode == "live":
            self.api_mode_toggle_button.setText("🔴 Live モード")
            self.api_mode_toggle_button.setToolTip("現在 Live モードです。クリックして Demo モードに切り替えます。")
            self.api_mode_toggle_button.setProperty("apiMode", "live")
        else:
            self.api_mode_toggle_button.setText("🔵 Demo モード")
            self.api_mode_toggle_button.setToolTip("現在 Demo モードです。クリックして Live モードに切り替えます。")
            self.api_mode_toggle_button.setProperty("apiMode", "demo")
        self.api_mode_toggle_button.style().unpolish(self.api_mode_toggle_button)
        self.api_mode_toggle_button.style().polish(self.api_mode_toggle_button)
        self.api_mode_toggle_button.update()

    def _toggle_api_mode(self):
        if self.is_ocr_running:
            QMessageBox.warning(self, "モード変更不可", "OCR処理の実行中はAPIモードを変更できません。")
            return

        current_mode = self.config.get("api_execution_mode", "demo")
        new_mode = "live" if current_mode == "demo" else "demo"

        if new_mode == "live":
            active_api_key = ConfigManager.get_active_api_key(self.config)
            if not active_api_key or not active_api_key.strip():
                active_profile_name = self.active_api_profile.get("name", "不明なプロファイル") if self.active_api_profile else "不明なプロファイル"
                QMessageBox.warning(self, "APIキー未設定",
                                    f"Liveモードに切り替えるには、まず「⚙️設定」から\n"
                                    f"現在アクティブなプロファイル「{active_profile_name}」用のAPIキーを設定してください。")
                return
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("APIモード変更の確認")
        msg_box.setText(f"API実行モードを「{current_mode.upper()}」から「{new_mode.upper()}」に変更しますか？")
        msg_box.setInformativeText("変更を保存し、関連コンポーネントに適用します。")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        msg_box.setIcon(QMessageBox.Icon.Question)
        
        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            self.config["api_execution_mode"] = new_mode
            ConfigManager.save(self.config)
            self.log_manager.info(f"API execution mode changed to: {new_mode.upper()}", context="CONFIG_CHANGE_MAIN")

            if hasattr(self, 'api_client') and self.api_client:
                self.api_client.update_config(self.config, self.active_api_profile)
            if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator:
                self.ocr_orchestrator.update_config(self.config, self.active_api_profile)

            self._update_window_title()
            self._update_api_mode_toggle_button_display()
            self.update_ocr_controls()
            self.log_manager.info(f"MainWindow components updated for {new_mode.upper()} mode.", context="CONFIG_CHANGE_MAIN")

    def _update_folder_display(self):
        if hasattr(self, 'input_folder_button'):
            display_path = self.input_folder_path or "未選択"
            self.input_folder_button.setText(display_path)
            self.input_folder_button.setToolTip(self.input_folder_path if self.input_folder_path else "入力フォルダが選択されていません")

    def _load_previous_state_and_perform_initial_scan(self):
        self.input_folder_path = self.config.get("last_target_dir", "")
        self._update_folder_display()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT")
            self.perform_initial_scan()
        elif self.input_folder_path: # Path was saved but is no longer valid
            self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT")
            self.input_folder_path = ""
            self._update_folder_display()
            self._clear_and_update_file_list_display()
        else: # No path saved
            self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT")
            self._update_folder_display()
            self._clear_and_update_file_list_display()
        
        if hasattr(self, 'api_mode_toggle_button'): # Ensure button display is updated after config load
            self._update_api_mode_toggle_button_display()


    def _clear_and_update_file_list_display(self):
        self.processed_files_info = []
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        if hasattr(self, 'summary_view') and self.summary_view:
            self.summary_view.reset_summary() # Reset counts in summary view
        self.update_all_status_displays()


    def _restore_view_and_log_state(self):
        self.current_view = self.config.get("current_view", 0)
        if hasattr(self, 'stack'):
            self.stack.setCurrentIndex(self.current_view)
        
        log_visible = self.config.get("log_visible", True)
        if hasattr(self, 'log_container'):
            self.log_container.setVisible(log_visible)

    def _update_all_ui_controls_state(self): # Wrapper for clarity
        self.update_ocr_controls()

    def _handle_ocr_process_started_from_orchestrator(self, num_files_to_process: int, updated_file_list: List[FileInfo]):
        self.log_manager.info(f"MainWindow: OCR process started signal received for {num_files_to_process} files.", context="OCR_FLOW_MAIN")
        self.is_ocr_running = True
        self.processed_files_info = updated_file_list # Update main data
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info) # Update ListView display
        if hasattr(self.summary_view, 'start_processing'):
            self.summary_view.start_processing(num_files_to_process)
        self.update_status_bar()
        self.update_ocr_controls()

    def _handle_ocr_process_finished_from_orchestrator(self, was_interrupted: bool, fatal_error_info: Optional[dict] = None):
        self.log_manager.info(f"MainWindow: OCR process finished signal received. Interrupted: {was_interrupted}, FatalError: {fatal_error_info}", context="OCR_FLOW_MAIN")
        self.is_ocr_running = False
        reason = ""
        if fatal_error_info and isinstance(fatal_error_info, dict):
            reason = fatal_error_info.get("message", "不明な致命的エラー")
            self.log_manager.error(f"MainWindow: OCR processing stopped due to a fatal error from worker: {reason}", context="OCR_FLOW_MAIN")
        elif was_interrupted:
            reason = "ユーザーによる中止"
            self.log_manager.info(f"MainWindow: OCR processing was interrupted by user (from orchestrator signal).", context="OCR_FLOW_MAIN")

        if was_interrupted or fatal_error_info:
            output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both")
            json_interrupt_status = "中断" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
            pdf_interrupt_status = "中断" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"

            for file_info in self.processed_files_info:
                if file_info.ocr_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING] or \
                   (file_info.status == OCR_STATUS_PROCESSING and file_info.ocr_engine_status == OCR_STATUS_PROCESSING) : # Check both status fields for robustness
                    file_info.ocr_engine_status = OCR_STATUS_FAILED # Mark as failed if interrupted during active processing
                    file_info.status = "中断" if was_interrupted else "エラー(停止)"
                    file_info.ocr_result_summary = f"(処理が中止/停止されました: {reason})" if reason else "(処理が中止/停止されました)"
                    file_info.json_status = json_interrupt_status
                    file_info.searchable_pdf_status = pdf_interrupt_status
        
        self.perform_batch_list_view_update() # Update list view with final statuses
        self.update_ocr_controls()

        final_message = "全てのファイルのOCR処理が完了しました。"
        if fatal_error_info and isinstance(fatal_error_info, dict):
            final_message = f"OCR処理がエラーにより停止しました。\n理由: {fatal_error_info.get('message', '不明なエラー')}"
            if fatal_error_info.get("code") in ["NOT_IMPLEMENTED_LIVE_API", "NOT_IMPLEMENTED_LIVE_API_PDF", "NOT_IMPLEMENTED_API_CALL", "NOT_IMPLEMENTED_API_CALL_PDF"]:
                final_message += "\n\nLiveモードでのAPI呼び出しは現在実装されていません。\nDemoモードで実行するか、APIクライアントの実装をご確認ください。"
            QMessageBox.critical(self, "処理停止 (致命的エラー)", final_message)
        elif was_interrupted:
            final_message = "OCR処理が中止されました。"
            QMessageBox.information(self, "処理終了", final_message)
        else:
            QMessageBox.information(self, "処理終了", final_message)

    def update_status_bar(self):
        total_list_items = len(self.processed_files_info)
        selected_for_processing_count = 0
        # ocr_success_count と ocr_error_count は summary_view から取得するのがより正確
        ocr_success_count = self.summary_view.ocr_completed_count if hasattr(self, 'summary_view') else 0
        ocr_error_count = self.summary_view.ocr_error_count if hasattr(self, 'summary_view') else 0

        for file_info in self.processed_files_info:
            if file_info.is_checked and file_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                selected_for_processing_count += 1
        
        if hasattr(self, 'status_total_list_label'): # Ensure widgets exist
            self.status_total_list_label.setText(f"リスト総数: {total_list_items}")
            self.status_selected_files_label.setText(f"選択中: {selected_for_processing_count}")
            self.status_success_files_label.setText(f"成功: {ocr_success_count}")
            self.status_error_files_label.setText(f"エラー: {ocr_error_count}")

    def update_all_status_displays(self):
        size_skipped_count = 0
        checked_and_processable_for_summary = 0
        for file_info in self.processed_files_info:
            if file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                size_skipped_count += 1
            elif file_info.is_checked: # Only count checked items for "total ocr target" for summary
                 checked_and_processable_for_summary +=1
        
        if hasattr(self, 'summary_view'):
            self.summary_view.update_summary_counts(
                total_scanned=len(self.processed_files_info),
                total_ocr_target=checked_and_processable_for_summary, # Pass the count of checked & processable
                skipped_size=size_skipped_count
            )
        self.update_status_bar() # Status bar also needs update

    def on_list_item_check_state_changed(self, row_index, is_checked):
        if 0 <= row_index < len(self.processed_files_info):
            self.processed_files_info[row_index].is_checked = is_checked
            self.log_manager.debug(f"File '{self.processed_files_info[row_index].name}' check state in data model changed to: {is_checked}", context="UI_EVENT")
            self.update_all_status_displays() # This will update summary and status bar
            self.update_ocr_controls()
    
    def perform_initial_scan(self):
        self.log_manager.info(f"スキャン開始: {self.input_folder_path}", context="FILE_SCAN_MAIN")
        if self.update_timer.isActive(): self.update_timer.stop() # Stop any pending batch update
        self.processed_files_info = [] # Clear existing list

        collected_files_paths, max_files_info, depth_limited_folders = self.file_scanner.scan_folder(self.input_folder_path)
        
        if collected_files_paths:
            self.processed_files_info = self.file_scanner.create_initial_file_list(
                collected_files_paths,
                OCR_STATUS_SKIPPED_SIZE_LIMIT,
                OCR_STATUS_NOT_PROCESSED
            )
            processable_count = sum(1 for item in self.processed_files_info if item.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT)
            self.log_manager.info(f"MainWindow: Scan completed. {len(self.processed_files_info)} files loaded ({processable_count} processable).", context="FILE_SCAN_MAIN")
        else:
            self.log_manager.info("MainWindow: Scan completed. No files found or collected.", context="FILE_SCAN_MAIN")

        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info) # Update list view

        warning_messages = []
        if max_files_info:
            msg = (f"最大処理ファイル数 ({max_files_info['limit']}件) に達したため、"
                   f"フォルダ「{max_files_info['last_scanned_folder']}」以降の一部のファイルは読み込まれていません。")
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
             self.summary_view.reset_summary() # Reset summary view counts
        self.update_all_status_displays() # Update summary and status bar based on new list
        self.update_ocr_controls()


    def append_log_message_to_widget(self, level: str, message: str):
        if hasattr(self, 'log_widget') and self.log_widget:
            color_map = {
                LogLevel.ERROR: "red",
                LogLevel.WARNING: "orange",
                # LogLevel.INFO: "black", # Default color
                LogLevel.DEBUG: "gray",
            }
            color = color_map.get(level)
            if color:
                self.log_widget.append(f'<font color="{color}">{message}</font>')
            else:
                self.log_widget.append(message)
            self.log_widget.ensureCursorVisible() # Scroll to the bottom

    def select_input_folder(self):
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): # ensure last_dir is valid
            last_dir = os.path.expanduser("~")
            
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.log_manager.info(f"Input folder selected by user: {folder}", context="UI_EVENT")
            if folder != self.input_folder_path or not self.processed_files_info : # Rescan if folder changed or list is empty
                self.input_folder_path = folder
                self._update_folder_display()
                self.log_manager.info(f"Performing rescan for newly selected folder: {folder}", context="UI_EVENT")
                self.perform_rescan() # This will clear and rescan
            else:
                self.log_manager.info("Selected folder is the same as current and list is not empty. No rescan forced.", context="UI_EVENT")
        else:
            self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")
        self._update_folder_display() # Update display even if cancelled (in case it was cleared)

    def open_input_folder_in_explorer(self):
        self.log_manager.debug(f"Attempting to open folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            try:
                # Normalize path for safety, especially on Windows
                norm_path = os.path.normpath(self.input_folder_path)
                if platform.system() == "Windows":
                    os.startfile(norm_path)
                elif platform.system() == "Darwin": # macOS
                    subprocess.run(['open', norm_path], check=True)
                else: # Linux and other Unix-like
                    subprocess.run(['xdg-open', norm_path], check=True)
                self.log_manager.info(f"Successfully opened folder: {norm_path}", context="UI_ACTION_OPEN_FOLDER")
            except Exception as e:
                self.log_manager.error(f"Failed to open folder '{self.input_folder_path}'. Error: {e}", context="UI_ACTION_OPEN_FOLDER_ERROR", exception_info=e)
                QMessageBox.warning(self, "フォルダを開けません", f"フォルダ '{self.input_folder_path}' を開けませんでした。\nエラー: {e}")
        else:
            self.log_manager.warning(f"Cannot open folder: Path is invalid or not set. Path: '{self.input_folder_path}'", context="UI_ACTION_OPEN_FOLDER_INVALID")
            QMessageBox.information(self, "フォルダ情報なし", "入力フォルダが選択されていないか、無効なパスです。")


    def toggle_view(self):
        if hasattr(self, 'stack'):
            self.current_view = 1 - self.stack.currentIndex() # Get current and toggle
            self.stack.setCurrentIndex(self.current_view)
            self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")

    def toggle_log_display(self):
        if hasattr(self, 'log_container'):
            visible = self.log_container.isVisible()
            self.log_container.setVisible(not visible)
            self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION")
            if hasattr(self, 'log_toggle_action'): # Update action text/icon if needed
                self.log_toggle_action.setText("📄ログ非表示" if not visible else "📄ログ表示")


    def show_option_dialog(self):
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION")
        active_profile_id = self.config.get("current_api_profile_id")
        
        options_schema = ConfigManager.get_active_api_options_schema(self.config)
        current_option_values = ConfigManager.get_active_api_options_values(self.config)

        if options_schema is None: # Schema definition missing for profile
            QMessageBox.warning(self, "設定エラー", 
                                f"現在アクティブなAPIプロファイル '{active_profile_id}' のオプション定義の取得に失敗しました。\n"
                                "設定ファイルが破損しているか、プロファイル定義に問題がある可能性があります。")
            self.log_manager.error(f"オプションスキーマの取得に失敗 (None)。Profile ID: {active_profile_id}", context="CONFIG_ERROR")
            return
        
        if current_option_values is None: # Should not happen if config is consistent
            self.log_manager.warning(f"アクティブプロファイル '{active_profile_id}' のオプション値(current_option_values)が取得できませんでした。空のオプションでダイアログを開きます。", context="CONFIG_WARN")
            current_option_values = {} 

        # Capture old scan-related settings before dialog to check if rescan is needed
        # These options should be part of options_schema for the profile if they are per-profile
        # For now, assuming they might be in current_option_values directly or from schema defaults
        old_scan_options = {
            "max_files_to_process": current_option_values.get("max_files_to_process", (options_schema.get("max_files_to_process", {}).get("default") if options_schema else None)),
            "recursion_depth": current_option_values.get("recursion_depth", (options_schema.get("recursion_depth", {}).get("default") if options_schema else None))
        }

        dialog = OptionDialog(
            options_schema=options_schema, # Can be {}
            current_option_values=current_option_values,
            global_config=self.config, # Pass the whole config for global settings like file_actions
            parent=self
        )

        if dialog.exec():
            updated_profile_specific_options, updated_global_config_parts = dialog.get_saved_settings()

            # Update profile-specific options (OCR options, api_key, base_uri)
            if active_profile_id and updated_profile_specific_options is not None:
                self.config["options_values_by_profile"][active_profile_id] = updated_profile_specific_options
            
            # Update global (non-profile-specific) parts of the config from dialog
            if updated_global_config_parts is not None:
                # Only update specific keys that OptionDialog is responsible for (e.g., file_actions)
                # instead of overwriting the whole self.config with updated_global_config_parts
                if "file_actions" in updated_global_config_parts:
                    self.config["file_actions"] = updated_global_config_parts["file_actions"]
                # Add other global keys here if OptionDialog modifies them
            
            ConfigManager.save(self.config) # Save the entire modified self.config
            self.log_manager.info("Options saved.", context="CONFIG_EVENT") # Simpler log

            # Reload active profile and options for consistency after save
            self.active_api_profile = ConfigManager.get_active_api_profile(self.config)
            # Re-fetch current_option_values AFTER saving and reloading active_api_profile
            current_option_values = ConfigManager.get_active_api_options_values(self.config) or {}


            if hasattr(self, 'api_client') and self.api_client:
                self.api_client.update_config(self.config, self.active_api_profile)
            if hasattr(self, 'ocr_orchestrator') and self.ocr_orchestrator:
                self.ocr_orchestrator.update_config(self.config, self.active_api_profile)
            if hasattr(self, 'file_scanner') and self.file_scanner:
                self.file_scanner.config = self.config

            self._update_window_title()
            self._update_api_mode_toggle_button_display()
            
            # Check if scan-related options changed
            new_scan_options = {
                "max_files_to_process": current_option_values.get("max_files_to_process", (options_schema.get("max_files_to_process", {}).get("default") if options_schema else None)),
                "recursion_depth": current_option_values.get("recursion_depth", (options_schema.get("recursion_depth", {}).get("default") if options_schema else None))
            }
            
            rescan_needed = False
            if ("max_files_to_process" in old_scan_options and old_scan_options["max_files_to_process"] != new_scan_options["max_files_to_process"]) or \
               ("recursion_depth" in old_scan_options and old_scan_options["recursion_depth"] != new_scan_options["recursion_depth"]):
                # Note: This assumes max_files_to_process and recursion_depth are part of options_schema
                # and their values are stored in options_values_by_profile.
                # If they are global, this check needs adjustment.
                # For now, we'll assume they *could* be per-profile if defined in schema.
                # FileScanner currently reads them from self.config.get("options", {}).get(self.config.get("api_type"), {})
                # which is not ideal if they are per-profile via options_values_by_profile.
                # This part needs to be harmonized with how FileScanner gets its scan parameters.
                # For now, to be safe, let's assume if *any* OCR option changed for current profile, or global file_actions changed,
                # it's safer to allow a re-evaluation of files, but not necessarily a full rescan unless specifically scan params change.
                # The user did not define max_files_to_process or recursion_depth in their schemas yet.
                # So this check is currently not very effective.
                # Let's simplify: if certain known options change, prompt for rescan.
                # However, FileScanner uses config values that are NOT currently in options_schema (max_files_to_process, recursion_depth)
                # These are currently hardcoded defaults or from a different part of config in FileScanner.
                # This needs to be unified. For now, we'll skip smart rescan check and just re-evaluate.
                pass # Simplified for now. Re-evaluation logic is below.


            self.log_manager.info(f"Settings changed. Re-evaluating file statuses based on new options.", context="CONFIG_EVENT")
            new_upload_max_mb = current_option_values.get("upload_max_size_mb", 60)
            new_upload_max_bytes = new_upload_max_mb * 1024 * 1024
            
            new_file_actions_cfg = self.config.get("file_actions", {})
            new_output_format = new_file_actions_cfg.get("output_format", "both")
            
            default_json_status = "-" if new_output_format in ["json_only", "both"] else "作成しない(設定)"
            default_pdf_status = "-" if new_output_format in ["pdf_only", "both"] else "作成しない(設定)"
            
            items_updated = False
            for file_info in self.processed_files_info:
                prev_engine_status = file_info.ocr_engine_status; prev_checked = file_info.is_checked
                orig_status = file_info.status; orig_json = file_info.json_status; orig_pdf = file_info.searchable_pdf_status
                
                is_now_skipped = file_info.size > new_upload_max_bytes
                
                if is_now_skipped:
                    if file_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                        file_info.status = "スキップ(サイズ上限)"; file_info.ocr_engine_status = OCR_STATUS_SKIPPED_SIZE_LIMIT
                        file_info.ocr_result_summary = f"ファイルサイズが上限 ({new_upload_max_mb}MB) を超過"
                        file_info.json_status = "スキップ"; file_info.searchable_pdf_status = "スキップ"
                        file_info.is_checked = False
                else: 
                    if file_info.ocr_engine_status == OCR_STATUS_SKIPPED_SIZE_LIMIT:
                        file_info.status = "待機中"; file_info.ocr_engine_status = OCR_STATUS_NOT_PROCESSED
                        file_info.ocr_result_summary = ""; file_info.is_checked = True
                    
                    if file_info.ocr_engine_status == OCR_STATUS_NOT_PROCESSED: # Only update if not processed yet
                        file_info.json_status = default_json_status
                        file_info.searchable_pdf_status = default_pdf_status
                        
                if (file_info.ocr_engine_status != prev_engine_status or file_info.status != orig_status or \
                    file_info.json_status != orig_json or file_info.searchable_pdf_status != orig_pdf or \
                    file_info.is_checked != prev_checked):
                    items_updated = True
                    
            if items_updated:
                if hasattr(self, 'list_view'): self.list_view.update_files(self.processed_files_info)
            
            self.update_all_status_displays()
            self.update_ocr_controls()
        else:
            self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

    def confirm_start_ocr(self):
        if hasattr(self, 'ocr_orchestrator'):
            # ★変更: self.processed_files_info の代わりに、ソート済みのリストを取得して渡す
            sorted_list_to_process = self.list_view.get_sorted_file_info_list()
            self.ocr_orchestrator.confirm_and_start_ocr(sorted_list_to_process, self.input_folder_path, self)

    def confirm_resume_ocr(self):
        if hasattr(self, 'ocr_orchestrator'):
            # ★変更: self.processed_files_info の代わりに、ソート済みのリストを取得して渡す
            sorted_list_to_process = self.list_view.get_sorted_file_info_list()
            self.ocr_orchestrator.confirm_and_resume_ocr(sorted_list_to_process, self.input_folder_path, self)

    def confirm_stop_ocr(self):
        if hasattr(self, 'ocr_orchestrator'):
            self.ocr_orchestrator.confirm_and_stop_ocr(self)


    def on_original_file_status_update_from_worker(self, original_file_path: str, status_message: str):
        target_file_info = next((item for item in self.processed_files_info if item.path == original_file_path), None)
        if target_file_info:
            self.log_manager.debug(f"UI Update for '{target_file_info.name}': {status_message}", context="UI_STATUS_UPDATE")
            target_file_info.status = status_message # Update general status for display
            # Update engine_status based on specific messages for more precise state tracking
            if status_message == OCR_STATUS_SPLITTING: target_file_info.ocr_engine_status = OCR_STATUS_SPLITTING
            elif OCR_STATUS_PART_PROCESSING in status_message: target_file_info.ocr_engine_status = OCR_STATUS_PART_PROCESSING
            elif status_message == OCR_STATUS_MERGING: target_file_info.ocr_engine_status = OCR_STATUS_MERGING
            # For "処理中" that is not more specific, ensure engine_status is also 'processing'
            elif status_message == OCR_STATUS_PROCESSING and target_file_info.ocr_engine_status == OCR_STATUS_NOT_PROCESSED : # Only if not already in a sub-processing state
                 target_file_info.ocr_engine_status = OCR_STATUS_PROCESSING

            if not self.update_timer.isActive():
                self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)
        else:
            self.log_manager.warning(f"Status update received for unknown file: {original_file_path}", context="UI_STATUS_UPDATE_WARN")

    def on_file_ocr_processed(self, original_file_main_idx: int, original_file_path: str, ocr_result_data_for_original: Any, ocr_error_info_for_original: Optional[Dict[str, Any]], json_save_status_for_original: str):
        self.log_manager.debug(f"Original File OCR stage processed (MainWin): {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Success={not ocr_error_info_for_original}, JSON Status='{json_save_status_for_original}'", context="CALLBACK_OCR_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx}. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return
        
        target_file_info = self.processed_files_info[original_file_main_idx]

        if ocr_error_info_for_original and isinstance(ocr_error_info_for_original, dict):
            target_file_info.status = "OCR失敗"
            target_file_info.ocr_engine_status = OCR_STATUS_FAILED
            err_msg = ocr_error_info_for_original.get('message', '不明なOCRエラー')
            err_code = ocr_error_info_for_original.get('code', '')
            err_detail = ocr_error_info_for_original.get('detail', '')
            target_file_info.ocr_result_summary = f"エラー: {err_msg}" + (f" (コード: {err_code})" if err_code else "")
            # Avoid showing popups for non-critical or already handled errors by worker/orchestrator
            if err_code not in ["USER_INTERRUPT", "NOT_IMPLEMENTED_LIVE_API", "NOT_IMPLEMENTED_API_CALL", "FATAL_ERROR_STOP", "PART_PROCESSING_ERROR", # Generic worker error
                                "DXSUITE_REGISTER_HTTP_ERROR_NON_JSON", "DXSUITE_GETRESULT_HTTP_ERROR_NON_JSON", # Covered by specific API errors
                                "DXSUITE_REGISTER_REQUEST_FAIL", "DXSUITE_GETRESULT_REQUEST_FAIL",
                                "DXSUITE_REGISTER_UNEXPECTED_ERROR", "DXSUITE_GETRESULT_UNEXPECTED_ERROR",
                                "DXSUITE_BASE_URI_NOT_CONFIGURED"] and not ("DXSUITE_API_" in err_code): # DX Suite API specific errors often have messages
                 QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})",
                                    f"ファイル「{target_file_info.name}」のOCR処理中にエラーが発生しました。\n\n"
                                    f"メッセージ: {err_msg}\nコード: {err_code}\n詳細: {err_detail if err_detail else 'N/A'}\n\n"
                                    "ログファイルをご確認ください。")
        elif ocr_result_data_for_original:
            target_file_info.status = "OCR成功"
            target_file_info.ocr_engine_status = OCR_STATUS_COMPLETED
            fulltext = ""
            # Extract fulltext based on known structures (adapt as needed for different API responses)
            if isinstance(ocr_result_data_for_original, dict):
                if ocr_result_data_for_original.get("status") == "ocr_registered": # Intermediate status from DX Suite register
                    fulltext = f"(登録成功 Job ID: {ocr_result_data_for_original.get('job_id', 'N/A')})"
                    target_file_info.status = "OCR登録済 (結果待機中)" # More specific status
                    target_file_info.ocr_engine_status = OCR_STATUS_PROCESSING # Still processing overall
                elif ocr_result_data_for_original.get("status") == "done": # DX Suite GetResult
                    # DX Suite specific structure from spec
                    results_list = ocr_result_data_for_original.get("results", [])
                    if results_list and isinstance(results_list, list) and results_list[0].get("pages"):
                        fulltext_parts = [page.get("fulltext", "") for page in results_list[0]["pages"]]
                        fulltext = " ".join(filter(None, fulltext_parts))
                    else:
                        fulltext = "結果解析エラー(DX Suite)"
                elif "detail" in ocr_result_data_for_original: # Generic detail
                     fulltext = ocr_result_data_for_original["detail"]
                elif "message" in ocr_result_data_for_original: # Generic message
                     fulltext = ocr_result_data_for_original["message"]
                else: # Fallback for Cube-like structure (list of page results) or unknown single dict result
                    fulltext_parts = [ocr_result_data_for_original.get("fulltext", ""),
                                      (ocr_result_data_for_original.get("result", {}) or {}).get("fulltext", ""),
                                      (ocr_result_data_for_original.get("result", {}) or {}).get("aGroupingFulltext", "")]
                    fulltext = " / ".join(filter(None, fulltext_parts))
            elif isinstance(ocr_result_data_for_original, list) and ocr_result_data_for_original: # Cube-like list
                try:
                    first_page_res = ocr_result_data_for_original[0].get("result", {})
                    fulltext_parts = [first_page_res.get("fulltext", ""), first_page_res.get("aGroupingFulltext", "")]
                    fulltext = " / ".join(filter(None, fulltext_parts))
                except Exception: fulltext = "結果解析エラー(集約)"
            else:
                fulltext = "OCR結果あり(形式不明)"
            
            target_file_info.ocr_result_summary = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
        else: # No result and no error_info - should ideally not happen if worker guarantees one or the other
            target_file_info.status = "OCR状態不明"
            target_file_info.ocr_engine_status = OCR_STATUS_FAILED
            target_file_info.ocr_result_summary = "APIレスポンスなし(OCR)"
            QMessageBox.warning(self, f"OCR処理エラー ({target_file_info.name})",
                                f"ファイル「{target_file_info.name}」のOCR処理でAPIから有効な応答がありませんでした。")

        if isinstance(json_save_status_for_original, str):
            target_file_info.json_status = json_save_status_for_original
        elif ocr_error_info_for_original : # If OCR error, JSON status reflects that
            target_file_info.json_status = "エラー(OCR失敗)"
        
        # Update summary only if this is the final step for this file (e.g. JSON only mode)
        # or if PDF step is not applicable/failed already.
        # The OcrWorker is now responsible for emitting only "final" file_processed for summary updates.
        # OcrOrchestrator might handle this logic better.
        # For now, we assume this callback might be intermediate for async flows.
        # Let OcrWorker's all_files_processed or a specific final signal from orchestrator update summary.
        # However, if JSON only mode, this IS the final step.
        output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both")
        if output_format_cfg == "json_only":
            if target_file_info.ocr_engine_status == OCR_STATUS_COMPLETED:
                if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=True)
                target_file_info.status = "完了" # Final status for UI
            elif target_file_info.ocr_engine_status == OCR_STATUS_FAILED:
                 if hasattr(self, 'summary_view'): self.summary_view.update_for_processed_file(is_success=False)
            self.update_status_bar()

        if not self.update_timer.isActive():
            self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)


    def on_file_searchable_pdf_processed(self, original_file_main_idx: int, original_file_path: str, pdf_final_path: Optional[str], pdf_error_info: Optional[Dict[str, Any]]):
        self.log_manager.debug(f"Original File Searchable PDF processed: {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Path={pdf_final_path}, Error={pdf_error_info}", context="CALLBACK_PDF_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx}. Max idx: {len(self.processed_files_info)-1}. File: {original_file_path}", context="CALLBACK_ERROR")
            return

        target_file_info = self.processed_files_info[original_file_main_idx]
        output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both")
        ocr_engine_status_before_pdf = target_file_info.ocr_engine_status # Status from OCR text step
        pdf_stage_final_success = False

        if output_format_cfg == "json_only":
            target_file_info.searchable_pdf_status = "作成しない(設定)"
            # Overall success already determined by OCR stage if json_only
        elif pdf_final_path and not pdf_error_info and os.path.exists(pdf_final_path):
            target_file_info.searchable_pdf_status = "PDF作成成功"
            pdf_stage_final_success = True
            if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED : # If OCR text was also OK
                 target_file_info.status = "完了" # Final status
        elif pdf_error_info and isinstance(pdf_error_info, dict):
            error_msg = pdf_error_info.get('message', 'PDF作成不明エラー')
            error_code = pdf_error_info.get('code', '')
            err_detail = pdf_error_info.get('detail', '')
            target_file_info.searchable_pdf_status = f"PDFエラー: {error_msg}" + (f" (コード: {error_code})" if error_code else "")

            if error_code == "PARTS_COPIED_SUCCESS": # Special case for non-merged split PDFs
                pdf_stage_final_success = True
                if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED: target_file_info.status = "完了"
            elif error_code in ["PARTS_COPIED_PARTIAL", "PARTS_COPY_ERROR", "NO_PARTS_TO_COPY"] :
                 if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED : target_file_info.status = "部品PDFエラー" # If OCR was ok, but PDF copy failed
            elif not ("作成対象外" in error_msg or "作成しない" in error_msg or "部品PDFは結合されません(設定)" in error_msg or "PDF_NOT_REQUESTED" == error_code):
                # Only pop up for actual processing errors, not for config-based skips or known non-implemented live calls for PDF
                if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED : # If OCR was ok, but PDF failed
                    target_file_info.status = "PDF作成失敗"
                    # Append PDF error to summary if OCR summary was simple (not already an error/multi-part message)
                    if target_file_info.ocr_result_summary and \
                       "エラー" not in target_file_info.ocr_result_summary and \
                       "部品のOCR完了" not in target_file_info.ocr_result_summary and \
                       "登録成功 Job ID" not in target_file_info.ocr_result_summary and \
                       "PDFエラー" not in target_file_info.ocr_result_summary:
                        target_file_info.ocr_result_summary += f" (PDFエラー: {error_msg})"
                    elif not target_file_info.ocr_result_summary:
                         target_file_info.ocr_result_summary = f"PDFエラー: {error_msg}"

                # Filter popups for known "not implemented" or less critical PDF errors
                popup_exclusions_pdf = [
                    "USER_INTERRUPT_PDF", "PDF_NOT_REQUESTED", "PARTS_COPIED_SUCCESS", "NO_PARTS_TO_COPY",
                    "PDF_CREATION_FAIL_DUE_TO_OCR_ERROR", "FATAL_ERROR_STOP_PDF",
                    "NOT_IMPLEMENTED_API_CALL_PDF", # Cube PDF not implemented
                    "NOT_IMPLEMENTED_API_CALL_DX_SPDF" # DX Suite PDF not implemented
                ]
                if error_code not in popup_exclusions_pdf:
                    QMessageBox.warning(self, f"PDF処理エラー ({target_file_info.name})",
                                        f"ファイル「{target_file_info.name}」のPDF処理中にエラーが発生しました。\n\n"
                                        f"メッセージ: {error_msg}\nコード: {error_code}\n詳細: {err_detail or 'N/A'}\n\n"
                                        "ログファイルをご確認ください。")
        elif ocr_engine_status_before_pdf == OCR_STATUS_FAILED: # If OCR text failed, PDF is not applicable
            target_file_info.searchable_pdf_status = "対象外(OCR失敗)"
        elif output_format_cfg in ["pdf_only", "both"]: # PDF was expected but no path and no error
            target_file_info.searchable_pdf_status = "PDF状態不明"
            if ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED : target_file_info.status = "PDF状態不明"
        else: # Should not be reached if json_only was handled
            target_file_info.searchable_pdf_status = "-"

        # Update overall summary view if PDF processing was relevant (not json_only)
        if output_format_cfg != "json_only":
            # Success for summary if OCR was OK AND PDF was OK (or not needed and OCR was OK)
            is_overall_success_for_summary = (ocr_engine_status_before_pdf == OCR_STATUS_COMPLETED and pdf_stage_final_success)
            if hasattr(self, 'summary_view'):
                self.summary_view.update_for_processed_file(is_success=is_overall_success_for_summary)
            self.update_status_bar()

        if not self.update_timer.isActive():
            self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def perform_batch_list_view_update(self):
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE")
        if hasattr(self, 'list_view') and self.list_view:
            self.list_view.update_files(self.processed_files_info)
        self.update_all_status_displays() # Ensure summary and status bar are also up-to-date

    def confirm_rescan_ui(self):
        self.log_manager.debug("Confirming UI rescan.", context="UI_ACTION")
        if self.is_ocr_running:
            QMessageBox.warning(self, "再スキャン不可", "OCR処理の実行中は再スキャンできません。")
            return
        if not self.processed_files_info and not self.input_folder_path: # Nothing to clear or rescan
            QMessageBox.information(self, "再スキャン", "クリアまたは再スキャンする対象がありません。")
            return

        if self.update_timer.isActive(): self.update_timer.stop() # Stop pending updates before rescan

        reply = QMessageBox.question(self, "再スキャン確認",
                                     "入力フォルダが再スキャンされます。\n\n"
                                     "現在のリストと進捗状況はクリアされます。\n\nよろしいですか？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_manager.info("User confirmed UI rescan.", context="UI_ACTION")
            self.perform_rescan()
        else:
            self.log_manager.info("User cancelled UI rescan.", context="UI_ACTION")

    def perform_rescan(self):
        self.log_manager.info("Performing UI clear and input folder rescan.", context="UI_ACTION_RESCAN")
        if hasattr(self.summary_view, 'reset_summary'):
            self.summary_view.reset_summary() # Reset summary first

        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"Rescanning input folder: {self.input_folder_path}", context="UI_ACTION_RESCAN")
            self.perform_initial_scan() # This will update file list and then statuses
        else:
            self.log_manager.info("Rescan: Input folder not set or invalid. File list cleared.", context="UI_ACTION_RESCAN")
            self.processed_files_info = [] # Clear list
            if hasattr(self, 'list_view'): self.list_view.update_files([])
            self.update_all_status_displays() # Update displays based on empty list

        self._update_folder_display()
        self.is_ocr_running = False # Ensure OCR is marked as not running
        self.update_ocr_controls()


    def update_ocr_controls(self):
        running = self.is_ocr_running
        if hasattr(self, 'api_mode_toggle_button'):
            self.api_mode_toggle_button.setEnabled(not running)

        can_start_ocr = False
        can_resume_ocr = False

        if not running and self.processed_files_info: # Only enable if not running and files exist
            # Can start if any checked file is not skipped and not already completed successfully
            # (Allowing re-processing of failed or already processed for now, orchestrator handles confirmation)
            if any(f.is_checked and f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT for f in self.processed_files_info):
                can_start_ocr = True
            
            # Can resume if any checked file is specifically in a state that allows resume (e.g. failed, or not_processed)
            # and not already successfully completed.
            eligible_for_resume = [
                f for f in self.processed_files_info 
                if f.is_checked and 
                   f.ocr_engine_status in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and 
                   f.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT
            ]
            if eligible_for_resume: # If there are any files that are clearly resumable
                can_resume_ocr = True
            
        if hasattr(self, 'start_ocr_action'): self.start_ocr_action.setEnabled(can_start_ocr)
        if hasattr(self, 'resume_ocr_action'): self.resume_ocr_action.setEnabled(can_resume_ocr)
        if hasattr(self, 'stop_ocr_action'): self.stop_ocr_action.setEnabled(running)
        
        can_rescan_action = not running and (bool(self.processed_files_info) or bool(self.input_folder_path))
        if hasattr(self, 'rescan_action'): self.rescan_action.setEnabled(can_rescan_action)
        
        # Other general actions
        enable_general_actions = not running
        if hasattr(self, 'input_folder_action'): self.input_folder_action.setEnabled(enable_general_actions)
        if hasattr(self, 'option_action'): self.option_action.setEnabled(enable_general_actions)
        if hasattr(self, 'toggle_view_action') and not self.toggle_view_action.isEnabled(): # View toggle always enabled
            self.toggle_view_action.setEnabled(True)
        # Log toggle and clear can also be always enabled, or tied to 'not running'
        if hasattr(self, 'log_toggle_action'): self.log_toggle_action.setEnabled(True)
        if hasattr(self, 'clear_log_action'): self.clear_log_action.setEnabled(True)


    def closeEvent(self, event):
        self.log_manager.debug("Application closeEvent triggered.", context="SYSTEM_LIFECYCLE")
        if self.update_timer.isActive():
            self.update_timer.stop()

        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認",
                                         "OCR処理が実行中です。本当にアプリケーションを終了しますか？\n"
                                         "(進行中の処理は中断されます)",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            else: # User confirmed to close while running
                if self.ocr_orchestrator:
                    self.log_manager.info("Close event: OCR running, requesting worker to stop.", context="SYSTEM_LIFECYCLE_CLOSE")
                    # Orchestrator's stop is async, but we proceed to save and close.
                    # Worker thread should ideally terminate gracefully.
                    self.ocr_orchestrator.confirm_and_stop_ocr(self) # Request stop
                    # Give a brief moment for signals to process if needed, though this is tricky on close
                    QApplication.processEvents() # Try to process stop signals
        
        # Save configuration
        cfg = self.config.copy() # Start with a copy of current config
        
        if self.isMaximized():
            cfg["window_state"] = "maximized"
            # When maximized, normalGeometry might give previous non-maximized size.
            # It's often better not to save specific width/height if maximized,
            # or to save the geometry of the screen it's on.
            # For simplicity, we'll just save the normalGeometry.
            geom = self.normalGeometry() 
            cfg["window_size"] = {"width": geom.width(), "height": geom.height()}
            # Position is less relevant when maximized, but can be saved.
            if "window_position" in cfg: del cfg["window_position"] # Or save geom.x(), geom.y()
        else:
            cfg["window_state"] = "normal"
            geom = self.geometry() # Current geometry if not maximized
            cfg["window_size"] = {"width": geom.width(), "height": geom.height()}
            cfg["window_position"] = {"x": geom.x(), "y": geom.y()}

        cfg["last_target_dir"] = self.input_folder_path
        cfg["current_view"] = self.stack.currentIndex() if hasattr(self, 'stack') else 0
        cfg["log_visible"] = self.log_container.isVisible() if hasattr(self, 'log_container') else True
        
        if hasattr(self.splitter, 'sizes'):
            cfg["splitter_sizes"] = self.splitter.sizes()
        
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'):
            cfg["column_widths"] = self.list_view.get_column_widths()
            cfg["sort_order"] = self.list_view.get_sort_order()
            
        ConfigManager.save(cfg)
        self.log_manager.info("Settings saved. Exiting application.", context="SYSTEM_LIFECYCLE")
        super().closeEvent(event)

    def clear_log_display(self):
        if hasattr(self, 'log_widget'):
            self.log_widget.clear()
        # Log to file that UI log was cleared
        self.log_manager.info("画面ログをクリアしました（ファイル記録は継続）。", context="UI_ACTION_CLEAR_LOG", emit_to_ui=False)