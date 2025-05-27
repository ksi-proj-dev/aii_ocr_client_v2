import sys
import os
import json
import datetime
import time
import shutil
import threading
import platform # OS判定のためインポート
import subprocess # フォルダを開くためインポート
import faulthandler
faulthandler.enable()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter, QDialog, QScrollArea,
    QFormLayout, QPushButton, QHBoxLayout
)
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient

# OcrConfirmationDialog クラス (変更なし)
# ... (OcrConfirmationDialogのコードは前回提示のまま) ...
class OcrConfirmationDialog(QDialog):
    def __init__(self, settings_summary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR実行内容の確認")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        layout = QVBoxLayout(self)
        label = QLabel("以下の内容でOCR処理を開始します。よろしいですか？")
        layout.addWidget(label)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setHtml(settings_summary)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.text_edit)
        layout.addWidget(scroll_area)
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("実行")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)
        self.setLayout(layout)


# OcrWorker クラス (変更なし)
# ... (OcrWorkerのコードは前回提示のまま) ...
class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object, object) 
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
    all_files_processed = pyqtSignal()
    def __init__(self, api_client, files_to_process, input_root_folder, log_manager, config):
        super().__init__()
        self.api_client = api_client; self.files_to_process = files_to_process; self.is_running = True
        self.input_root_folder = input_root_folder; self.log_manager = log_manager; self.config = config
        self.log_manager.debug("OcrWorker initialized.", context="WORKER_LIFECYCLE", num_files=len(files_to_process))
    def _get_unique_filepath(self, target_dir, filename):
        base, ext = os.path.splitext(filename); counter = 1; new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath): new_filename = f"{base} ({counter}){ext}"; new_filepath = os.path.join(target_dir, new_filename); counter += 1
        return new_filepath
    def _move_file_with_collision_handling(self, source_path, original_file_parent_dir, dest_subfolder_name, collision_action):
        log_ctx_move = "WORKER_MOVE"; original_basename = os.path.basename(source_path)
        self.log_manager.debug(f"Move process started for: {original_basename}", context=log_ctx_move,source=source_path, dest_parent=original_file_parent_dir, dest_subfolder=dest_subfolder_name)
        if not dest_subfolder_name: self.log_manager.warning(f"Move skipped (no dest_subfolder_name): {original_basename}", context=log_ctx_move, source=source_path); return None, "移動先サブフォルダ名が指定されていません。"
        target_dir = os.path.join(original_file_parent_dir, dest_subfolder_name)
        try:
            if not os.path.exists(target_dir): os.makedirs(target_dir, exist_ok=True)
        except OSError as e: msg = f"移動先フォルダ作成失敗: {target_dir}"; self.log_manager.error(msg, context=log_ctx_move + "_MKDIR_FAIL", exception_info=e); return None, msg
        target_filepath = os.path.join(target_dir, original_basename); moved_path_result, error_message_result = None, None
        if os.path.exists(target_filepath):
            if collision_action == "overwrite": self.log_manager.info(f"Overwriting existing file at move destination: {target_filepath}", context=log_ctx_move)
            elif collision_action == "rename": old_target_filepath = target_filepath; target_filepath = self._get_unique_filepath(target_dir, original_basename); self.log_manager.info(f"Renaming colliding file at move destination: {old_target_filepath} -> {target_filepath}", context=log_ctx_move)
            elif collision_action == "skip": msg = f"Skipping move, file exists at destination: {target_filepath}"; self.log_manager.info(msg, context=log_ctx_move); error_message_result = msg; target_filepath = None
            else: msg = f"Unknown collision action '{collision_action}'"; self.log_manager.error(msg, context=log_ctx_move + "_INVALID_ACTION"); error_message_result = msg; target_filepath = None
        if target_filepath and not error_message_result:
            try: shutil.move(source_path, target_filepath); self.log_manager.info(f"File moved: '{source_path}' -> '{target_filepath}'", context=log_ctx_move + "_SUCCESS"); moved_path_result = target_filepath
            except Exception as e: msg = f"File move failed: '{source_path}' -> '{target_filepath}'"; self.log_manager.error(msg, context=log_ctx_move + "_FAIL", exception_info=e); error_message_result = msg
        return moved_path_result, error_message_result
    def run(self):
        thread_id = threading.get_ident(); self.log_manager.debug(f"OcrWorker thread started.", context="WORKER_LIFECYCLE", thread_id=thread_id, num_files=len(self.files_to_process))
        file_actions_config = self.config.get("file_actions", {}); results_folder_name = file_actions_config.get("results_folder_name", "OCR結果"); success_folder_name = file_actions_config.get("success_folder_name", "OCR成功"); failure_folder_name = file_actions_config.get("failure_folder_name", "OCR失敗"); move_on_success_enabled = file_actions_config.get("move_on_success_enabled", False); move_on_failure_enabled = file_actions_config.get("move_on_failure_enabled", False); collision_action = file_actions_config.get("collision_action", "rename"); output_format = file_actions_config.get("output_format", "both")
        self.log_manager.info(f"Worker starting with Output format: {output_format}", context="WORKER_CONFIG")
        for idx, original_file_path in enumerate(self.files_to_process):
            if not self.is_running: self.log_manager.info("OcrWorker run loop aborted by stop signal.", context="WORKER_LIFECYCLE"); break
            original_file_parent_dir = os.path.dirname(original_file_path); original_file_basename = os.path.basename(original_file_path); base_name_for_output = os.path.splitext(original_file_basename)[0]
            self.log_manager.info(f"Processing file {idx + 1}/{len(self.files_to_process)}: {original_file_basename}", context="WORKER_FILE_PROGRESS")
            ocr_result_json, ocr_error_info = self.api_client.read_document(original_file_path)
            ocr_succeeded = (ocr_result_json and not ocr_error_info)
            json_target_parent_dir = os.path.join(original_file_parent_dir, results_folder_name); should_create_json = (output_format == "json_only" or output_format == "both"); json_save_info_for_signal = None
            if ocr_succeeded and should_create_json:
                if not os.path.exists(json_target_parent_dir):
                    try: os.makedirs(json_target_parent_dir, exist_ok=True)
                    except OSError as e: self.log_manager.error(f"Failed to create dir for JSON result: {json_target_parent_dir}", context="WORKER_FILE_IO_ERROR", exception_info=e); json_save_info_for_signal = {"error": "JSON保存先フォルダ作成失敗", "details": str(e)}
                if not json_save_info_for_signal:
                    json_output_filename = f"{base_name_for_output}.json"; json_output_path = os.path.join(json_target_parent_dir, json_output_filename)
                    try:
                        with open(json_output_path, 'w', encoding='utf-8') as f: json.dump(ocr_result_json, f, ensure_ascii=False, indent=2)
                        self.log_manager.info(f"JSON result saved: '{json_output_path}'", context="WORKER_FILE_IO"); json_save_info_for_signal = json_output_path
                    except Exception as e: self.log_manager.error(f"Failed to save JSON result for {original_file_basename}", context="WORKER_FILE_IO_ERROR", exception_info=e, path=json_output_path); json_save_info_for_signal = {"error": "JSONファイル保存失敗", "details": str(e)}
            elif ocr_succeeded and not should_create_json: self.log_manager.info(f"JSON file creation skipped for {original_file_basename} (output_format: '{output_format}').", context="WORKER_FILE_IO"); json_save_info_for_signal = "作成しない(設定)"
            elif ocr_error_info: self.log_manager.error(f"OCR failed for {original_file_basename}, skipping JSON save.", context="WORKER_OCR_FAIL", error_details=ocr_error_info.get("message", str(ocr_error_info))); json_save_info_for_signal = {"error": "OCR失敗のためJSON作成スキップ", "details": ocr_error_info.get("message")}
            else: json_save_info_for_signal = "対象外または不明"
            self.file_processed.emit(idx, original_file_path, ocr_result_json, ocr_error_info, json_save_info_for_signal)
            should_create_pdf = (output_format == "pdf_only" or output_format == "both"); pdf_content_for_signal, pdf_error_for_signal = None, None
            if should_create_pdf and self.is_running:
                self.log_manager.info(f"Searchable PDF creation initiated for {original_file_basename} (output_format: {output_format}).", context="WORKER_PDF_CREATE_INIT")
                pdf_content, pdf_error_info = self.api_client.make_searchable_pdf(original_file_path); pdf_content_for_signal, pdf_error_for_signal = pdf_content, pdf_error_info
                pdf_target_parent_dir = json_target_parent_dir
                if pdf_content and not pdf_error_info:
                    if not os.path.exists(pdf_target_parent_dir):
                        try: os.makedirs(pdf_target_parent_dir, exist_ok=True)
                        except OSError as e: self.log_manager.error(f"Failed to create dir for PDF result: {pdf_target_parent_dir}", context="WORKER_FILE_IO_ERROR", exception_info=e)
                    if os.path.exists(pdf_target_parent_dir):
                        pdf_output_filename = f"{base_name_for_output}.pdf"; pdf_output_path = os.path.join(pdf_target_parent_dir, pdf_output_filename)
                        try:
                            with open(pdf_output_path, 'wb') as f: f.write(pdf_content)
                            self.log_manager.info(f"Searchable PDF saved: '{pdf_output_path}'", context="WORKER_FILE_IO")
                        except Exception as e: self.log_manager.error(f"Failed to save searchable PDF for {original_file_basename}", context="WORKER_FILE_IO_ERROR", exception_info=e, path=pdf_output_path); pdf_error_for_signal = pdf_error_for_signal or {"error": "PDFファイル保存失敗", "details": str(e)}
                elif pdf_error_info: self.log_manager.error(f"Searchable PDF creation failed for {original_file_basename}.", context="WORKER_PDF_FAIL", error_details=pdf_error_info.get("message", str(pdf_error_info)))
            elif not should_create_pdf: self.log_manager.info(f"Searchable PDF creation skipped for {original_file_basename} (output_format: '{output_format}').", context="WORKER_PDF_CREATE_SKIP")
            if should_create_pdf: self.searchable_pdf_processed.emit(idx, original_file_path, pdf_content_for_signal, pdf_error_for_signal)
            else: self.searchable_pdf_processed.emit(idx, original_file_path, None, {"message": "作成対象外(設定)"})
            current_source_file_to_move = original_file_path
            if os.path.exists(current_source_file_to_move):
                destination_subfolder_for_move = None
                if ocr_succeeded and move_on_success_enabled: destination_subfolder_for_move = success_folder_name
                elif not ocr_succeeded and move_on_failure_enabled: destination_subfolder_for_move = failure_folder_name
                if destination_subfolder_for_move and self.is_running: self._move_file_with_collision_handling(current_source_file_to_move, original_file_parent_dir, destination_subfolder_for_move, collision_action)
            else: self.log_manager.warning(f"Source file for move not found: '{current_source_file_to_move}'", context="WORKER_MOVE_SRC_MISSING")
            time.sleep(0.01)
        self.all_files_processed.emit()
        if self.is_running: self.log_manager.info("All files processed by OcrWorker.", context="WORKER_LIFECYCLE")
        else: self.log_manager.info("OcrWorker processing was stopped.", context="WORKER_LIFECYCLE")
        self.log_manager.debug(f"OcrWorker thread finished.", context="WORKER_LIFECYCLE", thread_id=thread_id)
    def stop(self):
        if self.is_running: self.is_running = False; self.log_manager.info("OcrWorker stop requested.", context="WORKER_LIFECYCLE")
        else: self.log_manager.debug("OcrWorker stop requested, but already not running.", context="WORKER_LIFECYCLE")

