# ocr_orchestrator.py

import os
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal

from ocr_worker import OcrWorker
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient
from ui_dialogs import OcrConfirmationDialog

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING
)
from file_model import FileInfo

class OcrOrchestrator(QObject):
    ocr_process_started_signal = pyqtSignal(int, list)
    ocr_process_finished_signal = pyqtSignal(bool)
    
    original_file_status_update_signal = pyqtSignal(str, str)
    file_ocr_processed_signal = pyqtSignal(int, str, object, object, object)
    file_searchable_pdf_processed_signal = pyqtSignal(int, str, object, object)
    
    request_ui_controls_update_signal = pyqtSignal()
    request_list_view_update_signal = pyqtSignal(list)

    def __init__(self, api_client: CubeApiClient, log_manager: LogManager, config: dict):
        super().__init__()
        self.api_client = api_client
        self.log_manager = log_manager
        self.config = config
        self.ocr_worker = None
        self.is_ocr_running = False

    def _create_confirmation_summary(self, files_to_process_count, input_folder_path, parent_widget_for_dialog):
        file_actions_cfg = self.config.get("file_actions", {})
        api_type_key = self.config.get("api_type", "cube_fullocr")
        ocr_opts = self.config.get("options", {}).get(api_type_key, {})

        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]
        summary_lines.append("<strong>【基本設定】</strong>")
        summary_lines.append(f"入力フォルダ: {input_folder_path or '未選択'}")
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
        ocr_model_display = ocr_opts.get('ocr_model', 'katsuji')
        summary_lines.append(f"OCRモデル: {ocr_model_display}")
        summary_lines.append("<br>上記内容で処理を開始します。")

        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])

    def _prepare_and_start_ocr_worker(self, files_to_send_to_worker_tuples, input_folder_path):
        self.log_manager.info(f"OcrOrchestrator: Instantiating OcrWorker for {len(files_to_send_to_worker_tuples)} files.", context="OCR_ORCH_WORKER_INIT")
        if not self.api_client:
            self.log_manager.critical("OcrOrchestrator: ApiClient is not configured. Cannot start OCR worker.", context="OCR_ORCH_ERROR")
            self.is_ocr_running = False
            self.ocr_process_finished_signal.emit(True)
            self.request_ui_controls_update_signal.emit()
            # Consider showing message box via a signal to MainWindow if parent_widget is available
            # QMessageBox.critical(None, "APIクライアントエラー", "APIクライアントが設定されていません。") # parent=None is not ideal
            return

        self.ocr_worker = OcrWorker(
            api_client=self.api_client,
            files_to_process_tuples=files_to_send_to_worker_tuples,
            input_root_folder=input_folder_path,
            log_manager=self.log_manager,
            config=self.config
        )
        self.ocr_worker.original_file_status_update.connect(self._handle_worker_status_update)
        self.ocr_worker.file_processed.connect(self._handle_worker_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self._handle_worker_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self._handle_worker_all_files_processed)

        try:
            self.ocr_worker.start()
            self.is_ocr_running = True
        except Exception as e_start_worker:
            self.log_manager.error(f"OcrOrchestrator: Failed to start OcrWorker thread: {e_start_worker}", context="OCR_ORCH_WORKER_ERROR", exc_info=True)
            self.is_ocr_running = False
            self.ocr_worker = None
            self.ocr_process_finished_signal.emit(True)
            self.request_ui_controls_update_signal.emit()
            # Consider showing message box via a signal to MainWindow
            # QMessageBox.critical(None, "ワーカー起動エラー", f"OCR処理スレッドの開始に失敗しました。\nエラー: {e_start_worker}")

    def _handle_worker_status_update(self, path, status_message):
        self.original_file_status_update_signal.emit(path, status_message)

    def _handle_worker_file_ocr_processed(self, original_idx, path, ocr_result, ocr_error, json_status):
        self.file_ocr_processed_signal.emit(original_idx, path, ocr_result, ocr_error, json_status)
        self.request_ui_controls_update_signal.emit()

    def _handle_worker_searchable_pdf_processed(self, original_idx, path, pdf_final_path, pdf_error_info):
        self.file_searchable_pdf_processed_signal.emit(original_idx, path, pdf_final_path, pdf_error_info)

    def _handle_worker_all_files_processed(self):
        was_interrupted = False
        if self.ocr_worker: # ワーカーインスタンスが存在する場合のみチェック
            was_interrupted = self.ocr_worker.user_stopped
            # ★★★ 修正点: 安全なシグナル切断 ★★★
            try:
                # シグナルが実際に接続されているかを確認する方法はないため、
                # 単にdisconnectを試み、TypeError (接続されていない場合) や
                # RuntimeError (オブジェクトが既に削除されている場合) をキャッチする。
                self.ocr_worker.original_file_status_update.disconnect(self._handle_worker_status_update)
            except (TypeError, RuntimeError) as e:
                self.log_manager.debug(f"OcrOrchestrator: Error disconnecting original_file_status_update: {e}", context="OCR_ORCH_CLEANUP")
            try:
                self.ocr_worker.file_processed.disconnect(self._handle_worker_file_ocr_processed)
            except (TypeError, RuntimeError) as e:
                self.log_manager.debug(f"OcrOrchestrator: Error disconnecting file_processed: {e}", context="OCR_ORCH_CLEANUP")
            try:
                self.ocr_worker.searchable_pdf_processed.disconnect(self._handle_worker_searchable_pdf_processed)
            except (TypeError, RuntimeError) as e:
                self.log_manager.debug(f"OcrOrchestrator: Error disconnecting searchable_pdf_processed: {e}", context="OCR_ORCH_CLEANUP")
            try:
                self.ocr_worker.all_files_processed.disconnect(self._handle_worker_all_files_processed)
            except (TypeError, RuntimeError) as e:
                self.log_manager.debug(f"OcrOrchestrator: Error disconnecting all_files_processed: {e}", context="OCR_ORCH_CLEANUP")
            
            self.ocr_worker = None # ワーカーインスタンスをクリア
        
        self.is_ocr_running = False
        self.ocr_process_finished_signal.emit(was_interrupted)
        self.request_ui_controls_update_signal.emit()


    def confirm_and_start_ocr(self, processed_files_info: list[FileInfo], input_folder_path: str, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming OCR start...", context="OCR_ORCH_FLOW")
        if not self.api_client:
            self.log_manager.error("OcrOrchestrator: ApiClient is not initialized. Cannot start OCR.", context="OCR_ORCH_ERROR")
            QMessageBox.critical(parent_widget_for_dialog, "設定エラー", "APIクライアントが初期化されていません。")
            return
        if not self.config.get("api_key"):
            self.log_manager.warning("OcrOrchestrator: API Key is not set. OCR cannot start.", context="OCR_ORCH_CONFIG_ERROR")
            QMessageBox.warning(parent_widget_for_dialog, "APIキー未設定", "APIキーが設定されていません。オプション画面で設定してください。")
            return

        if not input_folder_path or not os.path.isdir(input_folder_path):
            self.log_manager.warning("OcrOrchestrator: OCR start aborted: Input folder invalid.", context="OCR_ORCH_FLOW")
            QMessageBox.warning(parent_widget_for_dialog, "入力フォルダエラー", "入力フォルダが選択されていないか、無効なパスです。")
            return
        if self.is_ocr_running:
            self.log_manager.info("OcrOrchestrator: OCR start aborted: Already running.", context="OCR_ORCH_FLOW")
            return

        files_eligible_for_ocr_info = [
            item for item in processed_files_info
            if item.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and \
               item.is_checked
        ]

        if not files_eligible_for_ocr_info:
            self.log_manager.info("OcrOrchestrator: OCR start aborted: No eligible and checked files to process.", context="OCR_ORCH_FLOW")
            QMessageBox.information(parent_widget_for_dialog, "対象ファイルなし", "処理対象として選択（チェック）されているファイル（サイズ上限内）が見つかりませんでした。")
            self.request_ui_controls_update_signal.emit()
            return

        ocr_already_attempted_in_eligible_list = any(
            item.ocr_engine_status not in [OCR_STATUS_NOT_PROCESSED, None]
            for item in files_eligible_for_ocr_info
        )

        if ocr_already_attempted_in_eligible_list:
            message = "選択されたファイルの中に、既に処理が試みられた（未処理ではない）ファイルが含まれています。\n" \
                        "これらのファイルのOCR処理状態がリセットされ、最初から処理されます。\n\n" \
                        "よろしいですか？"
            reply = QMessageBox.question(parent_widget_for_dialog, "OCR再実行の確認", message,
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                self.log_manager.info("OcrOrchestrator: OCR re-execution cancelled by user.", context="OCR_ORCH_FLOW")
                return

        confirmation_summary = self._create_confirmation_summary(len(files_eligible_for_ocr_info), input_folder_path, parent_widget_for_dialog)
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, parent_widget_for_dialog)
        if not confirm_dialog.exec():
            self.log_manager.info("OcrOrchestrator: OCR start cancelled by user (final confirmation dialog).", context="OCR_ORCH_FLOW")
            return

        self.log_manager.info(f"OcrOrchestrator: User confirmed. Starting OCR process for {len(files_eligible_for_ocr_info)} files...", context="OCR_ORCH_FLOW")
        
        files_to_send_to_worker_tuples = []
        updated_processed_files_info_for_start = [] 
        for original_idx, item_info_orig in enumerate(processed_files_info):
            item_info = item_info_orig 
            if item_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and \
               item_info.is_checked:
                item_info.status = OCR_STATUS_PROCESSING
                item_info.ocr_engine_status = OCR_STATUS_PROCESSING
                item_info.ocr_result_summary = ""
                output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both")
                item_info.json_status = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
                item_info.searchable_pdf_status = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
                files_to_send_to_worker_tuples.append((item_info.path, original_idx))
            updated_processed_files_info_for_start.append(item_info)
        
        self.ocr_process_started_signal.emit(len(files_to_send_to_worker_tuples), updated_processed_files_info_for_start)
        
        self._prepare_and_start_ocr_worker(files_to_send_to_worker_tuples, input_folder_path)
        self.request_ui_controls_update_signal.emit()

    def confirm_and_resume_ocr(self, processed_files_info: list[FileInfo], input_folder_path: str, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming OCR resume...", context="OCR_ORCH_FLOW")
        if not self.api_client:
            self.log_manager.error("OcrOrchestrator: ApiClient is not initialized. Cannot resume OCR.", context="OCR_ORCH_ERROR")
            QMessageBox.critical(parent_widget_for_dialog, "設定エラー", "APIクライアントが初期化されていません。")
            return
        if not self.config.get("api_key"):
            self.log_manager.warning("OcrOrchestrator: API Key is not set. OCR cannot resume.", context="OCR_ORCH_CONFIG_ERROR")
            QMessageBox.warning(parent_widget_for_dialog, "APIキー未設定", "APIキーが設定されていません。オプション画面で設定してください。")
            return

        if self.is_ocr_running:
            self.log_manager.info("OcrOrchestrator: OCR resume aborted: OCR is already running.", context="OCR_ORCH_FLOW")
            return

        files_to_resume_tuples = []
        for original_idx, item_info in enumerate(processed_files_info):
            if item_info.is_checked and \
               item_info.ocr_engine_status in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and \
               item_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                files_to_resume_tuples.append((item_info.path, original_idx))

        if not files_to_resume_tuples:
            self.log_manager.info("OcrOrchestrator: OCR resume: No checked files found with 'Not Processed' or 'Failed' OCR status.", context="OCR_ORCH_FLOW")
            QMessageBox.information(parent_widget_for_dialog, "再開対象なし", "OCR未処理または失敗状態で、かつチェックされているファイル（サイズ上限内）が見つかりませんでした。")
            self.request_ui_controls_update_signal.emit()
            return

        message = f"{len(files_to_resume_tuples)} 件の選択されたファイルに対してOCR処理を再開します。\n\n" \
                    "よろしいですか？"
        reply = QMessageBox.question(parent_widget_for_dialog, "OCR再開の確認", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            self.log_manager.info("OcrOrchestrator: OCR resume cancelled by user.", context="OCR_ORCH_FLOW")
            return

        self.log_manager.info(f"OcrOrchestrator: User confirmed. Resuming OCR process for {len(files_to_resume_tuples)} files.", context="OCR_ORCH_FLOW")
        
        updated_processed_files_info_for_resume = []
        output_format_cfg = self.config.get("file_actions", {}).get("output_format", "both")
        initial_json_status_ui = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
        initial_pdf_status_ui = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"

        for original_idx, item_info_orig in enumerate(processed_files_info):
            item_info = item_info_orig
            is_target_for_resume = any(orig_idx == original_idx for path, orig_idx in files_to_resume_tuples)
            if is_target_for_resume:
                item_info.ocr_engine_status = OCR_STATUS_PROCESSING
                item_info.status = f"{OCR_STATUS_PROCESSING}(再開)"
                item_info.ocr_result_summary = ""
                item_info.json_status = initial_json_status_ui
                item_info.searchable_pdf_status = initial_pdf_status_ui
            updated_processed_files_info_for_resume.append(item_info)

        self.ocr_process_started_signal.emit(len(files_to_resume_tuples), updated_processed_files_info_for_resume)
        
        self._prepare_and_start_ocr_worker(files_to_resume_tuples, input_folder_path)
        self.request_ui_controls_update_signal.emit()


    def confirm_and_stop_ocr(self, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming OCR stop...", context="OCR_ORCH_FLOW_STOP")
        
        worker_to_stop = self.ocr_worker # チェック時のワーカーインスタンスを保持

        if worker_to_stop is not None and hasattr(worker_to_stop, 'isRunning') and worker_to_stop.isRunning():
            self.log_manager.debug(f"OcrOrchestrator: Worker found and is running. Asking user to confirm stop. Worker ID: {id(worker_to_stop)}", context="OCR_ORCH_FLOW_STOP")
            reply = QMessageBox.question(parent_widget_for_dialog, "OCR中止確認", "OCR処理を中止しますか？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("OcrOrchestrator: User confirmed OCR stop. Requesting worker to stop.", context="OCR_ORCH_FLOW_STOP")
                # worker_to_stop は isRunning() であることが確認されている
                if hasattr(worker_to_stop, 'stop'):
                    worker_to_stop.stop()
                else:
                    self.log_manager.warning(f"OcrOrchestrator: Worker object {id(worker_to_stop)} no longer has stop method (unexpected).", context="OCR_ORCH_FLOW_STOP")
            else:
                self.log_manager.info("OcrOrchestrator: User cancelled OCR stop.", context="OCR_ORCH_FLOW_STOP")
        else:
            current_worker_id = id(worker_to_stop) if worker_to_stop is not None else 'N/A'
            is_running_attr = hasattr(worker_to_stop, 'isRunning')
            is_actually_running = worker_to_stop.isRunning() if is_running_attr and worker_to_stop is not None else False
            
            current_worker_state_log = f"Worker instance is {'None' if worker_to_stop is None else 'Exists'}. "
            if worker_to_stop is not None:
                 current_worker_state_log += f"Has isRunning: {is_running_attr}. Is actually running: {is_actually_running}."

            self.log_manager.debug(f"OcrOrchestrator: Stop OCR requested, but OCR worker state is not suitable for stop. Details: {current_worker_state_log} Worker ID: {current_worker_id}", context="OCR_ORCH_FLOW_STOP")

            if self.is_ocr_running: # OrchestratorのフラグがまだTrueなら、実態と合わない
                self.log_manager.warning(f"OcrOrchestrator: is_ocr_running was True but worker state suggests it's not active. Resetting orchestrator state.", context="OCR_ORCH_STATE_MISMATCH")
                self.is_ocr_running = False
                self.ocr_process_finished_signal.emit(True) # 中断扱いで完了を通知
                if parent_widget_for_dialog:
                     QMessageBox.information(parent_widget_for_dialog, "処理状態", "OCR処理は既に終了しているか、中止されています。")
            self.request_ui_controls_update_signal.emit()

    def get_is_ocr_running(self):
        return self.is_ocr_running

    def set_is_ocr_running(self, is_running: bool):
        self.is_ocr_running = is_running

    def update_config(self, new_config: dict):
        self.log_manager.info("OcrOrchestrator: Updating internal config.", context="OCR_ORCH_CONFIG")
        self.config = new_config
        if self.api_client:
            self.api_client.config = new_config
            self.api_client.api_key = new_config.get("api_key")
            self.api_client.base_uri = new_config.get("base_uri", "")
            api_type = new_config.get("api_type", "cube_fullocr")
            self.api_client.endpoints = new_config.get("endpoints", {}).get(api_type, {})