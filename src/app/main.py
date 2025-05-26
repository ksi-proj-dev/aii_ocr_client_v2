import sys
import os
import json
import time
import shutil
import threading
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
from option_dialog import OptionDialog # option_dialog.py は出力形式UI追加版を想定
from summary_view import SummaryView
from config_manager import ConfigManager # config_manager.py は output_format対応版を想定
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient

# OcrConfirmationDialog クラス (変更なし)
class OcrConfirmationDialog(QDialog):
    def __init__(self, settings_summary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OCR実行内容の確認")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400) # 少し高さを調整
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

# OcrWorker クラス (出力形式に応じて処理を分岐)
class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object)
    searchable_pdf_processed = pyqtSignal(int, str, object, object) # PDF処理結果のシグナルは残す
    all_files_processed = pyqtSignal()

    def __init__(self, api_client, files_to_process,
                input_root_folder, log_manager, config): # create_searchable_pdf引数を削除
        super().__init__()
        self.api_client = api_client
        self.files_to_process = files_to_process
        # self.create_searchable_pdf = create_searchable_pdf # 引数から削除 (configから取得)
        self.is_running = True
        self.input_root_folder = input_root_folder
        self.log_manager = log_manager
        self.config = config
        self.log_manager.debug(
            "OcrWorker initialized.", context="WORKER_LIFECYCLE",
            num_files=len(files_to_process)
        )

    def _get_unique_filepath(self, target_dir, filename):
        # (変更なし)
        base, ext = os.path.splitext(filename)
        counter = 1; new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath): new_filename = f"{base} ({counter}){ext}"; new_filepath = os.path.join(target_dir, new_filename); counter += 1
        return new_filepath

    def _move_file_with_collision_handling(self, source_path, original_file_parent_dir, dest_subfolder_name, collision_action):
        # (変更なし)
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
        thread_id = threading.get_ident()
        self.log_manager.debug(f"OcrWorker thread started.", context="WORKER_LIFECYCLE", thread_id=thread_id, num_files=len(self.files_to_process))

        file_actions_config = self.config.get("file_actions", {})
        results_folder_name = file_actions_config.get("results_folder_name", "OCR結果")
        success_folder_name = file_actions_config.get("success_folder_name", "OCR成功")
        failure_folder_name = file_actions_config.get("failure_folder_name", "OCR失敗")
        move_on_success_enabled = file_actions_config.get("move_on_success_enabled", False)
        move_on_failure_enabled = file_actions_config.get("move_on_failure_enabled", False)
        collision_action = file_actions_config.get("collision_action", "rename")
        
        # --- ここから変更: 出力形式を取得 ---
        output_format = file_actions_config.get("output_format", "both") # デフォルトは両方
        self.log_manager.info(f"Output format setting: {output_format}", context="WORKER_CONFIG")
        # --- ここまで変更 ---

        for idx, original_file_path in enumerate(self.files_to_process):
            if not self.is_running:
                self.log_manager.info("OcrWorker run loop aborted by stop signal.", context="WORKER_LIFECYCLE")
                break
            
            original_file_parent_dir = os.path.dirname(original_file_path)
            original_file_basename = os.path.basename(original_file_path)
            base_name_for_output = os.path.splitext(original_file_basename)[0]
            self.log_manager.info(f"Processing file {idx + 1}/{len(self.files_to_process)}: {original_file_basename}", context="WORKER_FILE_PROGRESS")

            # OCR API呼び出し (JSON結果は常に取得を試みる前提)
            ocr_result_json, ocr_error_info = self.api_client.read_document(original_file_path)
            self.file_processed.emit(idx, original_file_path, ocr_result_json, ocr_error_info) # OCR結果はUIサマリー表示のため常にemit
            ocr_succeeded = (ocr_result_json and not ocr_error_info)

            json_target_parent_dir = os.path.join(original_file_parent_dir, results_folder_name)

            # --- ここから変更: JSONファイルの保存を条件分岐 ---
            should_create_json = (output_format == "json_only" or output_format == "both")
            if ocr_succeeded and should_create_json:
                if not os.path.exists(json_target_parent_dir):
                    try: os.makedirs(json_target_parent_dir, exist_ok=True)
                    except OSError as e: self.log_manager.error(f"Failed to create dir for JSON result: {json_target_parent_dir}", context="WORKER_FILE_IO_ERROR", exception_info=e)
                
                json_output_filename = f"{base_name_for_output}.json"
                json_output_path = os.path.join(json_target_parent_dir, json_output_filename)
                try:
                    with open(json_output_path, 'w', encoding='utf-8') as f: json.dump(ocr_result_json, f, ensure_ascii=False, indent=2)
                    self.log_manager.info(f"JSON result saved: '{json_output_path}'", context="WORKER_FILE_IO")
                except Exception as e:
                    self.log_manager.error(f"Failed to save JSON result for {original_file_basename}", context="WORKER_FILE_IO_ERROR", exception_info=e, path=json_output_path)
            elif ocr_succeeded and not should_create_json:
                self.log_manager.info(f"JSON file creation skipped for {original_file_basename} due to output_format setting '{output_format}'.", context="WORKER_FILE_IO")
            elif ocr_error_info: # OCR失敗時
                self.log_manager.error(f"OCR failed for {original_file_basename}, skipping JSON save.", context="WORKER_OCR_FAIL", error_details=ocr_error_info.get("message", str(ocr_error_info)))
            # --- ここまで変更 ---

            # --- ここから変更: サーチャブルPDFの作成と保存を条件分岐 ---
            should_create_pdf = (output_format == "pdf_only" or output_format == "both")
            pdf_content_for_signal, pdf_error_for_signal = None, None # シグナル用の変数を初期化
            
            if should_create_pdf and self.is_running:
                self.log_manager.info(f"Searchable PDF creation initiated for {original_file_basename} (output_format: {output_format}).", context="WORKER_PDF_CREATE_INIT")
                pdf_content, pdf_error_info = self.api_client.make_searchable_pdf(original_file_path)
                pdf_content_for_signal, pdf_error_for_signal = pdf_content, pdf_error_info # シグナル用に保存
                
                pdf_target_parent_dir = json_target_parent_dir # JSONと同じ場所 (results_folder_name を使用)
                if pdf_content and not pdf_error_info: # PDF作成成功
                    if not os.path.exists(pdf_target_parent_dir):
                        try: os.makedirs(pdf_target_parent_dir, exist_ok=True)
                        except OSError as e: self.log_manager.error(f"Failed to create dir for PDF result: {pdf_target_parent_dir}", context="WORKER_FILE_IO_ERROR", exception_info=e)

                    pdf_output_filename = f"{base_name_for_output}.pdf"
                    pdf_output_path = os.path.join(pdf_target_parent_dir, pdf_output_filename)
                    try:
                        with open(pdf_output_path, 'wb') as f: f.write(pdf_content)
                        self.log_manager.info(f"Searchable PDF saved: '{pdf_output_path}'", context="WORKER_FILE_IO")
                    except Exception as e:
                        self.log_manager.error(f"Failed to save searchable PDF for {original_file_basename}", context="WORKER_FILE_IO_ERROR", exception_info=e, path=pdf_output_path)
                elif pdf_error_info: # PDF作成失敗
                    self.log_manager.error(f"Searchable PDF creation failed for {original_file_basename}.", context="WORKER_PDF_FAIL", error_details=pdf_error_info.get("message", str(pdf_error_info)))
            elif not should_create_pdf:
                self.log_manager.info(f"Searchable PDF creation skipped for {original_file_basename} due to output_format setting '{output_format}'.", context="WORKER_PDF_CREATE_SKIP")
            
            # PDF処理結果のシグナルは、PDF作成を試みた場合のみemitする（内容がNoneでも）
            # あるいは、UI側で「作成しない」と表示するために、常にemitする（その場合はデフォルト値を設定）
            # ここでは、should_create_pdf がTrueの場合にemitする。
            if should_create_pdf:
                self.searchable_pdf_processed.emit(idx, original_file_path, pdf_content_for_signal, pdf_error_for_signal)
            else:   # PDF作成がスキップされた場合、UIにその旨を伝えるためのダミーのシグナルを発行するか検討
                    # 今回は、UI側で searchable_pdf_status の初期値が「作成しない」になっていることを利用し、
                    # PDF作成を試みなかった場合はシグナルを発行しない（UIは「作成しない」のまま）
                    # 必要なら、ここでemit(..., None, {"message": "Skipped by setting"}) のようにする
                self.searchable_pdf_processed.emit(idx, original_file_path, None, {"message": "作成対象外(設定)"})


            # --- ここまで変更 ---
            
            # 元ファイルの移動処理 (変更なし)
            current_source_file_to_move = original_file_path
            if os.path.exists(current_source_file_to_move):
                destination_subfolder_for_move = None
                if ocr_succeeded and move_on_success_enabled: destination_subfolder_for_move = success_folder_name
                elif not ocr_succeeded and move_on_failure_enabled: destination_subfolder_for_move = failure_folder_name
                if destination_subfolder_for_move and self.is_running:
                    self._move_file_with_collision_handling(current_source_file_to_move, original_file_parent_dir, destination_subfolder_for_move, collision_action)
            else: self.log_manager.warning(f"Source file for move not found: '{current_source_file_to_move}'", context="WORKER_MOVE_SRC_MISSING")
            
            time.sleep(0.01)

        self.all_files_processed.emit()
        if self.is_running: self.log_manager.info("All files processed by OcrWorker.", context="WORKER_LIFECYCLE")
        else: self.log_manager.info("OcrWorker processing was stopped.", context="WORKER_LIFECYCLE")
        self.log_manager.debug(f"OcrWorker thread finished.", context="WORKER_LIFECYCLE", thread_id=thread_id)

    def stop(self):
        # (変更なし)
        if self.is_running: self.is_running = False; self.log_manager.info("OcrWorker stop requested.", context="WORKER_LIFECYCLE")
        else: self.log_manager.debug("OcrWorker stop requested, but already not running.", context="WORKER_LIFECYCLE")