LISTVIEW_UPDATE_INTERVAL_MS = 300

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.log_manager = LogManager()
        self.log_manager.debug("MainWindow initializing...", context="MAINWIN_LIFECYCLE")
        self.setWindowTitle("AI inside Cube Client Ver.0.0.12") # バージョンアップ
        self.config = ConfigManager.load()

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
        self.splitter = QSplitter(Qt.Orientation.Vertical); self.stack = QStackedWidget(); self.summary_view = SummaryView(); self.processed_files_info = []; self.list_view = ListView(self.processed_files_info); self.stack.addWidget(self.summary_view); self.stack.addWidget(self.list_view); self.splitter.addWidget(self.stack)
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
        
        self.input_folder_path = self.config.get("last_target_dir", "")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT")
            self.perform_initial_scan() 
        elif self.input_folder_path:
            self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT")
            self.input_folder_path = ""
        else: self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT")

        self.setup_toolbar_and_folder_labels() # ラベルの初期テキスト設定を含む
        self.is_ocr_running = False; self.current_view = self.config.get("current_view", 0); self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True); self.log_container.setVisible(log_visible)
        self.update_ocr_controls(); self.check_input_folder_validity()
        self.log_manager.info("Application initialized successfully.", context="SYSTEM_LIFECYCLE")

    def perform_initial_scan(self): # (変更なし)
        self.log_manager.info(f"起動時スキャン開始: {self.input_folder_path}", context="SYSTEM_INIT_SCAN");
        if self.update_timer.isActive(): self.update_timer.stop()
        self.processed_files_info = []
        collected_files = self._collect_files_from_input_folder()
        if collected_files:
            current_config = ConfigManager.load(); output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both"); initial_json_status = "作成しない(設定)"; initial_pdf_status = "作成しない(設定)"
            if output_format_cfg == "json_only" or output_format_cfg == "both": initial_json_status = "-"
            if output_format_cfg == "pdf_only" or output_format_cfg == "both": initial_pdf_status = "-"
            for i, f_path in enumerate(collected_files):
                try: f_size = os.path.getsize(f_path)
                except OSError: f_size = 0
                self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中", "ocr_result_summary": "", "json_status": initial_json_status, "searchable_pdf_status": initial_pdf_status})
            self.list_view.update_files(self.processed_files_info)
            if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
            if hasattr(self.summary_view, 'start_processing'): self.summary_view.total_files = len(collected_files); self.summary_view.update_display()
            self.log_manager.info(f"起動時スキャン完了: {len(collected_files)}件のファイルをリスト表示しました。", context="SYSTEM_INIT_SCAN", count=len(collected_files))
        else: self.list_view.update_files([]);
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        self.log_manager.info("起動時スキャン: 対象ファイルは見つかりませんでした。", context="SYSTEM_INIT_SCAN")

    def append_log_message_to_widget(self, level, message): # (変更なし)
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
        self.stop_ocr_action = QAction("⏹️中止", self); self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr); toolbar.addAction(self.stop_ocr_action)
        self.rescan_action = QAction("🔄再スキャン", self); self.rescan_action.triggered.connect(self.confirm_rescan_ui); self.rescan_action.setEnabled(False); toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        self.log_toggle_action = QAction("📄ログ表示", self); self.log_toggle_action.triggered.connect(self.toggle_log_display); toolbar.addAction(self.log_toggle_action)
        self.clear_log_action = QAction("🗑️ログクリア", self); self.clear_log_action.triggered.connect(self.clear_log_display); toolbar.addAction(self.clear_log_action)
        
        folder_label_toolbar = QToolBar("Folder Paths Toolbar"); folder_label_toolbar.setMovable(False)
        folder_label_widget = QWidget(); folder_label_layout = QFormLayout(folder_label_widget)
        folder_label_layout.setContentsMargins(5, 5, 5, 5); folder_label_layout.setSpacing(3)
        
        # --- ここから変更: QLabel を QPushButton に変更 ---
        self.input_folder_button = QPushButton(f"{self.input_folder_path or '未選択'}")
        self.input_folder_button.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                text-align: left;
                padding: 0px; /* パディングを調整 */
                margin: 0px;  /* マージンを調整 */
            }
            QPushButton:hover {
                text-decoration: underline; /* ホバー時に下線 */
                color: blue; /* ホバー時に色変更 */
            }
        """)
        self.input_folder_button.setFlat(True) # よりラベルっぽくする
        self.input_folder_button.setCursor(Qt.CursorShape.PointingHandCursor) # カーソルを手指に
        self.input_folder_button.clicked.connect(self.open_input_folder_in_explorer)
        folder_label_layout.addRow("入力フォルダ:", self.input_folder_button)
        # --- ここまで変更 ---
        
        folder_label_toolbar.addWidget(folder_label_widget)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar)
        self.insertToolBarBreak(folder_label_toolbar)

    # --- ここから変更: open_input_folder_in_explorer メソッドを新規作成 ---
    def open_input_folder_in_explorer(self):
        self.log_manager.debug(f"Attempting to open folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            try:
                if platform.system() == "Windows":
                    # os.startfile() はstr型でないとエラーになることがあるため、正規化
                    norm_path = os.path.normpath(self.input_folder_path)
                    os.startfile(norm_path)
                elif platform.system() == "Darwin": # macOS
                    subprocess.run(['open', self.input_folder_path], check=True)
                else: # Linuxなど
                    subprocess.run(['xdg-open', self.input_folder_path], check=True)
                self.log_manager.info(f"Successfully opened folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
            except Exception as e:
                self.log_manager.error(f"Failed to open folder '{self.input_folder_path}'. Error: {e}", context="UI_ACTION_OPEN_FOLDER_ERROR", exception_info=e)
                QMessageBox.warning(self, "フォルダを開けません", f"フォルダ '{self.input_folder_path}' を開けませんでした。\nエラー: {e}")
        else:
            self.log_manager.warning(f"Cannot open folder: Path is invalid or not set. Path: '{self.input_folder_path}'", context="UI_ACTION_OPEN_FOLDER_INVALID")
            QMessageBox.information(self, "フォルダ情報なし", "入力フォルダが選択されていないか、無効なパスです。")
    # --- ここまで変更 ---

    def toggle_view(self): # (変更なし)
        self.current_view = 1 - self.current_view; self.stack.setCurrentIndex(self.current_view); self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")
    def toggle_log_display(self): # (変更なし)
        visible = self.log_container.isVisible(); self.log_container.setVisible(not visible); self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION")

    def show_option_dialog(self):
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION")
        dialog = OptionDialog(self)
        if dialog.exec():
            self.config = ConfigManager.load()
            self.log_manager.info("Options saved and reloaded.", context="CONFIG_EVENT")
            self.api_client = CubeApiClient(self.config, self.log_manager)

            new_output_format = self.config.get("file_actions", {}).get("output_format", "both")
            self.log_manager.info(f"Output format changed to: {new_output_format}. Updating unprocessed items status.", context="CONFIG_EVENT")
            updated_count = 0
            for item_info in self.processed_files_info:
                if item_info.get("status") == "待機中" or \
                    item_info.get("status") == "待機中(再スキャン)" or \
                    item_info.get("status") == "-": # 初期状態なども考慮

                    old_json_status = item_info.get("json_status")
                    old_pdf_status = item_info.get("searchable_pdf_status")

                    if new_output_format == "json_only" or new_output_format == "both":
                        item_info["json_status"] = "-" 
                    else:
                        item_info["json_status"] = "作成しない(設定)"

                    if new_output_format == "pdf_only" or new_output_format == "both":
                        item_info["searchable_pdf_status"] = "-"
                    else:
                        item_info["searchable_pdf_status"] = "作成しない(設定)"
                    
                    if old_json_status != item_info["json_status"] or \
                        old_pdf_status != item_info["searchable_pdf_status"]:
                        updated_count += 1
            
            if updated_count > 0:
                self.log_manager.info(f"{updated_count} unprocessed items' output status expectations were updated.", context="CONFIG_EVENT")
                self.list_view.update_files(self.processed_files_info)
        else:
            self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

    def select_input_folder(self):
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.log_manager.info(f"Input folder selected by user: {folder}", context="UI_EVENT")
            self.input_folder_path = folder
            # --- ここから変更: ラベルではなくボタンのテキストを更新 ---
            self.input_folder_button.setText(folder) 
            # --- ここまで変更 ---
            self.log_manager.info(f"Performing rescan for newly selected folder: {folder}", context="UI_EVENT")
            self.perform_rescan()
        else:
            self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")

    def check_input_folder_validity(self): # (変更なし)
        is_valid = bool(self.input_folder_path and os.path.isdir(self.input_folder_path))
        if not self.is_ocr_running: self.start_ocr_action.setEnabled(is_valid)
        else: self.start_ocr_action.setEnabled(False)
    def _collect_files_from_input_folder(self): # (変更なし)
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path): self.log_manager.warning("File collection skipped: Input folder invalid.", context="FILE_SCAN"); return []
        current_config = ConfigManager.load(); file_actions_config = current_config.get("file_actions", {}); excluded_folder_names = [name for name in [file_actions_config.get("success_folder_name"), file_actions_config.get("failure_folder_name"), file_actions_config.get("results_folder_name")] if name and name.strip()]
        options_cfg = current_config.get("options", {}).get(current_config.get("api_type"), {}); max_files = options_cfg.get("max_files_to_process", 100); recursion_depth_limit = options_cfg.get("recursion_depth", 5)
        self.log_manager.info(f"File collection started: In='{self.input_folder_path}', Max={max_files}, DepthLimit={recursion_depth_limit}, Exclude={excluded_folder_names}", context="FILE_SCAN")
        collected_files = []; supported_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        for root, dirs, files in os.walk(self.input_folder_path, topdown=True, followlinks=False):
            norm_root = os.path.normpath(root); norm_input_root = os.path.normpath(self.input_folder_path); relative_path_from_input = os.path.relpath(norm_root, norm_input_root)
            current_depth = 0 if relative_path_from_input == "." else len(relative_path_from_input.split(os.sep))
            if current_depth >= recursion_depth_limit: dirs[:] = []; continue
            dirs_to_remove_from_walk = [d for d in dirs if d in excluded_folder_names];
            for d_to_remove in dirs_to_remove_from_walk:
                if d_to_remove in dirs: dirs.remove(d_to_remove)
            for filename in sorted(files):
                if len(collected_files) >= max_files: self.log_manager.info(f"Max files ({max_files}) reached.", context="FILE_SCAN"); return sorted(list(set(collected_files)))
                file_path = os.path.join(root, filename)
                if os.path.islink(file_path): continue
                if os.path.splitext(filename)[1].lower() in supported_extensions: collected_files.append(file_path)
        unique_sorted_files = sorted(list(set(collected_files)))
        self.log_manager.info(f"File collection finished: Found {len(unique_sorted_files)} files.", context="FILE_SCAN", count=len(unique_sorted_files))
        return unique_sorted_files

    def _create_confirmation_summary(self, files_to_process_count): # (変更なし)
        current_config = ConfigManager.load(); file_actions_cfg = current_config.get("file_actions", {}); api_type_key = current_config.get("api_type", "cube_fullocr"); ocr_opts = current_config.get("options", {}).get(api_type_key, {})
        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]; summary_lines.append("<strong>【基本設定】</strong>"); summary_lines.append(f"入力フォルダ: {self.input_folder_path or '未選択'}"); summary_lines.append("<br>"); summary_lines.append("<strong>【ファイル処理後の出力と移動】</strong>")
        output_format_value = file_actions_cfg.get("output_format", "both"); output_format_display_map = {"json_only": "JSONのみ", "pdf_only": "サーチャブルPDFのみ", "both": "JSON と サーチャブルPDF (両方)"}; output_format_display = output_format_display_map.get(output_format_value, "未設定/不明"); summary_lines.append(f"出力形式: <strong>{output_format_display}</strong>")
        results_folder_name = file_actions_cfg.get("results_folder_name", "(未設定)"); summary_lines.append(f"OCR結果サブフォルダ名: <strong>{results_folder_name}</strong>"); summary_lines.append(f"  <small>(備考: 元ファイルの各場所に '{results_folder_name}' サブフォルダを作成し結果を保存)</small>")
        move_on_success = file_actions_cfg.get("move_on_success_enabled", False); success_folder_name_cfg = file_actions_cfg.get("success_folder_name", "(未設定)"); summary_lines.append(f"成功ファイル移動: {'<strong>する</strong>' if move_on_success else 'しない'}");
        if move_on_success: summary_lines.append(f"  移動先サブフォルダ名: <strong>{success_folder_name_cfg}</strong>"); summary_lines.append(f"    <small>(備考: 元ファイルの各場所に '{success_folder_name_cfg}' サブフォルダを作成し移動)</small>")
        move_on_failure = file_actions_cfg.get("move_on_failure_enabled", False); failure_folder_name_cfg = file_actions_cfg.get("failure_folder_name", "(未設定)"); summary_lines.append(f"失敗ファイル移動: {'<strong>する</strong>' if move_on_failure else 'しない'}");
        if move_on_failure: summary_lines.append(f"  移動先サブフォルダ名: <strong>{failure_folder_name_cfg}</strong>"); summary_lines.append(f"    <small>(備考: 元ファイルの各場所に '{failure_folder_name_cfg}' サブフォルダを作成し移動)</small>")
        if move_on_success or move_on_failure: collision_map = {"overwrite": "上書き", "rename": "リネーム", "skip": "スキップ"}; collision_act = collision_map.get(file_actions_cfg.get("collision_action", "rename"), "リネーム"); summary_lines.append(f"ファイル名衝突時 (移動先): {collision_act}")
        summary_lines.append("<br>"); summary_lines.append("<strong>【ファイル検索設定】</strong>"); summary_lines.append(f"最大処理ファイル数: {ocr_opts.get('max_files_to_process', 100)}"); summary_lines.append(f"再帰検索の深さ (入力フォルダ自身を0): {ocr_opts.get('recursion_depth', 5)}"); summary_lines.append(f"処理対象ファイル数 (収集結果): {files_to_process_count} 件"); summary_lines.append("<br>"); summary_lines.append("<strong>【主要OCRオプション】</strong>"); summary_lines.append(f"回転補正: {'ON' if ocr_opts.get('adjust_rotation', 0) == 1 else 'OFF'}"); summary_lines.append(f"OCRモデル: {ocr_opts.get('ocr_model', 'katsuji')}"); summary_lines.append("<br>上記内容で処理を開始します。")
        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])

    def confirm_start_ocr(self):
        self.log_manager.debug("Confirming OCR start...", context="OCR_FLOW")
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            self.log_manager.warning("OCR start aborted: Input folder invalid.", context="OCR_FLOW")
            return
        if self.is_ocr_running:
            self.log_manager.info("OCR start aborted: Already running.", context="OCR_FLOW")
            return
        
        # --- ここから変更: OCR再実行時の確認条件とメッセージ ---
        ocr_already_processed_in_list = False
        if self.processed_files_info: 
            for item in self.processed_files_info:
                item_status = item.get("status", "")
                # 「待機中」や初期状態「-」以外のステータスがあれば、何らかの処理が試みられたとみなす
                if item_status not in ["待機中", "待機中(再スキャン)", "-"]: # 初期スキャン時の「-」も未処理とみなす
                    ocr_already_processed_in_list = True
                    break
        
        if ocr_already_processed_in_list:
            message = "もう一度OCRを実行します。\n\n" \
                      "現在の進捗状況はクリアされます。\n\n" \
                      "よろしいですか？"
            reply = QMessageBox.question(self, "OCR再実行の確認", message,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                self.log_manager.info("OCR re-execution cancelled by user.", context="OCR_FLOW")
                return
        # --- ここまで変更 ---

        files_to_process = self._collect_files_from_input_folder()
        if not files_to_process:
            self.log_manager.info("OCR start aborted: No files to process after collection.", context="OCR_FLOW")
            QMessageBox.information(self,"対象ファイルなし", "入力フォルダに処理対象ファイルが見つかりませんでした。\n設定やフォルダ内容を確認してください。")
            return
        
        confirmation_summary = self._create_confirmation_summary(len(files_to_process)) 
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, self)
        if not confirm_dialog.exec():
            self.log_manager.info("OCR start cancelled by user (final confirmation dialog).", context="OCR_FLOW")
            return

        self.log_manager.info("User confirmed. Starting OCR process...", context="OCR_FLOW")
        current_config_for_run = ConfigManager.load()
        
        self.is_ocr_running = True
        self.update_ocr_controls()
        self.processed_files_info = []
        output_format_cfg = current_config_for_run.get("file_actions", {}).get("output_format", "both")
        initial_json_status_on_start = "作成しない(設定)"; initial_pdf_status_on_start = "作成しない(設定)"
        if output_format_cfg == "json_only" or output_format_cfg == "both": initial_json_status_on_start = "処理待ち"
        if output_format_cfg == "pdf_only" or output_format_cfg == "both": initial_pdf_status_on_start = "処理待ち"
        for i, f_path in enumerate(files_to_process):
            try: f_size = os.path.getsize(f_path)
            except OSError: f_size = 0
            self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中", "ocr_result_summary": "", "json_status": initial_json_status_on_start, "searchable_pdf_status": initial_pdf_status_on_start})
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'): self.summary_view.start_processing(len(files_to_process))
        self.log_manager.info(f"Instantiating and starting OcrWorker for {len(files_to_process)} files.", context="OCR_FLOW")
        self.ocr_worker = OcrWorker(api_client=self.api_client, files_to_process=files_to_process, input_root_folder=self.input_folder_path, log_manager=self.log_manager, config=current_config_for_run)
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()

    def confirm_stop_ocr(self):
        self.log_manager.debug("Confirming OCR stop...", context="OCR_FLOW")
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(self, "OCR中止確認", "OCR処理を中止しますか？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No) # Default to No
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("User confirmed OCR stop. Requesting worker to stop.", context="OCR_FLOW")
                self.ocr_worker.stop()
            else:
                self.log_manager.info("User cancelled OCR stop.", context="OCR_FLOW")
        else:
            self.log_manager.debug("Stop OCR requested, but OCR is not running.", context="OCR_FLOW")
            if self.is_ocr_running : # UI state might be inconsistent
                self.is_ocr_running = False
                self.update_ocr_controls()
                self.log_manager.warning("OCR stop: Worker not active but UI state was 'running'. Resetting UI state.", context="OCR_FLOW_STATE_MISMATCH")

    def update_ocr_controls(self): # (変更なし)
        running = self.is_ocr_running; can_start = bool(self.input_folder_path and os.path.isdir(self.input_folder_path)) and not running
        if self.start_ocr_action.isEnabled() != can_start : self.start_ocr_action.setEnabled(can_start)
        if self.stop_ocr_action.isEnabled() != running : self.stop_ocr_action.setEnabled(running)
        can_rescan = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        if self.rescan_action.isEnabled() != can_rescan : self.rescan_action.setEnabled(can_rescan)
        enable_actions_if_not_running = not running
        if self.input_folder_action.isEnabled() != enable_actions_if_not_running : self.input_folder_action.setEnabled(enable_actions_if_not_running)
        if self.option_action.isEnabled() != enable_actions_if_not_running : self.option_action.setEnabled(enable_actions_if_not_running)
        if not self.toggle_view_action.isEnabled(): self.toggle_view_action.setEnabled(True)

    def perform_batch_list_view_update(self): # (変更なし)
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE");
        if self.list_view: self.list_view.update_files(self.processed_files_info)

# class MainWindow(QMainWindow):
# ... (他のメソッドは変更なし) ...

    def on_file_ocr_processed(self, file_idx, file_path, ocr_result_json, ocr_error_info, json_save_info):
        self.log_manager.debug(
            f"File OCR processed (MainWin): {os.path.basename(file_path)}, Idx={file_idx}, Success={bool(ocr_result_json)}, JSON Save Info: {json_save_info}",
            context="CALLBACK_OCR"
        )
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.warning(f"No item found in processed_files_info for {file_path}", context="CALLBACK_ERROR")
            return

        ocr_actually_succeeded = False
        if ocr_error_info:
            target_file_info["status"] = "OCR失敗"
            target_file_info["ocr_result_summary"] = ocr_error_info.get('message', '不明なエラー')
        elif ocr_result_json:
            target_file_info["status"] = "OCR成功"
            ocr_actually_succeeded = True
            try: 
                if isinstance(ocr_result_json, list) and len(ocr_result_json) > 0:
                    first_page_result = ocr_result_json[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "") or first_page_result.get("aGroupingFulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                else: target_file_info["ocr_result_summary"] = "結果形式不明"
            except Exception: target_file_info["ocr_result_summary"] = "結果解析エラー"
        else:
            target_file_info["status"] = "OCR状態不明"
            target_file_info["ocr_result_summary"] = "APIレスポンスなし"

        if isinstance(json_save_info, str) and os.path.exists(json_save_info): target_file_info["json_status"] = "JSON作成成功"
        elif isinstance(json_save_info, str) and json_save_info == "作成しない(設定)": target_file_info["json_status"] = "作成しない(設定)"
        elif isinstance(json_save_info, dict) and "error" in json_save_info: target_file_info["json_status"] = "JSON作成失敗"
        elif ocr_error_info: target_file_info["json_status"] = "対象外(OCR失敗)"
        else: target_file_info["json_status"] = "JSON状態不明"
        
        if hasattr(self.summary_view, 'update_for_processed_file'):
            self.summary_view.update_for_processed_file(is_success=ocr_actually_succeeded)
        
        self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_file_searchable_pdf_processed(self, file_idx, file_path, pdf_content, pdf_error_info): # (変更なし)
        self.log_manager.debug(f"File Searchable PDF processed: {os.path.basename(file_path)}, Idx={file_idx}, Success={bool(pdf_content)}", context="CALLBACK_PDF"); target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info: self.log_manager.warning(f"No item found in processed_files_info for PDF {file_path}", context="CALLBACK_ERROR"); return
        current_config = ConfigManager.load(); output_format = current_config.get("file_actions", {}).get("output_format", "both")
        if output_format == "json_only": target_file_info["searchable_pdf_status"] = "作成しない(設定)"
        elif isinstance(pdf_error_info, dict) and pdf_error_info.get("message") == "作成対象外(設定)": target_file_info["searchable_pdf_status"] = "作成しない(設定)"
        elif pdf_error_info: target_file_info["searchable_pdf_status"] = "PDF作成失敗"
        elif pdf_content: target_file_info["searchable_pdf_status"] = "PDF作成成功"
        else: target_file_info["searchable_pdf_status"] = "PDF状態不明"
        self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_all_files_processed(self): # (変更なし)
        self.log_manager.info("All files processing finished by worker.", context="OCR_FLOW_COMPLETE");
        if self.update_timer.isActive(): self.update_timer.stop()
        self.is_ocr_running = False; self.update_ocr_controls(); self.perform_batch_list_view_update()
        final_message = "全てのファイルのOCR処理が完了しました。";
        if self.ocr_worker and not self.ocr_worker.is_running: final_message = "OCR処理が中止されました。"
        QMessageBox.information(self, "処理終了", final_message); self.ocr_worker = None
    
    def confirm_rescan_ui(self): # (変更なし)
        self.log_manager.debug("Confirming UI rescan.", context="UI_ACTION")
        if self.is_ocr_running: QMessageBox.warning(self, "再スキャン不可", "OCR処理の実行中は再スキャンできません。"); return
        if not self.processed_files_info and not self.input_folder_path: QMessageBox.information(self, "再スキャン", "クリアまたは再スキャンする対象がありません。"); return
        if self.update_timer.isActive(): self.update_timer.stop()
        message = "入力フォルダが再スキャンされます。\n\n現在の進捗状況はクリアされます。\n\nよろしいですか？"; # メッセージ変更済み
        reply = QMessageBox.question(self, "再スキャン確認", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: self.log_manager.info("User confirmed UI rescan.", context="UI_ACTION"); self.perform_rescan()
        else: self.log_manager.info("User cancelled UI rescan.", context="UI_ACTION")

    def perform_rescan(self): # (変更なし)
        self.log_manager.info("Performing UI clear and input folder rescan.", context="UI_ACTION_RESCAN"); self.processed_files_info = []; self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"Rescanning input folder: {self.input_folder_path}", context="UI_ACTION_RESCAN")
            collected_files = self._collect_files_from_input_folder()
            if collected_files:
                current_config = ConfigManager.load(); output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both"); initial_json_status_on_rescan = "作成しない(設定)"; initial_pdf_status_on_rescan = "作成しない(設定)"
                if output_format_cfg == "json_only" or output_format_cfg == "both": initial_json_status_on_rescan = "-"
                if output_format_cfg == "pdf_only" or output_format_cfg == "both": initial_pdf_status_on_rescan = "-" 
                for i, f_path in enumerate(collected_files):
                    try: f_size = os.path.getsize(f_path)
                    except OSError: f_size = 0
                    self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中", "ocr_result_summary": "", "json_status": initial_json_status_on_rescan, "searchable_pdf_status": initial_pdf_status_on_rescan})
                self.list_view.update_files(self.processed_files_info)
                if hasattr(self.summary_view, 'start_processing'): self.summary_view.reset_summary(); self.summary_view.total_files = len(collected_files); self.summary_view.update_display()
                self.log_manager.info(f"Rescan complete: {len(collected_files)} files listed.", context="UI_ACTION_RESCAN", count=len(collected_files))
            else: self.log_manager.info("Rescan: No files found in input folder.", context="UI_ACTION_RESCAN")
        else: self.log_manager.info("Rescan: Input folder not set or invalid. File list cleared.", context="UI_ACTION_RESCAN")
        self.is_ocr_running = False; self.update_ocr_controls(); self.check_input_folder_validity()

    def closeEvent(self, event): # (変更なし)
        self.log_manager.debug("Application closeEvent triggered.", context="SYSTEM_LIFECYCLE");
        if self.update_timer.isActive(): self.update_timer.stop()
        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: event.ignore(); return
            else:
                if self.ocr_worker and self.ocr_worker.isRunning(): self.ocr_worker.stop()
        current_config_to_save = self.config.copy(); normal_geom = self.normalGeometry(); current_config_to_save["window_state"] = "maximized" if self.isMaximized() else "normal"; current_config_to_save["window_size"] = {"width": normal_geom.width(), "height": normal_geom.height()}
        if not self.isMaximized(): current_config_to_save["window_position"] = {"x": normal_geom.x(), "y": normal_geom.y()}
        elif "window_position" in current_config_to_save: del current_config_to_save["window_position"]
        current_config_to_save["last_target_dir"] = self.input_folder_path; current_config_to_save["current_view"] = self.current_view; current_config_to_save["log_visible"] = self.log_container.isVisible()
        if hasattr(self.splitter, 'sizes'): current_config_to_save["splitter_sizes"] = self.splitter.sizes()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'): current_config_to_save["column_widths"] = self.list_view.get_column_widths(); current_config_to_save["sort_order"] = self.list_view.get_sort_order()
        ConfigManager.save(current_config_to_save); self.log_manager.info("Settings saved. Exiting application.", context="SYSTEM_LIFECYCLE"); super().closeEvent(event)

    def clear_log_display(self): # (変更なし)
        self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました（ファイル記録のみ）。", context="UI_ACTION_CLEAR_LOG", emit_to_ui=False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())