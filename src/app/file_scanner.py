# file_scanner.py

import os
from log_manager import LogManager
from file_model import FileInfo
from PyPDF2 import PdfReader, errors

class FileScanner:
    def __init__(self, log_manager: LogManager, config: dict):
        """
        FileScannerのコンストラクタ。

        Args:
            log_manager: LogManagerのインスタンス。
            config: アプリケーションの設定情報を含む辞書。
        """
        self.log_manager = log_manager
        self.config = config

    def scan_folder(self, input_folder_path: str):
        """
        指定された入力フォルダからサポート対象のファイルを再帰的に収集します。
        設定は self.config から取得します。

        Args:
            input_folder_path (str): スキャン対象のルートフォルダパス。

        Returns:
            tuple: (収集されたファイルパスのリスト, 最大ファイル数到達情報 or None, 深さ制限でスキップされたフォルダのリスト)
        """
        # (このメソッドは変更なし)
        if not input_folder_path or not os.path.isdir(input_folder_path):
            self.log_manager.warning(f"File collection skipped: Input folder invalid or not a directory. Path: '{input_folder_path}'", context="FILE_SCANNER")
            return [], None, []

        options_cfg = self.config.get("options", {}).get(self.config.get("api_type"), {}) # これは古い構造かもしれません
        file_actions_config = self.config.get("file_actions", {})

        max_files = options_cfg.get("max_files_to_process", 100)
        recursion_depth_limit = options_cfg.get("recursion_depth", 5)
        excluded_folder_names = [name for name in [
            file_actions_config.get("success_folder_name"),
            file_actions_config.get("failure_folder_name"),
            file_actions_config.get("results_folder_name")
        ] if name and name.strip()]

        self.log_manager.info(f"FileScanner: Collection started. In='{input_folder_path}', Max={max_files}, DepthLimit={recursion_depth_limit}, Exclude={excluded_folder_names}", context="FILE_SCANNER")

        collected_files = []
        supported_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        max_files_reached_info = None
        depth_limited_folders = set()

        for root, dirs, files in os.walk(input_folder_path, topdown=True, followlinks=False):
            norm_root = os.path.normpath(root)
            norm_input_root = os.path.normpath(input_folder_path)
            
            if norm_root == norm_input_root:
                current_depth = 0
            else:
                relative_path_from_input = os.path.relpath(norm_root, norm_input_root)
                current_depth = len(relative_path_from_input.split(os.sep))

            if current_depth >= recursion_depth_limit:
                for d_name in dirs:
                    depth_limited_folders.add(os.path.join(norm_root, d_name))
                self.log_manager.debug(f"FileScanner: Recursion depth limit ({recursion_depth_limit}) reached at '{norm_root}'. Skipping subdirectories: {dirs}", context="FILE_SCANNER_DEPTH")
                dirs[:] = []
                continue

            dirs_to_remove_from_walk = [d for d in dirs if d in excluded_folder_names]
            for d_to_remove in dirs_to_remove_from_walk:
                if d_to_remove in dirs:
                    dirs.remove(d_to_remove)

            for filename in sorted(files):
                if len(collected_files) >= max_files:
                    if max_files_reached_info is None:
                        max_files_reached_info = {
                            "limit": max_files,
                            "last_scanned_folder": norm_root
                        }
                    break
                
                file_path = os.path.join(root, filename)
                if os.path.islink(file_path):
                    continue
                if os.path.splitext(filename)[1].lower() in supported_extensions:
                    collected_files.append(file_path)
            
            if max_files_reached_info is not None:
                break
        
        unique_sorted_files = sorted(list(set(collected_files)))
        self.log_manager.info(f"FileScanner: Collection finished. Found {len(unique_sorted_files)} files.", context="FILE_SCANNER", count=len(unique_sorted_files))
        return unique_sorted_files, max_files_reached_info, list(depth_limited_folders)

    def create_initial_file_list(self, file_paths: list, ocr_status_skipped_size_limit: str, ocr_status_not_processed: str) -> list[FileInfo]:
        """
        収集されたファイルパスのリストから、処理用の初期ファイル情報リストを生成します。
        PDFファイルの場合はページ数も読み取ります。
        """
        processed_files_info: list[FileInfo] = []
        
        # self.config からアクティブプロファイルのオプション値を取得
        from config_manager import ConfigManager # ローカルインポート
        active_profile_options = ConfigManager.get_active_api_options_values(self.config)
        if active_profile_options is None:
            active_profile_options = {}

        file_actions_config = self.config.get("file_actions", {})
        upload_max_size_mb = active_profile_options.get("upload_max_size_mb", 50)
        output_format = file_actions_config.get("output_format", "both")
        
        upload_max_bytes = upload_max_size_mb * 1024 * 1024

        initial_json_status_default = "-" if output_format in ["json_only", "both"] else "作成しない(設定)"
        initial_pdf_status_default = "-" if output_format in ["pdf_only", "both"] else "作成しない(設定)"

        if file_paths:
            for i, f_path in enumerate(file_paths):
                try:
                    f_size = os.path.getsize(f_path)
                    is_skipped_by_size = f_size > upload_max_bytes
                    
                    page_count = None
                    if os.path.splitext(f_path)[1].lower() == ".pdf":
                        try:
                            with open(f_path, 'rb') as f:
                                reader = PdfReader(f)
                                page_count = len(reader.pages)
                        except errors.PdfReadError as e_pdf:
                            self.log_manager.warning(f"FileScanner: PDFファイル '{os.path.basename(f_path)}' のページ数読み取りに失敗しました (ファイル破損の可能性)。エラー: {e_pdf}", context="FILE_SCANNER_PDF_ERROR")
                        except Exception as e_generic:
                            self.log_manager.error(f"FileScanner: PDFファイル '{os.path.basename(f_path)}' の読み取り中に予期せぬエラーが発生しました。エラー: {e_generic}", context="FILE_SCANNER_PDF_ERROR", exc_info=True)


                    file_info_item = FileInfo(
                        no=i + 1,
                        path=f_path,
                        name=os.path.basename(f_path),
                        size=f_size,
                        status="スキップ(サイズ上限)" if is_skipped_by_size else "待機中",
                        ocr_engine_status=ocr_status_skipped_size_limit if is_skipped_by_size else ocr_status_not_processed,
                        ocr_result_summary=f"ファイルサイズが上限 ({upload_max_size_mb}MB) を超過" if is_skipped_by_size else "",
                        json_status="スキップ" if is_skipped_by_size else initial_json_status_default,
                        searchable_pdf_status="スキップ" if is_skipped_by_size else initial_pdf_status_default,
                        page_count=page_count,
                        is_checked=not is_skipped_by_size
                    )
                    if is_skipped_by_size:
                        self.log_manager.warning(f"FileScanner: File '{file_info_item.name}' ({f_size/(1024*1024):.2f}MB) exceeds upload limit ({upload_max_size_mb}MB). Skipped.", context="FILE_SCANNER_SIZE_LIMIT")
                    processed_files_info.append(file_info_item)
                except OSError as e:
                    self.log_manager.error(f"FileScanner: Failed to get info for file '{f_path}'. Skipped. Error: {e}", context="FILE_SCANNER_ERROR")
        
        return processed_files_info
