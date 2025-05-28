import sys
import os
import json
import datetime
import time
import shutil
import threading
import platform
import subprocess
import faulthandler
faulthandler.enable()

import io
import tempfile
from PyPDF2 import PdfReader, PdfWriter, PdfMerger

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QToolBar, QVBoxLayout, QWidget,
    QLabel, QMessageBox, QFileDialog, QTextEdit, QSplitter, QDialog, QScrollArea,
    QFormLayout, QPushButton, QHBoxLayout
)
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer

from list_view import ListView
from option_dialog import OptionDialog
from summary_view import SummaryView
from config_manager import ConfigManager
from log_manager import LogManager, LogLevel
from api_client import CubeApiClient

# --- OCRエンジン処理状態の定数 ---
OCR_STATUS_NOT_PROCESSED = "未処理"
OCR_STATUS_PROCESSING = "処理中"
OCR_STATUS_COMPLETED = "完了"
OCR_STATUS_FAILED = "失敗"
OCR_STATUS_SKIPPED_SIZE_LIMIT = "対象外(サイズ上限)"
OCR_STATUS_SPLITTING = "分割中"
OCR_STATUS_PART_PROCESSING = "部品処理中"
OCR_STATUS_MERGING = "結合中"


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
                    return None, {"message": f"結合用PDF部品が見つかりません: {os.path.basename(part_path)}"}
            
            final_dir = os.path.dirname(final_merged_pdf_path)
            os.makedirs(final_dir, exist_ok=True)
            
            merger.write(final_merged_pdf_path)
            merger.close()
            self.log_manager.info(f"Searchable PDF parts successfully merged into: {final_merged_pdf_path}", context="WORKER_PDF_MERGE")
            return final_merged_pdf_path, None 
        except Exception as e:
            self.log_manager.error(f"Error merging PDF parts into {final_merged_pdf_path}: {e}", context="WORKER_PDF_MERGE_ERROR", exc_info=True)
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
        
        for original_file_main_idx, (original_file_path, _) in enumerate(self.files_to_process_tuples):
            if not self.is_running:
                self.log_manager.info("OcrWorker run loop aborted by stop signal (outer loop).", context="WORKER_LIFECYCLE")
                break
            
            self.original_file_status_update.emit(original_file_path, f"{OCR_STATUS_PROCESSING} (準備中)")

            original_file_basename = os.path.basename(original_file_path)
            original_file_parent_dir = os.path.dirname(original_file_path)
            base_name_for_output_prefix = os.path.splitext(original_file_basename)[0]
            
            self.log_manager.info(f"Starting processing for original file: '{original_file_basename}'", context="WORKER_ORIGINAL_FILE")

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
                self.file_processed.emit(original_file_main_idx, original_file_path, None, {"message": "ファイルサイズ取得エラー"}, "エラー")
                self.searchable_pdf_processed.emit(original_file_main_idx, original_file_path, None, {"message": "ファイルサイズ取得エラー"})
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
                    self.file_processed.emit(original_file_main_idx, original_file_path, None, {"message": "分割用一時フォルダ作成失敗"}, "エラー")
                    self.searchable_pdf_processed.emit(original_file_main_idx, original_file_path, None, {"message": "分割用一時フォルダ作成失敗"})
                    continue

                files_to_ocr_for_this_original = self._split_file(original_file_path, split_chunk_size_mb, temp_dir_for_this_file_source_parts)
                
                if not files_to_ocr_for_this_original:
                    self.log_manager.error(f"Splitting failed for '{original_file_basename}'.", context="WORKER_FILE_SPLIT_ERROR")
                    self.file_processed.emit(original_file_main_idx, original_file_path, None, {"message": "ファイル分割失敗"}, "エラー")
                    self.searchable_pdf_processed.emit(original_file_main_idx, original_file_path, None, {"message": "ファイル分割失敗"})
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
                     self.file_processed.emit(original_file_main_idx, original_file_path, None, {"message": "結果フォルダ作成失敗"}, "エラー")
                     self.searchable_pdf_processed.emit(original_file_main_idx, original_file_path, None, {"message": "結果フォルダ作成失敗"})
                     continue


            part_ocr_results_agg = [] 
            part_pdf_paths_agg = []   
            all_parts_processed_successfully = True
            final_ocr_result_for_main = None
            final_ocr_error_for_main = None
            json_status_for_original_file = "作成しない(設定)" 
            pdf_final_path_for_signal = None
            pdf_error_for_signal = None
            merge_error_info_local = None # ★ PDF結合エラーを保持するローカル変数


            for part_idx, current_processing_path in enumerate(files_to_ocr_for_this_original):
                if not self.is_running or not all_parts_processed_successfully:
                    all_parts_processed_successfully = False
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
                
                should_create_json_output = self.file_actions_config.get("output_format", "both") in ["json_only", "both"]
                if should_create_json_output:
                    part_json_filename = os.path.splitext(current_part_basename)[0] + ".json"
                    target_json_save_dir = parts_results_temp_dir if was_split else os.path.join(original_file_parent_dir, results_folder_name)
                    part_json_filepath = os.path.join(target_json_save_dir, part_json_filename)
                    try:
                        with open(part_json_filepath, 'w', encoding='utf-8') as f_json:
                            json.dump(part_ocr_result_json, f_json, ensure_ascii=False, indent=2)
                        self.log_manager.info(f"  JSON for part saved: '{part_json_filepath}'", context="WORKER_PART_IO")
                    except Exception as e_json_save:
                        self.log_manager.error(f"  Failed to save JSON for part '{current_part_basename}': {e_json_save}", context="WORKER_PART_IO_ERROR")
                
                should_create_pdf_output = self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]
                if should_create_pdf_output:
                    self.log_manager.info(f"  Creating searchable PDF for part: '{current_part_basename}'", context="WORKER_PART_PDF")
                    part_pdf_content, part_pdf_error_info = self.api_client.make_searchable_pdf(current_processing_path)

                    if part_pdf_error_info:
                        self.log_manager.error(f"  Searchable PDF creation failed for part '{current_part_basename}'. Error: {part_pdf_error_info.get('message')}", context="WORKER_PART_PDF_ERROR")
                        all_parts_processed_successfully = False
                        pdf_error_for_signal = part_pdf_error_info
                        break
                    elif part_pdf_content:
                        part_pdf_filename = os.path.splitext(current_part_basename)[0] + "_searchable.pdf"
                        target_pdf_save_dir = parts_results_temp_dir if was_split else os.path.join(original_file_parent_dir, results_folder_name)
                        part_pdf_filepath = os.path.join(target_pdf_save_dir, part_pdf_filename)
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
            
            if not self.is_running: break 

            if all_parts_processed_successfully:
                self.log_manager.info(f"All parts of '{original_file_basename}' processed successfully for OCR and intermediate file saving.", context="WORKER_ORIGINAL_FILE")
                
                if was_split:
                    final_ocr_result_for_main = {"status": "parts_processed_ok", "num_parts": len(files_to_ocr_for_this_original), "detail": f"{len(files_to_ocr_for_this_original)}部品のOCR完了"}
                elif part_ocr_results_agg: 
                    final_ocr_result_for_main = part_ocr_results_agg[0]["result"]
                else: 
                    final_ocr_result_for_main = {"status": "ocr_done_no_parts_data"}

                if self.file_actions_config.get("output_format", "both") in ["json_only", "both"]:
                    json_status_for_original_file = "部品JSON作成済 (結合保留)" if was_split else "JSON作成成功"
                
                if self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                    if was_split and part_pdf_paths_agg:
                        self.original_file_status_update.emit(original_file_path, OCR_STATUS_MERGING)
                        final_merged_pdf_dir = os.path.join(original_file_parent_dir, results_folder_name)
                        merged_pdf_filename = f"{base_name_for_output_prefix}.pdf"
                        final_merged_pdf_path_unique = self._get_unique_filepath(final_merged_pdf_dir, merged_pdf_filename)
                        
                        merged_path_result, merge_error_info_local = self._merge_searchable_pdfs(part_pdf_paths_agg, final_merged_pdf_path_unique)
                        if merged_path_result and not merge_error_info_local:
                            pdf_final_path_for_signal = merged_path_result
                        else:
                            all_parts_processed_successfully = False 
                            pdf_error_for_signal = merge_error_info_local if merge_error_info_local else {"message": "PDF結合中に不明なエラー"}
                    elif not was_split and part_pdf_paths_agg: 
                        pdf_final_path_for_signal = part_pdf_paths_agg[0]
                    elif not part_pdf_paths_agg: # PDF作成すべきだが部品がない場合
                        all_parts_processed_successfully = False
                        pdf_error_for_signal = {"message": "PDF部品が見つかりません (結合前)"}
            
            else: 
                if not final_ocr_error_for_main: # パーツループ内でエラーが設定されていなければ
                     final_ocr_error_for_main = {"message": f"'{original_file_basename}' の部品処理中にエラー発生"}
                json_status_for_original_file = "エラー" 
                # pdf_error_for_signal は既にパーツループ内で設定されているか、この段階で設定する
                if not pdf_error_for_signal:
                    pdf_error_for_signal = {"message": f"'{original_file_basename}' の部品処理エラーによりPDF作成不可"}


            # 最終的なPDFステータスの決定
            if self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
                if pdf_final_path_for_signal and not pdf_error_for_signal :
                     pdf_status_for_original_file = "PDF作成成功"
                elif pdf_error_for_signal:
                     pdf_status_for_original_file = "PDF作成失敗"
                elif not all_parts_processed_successfully: # OCRまたは部品PDF作成で失敗した場合
                     pdf_status_for_original_file = "対象外(エラー)" if final_ocr_error_for_main else "PDF作成失敗"
                # else pdf_status_for_original_file は初期値 "作成しない(設定)" または上記条件で設定済
            else:
                pdf_status_for_original_file = "作成しない(設定)"


            self.file_processed.emit(original_file_main_idx, original_file_path, final_ocr_result_for_main, final_ocr_error_for_main, json_status_for_original_file)
            self.searchable_pdf_processed.emit(original_file_main_idx, original_file_path, pdf_final_path_for_signal, pdf_error_for_signal)

            move_original_file_succeeded_final = all_parts_processed_successfully
            # ★ 結合エラーも最終的な成功判定に含める
            if pdf_error_for_signal and self.file_actions_config.get("output_format", "both") in ["pdf_only", "both"]:
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

            if temp_dir_for_this_file_source_parts and os.path.isdir(temp_dir_for_this_file_source_parts):
                try: shutil.rmtree(temp_dir_for_this_file_source_parts)
                except Exception as e: self.log_manager.warning(f"Failed to cleanup source parts temp dir: {e}", context="WORKER_TEMP_CLEANUP")
            
            if was_split and parts_results_temp_dir and os.path.isdir(parts_results_temp_dir) and self.main_temp_dir_for_splits in parts_results_temp_dir:
                 try: shutil.rmtree(parts_results_temp_dir)
                 except Exception as e: self.log_manager.warning(f"Failed to cleanup results parts temp dir after merge: {e}", context="WORKER_TEMP_CLEANUP")
            
            time.sleep(0.01)
        
        self._cleanup_main_temp_dir()
        self.all_files_processed.emit()
        if self.is_running: self.log_manager.info("All files processed by OcrWorker.", context="WORKER_LIFECYCLE")
        else: self.log_manager.info("OcrWorker processing was stopped.", context="WORKER_LIFECYCLE")
        self.log_manager.debug(f"OcrWorker thread finished.", context="WORKER_LIFECYCLE", thread_id=thread_id)

