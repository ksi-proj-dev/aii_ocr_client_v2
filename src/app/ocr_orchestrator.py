# ocr_orchestrator.py

import os
import threading
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, QThread, pyqtSignal
from typing import Optional, Dict, Any, List

from sort_worker import SortWorker
from log_manager import LogManager
from ui_dialogs import OcrConfirmationDialog
from config_manager import ConfigManager
from file_model import FileInfo
from csv_exporter import export_atypical_to_csv

from app_constants import (
    OCR_STATUS_NOT_PROCESSED, OCR_STATUS_PROCESSING, OCR_STATUS_COMPLETED,
    OCR_STATUS_FAILED, OCR_STATUS_SKIPPED_SIZE_LIMIT, OCR_STATUS_SPLITTING,
    OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING
)

class OcrOrchestrator(QObject):
    # OCR用シグナル
    ocr_process_started_signal = pyqtSignal(int, list)
    ocr_process_finished_signal = pyqtSignal(bool, object)
    original_file_status_update_signal = pyqtSignal(str, str)
    file_ocr_processed_signal = pyqtSignal(int, str, object, object, object, object)
    file_auto_csv_processed_signal = pyqtSignal(int, str, object)
    file_searchable_pdf_processed_signal = pyqtSignal(int, str, object, object)
    
    # 仕分け用シグナル
    sort_process_started_signal = pyqtSignal(str)
    sort_process_finished_signal = pyqtSignal(bool, object)

    request_ui_controls_update_signal = pyqtSignal()
    request_list_view_update_signal = pyqtSignal(list)

    def __init__(self, log_manager: LogManager, config: Dict[str, Any], api_profile: Optional[Dict[str, Any]]):
        super().__init__()
        self.log_manager = log_manager
        self.config = config
        self.active_api_profile = api_profile
        self.is_ocr_running = False
        self.user_stopped = False
        self.fatal_error_occurred_info: Optional[Dict[str, Any]] = None
        self.thread_lock = threading.Lock()
        self.input_root_folder = ""
        self.ocr_worker: Optional[QThread] = None # 型を汎用的に
        self.sort_worker: Optional[SortWorker] = None

        self.api_client_class = None
        self.worker_class = None
        self.api_client = None

        if not self.active_api_profile:
            self.log_manager.critical("OcrOrchestrator: APIプロファイルが提供されませんでした。処理は続行できません。", context="OCR_ORCH_INIT_ERROR")
        else:
            self._set_classes_by_profile()

    def _set_classes_by_profile(self):
        """アクティブなプロファイルに応じて、使用するApiClientとOcrWorkerのクラスを動的に設定する"""
        profile_id = self.active_api_profile.get("id") if self.active_api_profile else None
        self.log_manager.info(f"Orchestrator: プロファイル '{profile_id}' に基づいてコンポーネントを設定します。", context="OCR_ORCH_SETUP")

        if profile_id == 'dx_atypical_v2':
            from api_client_atypical import OCRApiClientAtypical
            from ocr_worker_atypical import OcrWorkerAtypical
            self.api_client_class = OCRApiClientAtypical
            self.worker_class = OcrWorkerAtypical
        elif profile_id == 'dx_fulltext_v2':
            from api_client_fulltext import OCRApiClientFulltext
            from ocr_worker_fulltext import OcrWorkerFulltext
            self.api_client_class = OCRApiClientFulltext
            self.worker_class = OcrWorkerFulltext
        elif profile_id == 'dx_standard_v2':
            from api_client_standard import OCRApiClientStandard
            from ocr_worker_standard import OcrWorkerStandard
            self.api_client_class = OCRApiClientStandard
            self.worker_class = OcrWorkerStandard
        else:
            self.log_manager.critical(f"不明またはサポートされていないAPIプロファイルIDです: {profile_id}", context="OCR_ORCH_SETUP_ERROR")
            self.api_client_class = None
            self.worker_class = None
            return

        if self.api_client_class:
            self.api_client = self.api_client_class(
                config=self.config,
                log_manager=self.log_manager,
                api_profile_schema=self.active_api_profile
            )
        else:
            self.api_client = None

    def _create_confirmation_summary(self, files_to_process_count: int, input_folder_path: str, parent_widget_for_dialog) -> str:
        if not self.active_api_profile:
            return "エラー: APIプロファイルがアクティブではありません。設定を確認してください。"

        active_options_values = ConfigManager.get_active_api_options_values(self.config)
        if active_options_values is None: active_options_values = {} 

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
                if isinstance(value, str): 
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
        return "<br>".join(summary_lines)

    def _prepare_and_start_ocr_worker(self, files_to_send_to_worker_tuples: List[tuple], input_folder_path: str):
        self.log_manager.info(f"OcrOrchestrator: Instantiating OcrWorker for {len(files_to_send_to_worker_tuples)} files.", context="OCR_ORCH_WORKER_INIT")
        self.fatal_error_occurred_info = None
        
        if not self.api_client or not self.active_api_profile or not self.worker_class:
            error_msg = "APIクライアント、プロファイル、またはワーカークラスが未設定です。"
            self.log_manager.error(f"OcrOrchestrator: {error_msg} Cannot start OCR worker.", context="OCR_ORCH_ERROR")
            self.is_ocr_running = False
            self.ocr_process_finished_signal.emit(True, {"message": error_msg, "code": "ORCH_CONFIG_ERROR"})
            self.request_ui_controls_update_signal.emit()
            return

        self.ocr_worker = self.worker_class(
            api_client=self.api_client,
            files_to_process_tuples=files_to_send_to_worker_tuples,
            input_root_folder=input_folder_path,
            log_manager=self.log_manager,
            config=self.config, 
            api_profile=self.active_api_profile 
        )
        self.ocr_worker.original_file_status_update.connect(self.original_file_status_update_signal)
        self.ocr_worker.file_processed.connect(self._handle_worker_file_ocr_processed)
        self.ocr_worker.auto_csv_processed.connect(self.file_auto_csv_processed_signal)
        self.ocr_worker.searchable_pdf_processed.connect(self._handle_worker_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self._handle_worker_all_files_processed)

        try:
            self.ocr_worker.start()
            self.is_ocr_running = True
        except Exception as e_start_worker:
            self.log_manager.error(f"OcrOrchestrator: Failed to start OcrWorker thread: {e_start_worker}", context="OCR_ORCH_WORKER_ERROR", exc_info=True)
            self.is_ocr_running = False
            self.ocr_worker = None
            self.ocr_process_finished_signal.emit(True, {"message": f"ワーカー起動失敗: {e_start_worker}", "code": "WORKER_START_FAIL"})
            self.request_ui_controls_update_signal.emit()

    def _handle_worker_status_update(self, path: str, status_message: str):
        self.original_file_status_update_signal.emit(path, status_message)

    def _handle_worker_auto_csv_processed(self, original_idx: int, path: str, status_info: Any):
        self.file_auto_csv_processed_signal.emit(original_idx, path, status_info)

    def _handle_worker_file_ocr_processed(self, original_idx: int, path: str, ocr_result: Any, ocr_error: Any, json_status: Any, job_id: Any):
        if ocr_error and isinstance(ocr_error, dict) and ocr_error.get("code") in ["NOT_IMPLEMENTED_API_CALL", "NOT_IMPLEMENTED_LIVE_API", "API_KEY_MISSING_LIVE", "DXSUITE_BASE_URI_NOT_CONFIGURED"]:
            self.fatal_error_occurred_info = ocr_error
            self.log_manager.error(f"OcrOrchestrator: Fatal OCR error detected: {ocr_error.get('message')}. Worker will stop.", context="OCR_ORCH_FATAL_ERROR", error_code=ocr_error.get("code"))
        
        self.file_ocr_processed_signal.emit(original_idx, path, ocr_result, ocr_error, json_status, job_id)
        self.request_ui_controls_update_signal.emit()

    def _handle_worker_searchable_pdf_processed(self, original_idx: int, path: str, pdf_final_path: Any, pdf_error_info: Any):
        if pdf_error_info and isinstance(pdf_error_info, dict) and pdf_error_info.get("code") in ["NOT_IMPLEMENTED_API_CALL_PDF", "NOT_IMPLEMENTED_LIVE_API_PDF"]:
            self.fatal_error_occurred_info = pdf_error_info
            self.log_manager.error(f"OcrOrchestrator: Fatal PDF error detected: {pdf_error_info.get('message')}. Worker will stop.", context="OCR_ORCH_FATAL_ERROR", error_code=pdf_error_info.get("code"))
        self.file_searchable_pdf_processed_signal.emit(original_idx, path, pdf_final_path, pdf_error_info)

    def _handle_worker_all_files_processed(self):
        self.log_manager.info("Orchestrator: 全てのOCRワーカー処理が完了しました。", context="OCR_FLOW_ORCH")
        
        final_fatal_error_info = self.fatal_error_occurred_info
        was_interrupted_by_user = self.user_stopped
        
        if self.is_ocr_running:
            self.is_ocr_running = False
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

        if self.config.get("api_execution_mode") == "live":
            active_api_key = ConfigManager.get_active_api_key(self.config)
            if not active_api_key or not active_api_key.strip():
                active_profile_name = self.active_api_profile.get("name", "不明なプロファイル")
                self.log_manager.warning(f"OcrOrchestrator: API Key for profile '{active_profile_name}' is not set for Live mode. OCR cannot start.", context="OCR_ORCH_CONFIG_ERROR", error_code="API_KEY_MISSING_LIVE")
                QMessageBox.warning(parent_widget_for_dialog, "APIキー未設定 (Liveモード)", f"LiveモードでOCRを実行するには、プロファイル「{active_profile_name}」のAPIキーを設定してください。")
                return

        if not input_folder_path or not os.path.isdir(input_folder_path):
            self.log_manager.warning("OcrOrchestrator: OCR start aborted: Input folder invalid.", context="OCR_ORCH_FLOW")
            QMessageBox.warning(parent_widget_for_dialog, "入力フォルダエラー", "入力フォルダが選択されていないか、無効なパスです。")
            return
        if self.is_ocr_running:
            self.log_manager.info("OcrOrchestrator: OCR start aborted: Already running.", context="OCR_ORCH_FLOW")
            return

        files_eligible_for_ocr_info = [ item for item in processed_files_info if item.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and item.is_checked ]
        if self.active_api_profile and self.active_api_profile.get('id') == 'dx_standard_v2':
            file_actions = self.config.get("file_actions", {})
            if not file_actions.get("dx_standard_output_json", True) and not file_actions.get("dx_standard_auto_download_csv", True):
                reply = QMessageBox.warning(parent_widget_for_dialog, "注意：出力設定の確認", "「JSON出力」と「CSV自動ダウンロード」が両方オフです。\nこのまま処理すると、後から結果をダウンロードできません。\nよろしいですか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.No: return
        
        if any(item.ocr_engine_status not in [OCR_STATUS_NOT_PROCESSED, None] for item in files_eligible_for_ocr_info):
            reply = QMessageBox.question(parent_widget_for_dialog, "OCR再実行の確認", "選択されたファイルの中に、既に処理が試みられたファイルが含まれています。\nこれらのファイルのOCR処理状態がリセットされ、最初から処理されます。\nよろしいですか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: return

        confirmation_summary = self._create_confirmation_summary(len(files_eligible_for_ocr_info), input_folder_path, parent_widget_for_dialog)
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, parent_widget_for_dialog)
        if not confirm_dialog.exec(): return

        self.log_manager.info(f"OcrOrchestrator: User confirmed. Starting OCR process for {len(files_eligible_for_ocr_info)} files using API '{self.active_api_profile.get('name')}'...", context="OCR_ORCH_FLOW")
        
        files_to_send_to_worker_tuples = []
        updated_processed_files_info_for_start = [] 
        for original_idx, item_info_orig in enumerate(processed_files_info):
            item_info = item_info_orig 
            if item_info.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT and item_info.is_checked:
                item_info.status = OCR_STATUS_PROCESSING; item_info.ocr_engine_status = OCR_STATUS_PROCESSING; item_info.ocr_result_summary = ""
                file_actions = self.config.get("file_actions", {})
                is_dx_standard = self.active_api_profile and self.active_api_profile.get('id') == 'dx_standard_v2'
                if is_dx_standard:
                    item_info.json_status = "処理待ち" if file_actions.get("dx_standard_output_json", False) else "作成しない(設定)"
                    item_info.auto_csv_status = "処理待ち" if file_actions.get("dx_standard_auto_download_csv", False) else "作成しない(設定)"
                    item_info.searchable_pdf_status = "対象外"
                else:
                    output_format_cfg = file_actions.get("output_format", "both")
                    item_info.json_status = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
                    item_info.searchable_pdf_status = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
                    item_info.auto_csv_status = "対象外"
                files_to_send_to_worker_tuples.append((item_info.path, original_idx))
            updated_processed_files_info_for_start.append(item_info) 
        
        self.ocr_process_started_signal.emit(len(files_to_send_to_worker_tuples), updated_processed_files_info_for_start)
        self._prepare_and_start_ocr_worker(files_to_send_to_worker_tuples, input_folder_path)
        self.request_ui_controls_update_signal.emit()

    def confirm_and_resume_ocr(self, processed_files_info: List[FileInfo], input_folder_path: str, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming OCR resume...", context="OCR_ORCH_FLOW")
        if not self.api_client or not self.active_api_profile: return
        if self.config.get("api_execution_mode") == "live" and not ConfigManager.get_active_api_key(self.config):
            QMessageBox.warning(parent_widget_for_dialog, "APIキー未設定 (Liveモード)", f"LiveモードでOCRを再開するには、プロファイル「{self.active_api_profile.get('name', 'N/A')}」のAPIキーを設定してください。"); return
        if self.is_ocr_running: return

        files_to_resume_tuples = [(item.path, idx) for idx, item in enumerate(processed_files_info) if item.is_checked and item.ocr_engine_status in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and item.ocr_engine_status != OCR_STATUS_SKIPPED_SIZE_LIMIT]
        if not files_to_resume_tuples:
            QMessageBox.information(parent_widget_for_dialog, "再開対象なし", "OCR未処理または失敗状態で、かつチェックされているファイルが見つかりませんでした。"); self.request_ui_controls_update_signal.emit(); return

        reply = QMessageBox.question(parent_widget_for_dialog, "OCR再開の確認", f"{len(files_to_resume_tuples)} 件のファイルに対してOCR処理を再開しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No: return

        self.log_manager.info(f"OcrOrchestrator: Resuming OCR process for {len(files_to_resume_tuples)} files.", context="OCR_ORCH_FLOW")
        
        updated_files_info = []
        for idx, item in enumerate(processed_files_info):
            if any(orig_idx == idx for _, orig_idx in files_to_resume_tuples):
                item.ocr_engine_status = OCR_STATUS_PROCESSING; item.status = f"{OCR_STATUS_PROCESSING}(再開)"; item.ocr_result_summary = ""
                # statusリセットロジックは上記 confirm_and_start_ocr と同じ
                file_actions = self.config.get("file_actions", {}); is_dx_standard = self.active_api_profile.get('id') == 'dx_standard_v2'
                if is_dx_standard:
                    item.json_status = "処理待ち" if file_actions.get("dx_standard_output_json", False) else "作成しない(設定)"; item.auto_csv_status = "処理待ち" if file_actions.get("dx_standard_auto_download_csv", False) else "作成しない(設定)"; item.searchable_pdf_status = "対象外"
                else:
                    output_format_cfg = file_actions.get("output_format", "both"); item.json_status = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"; item.searchable_pdf_status = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"; item.auto_csv_status = "対象外"
            updated_files_info.append(item)

        self.ocr_process_started_signal.emit(len(files_to_resume_tuples), updated_files_info)
        self._prepare_and_start_ocr_worker(files_to_resume_tuples, input_folder_path)
        self.request_ui_controls_update_signal.emit()

    def confirm_and_stop_ocr(self, parent_widget_for_dialog):
        self.log_manager.debug("OcrOrchestrator: Confirming process stop...", context="OCR_ORCH_FLOW_STOP")
        worker_to_stop = self.ocr_worker if self.ocr_worker and self.ocr_worker.isRunning() else self.sort_worker
        if worker_to_stop and worker_to_stop.isRunning():
            reply = QMessageBox.question(parent_widget_for_dialog, "処理中止確認", "現在の処理を中止しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("OcrOrchestrator: User confirmed process stop. Requesting worker to stop.", context="OCR_ORCH_FLOW_STOP")
                worker_to_stop.stop(); self.user_stopped = True
        else:
            if self.is_ocr_running:
                self.log_manager.warning(f"OcrOrchestrator: is_ocr_running was True but no active worker found. Resetting state.", context="OCR_ORCH_STATE_MISMATCH")
                self.is_ocr_running = False; self.ocr_process_finished_signal.emit(True, {"message": "処理状態の不整合により停止", "code": "STATE_INCONSISTENCY_STOP"}); self.sort_process_finished_signal.emit(True, {"message": "処理状態の不整合により停止", "code": "STATE_INCONSISTENCY_STOP"})
            self.request_ui_controls_update_signal.emit()

    def confirm_and_start_sort(self, processed_files_info: List[FileInfo], sort_config_id: str, input_folder_path: str):
        self.log_manager.debug("OcrOrchestrator: Starting sort process...", context="SORT_ORCH_FLOW")
        self.is_ocr_running = True; self.user_stopped = False; self.request_ui_controls_update_signal.emit()
        file_paths_to_sort = [f.path for f in processed_files_info if f.is_checked]
        self.sort_worker = SortWorker(api_client=self.api_client, file_paths=file_paths_to_sort, sort_config_id=sort_config_id, log_manager=self.log_manager, input_root_folder=input_folder_path, config=self.config)
        self.sort_worker.sort_status_update.connect(self._handle_sort_worker_status_update); self.sort_worker.sort_finished.connect(self._handle_sort_worker_finished)
        self.sort_process_started_signal.emit(f"{len(file_paths_to_sort)}件のファイルで仕分け処理を開始します..."); self.sort_worker.start()

    def _handle_sort_worker_status_update(self, message: str):
        self.log_manager.info(message, context="SORT_STATUS_UPDATE")

    def _handle_sort_worker_finished(self, success: bool, result_or_error: object):
        self.log_manager.info(f"Orchestrator: Sort worker finished. Success: {success}", context="SORT_ORCH_FLOW"); self.is_ocr_running = False; self.sort_worker = None
        self.sort_process_finished_signal.emit(success, result_or_error); self.request_ui_controls_update_signal.emit()

    def get_is_ocr_running(self) -> bool: return self.is_ocr_running
    def set_is_ocr_running(self, is_running: bool): self.is_ocr_running = is_running

    def update_config(self, new_config: dict, new_api_profile_schema: Optional[Dict[str, Any]]):
        self.log_manager.info("OcrOrchestrator: 設定更新中...", context="OCR_ORCH_CONFIG")
        self.config = new_config
        if new_api_profile_schema:
            self.active_api_profile = new_api_profile_schema
            self.log_manager.info(f"OcrOrchestrator: アクティブAPIプロファイルスキーマを '{new_api_profile_schema.get('name')}' に更新しました。", context="OCR_ORCH_CONFIG")
        else: 
            current_profile_id = new_config.get("current_api_profile_id"); active_profile_from_cfg = ConfigManager.get_api_profile(new_config, current_profile_id) 
            if active_profile_from_cfg: self.active_api_profile = active_profile_from_cfg
            elif new_config.get("api_profiles"): self.active_api_profile = new_config["api_profiles"][0]; self.log_manager.warning("プロファイルが見つからずフォールバックしました。", context="OCR_ORCH_CONFIG")
            else: self.log_manager.error("有効なAPIプロファイルが見つかりません。", context="OCR_ORCH_CONFIG"); self.active_api_profile = {}
        
        self._set_classes_by_profile()

    def export_results_to_csv(self, processed_files: List[FileInfo], input_root_folder: str):
        if not self.active_api_profile or self.active_api_profile.get("id") != "dx_atypical_v2": return
        self.log_manager.info("OCR処理完了。CSVエクスポートの準備をします。", context="CSV_EXPORT")
        successful_files = [f for f in processed_files if f.ocr_engine_status == OCR_STATUS_COMPLETED]
        if not successful_files: return
        if not input_root_folder or not os.path.isdir(input_root_folder): return
        results_folder_name = self.config.get("file_actions", {}).get("results_folder_name", "OCR結果")
        output_dir = os.path.join(input_root_folder, results_folder_name)
        os.makedirs(output_dir, exist_ok=True)
        csv_filename = f"{os.path.basename(os.path.normpath(input_root_folder))}.csv"
        output_csv_path = os.path.join(output_dir, csv_filename)
        active_options = ConfigManager.get_active_api_options_values(self.config)
        model_id = active_options.get("model") if active_options else None
        if not model_id: return
        export_atypical_to_csv(successful_files, output_csv_path, self.log_manager, model_id)