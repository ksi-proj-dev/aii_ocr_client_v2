# ocr_orchestrator.py

import os
import csv
import threading # ★ threading をインポート
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal
from typing import Optional, Dict, Any, List

from ocr_worker import OcrWorker
from log_manager import LogManager, LogLevel
from api_client import OCRApiClient # ★変更箇所: CubeApiClient から OCRApiClient へ
from ui_dialogs import OcrConfirmationDialog
from config_manager import ConfigManager
from file_model import FileInfo
from csv_exporter import export_atypical_to_csv

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING
)
from file_model import FileInfo

class OcrOrchestrator(QObject):
    ocr_process_started_signal = pyqtSignal(int, list) # int: num_files_to_process, list: updated_file_list (List[FileInfo])
    ocr_process_finished_signal = pyqtSignal(bool, object) # bool: was_interrupted, object: fatal_error_info (Optional[Dict[str, Any]])
    
    original_file_status_update_signal = pyqtSignal(str, str) # str: original_file_path, str: status_message
    file_ocr_processed_signal = pyqtSignal(int, str, object, object, object) # int: original_idx, str: path, object: ocr_result, object: ocr_error, object: json_status
    file_searchable_pdf_processed_signal = pyqtSignal(int, str, object, object) # int: original_idx, str: path, object: pdf_final_path, object: pdf_error_info
    
    request_ui_controls_update_signal = pyqtSignal()
    request_list_view_update_signal = pyqtSignal(list) # list: updated_file_list (List[FileInfo])

    def __init__(self, api_client: OCRApiClient, log_manager: LogManager, config: Dict[str, Any], api_profile: Optional[Dict[str, Any]]):
        super().__init__()
        self.api_client = api_client
        self.log_manager = log_manager
        self.config = config
        self.active_api_profile = api_profile 
        self.thread_pool: List[OcrWorker] = []
        self.is_ocr_running = False
        self.user_stopped = False
        self.fatal_error_occurred_info: Optional[Dict[str, Any]] = None
        self.thread_lock = threading.Lock()
        self.input_root_folder = ""
        self.ocr_worker: Optional[OcrWorker] = None

        if not self.active_api_profile:
            self.log_manager.critical("OcrOrchestrator: APIプロファイルが提供されませんでした。処理は続行できません。", context="OCR_ORCH_INIT_ERROR")

    def _create_confirmation_summary(self, files_to_process_count: int, input_folder_path: str, parent_widget_for_dialog) -> str:
        if not self.active_api_profile:
            return "エラー: APIプロファイルがアクティブではありません。設定を確認してください。"

        active_options_values = ConfigManager.get_active_api_options_values(self.config)
        if active_options_values is None:
            active_options_values = {} 

        file_actions_cfg = self.config.get("file_actions", {})
        
        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]
        summary_lines.append(f"<strong>APIプロファイル: {self.active_api_profile.get('name', 'N/A')}</strong>")
        summary_lines.append("<strong>【基本設定】</strong>")
        summary_lines.append(f"入力フォルダ: {input_folder_path or '未選択'}")
        summary_lines.append("<br>")
        summary_lines.append("<strong>【ファイル処理後の出力と移動】</strong>")
        output_format_value = file_actions_cfg.get("output_format", "both")
        output_format_display_map = {"json_only": "JSONのみ", "pdf_only": "サーチャブルPDFのみ", "both": "JSON と サーチャブルPDF (両方)"}
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

        options_schema = self.active_api_profile.get("options_schema", {})
        
        max_files_val = active_options_values.get("max_files_to_process", options_schema.get("max_files_to_process", {}).get("default", 100))
        recursion_depth_val = active_options_values.get("recursion_depth", options_schema.get("recursion_depth", {}).get("default", 5))
        
        summary_lines.append("<strong>【ファイル検索設定 (現在アクティブなAPIプロファイルより)】</strong>")
        # max_files_to_process と recursion_depth はオプションスキーマに存在しない可能性があるので、
        # active_options_values (ユーザー設定値) を優先し、なければスキーマのデフォルト、それもなければ固定デフォルト
        summary_lines.append(f"最大処理ファイル数: {active_options_values.get('max_files_to_process', options_schema.get('max_files_to_process', {}).get('default', '未設定'))}")
        summary_lines.append(f"再帰検索の深さ (入力フォルダ自身を0): {active_options_values.get('recursion_depth', options_schema.get('recursion_depth', {}).get('default', '未設定'))}")

        if "upload_max_size_mb" in active_options_values:
            summary_lines.append(f"アップロード上限サイズ: {active_options_values.get('upload_max_size_mb')} MB")

        if active_options_values.get('split_large_files_enabled', False):
            summary_lines.append(f"ファイル分割: <strong>有効</strong> (分割サイズ目安: {active_options_values.get('split_chunk_size_mb',10)} MB)")
            if active_options_values.get('merge_split_pdf_parts', True):
                summary_lines.append(f"  <small>分割PDF部品の結合: <strong>有効</strong></small>")
            else:
                summary_lines.append(f"  <small>分割PDF部品の結合: <strong>無効</strong> (部品ごとに出力)</small>")
        else:
            summary_lines.append("ファイル分割: 無効")
        summary_lines.append(f"処理対象ファイル数 (選択結果): {files_to_process_count} 件")
        summary_lines.append("<br>")

        summary_lines.append("<strong>【主要OCRオプション (現在アクティブなAPIプロファイルより)】</strong>")
        has_specific_ocr_options = False
        for key, schema_item in options_schema.items():
            if key in [ "max_files_to_process", "recursion_depth", "upload_max_size_mb", 
                        "split_large_files_enabled", "split_chunk_size_mb", "merge_split_pdf_parts"]:
                continue

            label = schema_item.get("label", key)
            value = active_options_values.get(key, schema_item.get("default"))
            display_value = ""
            if schema_item.get("type") == "bool":
                display_value = "ON" if value == 1 else "OFF"
            elif schema_item.get("type") == "enum":
                if isinstance(value, int) and "values" in schema_item and 0 <= value < len(schema_item["values"]):
                    display_value = schema_item["values"][value]
                elif isinstance(value, str): 
                    display_value = value 
                else:
                    display_value = str(value)
            else:
                display_value = str(value)
            
            summary_lines.append(f"{label}: {display_value}")
            has_specific_ocr_options = True
        
        if not has_specific_ocr_options:
            summary_lines.append(" (このAPIプロファイルに固有の主要OCRオプションはありません)")


        summary_lines.append("<br>上記内容で処理を開始します。")
        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])

    def _prepare_and_start_ocr_worker(self, files_to_send_to_worker_tuples: List[tuple], input_folder_path: str):
        self.log_manager.info(f"OcrOrchestrator: Instantiating OcrWorker for {len(files_to_send_to_worker_tuples)} files.", context="OCR_ORCH_WORKER_INIT")
        self.fatal_error_occurred_info = None
        
        if not self.api_client:
            self.log_manager.error("OcrOrchestrator: ApiClient is not configured. Cannot start OCR worker.", context="OCR_ORCH_ERROR", error_code="NO_API_CLIENT")
            self.is_ocr_running = False
            self.ocr_process_finished_signal.emit(True, {"message": "APIクライアント未設定", "code": "NO_API_CLIENT"})
            self.request_ui_controls_update_signal.emit()
            return

        if not self.active_api_profile: 
            self.log_manager.error("OcrOrchestrator: Active API profile is not set. Cannot start OCR worker.", context="OCR_ORCH_ERROR", error_code="NO_ACTIVE_API_PROFILE")
            self.is_ocr_running = False
            self.ocr_process_finished_signal.emit(True, {"message": "アクティブなAPIプロファイルが未設定です。", "code": "NO_ACTIVE_API_PROFILE"})
            self.request_ui_controls_update_signal.emit()
            return

        self.ocr_worker = OcrWorker(
            api_client=self.api_client,
            files_to_process_tuples=files_to_send_to_worker_tuples,
            input_root_folder=input_folder_path,
            log_manager=self.log_manager,
            config=self.config, 
            api_profile=self.active_api_profile 
        )
        self.ocr_worker.original_file_status_update.connect(self._handle_worker_status_update)
        self.ocr_worker.file_processed.connect(self._handle_worker_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self._handle_worker_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self._handle_worker_all_files_processed)

        try:
            self.ocr_worker.start()
            self.is_ocr_running = True
        except Exception as e_start_worker:
            self.log_manager.error(f"OcrOrchestrator: Failed to start OcrWorker thread: {e_start_worker}", context="OCR_ORCH_WORKER_ERROR", exc_info=True, error_code="WORKER_START_FAIL")
            self.is_ocr_running = False
            self.ocr_worker = None
            self.ocr_process_finished_signal.emit(True, {"message": f"ワーカー起動失敗: {e_start_worker}", "code": "WORKER_START_FAIL"})
            self.request_ui_controls_update_signal.emit()

    def _handle_worker_status_update(self, path: str, status_message: str):
        self.original_file_status_update_signal.emit(path, status_message)

    def _handle_worker_file_ocr_processed(self, original_idx: int, path: str, ocr_result: Any, ocr_error: Any, json_status: Any):
        if ocr_error and isinstance(ocr_error, dict) and \
            ocr_error.get("code") in ["NOT_IMPLEMENTED_API_CALL", "NOT_IMPLEMENTED_LIVE_API"]:
            self.fatal_error_occurred_info = ocr_error
            self.log_manager.error(f"OcrOrchestrator: Fatal OCR error detected: {ocr_error.get('message')}. Worker will stop.", context="OCR_ORCH_FATAL_ERROR", error_code=ocr_error.get("code"))
        
        self.file_ocr_processed_signal.emit(original_idx, path, ocr_result, ocr_error, json_status)
        self.request_ui_controls_update_signal.emit()

    def _handle_worker_searchable_pdf_processed(self, original_idx: int, path: str, pdf_final_path: Any, pdf_error_info: Any):
        if pdf_error_info and isinstance(pdf_error_info, dict) and \
            pdf_error_info.get("code") in ["NOT_IMPLEMENTED_API_CALL_PDF", "NOT_IMPLEMENTED_LIVE_API_PDF"]:
            self.fatal_error_occurred_info = pdf_error_info
            self.log_manager.error(f"OcrOrchestrator: Fatal PDF error detected: {pdf_error_info.get('message')}. Worker will stop.", context="OCR_ORCH_FATAL_ERROR", error_code=pdf_error_info.get("code"))

        self.file_searchable_pdf_processed_signal.emit(original_idx, path, pdf_final_path, pdf_error_info)

    def _handle_worker_all_files_processed(self):
        self.log_manager.info("Orchestrator: 全てのワーカー処理が完了しました。", context="OCR_FLOW_ORCH")
        
        final_fatal_error_info = None
        was_interrupted_by_user = False
        with self.thread_lock:
            self.thread_pool.clear()
            if self.fatal_error_occurred_info:
                final_fatal_error_info = self.fatal_error_occurred_info
            
            was_interrupted_by_user = self.user_stopped
        
        if self.is_ocr_running:
            self.is_ocr_running = False
            # ★★★ ここにあったCSVエクスポートの呼び出しを削除 ★★★
            self.ocr_process_finished_signal.emit(was_interrupted_by_user or bool(final_fatal_error_info), final_fatal_error_info)
        
        self.request_ui_controls_update_signal.emit()

    def confirm_and_start_ocr(self, processed_files_info: List[FileInfo], input_folder_path: str, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming OCR start...", context="OCR_ORCH_FLOW")
        if not self.api_client:
            self.log_manager.error("OcrOrchestrator: ApiClient is not initialized. Cannot start OCR.", context="OCR_ORCH_ERROR", error_code="NO_API_CLIENT")
            QMessageBox.critical(parent_widget_for_dialog, "設定エラー", "APIクライアントが初期化されていません。")
            return
        if not self.active_api_profile: 
            self.log_manager.error("OcrOrchestrator: Active API profile not set. Cannot start OCR.", context="OCR_ORCH_ERROR", error_code="NO_ACTIVE_PROFILE")
            QMessageBox.critical(parent_widget_for_dialog, "設定エラー", "アクティブなAPIプロファイルが設定されていません。")
            return

        # ★変更箇所: アクティブプロファイルのAPIキーをチェックする
        if self.config.get("api_execution_mode") == "live":
            active_api_key = ConfigManager.get_active_api_key(self.config)
            if not active_api_key or not active_api_key.strip():
                active_profile_name = self.active_api_profile.get("name", "不明なプロファイル")
                self.log_manager.warning(f"OcrOrchestrator: API Key for profile '{active_profile_name}' is not set for Live mode. OCR cannot start.", context="OCR_ORCH_CONFIG_ERROR", error_code="API_KEY_MISSING_LIVE")
                QMessageBox.warning(parent_widget_for_dialog, "APIキー未設定 (Liveモード)",
                                    f"LiveモードでOCRを実行するには、プロファイル「{active_profile_name}」のAPIキーを設定してください。")
                return
        # --- ★変更箇所ここまで ---

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

        self.log_manager.info(f"OcrOrchestrator: User confirmed. Starting OCR process for {len(files_eligible_for_ocr_info)} files using API '{self.active_api_profile.get('name')}'...", context="OCR_ORCH_FLOW")
        
        files_to_send_to_worker_tuples = []
        updated_processed_files_info_for_start = [] 
        for original_idx, item_info_orig in enumerate(processed_files_info):
            item_info = item_info_orig 
            if item_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and item_info.is_checked:
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

    def confirm_and_resume_ocr(self, processed_files_info: List[FileInfo], input_folder_path: str, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming OCR resume...", context="OCR_ORCH_FLOW")
        if not self.api_client:
            self.log_manager.error("OcrOrchestrator: ApiClient is not initialized. Cannot resume OCR.", context="OCR_ORCH_ERROR", error_code="NO_API_CLIENT")
            QMessageBox.critical(parent_widget_for_dialog, "設定エラー", "APIクライアントが初期化されていません。")
            return
        if not self.active_api_profile:
            self.log_manager.error("OcrOrchestrator: Active API profile not set. Cannot resume OCR.", context="OCR_ORCH_ERROR", error_code="NO_ACTIVE_PROFILE")
            QMessageBox.critical(parent_widget_for_dialog, "設定エラー", "アクティブなAPIプロファイルが設定されていません。")
            return

        # ★変更箇所: アクティブプロファイルのAPIキーをチェックする (resume時も同様に)
        if self.config.get("api_execution_mode") == "live":
            active_api_key = ConfigManager.get_active_api_key(self.config)
            if not active_api_key or not active_api_key.strip():
                active_profile_name = self.active_api_profile.get("name", "不明なプロファイル")
                self.log_manager.warning(f"OcrOrchestrator: API Key for profile '{active_profile_name}' is not set for Live mode. OCR cannot resume.", context="OCR_ORCH_CONFIG_ERROR", error_code="API_KEY_MISSING_LIVE")
                QMessageBox.warning(parent_widget_for_dialog, "APIキー未設定 (Liveモード)",
                                    f"LiveモードでOCRを再開するには、プロファイル「{active_profile_name}」のAPIキーを設定してください。")
                return
        # --- ★変更箇所ここまで ---

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

        message = f"{len(files_to_resume_tuples)} 件の選択されたファイルに対してOCR処理を再開します。\n" \
                    f"(APIプロファイル: {self.active_api_profile.get('name', 'N/A')})\n\n" \
                    "よろしいですか？"
        reply = QMessageBox.question(parent_widget_for_dialog, "OCR再開の確認", message,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            self.log_manager.info("OcrOrchestrator: OCR resume cancelled by user.", context="OCR_ORCH_FLOW")
            return

        self.log_manager.info(f"OcrOrchestrator: User confirmed. Resuming OCR process for {len(files_to_resume_tuples)} files using API '{self.active_api_profile.get('name')}'...", context="OCR_ORCH_FLOW")
        
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
        worker_to_stop = self.ocr_worker
        if worker_to_stop is not None and hasattr(worker_to_stop, 'isRunning') and worker_to_stop.isRunning():
            reply = QMessageBox.question(parent_widget_for_dialog, "OCR中止確認", "OCR処理を中止しますか？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("OcrOrchestrator: User confirmed OCR stop. Requesting worker to stop.", context="OCR_ORCH_FLOW_STOP")
                if hasattr(worker_to_stop, 'stop'):
                    worker_to_stop.stop() 
                else:
                    self.log_manager.warning(f"OcrOrchestrator: Worker object {id(worker_to_stop)} no longer has stop method (unexpected). Manually setting is_ocr_running to False.", context="OCR_ORCH_FLOW_STOP")
                    self.is_ocr_running = False 
                    self.ocr_process_finished_signal.emit(True, {"message": "ワーカーの停止メソッド呼び出しに失敗（内部エラー）", "code":"WORKER_STOP_METHOD_FAIL"}) 
                    self.request_ui_controls_update_signal.emit()
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

            if self.is_ocr_running:
                self.log_manager.warning(f"OcrOrchestrator: is_ocr_running was True but worker state suggests it's not active. Resetting orchestrator state.", context="OCR_ORCH_STATE_MISMATCH")
                self.is_ocr_running = False
                self.ocr_process_finished_signal.emit(True, self.fatal_error_occurred_info if self.fatal_error_occurred_info else {"message": "処理状態の不整合により停止", "code": "STATE_INCONSISTENCY_STOP"})
            
            self.request_ui_controls_update_signal.emit() 

    def get_is_ocr_running(self) -> bool:
        return self.is_ocr_running

    def set_is_ocr_running(self, is_running: bool): 
        self.is_ocr_running = is_running

    def update_config(self, new_config: dict, new_api_profile_schema: Optional[Dict[str, Any]]): # new_api_profile -> new_api_profile_schema
        self.log_manager.info("OcrOrchestrator: 設定更新中...", context="OCR_ORCH_CONFIG")
        self.config = new_config
        if new_api_profile_schema:
            self.active_api_profile_schema = new_api_profile_schema
            self.log_manager.info(f"OcrOrchestrator: アクティブAPIプロファイルスキーマを '{new_api_profile_schema.get('name')}' に更新しました。", context="OCR_ORCH_CONFIG")
        else: 
            current_profile_id = new_config.get("current_api_profile_id")
            active_profile_schema_from_cfg = ConfigManager.get_api_profile(new_config, current_profile_id) 
            if active_profile_schema_from_cfg:
                self.active_api_profile_schema = active_profile_schema_from_cfg
            elif new_config.get("api_profiles") and len(new_config.get("api_profiles")) > 0: # フォールバック
                self.active_api_profile_schema = new_config["api_profiles"][0]
                self.log_manager.warning(f"OcrOrchestrator: update_config で current_api_profile_id '{current_profile_id}' に対応するプロファイルスキーマが見つからず、最初のプロファイルを使用します。", context="OCR_ORCH_CONFIG")
            else:
                self.log_manager.error("OcrOrchestrator: update_configで有効なAPIプロファイルスキーマが見つかりません。", context="OCR_ORCH_CONFIG")
                self.active_api_profile_schema = {} # 空の辞書にフォールバック

        if self.api_client: 
            self.api_client.update_config(new_config, self.active_api_profile_schema)

    def export_results_to_csv(self, processed_files: List[FileInfo], input_root_folder: str):
        """
        MainWindowから呼び出されるCSVエクスポートのメインメソッド。
        """
        # 現在のプロファイルが dx_atypical_v2 でない場合は何もしない
        if not self.active_api_profile or self.active_api_profile.get("id") != "dx_atypical_v2":
            return

        self.log_manager.info("OCR処理完了。CSVエクスポートの準備をします。", context="CSV_EXPORT")

        # 引数で渡されたリストを使用する
        successful_files = [f for f in processed_files if f.ocr_engine_status == OCR_STATUS_COMPLETED]

        if not successful_files:
            self.log_manager.info("CSVエクスポート対象の成功ファイルがありません。", context="CSV_EXPORT")
            return

        # 引数で渡されたパスを使用する
        if not input_root_folder or not os.path.isdir(input_root_folder):
            self.log_manager.error("CSV出力先となるルート入力フォルダが無効です。", context="CSV_EXPORT_ERROR")
            return
            
        results_folder_name = self.config.get("file_actions", {}).get("results_folder_name", "OCR結果")
        output_dir = os.path.join(input_root_folder, results_folder_name)
        
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            self.log_manager.error(f"CSV出力先フォルダの作成に失敗しました: {output_dir}, エラー: {e}", context="CSV_EXPORT_ERROR")
            return

        csv_filename = f"{os.path.basename(os.path.normpath(input_root_folder))}.csv"
        output_csv_path = os.path.join(output_dir, csv_filename)

        # ★★★ CSV Exporter に渡す引数を修正 ★★★
        # 使用されたモデルIDを取得して渡す
        active_options = ConfigManager.get_active_api_options_values(self.config)
        model_id = active_options.get("model") if active_options else None
        if not model_id:
            self.log_manager.error("CSVエクスポートに必要なモデルIDが取得できませんでした。", context="CSV_EXPORT_ERROR")
            return

        export_atypical_to_csv(successful_files, output_csv_path, self.log_manager, model_id)
