# file_scanner.py

import os
from log_manager import LogManager
from file_model import FileInfo
# from config_manager import ConfigManager # 型ヒントや構造参照以外では不要になる

class FileScanner:
    def __init__(self, log_manager: LogManager, config: dict): # ★ config を引数に追加
        """
        FileScannerのコンストラクタ。

        Args:
            log_manager: LogManagerのインスタンス。
            config: アプリケーションの設定情報を含む辞書。
        """
        self.log_manager = log_manager
        self.config = config # ★ 受け取ったconfigを保持

    def scan_folder(self, input_folder_path: str): # ★ 引数から設定値を削除
        """
        指定された入力フォルダからサポート対象のファイルを再帰的に収集します。
        設定は self.config から取得します。

        Args:
            input_folder_path (str): スキャン対象のルートフォルダパス。

        Returns:
            tuple: (収集されたファイルパスのリスト, 最大ファイル数到達情報 or None, 深さ制限でスキップされたフォルダのリスト)
        """
        if not input_folder_path or not os.path.isdir(input_folder_path):
            self.log_manager.warning(f"File collection skipped: Input folder invalid or not a directory. Path: '{input_folder_path}'", context="FILE_SCANNER")
            return [], None, []

        # ★ self.config から設定値を取得
        file_actions_config = self.config.get("file_actions", {})
        options_cfg = self.config.get("options", {}).get(self.config.get("api_type"), {})

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

    def create_initial_file_list(self, file_paths: list, ocr_status_skipped_size_limit: str, ocr_status_not_processed: str) -> list[FileInfo]: # ★ 引数から設定値を削除
        """
        収集されたファイルパスのリストから、処理用の初期ファイル情報リストを生成します。
        FileInfoオブジェクトのリストを返します。設定は self.config から取得します。
        """
        processed_files_info: list[FileInfo] = []
        
        # ★ self.config から設定値を取得
        options_cfg = self.config.get("options", {}).get(self.config.get("api_type"), {})
        file_actions_config = self.config.get("file_actions", {})
        upload_max_size_mb = options_cfg.get("upload_max_size_mb", 50)
        output_format = file_actions_config.get("output_format", "both")
        
        upload_max_bytes = upload_max_size_mb * 1024 * 1024

        initial_json_status_default = "作成しない(設定)"
        if output_format == "json_only" or output_format == "both":
            initial_json_status_default = "-"
        initial_pdf_status_default = "作成しない(設定)"
        if output_format == "pdf_only" or output_format == "both":
            initial_pdf_status_default = "-"

        if file_paths:
            for i, f_path in enumerate(file_paths):
                try:
                    f_size = os.path.getsize(f_path)
                    is_skipped_by_size = f_size > upload_max_bytes
                    
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
                        is_checked=not is_skipped_by_size
                    )
                    if is_skipped_by_size:
                        self.log_manager.warning(f"FileScanner: File '{file_info_item.name}' ({f_size/(1024*1024):.2f}MB) exceeds upload limit ({upload_max_size_mb}MB). Skipped.", context="FILE_SCANNER_SIZE_LIMIT")
                    processed_files_info.append(file_info_item)
                except OSError as e:
                    self.log_manager.error(f"FileScanner: Failed to get info for file '{f_path}'. Skipped. Error: {e}", context="FILE_SCANNER_ERROR")
        
        return processed_files_info