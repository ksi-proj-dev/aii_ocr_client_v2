# ocr_worker.py

import os
import json
import datetime
import time
import shutil
import threading
import io
import tempfile

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from PyQt6.QtCore import QThread, pyqtSignal

# ローカルモジュールからのインポート
from app_constants import (
    OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING,
    OCR_STATUS_MERGING
)
# api_client と log_manager はコンストラクタでインスタンスを受け取るので、
# 型ヒントのためだけにインポートするなら以下のように記述できるが、必須ではない。
# from api_client import CubeApiClient (type hinting)
# from log_manager import LogManager (type hinting)

class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object, object) # original_idx, path, ocr_result, ocr_error, json_status
    searchable_pdf_processed = pyqtSignal(int, str, object, object) # original_idx, path, pdf_final_path, pdf_error_info
    all_files_processed = pyqtSignal()
    original_file_status_update = pyqtSignal(str, str)

    def __init__(self, api_client, files_to_process_tuples, input_root_folder, log_manager, config):
        super().__init__()
        self.api_client = api_client
        self.files_to_process_tuples = files_to_process_tuples
        self.is_running = True
        self.user_stopped = False
        self.input_root_folder = input_root_folder
        self.log_manager = log_manager
        self.config = config
        self.current_api_options = self.config.get("options", {}).get(self.config.get("api_type"), {})
        self.file_actions_config = self.config.get("file_actions", {})
        self.main_temp_dir_for_splits = None
        self.log_manager.debug("OcrWorker initialized.", context="WORKER_LIFECYCLE", num_original_files=len(self.files_to_process_tuples))

    def _get_unique_filepath(self, target_dir, filename):
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath):
            new_filename = f"{base} ({counter}){ext}"
            new_filepath = os.path.join(target_dir, new_filename)
            counter += 1
        return new_filepath

    def _ensure_main_temp_dir_exists(self):
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

    def _get_part_filename(self, original_basename, part_num, total_parts_estimate, original_ext):
        base = os.path.splitext(original_basename)[0]
        num_digits = len(str(total_parts_estimate)) if total_parts_estimate > 0 else 2
        if num_digits < 2: num_digits = 2
        if total_parts_estimate >= 1000: num_digits = 4
        elif total_parts_estimate >= 100: num_digits = 3
        return f"{base}.split#{str(part_num).zfill(num_digits)}{original_ext}"

    def _split_pdf_by_size(self, original_filepath, chunk_size_bytes, temp_dir_for_parts):
        split_files = []
        original_basename = os.path.basename(original_filepath)
        original_ext = os.path.splitext(original_basename)[1]
        part_counter = 1
        
        try:
            reader = PdfReader(original_filepath)
            total_pages = len(reader.pages)
            if total_pages == 0:
                self.log_manager.warning(f"PDF '{original_basename}' has 0 pages. Cannot split.", context="WORKER_PDF_SPLIT")
                return []

            original_size_bytes = os.path.getsize(original_filepath)
            if total_pages == 1 or original_size_bytes <= chunk_size_bytes:
                self.log_manager.info(f"PDF '{original_basename}' is small or single page. Treating as single part initially.", context="WORKER_PDF_SPLIT")
                return [] 
            
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
                        with open(part_filepath, "wb") as f_out:
                            current_writer.write(f_out)
                        split_files.append(part_filepath)
                        self.log_manager.info(f"PDF part saved: {part_filepath} ({len(current_writer.pages)} pages, size: {current_writer_size} bytes)", context="WORKER_PDF_SPLIT")
                        part_counter += 1
                        current_writer = PdfWriter()

                current_writer.add_page(reader.pages[i])
            
            if len(current_writer.pages) > 0 and self.is_running:
                part_filename = self._get_part_filename(original_basename, part_counter, estimated_total_parts, original_ext)
                part_filepath = os.path.join(temp_dir_for_parts, part_filename)
                with open(part_filepath, "wb") as f_out:
                    current_writer.write(f_out)
                split_files.append(part_filepath)
                self.log_manager.info(f"Final PDF part saved: {part_filepath} ({len(current_writer.pages)} pages)", context="WORKER_PDF_SPLIT")

            if not self.is_running:
                self.log_manager.info("PDF splitting interrupted.", context="WORKER_PDF_SPLIT")
                return []

        except Exception as e:
            self.log_manager.error(f"Error splitting PDF '{original_basename}': {e}", context="WORKER_PDF_SPLIT_ERROR", exc_info=True)
            return []
        
        return split_files

    def _split_file(self, original_filepath, chunk_size_mb, temp_dir_for_parts):
        _, ext = os.path.splitext(original_filepath)
        original_basename = os.path.basename(original_filepath)
        ext_lower = ext.lower()
        chunk_size_bytes = chunk_size_mb * 1024 * 1024
        split_part_paths = []

        if ext_lower == ".pdf":
            split_part_paths = self._split_pdf_by_size(original_filepath, chunk_size_bytes, temp_dir_for_parts)
        else: 
            self.log_manager.info(f"File type {ext_lower} not split by size. Treating as single part: {original_basename}", context="WORKER_FILE_SPLIT")
        
        if not split_part_paths:
            try:
                single_part_filename = self._get_part_filename(original_basename, 1, 1, ext)
                single_part_filepath = os.path.join(temp_dir_for_parts, single_part_filename)
                shutil.copy2(original_filepath, single_part_filepath)
                split_part_paths.append(single_part_filepath)
                self.log_manager.info(f"Original file '{original_basename}' treated as a single part: {single_part_filepath}", context="WORKER_FILE_SPLIT")
            except Exception as e:
                self.log_manager.error(f"Error copying file '{original_basename}' as single part: {e}", context="WORKER_FILE_SPLIT_ERROR", exc_info=True)
                return []
        return split_part_paths

    def _merge_searchable_pdfs(self, pdf_part_paths, final_merged_pdf_path):
        if not pdf_part_paths:
            self.log_manager.warning("No PDF parts provided for merging.", context="WORKER_PDF_MERGE")
            return None, {"message": "結合対象のPDF部品がありません。"}

        merger = PdfMerger()
        try:
            for part_path in pdf_part_paths:
                if os.path.exists(part_path):
                    merger.append(part_path)
                else:
                    self.log_manager.error(f"PDF part not found for merging: {part_path}", context="WORKER_PDF_MERGE_ERROR")
                    try: merger.close() 
                    except: pass
                    return None, {"message": f"結合用PDF部品が見つかりません: {os.path.basename(part_path)}"}
            
            final_dir = os.path.dirname(final_merged_pdf_path)
            os.makedirs(final_dir, exist_ok=True)
            
            merger.write(final_merged_pdf_path)
            merger.close()
            self.log_manager.info(f"Searchable PDF parts successfully merged into: {final_merged_pdf_path}", context="WORKER_PDF_MERGE")
            return final_merged_pdf_path, None 
        except Exception as e:
            self.log_manager.error(f"Error merging PDF parts into {final_merged_pdf_path}: {e}", context="WORKER_PDF_MERGE_ERROR", exc_info=True)
            try: merger.close()
            except: pass
            if os.path.exists(final_merged_pdf_path):
                try: os.remove(final_merged_pdf_path)
                except: pass
            return None, {"message": f"PDF結合エラー: {str(e)}"}


    def run(self):
        thread_id = threading.get_ident()
        self.log_manager.debug(f"OcrWorker thread started.", context="WORKER_LIFECYCLE", thread_id=thread_id, num_original_files=len(self.files_to_process_tuples))
        
        if not self._ensure_main_temp_dir_exists():
            self.log_manager.critical("Failed to create main temporary directory. Worker cannot proceed.", context="WORKER_LIFECYCLE")
            self.all_files_processed.emit()
            return

        results_folder_name = self.file_actions_config.get("results_folder_name", "OCR結果")
        
        for worker_internal_idx, (original_file_path, original_file_global_idx) in enumerate(self.files_to_process_tuples):
            if not self.is_running:
                self.log_manager.info("OcrWorker run loop aborted by stop signal (outer loop).", context="WORKER_LIFECYCLE")
                break
            
            self.original_file_status_update.emit(original_file_path, f"{OCR_STATUS_PROCESSING} (準備中)")

            original_file_basename = os.path.basename(original_file_path)
            original_file_parent_dir = os.path.dirname(original_file_path)
            base_name_for_output_prefix = os.path.splitext(original_file_basename)[0]
            
            self.log_manager.info(f"Starting processing for original file: '{original_file_basename}' (Global index: {original_file_global_idx})", context="WORKER_ORIGINAL_FILE")

            files_to_ocr_for_this_original = []
            temp_dir_for_this_file_source_parts = None 
            parts_results_temp_dir = None     
            was_split = False

            split_enabled = self.current_api_options.get("split_large_files_enabled", False)
            split_chunk_size_mb = self.current_api_options.get("split_chunk_size_mb", 10)
            
            try:
                original_file_size_bytes = os.path.getsize(original_file_path)
            except OSError as e:
                self.log_manager.error(f"Cannot get size of '{original_file_basename}', skipping: {e}", context="WORKER_ORIGINAL_FILE_ERROR")
                self.file_processed.emit(original_file_global_idx, original_file_path, None, {"message": "ファイルサイズ取得エラー"}, "エラー")
                self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, {"message": "ファイルサイズ取得エラー"})
                continue

            if split_enabled and original_file_size_bytes > (split_chunk_size_mb * 1024 * 1024):
                self.original_file_status_update.emit(original_file_path, OCR_STATUS_SPLITTING)
                self.log_manager.info(f"File '{original_file_basename}' needs splitting. Size: {original_file_size_bytes / (1024*1024):.2f}MB, Chunk: {split_chunk_size_mb}MB", context="WORKER_FILE_SPLIT")
                
                temp_dir_for_this_file_source_parts = os.path.join(self.main_temp_dir_for_splits, base_name_for_output_prefix + "_source_parts")
                parts_results_temp_dir = os.path.join(self.main_temp_dir_for_splits, base_name_for_output_prefix + "_results_parts")
                try:
                    os.makedirs(temp_dir_for_this_file_source_parts, exist_ok=True)
                    os.makedirs(parts_results_temp_dir, exist_ok=True)
                except Exception as e_mkdir:
                    self.log_manager.error(f"Failed to create temp subdirs for '{original_file_basename}': {e_mkdir}", context="WORKER_FILE_SPLIT_ERROR", exc_info=True)
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, {"message": "分割用一時フォルダ作成失敗"}, "エラー")
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, {"message": "分割用一時フォルダ作成失敗"})
                    continue

                files_to_ocr_for_this_original = self._split_file(original_file_path, split_chunk_size_mb, temp_dir_for_this_file_source_parts)
                
                if not files_to_ocr_for_this_original:
                    self.log_manager.error(f"Splitting failed for '{original_file_basename}'.", context="WORKER_FILE_SPLIT_ERROR")
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, {"message": "ファイル分割失敗"}, "エラー")
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, {"message": "ファイル分割失敗"})
                    if temp_dir_for_this_file_source_parts and os.path.isdir(temp_dir_for_this_file_source_parts):
                        try: shutil.rmtree(temp_dir_for_this_file_source_parts)
                        except: pass
                    if parts_results_temp_dir and os.path.isdir(parts_results_temp_dir):
                        try: shutil.rmtree(parts_results_temp_dir)
                        except: pass
                    continue
                was_split = True
                self.log_manager.info(f"File '{original_file_basename}' split into {len(files_to_ocr_for_this_original)} parts.", context="WORKER_FILE_SPLIT")
            else: 
                files_to_ocr_for_this_original = [original_file_path]
                parts_results_temp_dir = os.path.join(original_file_parent_dir, results_folder_name)
                try:
                    os.makedirs(parts_results_temp_dir, exist_ok=True)
                except Exception as e_mkdir_nonsplit:
                    self.log_manager.error(f"Failed to create results directory for non-split file '{original_file_basename}': {e_mkdir_nonsplit}", context="WORKER_IO_ERROR")
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, {"message": "結果フォルダ作成失敗"}, "エラー")
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, {"message": "結果フォルダ作成失敗"})
                    continue

            part_ocr_results_agg = [] 
            part_pdf_paths_agg = []   
            all_parts_processed_successfully = True
            final_ocr_result_for_main = None
            final_ocr_error_for_main = None
            json_status_for_original_file = "作成しない(設定)" 
            pdf_final_path_for_signal = None
            pdf_error_for_signal = None

            for part_idx, current_processing_path in enumerate(files_to_ocr_for_this_original):
                if not self.is_running:
                    all_parts_processed_successfully = False
                    self.log_manager.info(f"Processing of parts for '{original_file_basename}' interrupted by stop signal.", context="WORKER_PART_PROCESS")
                    break 
                
                current_part_basename = os.path.basename(current_processing_path) 
                status_msg_for_ui = f"{OCR_STATUS_PART_PROCESSING} ({part_idx + 1}/{len(files_to_ocr_for_this_original)})"
                if not was_split: status_msg_for_ui = OCR_STATUS_PROCESSING
                self.original_file_status_update.emit(original_file_path, status_msg_for_ui)
                self.log_manager.info(f"  Processing part: '{current_part_basename}' for original '{original_file_basename}'", context="WORKER_PART_PROCESS")

                part_ocr_result_json, part_ocr_error_info = self.api_client.read_document(current_processing_path)

                if part_ocr_error_info:
                    self.log_manager.error(f"  OCR failed for part '{current_part_basename}'. Error: {part_ocr_error_info.get('message')}", context="WORKER_PART_OCR_ERROR")
                    all_parts_processed_successfully = False
                    final_ocr_error_for_main = part_ocr_error_info
                    break 

                part_ocr_results_agg.append({"path": current_processing_path, "result": part_ocr_result_json})
                
                should_create_json_output_for_part = self.file_actions_config.get("output_format", "both") in ["json_only", "both"]
                if should_create_json_output_for_part:
                    part_json_filename = os.path.splitext(current_part_basename)[0] + ".json" 
                    target_json_save_dir_for_part = parts_results_temp_dir
                    
                    part_json_filepath = os.path.join(target_json_save_dir_for_part, part_json_filename)
                    try:
                        with open(part_json_filepath, 'w', encoding='utf-8') as f_json:
                            json.dump(part_ocr_result_json, f_json, ensure_ascii=False, indent=2)
                        self.log_manager.info(f"  JSON for part saved: '{part_json_filepath}'", context="WORKER_PART_IO")
                    except Exception as e_json_save:
                        self.log_manager.error(f"  Failed to save JSON for part '{current_part_basename}': {e_json_save}", context="WORKER_PART_IO_ERROR")
                
                should_create_pdf_output_for_part = self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]
                if should_create_pdf_output_for_part:
                    self.log_manager.info(f"  Creating searchable PDF for part: '{current_part_basename}'", context="WORKER_PART_PDF")
                    part_pdf_content, part_pdf_error_info = self.api_client.make_searchable_pdf(current_processing_path)

                    if part_pdf_error_info:
                        self.log_manager.error(f"  Searchable PDF creation failed for part '{current_part_basename}'. Error: {part_pdf_error_info.get('message')}", context="WORKER_PART_PDF_ERROR")
                        all_parts_processed_successfully = False
                        pdf_error_for_signal = part_pdf_error_info
                        break
                    elif part_pdf_content:
                        part_pdf_filename = current_part_basename 
                        target_pdf_save_dir_for_part = parts_results_temp_dir
                        part_pdf_filepath = os.path.join(target_pdf_save_dir_for_part, part_pdf_filename)
                        try:
                            with open(part_pdf_filepath, 'wb') as f_pdf:
                                f_pdf.write(part_pdf_content)
                            self.log_manager.info(f"  Searchable PDF for part saved: '{part_pdf_filepath}'", context="WORKER_PART_IO")
                            part_pdf_paths_agg.append(part_pdf_filepath)
                        except Exception as e_pdf_save:
                            self.log_manager.error(f"  Failed to save searchable PDF for part '{current_part_basename}': {e_pdf_save}", context="WORKER_PART_IO_ERROR")
                            all_parts_processed_successfully = False
                            pdf_error_for_signal = {"message": f"部品PDF保存エラー: {e_pdf_save}"}
                            break
            
            if not self.is_running and not all_parts_processed_successfully:
                 self.log_manager.info(f"Processing for '{original_file_basename}' stopped by user.", context="WORKER_LIFECYCLE")
                 if not final_ocr_error_for_main: final_ocr_error_for_main = {"message": "処理がユーザーにより中止されました"}
            elif not self.is_running and all_parts_processed_successfully:
                 self.log_manager.warning(f"Processing for '{original_file_basename}' marked successful but run was stopped.", context="WORKER_LIFECYCLE_UNEXPECTED")

            if all_parts_processed_successfully:
                self.log_manager.info(f"All parts of '{original_file_basename}' processed successfully for OCR and intermediate file saving.", context="WORKER_ORIGINAL_FILE")
                
                if was_split:
                    final_ocr_result_for_main = {"status": "parts_processed_ok", "num_parts": len(files_to_ocr_for_this_original), "detail": f"{len(files_to_ocr_for_this_original)}部品のOCR完了"}
                elif part_ocr_results_agg:
                    final_ocr_result_for_main = part_ocr_results_agg[0]["result"]
                else: 
                    final_ocr_result_for_main = {"status": "ocr_done_no_parts_data_unexpected", "message": "OCR成功(データ無)"}

                should_create_json_globally = self.file_actions_config.get("output_format", "both") in ["json_only", "both"]
                if should_create_json_globally:
                    if was_split:
                        final_json_output_dir = os.path.join(original_file_parent_dir, results_folder_name)
                        os.makedirs(final_json_output_dir, exist_ok=True)
                        
                        copied_json_count = 0
                        total_json_parts_expected = len(files_to_ocr_for_this_original)
                        original_base_name_no_ext = os.path.splitext(original_file_basename)[0]

                        if parts_results_temp_dir and os.path.isdir(parts_results_temp_dir):
                            for item_name in os.listdir(parts_results_temp_dir):
                                if item_name.startswith(original_base_name_no_ext) and \
                                   item_name.endswith(".json") and \
                                   ".split#" in item_name:
                                    
                                    src_json_path = os.path.join(parts_results_temp_dir, item_name)
                                    dest_json_path = self._get_unique_filepath(final_json_output_dir, item_name)
                                    try:
                                        shutil.copy2(src_json_path, dest_json_path)
                                        self.log_manager.info(f"Copied split JSON part to final destination: {dest_json_path}", context="WORKER_PART_IO")
                                        copied_json_count += 1
                                    except Exception as e_copy:
                                        self.log_manager.error(f"Failed to copy split JSON part '{src_json_path}' to final destination: {e_copy}", context="WORKER_PART_IO_ERROR")
                            
                            if total_json_parts_expected == 0 and copied_json_count == 0:
                                json_status_for_original_file = "部品JSONなし (対象部品0)"
                            elif copied_json_count == total_json_parts_expected and total_json_parts_expected > 0:
                                json_status_for_original_file = f"{copied_json_count}個の部品JSON出力成功"
                            elif copied_json_count > 0:
                                json_status_for_original_file = f"部品JSON一部出力 ({copied_json_count}/{total_json_parts_expected})"
                            else: 
                                json_status_for_original_file = "部品JSON出力失敗 (コピーエラー)"
                        else:
                             self.log_manager.warning(f"Parts results temp dir not found or not a dir, cannot copy split JSONs: {parts_results_temp_dir}", context="WORKER_PART_IO")
                             json_status_for_original_file = "部品JSON出力エラー (一時フォルダなし)"
                    else: 
                        json_status_for_original_file = "JSON作成成功"
                else: 
                    json_status_for_original_file = "作成しない(設定)"
                
                should_create_pdf_globally = self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]
                if should_create_pdf_globally:
                    if was_split and part_pdf_paths_agg:
                        merge_pdfs_enabled = self.current_api_options.get("merge_split_pdf_parts", True)
                        if merge_pdfs_enabled: 
                            self.original_file_status_update.emit(original_file_path, OCR_STATUS_MERGING)
                            final_merged_pdf_dir = os.path.join(original_file_parent_dir, results_folder_name)
                            merged_pdf_filename = f"{base_name_for_output_prefix}.pdf"
                            final_merged_pdf_path_unique = self._get_unique_filepath(final_merged_pdf_dir, merged_pdf_filename)
                            
                            merged_path_result, merge_error = self._merge_searchable_pdfs(part_pdf_paths_agg, final_merged_pdf_path_unique)
                            if merged_path_result and not merge_error:
                                pdf_final_path_for_signal = merged_path_result
                            else:
                                pdf_error_for_signal = merge_error if merge_error else {"message": "PDF結合中に不明なエラー"}
                        else: 
                            self.log_manager.info(f"PDF merging disabled by config. {len(part_pdf_paths_agg)} PDF parts will be copied individually.", context="WORKER_PDF_PARTS_COPY")
                            final_pdf_output_dir = os.path.join(original_file_parent_dir, results_folder_name)
                            os.makedirs(final_pdf_output_dir, exist_ok=True)
                            
                            copied_pdf_count = 0
                            expected_pdf_parts = len(part_pdf_paths_agg)

                            for src_pdf_part_path in part_pdf_paths_agg:
                                if os.path.exists(src_pdf_part_path):
                                    pdf_part_filename = os.path.basename(src_pdf_part_path)
                                    dest_pdf_part_path = self._get_unique_filepath(final_pdf_output_dir, pdf_part_filename)
                                    try:
                                        shutil.copy2(src_pdf_part_path, dest_pdf_part_path)
                                        self.log_manager.info(f"Copied split PDF part to final destination: {dest_pdf_part_path}", context="WORKER_PART_IO")
                                        copied_pdf_count +=1
                                    except Exception as e_copy_pdf:
                                        self.log_manager.error(f"Failed to copy split PDF part '{src_pdf_part_path}' to final destination: {e_copy_pdf}", context="WORKER_PART_IO_ERROR")
                                else:
                                    self.log_manager.warning(f"PDF part path not found, cannot copy: {src_pdf_part_path}", context="WORKER_PART_IO")
                            
                            if expected_pdf_parts == 0 and copied_pdf_count == 0:
                                pdf_error_for_signal = {"message": "対象のPDF部品なし (コピー対象0)", "code": "NO_PARTS_TO_COPY"}
                            elif copied_pdf_count == expected_pdf_parts and expected_pdf_parts > 0 :
                                pdf_error_for_signal = {"message": f"{copied_pdf_count}個の部品PDF出力成功", "code": "PARTS_COPIED_SUCCESS"}
                            elif copied_pdf_count > 0:
                                pdf_error_for_signal = {"message": f"部品PDF一部出力 ({copied_pdf_count}/{expected_pdf_parts})", "code": "PARTS_COPIED_PARTIAL"}
                            else: 
                                pdf_error_for_signal = {"message": "部品PDF出力失敗 (コピーエラー)", "code": "PARTS_COPY_ERROR"}
                    elif not was_split and part_pdf_paths_agg:
                        pdf_final_path_for_signal = part_pdf_paths_agg[0]
                    elif not part_pdf_paths_agg and should_create_pdf_globally:
                        pdf_error_for_signal = {"message": "PDF部品が見つかりません (作成対象)"}
            
            else: 
                if not final_ocr_error_for_main and not self.user_stopped : 
                    final_ocr_error_for_main = {"message": f"'{original_file_basename}' の部品処理中にエラー発生"}
                elif self.user_stopped and not final_ocr_error_for_main:
                    final_ocr_error_for_main = {"message": "処理がユーザーにより中止されました"}

                if self.file_actions_config.get("output_format", "both") in ["json_only", "both"]:
                    json_status_for_original_file = "エラー" if not self.user_stopped else "中断"
                else:
                    json_status_for_original_file = "作成しない(設定)" 
                
                if not pdf_error_for_signal and self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                    if self.user_stopped:
                         pdf_error_for_signal = {"message": "処理中止によりPDF作成不可"}
                    else:
                         pdf_error_for_signal = {"message": f"'{original_file_basename}' の処理エラー等によりPDF作成不可"}
            
            self.file_processed.emit(original_file_global_idx, original_file_path, final_ocr_result_for_main, final_ocr_error_for_main, json_status_for_original_file)
            self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, pdf_final_path_for_signal, pdf_error_for_signal)

            move_original_file_succeeded_final = all_parts_processed_successfully
            
            if self.file_actions_config.get("output_format", "both") in ["json_only", "both"]:
                 if not ("成功" in json_status_for_original_file or "作成しない" in json_status_for_original_file):
                     move_original_file_succeeded_final = False
            
            if self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                if pdf_error_for_signal:
                    if not (pdf_error_for_signal.get("code") and "SUCCESS" in pdf_error_for_signal.get("code").upper()):
                        move_original_file_succeeded_final = False
                elif not pdf_final_path_for_signal: 
                    move_original_file_succeeded_final = False
            
            if self.user_stopped:
                move_original_file_succeeded_final = False

            current_source_file_to_move = original_file_path 
            if os.path.exists(current_source_file_to_move):
                destination_subfolder_for_move = None
                success_folder_name_cfg = self.file_actions_config.get("success_folder_name", "OCR成功")
                failure_folder_name_cfg = self.file_actions_config.get("failure_folder_name", "OCR失敗")
                move_on_success_enabled_cfg = self.file_actions_config.get("move_on_success_enabled", False)
                move_on_failure_enabled_cfg = self.file_actions_config.get("move_on_failure_enabled", False)
                collision_action_cfg = self.file_actions_config.get("collision_action", "rename")

                if move_original_file_succeeded_final and move_on_success_enabled_cfg:
                    destination_subfolder_for_move = success_folder_name_cfg
                elif not move_original_file_succeeded_final and move_on_failure_enabled_cfg:
                    destination_subfolder_for_move = failure_folder_name_cfg
                
                if destination_subfolder_for_move and self.is_running: 
                    self._move_file_with_collision_handling(current_source_file_to_move, 
                                                            original_file_parent_dir, 
                                                            destination_subfolder_for_move, 
                                                            collision_action_cfg)
                elif destination_subfolder_for_move and not self.is_running and self.user_stopped:
                     self.log_manager.info(f"File moving for '{original_file_basename}' skipped due to process interruption.", context="WORKER_FILE_MOVE")

            if temp_dir_for_this_file_source_parts and os.path.isdir(temp_dir_for_this_file_source_parts) and self.main_temp_dir_for_splits in temp_dir_for_this_file_source_parts:
                try: shutil.rmtree(temp_dir_for_this_file_source_parts)
                except Exception as e: self.log_manager.warning(f"Failed to cleanup source parts temp dir: {temp_dir_for_this_file_source_parts}, Error: {e}", context="WORKER_TEMP_CLEANUP")
            
            if was_split and parts_results_temp_dir and os.path.isdir(parts_results_temp_dir) and self.main_temp_dir_for_splits in parts_results_temp_dir:
                try: shutil.rmtree(parts_results_temp_dir)
                except Exception as e: self.log_manager.warning(f"Failed to cleanup results parts temp dir: {parts_results_temp_dir}, Error: {e}", context="WORKER_TEMP_CLEANUP")
            
            time.sleep(0.01)
        
        self._cleanup_main_temp_dir()
        self.all_files_processed.emit()
        if self.is_running:
             self.log_manager.info("All files processed by OcrWorker.", context="WORKER_LIFECYCLE")
        elif self.user_stopped:
             self.log_manager.info("OcrWorker processing was stopped by user.", context="WORKER_LIFECYCLE")
        else:
             self.log_manager.warning("OcrWorker processing finished, but final state of is_running is unclear.", context="WORKER_LIFECYCLE")

        self.log_manager.debug(f"OcrWorker thread finished.", context="WORKER_LIFECYCLE", thread_id=thread_id)

    def stop(self):
        self.log_manager.info("OcrWorker stop requested.", context="WORKER_LIFECYCLE")
        self.is_running = False
        self.user_stopped = True

    def _move_file_with_collision_handling(self, source_path, root_dest_dir, subfolder_name, collision_action):
        source_filename = os.path.basename(source_path)
        destination_folder = os.path.join(root_dest_dir, subfolder_name)
        os.makedirs(destination_folder, exist_ok=True)
        destination_path = os.path.join(destination_folder, source_filename)

        if os.path.exists(destination_path):
            if collision_action == "overwrite":
                self.log_manager.info(f"Overwriting existing file at '{destination_path}' with '{source_path}'.", context="WORKER_FILE_MOVE")
            elif collision_action == "rename":
                destination_path = self._get_unique_filepath(destination_folder, source_filename)
                self.log_manager.info(f"Renaming new file to '{os.path.basename(destination_path)}' due to collision at '{destination_folder}'.", context="WORKER_FILE_MOVE")
            elif collision_action == "skip":
                self.log_manager.info(f"Skipping move of '{source_path}' to '{destination_folder}' due to existing file and 'skip' policy.", context="WORKER_FILE_MOVE")
                return
            else: 
                destination_path = self._get_unique_filepath(destination_folder, source_filename)
                self.log_manager.warning(f"Unknown collision action '{collision_action}'. Defaulting to rename: '{os.path.basename(destination_path)}'.", context="WORKER_FILE_MOVE")
        
        try:
            shutil.move(source_path, destination_path)
            self.log_manager.info(f"Successfully moved '{source_path}' to '{destination_path}'.", context="WORKER_FILE_MOVE")
        except Exception as e:
            self.log_manager.error(f"Failed to move '{source_path}' to '{destination_path}'. Error: {e}", context="WORKER_FILE_MOVE_ERROR", exc_info=True)