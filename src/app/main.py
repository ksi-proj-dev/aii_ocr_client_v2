import sys
import os
import json
import datetime
import time
# import glob # OcrWorker内では直接使われなくなった
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

# OcrConfirmationDialog クラス (変更なし)
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

# OcrWorker クラス (今回の変更対象)
class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object)
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
    all_files_processed = pyqtSignal()

    def __init__(self, api_client, files_to_process, create_searchable_pdf,
                input_root_folder, log_manager, config): # 引数からパス関連を削除しconfigを追加
        super().__init__()
        self.api_client = api_client
        self.files_to_process = files_to_process
        self.create_searchable_pdf = create_searchable_pdf
        self.is_running = True
        self.input_root_folder = input_root_folder # これはファイル収集時のルートとして使用
        self.log_manager = log_manager
        self.config = config # ConfigManagerから読み込んだ設定全体を保持

    def _get_unique_filepath(self, target_dir, filename):
        """指定されたディレクトリ内でユニークなファイルパスを生成する。"""
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath):
            new_filename = f"{base} ({counter}){ext}"
            new_filepath = os.path.join(target_dir, new_filename)
            counter += 1
        return new_filepath

    def _move_file_with_collision_handling(self, source_path, original_file_parent_dir, dest_subfolder_name, collision_action):
        """
        ファイルを指定されたサブフォルダに移動する。衝突時の処理も行う。
        original_file_parent_dir: 元ファイルの親ディレクトリ
        dest_subfolder_name: 移動先のサブフォルダ名 (例: "OCR成功")
        """
        log_ctx_move = "FILE_IO_MOVE"
        original_basename = os.path.basename(source_path)

        if not dest_subfolder_name: # 通常はOptionDialogで必須入力になっているはず
            self.log_manager.warning(f"ファイル移動スキップ（移動先サブフォルダ名未指定）: {original_basename}", context=log_ctx_move, source=source_path)
            return None, "移動先サブフォルダ名が指定されていません。"

        # 移動先ディレクトリのフルパスを決定
        target_dir = os.path.join(original_file_parent_dir, dest_subfolder_name)

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
            if collision_action == "overwrite":
                action_taken_for_collision = "上書き"
                self.log_manager.info(f"ファイル名衝突 (移動先): '{target_filepath}' を上書きします。", context=log_ctx_move, action=action_taken_for_collision)
            elif collision_action == "rename":
                action_taken_for_collision = "リネーム"
                old_target_filepath = target_filepath
                target_filepath = self._get_unique_filepath(target_dir, original_basename)
                self.log_manager.info(f"ファイル名衝突 (移動先): '{old_target_filepath}' を '{target_filepath}' にリネームします。", context=log_ctx_move, action=action_taken_for_collision)
            elif collision_action == "skip":
                action_taken_for_collision = "スキップ"
                msg = f"ファイル移動スキップ（同名ファイルが移動先に存在）: '{target_filepath}'"
                self.log_manager.info(msg, context=log_ctx_move, action=action_taken_for_collision)
                return None, msg # スキップ時はエラーメッセージを返す
            else: # 未知の衝突処理
                msg = f"未知のファイル名衝突処理方法 '{collision_action}' が指定されました。"
                self.log_manager.error(msg, context=log_ctx_move, error_code="INVALID_COLLISION_ACTION", filename=original_basename)
                return None, msg
        try:
            shutil.move(source_path, target_filepath)
            self.log_manager.info(f"ファイル移動成功: '{source_path}' -> '{target_filepath}'", context=log_ctx_move+"_SUCCESS")
            return target_filepath, None # 成功時はエラーメッセージなし
        except Exception as e:
            msg = f"ファイル移動失敗: '{source_path}' -> '{target_filepath}'"
            self.log_manager.error(msg, context=log_ctx_move+"_ERROR", exception_info=e, source=source_path, target=target_filepath)
            return None, msg

    def run(self):
        self.log_manager.info(f"{len(self.files_to_process)} 件のファイルのOCR処理を開始します。", context="WORKER_LIFECYCLE")

        # 設定値を取得
        file_actions_config = self.config.get("file_actions", {})
        results_folder_name = file_actions_config.get("results_folder_name", "OCR結果") # デフォルト値も考慮
        success_folder_name = file_actions_config.get("success_folder_name", "OCR成功")
        failure_folder_name = file_actions_config.get("failure_folder_name", "OCR失敗")
        move_on_success_enabled = file_actions_config.get("move_on_success_enabled", False)
        move_on_failure_enabled = file_actions_config.get("move_on_failure_enabled", False)
        collision_action = file_actions_config.get("collision_action", "rename")

        for idx, original_file_path in enumerate(self.files_to_process):
            if not self.is_running:
                self.log_manager.info("OCR処理がユーザーによって中止されました。", context="WORKER_LIFECYCLE")
                break
            
            original_file_parent_dir = os.path.dirname(original_file_path)
            original_file_basename = os.path.basename(original_file_path)
            base_name_for_output = os.path.splitext(original_file_basename)[0] # 拡張子なしのファイル名

            self.log_manager.info(f"処理開始 ({idx + 1}/{len(self.files_to_process)}): '{original_file_basename}'", context="WORKER_FILE_PROGRESS")
            
            # OCR処理実行
            ocr_result_json, ocr_error_info = self.api_client.read_document(original_file_path)
            self.file_processed.emit(idx, original_file_path, ocr_result_json, ocr_error_info) # UIへ通知
            ocr_succeeded = (ocr_result_json and not ocr_error_info)

            # 結果JSONファイルの保存先ディレクトリ
            json_target_parent_dir = os.path.join(original_file_parent_dir, results_folder_name)
            
            if ocr_succeeded:
                # 結果JSONファイルの保存
                if not os.path.exists(json_target_parent_dir):
                    try: os.makedirs(json_target_parent_dir, exist_ok=True)
                    except OSError as e: self.log_manager.error(f"結果JSON用親フォルダ '{json_target_parent_dir}' 作成失敗。", context="FILE_IO_MKDIR_ERROR", exception_info=e)
                
                json_output_filename = f"{base_name_for_output}.json" # 接尾辞なし
                json_output_path = os.path.join(json_target_parent_dir, json_output_filename)
                try:
                    with open(json_output_path, 'w', encoding='utf-8') as f:
                        json.dump(ocr_result_json, f, ensure_ascii=False, indent=2)
                    self.log_manager.info(f"結果JSON保存成功: '{json_output_path}'", context="FILE_IO_SAVE")
                except Exception as e:
                    self.log_manager.error(f"結果JSON保存失敗 ({original_file_basename})", context="FILE_IO_SAVE_ERROR", exception_info=e, path=json_output_path)
            elif ocr_error_info:
                self.log_manager.error(f"OCR処理失敗 ({original_file_basename})", context="WORKER_OCR_ERROR", error_details=ocr_error_info)

            # サーチャブルPDFの作成と保存
            if self.create_searchable_pdf and self.is_running:
                self.log_manager.info(f"サーチャブルPDF作成開始: '{original_file_basename}'", context="WORKER_PDF_CREATE")
                pdf_content, pdf_error_info = self.api_client.make_searchable_pdf(original_file_path)
                self.searchable_pdf_processed.emit(idx, original_file_path, pdf_content, pdf_error_info) # UIへ通知

                # サーチャブルPDFの保存先ディレクトリ (JSONと同じ場所)
                pdf_target_parent_dir = json_target_parent_dir # results_folder_name を使用
                if not os.path.exists(pdf_target_parent_dir): # JSON保存時に作成試行済みだが念のため
                    try: os.makedirs(pdf_target_parent_dir, exist_ok=True)
                    except OSError as e: self.log_manager.error(f"サーチャブルPDF用親フォルダ '{pdf_target_parent_dir}' 作成失敗。", context="FILE_IO_MKDIR_ERROR", exception_info=e)

                if pdf_content and not pdf_error_info:
                    pdf_output_filename = f"{base_name_for_output}.pdf" # 接尾辞なし
                    pdf_output_path = os.path.join(pdf_target_parent_dir, pdf_output_filename)
                    try:
                        with open(pdf_output_path, 'wb') as f: f.write(pdf_content)
                        self.log_manager.info(f"サーチャブルPDF保存成功: '{pdf_output_path}'", context="FILE_IO_SAVE")
                    except Exception as e:
                        self.log_manager.error(f"サーチャブルPDF保存失敗 ({original_file_basename})", context="FILE_IO_SAVE_ERROR", exception_info=e, path=pdf_output_path)
                elif pdf_error_info:
                    self.log_manager.error(f"サーチャブルPDF作成失敗 ({original_file_basename})", context="WORKER_PDF_ERROR", error_details=pdf_error_info)
            
            # 元ファイルの移動処理
            current_source_file_to_move = original_file_path
            if os.path.exists(current_source_file_to_move): # ファイルが存在する場合のみ移動試行
                destination_subfolder_for_move = None
                if ocr_succeeded and move_on_success_enabled:
                    destination_subfolder_for_move = success_folder_name
                    log_move_type = "OCR成功"
                elif not ocr_succeeded and move_on_failure_enabled:
                    destination_subfolder_for_move = failure_folder_name
                    log_move_type = "OCR失敗"
                
                if destination_subfolder_for_move and self.is_running:
                    self.log_manager.info(f"{log_move_type}ファイルの移動開始: '{original_file_basename}' -> 親ディレクトリ直下の '{destination_subfolder_for_move}' へ", context="WORKER_FILE_MOVE")
                    moved_path, move_err_msg = self._move_file_with_collision_handling(
                        current_source_file_to_move, 
                        original_file_parent_dir, # 元ファイルの親ディレクトリを渡す
                        destination_subfolder_for_move, 
                        collision_action
                    )
                    if move_err_msg: # エラーメッセージがあればログに出力
                        self.log_manager.error(f"{log_move_type}ファイルの移動で問題発生: {move_err_msg} (ファイル: {original_file_basename})", context="WORKER_FILE_MOVE_RESULT")
                    # moved_path はここでは特に使わない
            else:
                # OCR処理中にファイルが外部から削除/移動された場合など
                self.log_manager.warning(f"移動対象の元ファイルが見つかりません（既に移動済みか削除された可能性）: '{current_source_file_to_move}'", context="WORKER_FILE_MOVE")

            time.sleep(0.01) # UIの応答性をわずかに保つため

        self.all_files_processed.emit() # 全ファイル処理完了をUIへ通知
        if self.is_running: # ユーザーによる中止でなければ
            self.log_manager.info("全てのファイルのOCR処理が完了しました。", context="WORKER_LIFECYCLE")
        # is_running が False の場合は、stop() メソッド内で既にログが出ているはず

    def stop(self):
        if self.is_running: # 重複してログが出ないように
            self.is_running = False
            self.log_manager.info("OCR処理の中止が要求されました。現在のファイル処理後に停止します。", context="WORKER_LIFECYCLE")

