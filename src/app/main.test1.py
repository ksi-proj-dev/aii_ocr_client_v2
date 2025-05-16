import sys
import os
import json
import datetime
import time
import glob
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter, QDialog, QScrollArea,
    QFormLayout, QPushButton, QHBoxLayout
)
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient

# OcrConfirmationDialog クラス
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
        # self.text_edit.setFont(QFont("Courier New", 9)) # Optional
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

# OcrWorker クラス
class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object)
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
    all_files_processed = pyqtSignal()

    def __init__(self, api_client, files_to_process, output_folder_for_results, create_searchable_pdf,
                move_on_success_enabled, success_move_target_folder_root,
                move_on_failure_enabled, failure_move_target_folder_root,
                collision_action, input_root_folder, log_manager):
        super().__init__()
        self.api_client = api_client
        self.files_to_process = files_to_process
        self.output_folder_for_results = output_folder_for_results
        self.create_searchable_pdf = create_searchable_pdf
        self.is_running = True
        self.move_on_success_enabled = move_on_success_enabled
        self.success_move_target_folder_root = success_move_target_folder_root
        self.move_on_failure_enabled = move_on_failure_enabled
        self.failure_move_target_folder_root = failure_move_target_folder_root
        self.collision_action = collision_action
        self.input_root_folder = input_root_folder
        self.log_manager = log_manager

    def _get_unique_filepath(self, target_dir, filename):
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath):
            new_filename = f"{base} ({counter}){ext}"
            new_filepath = os.path.join(target_dir, new_filename)
            counter += 1
        return new_filepath

    def _move_file_with_collision_handling(self, source_path, target_folder_root, original_filename_for_log, preserve_subdirs=True):
        log_ctx_move = "FILE_IO_MOVE"
        if not target_folder_root:
            self.log_manager.info(f"ファイル移動スキップ（移動先未指定）: {original_filename_for_log}", context=log_ctx_move, source=source_path)
            return None, "移動先フォルダが指定されていません。"
        original_basename = os.path.basename(source_path)
        target_dir = target_folder_root
        if preserve_subdirs and self.input_root_folder and os.path.isdir(self.input_root_folder):
            try:
                relative_path_from_input = os.path.relpath(os.path.dirname(source_path), self.input_root_folder)
                if relative_path_from_input and relative_path_from_input != '.':
                    target_dir = os.path.join(target_folder_root, relative_path_from_input)
            except ValueError as e:
                self.log_manager.info(f"警告: 相対パス計算失敗。移動先はルート直下。 Src='{source_path}', Root='{self.input_root_folder}'", context=log_ctx_move, exception_info=e)
        try:
            if not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
                self.log_manager.info(f"移動先フォルダ作成: '{target_dir}'", context="FILE_IO_MKDIR")
        except OSError as e:
            msg = f"移動先フォルダ作成失敗: {target_dir}"
            self.log_manager.error(msg, context="FILE_IO_MKDIR_ERROR", exception_info=e, target_dir=target_dir)
            return None, msg
        target_filepath = os.path.join(target_dir, original_basename)
        if os.path.exists(target_filepath):
            action_taken_for_collision = ""
            if self.collision_action == "overwrite":
                action_taken_for_collision = "上書き"
                self.log_manager.info(f"ファイル名衝突: '{target_filepath}' を上書きします。", context=log_ctx_move, action=action_taken_for_collision)
            elif self.collision_action == "rename":
                action_taken_for_collision = "リネーム"
                old_target_filepath = target_filepath
                target_filepath = self._get_unique_filepath(target_dir, original_basename)
                self.log_manager.info(f"ファイル名衝突: '{old_target_filepath}' を '{target_filepath}' にリネームします。", context=log_ctx_move, action=action_taken_for_collision)
            elif self.collision_action == "skip":
                action_taken_for_collision = "スキップ"
                msg = f"ファイル移動スキップ（同名ファイル存在）: '{target_filepath}'"
                self.log_manager.info(msg, context=log_ctx_move, action=action_taken_for_collision)
                return None, msg
            else:
                msg = f"未知の衝突処理方法 '{self.collision_action}'"
                self.log_manager.error(msg, context=log_ctx_move, error_code="INVALID_COLLISION_ACTION", filename=original_basename)
                return None, msg
        try:
            shutil.move(source_path, target_filepath)
            self.log_manager.info(f"ファイル移動成功: '{source_path}' -> '{target_filepath}'", context=log_ctx_move+"_SUCCESS")
            return target_filepath, None
        except Exception as e:
            msg = f"ファイル移動失敗: '{source_path}' -> '{target_filepath}'"
            self.log_manager.error(msg, context=log_ctx_move+"_ERROR", exception_info=e, source=source_path, target=target_filepath)
            return None, msg

    def run(self):
        self.log_manager.info(f"{len(self.files_to_process)} 件のファイルのOCR処理を開始します。", context="WORKER_LIFECYCLE")
        for idx, original_file_path in enumerate(self.files_to_process):
            if not self.is_running:
                self.log_manager.info("OCR処理がユーザーによって中止されました。", context="WORKER_LIFECYCLE")
                break
            file_name_for_log = os.path.basename(original_file_path)
            self.log_manager.info(f"処理開始 ({idx + 1}/{len(self.files_to_process)}): '{file_name_for_log}'", context="WORKER_FILE_PROGRESS")
            ocr_result_json, ocr_error_info = self.api_client.read_document(original_file_path)
            self.file_processed.emit(idx, original_file_path, ocr_result_json, ocr_error_info)
            ocr_succeeded = (ocr_result_json and not ocr_error_info)
            if ocr_succeeded:
                try:
                    base, ext = os.path.splitext(file_name_for_log)
                    json_target_dir = self.output_folder_for_results
                    if self.input_root_folder and os.path.isdir(self.input_root_folder):
                        try:
                            relative_path = os.path.relpath(os.path.dirname(original_file_path), self.input_root_folder)
                            if relative_path and relative_path != '.': json_target_dir = os.path.join(self.output_folder_for_results, relative_path)
                        except ValueError: pass
                    if not os.path.exists(json_target_dir): os.makedirs(json_target_dir, exist_ok=True)
                    json_output_path = os.path.join(json_target_dir, f"{base}_ocr_result.json")
                    with open(json_output_path, 'w', encoding='utf-8') as f:
                        json.dump(ocr_result_json, f, ensure_ascii=False, indent=2)
                    self.log_manager.info(f"結果JSON保存成功: '{json_output_path}'", context="FILE_IO_SAVE")
                except Exception as e:
                    self.log_manager.error(f"結果JSON保存失敗 ({file_name_for_log})", context="FILE_IO_SAVE_ERROR", exception_info=e)
            elif ocr_error_info:
                 self.log_manager.error(f"OCR処理失敗 ({file_name_for_log})", context="WORKER_OCR_ERROR", error_details=ocr_error_info)

            pdf_created_path = None
            if self.create_searchable_pdf and self.is_running:
                self.log_manager.info(f"サーチャブルPDF作成開始: '{file_name_for_log}'", context="WORKER_PDF_CREATE")
                pdf_content, pdf_error_info = self.api_client.make_searchable_pdf(original_file_path)
                self.searchable_pdf_processed.emit(idx, original_file_path, pdf_content, pdf_error_info)
                if pdf_content and not pdf_error_info:
                    try:
                        base, ext = os.path.splitext(file_name_for_log)
                        pdf_target_dir = self.output_folder_for_results
                        if self.input_root_folder and os.path.isdir(self.input_root_folder):
                            try:
                                relative_path = os.path.relpath(os.path.dirname(original_file_path), self.input_root_folder)
                                if relative_path and relative_path != '.': pdf_target_dir = os.path.join(self.output_folder_for_results, relative_path)
                            except ValueError: pass
                        if not os.path.exists(pdf_target_dir): os.makedirs(pdf_target_dir, exist_ok=True)
                        pdf_output_path = os.path.join(pdf_target_dir, f"{base}_searchable.pdf")
                        with open(pdf_output_path, 'wb') as f: f.write(pdf_content)
                        self.log_manager.info(f"サーチャブルPDF保存成功: '{pdf_output_path}'", context="FILE_IO_SAVE")
                        pdf_created_path = pdf_output_path
                    except Exception as e:
                        self.log_manager.error(f"サーチャブルPDF保存失敗 ({file_name_for_log})", context="FILE_IO_SAVE_ERROR", exception_info=e)
                elif pdf_error_info:
                    self.log_manager.error(f"サーチャブルPDF作成失敗 ({file_name_for_log})", context="WORKER_PDF_ERROR", error_details=pdf_error_info)

            current_source_file_to_move = original_file_path
            if os.path.exists(current_source_file_to_move):
                if ocr_succeeded and self.move_on_success_enabled and self.is_running:
                    self.log_manager.info(f"OCR成功ファイルの移動開始: '{file_name_for_log}' -> DestRoot='{self.success_move_target_folder_root}'", context="WORKER_FILE_MOVE")
                    _, move_err = self._move_file_with_collision_handling(current_source_file_to_move, self.success_move_target_folder_root, file_name_for_log)
                    if move_err: self.log_manager.error(f"OCR成功ファイルの移動で問題発生: {move_err}", context="WORKER_FILE_MOVE_RESULT", filename=file_name_for_log)
                elif not ocr_succeeded and self.move_on_failure_enabled and self.is_running:
                    self.log_manager.info(f"OCR失敗ファイルの移動開始: '{file_name_for_log}' -> DestRoot='{self.failure_move_target_folder_root}'", context="WORKER_FILE_MOVE")
                    _, move_err = self._move_file_with_collision_handling(current_source_file_to_move, self.failure_move_target_folder_root, file_name_for_log)
                    if move_err: self.log_manager.error(f"OCR失敗ファイルの移動で問題発生: {move_err}", context="WORKER_FILE_MOVE_RESULT", filename=file_name_for_log)
            else:
                 self.log_manager.warning(f"移動対象の元ファイルが見つかりません（既に移動済みか削除された可能性）: '{current_source_file_to_move}'", context="WORKER_FILE_MOVE")
            time.sleep(0.01)

        self.all_files_processed.emit()
        if self.is_running:
             self.log_manager.info("全てのファイルのOCR処理が完了しました。", context="WORKER_LIFECYCLE")

    def stop(self):
        self.is_running = False
        self.log_manager.info("OCR処理の中止が要求されました。", context="WORKER_LIFECYCLE")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI inside Cube Client Ver.0.0.1")
        self.config = ConfigManager.load()

        self.log_widget = QTextEdit()
        self.log_manager = LogManager(self.log_widget)
        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.ocr_worker = None

        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700})
        state_cfg = self.config.get("window_state", "normal")
        pos_cfg = self.config.get("window_position", {"x": 100, "y": 100})
        self.resize(size_cfg["width"], size_cfg["height"])
        if "window_position" not in self.config or pos_cfg.get("x") is None or pos_cfg.get("y") is None :
            try:
                screen_geometry = QApplication.primaryScreen().geometry()
                self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e:
                self.log_manager.error("ウィンドウ中央配置に失敗しました。", context="UI_INIT", exception_info=e)
                self.move(100, 100)
        else:
            self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized": self.showMaximized()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.summary_view = SummaryView()
        self.processed_files_info = []
        self.list_view = ListView(self.processed_files_info)
        self.stack.addWidget(self.summary_view)
        self.stack.addWidget(self.list_view)
        self.splitter.addWidget(self.stack)
        self.log_header = QLabel("ログ：")
        self.log_header.setStyleSheet("margin: 5px 0px 0px 6px; padding: 0px; font-weight: bold;")
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet("margin: 0px 10px 10px 10px; font-family: Consolas, Meiryo, monospace; font-size: 9pt;")
        self.log_container = QWidget()
        log_layout_inner = QVBoxLayout(self.log_container)
        log_layout_inner.setContentsMargins(0, 0, 0, 0)
        log_layout_inner.addWidget(self.log_header)
        log_layout_inner.addWidget(self.log_widget)
        self.splitter.addWidget(self.log_container)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        self.main_layout.addWidget(self.splitter)

        self.input_folder_path = self.config.get("last_target_dir", "")
        self.output_folder_path = self.config.get("last_result_dir", "")
        self.success_move_folder_path = self.config.get("last_success_move_dir", "")
        self.failure_move_folder_path = self.config.get("last_failure_move_dir", "")

        self.setup_toolbar_and_folder_labels()

        self.is_ocr_running = False
        self.current_view = self.config.get("current_view", 0)
        self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True)
        self.log_container.setVisible(log_visible)
        self.update_ocr_controls() # ボタン状態を初期化
        self.check_both_folders_validity() # フォルダ妥当性も初期チェック
        self.log_manager.info("アプリケーション起動完了", context="SYSTEM")

    def setup_toolbar_and_folder_labels(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.input_folder_action = QAction("📂入力", self)
        self.input_folder_action.triggered.connect(self.select_input_folder)
        toolbar.addAction(self.input_folder_action)
        self.output_folder_action = QAction("📂出力(結果)", self)
        self.output_folder_action.triggered.connect(self.select_output_folder)
        toolbar.addAction(self.output_folder_action)
        self.success_move_folder_action = QAction("📂移動先(成功)", self)
        self.success_move_folder_action.triggered.connect(self.select_success_move_folder)
        toolbar.addAction(self.success_move_folder_action)
        self.failure_move_folder_action = QAction("📂移動先(失敗)", self)
        self.failure_move_folder_action.triggered.connect(self.select_failure_move_folder)
        toolbar.addAction(self.failure_move_folder_action)
        toolbar.addSeparator()
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
        self.stop_ocr_action = QAction("⏹️中止", self)
        self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr)
        toolbar.addAction(self.stop_ocr_action)
        self.reset_action = QAction("🔄リセット", self)
        self.reset_action.triggered.connect(self.confirm_reset_ui)
        self.reset_action.setEnabled(False)
        toolbar.addAction(self.reset_action)
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
        self.input_folder_label = QLabel(f"{self.input_folder_path or '未選択'}")
        folder_label_layout.addRow("入力フォルダ:", self.input_folder_label)
        self.output_folder_label = QLabel(f"{self.output_folder_path or '未選択'}")
        folder_label_layout.addRow("出力フォルダ (結果):", self.output_folder_label)
        self.success_move_folder_label = QLabel(f"{self.success_move_folder_path or '未選択'}")
        folder_label_layout.addRow("移動先 (成功時):", self.success_move_folder_label)
        self.failure_move_folder_label = QLabel(f"{self.failure_move_folder_path or '未選択'}")
        folder_label_layout.addRow("移動先 (失敗時):", self.failure_move_folder_label)
        folder_label_toolbar.addWidget(folder_label_widget)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar)
        self.insertToolBarBreak(folder_label_toolbar)

    def toggle_view(self):
        self.current_view = 1 - self.current_view
        self.stack.setCurrentIndex(self.current_view)
        self.log_manager.info(f"ビューを切り替えました: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")

    def toggle_log_display(self):
        visible = self.log_container.isVisible()
        self.log_container.setVisible(not visible)
        self.log_manager.info(f"ログ表示を{'非表示' if visible else '表示'}にしました。", context="UI_ACTION")

    def show_option_dialog(self):
        self.log_manager.info("オプションダイアログを開きます。", context="UI_ACTION")
        dialog = OptionDialog(self)
        if dialog.exec():
            self.config = ConfigManager.load() # 保存された設定を再ロード
            self.log_manager.info("オプション設定が保存・再読み込みされました。", context="CONFIG_UPDATE")
            self.api_client = CubeApiClient(self.config, self.log_manager)
        else:
            self.log_manager.info("オプション設定はキャンセルされました。", context="UI_ACTION")

    def _select_folder_generic(self, current_path_attr, last_dir_config_key, label_widget, dialog_title, log_context_prefix):
        last_dir = getattr(self, current_path_attr) or self.config.get(last_dir_config_key, os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, dialog_title, last_dir)
        if folder:
            setattr(self, current_path_attr, folder)
            label_widget.setText(folder)
            self.log_manager.info(f"{log_context_prefix}選択: {folder}", context="UI_FOLDER_SELECT")
            if current_path_attr == "input_folder_path":
                self.processed_files_info = []
                self.list_view.update_files(self.processed_files_info)
                if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
            self.check_both_folders_validity()
        else:
            self.log_manager.info(f"{log_context_prefix}選択がキャンセルされました。", context="UI_FOLDER_SELECT")

    def select_input_folder(self):
        self._select_folder_generic("input_folder_path", "last_target_dir", self.input_folder_label, "入力フォルダを選択", "入力フォルダ")

    def select_output_folder(self):
        self._select_folder_generic("output_folder_path", "last_result_dir", self.output_folder_label, "出力フォルダ（結果）を選択", "出力フォルダ(結果)")

    def select_success_move_folder(self):
        self._select_folder_generic("success_move_folder_path", "last_success_move_dir", self.success_move_folder_label, "成功ファイルの移動先フォルダを選択", "成功ファイル移動先")

    def select_failure_move_folder(self):
        self._select_folder_generic("failure_move_folder_path", "last_failure_move_dir", self.failure_move_folder_label, "失敗ファイルの移動先フォルダを選択", "失敗ファイル移動先")

    def check_both_folders_validity(self):
        input_path = self.input_folder_path
        output_path = self.output_folder_path
        is_valid = True
        error_message = None
        if not input_path or not output_path:
            is_valid = False
        elif input_path == output_path:
            is_valid = False
            error_message = "入力フォルダと出力フォルダ（結果）は同一にできません。"
        elif os.path.commonpath([input_path, output_path]) == input_path:
            is_valid = False
            error_message = "出力フォルダ（結果）は入力フォルダのサブフォルダに設定できません。"
        
        # 実行中でなければ、フォルダの妥当性に基づいて開始ボタンの有効性を設定
        # 実行中であれば、開始ボタンは常に無効
        self.start_ocr_action.setEnabled(is_valid and not self.is_ocr_running)

        if error_message:
            if not hasattr(self, '_last_folder_error') or self._last_folder_error != error_message:
                self.log_manager.warning(f"フォルダ設定警告: {error_message}", context="UI_VALIDATION")
                self._last_folder_error = error_message
        else:
            self._last_folder_error = None

    def _collect_files_from_input_folder(self):
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            self.log_manager.warning("ファイル収集スキップ: 入力フォルダが未選択または無効です。", context="FILE_SCAN")
            return []
        api_type_key = self.config.get("api_type", "cube_fullocr")
        options = self.config.get("options", {}).get(api_type_key, {})
        max_files = options.get("max_files_to_process", 100)
        recursion_depth_limit = options.get("recursion_depth", 5)
        self.log_manager.info(f"ファイル収集開始: In='{self.input_folder_path}', MaxFiles={max_files}, DepthLimit={recursion_depth_limit}", context="FILE_SCAN")
        collected_files = []
        supported_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        for root, dirs, files in os.walk(self.input_folder_path, topdown=True, followlinks=False):
            current_depth = root.replace(self.input_folder_path, '').count(os.sep) + 1 # 簡易的な深さ計算
            if current_depth > recursion_depth_limit:
                self.log_manager.info(f"  深さ制限超過 ({current_depth}/{recursion_depth_limit}): スキップ中 '{root}'", context="FILE_SCAN_DETAIL")
                dirs[:] = []
                continue
            for filename in sorted(files):
                if len(collected_files) >= max_files:
                    self.log_manager.info(f"  最大ファイル数 {max_files} に到達。収集終了。", context="FILE_SCAN")
                    return sorted(list(set(collected_files))) # ここでソートと重複排除
                file_path = os.path.join(root, filename)
                if os.path.islink(file_path):
                    self.log_manager.info(f"  シンボリックリンクスキップ: {file_path}", context="FILE_SCAN_SKIP")
                    continue
                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in supported_extensions:
                    collected_files.append(file_path)
        unique_sorted_files = sorted(list(set(collected_files))) # 最後に全体でソートと重複排除
        self.log_manager.info(f"ファイル収集完了: {len(unique_sorted_files)} 件発見。", context="FILE_SCAN", found_count=len(unique_sorted_files))
        if len(unique_sorted_files) > max_files:
            self.log_manager.info(f"最大ファイル数 {max_files} に切り詰めます。", context="FILE_SCAN")
            return unique_sorted_files[:max_files]
        return unique_sorted_files

    def _create_confirmation_summary(self, files_to_process_count, create_searchable_pdf_flag):
        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]
        summary_lines.append("<strong>【フォルダ設定】</strong>")
        summary_lines.append(f"入力フォルダ: {self.input_folder_path or '未選択'}")
        summary_lines.append(f"出力フォルダ (結果): {self.output_folder_path or '未選択'}")
        file_actions_config = self.config.get("file_actions", {})
        move_on_success = file_actions_config.get("move_on_success_enabled", False)
        success_folder_cfg = file_actions_config.get("success_folder", "OCR成功")
        # UIで選択されたフルパスがあればそれを、なければ設定名と出力フォルダから組み立てる
        actual_success_folder = self.success_move_folder_path or \
                                (os.path.join(self.output_folder_path, success_folder_cfg) if self.output_folder_path else success_folder_cfg)
        summary_lines.append(f"成功ファイル移動先: {actual_success_folder if move_on_success else '(移動しない)'}")
        move_on_failure = file_actions_config.get("move_on_failure_enabled", False)
        failure_folder_cfg = file_actions_config.get("failure_folder", "OCR失敗")
        actual_failure_folder = self.failure_move_folder_path or \
                                (os.path.join(self.output_folder_path, failure_folder_cfg) if self.output_folder_path else failure_folder_cfg)
        summary_lines.append(f"失敗ファイル移動先: {actual_failure_folder if move_on_failure else '(移動しない)'}")
        if move_on_success or move_on_failure:
             collision_map = {"overwrite": "上書き", "rename": "リネーム", "skip": "スキップ"}
             collision_act = collision_map.get(file_actions_config.get("collision_action", "rename"), "リネーム")
             summary_lines.append(f"ファイル名衝突時: {collision_act}")
        summary_lines.append("<br>")
        api_type_key = self.config.get("api_type", "cube_fullocr")
        ocr_opts = self.config.get("options", {}).get(api_type_key, {})
        summary_lines.append("<strong>【ファイル検索設定】</strong>")
        summary_lines.append(f"最大処理ファイル数: {ocr_opts.get('max_files_to_process', 100)}")
        summary_lines.append(f"再帰検索の深さ: {ocr_opts.get('recursion_depth', 5)}")
        summary_lines.append(f"処理対象ファイル数: {files_to_process_count} 件")
        summary_lines.append("<br>")
        summary_lines.append("<strong>【主要OCRオプション】</strong>")
        summary_lines.append(f"回転補正: {'ON' if ocr_opts.get('adjust_rotation', 0) == 1 else 'OFF'}")
        summary_lines.append(f"文字情報抽出: {'ON' if ocr_opts.get('character_extraction', 0) == 1 else 'OFF'}")
        summary_lines.append(f"強制結合: {'ON' if ocr_opts.get('concatenate', 1) == 1 else 'OFF'}") # デフォルトON考慮
        summary_lines.append(f"チェックボックス認識: {'ON' if ocr_opts.get('enable_checkbox', 0) == 1 else 'OFF'}")
        summary_lines.append(f"テキスト出力モード: {'全文テキストのみ' if ocr_opts.get('fulltext_output_mode', 0) == 1 else '詳細情報'}")
        summary_lines.append(f"全文テキスト改行: {'付加する' if ocr_opts.get('fulltext_linebreak_char', 0) == 1 else '付加しない'}")
        summary_lines.append(f"OCRモデル: {ocr_opts.get('ocr_model', 'katsuji')}")
        summary_lines.append(f"サーチャブルPDF作成: {'する' if create_searchable_pdf_flag else 'しない'}")
        summary_lines.append("<br>上記内容で処理を開始します。")
        return "<br>".join(summary_lines)

    def confirm_start_ocr(self):
        if not self.input_folder_path or not self.output_folder_path:
            QMessageBox.warning(self, "開始不可", "入力フォルダと出力フォルダ（結果）を選択してください。")
            self.log_manager.warning("OCR開始不可: 入力または出力フォルダ未選択。", context="OCR_FLOW_VALIDATION")
            return
        if self.is_ocr_running:
            QMessageBox.information(self, "処理中", "現在OCR処理を実行中です。")
            self.log_manager.info("OCR開始試行: 既に処理実行中。", context="OCR_FLOW_VALIDATION")
            return

        files_to_process = self._collect_files_from_input_folder()
        if not files_to_process:
            api_type_key = self.config.get("api_type", "cube_fullocr")
            options = self.config.get("options", {}).get(api_type_key, {})
            max_f = options.get('max_files_to_process', 100)
            depth = options.get('recursion_depth', 5)
            msg = f"入力フォルダに処理対象ファイルなし。MaxFiles={max_f}, Depth={depth}"
            QMessageBox.information(self, "対象ファイルなし", msg + "\n設定を確認してください。")
            self.log_manager.info(msg, context="OCR_FLOW_VALIDATION")
            return

        reply_searchable = QMessageBox.question(self, "サーチャブルPDF作成確認", "OCR結果（JSON）と合わせてサーチャブルPDFも作成しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        create_searchable_pdf = (reply_searchable == QMessageBox.StandardButton.Yes)
        self.log_manager.info(f"サーチャブルPDF作成選択: {'はい' if create_searchable_pdf else 'いいえ'}", context="OCR_CONFIG_USER_CHOICE")

        confirmation_summary = self._create_confirmation_summary(len(files_to_process), create_searchable_pdf)
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, self)
        if not confirm_dialog.exec():
            self.log_manager.info("OCR処理キャンセル（確認ダイアログ）。", context="OCR_FLOW_USER_CHOICE")
            return

        self.log_manager.info("ユーザー確認OK。OCR処理を開始します。", context="OCR_FLOW_START")
        self.log_manager.info("--- OCR実行設定スナップショット ---", context="OCR_CONFIG_BEGIN")
        # (ログ出力は _create_confirmation_summary と重複しないように主要なもの、または詳細をここに書く)
        self.log_manager.info(f"入力フォルダ: {self.input_folder_path}", context="OCR_CONFIG_BEGIN")
        self.log_manager.info(f"出力フォルダ(結果): {self.output_folder_path}", context="OCR_CONFIG_BEGIN")
        file_actions_cfg = self.config.get("file_actions", {})
        ocr_opts_cfg = self.config.get("options", {}).get(self.config.get("api_type"), {})
        self.log_manager.info(f"移動(成功):有効={file_actions_cfg.get('move_on_success_enabled')}, 先={self.success_move_folder_path or file_actions_cfg.get('success_folder')}", context="OCR_CONFIG_BEGIN")
        self.log_manager.info(f"移動(失敗):有効={file_actions_cfg.get('move_on_failure_enabled')}, 先={self.failure_move_folder_path or file_actions_cfg.get('failure_folder')}", context="OCR_CONFIG_BEGIN")
        self.log_manager.info(f"衝突処理: {file_actions_cfg.get('collision_action')}", context="OCR_CONFIG_BEGIN")
        self.log_manager.info(f"OCR Opts: MaxFiles={ocr_opts_cfg.get('max_files_to_process')}, Depth={ocr_opts_cfg.get('recursion_depth')}, Model={ocr_opts_cfg.get('ocr_model')}", context="OCR_CONFIG_BEGIN") # 他のOCRオプションもログ追加推奨
        self.log_manager.info("---------------------------------", context="OCR_CONFIG_BEGIN")

        self.is_ocr_running = True
        self.update_ocr_controls()
        self.processed_files_info = []
        for i, f_path in enumerate(files_to_process):
            try: f_size = os.path.getsize(f_path)
            except OSError: f_size = 0
            self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中", "ocr_result_summary": "", "searchable_pdf_status": "作成する" if create_searchable_pdf else "作成しない"})
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'): self.summary_view.start_processing(len(files_to_process))

        file_actions_cfg = self.config.get("file_actions", {})
        def get_abs_move_path_for_worker(user_selected_path, config_folder_name, default_subfolder_name, base_output_folder_for_results):
            # Workerに渡すパスは、ユーザーがUIでフルパスを指定していたらそれを最優先
            if user_selected_path and os.path.isabs(user_selected_path):
                return user_selected_path
            # 次にconfigファイル内の値（フルパスまたはサブフォルダ名）
            path_from_conf = config_folder_name
            if os.path.isabs(path_from_conf):
                return path_from_conf
            # 上記以外（サブフォルダ名または空）の場合は、OCR結果出力フォルダを基準にする
            # OCR結果出力フォルダが未選択の場合は、サブフォルダ名だけを返す（Worker側でエラー処理かカレント基準）
            if not base_output_folder_for_results:
                # ベースとなる出力フォルダが指定されていない場合、カレントディレクトリ基準の相対パスとして扱うか、
                # もしくはエラーとするか、または単なる名前としてWorkerに渡す。ここでは単なる名前として渡す。
                self.log_manager.warning(f"移動先フォルダの基準となる出力フォルダ(結果)が未選択です。移動先 '{path_from_conf or default_subfolder_name}' は相対パスとして扱われる可能性があります。", context="OCR_CONFIG_WARN")
                return path_from_conf or default_subfolder_name # これだと相対パスになる可能性
            return os.path.join(base_output_folder_for_results, path_from_conf or default_subfolder_name)

        actual_success_move_folder = get_abs_move_path_for_worker(self.success_move_folder_path, file_actions_cfg.get("success_folder"), "OCR成功", self.output_folder_path)
        actual_failure_move_folder = get_abs_move_path_for_worker(self.failure_move_folder_path, file_actions_cfg.get("failure_folder"), "OCR失敗", self.output_folder_path)

        self.ocr_worker = OcrWorker(
            api_client=self.api_client, files_to_process=files_to_process,
            output_folder_for_results=self.output_folder_path, create_searchable_pdf=create_searchable_pdf,
            move_on_success_enabled=file_actions_cfg.get("move_on_success_enabled", False),
            success_move_target_folder_root=actual_success_move_folder,
            move_on_failure_enabled=file_actions_cfg.get("move_on_failure_enabled", False),
            failure_move_target_folder_root=actual_failure_move_folder,
            collision_action=file_actions_cfg.get("collision_action", "rename"),
            input_root_folder=self.input_folder_path, log_manager=self.log_manager
        )
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()

    def confirm_stop_ocr(self):
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(self, "OCR中止確認", "OCR処理を中止しますか？（現在のファイル処理完了後に停止）", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.ocr_worker.stop()
                self.log_manager.info("OCR処理の中止をユーザーが指示しました。", context="OCR_FLOW_CONTROL")
        else:
            self.is_ocr_running = False # 実行中でないなら状態を更新
            self.update_ocr_controls()
            self.log_manager.info("中止試行: OCR処理は実行されていません。", context="OCR_FLOW_CONTROL")

    def update_ocr_controls(self):
        running = self.is_ocr_running
        # 開始ボタンの有効性は check_both_folders_validity にも依存するので、その結果を尊重する
        # check_both_folders_validity は self.start_ocr_action.setEnabled() を直接呼んでいるので、
        # ここでは running 状態に基づいてさらに上書きする。
        if running:
            self.start_ocr_action.setEnabled(False)
        else:
            # 実行中でなければ、フォルダの妥当性チェック結果に依存
            self.check_both_folders_validity() # これでstart_ocr_actionの有効性が設定される

        self.stop_ocr_action.setEnabled(running)
        can_reset = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        self.reset_action.setEnabled(can_reset)
        for action in [ self.input_folder_action,
                        self.output_folder_action,
                        self.success_move_folder_action,
                        self.failure_move_folder_action,
                        self.option_action]:
            action.setEnabled(not running)
        # self.log_manager.debug(f"update_ocr_controls: running={running}, start_enabled={self.start_ocr_action.isEnabled()}, stop_enabled={self.stop_ocr_action.isEnabled()}, reset_enabled={self.reset_action.isEnabled()}", context="UI_CONTROL_DEBUG")

    def on_file_ocr_processed(self, file_idx, file_path, ocr_result_json, error_info):
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.warning(f"処理済みファイル情報なし(OCR): {file_path}", context="UI_UPDATE_WARN")
            return
        if error_info:
            target_file_info["status"] = "OCR失敗"
            target_file_info["ocr_result_summary"] = error_info.get('message', '不明なエラー')
            self.log_manager.error(f"ファイル '{target_file_info['name']}' OCR失敗。", context="OCR_RESULT_UI", error_code=error_info.get('error_code'), details=error_info.get('message'), path=file_path)
            if hasattr(self.summary_view, 'increment_error_count'): self.summary_view.increment_error_count()
        elif ocr_result_json:
            target_file_info["status"] = "OCR成功"
            try:
                if isinstance(ocr_result_json, list) and len(ocr_result_json) > 0:
                    first_page_result = ocr_result_json[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                else: target_file_info["ocr_result_summary"] = "結果形式不正"
            except Exception as e:
                target_file_info["ocr_result_summary"] = "結果解析エラー"
                self.log_manager.error(f"結果JSON解析エラー ({target_file_info['name']})", context="UI_UPDATE_ERROR", exception_info=e, path=file_path)
            self.log_manager.info(f"ファイル '{target_file_info['name']}' OCR成功。", context="OCR_RESULT_UI", path=file_path)
            if hasattr(self.summary_view, 'increment_completed_count'): self.summary_view.increment_completed_count()
        else: # Should not happen if error_info is also None
            target_file_info["status"] = "OCR状態不明"
            target_file_info["ocr_result_summary"] = "レスポンスなし"
            self.log_manager.warning(f"ファイル '{target_file_info['name']}' OCRレスポンスなし(エラー情報もなし)。", context="OCR_RESULT_UI", path=file_path)
            if hasattr(self.summary_view, 'increment_error_count'): self.summary_view.increment_error_count() # 不明な場合はエラー扱いも検討
        self.list_view.update_files(self.processed_files_info) # 全体更新がシンプルで確実
        if hasattr(self.summary_view, 'increment_processed_count'): self.summary_view.increment_processed_count()

    def on_file_searchable_pdf_processed(self, file_idx, file_path, pdf_content, pdf_error_info):
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.warning(f"処理済みファイル情報なし(PDF): {file_path}", context="UI_UPDATE_WARN")
            return
        if pdf_error_info:
            target_file_info["searchable_pdf_status"] = "PDF作成失敗"
            self.log_manager.error(f"ファイル '{target_file_info['name']}' PDF作成失敗。", context="PDF_RESULT_UI", error_details=pdf_error_info, path=file_path)
        elif pdf_content:
            target_file_info["searchable_pdf_status"] = "PDF作成成功"
            self.log_manager.info(f"ファイル '{target_file_info['name']}' PDF作成成功。", context="PDF_RESULT_UI", path=file_path)
        else:
            target_file_info["searchable_pdf_status"] = "PDF状態不明"
            self.log_manager.warning(f"ファイル '{target_file_info['name']}' PDFレスポンスなし(エラー情報もなし)。", context="PDF_RESULT_UI", path=file_path)
        self.list_view.update_files(self.processed_files_info)

    def on_all_files_processed(self):
        self.is_ocr_running = False
        self.update_ocr_controls()
        final_message = "全てのファイルのOCR処理が完了しました。"
        if self.ocr_worker and not self.ocr_worker.is_running:
            final_message = "OCR処理がユーザーによって中止されました。"
        QMessageBox.information(self, "処理終了", final_message)
        self.log_manager.info(final_message, context="OCR_FLOW_END")
        self.ocr_worker = None

    def confirm_reset_ui(self):
        if self.is_ocr_running:
            QMessageBox.warning(self, "リセット不可", "OCR処理の実行中はリセットできません。")
            self.log_manager.info("リセット試行: 処理実行中のため不可。", context="UI_ACTION_RESET")
            return
        if not self.processed_files_info and not self.input_folder_path:
             self.log_manager.info("リセット: 対象データなし、入力フォルダも未選択のため、UIのみリセット。", context="UI_ACTION_RESET")
             self.perform_reset()
             return
        reply = QMessageBox.question(self, "リセット確認", "表示結果をクリアし入力フォルダを再スキャンしますか？\n（フォルダ選択は維持されます）", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log_manager.info("UIリセットとファイルリスト再読み込みをユーザーが確認。", context="UI_ACTION_RESET")
            self.perform_reset()
        else:
            self.log_manager.info("UIリセットをユーザーがキャンセル。", context="UI_ACTION_RESET")

    def perform_reset(self):
        self.log_manager.info("リセット処理開始。", context="RESET_FLOW")
        self.processed_files_info = []
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        self.log_manager.info("表示と内部処理リストをクリア。", context="RESET_FLOW")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"入力フォルダ再スキャン: {self.input_folder_path}", context="RESET_FLOW_SCAN")
            collected_files = self._collect_files_from_input_folder()
            if collected_files:
                for i, f_path in enumerate(collected_files):
                    try: f_size = os.path.getsize(f_path)
                    except OSError: f_size = 0
                    self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中(再読込)", "ocr_result_summary": "", "searchable_pdf_status": "-"})
                self.list_view.update_files(self.processed_files_info)
                if hasattr(self.summary_view, 'start_processing'):
                    self.summary_view.reset_summary() #カウンターリセット
                    self.summary_view.total_files = len(collected_files) #総数のみ更新
                    self.summary_view.update_display()
                self.log_manager.info(f"再スキャン完了: {len(collected_files)} 件発見。", context="RESET_FLOW_SCAN", count=len(collected_files))
            else: self.log_manager.info("再スキャン結果: 対象ファイルなし。", context="RESET_FLOW_SCAN")
        else: self.log_manager.info("リセット: 入力フォルダ未選択または無効。ファイルリストは空。", context="RESET_FLOW")
        self.is_ocr_running = False
        self.update_ocr_controls() # ボタン状態を更新
        self.check_both_folders_validity() # これも呼んで開始ボタンの妥当性を再評価
        self.log_manager.info("リセット処理完了。", context="RESET_FLOW")

    def closeEvent(self, event):
        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                self.log_manager.info("アプリケーション終了キャンセル（処理実行中）。", context="SYSTEM_LIFECYCLE")
                return
            else:
                if self.ocr_worker: self.ocr_worker.stop()
                self.log_manager.info("アプリケーション終了（処理実行中に強制）。", context="SYSTEM_LIFECYCLE")

        normal_geom = self.normalGeometry()
        self.config["window_state"] = "maximized" if self.isMaximized() else "normal"
        self.config["window_size"] = {"width": normal_geom.width(), "height": normal_geom.height()}
        self.config["window_position"] = {"x": normal_geom.x(), "y": normal_geom.y()}
        self.config["last_target_dir"] = self.input_folder_path
        self.config["last_result_dir"] = self.output_folder_path
        self.config["last_success_move_dir"] = self.success_move_folder_path
        self.config["last_failure_move_dir"] = self.failure_move_folder_path
        self.config["current_view"] = self.current_view
        self.config["log_visible"] = self.log_container.isVisible()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'):
            self.config["column_widths"] = self.list_view.get_column_widths()
            self.config["sort_order"] = self.list_view.get_sort_order()
        ConfigManager.save(self.config)
        self.log_manager.info("設定を保存し、アプリケーションを終了します。", context="SYSTEM_LIFECYCLE")
        super().closeEvent(event)

    def clear_log_display(self):
        self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました。", context="UI_ACTION")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())