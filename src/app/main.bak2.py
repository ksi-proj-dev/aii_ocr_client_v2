import sys
import os
import json # OcrWorker 内でのJSONダンプ、MainWindowでのエンドポイント表示に使用
import datetime # LogManager と SummaryView で使用
import time     # OcrWorker 内でのスリープに使用
import glob     # ファイル検索用
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal # QThreadとpyqtSignalを追加

from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager
from api_client import CubeApiClient # 作成したAPIクライアント

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
        self.setWindowTitle("AI inside Cube Client Ver.0.0.1") # アプリケーションタイトル変更
        self.config = ConfigManager.load()

        # ウィンドウ設定
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700}) # 少し高さを増やす
        state_cfg = self.config.get("window_state", "normal")
        pos_cfg = self.config.get("window_position", {"x": 100, "y": 100})

        self.resize(size_cfg["width"], size_cfg["height"])
        # self.center_window() # center_windowメソッドを定義するか、手動で中央配置を検討
        if "window_position" not in self.config:
             # 簡易的な中央配置 (center_windowがない場合)
            try:
                screen_geometry = QApplication.primaryScreen().geometry()
                self.move((screen_geometry.width() - self.width()) // 2,
                          (screen_geometry.height() - self.height()) // 2)
            except Exception: # QApplicationが初期化されていない場合など
                self.move(pos_cfg["x"], pos_cfg["y"])
        else:
            self.move(pos_cfg["x"], pos_cfg["y"])

        if state_cfg == "maximized":
            self.showMaximized()

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.summary_view = SummaryView()
        self.processed_files_info = [] # 処理したファイル情報を保持するリスト
        self.list_view = ListView(self.processed_files_info)


        self.stack.addWidget(self.summary_view)
        self.stack.addWidget(self.list_view)
        self.splitter.addWidget(self.stack)

        self.log_header = QLabel("ログ：")
        self.log_header.setStyleSheet("margin: 5px 0px 0px 6px; padding: 0px; font-weight: bold;")
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet("margin: 0px 10px 10px 10px;")

        self.log_container = QWidget()
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.log_header)
        log_layout.addWidget(self.log_widget)
        self.log_container.setLayout(log_layout)

        self.splitter.addWidget(self.log_container) # log_container を splitter に追加
        self.splitter.setStyleSheet("""
        QSplitter::handle {
            background-color: #CCCCCC;
            height: 2px;
        }
        """)
        self.main_layout.addWidget(self.splitter)


        # --- LogManager と APIClient のインスタンス化 ---
        self.log_manager = LogManager(self.log_widget)
        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.ocr_worker = None # OCRワーカースレッドのプレースホルダ

        self.setup_toolbar()

        # フォルダパスの初期化と表示
        self.input_folder_path = self.config.get("last_target_dir", "")
        self.output_folder_path = self.config.get("last_result_dir", "")

        self.input_folder_label = QLabel(f"入力フォルダ：{self.input_folder_path or '未選択'}")
        self.input_folder_label.setStyleSheet("padding: 0px; font-weight: bold;")
        self.output_folder_label = QLabel(f"出力フォルダ：{self.output_folder_path or '未選択'}")
        self.output_folder_label.setStyleSheet("padding: 0px; font-weight: bold;")

        label_widget = QWidget()
        label_layout = QVBoxLayout()
        label_layout.addWidget(self.input_folder_label)
        label_layout.addWidget(self.output_folder_label)
        label_widget.setLayout(label_layout)
        self.addToolBarBreak() # ツールバーの区切り

        label_toolbar = QToolBar("Folder Labels Toolbar")
        label_toolbar.addWidget(label_widget)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, label_toolbar) # ツールバーエリアを指定


        self.is_ocr_running = False
        self.current_view = self.config.get("current_view", 0)
        self.stack.setCurrentIndex(self.current_view)

        log_visible = self.config.get("log_visible", True) # デフォルトで表示するように変更も検討
        self.log_container.setVisible(log_visible)

        self.update_ocr_controls()
        self.check_both_folders_validity() # 初期状態でボタン有効/無効をチェック

        self.log_manager.log_message("AI inside Cube Client アプリケーション起動")


    def setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar) # ツールバーエリアを指定

        self.input_folder_action = QAction("📂入力", self)
        self.output_folder_action = QAction("📂出力", self)
        self.toggle_view_action = QAction("📑ビュー", self)
        self.option_action = QAction("⚙️設定", self)
        self.start_ocr_action = QAction("▶️開始", self)
        self.stop_ocr_action = QAction("⏹️中止", self)
        self.log_toggle_action = QAction("📄ログ", self)
        self.clear_log_action = QAction("🗑️クリア", self)

        actions = [
            self.input_folder_action, self.output_folder_action,
            self.toggle_view_action, self.option_action,
            self.start_ocr_action, self.stop_ocr_action,
            self.log_toggle_action, self.clear_log_action
        ]
        handlers = [
            self.select_input_folder, self.select_output_folder,
            self.toggle_view, self.show_option_dialog,
            self.confirm_start_ocr, self.confirm_stop_ocr,
            self.toggle_log_display, self.clear_log_display
        ]
        for action, handler in zip(actions, handlers):
            action.triggered.connect(handler)
            toolbar.addAction(action)

    def toggle_view(self):
        self.current_view = 1 - self.current_view
        self.stack.setCurrentIndex(self.current_view)
        self.config["current_view"] = self.current_view
        # ConfigManager.save(self.config) # 保存はcloseEventでまとめて行う

    def toggle_log_display(self):
        visible = self.log_container.isVisible()
        self.log_container.setVisible(not visible)
        self.config["log_visible"] = not visible
        # ConfigManager.save(self.config)

    def show_option_dialog(self):
        # OptionDialog を開く前に現在の config を再ロードする（推奨）
        # self.config = ConfigManager.load()
        dialog = OptionDialog(self) # OptionDialogは自身のコンストラクタでconfigをロードする
        if dialog.exec(): # exec() はダイアログがOKで閉じられた場合にTrue (PyQt6では Accepted)
            self.config = ConfigManager.load() # 設定が変更された可能性があるので再読み込み
            self.log_manager.log_message("オプション設定が更新されました。")
            # APIクライアントが設定変更を即時反映する必要があれば、ここで再初期化など
            self.api_client = CubeApiClient(self.config, self.log_manager)


    def select_input_folder(self):
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.input_folder_path = folder
            self.input_folder_label.setText(f"入力フォルダ：{folder}")
            self.processed_files_info = []
            self.list_view.update_files(self.processed_files_info)
            if hasattr(self.summary_view, 'reset_summary'): # summary_viewにreset_summaryがあるか確認
                self.summary_view.reset_summary()
            self.check_both_folders_validity()
            self.log_manager.log_message(f"入力フォルダ選択: {folder}")

    def select_output_folder(self):
        last_dir = self.output_folder_path or self.config.get("last_result_dir", os.path.expanduser("~"))
        folder = QFileDialog.getExistingDirectory(self, "出力フォルダを選択", last_dir)
        if folder:
            self.output_folder_path = folder
            self.output_folder_label.setText(f"出力フォルダ：{folder}")
            self.check_both_folders_validity()
            self.log_manager.log_message(f"出力フォルダ選択: {folder}")

    def check_both_folders_validity(self):
        input_path = self.input_folder_path
        output_path = self.output_folder_path
        is_valid = True
        error_message = None

        if not input_path or not output_path:
            is_valid = False
        elif input_path == output_path:
            is_valid = False
            error_message = "入力フォルダと出力フォルダは同一にできません。"
        elif os.path.commonpath([input_path, output_path]) == input_path: # 出力が入力のサブフォルダ
            is_valid = False
            error_message = "出力フォルダは入力フォルダのサブフォルダに設定できません。"

        self.start_ocr_action.setEnabled(is_valid and not self.is_ocr_running)

        # エラーメッセージの表示 (一度だけ表示する工夫)
        if error_message:
            if not hasattr(self, '_last_folder_error') or self._last_folder_error != error_message:
                QMessageBox.warning(self, "フォルダ選択エラー", error_message)
                self._last_folder_error = error_message
        else:
            self._last_folder_error = None


    def confirm_start_ocr(self):
        if not self.input_folder_path or not self.output_folder_path:
            QMessageBox.warning(self, "開始不可", "入力フォルダと出力フォルダを選択してください。")
            return
        if self.is_ocr_running:
            QMessageBox.information(self, "処理中", "現在OCR処理を実行中です。")
            return

        reply_searchable = QMessageBox.question(
            self, "サーチャブルPDF作成確認",
            "OCR結果（JSON）と合わせて、サーチャブルPDFも作成しますか？\n"
            "（サーチャブルPDFを作成する場合、処理時間が長くなる可能性があります）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        create_searchable_pdf = (reply_searchable == QMessageBox.StandardButton.Yes)

        files_to_process = []
        supported_extensions = ("*.pdf", "*.png", "*.jpg", "*.jpeg", "*.tif", "*.tiff")
        for ext in supported_extensions:
            files_to_process.extend(glob.glob(os.path.join(self.input_folder_path, ext)))
            # 大文字の拡張子も検索 (Windowsでは不要だが、他OS互換性のため)
            if os.name != 'nt': # Windows以外の場合
                 files_to_process.extend(glob.glob(os.path.join(self.input_folder_path, ext.upper())))
        # 重複削除
        files_to_process = sorted(list(set(files_to_process)))


        if not files_to_process:
            QMessageBox.information(self, "対象ファイルなし", "入力フォルダに処理対象のファイルが見つかりませんでした。\n(pdf, png, jpg, jpeg, tif, tiff)")
            return

        reply_start = QMessageBox.question(
            self, "OCR開始確認", f"{len(files_to_process)}件のファイルのOCR処理を開始します。よろしいですか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply_start == QMessageBox.StandardButton.Yes:
            self.is_ocr_running = True
            self.update_ocr_controls()
            self.log_manager.log_message(f"OCR処理開始準備 ({len(files_to_process)}件)")

            self.processed_files_info = [] # 結果リストを初期化
            for i, f_path in enumerate(files_to_process):
                try:
                    file_size = os.path.getsize(f_path)
                except OSError:
                    file_size = 0 # アクセスできない場合など
                file_info = {
                    "no": i + 1,
                    "path": f_path,
                    "name": os.path.basename(f_path),
                    "size": file_size,
                    "status": "待機中",
                    "ocr_result_summary": "",
                    "searchable_pdf_status": "作成する" if create_searchable_pdf else "作成しない"
                }
                self.processed_files_info.append(file_info)
            self.list_view.update_files(self.processed_files_info)
            if hasattr(self.summary_view, 'start_processing'):
                self.summary_view.start_processing(len(files_to_process))

            self.ocr_worker = OcrWorker(self.api_client, files_to_process, self.output_folder_path, create_searchable_pdf)
            self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
            self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
            self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
            self.ocr_worker.progress_log.connect(self.log_manager.log_message)
            self.ocr_worker.start()

    def confirm_stop_ocr(self):
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(
                self, "OCR中止確認", "OCR処理を中止します。よろしいですか？\n（現在処理中のファイルが完了次第、停止します）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.ocr_worker.stop()
                self.log_manager.log_message("OCR処理の中止を要求しました。")
                # is_ocr_running は on_all_files_processed でFalseに設定
        else:
            self.is_ocr_running = False # 念のため
            self.update_ocr_controls()

    def update_ocr_controls(self):
        running = self.is_ocr_running
        # check_both_folders_validity でstart_ocr_actionの有効性は制御されるので、ここでは単純なrunning状態のみ見る
        self.start_ocr_action.setEnabled(not running and self.start_ocr_action.isEnabled()) #元々の有効性を維持
        self.stop_ocr_action.setEnabled(running)
        self.input_folder_action.setEnabled(not running)
        self.output_folder_action.setEnabled(not running)
        self.option_action.setEnabled(not running)

    def on_file_ocr_processed(self, file_idx, file_path, ocr_result_json, error_info):
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.log_message(f"警告: 処理済みファイル情報が見つかりません - {file_path}")
            return

        if error_info:
            target_file_info["status"] = f"OCRエラー" #: {error_info.get('error_code', '')}"
            target_file_info["ocr_result_summary"] = error_info.get('message', '不明なエラー')
            if hasattr(self.summary_view, 'increment_error_count'):
                self.summary_view.increment_error_count()
        elif ocr_result_json:
            target_file_info["status"] = "OCR完了"
            try:
                if isinstance(ocr_result_json, list) and len(ocr_result_json) > 0:
                    first_page_result = ocr_result_json[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else fulltext
                    if not fulltext: target_file_info["ocr_result_summary"] = "(テキスト抽出なし)"
                else:
                    target_file_info["ocr_result_summary"] = "結果形式不正"
            except Exception as e:
                target_file_info["ocr_result_summary"] = f"結果解析エラー: {e}"
                self.log_manager.log_message(f"結果解析エラー ({file_path}): {e}")
            if hasattr(self.summary_view, 'increment_completed_count'):
                self.summary_view.increment_completed_count()
        else:
            target_file_info["status"] = "OCR状態不明"
            target_file_info["ocr_result_summary"] = "OCRレスポンスなし"
            if hasattr(self.summary_view, 'increment_error_count'):
                self.summary_view.increment_error_count()

        # ListViewの更新はリスト全体を渡す方式に変更する方が堅牢
        # self.list_view.update_file_info_by_path(file_path, target_file_info)
        self.list_view.update_files(self.processed_files_info) # 全体更新
        if hasattr(self.summary_view, 'increment_processed_count'):
            self.summary_view.increment_processed_count()


    def on_file_searchable_pdf_processed(self, file_idx, file_path, pdf_content, pdf_error_info):
        target_file_info = next((item for item in self.processed_files_info if item["path"] == file_path), None)
        if not target_file_info:
            self.log_manager.log_message(f"警告: サーチャブルPDF処理済みファイル情報が見つかりません - {file_path}")
            return

        if pdf_error_info:
            target_file_info["searchable_pdf_status"] = f"PDFエラー" #: {pdf_error_info.get('error_code', '')}"
        elif pdf_content:
            target_file_info["searchable_pdf_status"] = "PDF作成完了"
        else:
            target_file_info["searchable_pdf_status"] = "PDF状態不明"

        # self.list_view.update_file_info_by_path(file_path, target_file_info)
        self.list_view.update_files(self.processed_files_info) # 全体更新


    def on_all_files_processed(self):
        self.is_ocr_running = False
        self.update_ocr_controls()
        final_message = "全てのファイルのOCR処理が完了しました。"
        if self.ocr_worker and not self.ocr_worker.is_running: # stop()が呼ばれて中止された場合
            final_message = "OCR処理がユーザーによって中止されました。"

        QMessageBox.information(self, "処理終了", final_message)
        self.log_manager.log_message(final_message)
        self.ocr_worker = None # ワーカーインスタンスを解放

    def closeEvent(self, event):
        if self.is_ocr_running:
            reply = QMessageBox.question(
                self, "処理中の終了確認",
                "OCR処理が実行中です。本当にアプリケーションを終了しますか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            else:
                if self.ocr_worker:
                    self.ocr_worker.stop() # スレッドに停止を指示

        # ウィンドウ状態の保存
        normal_geom = self.normalGeometry() # 最大化されていない状態のジオメトリを取得
        size = normal_geom.size()
        pos = normal_geom.topLeft()
        self.config["window_state"] = "maximized" if self.isMaximized() else "normal"
        self.config["window_size"] = {"width": size.width(), "height": size.height()}
        self.config["window_position"] = {"x": pos.x(), "y": pos.y()}

        # フォルダパスの保存
        self.config["last_target_dir"] = self.input_folder_path
        self.config["last_result_dir"] = self.output_folder_path
        # その他の設定も保存
        self.config["current_view"] = self.current_view
        self.config["log_visible"] = self.log_container.isVisible()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'):
            self.config["column_widths"] = self.list_view.get_column_widths()
            self.config["sort_order"] = self.list_view.get_sort_order()

        ConfigManager.save(self.config)
        self.log_manager.log_message("AI inside Cube Client アプリケーション終了")
        super().closeEvent(event)

    def clear_log_display(self):
        self.log_widget.clear()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())