LISTVIEW_UPDATE_INTERVAL_MS = 300

class MainWindow(QMainWindow):
    def __init__(self):
        # (変更なし)
        super().__init__(); self.log_manager = LogManager();
        self.log_manager.debug("MainWindow initializing...", context="MAINWIN_LIFECYCLE");
        self.setWindowTitle("AI inside Cube Client Ver.0.0.6");
        self.config = ConfigManager.load();
        self.log_widget = QTextEdit();
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget);
        self.api_client = CubeApiClient(self.config, self.log_manager);
        self.ocr_worker = None; self.update_timer = QTimer(self);
        self.update_timer.setSingleShot(True);
        self.update_timer.timeout.connect(self.perform_batch_list_view_update);
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700});
        state_cfg = self.config.get("window_state", "normal");
        pos_cfg = self.config.get("window_position");
        self.resize(size_cfg["width"], size_cfg["height"]);
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try:
                screen_geometry = QApplication.primaryScreen().geometry();
                self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e:
                self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e);
            self.move(100, 100)
        else: self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized": self.showMaximized()
        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget);
        self.main_layout = QVBoxLayout(self.central_widget);
        self.splitter = QSplitter(Qt.Orientation.Vertical);
        
        # 上部：スタックウィジェット（サマリービューとリストビュー）
        self.stack = QStackedWidget();
        self.summary_view = SummaryView();
        self.processed_files_info = [];
        self.list_view = ListView(self.processed_files_info);
        self.stack.addWidget(self.summary_view);
        self.stack.addWidget(self.list_view);
        self.splitter.addWidget(self.stack);

        # 下部：ログ表示エリア
        self.log_container = QWidget() # まずコンテナを作成
        log_layout_inner = QVBoxLayout(self.log_container) # コンテナにレイアウトを設定
        log_layout_inner.setContentsMargins(0, 0, 0, 0) # コンテナ内部のマージンは一旦0

        self.log_header = QLabel("ログ：")
        self.log_header.setStyleSheet("margin-left: 6px; padding-bottom: 2px; font-weight: bold;")
        log_layout_inner.addWidget(self.log_header)

        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        # スクロールバー問題の切り分けのため、log_widgetのスタイルシートを一時的に元に戻すか、最小限にする
        self.log_widget.setStyleSheet("font-family: Consolas, Meiryo, monospace; font-size: 9pt;") # マージンとボーダーを削除
        # self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded) # 明示的に設定 (デフォルトだが)
        log_layout_inner.addWidget(self.log_widget)
        
        self.splitter.addWidget(self.log_container) # 次にログコンテナを追加

        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        
        # スプリッターの初期サイズを明示的に設定
        # ここで、stack と log_container の初期の高さの割合を調整してみてください。
        # 例えば、全体の高さの65%をstackに、35%をlog_containerに割り当てるなど。
        # この値はウィンドウの初期高さに基づいて調整する必要があります。
        # スプリッターのサイズが保存されていればそれを使う
        splitter_sizes = self.config.get("splitter_sizes")
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0:
            self.splitter.setSizes(splitter_sizes)
        else:
            # ウィンドウの高さに基づいて初期サイズを設定 (例)
            # self.height() はこの時点ではまだ不正確な場合があるので注意
            # 固定値や、QApplication.primaryScreen().geometry() から計算する方が良い場合もある
            default_height = 700 # 仮のデフォルトウィンドウ高さ
            initial_splitter_sizes = [int(default_height * 0.65), int(default_height * 0.35)]
            self.splitter.setSizes(initial_splitter_sizes)

        self.main_layout.addWidget(self.splitter); self.input_folder_path = self.config.get("last_target_dir", ""); self.setup_toolbar_and_folder_labels(); self.is_ocr_running = False; self.current_view = self.config.get("current_view", 0); self.stack.setCurrentIndex(self.current_view); log_visible = self.config.get("log_visible", True); self.log_container.setVisible(log_visible); self.update_ocr_controls(); self.check_input_folder_validity(); self.log_manager.info("Application initialized successfully.", context="SYSTEM_LIFECYCLE")

    def append_log_message_to_widget(self, level, message):
        # (変更なし)
        if self.log_widget:
            if level == LogLevel.ERROR: self.log_widget.append(f'<font color="red">{message}</font>')
            elif level == LogLevel.WARNING: self.log_widget.append(f'<font color="orange">{message}</font>')
            elif level == LogLevel.DEBUG: self.log_widget.append(f'<font color="gray">{message}</font>')
            else: self.log_widget.append(message)
            self.log_widget.ensureCursorVisible()

    def setup_toolbar_and_folder_labels(self):
        # (変更なし)
        toolbar = QToolBar("Main Toolbar"); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar); self.input_folder_action = QAction("📂入力", self); self.input_folder_action.triggered.connect(self.select_input_folder); toolbar.addAction(self.input_folder_action); self.toggle_view_action = QAction("📑ビュー", self); self.toggle_view_action.triggered.connect(self.toggle_view); toolbar.addAction(self.toggle_view_action); self.option_action = QAction("⚙️設定", self); self.option_action.triggered.connect(self.show_option_dialog); toolbar.addAction(self.option_action); toolbar.addSeparator(); self.start_ocr_action = QAction("▶️開始", self); self.start_ocr_action.triggered.connect(self.confirm_start_ocr); toolbar.addAction(self.start_ocr_action); self.stop_ocr_action = QAction("⏹️中止", self); self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr); toolbar.addAction(self.stop_ocr_action); self.reset_action = QAction("🔄リセット", self); self.reset_action.triggered.connect(self.confirm_reset_ui); self.reset_action.setEnabled(False); toolbar.addAction(self.reset_action); toolbar.addSeparator(); self.log_toggle_action = QAction("📄ログ表示", self); self.log_toggle_action.triggered.connect(self.toggle_log_display); toolbar.addAction(self.log_toggle_action); self.clear_log_action = QAction("🗑️ログクリア", self); self.clear_log_action.triggered.connect(self.clear_log_display); toolbar.addAction(self.clear_log_action); folder_label_toolbar = QToolBar("Folder Paths Toolbar"); folder_label_toolbar.setMovable(False); folder_label_widget = QWidget(); folder_label_layout = QFormLayout(folder_label_widget); folder_label_layout.setContentsMargins(5, 5, 5, 5); folder_label_layout.setSpacing(3); self.input_folder_label = QLabel(f"{self.input_folder_path or '未選択'}"); folder_label_layout.addRow("入力フォルダ:", self.input_folder_label); folder_label_toolbar.addWidget(folder_label_widget); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar); self.insertToolBarBreak(folder_label_toolbar)

    def toggle_view(self): # (変更なし)
        self.current_view = 1 - self.current_view; self.stack.setCurrentIndex(self.current_view); self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")
    def toggle_log_display(self): # (変更なし)
        visible = self.log_container.isVisible(); self.log_container.setVisible(not visible); self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION")
    def show_option_dialog(self): # (変更なし)
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION"); dialog = OptionDialog(self)
        if dialog.exec(): self.config = ConfigManager.load(); self.log_manager.info("Options saved and reloaded.", context="CONFIG_EVENT"); self.api_client = CubeApiClient(self.config, self.log_manager)
        else: self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

