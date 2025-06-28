# ocr_worker_fulltext.py

import os
import json
import datetime
import time
import shutil
import threading
import tempfile
from typing import Optional, Dict, Any, List, Tuple

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from PyQt6.QtCore import QThread, pyqtSignal

from app_constants import (
    OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING,
    OCR_STATUS_MERGING, OCR_STATUS_COMPLETED, OCR_STATUS_FAILED
)
from api_client_fulltext import OCRApiClientFulltext

# ポーリング設定のデフォルト値
DEFAULT_POLLING_INTERVAL_SECONDS = 3
DEFAULT_POLLING_MAX_ATTEMPTS = 60


class OcrWorkerFulltext(QThread):
    file_processed = pyqtSignal(int, str, object, object, object, object)
    auto_csv_processed = pyqtSignal(int, str, object)
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
    all_files_processed = pyqtSignal()
    original_file_status_update = pyqtSignal(str, str)

    def __init__(self, api_client: OCRApiClientFulltext, files_to_process_tuples: List[Tuple[str, int]],
                input_root_folder: str, log_manager, config: Dict[str, Any],
                api_profile: Optional[Dict[str, Any]]):
        super().__init__()
        self.api_client = api_client
        self.files_to_process_tuples = files_to_process_tuples
        self.is_running = True
        self.user_stopped = False
        self.input_root_folder = input_root_folder
        self.log_manager = log_manager
        self.config = config
        self.active_api_profile = api_profile

        current_profile_id = self.active_api_profile.get("id") if self.active_api_profile else None
        self.current_api_options_values = self.config.get("options_values_by_profile", {}).get(current_profile_id, {})

        self.file_actions_config = self.config.get("file_actions", {})
        self.main_temp_dir_for_splits: Optional[str] = None
        self.log_manager.debug(f"FulltextOcrWorker initialized for API: {self.active_api_profile.get('name', 'N/A') if self.active_api_profile else 'Unknown'}",
                                context="WORKER_LIFECYCLE", num_original_files=len(self.files_to_process_tuples))
        self.encountered_fatal_error = False
        self.fatal_error_info: Optional[Dict[str, Any]] = None

    def _get_unique_filepath(self, target_dir: str, filename: str) -> str:
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath):
            new_filename = f"{base} ({counter}){ext}"
            new_filepath = os.path.join(target_dir, new_filename)
            counter += 1
        return new_filepath

    def _ensure_main_temp_dir_exists(self) -> Optional[str]:
        if self.main_temp_dir_for_splits is None:
            try:
                app_temp_base = tempfile.gettempdir()
                worker_temp_dirname = f"OcrClient_SplitWorker_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
                self.main_temp_dir_for_splits = os.path.join(app_temp_base, worker_temp_dirname)
                os.makedirs(self.main_temp_dir_for_splits, exist_ok=True)
                self.log_manager.info(f"Main temporary directory for splits created: {self.main_temp_dir_for_splits}", context="WORKER_TEMP_DIR")
            except Exception as e:
                self.log_manager.error(f"Failed to create main temporary directory for splits: {e}", context="WORKER_TEMP_DIR_ERROR", exc_info=True)
                self.main_temp_dir_for_splits = None
        return self.main_temp_dir_for_splits

    def _cleanup_main_temp_dir(self):
        if self.main_temp_dir_for_splits and os.path.isdir(self.main_temp_dir_for_splits):
            try:
                shutil.rmtree(self.main_temp_dir_for_splits)
                self.log_manager.info(f"Main temporary directory for splits cleaned up: {self.main_temp_dir_for_splits}", context="WORKER_TEMP_DIR")
            except Exception as e:
                self.log_manager.error(f"Failed to clean up main temporary directory {self.main_temp_dir_for_splits}: {e}", context="WORKER_TEMP_DIR_ERROR", exc_info=True)
        self.main_temp_dir_for_splits = None

    def _get_part_filename(self, original_basename: str, part_num: int, total_parts_estimate: int, original_ext: str) -> str:
        base = os.path.splitext(original_basename)[0]
        num_digits = len(str(total_parts_estimate)) if total_parts_estimate > 0 else 2
        if num_digits < 2: num_digits = 2
        if total_parts_estimate >= 1000: num_digits = 4
        elif total_parts_estimate >= 100: num_digits = 3
        return f"{base}.split#{str(part_num).zfill(num_digits)}{original_ext}"

    def _split_pdf_by_size(self, original_filepath: str, chunk_size_bytes: int, temp_dir_for_parts: str,
                            split_by_page_count_enabled: bool, max_pages_per_part: int) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        split_files: List[str] = []
        original_basename = os.path.basename(original_filepath)
        original_ext = os.path.splitext(original_basename)[1]
        part_counter = 1
        
        try:
            reader = PdfReader(original_filepath)
            total_pages = len(reader.pages)
            if total_pages == 0:
                msg = f"PDF '{original_basename}' にはページがありません。分割できません。"
                self.log_manager.warning(msg, context="WORKER_PDF_SPLIT")
                return [], {"message": msg, "code": "PDF_ZERO_PAGES"}

            original_size_bytes = os.path.getsize(original_filepath)
            self.log_manager.info(f"PDF '{original_basename}' ({total_pages}ページ, {original_size_bytes / (1024*1024):.2f}MB) を分割します。", context="WORKER_PDF_SPLIT")
            self.log_manager.info(f"  分割条件: サイズ目安={(chunk_size_bytes / (1024*1024)):.2f}MB, ページ数上限による分割={'有効' if split_by_page_count_enabled else '無効'} (上限={max_pages_per_part}ページ)", context="WORKER_PDF_SPLIT")

            average_page_size_bytes = original_size_bytes / total_pages if total_pages > 0 else 0
            chunk_size_with_margin = chunk_size_bytes * 0.9
            estimated_total_parts = 1
            if chunk_size_bytes > 0:
                estimated_total_parts = max(estimated_total_parts, -(-original_size_bytes // chunk_size_bytes))
            if split_by_page_count_enabled and max_pages_per_part > 0:
                estimated_total_parts = max(estimated_total_parts, -(-total_pages // max_pages_per_part))

            current_writer = PdfWriter()
            current_estimated_size = 0

            for i in range(total_pages):
                if not self.is_running: break

                current_writer.add_page(reader.pages[i])
                current_estimated_size += average_page_size_bytes

                is_last_page_of_original = (i == total_pages - 1)
                if not is_last_page_of_original:
                    must_cut = False
                    if split_by_page_count_enabled and len(current_writer.pages) >= max_pages_per_part:
                        must_cut = True
                    if not must_cut and chunk_size_bytes > 0 and current_estimated_size >= chunk_size_with_margin:
                        must_cut = True

                    if must_cut:
                        part_filename = self._get_part_filename(original_basename, part_counter, estimated_total_parts, original_ext)
                        part_filepath = os.path.join(temp_dir_for_parts, part_filename)
                        try:
                            with open(part_filepath, "wb") as f_out: current_writer.write(f_out)
                            split_files.append(part_filepath)
                        except IOError as e_io_write:
                            return [], {"message": f"PDF部品 '{part_filename}' の書き出しに失敗: {e_io_write}", "code": "SPLIT_PART_WRITE_ERROR", "detail": str(e_io_write)}
                        
                        part_counter += 1
                        current_writer = PdfWriter()
                        current_estimated_size = 0
            
            if len(current_writer.pages) > 0 and self.is_running:
                part_filename = self._get_part_filename(original_basename, part_counter, estimated_total_parts, original_ext)
                part_filepath = os.path.join(temp_dir_for_parts, part_filename)
                try:
                    with open(part_filepath, "wb") as f_out: current_writer.write(f_out)
                    split_files.append(part_filepath)
                except IOError as e_io_write_final:
                    return [], {"message": f"最終PDF部品 '{part_filename}' の書き出しに失敗: {e_io_write_final}", "code": "SPLIT_FINAL_PART_WRITE_ERROR", "detail": str(e_io_write_final)}

            if not self.is_running:
                return [], {"message": "PDF分割処理が中断されました", "code": "SPLIT_INTERRUPTED"}

        except Exception as e:
            return [], {"message": f"PDF '{original_basename}' の分割中にエラー発生: {e}", "code": "SPLIT_PDF_EXCEPTION", "detail": str(e)}
        
        return split_files, None

    def _split_file(self, original_filepath: str, base_temp_dir_for_parts: str) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        split_master_enabled = self.current_api_options_values.get("split_large_files_enabled", False)
        chunk_size_mb_for_size_split = self.current_api_options_values.get("split_chunk_size_mb", 10)
        upload_max_size_mb_threshold = self.current_api_options_values.get("upload_max_size_mb", 60)
        page_split_enabled = self.current_api_options_values.get("split_by_page_count_enabled", False)
        max_pages_per_part_for_page_split = self.current_api_options_values.get("split_max_pages_per_part", 100)
        upload_max_bytes_threshold = upload_max_size_mb_threshold * 1024 * 1024

        _, ext = os.path.splitext(original_filepath)
        original_basename = os.path.basename(original_filepath)
        ext_lower = ext.lower()
        split_part_paths: List[str] = []
        
        file_specific_temp_dir = os.path.join(base_temp_dir_for_parts, os.path.splitext(original_basename)[0] + "_parts")
        os.makedirs(file_specific_temp_dir, exist_ok=True)

        should_attempt_split = False
        if split_master_enabled and ext_lower == ".pdf":
            original_file_size_bytes = os.path.getsize(original_filepath)
            split_triggered_by_size = original_file_size_bytes > upload_max_bytes_threshold
            split_triggered_by_pages = False
            if page_split_enabled:
                reader = PdfReader(original_filepath)
                if len(reader.pages) > max_pages_per_part_for_page_split:
                    split_triggered_by_pages = True
            if split_triggered_by_size or split_triggered_by_pages:
                should_attempt_split = True

        if should_attempt_split:
            self.original_file_status_update.emit(original_filepath, OCR_STATUS_SPLITTING)
            split_part_paths, error_info = self._split_pdf_by_size(original_filepath, chunk_size_mb_for_size_split * 1024 * 1024, file_specific_temp_dir, page_split_enabled, max_pages_per_part_for_page_split)
            if error_info:
                self._try_cleanup_specific_temp_dirs(file_specific_temp_dir, None)
                return [], error_info
        
        if not split_part_paths:
            single_part_filename = self._get_part_filename(original_basename, 1, 1, ext)
            single_part_filepath = os.path.join(file_specific_temp_dir, single_part_filename)
            shutil.copy2(original_filepath, single_part_filepath)
            split_part_paths.append(single_part_filepath)
        
        return split_part_paths, None

    def _merge_searchable_pdfs(self, pdf_part_paths: List[str], final_merged_pdf_path: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if not pdf_part_paths:
            return None, {"message": "結合対象のPDF部品がありません。", "code": "MERGE_NO_PARTS"}
        merger = PdfMerger()
        try:
            for part_path in pdf_part_paths:
                if os.path.exists(part_path):
                    merger.append(part_path)
                else:
                    try: merger.close()
                    except Exception: pass
                    return None, {"message": f"結合用のPDF部品が見つかりません: {os.path.basename(part_path)}", "code": "MERGE_PART_NOT_FOUND"}
            os.makedirs(os.path.dirname(final_merged_pdf_path), exist_ok=True)
            merger.write(final_merged_pdf_path)
            return final_merged_pdf_path, None
        except Exception as e:
            if os.path.exists(final_merged_pdf_path):
                try: os.remove(final_merged_pdf_path)
                except Exception: pass
            return None, {"message": f"PDF結合エラー: {str(e)}", "code": "MERGE_EXCEPTION", "detail": str(e)}
        finally:
            try: merger.close()
            except Exception: pass

    def run(self):
        thread_id = threading.get_ident()
        self.log_manager.debug(f"FulltextOcrWorker thread started.", context="WORKER_LIFECYCLE", thread_id=thread_id)
        if not self._ensure_main_temp_dir_exists():
            self.all_files_processed.emit()
            return

        results_folder_name = self.file_actions_config.get("results_folder_name", "OCR結果")
        polling_interval = self.current_api_options_values.get("polling_interval_seconds", DEFAULT_POLLING_INTERVAL_SECONDS)
        max_polling_attempts = self.current_api_options_values.get("polling_max_attempts", DEFAULT_POLLING_MAX_ATTEMPTS)
        delete_job_after_processing = self.current_api_options_values.get("delete_job_after_processing", True)

        try:
            for _, (original_file_path, original_file_global_idx) in enumerate(self.files_to_process_tuples):
                if not self.is_running or self.encountered_fatal_error: break

                self.original_file_status_update.emit(original_file_path, f"{OCR_STATUS_PROCESSING} (準備中)")
                original_file_basename = os.path.basename(original_file_path)
                original_file_parent_dir = os.path.dirname(original_file_path)
                base_name_for_output_prefix = os.path.splitext(original_file_basename)[0]

                files_to_ocr, prep_error = self._split_file(original_file_path, self.main_temp_dir_for_splits)

                if prep_error or not files_to_ocr:
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, prep_error, "エラー", None)
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, {"message": "ファイル準備エラー", "code": "FILE_PREP_ERROR"})
                    continue
                
                parts_results_temp_dir = os.path.join(os.path.dirname(files_to_ocr[0]), base_name_for_output_prefix + "_results_parts")
                os.makedirs(parts_results_temp_dir, exist_ok=True)

                is_multi_part = len(files_to_ocr) > 1
                part_ocr_results = []
                part_pdf_paths = []
                all_parts_ok = True
                final_ocr_error = None
                final_pdf_error = None
                
                for part_idx, part_path in enumerate(files_to_ocr):
                    if not self.is_running or self.encountered_fatal_error:
                        all_parts_ok = False
                        if not final_ocr_error: final_ocr_error = {"message": "処理が中断/停止されました", "code": "USER_INTERRUPT"}
                        if not final_pdf_error: final_pdf_error = {"message": "処理が中断/停止されました", "code": "USER_INTERRUPT"}
                        break
                    
                    status_msg = f"{OCR_STATUS_PART_PROCESSING} ({part_idx + 1}/{len(files_to_ocr)})" if is_multi_part else OCR_STATUS_PROCESSING
                    self.original_file_status_update.emit(original_file_path, status_msg)

                    # --- OCR処理 ---
                    part_ocr_result_json = None
                    part_ocr_error = None
                    part_job_id = None
                    
                    ocr_response, ocr_error = self.api_client.read_document(part_path)
                    if ocr_error:
                        part_ocr_error = ocr_error
                    elif ocr_response and "registered" in ocr_response.get("status", ""):
                        part_job_id = ocr_response.get("job_id")
                        if not part_job_id:
                            part_ocr_error = {"message": "OCRジョブIDが取得できませんでした。", "code": "DXSUITE_NO_JOB_ID"}
                        else:
                            for attempt in range(max_polling_attempts):
                                if not self.is_running: break
                                poll_status_msg = f"{OCR_STATUS_PART_PROCESSING} (テキスト結果待機中 {attempt + 1}/{max_polling_attempts})"
                                self.original_file_status_update.emit(original_file_path, poll_status_msg)
                                
                                poll_res, poll_err = self.api_client.get_ocr_result(part_job_id)
                                if poll_err:
                                    part_ocr_error = poll_err
                                    break
                                
                                api_status = poll_res.get("status")
                                if api_status == "done":
                                    part_ocr_result_json = poll_res
                                    break
                                elif api_status == "error":
                                    part_ocr_error = {"message": "APIがエラーを返しました。", "code": "DXSUITE_OCR_API_ERROR", "detail": poll_res}
                                    break
                                time.sleep(polling_interval)
                            
                            if not part_ocr_result_json and not part_ocr_error and self.is_running:
                                part_ocr_error = {"message": "結果取得がタイムアウトしました。", "code": "DXSUITE_OCR_TIMEOUT"}
                    else: # Demoモードなど
                        part_ocr_result_json = ocr_response

                    if part_ocr_error:
                        all_parts_ok = False
                        final_ocr_error = part_ocr_error
                        break

                    part_ocr_results.append({"path": part_path, "result": part_ocr_result_json, "job_id": part_job_id})
                    
                    # --- JSON保存 ---
                    if self.file_actions_config.get("output_format", "both") in ["json_only", "both"]:
                        part_json_path = os.path.join(parts_results_temp_dir, f"{os.path.splitext(os.path.basename(part_path))[0]}.json")
                        with open(part_json_path, 'w', encoding='utf-8') as f:
                            json.dump(part_ocr_result_json, f, ensure_ascii=False, indent=2)
                    
                    # --- サーチャブルPDF作成 ---
                    if self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                        pdf_options = {"fullOcrJobId": part_job_id, **self.current_api_options_values}
                        pdf_response, pdf_error = self.api_client.make_searchable_pdf(part_path, pdf_options)
                        
                        part_pdf_content = None
                        if pdf_error:
                            final_pdf_error = pdf_error
                            all_parts_ok = False
                            break
                        elif pdf_response and "searchable_pdf_registered" in pdf_response.get("status", ""):
                            spdf_job_id = pdf_response.get("job_id")
                            if not spdf_job_id:
                                final_pdf_error = {"message": "サーチャブルPDFジョブIDが取得できませんでした。", "code": "DXSUITE_SPDF_NO_JOB_ID"}
                                all_parts_ok = False
                                break
                            
                            for attempt in range(max_polling_attempts):
                                if not self.is_running: break
                                poll_status_msg = f"{OCR_STATUS_PART_PROCESSING} (PDF結果待機中 {attempt + 1}/{max_polling_attempts})"
                                self.original_file_status_update.emit(original_file_path, poll_status_msg)

                                pdf_content, pdf_poll_error = self.api_client.get_searchable_pdf_content(spdf_job_id)
                                if pdf_poll_error:
                                    if "STATUS_INPROGRESS" in pdf_poll_error.get("code", "").upper():
                                        time.sleep(polling_interval)
                                        continue
                                    final_pdf_error = pdf_poll_error
                                    all_parts_ok = False
                                    break
                                part_pdf_content = pdf_content
                                break
                            
                            if not part_pdf_content and not final_pdf_error and self.is_running:
                                final_pdf_error = {"message": "サーチャブルPDF取得がタイムアウトしました。", "code": "DXSUITE_SPDF_TIMEOUT"}
                                all_parts_ok = False
                        else: # Demoモードなど
                            part_pdf_content = pdf_response
                        
                        if part_pdf_content:
                            part_pdf_path = os.path.join(parts_results_temp_dir, os.path.basename(part_path))
                            with open(part_pdf_path, 'wb') as f:
                                f.write(part_pdf_content)
                            part_pdf_paths.append(part_pdf_path)
                        elif not final_pdf_error:
                            all_parts_ok = False
                            final_pdf_error = {"message": "PDF作成で有効な応答がありませんでした", "code": "PDF_NO_VALID_RESPONSE"}
                            break

                    if delete_job_after_processing and part_job_id:
                        self.api_client.delete_job(part_job_id)

                # --- 全部品の処理完了後 ---
                job_id_for_signal = part_ocr_results[0]['job_id'] if part_ocr_results else None
                if all_parts_ok:
                    final_ocr_result = part_ocr_results[0]['result'] if not is_multi_part else {"status": OCR_STATUS_COMPLETED, "detail": f"{len(part_ocr_results)}部品のOCR完了"}
                    
                    json_status_ui = "作成しない(設定)"
                    if self.file_actions_config.get("output_format", "both") in ["json_only", "both"]:
                        final_json_dir = os.path.join(original_file_parent_dir, results_folder_name)
                        os.makedirs(final_json_dir, exist_ok=True)
                        if is_multi_part:
                            for item in os.listdir(parts_results_temp_dir):
                                if item.endswith(".json"): shutil.copy2(os.path.join(parts_results_temp_dir, item), self._get_unique_filepath(final_json_dir, item))
                            json_status_ui = f"{len(part_ocr_results)}個の部品JSON成功"
                        else:
                            shutil.copy2(os.path.join(parts_results_temp_dir, f"{os.path.splitext(os.path.basename(files_to_ocr[0]))[0]}.json"), self._get_unique_filepath(final_json_dir, f"{base_name_for_output_prefix}.json"))
                            json_status_ui = "JSON作成成功"
                    
                    self.file_processed.emit(original_file_global_idx, original_file_path, final_ocr_result, None, json_status_ui, job_id_for_signal)

                    pdf_final_path_for_signal = None
                    if self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                        merge_pdfs = self.current_api_options_values.get("merge_split_pdf_parts", True)
                        if is_multi_part and merge_pdfs:
                            self.original_file_status_update.emit(original_file_path, OCR_STATUS_MERGING)
                            final_pdf_dir = os.path.join(original_file_parent_dir, results_folder_name)
                            merged_pdf_path = self._get_unique_filepath(final_pdf_dir, f"{base_name_for_output_prefix}.pdf")
                            pdf_final_path_for_signal, final_pdf_error = self._merge_searchable_pdfs(part_pdf_paths, merged_pdf_path)
                        elif part_pdf_paths:
                            # 単一部品 or マージしない設定
                            final_pdf_dir = os.path.join(original_file_parent_dir, results_folder_name)
                            os.makedirs(final_pdf_dir, exist_ok=True)
                            for pdf_path in part_pdf_paths:
                                dest_path = self._get_unique_filepath(final_pdf_dir, os.path.basename(pdf_path))
                                shutil.copy2(pdf_path, dest_path)
                                if not is_multi_part: pdf_final_path_for_signal = dest_path
                            if is_multi_part and not merge_pdfs:
                                final_pdf_error = {"message": f"{len(part_pdf_paths)}個の部品PDF出力成功", "code": "PARTS_COPIED_SUCCESS"}
                    elif self.file_actions_config.get("output_format", "both") == "json_only":
                        final_pdf_error = {"message": "作成しない(設定)", "code": "PDF_NOT_REQUESTED"}

                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, pdf_final_path_for_signal, final_pdf_error)

                else: # if not all_parts_ok
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, final_ocr_error, "エラー", job_id_for_signal)
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, final_pdf_error or {"message": "OCRエラーのためPDF作成スキップ", "code": "PDF_SKIPPED_DUE_TO_OCR_ERROR"})

                # ファイル移動
                if os.path.exists(original_file_path):
                    self._move_file_if_configured(original_file_path, all_parts_ok)
                
                self._try_cleanup_specific_temp_dirs(os.path.dirname(files_to_ocr[0]), parts_results_temp_dir)

        finally:
            self._cleanup_main_temp_dir()
            self.all_files_processed.emit()
            self.log_manager.debug(f"FulltextOcrWorker thread finished.", context="WORKER_LIFECYCLE", thread_id=thread_id)

    def stop(self):
        self.is_running = False
        self.user_stopped = True

    def _move_file_if_configured(self, file_path, was_successful):
        dest_subfolder = None
        if was_successful and self.file_actions_config.get("move_on_success_enabled", False):
            dest_subfolder = self.file_actions_config.get("success_folder_name")
        elif not was_successful and self.file_actions_config.get("move_on_failure_enabled", False):
            dest_subfolder = self.file_actions_config.get("failure_folder_name")

        if dest_subfolder:
            collision_action = self.file_actions_config.get("collision_action", "rename")
            parent_dir = os.path.dirname(file_path)
            dest_dir = os.path.join(parent_dir, dest_subfolder)
            os.makedirs(dest_dir, exist_ok=True)
            
            final_dest_path = os.path.join(dest_dir, os.path.basename(file_path))
            if os.path.exists(final_dest_path):
                if collision_action == "rename":
                    final_dest_path = self._get_unique_filepath(dest_dir, os.path.basename(file_path))
                elif collision_action == "skip":
                    return
            
            shutil.move(file_path, final_dest_path)
    
    def _try_cleanup_specific_temp_dirs(self, source_parts_dir: Optional[str], results_parts_dir: Optional[str]):
        if source_parts_dir and os.path.isdir(source_parts_dir):
            shutil.rmtree(source_parts_dir)
        if results_parts_dir and os.path.isdir(results_parts_dir):
            shutil.rmtree(results_parts_dir)
