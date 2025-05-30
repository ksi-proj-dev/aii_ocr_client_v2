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

from app_constants import (
    OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING,
    OCR_STATUS_MERGING
)

class OcrWorker(QThread):
    file_processed = pyqtSignal(int, str, object, object, object)
    searchable_pdf_processed = pyqtSignal(int, str, object, object)
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
                msg = f"PDF '{original_basename}' にはページがありません。分割できません。"
                self.log_manager.warning(msg, context="WORKER_PDF_SPLIT")
                return [], {"message": msg, "code": "PDF_ZERO_PAGES"}
            
            original_size_bytes = os.path.getsize(original_filepath)
            if total_pages == 1 or original_size_bytes <= chunk_size_bytes:
                self.log_manager.info(f"PDF '{original_basename}' は小さいか単一ページのため、分割しません。", context="WORKER_PDF_SPLIT")
                return [], None
            
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
                            with open(part_filepath, "wb") as f_out:
                                current_writer.write(f_out)
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
                    with open(part_filepath, "wb") as f_out:
                        current_writer.write(f_out)
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

    def _split_file(self, original_filepath, chunk_size_mb, base_temp_dir_for_parts):
        """ファイルを分割する。PDF以外は単一の部品としてコピーする。"""
        _, ext = os.path.splitext(original_filepath)
        original_basename = os.path.basename(original_filepath)
        ext_lower = ext.lower()
        
        split_part_paths = []
        error_info = None

        # ★★★ 修正点: ファイルごとの一時ディレクトリを作成 ★★★
        file_specific_temp_dir = os.path.join(base_temp_dir_for_parts, os.path.splitext(original_basename)[0] + "_parts")
        try:
            os.makedirs(file_specific_temp_dir, exist_ok=True)
            self.log_manager.debug(f"Created/ensured temp directory for file parts: {file_specific_temp_dir}", context="WORKER_TEMP_MGMT")
        except Exception as e_mkdir:
            msg = f"ファイル '{original_basename}' 用の一時部品フォルダ作成に失敗: {e_mkdir}"
            self.log_manager.error(msg, context="WORKER_FILE_SPLIT_ERROR", exc_info=True)
            return [], {"message": msg, "code": "TEMP_PART_DIR_ERROR", "detail": str(e_mkdir)}

        if ext_lower == ".pdf":
            split_part_paths, error_info = self._split_pdf_by_size(original_filepath, chunk_size_mb * 1024 * 1024, file_specific_temp_dir)
            if error_info:
                self._try_cleanup_specific_temp_dirs(file_specific_temp_dir, None)
                return [], error_info
        else: 
            self.log_manager.info(f"ファイル種別 {ext_lower} はサイズによる分割対象外です。単一部品として扱います: {original_basename}", context="WORKER_FILE_SPLIT")
        
        if not split_part_paths and not error_info: 
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
        
        if not split_part_paths and not error_info:
             self.log_manager.warning(f"No parts created for '{original_basename}' and no error reported. This might be unexpected.", context="WORKER_FILE_SPLIT")
             # 部品がない場合はエラーとして扱う
             # return [], {"message": f"部品が生成されませんでした: {original_basename}", "code": "NO_PARTS_GENERATED"} # この行は元のロジックで問題がなければ不要

        return split_part_paths, None


    def _merge_searchable_pdfs(self, pdf_part_paths, final_merged_pdf_path):
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
        self.log_manager.debug(f"OcrWorker thread started.", context="WORKER_LIFECYCLE", thread_id=thread_id, num_original_files=len(self.files_to_process_tuples))
        
        if not self._ensure_main_temp_dir_exists():
            self.log_manager.critical("メイン一時フォルダの作成に失敗しました。処理を続行できません。", context="WORKER_LIFECYCLE")
            self.all_files_processed.emit()
            return

        results_folder_name = self.file_actions_config.get("results_folder_name", "OCR結果")
        
        try:
            for worker_internal_idx, (original_file_path, original_file_global_idx) in enumerate(self.files_to_process_tuples):
                if not self.is_running:
                    self.log_manager.info("OcrWorker処理ループが停止シグナルにより中断されました (外部ループ)。", context="WORKER_LIFECYCLE")
                    break
                
                self.original_file_status_update.emit(original_file_path, f"{OCR_STATUS_PROCESSING} (準備中)")

                original_file_basename = os.path.basename(original_file_path)
                original_file_parent_dir = os.path.dirname(original_file_path)
                base_name_for_output_prefix = os.path.splitext(original_file_basename)[0]
                
                self.log_manager.info(f"元ファイル処理開始: '{original_file_basename}' (グローバルインデックス: {original_file_global_idx})", context="WORKER_ORIGINAL_FILE")

                files_to_ocr_for_this_original = []
                current_file_parts_source_dir = None # このファイル専用の部品ソース一時ディレクトリ
                parts_results_temp_dir = None     # このファイル専用の部品結果一時ディレクトリ (分割時)
                was_split = False

                split_enabled = self.current_api_options.get("split_large_files_enabled", False)
                split_chunk_size_mb = self.current_api_options.get("split_chunk_size_mb", 10)
                
                try:
                    original_file_size_bytes = os.path.getsize(original_file_path)
                except OSError as e:
                    msg = f"ファイル '{original_file_basename}' のサイズ取得に失敗。スキップします: {e}"
                    self.log_manager.error(msg, context="WORKER_ORIGINAL_FILE_ERROR", exc_info=True)
                    err_dict = {"message": msg, "code": "FILE_SIZE_ERROR", "detail": str(e)}
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー")
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                    continue

                # ファイル準備 (分割または一時フォルダへのコピー)
                # _split_file は内部でファイル固有の一時ディレクトリを作成し、そこに部品を格納する
                files_to_ocr_for_this_original, prep_error_info = self._split_file(
                    original_file_path, 
                    split_chunk_size_mb, 
                    self.main_temp_dir_for_splits # ベースとなるメイン一時ディレクトリ
                )

                if prep_error_info or not files_to_ocr_for_this_original:
                    self.log_manager.error(f"'{original_file_basename}' のファイル準備(分割/コピー)に失敗しました。エラー: {prep_error_info}", context="WORKER_FILE_PREP_ERROR")
                    err_dict = prep_error_info if prep_error_info else {"message": "ファイル準備失敗 (詳細不明)", "code": "FILE_PREP_UNKNOWN_ERROR"}
                    self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー")
                    self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                    # _split_file 内でエラー時に一時ディレクトリの掃除が試みられる
                    continue
                
                if files_to_ocr_for_this_original: # 処理対象の部品パスが取得できた場合
                    current_file_parts_source_dir = os.path.dirname(files_to_ocr_for_this_original[0]) # 部品が格納されたディレクトリ

                # 分割されたかの判定を修正: 元のファイルパスと処理対象の最初の部品パスが異なるか、または部品が複数あるか
                if len(files_to_ocr_for_this_original) > 1 or \
                   (files_to_ocr_for_this_original and os.path.normpath(files_to_ocr_for_this_original[0]) != os.path.normpath(original_file_path)):
                    was_split = True
                    self.original_file_status_update.emit(original_file_path, OCR_STATUS_SPLITTING)
                    self.log_manager.info(f"ファイル '{original_file_basename}' は {len(files_to_ocr_for_this_original)} 個の部品として処理されます。", context="WORKER_FILE_SPLIT_INFO")
                    # 分割した場合の部品結果の一時保存先 (ファイル固有の一時ディレクトリの下に作成)
                    parts_results_temp_dir = os.path.join(current_file_parts_source_dir, base_name_for_output_prefix + "_results_parts")
                    try:
                        os.makedirs(parts_results_temp_dir, exist_ok=True)
                    except Exception as e_mkdir_results:
                        msg = f"'{original_file_basename}' の部品結果用一時フォルダ作成に失敗: {e_mkdir_results}"
                        self.log_manager.error(msg, context="WORKER_FILE_SPLIT_ERROR", exc_info=True)
                        err_dict = {"message": msg, "code": "TEMP_RESULTS_DIR_ERROR", "detail": str(e_mkdir_results)}
                        self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー")
                        self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                        self._try_cleanup_specific_temp_dirs(current_file_parts_source_dir, None)
                        continue
                else: 
                    was_split = False
                    parts_results_temp_dir = os.path.join(original_file_parent_dir, results_folder_name)
                    try:
                        os.makedirs(parts_results_temp_dir, exist_ok=True)
                    except Exception as e_mkdir_nonsplit:
                        msg = f"非分割ファイル '{original_file_basename}' の結果フォルダ作成に失敗: {e_mkdir_nonsplit}"
                        self.log_manager.error(msg, context="WORKER_IO_ERROR", exc_info=True)
                        err_dict = {"message": msg, "code": "RESULTS_DIR_ERROR", "detail":str(e_mkdir_nonsplit)}
                        self.file_processed.emit(original_file_global_idx, original_file_path, None, err_dict, "エラー")
                        self.searchable_pdf_processed.emit(original_file_global_idx, original_file_path, None, err_dict)
                        self._try_cleanup_specific_temp_dirs(current_file_parts_source_dir, None) # current_file_parts_source_dir は _split_file で作られたパス
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
                        self.log_manager.info(f"'{original_file_basename}' の部品処理が停止シグナルにより中断されました。", context="WORKER_PART_PROCESS")
                        final_ocr_error_for_main = {"message": "処理がユーザーにより中止されました", "code": "USER_INTERRUPT"}
                        pdf_error_for_signal = {"message": "処理中止によりPDF作成不可", "code": "USER_INTERRUPT_PDF"}
                        break 
                    
                    current_part_basename = os.path.basename(current_processing_path) 
                    status_msg_for_ui = f"{OCR_STATUS_PART_PROCESSING} ({part_idx + 1}/{len(files_to_ocr_for_this_original)})"
                    if not was_split and len(files_to_ocr_for_this_original) == 1:
                        status_msg_for_ui = OCR_STATUS_PROCESSING
                    self.original_file_status_update.emit(original_file_path, status_msg_for_ui)
                    self.log_manager.info(f"  部品処理中: '{current_part_basename}' (元ファイル: '{original_file_basename}')", context="WORKER_PART_PROCESS")

                    part_ocr_result_json, part_ocr_api_error_info = self.api_client.read_document(current_processing_path)

                    if part_ocr_api_error_info:
                        self.log_manager.error(f"  部品 '{current_part_basename}' のOCR API処理失敗。エラー: {part_ocr_api_error_info.get('message')}", context="WORKER_PART_OCR_ERROR", detail=part_ocr_api_error_info)
                        all_parts_processed_successfully = False
                        final_ocr_error_for_main = part_ocr_api_error_info
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
                            self.log_manager.info(f"  部品用JSON保存完了: '{part_json_filepath}'", context="WORKER_PART_IO")
                        except IOError as e_json_save:
                            msg = f"部品 '{current_part_basename}' のJSON保存に失敗: {e_json_save}"
                            self.log_manager.error(msg, context="WORKER_PART_IO_ERROR", exc_info=True)
                            all_parts_processed_successfully = False
                            final_ocr_error_for_main = {"message": msg, "code": "PART_JSON_SAVE_ERROR", "detail": str(e_json_save)}
                            break
                    
                    should_create_pdf_output_for_part = self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]
                    if should_create_pdf_output_for_part:
                        self.log_manager.info(f"  部品のサーチャブルPDF作成開始: '{current_part_basename}'", context="WORKER_PART_PDF")
                        part_pdf_content, part_pdf_api_error_info = self.api_client.make_searchable_pdf(current_processing_path)

                        if part_pdf_api_error_info:
                            self.log_manager.error(f"  部品 '{current_part_basename}' のサーチャブルPDF作成API失敗。エラー: {part_pdf_api_error_info.get('message')}", context="WORKER_PART_PDF_ERROR", detail=part_pdf_api_error_info)
                            all_parts_processed_successfully = False
                            pdf_error_for_signal = part_pdf_api_error_info
                            break
                        elif part_pdf_content:
                            part_pdf_filename = current_part_basename 
                            target_pdf_save_dir_for_part = parts_results_temp_dir
                            part_pdf_filepath = os.path.join(target_pdf_save_dir_for_part, part_pdf_filename)
                            try:
                                with open(part_pdf_filepath, 'wb') as f_pdf:
                                    f_pdf.write(part_pdf_content)
                                self.log_manager.info(f"  部品用サーチャブルPDF保存完了: '{part_pdf_filepath}'", context="WORKER_PART_IO")
                                part_pdf_paths_agg.append(part_pdf_filepath)
                            except IOError as e_pdf_save:
                                msg = f"部品 '{current_part_basename}' のサーチャブルPDF保存に失敗: {e_pdf_save}"
                                self.log_manager.error(msg, context="WORKER_PART_IO_ERROR", exc_info=True)
                                all_parts_processed_successfully = False
                                pdf_error_for_signal = {"message": msg, "code": "PART_PDF_SAVE_ERROR", "detail": str(e_pdf_save)}
                                break
                        else:
                            msg = f"部品 '{current_part_basename}' のサーチャブルPDF APIがコンテンツもエラーも返しませんでした。"
                            self.log_manager.error(msg, context="WORKER_PART_PDF_ERROR")
                            all_parts_processed_successfully = False
                            pdf_error_for_signal = {"message": msg, "code": "PART_PDF_NO_RESPONSE"}
                            break
                
                if not self.is_running and not all_parts_processed_successfully:
                     self.log_manager.info(f"'{original_file_basename}' の処理がユーザーにより中断されました。", context="WORKER_LIFECYCLE")
                     if not final_ocr_error_for_main: final_ocr_error_for_main = {"message": "処理がユーザーにより中止されました", "code": "USER_INTERRUPT"}
                     if not pdf_error_for_signal and self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                         pdf_error_for_signal = {"message": "処理中止によりPDF作成不可", "code": "USER_INTERRUPT_PDF"}
                elif not self.is_running and all_parts_processed_successfully:
                     self.log_manager.warning(f"'{original_file_basename}' の処理は成功しましたが、ワーカーは停止されました（予期せぬ状態）。", context="WORKER_LIFECYCLE_UNEXPECTED")

                if all_parts_processed_successfully:
                    self.log_manager.info(f"'{original_file_basename}' の全部品のOCR処理と中間ファイル保存が成功しました。", context="WORKER_ORIGINAL_FILE")
                    if was_split:
                        final_ocr_result_for_main = {"status": "parts_processed_ok", "num_parts": len(files_to_ocr_for_this_original), "detail": f"{len(files_to_ocr_for_this_original)}部品のOCR完了"}
                    elif part_ocr_results_agg:
                        final_ocr_result_for_main = part_ocr_results_agg[0]["result"]
                    else: 
                        final_ocr_result_for_main = {"status": "ocr_done_no_parts_data_unexpected", "message": "OCR成功(データ無)", "code": "OCR_NO_DATA"}

                    should_create_json_globally = self.file_actions_config.get("output_format", "both") in ["json_only", "both"]
                    if should_create_json_globally:
                        if was_split:
                            final_json_output_dir = os.path.join(original_file_parent_dir, results_folder_name)
                            try:
                                os.makedirs(final_json_output_dir, exist_ok=True)
                                copied_json_count = 0
                                total_json_parts_expected = len(files_to_ocr_for_this_original)
                                original_base_name_no_ext = os.path.splitext(original_file_basename)[0]
                                if parts_results_temp_dir and os.path.isdir(parts_results_temp_dir):
                                    for item_name in os.listdir(parts_results_temp_dir):
                                        if item_name.startswith(original_base_name_no_ext) and item_name.endswith(".json") and ".split#" in item_name:
                                            src_json_path = os.path.join(parts_results_temp_dir, item_name)
                                            dest_json_path = self._get_unique_filepath(final_json_output_dir, item_name)
                                            try:
                                                shutil.copy2(src_json_path, dest_json_path)
                                                self.log_manager.info(f"分割JSON部品を最終保存先にコピー: {dest_json_path}", context="WORKER_PART_IO_FINAL")
                                                copied_json_count += 1
                                            except Exception as e_copy_json:
                                                self.log_manager.error(f"分割JSON部品 '{src_json_path}' の最終保存先へのコピー失敗: {e_copy_json}", context="WORKER_PART_IO_FINAL_ERROR", exc_info=True)
                                    if total_json_parts_expected == 0 and copied_json_count == 0: json_status_for_original_file = "部品JSONなし (対象部品0)"
                                    elif copied_json_count == total_json_parts_expected and total_json_parts_expected > 0: json_status_for_original_file = f"{copied_json_count}個の部品JSON出力成功"
                                    elif copied_json_count > 0: json_status_for_original_file = f"部品JSON一部出力 ({copied_json_count}/{total_json_parts_expected})"
                                    else: json_status_for_original_file = "部品JSON出力失敗 (コピーエラー)"
                                else:
                                     self.log_manager.warning(f"部品結果一時フォルダが見つからないかディレクトリではありません。分割JSONをコピーできません: {parts_results_temp_dir}", context="WORKER_PART_IO_FINAL")
                                     json_status_for_original_file = "部品JSON出力エラー (一時フォルダなし)"
                            except Exception as e_mkdir_json:
                                msg = f"最終JSON出力先フォルダ '{final_json_output_dir}' の作成失敗: {e_mkdir_json}"
                                self.log_manager.error(msg, context="WORKER_IO_ERROR", exc_info=True)
                                json_status_for_original_file = "JSON出力先フォルダ作成失敗"
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
                                if merged_path_result and not merge_error: pdf_final_path_for_signal = merged_path_result
                                else: pdf_error_for_signal = merge_error if merge_error else {"message": "PDF結合中に不明なエラー", "code": "MERGE_UNKNOWN_ERROR"}
                            else: 
                                self.log_manager.info(f"PDF結合は設定により無効です。{len(part_pdf_paths_agg)} 個のPDF部品を個別にコピーします。", context="WORKER_PDF_PARTS_COPY")
                                final_pdf_output_dir = os.path.join(original_file_parent_dir, results_folder_name)
                                try:
                                    os.makedirs(final_pdf_output_dir, exist_ok=True)
                                    copied_pdf_count = 0
                                    expected_pdf_parts = len(part_pdf_paths_agg)
                                    for src_pdf_part_path in part_pdf_paths_agg:
                                        if os.path.exists(src_pdf_part_path):
                                            pdf_part_filename = os.path.basename(src_pdf_part_path)
                                            dest_pdf_part_path = self._get_unique_filepath(final_pdf_output_dir, pdf_part_filename)
                                            try:
                                                shutil.copy2(src_pdf_part_path, dest_pdf_part_path)
                                                self.log_manager.info(f"分割PDF部品を最終保存先にコピー: {dest_pdf_part_path}", context="WORKER_PART_IO_FINAL")
                                                copied_pdf_count +=1
                                            except Exception as e_copy_pdf:
                                                self.log_manager.error(f"分割PDF部品 '{src_pdf_part_path}' の最終保存先へのコピー失敗: {e_copy_pdf}", context="WORKER_PART_IO_FINAL_ERROR", exc_info=True)
                                        else:
                                            self.log_manager.warning(f"PDF部品パスが見つかりません。コピーできません: {src_pdf_part_path}", context="WORKER_PART_IO_FINAL")
                                    if expected_pdf_parts == 0 and copied_pdf_count == 0: pdf_error_for_signal = {"message": "対象のPDF部品なし (コピー対象0)", "code": "NO_PARTS_TO_COPY"}
                                    elif copied_pdf_count == expected_pdf_parts and expected_pdf_parts > 0 : pdf_error_for_signal = {"message": f"{copied_pdf_count}個の部品PDF出力成功", "code": "PARTS_COPIED_SUCCESS"}
                                    elif copied_pdf_count > 0: pdf_error_for_signal = {"message": f"部品PDF一部出力 ({copied_pdf_count}/{expected_pdf_parts})", "code": "PARTS_COPIED_PARTIAL"}
                                    else: pdf_error_for_signal = {"message": "部品PDF出力失敗 (コピーエラー)", "code": "PARTS_COPY_ERROR"}
                                except Exception as e_mkdir_pdf:
                                    msg = f"最終PDF出力先フォルダ '{final_pdf_output_dir}' の作成失敗: {e_mkdir_pdf}"
                                    self.log_manager.error(msg, context="WORKER_IO_ERROR", exc_info=True)
                                    pdf_error_for_signal = {"message": msg, "code": "PDF_DIR_ERROR"}
                        elif not was_split and part_pdf_paths_agg:
                            pdf_final_path_for_signal = part_pdf_paths_agg[0]
                        elif not part_pdf_paths_agg and should_create_pdf_globally:
                            pdf_error_for_signal = {"message": "PDF部品が見つかりません (作成対象)", "code": "PDF_PART_MISSING"}
                    else:
                        pdf_error_for_signal = {"message": "作成しない(設定)", "code": "PDF_NOT_REQUESTED"}
                else: 
                    if not final_ocr_error_for_main and not self.user_stopped : final_ocr_error_for_main = {"message": f"'{original_file_basename}' の部品処理中にエラー発生", "code": "PART_PROCESSING_ERROR"}
                    elif self.user_stopped and not final_ocr_error_for_main: final_ocr_error_for_main = {"message": "処理がユーザーにより中止されました", "code": "USER_INTERRUPT"}
                    json_status_for_original_file = "エラー" if not self.user_stopped else "中断"
                    if not (self.file_actions_config.get("output_format", "both") in ["json_only", "both"]): json_status_for_original_file = "作成しない(設定)"
                    if not pdf_error_for_signal and self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                        if self.user_stopped: pdf_error_for_signal = {"message": "処理中止によりPDF作成不可", "code": "USER_INTERRUPT_PDF"}
                        else: pdf_error_for_signal = {"message": f"'{original_file_basename}' の処理エラー等によりPDF作成不可", "code": "PDF_CREATION_FAIL_DUE_TO_OCR_ERROR"}
                
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
                        if not (pdf_error_for_signal and ("作成しない" in pdf_error_for_signal.get("message", "") or "対象外" in pdf_error_for_signal.get("message", ""))):
                             move_original_file_succeeded_final = False
                if self.user_stopped: move_original_file_succeeded_final = False

                current_source_file_to_move = original_file_path 
                if os.path.exists(current_source_file_to_move):
                    destination_subfolder_for_move = None
                    success_folder_name_cfg = self.file_actions_config.get("success_folder_name", "OCR成功")
                    failure_folder_name_cfg = self.file_actions_config.get("failure_folder_name", "OCR失敗")
                    move_on_success_enabled_cfg = self.file_actions_config.get("move_on_success_enabled", False)
                    move_on_failure_enabled_cfg = self.file_actions_config.get("move_on_failure_enabled", False)
                    collision_action_cfg = self.file_actions_config.get("collision_action", "rename")
                    if move_original_file_succeeded_final and move_on_success_enabled_cfg: destination_subfolder_for_move = success_folder_name_cfg
                    elif not move_original_file_succeeded_final and move_on_failure_enabled_cfg: destination_subfolder_for_move = failure_folder_name_cfg
                    if destination_subfolder_for_move and self.is_running: 
                        self._move_file_with_collision_handling(current_source_file_to_move, original_file_parent_dir, destination_subfolder_for_move, collision_action_cfg)
                    elif destination_subfolder_for_move and not self.is_running and self.user_stopped:
                         self.log_manager.info(f"'{original_file_basename}' のファイル移動は処理中断のためスキップされました。", context="WORKER_FILE_MOVE")

                self._try_cleanup_specific_temp_dirs(current_file_parts_source_dir, parts_results_temp_dir if was_split else None)
                time.sleep(0.01)
        finally:
            self._cleanup_main_temp_dir()
            self.all_files_processed.emit()
            if self.is_running and not self.user_stopped:
                 self.log_manager.info("OcrWorkerによる全ファイル処理が完了しました。", context="WORKER_LIFECYCLE")
            elif self.user_stopped:
                 self.log_manager.info("OcrWorkerの処理がユーザーにより停止されました。", context="WORKER_LIFECYCLE")
            else:
                 self.log_manager.warning("OcrWorkerの処理が終了しましたが、is_runningフラグの最終状態が不明確、またはエラーによる可能性があります。", context="WORKER_LIFECYCLE")
            self.log_manager.debug(f"OcrWorkerスレッドが終了しました。", context="WORKER_LIFECYCLE", thread_id=thread_id)

    def stop(self):
        if not self.is_running and self.user_stopped :
            self.log_manager.info("OcrWorker停止リクエストを受けましたが、既に停止処理中または停止済みです。", context="WORKER_LIFECYCLE_STOP")
            return
        self.log_manager.info("OcrWorker停止リクエスト受信 (オーケストレータ/ユーザーから)。", context="WORKER_LIFECYCLE_STOP")
        self.is_running = False
        self.user_stopped = True

    def _move_file_with_collision_handling(self, source_path, root_dest_dir, subfolder_name, collision_action):
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

    def _try_cleanup_specific_temp_dirs(self, source_parts_dir, results_parts_dir_if_split):
        if source_parts_dir and os.path.isdir(source_parts_dir) and self.main_temp_dir_for_splits and self.main_temp_dir_for_splits in source_parts_dir :
            try:
                shutil.rmtree(source_parts_dir)
                self.log_manager.debug(f"一時ソース部品ディレクトリをクリーンアップしました: {source_parts_dir}", context="WORKER_TEMP_CLEANUP")
            except Exception as e:
                self.log_manager.warning(f"一時ソース部品ディレクトリのクリーンアップ失敗: {source_parts_dir}, Error: {e}", context="WORKER_TEMP_CLEANUP_ERROR", exc_info=True)
        
        if results_parts_dir_if_split and os.path.isdir(results_parts_dir_if_split) and self.main_temp_dir_for_splits and self.main_temp_dir_for_splits in results_parts_dir_if_split:
            try:
                shutil.rmtree(results_parts_dir_if_split)
                self.log_manager.debug(f"一時結果部品ディレクトリをクリーンアップしました: {results_parts_dir_if_split}", context="WORKER_TEMP_CLEANUP")
            except Exception as e:
                self.log_manager.warning(f"一時結果部品ディレクトリのクリーンアップ失敗: {results_parts_dir_if_split}, Error: {e}", context="WORKER_TEMP_CLEANUP_ERROR", exc_info=True)