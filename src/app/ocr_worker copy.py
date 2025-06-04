# ocr_worker.py

import os
import json
import datetime
import time
import shutil
import threading
import io
import tempfile
from typing import Optional, Dict, Any, List, Tuple

from PyPDF2 import PdfReader, PdfWriter, PdfMerger # PyPDF2 のインポートを確認
from PyQt6.QtCore import QThread, pyqtSignal

from app_constants import (
    OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING,
    OCR_STATUS_MERGING
)

class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object, object)
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
    all_files_processed = pyqtSignal() 
    original_file_status_update = pyqtSignal(str, str)

    def __init__(self, api_client, files_to_process_tuples: List[Tuple[str, int]], 
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
        self.log_manager.debug(f"OcrWorker initialized for API: {self.active_api_profile.get('name', 'N/A') if self.active_api_profile else 'Unknown'}", 
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
                worker_temp_dirname = f"CubeOCR_SplitWorker_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
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

    def _split_pdf_by_size(self, original_filepath: str, chunk_size_bytes: int, temp_dir_for_parts: str) -> Tuple[List[str], Optional[Dict[str, Any]]]:
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
            
            # ★★★ 分割条件の確認は _split_file に移譲したので、ここでは分割処理のみを行う想定 ★★★
            # ただし、この関数が呼ばれる時点で分割が必要と判断されているはず。
            # 万が一、単一ページでこの関数が呼ばれた場合（現状のロジックでは起こりうる）は分割しない。
            if total_pages == 1: # 単一ページPDFは分割しない
                 self.log_manager.info(f"PDF '{original_basename}' は単一ページのため、分割しません。", context="WORKER_PDF_SPLIT")
                 return [], None

            self.log_manager.info(f"PDF '{original_basename}' ({original_size_bytes / (1024*1024):.2f}MB) を約 {chunk_size_bytes / (1024*1024):.2f}MB ごとに分割します。", context="WORKER_PDF_SPLIT")
            estimated_total_parts = max(1, -(-original_size_bytes // chunk_size_bytes)) 
            current_writer = PdfWriter()
            for i in range(total_pages):
                if not self.is_running: break
                if len(current_writer.pages) > 0:
                    with io.BytesIO() as temp_buffer_check:
                        current_writer.write(temp_buffer_check)
                        current_writer_size = temp_buffer_check.tell()
                    if current_writer_size >= chunk_size_bytes * 0.85: 
                        part_filename = self._get_part_filename(original_basename, part_counter, estimated_total_parts, original_ext)
                        part_filepath = os.path.join(temp_dir_for_parts, part_filename)
                        try:
                            with open(part_filepath, "wb") as f_out: current_writer.write(f_out)
                            split_files.append(part_filepath)
                            self.log_manager.info(f"PDF部品保存: {part_filepath} ({len(current_writer.pages)} ページ, サイズ: {current_writer_size} バイト)", context="WORKER_PDF_SPLIT")
                        except IOError as e_io_write:
                            msg = f"PDF部品 '{part_filename}' の書き出しに失敗: {e_io_write}"
                            self.log_manager.error(msg, context="WORKER_PDF_SPLIT_IO_ERROR", exc_info=True)
                            return [], {"message": msg, "code": "SPLIT_PART_WRITE_ERROR", "detail": str(e_io_write)}
                        part_counter += 1
                        current_writer = PdfWriter() 
                current_writer.add_page(reader.pages[i])
            
            if len(current_writer.pages) > 0 and self.is_running: 
                part_filename = self._get_part_filename(original_basename, part_counter, estimated_total_parts, original_ext)
                part_filepath = os.path.join(temp_dir_for_parts, part_filename)
                try:
                    with open(part_filepath, "wb") as f_out: current_writer.write(f_out)
                    split_files.append(part_filepath)
                    self.log_manager.info(f"最終PDF部品保存: {part_filepath} ({len(current_writer.pages)} ページ)", context="WORKER_PDF_SPLIT")
                except IOError as e_io_write_final:
                    msg = f"最終PDF部品 '{part_filename}' の書き出しに失敗: {e_io_write_final}"
                    self.log_manager.error(msg, context="WORKER_PDF_SPLIT_IO_ERROR", exc_info=True)
                    return [], {"message": msg, "code": "SPLIT_FINAL_PART_WRITE_ERROR", "detail": str(e_io_write_final)}
            
            if not self.is_running:
                self.log_manager.info("PDF分割処理が中断されました。", context="WORKER_PDF_SPLIT")
                return [], {"message": "PDF分割処理が中断されました", "code": "SPLIT_INTERRUPTED"}
        except Exception as e:
            msg = f"PDF '{original_basename}' の分割中にエラー発生: {e}"
            self.log_manager.error(msg, context="WORKER_PDF_SPLIT_ERROR", exc_info=True)
            return [], {"message": msg, "code": "SPLIT_PDF_EXCEPTION", "detail": str(e)}
        return split_files, None

    def _split_file(self, original_filepath: str, base_temp_dir_for_parts: str) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        split_enabled = self.current_api_options_values.get("split_large_files_enabled", False)
        chunk_size_mb = self.current_api_options_values.get("split_chunk_size_mb", 10)
        upload_max_size_mb = self.current_api_options_values.get("upload_max_size_mb", 60)
        upload_max_bytes = upload_max_size_mb * 1024 * 1024
        
        _, ext = os.path.splitext(original_filepath)
        original_basename = os.path.basename(original_filepath)
        ext_lower = ext.lower()
        split_part_paths: List[str] = []
        error_info: Optional[Dict[str, Any]] = None
        
        file_specific_temp_dir = os.path.join(base_temp_dir_for_parts, os.path.splitext(original_basename)[0] + "_parts")
        try:
            os.makedirs(file_specific_temp_dir, exist_ok=True)
        except Exception as e_mkdir:
            msg = f"ファイル '{original_basename}' 用の一時部品フォルダ作成に失敗: {e_mkdir}"
            self.log_manager.error(msg, context="WORKER_FILE_SPLIT_ERROR", exc_info=True)
            return [], {"message": msg, "code": "TEMP_PART_DIR_ERROR", "detail": str(e_mkdir)}

        original_file_size_bytes = os.path.getsize(original_filepath)
        
        # 分割実行条件
        should_attempt_split = (
            split_enabled and 
            ext_lower == ".pdf" and 
            original_file_size_bytes > upload_max_bytes # ここでのupload_max_bytesは分割の閾値として利用
        )

        if should_attempt_split:
            self.original_file_status_update.emit(original_filepath, OCR_STATUS_SPLITTING)
            split_part_paths, error_info = self._split_pdf_by_size(original_filepath, chunk_size_mb * 1024 * 1024, file_specific_temp_dir)
            if error_info:
                self._try_cleanup_specific_temp_dirs(file_specific_temp_dir, None)
                return [], error_info
            # _split_pdf_by_size が空リストを返した場合（例：単一ページPDFで分割不要と判断された）
            # 以下のifブロックで単一部品としてコピーされる
        
        if not split_part_paths: # 分割が行われなかった場合 (分割対象外、または_split_pdf_by_sizeが空を返した場合)
            try:
                single_part_filename = self._get_part_filename(original_basename, 1, 1, ext)
                single_part_filepath = os.path.join(file_specific_temp_dir, single_part_filename)
                shutil.copy2(original_filepath, single_part_filepath)
                split_part_paths.append(single_part_filepath)
                self.log_manager.info(f"元ファイル '{original_basename}' を単一部品として一時フォルダにコピーしました: {single_part_filepath}", context="WORKER_FILE_SPLIT")
            except Exception as e:
                msg = f"ファイル '{original_basename}' の単一部品としてのコピーに失敗: {e}"
                self.log_manager.error(msg, context="WORKER_FILE_SPLIT_ERROR", exc_info=True)
                self._try_cleanup_specific_temp_dirs(file_specific_temp_dir, None)
                return [], {"message": msg, "code": "COPY_SINGLE_PART_ERROR", "detail": str(e)}
        
        return split_part_paths, None

    def _merge_searchable_pdfs(self, pdf_part_paths: List[str], final_merged_pdf_path: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if not pdf_part_paths:
            msg = "結合対象のPDF部品がありません。"
            self.log_manager.warning(msg, context="WORKER_PDF_MERGE")
            return None, {"message": msg, "code": "MERGE_NO_PARTS"}
        merger = PdfMerger()
        try:
            for part_path in pdf_part_paths:
                if os.path.exists(part_path):
                    merger.append(part_path)
                else:
                    msg = f"結合用のPDF部品が見つかりません: {os.path.basename(part_path)}"
                    self.log_manager.error(msg, context="WORKER_PDF_MERGE_ERROR")
                    return None, {"message": msg, "code": "MERGE_PART_NOT_FOUND"}
            final_dir = os.path.dirname(final_merged_pdf_path)
            os.makedirs(final_dir, exist_ok=True)
            merger.write(final_merged_pdf_path)
            self.log_manager.info(f"サーチャブルPDF部品を正常に結合しました: {final_merged_pdf_path}", context="WORKER_PDF_MERGE")
            return final_merged_pdf_path, None 
        except Exception as e:
            msg = f"PDF部品の結合中にエラー発生 ({final_merged_pdf_path}): {e}"
            self.log_manager.error(msg, context="WORKER_PDF_MERGE_ERROR", exc_info=True)
            if os.path.exists(final_merged_pdf_path):
                try: os.remove(final_merged_pdf_path)
                except Exception as e_remove: self.log_manager.warning(f"不完全な結合済みPDF '{final_merged_pdf_path}' の削除に失敗: {e_remove}", context="WORKER_PDF_MERGE_CLEANUP_ERROR")
            return None, {"message": f"PDF結合エラー: {str(e)}", "code": "MERGE_EXCEPTION", "detail": str(e)}
        finally:
            try: merger.close()
            except Exception: pass

    def run(self):
        thread_id = threading.get_ident()
        api_profile_name = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else 'UnknownProfile'
        self.log_manager.debug(f"OcrWorker thread started for API: {api_profile_name}.", 
                               context="WORKER_LIFECYCLE", thread_id=thread_id, num_original_files=len(self.files_to_process_tuples))
        
        if not self._ensure_main_temp_dir_exists():
            self.log_manager.critical("メイン一時フォルダの作成に失敗しました。処理を続行できません。", context="WORKER_LIFECYCLE")
            self.all_files_processed.emit()
            return

        results_folder_name = self.file_actions_config.get("results_folder_name", "OCR結果")
        
        try:
            for worker_internal_idx, (original_file_path, original_file_global_idx) in enumerate(self.files_to_process_tuples):
                if not self.is_running or self.encountered_fatal_error:
                    stop_msg_suffix = f"({self.fatal_error_info.get('code') if self.fatal_error_info else 'N/A'})" if self.encountered_fatal_error else "(ユーザーにより中止)"
                    self.log_manager.warning(f"OcrWorker: 後続のファイル処理を中止します。理由: 致命的エラーまたはユーザー中止 {stop_msg_suffix}", context="WORKER_LIFECYCLE")
                    break
                
                self.original_file_status_update.emit(original_file_path, f"{OCR_STATUS_PROCESSING} (準備中)")
                original_file_basename = os.path.basename(original_file_path)
                original_file_parent_dir = os.path.dirname(original_file_path)
                base_name_for_output_prefix = os.path.splitext(original_file_basename)[0]
                self.log_manager.info(f"元ファイル処理開始: '{original_file_basename}' (グローバルインデックス: {original_file_global_idx})", context="WORKER_ORIGINAL_FILE")

                current_file_parts_source_dir: Optional[str] = None
                parts_results_temp_dir: Optional[str] = None # 部品ごとのJSONやPDFを一時保存するディレクトリ
                
                files_to_ocr_for_this_original, prep_error_info = self._split_file(
                    original_file_path, self.main_temp_dir_for_splits
                )

                if prep_error_info or not files_to_ocr_for_this_original:
                    self.log_manager.error(f"'{original_file_basename}' のファイル準備(分割/コピー)に失敗しました。エラー: {prep_error_info}", context="WORKER_FILE_PREP_ERROR")
                    err_dict = prep_error_info if prep_error_info else {"message": "ファイル準備失敗 (詳細不明)", "code": "FILE_PREP_UNKNOWN_ERROR"}
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー")
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                    continue
                
                is_genuinely_multi_part = len(files_to_ocr_for_this_original) > 1
                self.log_manager.info(f"ファイル '{original_file_basename}' は {len(files_to_ocr_for_this_original)} 個の部品として処理されます (is_multi_part: {is_genuinely_multi_part})。", context="WORKER_FILE_SPLIT_INFO")

                if files_to_ocr_for_this_original: 
                    current_file_parts_source_dir = os.path.dirname(files_to_ocr_for_this_original[0])
                    # 部品の結果を一時保存するディレクトリ (分割されてもされなくても、この一時ディレクトリを使う)
                    if current_file_parts_source_dir:
                        parts_results_temp_dir = os.path.join(current_file_parts_source_dir, base_name_for_output_prefix + "_results_parts")
                        try: os.makedirs(parts_results_temp_dir, exist_ok=True)
                        except Exception as e_mkdir_results:
                            msg = f"'{original_file_basename}' の部品結果用一時フォルダ作成に失敗: {e_mkdir_results}"
                            self.log_manager.error(msg, context="WORKER_FILE_SPLIT_ERROR", exc_info=True); err_dict = {"message": msg, "code": "TEMP_RESULTS_DIR_ERROR", "detail": str(e_mkdir_results)}
                            self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー"); self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                            self._try_cleanup_specific_temp_dirs(current_file_parts_source_dir, None); continue
                    else: # Should not happen if files_to_ocr_for_this_original is populated
                        msg = f"部品ソースディレクトリが未設定のため、'{original_file_basename}' の部品結果用一時フォルダを作成できません。"
                        self.log_manager.error(msg, context="WORKER_FILE_SPLIT_ERROR"); err_dict = {"message": msg, "code": "TEMP_SOURCE_DIR_MISSING"}
                        self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー"); self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                        continue


                part_ocr_results_agg: List[Dict[str,Any]] = [] 
                part_pdf_paths_agg: List[str] = []   
                all_parts_processed_successfully = True
                final_ocr_result_for_main: Any = None
                final_ocr_error_for_main: Optional[Dict[str, Any]] = None
                json_status_for_original_file = "作成しない(設定)" 
                pdf_final_path_for_signal: Optional[str] = None
                pdf_error_for_signal: Optional[Dict[str, Any]] = None

                active_profile_options = self.current_api_options_values

                for part_idx, current_processing_path in enumerate(files_to_ocr_for_this_original):
                    if not self.is_running: 
                        all_parts_processed_successfully = False
                        stop_reason_code = "USER_INTERRUPT" if self.user_stopped else (self.fatal_error_info.get("code", "FATAL_ERROR_STOP") if self.fatal_error_info else "FATAL_ERROR_STOP")
                        stop_reason_msg = "ユーザーにより中止" if self.user_stopped else (self.fatal_error_info.get("message", "致命的エラー") if self.fatal_error_info else "エラーにより停止")
                        self.log_manager.info(f"'{original_file_basename}' の部品処理が「{stop_reason_msg}」のため中断されました。", context="WORKER_PART_PROCESS")
                        final_ocr_error_for_main = {"message": stop_reason_msg, "code": stop_reason_code}
                        pdf_error_for_signal = {"message": f"{stop_reason_msg}のためPDF作成不可", "code": f"{stop_reason_code}_PDF"}
                        break 
                    
                    current_part_basename = os.path.basename(current_processing_path) 
                    status_msg_for_ui = f"{OCR_STATUS_PART_PROCESSING} ({part_idx + 1}/{len(files_to_ocr_for_this_original)})" if is_genuinely_multi_part else OCR_STATUS_PROCESSING
                    self.original_file_status_update.emit(original_file_path, status_msg_for_ui)
                    self.log_manager.info(f"  部品処理中: '{current_part_basename}' (元ファイル: '{original_file_basename}')", context="WORKER_PART_PROCESS")

                    part_ocr_result_json, part_ocr_api_error_info = self.api_client.read_document(current_processing_path, specific_options=active_profile_options)

                    if part_ocr_api_error_info:
                        self.log_manager.error(f"  部品 '{current_part_basename}' のOCR API処理失敗。エラー: {part_ocr_api_error_info.get('message')}", context="WORKER_PART_OCR_ERROR", detail=part_ocr_api_error_info)
                        all_parts_processed_successfully = False; final_ocr_error_for_main = part_ocr_api_error_info
                        if part_ocr_api_error_info.get("code") in ["NOT_IMPLEMENTED_API_CALL", "NOT_IMPLEMENTED_LIVE_API"]: 
                            self.encountered_fatal_error = True; self.fatal_error_info = part_ocr_api_error_info; self.is_running = False 
                        break 
                    part_ocr_results_agg.append({"path": current_processing_path, "result": part_ocr_result_json})
                    
                    should_create_json = self.file_actions_config.get("output_format", "both") in ["json_only", "both"]
                    if should_create_json and parts_results_temp_dir: 
                        part_json_filename = os.path.splitext(current_part_basename)[0] + ".json" 
                        part_json_filepath = os.path.join(parts_results_temp_dir, part_json_filename)
                        try:
                            with open(part_json_filepath, 'w', encoding='utf-8') as f_json: json.dump(part_ocr_result_json, f_json, ensure_ascii=False, indent=2)
                            self.log_manager.info(f"  部品用JSON保存完了: '{part_json_filepath}'", context="WORKER_PART_IO")
                        except IOError as e_json_save:
                            msg = f"部品 '{current_part_basename}' のJSON保存に失敗: {e_json_save}"; self.log_manager.error(msg, context="WORKER_PART_IO_ERROR", exc_info=True)
                            all_parts_processed_successfully = False; final_ocr_error_for_main = {"message": msg, "code": "PART_JSON_SAVE_ERROR", "detail": str(e_json_save)}; break
                    
                    should_create_pdf = self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]
                    if should_create_pdf and parts_results_temp_dir: 
                        self.log_manager.info(f"  部品のサーチャブルPDF作成開始: '{current_part_basename}'", context="WORKER_PART_PDF")
                        part_pdf_content, part_pdf_api_error_info = self.api_client.make_searchable_pdf(current_processing_path, specific_options=active_profile_options)

                        if part_pdf_api_error_info:
                            self.log_manager.error(f"  部品 '{current_part_basename}' のサーチャブルPDF作成API失敗。エラー: {part_pdf_api_error_info.get('message')}", context="WORKER_PART_PDF_ERROR", detail=part_pdf_api_error_info)
                            all_parts_processed_successfully = False; pdf_error_for_signal = part_pdf_api_error_info
                            if part_pdf_api_error_info.get("code") in ["NOT_IMPLEMENTED_API_CALL_PDF", "NOT_IMPLEMENTED_LIVE_API_PDF"]: 
                                self.encountered_fatal_error = True; self.fatal_error_info = part_pdf_api_error_info; self.is_running = False
                            break
                        elif part_pdf_content:
                            part_pdf_filename = current_part_basename 
                            part_pdf_filepath = os.path.join(parts_results_temp_dir, part_pdf_filename)
                            try:
                                with open(part_pdf_filepath, 'wb') as f_pdf: f_pdf.write(part_pdf_content)
                                self.log_manager.info(f"  部品用サーチャブルPDF保存完了: '{part_pdf_filepath}'", context="WORKER_PART_IO"); part_pdf_paths_agg.append(part_pdf_filepath)
                            except IOError as e_pdf_save:
                                msg = f"部品 '{current_part_basename}' のサーチャブルPDF保存に失敗: {e_pdf_save}"; self.log_manager.error(msg, context="WORKER_PART_IO_ERROR", exc_info=True)
                                all_parts_processed_successfully = False; pdf_error_for_signal = {"message": msg, "code": "PART_PDF_SAVE_ERROR", "detail": str(e_pdf_save)}; break
                        else:
                            msg = f"部品 '{current_part_basename}' のサーチャブルPDF APIがコンテンツもエラーも返しませんでした。"; self.log_manager.error(msg, context="WORKER_PART_PDF_ERROR")
                            all_parts_processed_successfully = False; pdf_error_for_signal = {"message": msg, "code": "PART_PDF_NO_RESPONSE"}; break
                
                if not self.is_running and not all_parts_processed_successfully: 
                     stop_reason_code = "USER_INTERRUPT" if self.user_stopped else (self.fatal_error_info.get("code", "FATAL_ERROR_STOP") if self.fatal_error_info else "FATAL_ERROR_STOP")
                     stop_reason_msg = "ユーザーにより中止" if self.user_stopped else (self.fatal_error_info.get("message", "致命的エラー") if self.fatal_error_info else "エラーにより停止")
                     self.log_manager.info(f"'{original_file_basename}' の処理が「{stop_reason_msg}」のため中断/停止されました。", context="WORKER_LIFECYCLE")
                     if not final_ocr_error_for_main: final_ocr_error_for_main = {"message": stop_reason_msg, "code": stop_reason_code}
                     if not pdf_error_for_signal and self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                         pdf_error_for_signal = {"message": f"{stop_reason_msg}のためPDF作成不可", "code": f"{stop_reason_code}_PDF"}
                elif not self.is_running and all_parts_processed_successfully: 
                     self.log_manager.warning(f"'{original_file_basename}' の処理は成功しましたが、ワーカーは停止されました（予期せぬ状態）。", context="WORKER_LIFECYCLE_UNEXPECTED")

                if all_parts_processed_successfully:
                    self.log_manager.info(f"'{original_file_basename}' の全部品のOCR処理と中間ファイル保存が成功しました。", context="WORKER_ORIGINAL_FILE")
                    if is_genuinely_multi_part: # ★ 修正: 実際に複数部品の場合
                        final_ocr_result_for_main = {"status": "parts_processed_ok", "num_parts": len(files_to_ocr_for_this_original), "detail": f"{len(files_to_ocr_for_this_original)}部品のOCR完了"}
                    elif part_ocr_results_agg: 
                        final_ocr_result_for_main = part_ocr_results_agg[0]["result"]
                    else: 
                        final_ocr_result_for_main = {"status": "ocr_done_no_parts_data_unexpected", "message": "OCR成功(データ無)", "code": "OCR_NO_DATA"}
                    
                    should_create_json_globally = self.file_actions_config.get("output_format", "both") in ["json_only", "both"]
                    if should_create_json_globally:
                        final_json_output_dir = os.path.join(original_file_parent_dir, results_folder_name); os.makedirs(final_json_output_dir, exist_ok=True)
                        copied_json_count = 0
                        
                        if parts_results_temp_dir and os.path.isdir(parts_results_temp_dir):
                            for item_name in os.listdir(parts_results_temp_dir):
                                if item_name.endswith(".json") and (is_genuinely_multi_part or ".split#" in item_name): # 部品JSON、または単一処理された一時JSON
                                    src_json_path = os.path.join(parts_results_temp_dir, item_name)
                                    
                                    if is_genuinely_multi_part:
                                        final_json_filename = item_name 
                                    else: 
                                        final_json_filename = f"{base_name_for_output_prefix}.json" # 元のファイル名に戻す
                                    
                                    dest_json_path = self._get_unique_filepath(final_json_output_dir, final_json_filename)
                                    try:
                                        shutil.copy2(src_json_path, dest_json_path)
                                        self.log_manager.info(f"JSONファイルを最終保存先にコピー: {dest_json_path}", context="WORKER_PART_IO_FINAL")
                                        copied_json_count += 1
                                    except Exception as e_copy_json:
                                        self.log_manager.error(f"JSONファイル '{src_json_path}' の最終保存先へのコピー失敗: {e_copy_json}", context="WORKER_PART_IO_FINAL_ERROR", exc_info=True)
                            
                            num_expected_parts = len(files_to_ocr_for_this_original)
                            if num_expected_parts == 0 and copied_json_count == 0: 
                                json_status_for_original_file = "JSON部品なし (対象部品0)"
                            elif copied_json_count == num_expected_parts and copied_json_count > 0:
                                json_status_for_original_file = f"{copied_json_count}個の部品JSON出力成功" if is_genuinely_multi_part else "JSON作成成功" # ★ 修正
                            elif copied_json_count > 0: 
                                json_status_for_original_file = f"部品JSON一部出力 ({copied_json_count}/{num_expected_parts})"
                            else: 
                                json_status_for_original_file = "部品JSON出力失敗 (コピーエラー等)" if num_expected_parts > 0 else "JSON作成対象なし"
                        else:
                             self.log_manager.warning(f"部品結果一時フォルダが見つからないかディレクトリではありません。JSONをコピーできません: {parts_results_temp_dir}", context="WORKER_PART_IO_FINAL")
                             json_status_for_original_file = "JSON出力エラー (一時フォルダなし)"
                    else:
                        json_status_for_original_file = "作成しない(設定)"
                    
                    # PDFステータスの設定ロジックは変更なし（ユーザーから問題ないと報告があったため）
                    should_create_pdf_globally = self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]
                    if should_create_pdf_globally:
                        merge_pdfs_enabled = self.current_api_options_values.get("merge_split_pdf_parts", True)
                        if is_genuinely_multi_part and part_pdf_paths_agg: # 実際に複数部品があり、PDF部品リストが存在する
                            if merge_pdfs_enabled: 
                                self.original_file_status_update.emit(original_file_path, OCR_STATUS_MERGING)
                                final_merged_pdf_dir = os.path.join(original_file_parent_dir, results_folder_name); merged_pdf_filename = f"{base_name_for_output_prefix}.pdf"
                                final_merged_pdf_path_unique = self._get_unique_filepath(final_merged_pdf_dir, merged_pdf_filename)
                                merged_path_result, merge_error = self._merge_searchable_pdfs(part_pdf_paths_agg, final_merged_pdf_path_unique)
                                if merged_path_result and not merge_error: pdf_final_path_for_signal = merged_path_result # これはUIのPDFステータスに直接影響しない
                                else: pdf_error_for_signal = merge_error if merge_error else {"message": "PDF結合中に不明なエラー", "code": "MERGE_UNKNOWN_ERROR"}
                            else: # 分割PDFをマージせず個別コピー
                                final_pdf_output_dir = os.path.join(original_file_parent_dir, results_folder_name); os.makedirs(final_pdf_output_dir, exist_ok=True)
                                copied_pdf_count = 0; expected_pdf_parts = len(part_pdf_paths_agg)
                                for src_pdf_part_path in part_pdf_paths_agg:
                                    if os.path.exists(src_pdf_part_path):
                                        pdf_part_filename = os.path.basename(src_pdf_part_path); dest_pdf_part_path = self._get_unique_filepath(final_pdf_output_dir, pdf_part_filename)
                                        try: shutil.copy2(src_pdf_part_path, dest_pdf_part_path); copied_pdf_count +=1
                                        except Exception as e_copy_pdf: self.log_manager.error(f"分割PDF部品 '{src_pdf_part_path}' の最終保存先へのコピー失敗: {e_copy_pdf}", context="WORKER_PART_IO_FINAL_ERROR", exc_info=True)
                                if expected_pdf_parts == 0 and copied_pdf_count == 0: pdf_error_for_signal = {"message": "対象のPDF部品なし (コピー対象0)", "code": "NO_PARTS_TO_COPY"}
                                elif copied_pdf_count == expected_pdf_parts and expected_pdf_parts > 0 : pdf_error_for_signal = {"message": f"{copied_pdf_count}個の部品PDF出力成功", "code": "PARTS_COPIED_SUCCESS"}
                                elif copied_pdf_count > 0: pdf_error_for_signal = {"message": f"部品PDF一部出力 ({copied_pdf_count}/{expected_pdf_parts})", "code": "PARTS_COPIED_PARTIAL"}
                                else: pdf_error_for_signal = {"message": "部品PDF出力失敗 (コピーエラー)", "code": "PARTS_COPY_ERROR"}
                        elif not is_genuinely_multi_part and part_pdf_paths_agg: # 単一部品でPDF部品リストが存在する
                             # 単一部品の場合、その部品PDFが最終成果物。parts_results_temp_dir から final_pdf_output_dir へコピー。
                            final_pdf_output_dir = os.path.join(original_file_parent_dir, results_folder_name); os.makedirs(final_pdf_output_dir, exist_ok=True)
                            src_pdf_part_path = part_pdf_paths_agg[0]
                            if os.path.exists(src_pdf_part_path):
                                final_pdf_filename = f"{base_name_for_output_prefix}.pdf" # 元のファイル名に戻す
                                dest_pdf_path = self._get_unique_filepath(final_pdf_output_dir, final_pdf_filename)
                                try:
                                    shutil.copy2(src_pdf_part_path, dest_pdf_path)
                                    pdf_final_path_for_signal = dest_pdf_path # これがUIに「PDF作成成功」と表示される根拠
                                except Exception as e_copy_single_pdf:
                                    self.log_manager.error(f"単一PDF部品 '{src_pdf_part_path}' の最終保存先へのコピー失敗: {e_copy_single_pdf}", context="WORKER_PART_IO_FINAL_ERROR", exc_info=True)
                                    pdf_error_for_signal = {"message": "単一PDFのコピー失敗", "code": "SINGLE_PDF_COPY_ERROR"}
                            else:
                                pdf_error_for_signal = {"message": "単一PDF部品が見つかりません", "code": "SINGLE_PDF_PART_MISSING"}
                        elif not part_pdf_paths_agg and should_create_pdf_globally : 
                            pdf_error_for_signal = {"message": "PDF部品が見つかりません (作成対象)", "code": "PDF_PART_MISSING"}
                    else: 
                        pdf_error_for_signal = {"message": "作成しない(設定)", "code": "PDF_NOT_REQUESTED"}
                else: 
                    if not final_ocr_error_for_main and not self.user_stopped and not self.encountered_fatal_error: final_ocr_error_for_main = {"message": f"'{original_file_basename}' の部品処理中にエラー発生", "code": "PART_PROCESSING_ERROR"}
                    elif self.user_stopped and not final_ocr_error_for_main: final_ocr_error_for_main = {"message": "処理がユーザーにより中止されました", "code": "USER_INTERRUPT"}
                    json_status_for_original_file = "エラー" if not self.user_stopped and not self.encountered_fatal_error else ("中断" if self.user_stopped else "エラー(致命的)")
                    if not (self.file_actions_config.get("output_format", "both") in ["json_only", "both"]): json_status_for_original_file = "作成しない(設定)"
                    if not pdf_error_for_signal and self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                        if self.user_stopped: pdf_error_for_signal = {"message": "処理中止によりPDF作成不可", "code": "USER_INTERRUPT_PDF"}
                        elif self.encountered_fatal_error: pdf_error_for_signal = {"message": "致命的エラーによりPDF作成不可", "code": "FATAL_ERROR_STOP_PDF"}
                        else: pdf_error_for_signal = {"message": f"'{original_file_basename}' の処理エラー等によりPDF作成不可", "code": "PDF_CREATION_FAIL_DUE_TO_OCR_ERROR"}
                
                self.file_processed.emit(original_file_global_idx, original_file_path, final_ocr_result_for_main, final_ocr_error_for_main, json_status_for_original_file)
                self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, pdf_final_path_for_signal, pdf_error_for_signal)

                move_original_file_succeeded_final = all_parts_processed_successfully
                if self.file_actions_config.get("output_format", "both") in ["json_only", "both"]:
                     if not (("成功" in json_status_for_original_file or "作成しない" in json_status_for_original_file) and "エラー" not in json_status_for_original_file and "中断" not in json_status_for_original_file):
                          move_original_file_succeeded_final = False
                if self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                    if pdf_error_for_signal and not (pdf_error_for_signal.get("code") and ("SUCCESS" in pdf_error_for_signal.get("code").upper() or "PARTS_COPIED_SUCCESS" == pdf_error_for_signal.get("code").upper() )): # PARTS_COPIED_SUCCESSも成功とみなす
                        move_original_file_succeeded_final = False
                    elif not pdf_final_path_for_signal and not (pdf_error_for_signal and ("作成しない" in pdf_error_for_signal.get("message", "") or "対象外" in pdf_error_for_signal.get("message", ""))):
                        move_original_file_succeeded_final = False
                if self.user_stopped or self.encountered_fatal_error:
                    move_original_file_succeeded_final = False

                current_source_file_to_move = original_file_path 
                if os.path.exists(current_source_file_to_move): 
                    destination_subfolder_for_move: Optional[str] = None
                    success_folder_name_cfg = self.file_actions_config.get("success_folder_name", "OCR成功")
                    failure_folder_name_cfg = self.file_actions_config.get("failure_folder_name", "OCR失敗")
                    move_on_success_enabled_cfg = self.file_actions_config.get("move_on_success_enabled", False)
                    move_on_failure_enabled_cfg = self.file_actions_config.get("move_on_failure_enabled", False)
                    collision_action_cfg = self.file_actions_config.get("collision_action", "rename")

                    if move_original_file_succeeded_final and move_on_success_enabled_cfg:
                        destination_subfolder_for_move = success_folder_name_cfg
                    elif not move_original_file_succeeded_final and move_on_failure_enabled_cfg:
                        destination_subfolder_for_move = failure_folder_name_cfg
                    
                    if destination_subfolder_for_move and (self.is_running or not self.encountered_fatal_error): 
                        self._move_file_with_collision_handling(current_source_file_to_move, original_file_parent_dir, destination_subfolder_for_move, collision_action_cfg)
                    elif destination_subfolder_for_move: 
                         self.log_manager.info(f"'{original_file_basename}' のファイル移動は処理中断/停止のためスキップされました。", context="WORKER_FILE_MOVE")

                self._try_cleanup_specific_temp_dirs(current_file_parts_source_dir, parts_results_temp_dir) # parts_results_temp_dirは常に一時的なものとして扱う
                time.sleep(0.01) 
        finally:
            self._cleanup_main_temp_dir()
            self.all_files_processed.emit() 
            final_log_message = "OcrWorkerの処理が完了しました。" # デフォルトメッセージ
            if self.user_stopped: final_log_message = "OcrWorkerの処理がユーザーにより停止されました。"
            elif self.encountered_fatal_error: final_log_message = f"OcrWorkerの処理が致命的なエラー ({self.fatal_error_info.get('code') if self.fatal_error_info else 'N/A'}) により停止しました。"
            elif not self.is_running: final_log_message = "OcrWorkerの処理が中断されました (is_runningがFalse)。"
            self.log_manager.info(final_log_message, context="WORKER_LIFECYCLE")
            self.log_manager.debug(f"OcrWorkerスレッドが終了しました。", context="WORKER_LIFECYCLE", thread_id=thread_id)

    def stop(self):
        if not self.is_running and self.user_stopped :
            self.log_manager.info("OcrWorker停止リクエストを受けましたが、既に停止処理中または停止済みです。", context="WORKER_LIFECYCLE_STOP")
            return
        self.log_manager.info("OcrWorker停止リクエスト受信 (オーケストレータ/ユーザーから)。", context="WORKER_LIFECYCLE_STOP")
        self.is_running = False
        self.user_stopped = True 

    def _move_file_with_collision_handling(self, source_path: str, root_dest_dir: str, subfolder_name: str, collision_action: str):
        source_filename = os.path.basename(source_path)
        destination_folder = os.path.join(root_dest_dir, subfolder_name)
        try:
            os.makedirs(destination_folder, exist_ok=True)
        except OSError as e:
            self.log_manager.error(f"移動先フォルダ '{destination_folder}' の作成失敗: {e}", context="WORKER_FILE_MOVE_ERROR", exc_info=True)
            return
        destination_path = os.path.join(destination_folder, source_filename)
        if os.path.exists(destination_path):
            if collision_action == "overwrite":
                self.log_manager.info(f"'{destination_path}' の既存ファイルを '{source_path}' で上書きします。", context="WORKER_FILE_MOVE")
                try: os.remove(destination_path)
                except OSError as e_remove:
                    self.log_manager.error(f"上書きのための既存ファイル '{destination_path}' の削除失敗: {e_remove}", context="WORKER_FILE_MOVE_ERROR", exc_info=True)
                    return
            elif collision_action == "rename":
                destination_path = self._get_unique_filepath(destination_folder, source_filename)
                self.log_manager.info(f"'{destination_folder}' での衝突のため、新しいファイルを '{os.path.basename(destination_path)}' にリネームします。", context="WORKER_FILE_MOVE")
            elif collision_action == "skip":
                self.log_manager.info(f"既存ファイルがあり 'skip' ポリシーのため、'{source_path}' から '{destination_folder}' への移動をスキップします。", context="WORKER_FILE_MOVE")
                return
            else: 
                destination_path = self._get_unique_filepath(destination_folder, source_filename)
                self.log_manager.warning(f"不明な衝突処理アクション '{collision_action}'。デフォルトのリネーム処理を行います: '{os.path.basename(destination_path)}'。", context="WORKER_FILE_MOVE")
        try:
            shutil.move(source_path, destination_path)
            self.log_manager.info(f"'{source_path}' から '{destination_path}' へ正常に移動しました。", context="WORKER_FILE_MOVE")
        except Exception as e:
            self.log_manager.error(f"'{source_path}' から '{destination_path}' への移動失敗。エラー: {e}", context="WORKER_FILE_MOVE_ERROR", exc_info=True)

    def _try_cleanup_specific_temp_dirs(self, source_parts_dir: Optional[str], results_parts_dir: Optional[str]): # 変数名を明確化
        if source_parts_dir and os.path.isdir(source_parts_dir) and \
           self.main_temp_dir_for_splits and self.main_temp_dir_for_splits in source_parts_dir : 
            try:
                shutil.rmtree(source_parts_dir)
                self.log_manager.debug(f"一時ソース部品ディレクトリをクリーンアップしました: {source_parts_dir}", context="WORKER_TEMP_CLEANUP")
            except Exception as e:
                self.log_manager.warning(f"一時ソース部品ディレクトリのクリーンアップ失敗: {source_parts_dir}, Error: {e}", context="WORKER_TEMP_CLEANUP_ERROR", exc_info=True)
        
        if results_parts_dir and os.path.isdir(results_parts_dir) and \
           self.main_temp_dir_for_splits and self.main_temp_dir_for_splits in results_parts_dir: 
            try:
                shutil.rmtree(results_parts_dir)
                self.log_manager.debug(f"一時結果部品ディレクトリをクリーンアップしました: {results_parts_dir}", context="WORKER_TEMP_CLEANUP")
            except Exception as e:
                self.log_manager.warning(f"一時結果部品ディレクトリのクリーンアップ失敗: {results_parts_dir}, Error: {e}", context="WORKER_TEMP_CLEANUP_ERROR", exc_info=True)