# (前のコード部分は省略)

    def select_input_folder(self): # (変更なし)
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir):
            last_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.input_folder_path = folder
            self.input_folder_label.setText(folder)
            self.log_manager.info(f"Input folder selected: {folder}", context="UI_EVENT")
            if self.update_timer.isActive():
                self.update_timer.stop()
            self.processed_files_info = []
            self.list_view.update_files(self.processed_files_info)
            if hasattr(self.summary_view, 'reset_summary'):
                self.summary_view.reset_summary()
            self.check_input_folder_validity()
        else:
            self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")

    def check_input_folder_validity(self): # (変更なし)
        is_valid = bool(self.input_folder_path and os.path.isdir(self.input_folder_path))
        if not self.is_ocr_running:
            self.start_ocr_action.setEnabled(is_valid)
        else:
            self.start_ocr_action.setEnabled(False)
        # (エラーログの部分は前回提示通り)
        if not is_valid and self.input_folder_path:
            if not hasattr(self, '_last_folder_error') or self._last_folder_error != "input_invalid":
                self.log_manager.warning(f"入力フォルダが無効です: {self.input_folder_path}", context="UI_VALIDATION_INPUT_INVALID")
                self._last_folder_error = "input_invalid"
        elif is_valid:
            self._last_folder_error = None


    def _collect_files_from_input_folder(self): # (変更なし)
        # ... (前回提示のコード) ...
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

    def _create_confirmation_summary(self, files_to_process_count): # create_searchable_pdf_flag 引数を削除
        # (変更なし - 内容は前回提示の通り)
        # ... (主要な設定項目をHTML形式でまとめる) ...
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
            "json_only": "JSONのみ", "pdf_only": "サーチャブルPDFのみ", "both": "JSON と サーチャブルPDF (両方)"
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
            collision_map = {"overwrite": "上書き", "rename": "リネーム", "skip": "スキップ"}
            collision_act = collision_map.get(file_actions_cfg.get("collision_action", "rename"), "リネーム")
            summary_lines.append(f"ファイル名衝突時 (移動先): {collision_act}")
        summary_lines.append("<br>")
        
        summary_lines.append("<strong>【ファイル検索設定】</strong>")
        summary_lines.append(f"最大処理ファイル数: {ocr_opts.get('max_files_to_process', 100)}")
        summary_lines.append(f"再帰検索の深さ (入力フォルダ自身を0): {ocr_opts.get('recursion_depth', 5)}")
        summary_lines.append(f"処理対象ファイル数 (収集結果): {files_to_process_count} 件")
        summary_lines.append("<br>")

        summary_lines.append("<strong>【主要OCRオプション】</strong>")
        summary_lines.append(f"回転補正: {'ON' if ocr_opts.get('adjust_rotation', 0) == 1 else 'OFF'}")
        summary_lines.append(f"文字情報抽出: {'ON' if ocr_opts.get('character_extraction', 0) == 1 else 'OFF'}")
        summary_lines.append(f"強制結合: {'ON' if ocr_opts.get('concatenate', 1) == 1 else 'OFF'}")
        summary_lines.append(f"チェックボックス認識: {'ON' if ocr_opts.get('enable_checkbox', 0) == 1 else 'OFF'}")
        summary_lines.append(f"テキスト出力モード: {'全文テキストのみ' if ocr_opts.get('fulltext_output_mode', 0) == 1 else '詳細情報'}")
        summary_lines.append(f"全文テキスト改行: {'付加する' if ocr_opts.get('fulltext_linebreak_char', 0) == 1 else '付加しない'}")
        summary_lines.append(f"OCRモデル: {ocr_opts.get('ocr_model', 'katsuji')}")
        summary_lines.append("<br>上記内容で処理を開始します。")
        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])


    def confirm_start_ocr(self):
        # (変更なし)
        self.log_manager.debug("Confirming OCR start...", context="OCR_FLOW")
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path): self.log_manager.warning("OCR start aborted: Input folder invalid.", context="OCR_FLOW"); return
        if self.is_ocr_running: self.log_manager.info("OCR start aborted: Already running.", context="OCR_FLOW"); return
        files_to_process = self._collect_files_from_input_folder()
        if not files_to_process: self.log_manager.info("OCR start aborted: No files to process.", context="OCR_FLOW"); return
        
        # ポップアップは削除済み
        confirmation_summary = self._create_confirmation_summary(len(files_to_process)) 
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, self)
        if not confirm_dialog.exec(): self.log_manager.info("OCR start cancelled by user (confirmation dialog).", context="OCR_FLOW"); return

        self.log_manager.info("User confirmed. Starting OCR process...", context="OCR_FLOW")
        current_config_for_run = ConfigManager.load()
        
        self.is_ocr_running = True; self.update_ocr_controls(); self.processed_files_info = []
        for i, f_path in enumerate(files_to_process):
            try: f_size = os.path.getsize(f_path)
            except OSError: f_size = 0
            output_format_cfg = current_config_for_run.get("file_actions", {}).get("output_format", "both")
            initial_pdf_status = "作成しない(設定)"
            if output_format_cfg == "pdf_only" or output_format_cfg == "both": initial_pdf_status = "処理待ち"
            self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中", "ocr_result_summary": "", "searchable_pdf_status": initial_pdf_status})
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'): self.summary_view.start_processing(len(files_to_process))
        self.log_manager.info(f"Instantiating and starting OcrWorker for {len(files_to_process)} files.", context="OCR_FLOW")
        self.ocr_worker = OcrWorker(api_client=self.api_client, files_to_process=files_to_process, input_root_folder=self.input_folder_path, log_manager=self.log_manager, config=current_config_for_run)
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed); self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed); self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()

    def confirm_stop_ocr(self):
        self.log_manager.debug("Confirming OCR stop...", context="OCR_FLOW")
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(self, "OCR中止確認", "OCR処理を中止しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("User confirmed OCR stop. Requesting worker to stop.", context="OCR_FLOW")
                self.ocr_worker.stop()
            else:
                self.log_manager.info("User cancelled OCR stop.", context="OCR_FLOW")
        else:
            self.log_manager.debug("Stop OCR requested, but OCR is not running.", context="OCR_FLOW")
            if self.is_ocr_running : # 状態の不整合があれば修正
                self.is_ocr_running = False
                self.update_ocr_controls()
                self.log_manager.warning("OCR stop: Worker not active but UI state was 'running'. Resetting UI state.", context="OCR_FLOW_STATE_MISMATCH")

    def update_ocr_controls(self):
        # (ログは整理し、主要な状態変化のみ)
        running = self.is_ocr_running
        can_start = bool(self.input_folder_path and os.path.isdir(self.input_folder_path)) and not running
        
        if self.start_ocr_action.isEnabled() != can_start :
            self.start_ocr_action.setEnabled(can_start)
        if self.stop_ocr_action.isEnabled() != running :
            self.stop_ocr_action.setEnabled(running)
        
        can_reset = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        if self.reset_action.isEnabled() != can_reset :
            self.reset_action.setEnabled(can_reset)
        
        # 他のアクションはOCR実行中でない場合のみ有効
        enable_actions_if_not_running = not running
        if self.input_folder_action.isEnabled() != enable_actions_if_not_running :
            self.input_folder_action.setEnabled(enable_actions_if_not_running)
        if self.option_action.isEnabled() != enable_actions_if_not_running :
            self.option_action.setEnabled(enable_actions_if_not_running)
        
        # --- ここから変更 ---
        # toggle_view_action は常に有効にする
        if not self.toggle_view_action.isEnabled(): # 常に有効なので、もし無効なら有効に戻す
            self.toggle_view_action.setEnabled(True)
        # --- ここまで変更 ---
        
        # self.log_manager.debug(f"OCR controls updated: running={running}", context="UI_STATE") # 必要に応じてコメント解除
        
    def perform_batch_list_view_update(self): # (変更なし)
        # ... (前回提示のコード) ...
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE");
        if self.list_view: self.list_view.update_files(self.processed_files_info)

    def on_file_ocr_processed(self, file_idx, file_path, ocr_result_json, error_info): # (変更なし)
        # ... (前回提示のコード) ...
        self.log_manager.debug(f"File OCR processed: {os.path.basename(file_path)}, Idx={file_idx}, Success={bool(ocr_result_json)}", context="CALLBACK"); target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info: self.log_manager.warning(f"No item found in processed_files_info for {file_path}", context="CALLBACK_ERROR"); return
        if error_info: target_file_info["status"] = "OCR失敗"; target_file_info["ocr_result_summary"] = error_info.get('message', '不明なエラー');
        elif ocr_result_json:
            target_file_info["status"] = "OCR成功";
            try: # サマリー生成
                if isinstance(ocr_result_json, list) and len(ocr_result_json) > 0:
                    first_page_result = ocr_result_json[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "") or first_page_result.get("aGroupingFulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                else: target_file_info["ocr_result_summary"] = "結果形式不明"
            except Exception: target_file_info["ocr_result_summary"] = "結果解析エラー"
        else: target_file_info["status"] = "OCR状態不明"; target_file_info["ocr_result_summary"] = "APIレスポンスなし";
        if hasattr(self.summary_view, 'update_counts_from_status_change'): self.summary_view.update_counts_from_status_change(target_file_info["status"]) # summary_viewの更新方法を見直すならここも
        elif hasattr(self.summary_view, 'increment_processed_count'): self.summary_view.increment_processed_count() # 古いメソッド呼び出し
        self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)


    def on_file_searchable_pdf_processed(self, file_idx, file_path, pdf_content, pdf_error_info): # (変更なし)
        # ... (前回提示のコード) ...
        self.log_manager.debug(f"File Searchable PDF processed: {os.path.basename(file_path)}, Idx={file_idx}, Success={bool(pdf_content)}", context="CALLBACK")
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info: self.log_manager.warning(f"No item found in processed_files_info for PDF {file_path}", context="CALLBACK_ERROR"); return
        current_config = ConfigManager.load() 
        output_format = current_config.get("file_actions", {}).get("output_format", "both")
        if output_format == "json_only": target_file_info["searchable_pdf_status"] = "作成しない(設定)"
        elif pdf_error_info: target_file_info["searchable_pdf_status"] = "PDF作成失敗"
        elif pdf_content: target_file_info["searchable_pdf_status"] = "PDF作成成功"
        else: target_file_info["searchable_pdf_status"] = "PDF状態不明"
        self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_all_files_processed(self): # (変更なし)
        # ... (前回提示のコード) ...
        self.log_manager.info("All files processing finished by worker.", context="OCR_FLOW_COMPLETE");
        if self.update_timer.isActive(): self.update_timer.stop()
        self.is_ocr_running = False; self.update_ocr_controls(); self.perform_batch_list_view_update()
        final_message = "全てのファイルのOCR処理が完了しました。";
        if self.ocr_worker and not self.ocr_worker.is_running: final_message = "OCR処理が中止されました。"
        QMessageBox.information(self, "処理終了", final_message); self.ocr_worker = None

    def confirm_reset_ui(self): # (変更なし)
        # ... (前回提示のコード) ...
        self.log_manager.debug("Confirming UI reset.", context="UI_ACTION")
        if self.is_ocr_running: QMessageBox.warning(self, "リセット不可", "OCR処理の実行中はリセットできません。"); return
        if not self.processed_files_info and not self.input_folder_path: QMessageBox.information(self, "リセット", "クリアするデータがありません。"); return
        if self.update_timer.isActive(): self.update_timer.stop()
        reply = QMessageBox.question(self, "リセット確認", "表示リストをクリアし入力フォルダを再スキャンしますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: self.log_manager.info("User confirmed UI reset.", context="UI_ACTION"); self.perform_reset()
        else: self.log_manager.info("User cancelled UI reset.", context="UI_ACTION")

    def perform_reset(self): # (変更なし)
        # ... (前回提示のコード) ...
        self.log_manager.info("Performing UI reset and rescan.", context="UI_ACTION_RESET"); self.processed_files_info = []; self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            collected_files = self._collect_files_from_input_folder()
            if collected_files:
                for i, f_path in enumerate(collected_files):
                    try: f_size = os.path.getsize(f_path)
                    except OSError: f_size = 0
                    self.processed_files_info.append({"no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size, "status": "待機中(再読込)", "ocr_result_summary": "", "searchable_pdf_status": "-"}) # 初期ステータス
                self.list_view.update_files(self.processed_files_info)
                if hasattr(self.summary_view, 'start_processing'): self.summary_view.reset_summary(); self.summary_view.total_files = len(collected_files); self.summary_view.update_display()
        self.is_ocr_running = False; self.update_ocr_controls(); self.check_input_folder_validity()

    def closeEvent(self, event): # (変更なし)
        # ... (前回提示のコード) ...
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

    def clear_log_display(self):
        self.log_widget.clear()
        # --- ここから変更 ---
        self.log_manager.info("画面ログをクリアしました（ファイル記録のみ）。", 
                            context="UI_ACTION_CLEAR_LOG", 
                            emit_to_ui=False) # UIへのemitをFalseに設定
        # --- ここまで変更 ---

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())