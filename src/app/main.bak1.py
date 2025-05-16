import sys
import os
import json
import glob
import time
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager
from api_client import CubeApiClient

class OcrWorker(QThread):
    # シグナル定義: (file_index, file_path, ocr_result_json, error_info)
    file_processed = pyqtSignal(int, str, object, object)
    # シグナル定義: (file_index, file_path, pdf_content, error_info)
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
    all_files_processed = pyqtSignal()
    progress_log = pyqtSignal(str) # ログメッセージ用シグナル

    def __init__(self, api_client, files_to_process, output_folder, create_searchable_pdf=False):
        super().__init__()
        self.api_client = api_client
        self.files_to_process = files_to_process
        self.output_folder = output_folder
        self.create_searchable_pdf = create_searchable_pdf # サーチャブルPDFを作成するかどうか
        self.is_running = True

    def run(self):
        self.progress_log.emit(f"{len(self.files_to_process)} 件のファイルのOCR処理を開始します。")
        for idx, file_path in enumerate(self.files_to_process):
            if not self.is_running:
                self.progress_log.emit("OCR処理が中止されました。")
                break

            self.progress_log.emit(f"処理中 ({idx + 1}/{len(self.files_to_process)}): {os.path.basename(file_path)}")

            # 1. 全文OCR (JSON結果)
            ocr_result_json, error_info = self.api_client.read_document(file_path)
            self.file_processed.emit(idx, file_path, ocr_result_json, error_info)

            if ocr_result_json and not error_info: # OCR成功時
                # JSON結果をファイルに保存
                try:
                    base, ext = os.path.splitext(os.path.basename(file_path))
                    json_output_path = os.path.join(self.output_folder, f"{base}_ocr_result.json")
                    with open(json_output_path, 'w', encoding='utf-8') as f:
                        json.dump(ocr_result_json, f, ensure_ascii=False, indent=2)
                    self.progress_log.emit(f"結果JSON保存完了: {json_output_path}")
                except Exception as e:
                    self.progress_log.emit(f"結果JSON保存エラー: {file_path} - {e}")
            elif error_info:
                 self.progress_log.emit(f"OCR処理エラー: {file_path} - {error_info.get('message', 'Unknown error')}")


            # 2. サーチャブルPDF作成 (オプションが有効な場合)
            if self.create_searchable_pdf and self.is_running: # OCR成功・失敗に関わらず、元ファイルに対して実行
                self.progress_log.emit(f"サーチャブルPDF作成中: {os.path.basename(file_path)}")
                pdf_content, pdf_error_info = self.api_client.make_searchable_pdf(file_path)
                self.searchable_pdf_processed.emit(idx, file_path, pdf_content, pdf_error_info)

                if pdf_content and not pdf_error_info:
                    try:
                        base, ext = os.path.splitext(os.path.basename(file_path))
                        pdf_output_path = os.path.join(self.output_folder, f"{base}_searchable.pdf")
                        with open(pdf_output_path, 'wb') as f:
                            f.write(pdf_content)
                        self.progress_log.emit(f"サーチャブルPDF保存完了: {pdf_output_path}")
                    except Exception as e:
                        self.progress_log.emit(f"サーチャブルPDF保存エラー: {file_path} - {e}")
                elif pdf_error_info:
                    self.progress_log.emit(f"サーチャブルPDF作成エラー: {file_path} - {pdf_error_info.get('message', 'Unknown error')}")

            time.sleep(0.1) # UIイベント処理のための短い待機

        self.all_files_processed.emit()
        if self.is_running: # 中止されずに完了した場合
             self.progress_log.emit("全てのファイルのOCR処理が完了しました。")

    def stop(self):
        self.is_running = False
        self.progress_log.emit("OCR処理の中止を要求しました。")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Inside Cube FullOCR Client. Ver.0.0.5")
        self.config = ConfigManager.load()
        
        # ウィンドウ設定
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 600})
        state_cfg = self.config.get("window_state", "normal")
        pos_cfg = self.config.get("window_position", {"x": 100, "y": 100})

        self.resize(size_cfg["width"], size_cfg["height"])
        if "window_position" not in self.config:
            self.center_window()
        else:
            self.move(pos_cfg["x"], pos_cfg["y"])

        self.resize(size_cfg["width"], size_cfg["height"])
        self.move(pos_cfg["x"], pos_cfg["y"])

        if state_cfg == "maximized":
            self.showMaximized()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.summary_view = SummaryView()
        self.list_view = ListView([])

        self.stack.addWidget(self.summary_view)
        self.stack.addWidget(self.list_view)
        self.splitter.addWidget(self.stack)

        self.log_header = QLabel("ログ：")
        self.log_header.setStyleSheet("margin: 5px 0px 0px 6px; padding: 0px; font-weight: bold;")
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)

        self.log_widget.setStyleSheet("margin: 0px 10px 10px 10px;")
        self.log_manager = LogManager(self.log_widget)
        self.splitter.addWidget(self.log_widget)
        self.splitter.setStyleSheet("""
        QSplitter::handle {
            background-color: #CCCCCC;  /* ライン色 */
            height: 2px;  /* 横方向なら高さ、縦方向なら幅 */
        }
        """)

        self.log_container = QWidget()
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.log_header)
        log_layout.addWidget(self.log_widget)
        self.log_container.setLayout(log_layout)

        self.splitter.addWidget(self.log_container)
        self.main_layout.addWidget(self.splitter)

        # ツールバーとアクションをすべて設定
        self.setup_toolbar()

        self.input_folder_path = ""
        self.output_folder_path = ""
        self.is_ocr_running = False
        self.current_view = self.config.get("current_view", 0)
        self.stack.setCurrentIndex(self.current_view)

        self.input_folder_label = QLabel("入力フォルダ：未選択")
        self.input_folder_label.setStyleSheet("padding: 0px; font-weight: bold;")
        self.output_folder_label = QLabel("出力フォルダ：未選択")
        self.output_folder_label.setStyleSheet("padding: 0px; font-weight: bold;")

        label_widget = QWidget()
        label_layout = QVBoxLayout()
        label_layout.addWidget(self.input_folder_label)
        label_layout.addWidget(self.output_folder_label)
        label_widget.setLayout(label_layout)
        self.addToolBarBreak()

        label_toolbar = QToolBar("Label Toolbar")
        label_toolbar.addWidget(label_widget)
        self.addToolBar(label_toolbar)
        self.addToolBarBreak()


        log_visible = self.config.get("log_visible", False)
        self.log_container.setVisible(log_visible)

        # アクションの定義が完了してから呼び出す
        self.update_ocr_controls()

        self.api_client = CubeApiClient(self.config, self.log_manager)

        self.log_manager.log_message("アプリケーション起動")

    def setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        # インスタンス変数でアクションを保持
        self.input_folder_action = QAction("📂入力", self)
        self.output_folder_action = QAction("📂出力", self)
        self.toggle_view_action = QAction("📑ビュー", self)
        self.option_action = QAction("⚙️設定", self)
        self.start_ocr_action = QAction("▶️開始", self)
        self.stop_ocr_action = QAction("⏹️中止", self)
        self.log_toggle_action = QAction("📄ログ", self)
        self.clear_log_action = QAction("🗑️クリア", self)

        actions = [
            self.input_folder_action,
            self.output_folder_action,
            self.toggle_view_action,
            self.option_action,
            self.start_ocr_action,
            self.stop_ocr_action,
            self.log_toggle_action,
            self.clear_log_action
        ]

        handlers = [
            self.select_input_folder,
            self.select_output_folder,
            self.toggle_view,
            self.show_option_dialog,
            self.confirm_start_ocr,
            self.confirm_stop_ocr,
            self.toggle_log_display,
            self.clear_log_display
        ]

        for action, handler in zip(actions, handlers):
            action.triggered.connect(handler)
            toolbar.addAction(action)

    def toggle_view(self):
        self.current_view = 1 - self.current_view
        self.stack.setCurrentIndex(self.current_view)
        self.config["current_view"] = self.current_view
        ConfigManager.save(self.config)

    def toggle_log_display(self):
        visible = self.log_container.isVisible()
        self.log_container.setVisible(not visible)
        self.config["log_visible"] = not visible
        ConfigManager.save(self.config)

    def show_option_dialog(self):
        dialog = OptionDialog(self)
        dialog.exec()

    def select_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択")
        if folder:
            self.input_folder_path = folder
            self.input_folder_label.setText(f"入力フォルダ：{folder}")
            self.check_both_folders_validity()
            self.log_manager.log_message(f"入力フォルダ選択: {folder}")

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "出力フォルダを選択")
        if folder:
            self.output_folder_path = folder
            self.output_folder_label.setText(f"出力フォルダ：{folder}")
            self.check_both_folders_validity()
            self.log_manager.log_message(f"出力フォルダ選択: {folder}")

    def check_both_folders_validity(self):
        input_path = self.input_folder_path
        output_path = self.output_folder_path

        # フォルダ未選択時
        if not input_path or not output_path:
            self.start_ocr_action.setEnabled(False)
            return

        # 入力と出力が同一の場合
        if input_path == output_path:
            QMessageBox.warning(self, "フォルダ選択エラー", "入力フォルダと出力フォルダは同一にできません。")
            return

        # 出力フォルダが入力フォルダの中にある場合
        if os.path.commonpath([input_path]) == os.path.commonpath([input_path, output_path]):
            QMessageBox.warning(self, "フォルダ選択エラー", "出力フォルダは入力フォルダのサブフォルダに設定できません。")
            return

        # 条件を満たす場合のみ開始アイコンを有効化
        self.start_ocr_action.setEnabled(True)

    def show_option_dialog(self):
        dialog = OptionDialog(self)
        dialog.exec()

    def confirm_start_ocr(self):
        reply = QMessageBox.question(
            self, "OCR開始確認", "OCRを開始します。よろしいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.is_ocr_running = True
            self.log_manager.log_message("OCR開始")
            self.update_ocr_controls()
            # OCR処理の実装はここに追加

    def confirm_stop_ocr(self):
        reply = QMessageBox.question(
            self, "OCR中止確認", "OCRを中止します。よろしいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.is_ocr_running = False
            self.log_manager.log_message("OCR終了")
            self.update_ocr_controls()
            # OCR停止処理の実装はここに追加

    def update_ocr_controls(self):
        running = self.is_ocr_running
        valid_folders = bool(self.input_folder_path) and bool(self.output_folder_path)
        self.start_ocr_action.setEnabled(not running and valid_folders)
        self.stop_ocr_action.setEnabled(running)
        self.input_folder_action.setEnabled(not running)
        self.output_folder_action.setEnabled(not running)
        self.option_action.setEnabled(not running)

    def closeEvent(self, event):
        normal_geom = self.normalGeometry()
        size = normal_geom.size()
        pos = normal_geom.topLeft()
        self.config["window_state"] = "maximized" if self.isMaximized() else "normal"
        self.config["window_size"] = {"width": size.width(), "height": size.height()}
        self.config["window_position"] = {"x": pos.x(), "y": pos.y()}
        ConfigManager.save(self.config)
        super().closeEvent(event)
        self.log_manager.log_message("アプリケーション終了")

    def clear_log_display(self):
        self.log_widget.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