LISTVIEW_UPDATE_INTERVAL_MS = 300

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.log_manager = LogManager()
        self.log_manager.debug("MainWindow initializing...", context="MAINWIN_LIFECYCLE")
        self.setWindowTitle("AI inside Cube Client Ver.0.0.12")
        self.config = ConfigManager.load()
        self.is_ocr_running = False
        self.processed_files_info = [] 
        self.log_widget = QTextEdit()
        self.log_manager.log_message_signal.connect(self.append_log_message_to_widget)
        self.api_client = CubeApiClient(self.config, self.log_manager)
        self.ocr_worker = None
        self.update_timer = QTimer(self); self.update_timer.setSingleShot(True); self.update_timer.timeout.connect(self.perform_batch_list_view_update)
        
        size_cfg = self.config.get("window_size", {"width": 1000, "height": 700}); state_cfg = self.config.get("window_state", "normal"); pos_cfg = self.config.get("window_position"); self.resize(size_cfg["width"], size_cfg["height"])
        if not pos_cfg or pos_cfg.get("x") is None or pos_cfg.get("y") is None:
            try: screen_geometry = QApplication.primaryScreen().geometry(); self.move((screen_geometry.width() - self.width()) // 2, (screen_geometry.height() - self.height()) // 2)
            except Exception as e: self.log_manager.error("Failed to center window.", context="UI_ERROR", exception_info=e); self.move(100, 100)
        else: self.move(pos_cfg["x"], pos_cfg["y"])
        if state_cfg == "maximized": self.showMaximized()

        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget); self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(2, 2, 2, 2)
        self.splitter = QSplitter(Qt.Orientation.Vertical); self.stack = QStackedWidget(); self.summary_view = SummaryView(); self.list_view = ListView(self.processed_files_info); self.stack.addWidget(self.summary_view); self.stack.addWidget(self.list_view); self.splitter.addWidget(self.stack)
        self.log_container = QWidget(); log_layout_inner = QVBoxLayout(self.log_container); log_layout_inner.setContentsMargins(8,8,8,8); log_layout_inner.setSpacing(0)
        self.log_header = QLabel("ログ："); self.log_header.setStyleSheet("margin-left: 6px; padding-bottom: 0px; font-weight: bold;"); log_layout_inner.addWidget(self.log_header)
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet("""
            QTextEdit { font-family: Consolas, Meiryo, monospace; font-size: 9pt; border: 1px solid #D0D0D0; margin: 0px; }
            QTextEdit QScrollBar:vertical { border: 1px solid #C0C0C0; background: #F0F0F0; width: 15px; margin: 0px; }
            QTextEdit QScrollBar::handle:vertical { background: #A0A0A0; min-height: 20px; border-radius: 7px; }
            QTextEdit QScrollBar::add-line:vertical, QTextEdit QScrollBar::sub-line:vertical { border: none; background: none; height: 0px; width: 0px; }
            QTextEdit QScrollBar::up-arrow:vertical, QTextEdit QScrollBar::down-arrow:vertical { height: 0px; width: 0px; background: none; }
            QTextEdit QScrollBar::add-page:vertical, QTextEdit QScrollBar::sub-page:vertical { background: none; }
        """)
        self.log_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        log_layout_inner.addWidget(self.log_widget)
        self.log_container.setStyleSheet("margin: 0px 6px 6px 6px;")
        self.splitter.addWidget(self.log_container); self.splitter.setStyleSheet("QSplitter::handle { background-color: #CCCCCC; height: 2px; }")
        splitter_sizes = self.config.get("splitter_sizes");
        if splitter_sizes and len(splitter_sizes) == 2 and sum(splitter_sizes) > 0 : self.splitter.setSizes(splitter_sizes)
        else: default_height = self.height(); initial_splitter_sizes = [int(default_height * 0.65), int(default_height * 0.35)]; self.splitter.setSizes(initial_splitter_sizes)
        self.main_layout.addWidget(self.splitter)
        
        self.input_folder_path = self.config.get("last_target_dir", "")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"前回終了時の入力フォルダを読み込みました: {self.input_folder_path}", context="SYSTEM_INIT")
        elif self.input_folder_path: 
            self.log_manager.warning(f"前回指定された入力フォルダ '{self.input_folder_path}' は無効です。クリアします。", context="SYSTEM_INIT")
            self.input_folder_path = ""
        else: 
            self.log_manager.info("前回終了時の入力フォルダ指定はありませんでした。", context="SYSTEM_INIT")

        self.setup_toolbar_and_folder_labels()

        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.perform_initial_scan() 
        else:
            self.list_view.update_files(self.processed_files_info) 
            if hasattr(self.summary_view, 'reset_summary'):
                self.summary_view.reset_summary()

        self.current_view = self.config.get("current_view", 0); self.stack.setCurrentIndex(self.current_view)
        log_visible = self.config.get("log_visible", True); self.log_container.setVisible(log_visible)
        self.update_ocr_controls(); 
        self.log_manager.info("Application initialized successfully.", context="SYSTEM_LIFECYCLE")

    def perform_initial_scan(self):
        self.log_manager.info(f"スキャン開始: {self.input_folder_path}", context="FILE_SCAN")
        if self.update_timer.isActive(): self.update_timer.stop()
        self.processed_files_info = []
        collected_files_paths = self._collect_files_from_input_folder()
        current_config = ConfigManager.load()
        ocr_options = current_config.get("options", {}).get(current_config.get("api_type"), {})
        upload_max_size_mb = ocr_options.get("upload_max_size_mb", 50)
        upload_max_bytes = upload_max_size_mb * 1024 * 1024
        output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both")
        initial_json_status_default = "作成しない(設定)"
        if output_format_cfg == "json_only" or output_format_cfg == "both": 
            initial_json_status_default = "-"
        initial_pdf_status_default = "作成しない(設定)"
        if output_format_cfg == "pdf_only" or output_format_cfg == "both": 
            initial_pdf_status_default = "-"
        actually_processable_count = 0
        if collected_files_paths:
            for i, f_path in enumerate(collected_files_paths):
                try:
                    f_size = os.path.getsize(f_path)
                    file_info_item = {
                        "no": i + 1, "path": f_path, "name": os.path.basename(f_path), "size": f_size,
                        "status": "待機中", "ocr_engine_status": OCR_STATUS_NOT_PROCESSED,
                        "ocr_result_summary": "", 
                        "json_status": initial_json_status_default, 
                        "searchable_pdf_status": initial_pdf_status_default
                    }
                    if f_size > upload_max_bytes:
                        file_info_item["status"] = "スキップ(サイズ上限)"
                        file_info_item["ocr_engine_status"] = OCR_STATUS_SKIPPED_SIZE_LIMIT
                        file_info_item["ocr_result_summary"] = f"ファイルサイズが上限 ({upload_max_size_mb}MB) を超過"
                        file_info_item["json_status"] = "スキップ"
                        file_info_item["searchable_pdf_status"] = "スキップ"
                        self.log_manager.warning(f"ファイル '{file_info_item['name']}' ({f_size/(1024*1024):.2f}MB) はアップロード上限 ({upload_max_size_mb}MB) 超過のためスキップ。", context="FILE_SCAN")
                    else:
                        actually_processable_count += 1
                    self.processed_files_info.append(file_info_item)
                except OSError as e:
                    self.log_manager.error(f"ファイル '{f_path}' の情報取得に失敗しました。スキップします。エラー: {e}", context="FILE_SCAN_ERROR")
            self.list_view.update_files(self.processed_files_info)
            self.log_manager.info(f"スキャン完了: {len(self.processed_files_info)}件のファイル情報を読み込み ({actually_processable_count}件処理対象)。", context="FILE_SCAN", total_found=len(self.processed_files_info), processable=actually_processable_count)
        else: 
            self.list_view.update_files(self.processed_files_info);
            self.log_manager.info("スキャン: 対象ファイルは見つかりませんでした。", context="FILE_SCAN")
        if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        if hasattr(self.summary_view, 'start_processing'):
            self.summary_view.total_files = actually_processable_count 
            self.summary_view.update_display()
        self.update_ocr_controls()

    def append_log_message_to_widget(self, level, message):
        if self.log_widget:
            if level == LogLevel.ERROR: self.log_widget.append(f'<font color="red">{message}</font>')
            elif level == LogLevel.WARNING: self.log_widget.append(f'<font color="orange">{message}</font>')
            elif level == LogLevel.DEBUG: self.log_widget.append(f'<font color="gray">{message}</font>')
            else: self.log_widget.append(message)
            self.log_widget.ensureCursorVisible()

    def setup_toolbar_and_folder_labels(self):
        toolbar = QToolBar("Main Toolbar"); self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self.input_folder_action = QAction("📂入力", self); self.input_folder_action.triggered.connect(self.select_input_folder); toolbar.addAction(self.input_folder_action)
        self.toggle_view_action = QAction("📑ビュー", self); self.toggle_view_action.triggered.connect(self.toggle_view); toolbar.addAction(self.toggle_view_action)
        self.option_action = QAction("⚙️設定", self); self.option_action.triggered.connect(self.show_option_dialog); toolbar.addAction(self.option_action)
        toolbar.addSeparator()
        self.start_ocr_action = QAction("▶️開始", self); self.start_ocr_action.triggered.connect(self.confirm_start_ocr); toolbar.addAction(self.start_ocr_action)
        self.resume_ocr_action = QAction("↪️再開", self)
        self.resume_ocr_action.setToolTip("未処理または失敗したファイルのOCR処理を再開します")
        self.resume_ocr_action.triggered.connect(self.confirm_resume_ocr)
        toolbar.addAction(self.resume_ocr_action)
        self.stop_ocr_action = QAction("⏹️中止", self); self.stop_ocr_action.triggered.connect(self.confirm_stop_ocr); toolbar.addAction(self.stop_ocr_action)
        self.rescan_action = QAction("🔄再スキャン", self); self.rescan_action.triggered.connect(self.confirm_rescan_ui); self.rescan_action.setEnabled(False); toolbar.addAction(self.rescan_action)
        toolbar.addSeparator()
        self.log_toggle_action = QAction("📄ログ表示", self); self.log_toggle_action.triggered.connect(self.toggle_log_display); toolbar.addAction(self.log_toggle_action)
        self.clear_log_action = QAction("🗑️ログクリア", self); self.clear_log_action.triggered.connect(self.clear_log_display); toolbar.addAction(self.clear_log_action)
        folder_label_toolbar = QToolBar("Folder Paths Toolbar"); folder_label_toolbar.setMovable(False)
        folder_label_widget = QWidget(); folder_label_layout = QFormLayout(folder_label_widget)
        folder_label_layout.setContentsMargins(5, 5, 5, 5); folder_label_layout.setSpacing(3)
        self.input_folder_button = QPushButton(f"{self.input_folder_path or '未選択'}")
        self.input_folder_button.setStyleSheet("""
            QPushButton { border: none; background: transparent; text-align: left; padding: 0px; margin: 0px; }
            QPushButton:hover { text-decoration: underline; color: blue; }
        """)
        self.input_folder_button.setFlat(True)
        self.input_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.input_folder_button.clicked.connect(self.open_input_folder_in_explorer)
        folder_label_layout.addRow("入力フォルダ:", self.input_folder_button)
        folder_label_toolbar.addWidget(folder_label_widget)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, folder_label_toolbar)
        self.insertToolBarBreak(folder_label_toolbar)

    def open_input_folder_in_explorer(self):
        self.log_manager.debug(f"Attempting to open folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            try:
                if platform.system() == "Windows":
                    norm_path = os.path.normpath(self.input_folder_path)
                    os.startfile(norm_path)
                elif platform.system() == "Darwin":
                    subprocess.run(['open', self.input_folder_path], check=True)
                else:
                    subprocess.run(['xdg-open', self.input_folder_path], check=True)
                self.log_manager.info(f"Successfully opened folder: {self.input_folder_path}", context="UI_ACTION_OPEN_FOLDER")
            except Exception as e:
                self.log_manager.error(f"Failed to open folder '{self.input_folder_path}'. Error: {e}", context="UI_ACTION_OPEN_FOLDER_ERROR", exception_info=e)
                QMessageBox.warning(self, "フォルダを開けません", f"フォルダ '{self.input_folder_path}' を開けませんでした。\nエラー: {e}")
        else:
            self.log_manager.warning(f"Cannot open folder: Path is invalid or not set. Path: '{self.input_folder_path}'", context="UI_ACTION_OPEN_FOLDER_INVALID")
            QMessageBox.information(self, "フォルダ情報なし", "入力フォルダが選択されていないか、無効なパスです。")

    def toggle_view(self):
        self.current_view = 1 - self.current_view; self.stack.setCurrentIndex(self.current_view); self.log_manager.info(f"View toggled to: {'ListView' if self.current_view == 1 else 'SummaryView'}", context="UI_ACTION")
    def toggle_log_display(self):
        visible = self.log_container.isVisible(); self.log_container.setVisible(not visible); self.log_manager.info(f"Log display toggled: {'Hidden' if visible else 'Shown'}", context="UI_ACTION")

    def show_option_dialog(self):
        self.log_manager.debug("Opening options dialog.", context="UI_ACTION")
        dialog = OptionDialog(self)
        if dialog.exec():
            self.config = ConfigManager.load()
            self.log_manager.info("Options saved and reloaded.", context="CONFIG_EVENT")
            self.api_client = CubeApiClient(self.config, self.log_manager)
            new_output_format = self.config.get("file_actions", {}).get("output_format", "both")
            self.log_manager.info(f"Output format changed to: {new_output_format}. Updating unprocessed items status.", context="CONFIG_EVENT")
            updated_count = 0
            for item_info in self.processed_files_info:
                if item_info.get("ocr_engine_status") == OCR_STATUS_NOT_PROCESSED:
                    old_json_status = item_info.get("json_status")
                    old_pdf_status = item_info.get("searchable_pdf_status")
                    if new_output_format == "json_only" or new_output_format == "both":
                        item_info["json_status"] = "-" 
                    else:
                        item_info["json_status"] = "作成しない(設定)"
                    if new_output_format == "pdf_only" or new_output_format == "both":
                        item_info["searchable_pdf_status"] = "-"
                    else:
                        item_info["searchable_pdf_status"] = "作成しない(設定)"
                    if old_json_status != item_info["json_status"] or old_pdf_status != item_info["searchable_pdf_status"]:
                        updated_count += 1
            if updated_count > 0:
                self.log_manager.info(f"{updated_count} unprocessed items' output status expectations were updated.", context="CONFIG_EVENT")
                self.list_view.update_files(self.processed_files_info)
        else:
            self.log_manager.info("Options dialog cancelled.", context="UI_ACTION")

    def select_input_folder(self):
        self.log_manager.debug("Selecting input folder.", context="UI_ACTION")
        last_dir = self.input_folder_path or self.config.get("last_target_dir", os.path.expanduser("~"))
        if not os.path.isdir(last_dir): last_dir = os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "入力フォルダを選択", last_dir)
        if folder:
            self.log_manager.info(f"Input folder selected by user: {folder}", context="UI_EVENT")
            self.input_folder_path = folder
            self.input_folder_button.setText(folder) 
            self.log_manager.info(f"Performing rescan for newly selected folder: {folder}", context="UI_EVENT")
            self.perform_rescan()
        else:
            self.log_manager.info("Input folder selection cancelled.", context="UI_EVENT")

    def check_input_folder_validity(self):
        pass

    def _collect_files_from_input_folder(self):
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path): self.log_manager.warning("File collection skipped: Input folder invalid.", context="FILE_SCAN"); return []
        current_config = ConfigManager.load(); file_actions_config = current_config.get("file_actions", {}); excluded_folder_names = [name for name in [file_actions_config.get("success_folder_name"), file_actions_config.get("failure_folder_name"), file_actions_config.get("results_folder_name")] if name and name.strip()]
        options_cfg = current_config.get("options", {}).get(current_config.get("api_type"), {}); max_files = options_cfg.get("max_files_to_process", 100); recursion_depth_limit = options_cfg.get("recursion_depth", 5)
        self.log_manager.info(f"File collection started: In='{self.input_folder_path}', Max={max_files}, DepthLimit={recursion_depth_limit}, Exclude={excluded_folder_names}", context="FILE_SCAN")
        collected_files = []; supported_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        for root, dirs, files in os.walk(self.input_folder_path, topdown=True, followlinks=False):
            norm_root = os.path.normpath(root); norm_input_root = os.path.normpath(self.input_folder_path); relative_path_from_input = os.path.relpath(norm_root, norm_input_root)
            current_depth = 0 if relative_path_from_input == "." else len(relative_path_from_input.split(os.sep))
            if current_depth >= recursion_depth_limit: dirs[:] = []; continue
            dirs_to_remove_from_walk = [d for d in dirs if d in excluded_folder_names];
            for d_to_remove in dirs_to_remove_from_walk:
                if d_to_remove in dirs: dirs.remove(d_to_remove)
            for filename in sorted(files):
                if len(collected_files) >= max_files: self.log_manager.info(f"Max files ({max_files}) reached.", context="FILE_SCAN"); return sorted(list(set(collected_files)))
                file_path = os.path.join(root, filename)
                if os.path.islink(file_path): continue
                if os.path.splitext(filename)[1].lower() in supported_extensions: collected_files.append(file_path)
        unique_sorted_files = sorted(list(set(collected_files)))
        self.log_manager.info(f"File collection finished: Found {len(unique_sorted_files)} files.", context="FILE_SCAN", count=len(unique_sorted_files))
        return unique_sorted_files

    def _create_confirmation_summary(self, files_to_process_count):
        current_config = ConfigManager.load(); file_actions_cfg = current_config.get("file_actions", {}); api_type_key = current_config.get("api_type", "cube_fullocr"); ocr_opts = current_config.get("options", {}).get(api_type_key, {})
        summary_lines = ["<strong><u>OCR実行設定の確認</u></strong><br><br>"]; summary_lines.append("<strong>【基本設定】</strong>"); summary_lines.append(f"入力フォルダ: {self.input_folder_path or '未選択'}"); summary_lines.append("<br>"); summary_lines.append("<strong>【ファイル処理後の出力と移動】</strong>")
        output_format_value = file_actions_cfg.get("output_format", "both"); output_format_display_map = {"json_only": "JSONのみ", "pdf_only": "サーチャブルPDFのみ", "both": "JSON と サーチャブルPDF (両方)"}; output_format_display = output_format_display_map.get(output_format_value, "未設定/不明"); summary_lines.append(f"出力形式: <strong>{output_format_display}</strong>")
        results_folder_name = file_actions_cfg.get("results_folder_name", "(未設定)"); summary_lines.append(f"OCR結果サブフォルダ名: <strong>{results_folder_name}</strong>"); summary_lines.append(f"  <small>(備考: 元ファイルの各場所に '{results_folder_name}' サブフォルダを作成し結果を保存)</small>")
        move_on_success = file_actions_cfg.get("move_on_success_enabled", False); success_folder_name_cfg = file_actions_cfg.get("success_folder_name", "(未設定)"); summary_lines.append(f"成功ファイル移動: {'<strong>する</strong>' if move_on_success else 'しない'}");
        if move_on_success: summary_lines.append(f"  移動先サブフォルダ名: <strong>{success_folder_name_cfg}</strong>"); summary_lines.append(f"    <small>(備考: 元ファイルの各場所に '{success_folder_name_cfg}' サブフォルダを作成し移動)</small>")
        move_on_failure = file_actions_cfg.get("move_on_failure_enabled", False); failure_folder_name_cfg = file_actions_cfg.get("failure_folder_name", "(未設定)"); summary_lines.append(f"失敗ファイル移動: {'<strong>する</strong>' if move_on_failure else 'しない'}");
        if move_on_failure: summary_lines.append(f"  移動先サブフォルダ名: <strong>{failure_folder_name_cfg}</strong>"); summary_lines.append(f"    <small>(備考: 元ファイルの各場所に '{failure_folder_name_cfg}' サブフォルダを作成し移動)</small>")
        if move_on_success or move_on_failure: collision_map = {"overwrite": "上書き", "rename": "リネームする (例: file.pdf --> file(1).pdf)", "skip": "スキップ"}; collision_act = collision_map.get(file_actions_cfg.get("collision_action", "rename"), "リネームする (例: file.pdf --> file(1).pdf)"); summary_lines.append(f"ファイル名衝突時 (移動先): {collision_act}")
        summary_lines.append("<br>"); summary_lines.append("<strong>【ファイル検索設定】</strong>"); summary_lines.append(f"最大処理ファイル数: {ocr_opts.get('max_files_to_process', 100)}"); summary_lines.append(f"再帰検索の深さ (入力フォルダ自身を0): {ocr_opts.get('recursion_depth', 5)}")
        summary_lines.append(f"アップロード上限サイズ: {ocr_opts.get('upload_max_size_mb', 50)} MB")
        if ocr_opts.get('split_large_files_enabled', False):
            summary_lines.append(f"ファイル分割: <strong>有効</strong> (分割サイズ目安: {ocr_opts.get('split_chunk_size_mb',10)} MB)")
        else:
            summary_lines.append("ファイル分割: 無効")
        summary_lines.append(f"処理対象ファイル数 (収集結果・サイズフィルタ後): {files_to_process_count} 件"); 
        summary_lines.append("<br>"); summary_lines.append("<strong>【主要OCRオプション】</strong>"); summary_lines.append(f"回転補正: {'ON' if ocr_opts.get('adjust_rotation', 0) == 1 else 'OFF'}"); summary_lines.append(f"OCRモデル: {ocr_opts.get('ocr_model', 'katsuji')}"); summary_lines.append("<br>上記内容で処理を開始します。")
        return "<br>".join([line.replace("  <small>", "&nbsp;&nbsp;<small>").replace("    <small>", "&nbsp;&nbsp;&nbsp;&nbsp;<small>") for line in summary_lines])

    def confirm_start_ocr(self):
        self.log_manager.debug("Confirming OCR start...", context="OCR_FLOW")
        if not self.input_folder_path or not os.path.isdir(self.input_folder_path):
            self.log_manager.warning("OCR start aborted: Input folder invalid.", context="OCR_FLOW")
            QMessageBox.warning(self, "入力フォルダエラー", "入力フォルダが選択されていないか、無効なパスです。")
            return
        if self.is_ocr_running:
            self.log_manager.info("OCR start aborted: Already running.", context="OCR_FLOW")
            return
        
        files_eligible_for_ocr_info = [
            item for item in self.processed_files_info 
            if item.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
        ]

        if not files_eligible_for_ocr_info:
            self.log_manager.info("OCR start aborted: No eligible files to process.", context="OCR_FLOW")
            QMessageBox.information(self,"対象ファイルなし", "処理対象となるファイル（サイズ上限内）が見つかりませんでした。")
            return

        ocr_already_attempted_in_eligible_list = any(
            item.get("ocr_engine_status") not in [OCR_STATUS_NOT_PROCESSED, None, OCR_STATUS_SKIPPED_SIZE_LIMIT]
            for item in files_eligible_for_ocr_info
        )
        
        if ocr_already_attempted_in_eligible_list:
            message = "OCR処理を再度実行します。\n\n" \
                      "現在リストされている処理対象ファイルのOCR処理状態がリセットされ、最初から処理されます。\n" \
                      "(サイズ上限でスキップされたファイルは影響を受けません)\n\n" \
                      "よろしいですか？"
            reply = QMessageBox.question(self, "OCR再実行の確認", message,
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                         QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                self.log_manager.info("OCR re-execution cancelled by user.", context="OCR_FLOW")
                return
        
        confirmation_summary = self._create_confirmation_summary(len(files_eligible_for_ocr_info)) 
        confirm_dialog = OcrConfirmationDialog(confirmation_summary, self)
        if not confirm_dialog.exec():
            self.log_manager.info("OCR start cancelled by user (final confirmation dialog).", context="OCR_FLOW")
            return

        self.log_manager.info(f"User confirmed. Starting OCR process for {len(files_eligible_for_ocr_info)} eligible files...", context="OCR_FLOW")
        current_config_for_run = ConfigManager.load()
        self.is_ocr_running = True
        
        files_to_send_to_worker_tuples = []
        output_format_cfg = current_config_for_run.get("file_actions", {}).get("output_format", "both")
        initial_json_status_ui = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
        initial_pdf_status_ui = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"

        for original_idx, item_info in enumerate(self.processed_files_info):
            if item_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT :
                item_info["status"] = OCR_STATUS_PROCESSING 
                item_info["ocr_engine_status"] = OCR_STATUS_PROCESSING 
                item_info["ocr_result_summary"] = "" 
                item_info["json_status"] = initial_json_status_ui 
                item_info["searchable_pdf_status"] = initial_pdf_status_ui 
                files_to_send_to_worker_tuples.append((item_info["path"], original_idx))
        
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'):
            self.summary_view.start_processing(len(files_to_send_to_worker_tuples))
        
        self.log_manager.info(f"Instantiating OcrWorker for {len(files_to_send_to_worker_tuples)} files.", context="OCR_FLOW")
        self.ocr_worker = OcrWorker(
            api_client=self.api_client,
            files_to_process_tuples=files_to_send_to_worker_tuples,
            input_root_folder=self.input_folder_path,
            log_manager=self.log_manager,
            config=current_config_for_run
        )
        self.ocr_worker.original_file_status_update.connect(self.on_original_file_status_update_from_worker)
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()
        self.update_ocr_controls()

    def confirm_resume_ocr(self):
        self.log_manager.debug("Confirming OCR resume...", context="OCR_FLOW")
        if self.is_ocr_running:
            self.log_manager.info("OCR resume aborted: OCR is already running.", context="OCR_FLOW")
            return

        files_to_resume_tuples = []
        for original_idx, item_info in enumerate(self.processed_files_info):
            if item_info.get("ocr_engine_status") in [OCR_STATUS_NOT_PROCESSED, OCR_STATUS_FAILED] and \
               item_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT:
                files_to_resume_tuples.append((item_info["path"], original_idx))

        if not files_to_resume_tuples:
            self.log_manager.info("OCR resume: No files found with 'Not Processed' or 'Failed' OCR status (and not size-skipped).", context="OCR_FLOW")
            QMessageBox.information(self, "再開対象なし", "OCR未処理または失敗状態のファイル（サイズ上限内）が見つかりませんでした。")
            self.update_ocr_controls()
            return

        message = f"{len(files_to_resume_tuples)} 件の未処理または失敗したファイルに対してOCR処理を再開します。\n\n" \
                  "よろしいですか？"
        reply = QMessageBox.question(self, "OCR再開の確認", message,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.Yes)
        if reply == QMessageBox.StandardButton.No:
            self.log_manager.info("OCR resume cancelled by user.", context="OCR_FLOW")
            return
            
        self.log_manager.info(f"User confirmed. Resuming OCR process for {len(files_to_resume_tuples)} files.", context="OCR_FLOW")
        current_config_for_run = ConfigManager.load()
        self.is_ocr_running = True
        output_format_cfg = current_config_for_run.get("file_actions", {}).get("output_format", "both")
        initial_json_status_ui = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
        initial_pdf_status_ui = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"

        for path, original_idx in files_to_resume_tuples:
            item_info = self.processed_files_info[original_idx]
            item_info["ocr_engine_status"] = OCR_STATUS_PROCESSING
            item_info["status"] = f"{OCR_STATUS_PROCESSING}(再開)" 
            item_info["ocr_result_summary"] = ""
            item_info["json_status"] = initial_json_status_ui
            item_info["searchable_pdf_status"] = initial_pdf_status_ui
        
        self.list_view.update_files(self.processed_files_info)
        if hasattr(self.summary_view, 'start_processing'):
             self.summary_view.start_processing(len(files_to_resume_tuples))

        self.log_manager.info(f"Instantiating OcrWorker for {len(files_to_resume_tuples)} files (resume).", context="OCR_FLOW")
        self.ocr_worker = OcrWorker(
            api_client=self.api_client,
            files_to_process_tuples=files_to_resume_tuples,
            input_root_folder=self.input_folder_path,
            log_manager=self.log_manager,
            config=current_config_for_run
        )
        self.ocr_worker.original_file_status_update.connect(self.on_original_file_status_update_from_worker)
        self.ocr_worker.file_processed.connect(self.on_file_ocr_processed)
        self.ocr_worker.searchable_pdf_processed.connect(self.on_file_searchable_pdf_processed)
        self.ocr_worker.all_files_processed.connect(self.on_all_files_processed)
        self.ocr_worker.start()
        self.update_ocr_controls()

    def on_original_file_status_update_from_worker(self, original_file_path, status_message):
        target_file_info = next((item for item in self.processed_files_info if item["path"] == original_file_path), None)
        if target_file_info:
            self.log_manager.debug(f"UI Update for '{os.path.basename(original_file_path)}': {status_message}", context="UI_STATUS_UPDATE")
            target_file_info["status"] = status_message
            
            if status_message == OCR_STATUS_SPLITTING:
                target_file_info["ocr_engine_status"] = OCR_STATUS_SPLITTING
            elif OCR_STATUS_PART_PROCESSING in status_message:
                target_file_info["ocr_engine_status"] = OCR_STATUS_PART_PROCESSING
            elif status_message == OCR_STATUS_MERGING:
                 target_file_info["ocr_engine_status"] = OCR_STATUS_MERGING

            if not self.update_timer.isActive():
                self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)
        else:
            self.log_manager.warning(f"Status update received for unknown file: {original_file_path}", context="UI_STATUS_UPDATE_WARN")

    def confirm_stop_ocr(self):
        self.log_manager.debug("Confirming OCR stop...", context="OCR_FLOW")
        if self.ocr_worker and self.ocr_worker.isRunning():
            reply = QMessageBox.question(self, "OCR中止確認", "OCR処理を中止しますか？",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.log_manager.info("User confirmed OCR stop. Requesting worker to stop.", context="OCR_FLOW")
                self.ocr_worker.stop()
            else:
                self.log_manager.info("User cancelled OCR stop.", context="OCR_FLOW")
        else:
            self.log_manager.debug("Stop OCR requested, but OCR is not running or worker is None.", context="OCR_FLOW")
            if self.is_ocr_running:
                self.log_manager.warning("OCR stop: UI state was 'running' but worker not active. Resetting UI state as interrupted.", context="OCR_FLOW_STATE_MISMATCH")
                self.is_ocr_running = False 
                for item_info in self.processed_files_info:
                    current_engine_status = item_info.get("ocr_engine_status")
                    if current_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING]:
                        item_info["ocr_engine_status"] = OCR_STATUS_NOT_PROCESSED 
                        item_info["status"] = "待機中(中断)"
                self.perform_batch_list_view_update()
                self.update_ocr_controls()
                QMessageBox.information(self, "処理状態", "OCR処理は既に停止されているか、開始されていませんでした。UIを整合しました。")
            else:
                self.update_ocr_controls()

    def update_ocr_controls(self):
        running = self.is_ocr_running
        
        has_processable_files = any(
            f_info.get("ocr_engine_status") not in [
                OCR_STATUS_SKIPPED_SIZE_LIMIT, 
                OCR_STATUS_COMPLETED, 
                OCR_STATUS_FAILED, 
                OCR_STATUS_PROCESSING, 
                OCR_STATUS_SPLITTING, 
                OCR_STATUS_PART_PROCESSING,
                OCR_STATUS_MERGING
            ]
            for f_info in self.processed_files_info
        ) or any ( 
            f_info.get("ocr_engine_status") == OCR_STATUS_FAILED and f_info.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
            for f_info in self.processed_files_info
        )
        can_start = not running and has_processable_files

        if self.start_ocr_action.isEnabled() != can_start:
            self.start_ocr_action.setEnabled(can_start)

        can_resume_eval = False
        if not running and self.processed_files_info:
            has_failed_files = any(f.get("ocr_engine_status") == OCR_STATUS_FAILED for f in self.processed_files_info if f.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT)
            has_eligible_not_processed_files = any(
                f.get("ocr_engine_status") == OCR_STATUS_NOT_PROCESSED 
                for f in self.processed_files_info if f.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
            )
            processable_files_for_resume_check = [
                f for f in self.processed_files_info if f.get("ocr_engine_status") != OCR_STATUS_SKIPPED_SIZE_LIMIT
            ]
            all_processable_are_pristine_not_processed = False
            if processable_files_for_resume_check:
                all_processable_are_pristine_not_processed = all(
                    f.get("ocr_engine_status") == OCR_STATUS_NOT_PROCESSED for f in processable_files_for_resume_check
                )
            if has_failed_files:
                can_resume_eval = True
            elif has_eligible_not_processed_files and not all_processable_are_pristine_not_processed:
                can_resume_eval = True
        
        if hasattr(self, 'resume_ocr_action') and self.resume_ocr_action.isEnabled() != can_resume_eval:
            self.resume_ocr_action.setEnabled(can_resume_eval)

        if self.stop_ocr_action.isEnabled() != running:
            self.stop_ocr_action.setEnabled(running)
        
        can_rescan = not running and (len(self.processed_files_info) > 0 or bool(self.input_folder_path))
        if self.rescan_action.isEnabled() != can_rescan:
            self.rescan_action.setEnabled(can_rescan)
        
        enable_actions_if_not_running = not running
        if self.input_folder_action.isEnabled() != enable_actions_if_not_running:
            self.input_folder_action.setEnabled(enable_actions_if_not_running)
        if self.option_action.isEnabled() != enable_actions_if_not_running:
            self.option_action.setEnabled(enable_actions_if_not_running)
        
        if not self.toggle_view_action.isEnabled():
             self.toggle_view_action.setEnabled(True)

    def perform_batch_list_view_update(self):
        self.log_manager.debug(f"Performing batch ListView update for {len(self.processed_files_info)} items.", context="UI_UPDATE");
        if self.list_view: self.list_view.update_files(self.processed_files_info)

    def on_file_ocr_processed(self, original_file_main_idx, original_file_path, ocr_result_data_for_original, ocr_error_info_for_original, json_save_info_for_original):
        self.log_manager.debug(
            f"Original File OCR stage processed (MainWin): {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Success={not ocr_error_info_for_original}",
            context="CALLBACK_OCR_ORIGINAL"
        )
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx} received in on_file_ocr_processed. Max idx: {len(self.processed_files_info)-1}", context="CALLBACK_ERROR")
            return
            
        target_file_info = self.processed_files_info[original_file_main_idx]
        if target_file_info["path"] != original_file_path:
             self.log_manager.warning(f"Path mismatch for original_file_main_idx {original_file_main_idx}. Expected '{target_file_info['path']}', got '{original_file_path}'. Updating based on index.", context="CALLBACK_WARN")

        ocr_overall_succeeded = False
        if ocr_error_info_for_original:
            target_file_info["status"] = "OCR失敗"
            target_file_info["ocr_engine_status"] = OCR_STATUS_FAILED
            target_file_info["ocr_result_summary"] = ocr_error_info_for_original.get('message', '不明なエラー')
        elif ocr_result_data_for_original:
            target_file_info["status"] = "OCR成功" 
            target_file_info["ocr_engine_status"] = OCR_STATUS_COMPLETED 
            ocr_overall_succeeded = True
            # ★ 修正: Workerから渡される辞書の形式に合わせて表示を調整
            if isinstance(ocr_result_data_for_original, dict) and "message" in ocr_result_data_for_original:
                target_file_info["ocr_result_summary"] = ocr_result_data_for_original["message"]
            elif isinstance(ocr_result_data_for_original, dict) and "status" in ocr_result_data_for_original and ocr_result_data_for_original["status"] == "parts_processed_ok":
                target_file_info["ocr_result_summary"] = ocr_result_data_for_original.get("detail", f"{ocr_result_data_for_original.get('num_parts','?')}部品のOCR完了")
            elif isinstance(ocr_result_data_for_original, list) and len(ocr_result_data_for_original) > 0 : 
                try:
                    first_page_result = ocr_result_data_for_original[0].get("result", {})
                    fulltext = first_page_result.get("fulltext", "") or first_page_result.get("aGroupingFulltext", "")
                    target_file_info["ocr_result_summary"] = (fulltext[:50] + '...') if len(fulltext) > 50 else (fulltext or "(テキスト抽出なし)")
                except Exception: target_file_info["ocr_result_summary"] = "結果解析エラー(集約)"
            else:
                 target_file_info["ocr_result_summary"] = "OCR結果あり(形式不明)"
        else:
            target_file_info["status"] = "OCR状態不明"
            target_file_info["ocr_engine_status"] = OCR_STATUS_FAILED 
            target_file_info["ocr_result_summary"] = "APIレスポンスなし(集約)" # ★ 修正

        if isinstance(json_save_info_for_original, str):
            target_file_info["json_status"] = json_save_info_for_original
        elif ocr_error_info_for_original : target_file_info["json_status"] = "対象外(OCR失敗)"
        else: target_file_info["json_status"] = "JSON状態不明"
        
        if hasattr(self.summary_view, 'update_for_processed_file'):
             self.summary_view.update_for_processed_file(is_success=ocr_overall_succeeded)
        
        self.update_ocr_controls()
        self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)

    def on_file_searchable_pdf_processed(self, original_file_main_idx, original_file_path, pdf_final_path, pdf_error_info):
        self.log_manager.debug(f"Original File Searchable PDF processed: {os.path.basename(original_file_path)}, Original Idx={original_file_main_idx}, Path={pdf_final_path}, Error={pdf_error_info}", context="CALLBACK_PDF_ORIGINAL")
        if not (0 <= original_file_main_idx < len(self.processed_files_info)):
            self.log_manager.error(f"Invalid original_file_main_idx {original_file_main_idx} received in on_file_searchable_pdf_processed. Max idx: {len(self.processed_files_info)-1}", context="CALLBACK_ERROR")
            return
            
        target_file_info = self.processed_files_info[original_file_main_idx]
        if target_file_info["path"] != original_file_path:
             self.log_manager.warning(f"Path mismatch for original_file_main_idx {original_file_main_idx} (PDF). Expected '{target_file_info['path']}', got '{original_file_path}'. Updating based on index.", context="CALLBACK_WARN")

        current_config = ConfigManager.load(); output_format = current_config.get("file_actions", {}).get("output_format", "both")
        ocr_engine_status_for_file = target_file_info.get("ocr_engine_status")

        if output_format == "json_only": 
            target_file_info["searchable_pdf_status"] = "作成しない(設定)"
        elif isinstance(pdf_error_info, dict) and pdf_error_info.get("message") == "作成対象外(設定)":
            target_file_info["searchable_pdf_status"] = "作成しない(設定)"
        elif pdf_final_path and not pdf_error_info and os.path.exists(pdf_final_path):
            target_file_info["searchable_pdf_status"] = "PDF作成成功"
            if target_file_info["ocr_engine_status"] == OCR_STATUS_COMPLETED:
                 target_file_info["status"] = "完了" 
        elif ocr_engine_status_for_file == OCR_STATUS_FAILED : 
             target_file_info["searchable_pdf_status"] = "対象外(OCR失敗)"
        elif pdf_error_info: 
            target_file_info["searchable_pdf_status"] = "PDF作成失敗"
            error_msg = pdf_error_info.get('message', 'PDF作成で不明なエラー')
            # エラーメッセージをOCR結果サマリーに追加（既にOCR失敗でない場合）
            if "OCR失敗" not in target_file_info.get("status", ""):
                if target_file_info["ocr_result_summary"]:
                    target_file_info["ocr_result_summary"] += f" (PDFエラー: {error_msg})"
                else:
                    target_file_info["ocr_result_summary"] = f"PDFエラー: {error_msg}"
            if target_file_info["status"] != "OCR失敗": # UI上の全体ステータスも更新
                target_file_info["status"] = "PDF作成失敗"
        else: 
            target_file_info["searchable_pdf_status"] = "PDF状態不明"
        
        self.update_timer.start(LISTVIEW_UPDATE_INTERVAL_MS)


    def on_all_files_processed(self):
        self.log_manager.info("All files processing finished by worker.", context="OCR_FLOW_COMPLETE");
        if self.update_timer.isActive(): self.update_timer.stop()
        was_interrupted_by_user = False
        if self.ocr_worker and self.ocr_worker.user_stopped:
            was_interrupted_by_user = True
        if was_interrupted_by_user:
            self.log_manager.info("OCR processing was interrupted by user.", context="OCR_FLOW_COMPLETE")
            current_config = ConfigManager.load()
            output_format_cfg = current_config.get("file_actions", {}).get("output_format", "both")
            initial_json_status_ui = "処理待ち" if output_format_cfg in ["json_only", "both"] else "作成しない(設定)"
            initial_pdf_status_ui = "処理待ち" if output_format_cfg in ["pdf_only", "both"] else "作成しない(設定)"
            for item_info in self.processed_files_info:
                current_engine_status = item_info.get("ocr_engine_status")
                if current_engine_status in [OCR_STATUS_PROCESSING, OCR_STATUS_SPLITTING, OCR_STATUS_PART_PROCESSING, OCR_STATUS_MERGING]:
                    item_info["ocr_engine_status"] = OCR_STATUS_NOT_PROCESSED
                    item_info["status"] = "待機中(中断)"
                    item_info["ocr_result_summary"] = "(中断されました)"
                    item_info["json_status"] = initial_json_status_ui
                    item_info["searchable_pdf_status"] = initial_pdf_status_ui
        self.is_ocr_running = False
        self.perform_batch_list_view_update()
        self.update_ocr_controls()
        final_message = "全てのファイルのOCR処理が完了しました。"
        if was_interrupted_by_user:
            final_message = "OCR処理が中止されました。"
        QMessageBox.information(self, "処理終了", final_message)
        if self.ocr_worker:
            try: 
                self.ocr_worker.original_file_status_update.disconnect(self.on_original_file_status_update_from_worker)
            except (TypeError, RuntimeError): pass 
            self.ocr_worker = None
    
    def confirm_rescan_ui(self):
        self.log_manager.debug("Confirming UI rescan.", context="UI_ACTION")
        if self.is_ocr_running: QMessageBox.warning(self, "再スキャン不可", "OCR処理の実行中は再スキャンできません。"); return
        if not self.processed_files_info and not self.input_folder_path: QMessageBox.information(self, "再スキャン", "クリアまたは再スキャンする対象がありません。"); return
        if self.update_timer.isActive(): self.update_timer.stop()
        message = "入力フォルダが再スキャンされます。\n\n現在のリストと進捗状況はクリアされます。\n\nよろしいですか？";
        reply = QMessageBox.question(self, "再スキャン確認", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes: self.log_manager.info("User confirmed UI rescan.", context="UI_ACTION"); self.perform_rescan()
        else: self.log_manager.info("User cancelled UI rescan.", context="UI_ACTION")

    def perform_rescan(self):
        self.log_manager.info("Performing UI clear and input folder rescan.", context="UI_ACTION_RESCAN")
        if hasattr(self.summary_view, 'reset_summary'): 
            self.summary_view.reset_summary()
        if self.input_folder_path and os.path.isdir(self.input_folder_path):
            self.log_manager.info(f"Rescanning input folder: {self.input_folder_path}", context="UI_ACTION_RESCAN")
            self.perform_initial_scan() 
        else: 
            self.log_manager.info("Rescan: Input folder not set or invalid. File list cleared.", context="UI_ACTION_RESCAN")
            self.processed_files_info = []
            self.list_view.update_files(self.processed_files_info)
            if hasattr(self.summary_view, 'reset_summary'): self.summary_view.reset_summary()
        if self.is_ocr_running: self.is_ocr_running = False
        self.update_ocr_controls()

    def closeEvent(self, event):
        self.log_manager.debug("Application closeEvent triggered.", context="SYSTEM_LIFECYCLE");
        if self.update_timer.isActive(): self.update_timer.stop()
        if self.is_ocr_running:
            reply = QMessageBox.question(self, "処理中の終了確認", "OCR処理が実行中です。本当にアプリケーションを終了しますか？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No: event.ignore(); return
            else:
                if self.ocr_worker and self.ocr_worker.isRunning(): self.ocr_worker.stop()
        current_config_to_save = self.config.copy(); normal_geom = self.normalGeometry(); current_config_to_save["window_state"] = "maximized" if self.isMaximized() else "normal"; current_config_to_save["window_size"] = {"width": normal_geom.width(), "height": normal_geom.height()}
        if not self.isMaximized(): current_config_to_save["window_position"] = {"x": normal_geom.x(), "y": normal_geom.y()}
        elif "window_position" in current_config_to_save: del current_config_to_save["window_position"]
        current_config_to_save["last_target_dir"] = self.input_folder_path; current_config_to_save["current_view"] = self.current_view; current_config_to_save["log_visible"] = self.log_container.isVisible()
        if hasattr(self.splitter, 'sizes'): current_config_to_save["splitter_sizes"] = self.splitter.sizes()
        if hasattr(self.list_view, 'get_column_widths') and hasattr(self.list_view, 'get_sort_order'): current_config_to_save["column_widths"] = self.list_view.get_column_widths(); current_config_to_save["sort_order"] = self.list_view.get_sort_order()
        ConfigManager.save(current_config_to_save); self.log_manager.info("Settings saved. Exiting application.", context="SYSTEM_LIFECYCLE"); super().closeEvent(event)

    def clear_log_display(self):
        self.log_widget.clear()
        self.log_manager.info("画面ログをクリアしました（ファイル記録のみ）。", context="UI_ACTION_CLEAR_LOG", emit_to_ui=False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())