# MainWindowクラス (前回提示の変更適用済み状態)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI inside Cube Client Ver.0.0.2")
        self.config = ConfigManager.load()

        self.log_widget = QTextEdit()
        self.log_manager = LogManager(self.log_widget)
        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.ocr_worker = None

        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700})
        state_cfg = self.config.get("window_state", "normal")
        pos_cfg = self.config.get("window_position")
        self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
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
        
        # スプリッターの保存されたサイズを復元
        splitter_sizes = self.config.get("splitter_sizes")
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0 :
            self.splitter.setSizes(splitter_sizes)
        else: # デフォルト比率
            initial_splitter_sizes = [int(self.height() * 0.65), int(self.height() * 0.35)]
            if sum(initial_splitter_sizes) > 0 : self.splitter.setSizes(initial_splitter_sizes)


        self.main_layout.addWidget(self.splitter)
        self.input_folder_path = self.config.get("last_target_dir", "")
        self.setup_toolbar_and_folder_labels()

        self.is_ocr_running = False
        self.current_view = self.config.get("current_view", 0)
        self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True)
        self.log_container.setVisible(log_visible)
        
        self.update_ocr_controls()
        self.check_input_folder_validity()
        self.log_manager.info("アプリケーション起動完了", context="SYSTEM")

    def setup_toolbar_and_folder_labels(self):
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
            self.config = ConfigManager.load()
            self.log_manager.info("オプション設定が保存・再読み込みされました。", context="CONFIG_UPDATE")
            self.api_client = CubeApiClient(self.config, self.log_manager) # API Clientも更新
        else:
            self.log_manager.info("オプション設定はキャンセルされました。", context="UI_ACTION")

    def select_input_folder(self):
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.input_folder_path = folder
            self.input_folder_label.setText(folder)
            self.log_manager.info(f"入力フォルダ選択: {folder}", context="UI_FOLDER_SELECT")
            self.processed_files_info = []
            self.list_view.update_files(self.processed_files_info)
            if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
            self.check_input_folder_validity()
        else:
            self.log_manager.info("入力フォルダ選択がキャンセルされました。", context="UI_FOLDER_SELECT")

    def check_input_folder_validity(self):
        is_valid = bool(self.input_folder_path and os.path.isdir(self.input_folder_path))
        # OCR実行中でなければ、入力フォルダの妥当性に応じて開始ボタンの有効性を設定
        if not self.is_ocr_running:
            self.start_ocr_action.setEnabled(is_valid)
        else: # 実行中なら常に無効
            self.start_ocr_action.setEnabled(False)

        if not is_valid and self.input_folder_path:
            if not hasattr(self, '_last_folder_error') or self._last_folder_error != "input_invalid":
                self.log_manager.warning(f"入力フォルダが無効です: {self.input_folder_path}", context="UI_VALIDATION")
                self._last_folder_error = "input_invalid"
        elif is_valid:
            self._last_folder_error = None # エラーが解消されたら記録をクリア

    def _collect_files_from_input_folder(self):
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            self.log_manager.warning("ファイル収集スキップ: 入力フォルダが未選択または無効です。", context="FILE_SCAN")
            return []

        current_config = ConfigManager.load() # ファイル収集時の最新設定を使用
        file_actions_config = current_config.get("file_actions", {})
        success_folder_name = file_actions_config.get("success_folder_name")
        failure_folder_name = file_actions_config.get("failure_folder_name")
        results_folder_name = file_actions_config.get("results_folder_name")
        excluded_folder_names = [name for name in [success_folder_name, failure_folder_name, results_folder_name] if name and name.strip()]

        api_type_key = current_config.get("api_type", "cube_fullocr")
        options_cfg = current_config.get("options", {}).get(api_type_key, {})
        max_files = options_cfg.get("max_files_to_process", 100)
        recursion_depth_limit = options_cfg.get("recursion_depth", 5)
        
        self.log_manager.info(f"ファイル収集開始: In='{self.input_folder_path}', MaxFiles={max_files}, DepthLimit={recursion_depth_limit}", context="FILE_SCAN")
        if excluded_folder_names:
            self.log_manager.info(f"  除外サブフォルダ名（これらの名前のフォルダはスキップ）: {excluded_folder_names}", context="FILE_SCAN_EXCLUDE")

        collected_files = []
        supported_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

        for root, dirs, files in os.walk(self.input_folder_path, topdown=True, followlinks=False):
            # 現在の深さを計算 (ルートは深さ0)
            # normpathでパスを正規化し、余計な区切り文字を除去
            # input_folder_pathも正規化して比較
            norm_root = os.path.normpath(root)
            norm_input_root = os.path.normpath(self.input_folder_path)
            
            relative_path_from_input = os.path.relpath(norm_root, norm_input_root)
            if relative_path_from_input == ".": current_depth = 0
            else: current_depth = len(relative_path_from_input.split(os.sep))

            if current_depth >= recursion_depth_limit:
                self.log_manager.debug(f"  深さ制限超過 (Depth={current_depth}, Limit={recursion_depth_limit}): スキップ中 '{root}'", context="FILE_SCAN_DEPTH_SKIP")
                dirs[:] = [] # このディレクトリ以下の探索を中止
                continue

            # 除外フォルダ名のチェック (dirsリストを変更して探索をスキップ)
            dirs_to_remove_from_walk = []
            for dir_name_in_walk in dirs:
                if dir_name_in_walk in excluded_folder_names: # 完全一致でチェック
                    self.log_manager.debug(f"  除外フォルダ '{os.path.join(root, dir_name_in_walk)}' をこれ以上探索しません。", context="FILE_SCAN_EXCLUDE_DIR")
                    dirs_to_remove_from_walk.append(dir_name_in_walk)
            for d_to_remove in dirs_to_remove_from_walk:
                if d_to_remove in dirs: dirs.remove(d_to_remove) # os.walkが次に探索するdirsリストから削除

            for filename in sorted(files):
                if len(collected_files) >= max_files:
                    self.log_manager.info(f"  最大ファイル数 {max_files} に到達。収集終了。", context="FILE_SCAN_MAX_REACHED")
                    return sorted(list(set(collected_files)))

                file_path = os.path.join(root, filename)
                if os.path.islink(file_path):
                    self.log_manager.info(f"  シンボリックリンクスキップ: {file_path}", context="FILE_SCAN_SKIP_LINK")
                    continue
                
                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in supported_extensions:
                    collected_files.append(file_path)
        
        unique_sorted_files = sorted(list(set(collected_files)))
        self.log_manager.info(f"ファイル収集完了: {len(unique_sorted_files)} 件発見。", context="FILE_SCAN_COMPLETE", found_count=len(unique_sorted_files))
        if len(unique_sorted_files) > max_files: # このチェックは通常不要(ループ内で制限しているため)だが念のため
            self.log_manager.info(f"最大ファイル数 {max_files} に切り詰めます。", context="FILE_SCAN_TRUNCATE")
            return unique_sorted_files[:max_files]
        return unique_sorted_files

    def _create_confirmation_summary(self, files_to_process_count, create_searchable_pdf_flag):
        current_config = ConfigManager.load()
        file_actions_cfg = current_config.get("file_actions", {})
        api_type_key = current_config.get("api_type", "cube_fullocr")
        ocr_opts = current_config.get("options", {}).get(api_type_key, {})

        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]
        summary_lines.append("<strong>【基本設定】</strong>")
        summary_lines.append(f"入力フォルダ: {self.input_folder_path or '未選択'}")
        summary_lines.append("<br>")

        summary_lines.append("<strong>【ファイル処理後のサブフォルダ設定】</strong>")
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
        # (他のOCRオプションも同様に表示) ...
        summary_lines.append(f"OCRモデル: {ocr_opts.get('ocr_model', 'katsuji')}")
        summary_lines.append(f"サーチャブルPDF作成: {'する' if create_searchable_pdf_flag else 'しない'}")
        summary_lines.append("<br>上記内容で処理を開始します。")
        
        # HTMLエスケープとインデントのための微調整
        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])


    def confirm_start_ocr(self):
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            QMessageBox.warning(self, "開始不可", "入力フォルダを選択し、有効なパスを指定してください。")
            self.log_manager.warning("OCR開始不可: 入力フォルダ未選択または無効。", context="OCR_FLOW_VALIDATION")
            return
        if self.is_ocr_running:
            QMessageBox.information(self, "処理中", "現在OCR処理を実行中です。")
            self.log_manager.info("OCR開始試行: 既に処理実行中。", context="OCR_FLOW_VALIDATION")
            return

        files_to_process = self._collect_files_from_input_folder()
        if not files_to_process:
            current_config_for_msg = ConfigManager.load()
            api_type_key = current_config_for_msg.get("api_type", "cube_fullocr")
            options_cfg_msg = current_config_for_msg.get("options", {}).get(api_type_key, {})
            max_f_msg = options_cfg_msg.get('max_files_to_process', 100)
            depth_msg = options_cfg_msg.get('recursion_depth', 5)
            file_actions_cfg_msg = current_config_for_msg.get("file_actions", {})
            excluded_names_msg_list = [
                file_actions_cfg_msg.get("results_folder_name"),
                file_actions_cfg_msg.get("success_folder_name"),
                file_actions_cfg_msg.get("failure_folder_name")
            ]
            excluded_names_str_msg = ", ".join(filter(None, excluded_names_msg_list))
            msg_detail_for_user = f"設定 (最大ファイル数={max_f_msg}, 検索深さ={depth_msg}"
            if excluded_names_str_msg: msg_detail_for_user += f", 除外指定のサブフォルダ名: {excluded_names_str_msg})"
            else: msg_detail_for_user += ")"

            QMessageBox.information(self, "対象ファイルなし", f"入力フォルダに処理対象ファイルが見つかりませんでした。\n{msg_detail_for_user}\n設定を確認してください。")
            self.log_manager.info(f"対象ファイルなし。詳細: {msg_detail_for_user}", context="OCR_FLOW_VALIDATION")
            return

        reply_searchable = QMessageBox.question(self, "サーチャブルPDF作成確認", 
                                            "OCR結果（JSON）と合わせてサーチャブルPDFも作成しますか？", 
                                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                            QMessageBox.StandardButton.No)
        create_searchable_pdf = (reply_searchable == QMessageBox.StandardButton.Yes)
        self.log_manager.info(f"サーチャブルPDF作成選択: {'はい' if create_searchable_pdf else 'いいえ'}", context="OCR_CONFIG_USER_CHOICE")

        confirmation_summary = self._create_confirmation_summary(len(files_to_process), create_searchable_pdf)
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, self)
        if not confirm_dialog.exec():
            self.log_manager.info("OCR処理キャンセル（確認ダイアログ）。", context="OCR_FLOW_USER_CHOICE")
            return

        self.log_manager.info("ユーザー確認OK。OCR処理を開始します。", context="OCR_FLOW_START")
        current_config_for_run = ConfigManager.load() # 実行直前の最新設定をWorkerに渡す
        # ログにも設定スナップショットを記録 (確認ダイアログと重複する部分もあるが、より詳細に)
        # (confirm_start_ocr内のログ記録部分は前回提示のままとし、ここではWorkerへの引数のみ変更)

        self.is_ocr_running = True
        self.update_ocr_controls()
        self.processed_files_info = []
        for i, f_path in enumerate(files_to_process):
            try: f_size = os.path.getsize(f_path)
            except OSError: f_size = 0
            self.processed_files_info.append({
                "no": i + 1, "path": f_path, "name": os.path.basename(f_path), 
                "size": f_size, "status": "待機中", "ocr_result_summary": "", 
                "searchable_pdf_status": "作成する" if create_searchable_pdf else "作成しない"
            })
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'): self.summary_view.start_processing(len(files_to_process))

        self.ocr_worker = OcrWorker(
            api_client=self.api_client, 
            files_to_process=files_to_process,
            create_searchable_pdf=create_searchable_pdf,
            input_root_folder=self.input_folder_path,
            log_manager=self.log_manager,
            config=current_config_for_run # ConfigManagerから読み込んだ設定を渡す
        )
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()

    def confirm_stop_ocr(self):
        # (前回提示から変更なし)
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(self, "OCR中止確認", 
                                        "OCR処理を中止しますか？（現在のファイル処理が完了次第、または次のファイル処理開始前に停止します）", 
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.ocr_worker.stop()
                self.log_manager.info("OCR処理の中止をユーザーが指示しました。Workerに停止を要求。", context="OCR_FLOW_CONTROL")
        else:
            self.is_ocr_running = False
            self.update_ocr_controls()
            self.log_manager.info("中止試行: OCR処理は実行されていません。", context="OCR_FLOW_CONTROL")

    def update_ocr_controls(self):
        # (前回提示から変更なし)
        running = self.is_ocr_running
        can_start = bool(self.input_folder_path and os.path.isdir(self.input_folder_path)) and not running
        self.start_ocr_action.setEnabled(can_start)
        self.stop_ocr_action.setEnabled(running)
        can_reset = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        self.reset_action.setEnabled(can_reset)
        self.input_folder_action.setEnabled(not running)
        self.option_action.setEnabled(not running)
        self.toggle_view_action.setEnabled(not running)


    def on_file_ocr_processed(self, file_idx, file_path, ocr_result_json, error_info):
        # (前回提示から変更なし)
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.warning(f"処理済みファイル情報なし(OCR): {file_path}", context="UI_UPDATE_WARN")
            return
        if error_info:
            target_file_info["status"] = "OCR失敗"
            target_file_info["ocr_result_summary"] = error_info.get('message', '不明なエラー')
            if hasattr(self.summary_view, 'increment_error_count'): self.summary_view.increment_error_count()
        elif ocr_result_json:
            target_file_info["status"] = "OCR成功"
            try:
                if isinstance(ocr_result_json, list) and len(ocr_result_json) > 0:
                    first_page_result = ocr_result_json[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "")
                    if not fulltext and "aGroupingFulltext" in first_page_result:
                        fulltext = first_page_result.get("aGroupingFulltext", "")
                    summary_text = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                    target_file_info["ocr_result_summary"] = summary_text
                elif isinstance(ocr_result_json, dict) and "result" in ocr_result_json:
                    fulltext = ocr_result_json.get("result", {}).get("fulltext", "")
                    summary_text = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                    target_file_info["ocr_result_summary"] = summary_text
                else: 
                    target_file_info["ocr_result_summary"] = "結果形式不明"
            except Exception as e:
                target_file_info["ocr_result_summary"] = "結果解析エラー"
                self.log_manager.error(f"結果JSON解析エラー ({target_file_info['name']})", context="UI_UPDATE_ERROR", exception_info=e, path=file_path)
            if hasattr(self.summary_view, 'increment_completed_count'): self.summary_view.increment_completed_count()
        else:
            target_file_info["status"] = "OCR状態不明"
            target_file_info["ocr_result_summary"] = "APIレスポンスなし"
            if hasattr(self.summary_view, 'increment_error_count'): self.summary_view.increment_error_count()
        
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'increment_processed_count'): self.summary_view.increment_processed_count()

    def on_file_searchable_pdf_processed(self, file_idx, file_path, pdf_content, pdf_error_info):
        # (前回提示から変更なし)
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.warning(f"処理済みファイル情報なし(PDF): {file_path}", context="UI_UPDATE_WARN")
            return
        if pdf_error_info: target_file_info["searchable_pdf_status"] = "PDF作成失敗"
        elif pdf_content: target_file_info["searchable_pdf_status"] = "PDF作成成功"
        else: target_file_info["searchable_pdf_status"] = "PDF状態不明"
        self.list_view.update_files(self.processed_files_info)

    def on_all_files_processed(self):
        # (前回提示から変更なし)
        self.is_ocr_running = False
        self.update_ocr_controls()
        final_message = "全てのファイルのOCR処理が完了しました。"
        if self.ocr_worker and not self.ocr_worker.is_running:
            final_message = "OCR処理が中止されました。"
        QMessageBox.information(self, "処理終了", final_message)
        self.log_manager.info(final_message, context="OCR_FLOW_END")
        self.ocr_worker = None

    def confirm_reset_ui(self):
        # (前回提示から変更なし)
        if self.is_ocr_running:
            QMessageBox.warning(self, "リセット不可", "OCR処理の実行中はリセットできません。")
            return
        if not self.processed_files_info and not self.input_folder_path:
            QMessageBox.information(self, "リセット", "クリアするデータがありません。")
            return
        reply = QMessageBox.question(self, "リセット確認", 
                                    "表示されている処理結果リストをクリアしますか？\n（入力フォルダが設定されていれば、ファイルリストを再スキャンします）", 
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                    QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: self.perform_reset()

    def perform_reset(self):
        # (前回提示から変更なし)
        self.log_manager.info("リセット処理開始。", context="RESET_FLOW")
        self.processed_files_info = []
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            collected_files = self._collect_files_from_input_folder()
            if collected_files:
                for i, f_path in enumerate(collected_files):
                    try: f_size = os.path.getsize(f_path)
                    except OSError: f_size = 0
                    self.processed_files_info.append({
                        "no": i + 1, "path": f_path, "name": os.path.basename(f_path), 
                        "size": f_size, "status": "待機中(再読込)", 
                        "ocr_result_summary": "", "searchable_pdf_status": "-"
                    })
                self.list_view.update_files(self.processed_files_info)
                if hasattr(self.summary_view, 'start_processing'):
                    self.summary_view.reset_summary()
                    self.summary_view.total_files = len(collected_files)
                    self.summary_view.update_display()
        self.is_ocr_running = False
        self.update_ocr_controls()
        self.check_input_folder_validity()

    def closeEvent(self, event):
        # (前回提示から変更なし、ただし不要なキーの保存は削除済み)
        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            else:
                if self.ocr_worker and self.ocr_worker.isRunning(): self.ocr_worker.stop()
        
        current_config_to_save = self.config.copy() # 保存用にコピー
        normal_geom = self.normalGeometry()
        current_config_to_save["window_state"] = "maximized" if self.isMaximized() else "normal"
        current_config_to_save["window_size"] = {"width": normal_geom.width(), "height": normal_geom.height()}
        if not self.isMaximized():
            current_config_to_save["window_position"] = {"x": normal_geom.x(), "y": normal_geom.y()}
        elif "window_position" in current_config_to_save: # 最大化時は位置情報を削除
            del current_config_to_save["window_position"]

        current_config_to_save["last_target_dir"] = self.input_folder_path
        current_config_to_save["current_view"] = self.current_view
        current_config_to_save["log_visible"] = self.log_container.isVisible()
        if hasattr(self.splitter, 'sizes'):
            current_config_to_save["splitter_sizes"] = self.splitter.sizes()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'):
            current_config_to_save["column_widths"] = self.list_view.get_column_widths()
            current_config_to_save["sort_order"] = self.list_view.get_sort_order()
        
        ConfigManager.save(current_config_to_save)
        self.log_manager.info("設定を保存し、アプリケーションを終了します。", context="SYSTEM_LIFECYCLE")
        super().closeEvent(event)

    def clear_log_display(self):
        # (前回提示から変更なし)
        self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました。", context="UI_ACTION")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())