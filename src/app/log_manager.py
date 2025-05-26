import os
import json
import datetime
from PyQt6.QtCore import QObject, pyqtSignal

LOG_DIR = 'logs'

class LogLevel:
    INFO = "INFO"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
    WARNING = "WARNING"

class LogManager(QObject):
    log_message_signal = pyqtSignal(str, str) # level, message

    def __init__(self, log_dir=LOG_DIR):
        super().__init__()
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.current_log_file_path = ""
        self._update_log_file_path()

    def _update_log_file_path(self):
        today_str = datetime.datetime.now().strftime('%Y%m%d')
        new_log_file_path = os.path.join(self.log_dir, f"app_log-{today_str}.jsonl")
        if self.current_log_file_path != new_log_file_path:
            old_file = self.current_log_file_path
            self.current_log_file_path = new_log_file_path
            if old_file:
                self._write_log_entry_internal( # ログローテーションメッセージはUIに通知しない
                    {"event": "LOG_ROTATE", "message": f"ログファイルを {os.path.basename(self.current_log_file_path)} に切り替え。"},
                    LogLevel.INFO, "SYSTEM_LOG", emit_to_ui=False # emit_to_ui=False を使用
                )
        return self.current_log_file_path

    # --- ここから変更 ---
    def _write_log_entry_internal(self, log_data_dict, level, context, emit_to_ui=True):
    # --- ここまで変更 ---
        timestamp = datetime.datetime.now().isoformat()
        log_file_path = self._update_log_file_path()

        log_entry_for_file = {
            "timestamp": timestamp, "level": level, "context": context, **log_data_dict
        }
        
        main_message = log_data_dict.get('message', json.dumps(log_data_dict, ensure_ascii=False))
        ui_message_formatted = f"[{timestamp.split('T')[1].split('.')[0]}] [{level}] [{context}] {main_message}"

        try:
            with open(log_file_path, 'a', encoding='utf-8') as f:
                json.dump(log_entry_for_file, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            error_ui_message = f"[{timestamp.split('T')[1].split('.')[0]}] [ERROR] [LOGGING_ERROR] ログファイル書込エラー: {e}"
            print(error_ui_message)
            # --- ここから変更 ---
            if emit_to_ui: # ファイル書き込みエラーもUI通知を制御
                self.log_message_signal.emit(LogLevel.ERROR, error_ui_message)
            # --- ここまで変更 ---

        # --- ここから変更 ---
        if emit_to_ui: # emit_to_ui フラグに基づいてシグナルを発行
            self.log_message_signal.emit(level, ui_message_formatted)
        # --- ここまで変更 ---

    # --- 各ログメソッドに emit_to_ui 引数を追加 ---
    def info(self, message, context="APP", emit_to_ui=True, **kwargs):
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.INFO, context, emit_to_ui=emit_to_ui)

    def error(self, message, context="APP", error_code=None, exception_info=None, emit_to_ui=True, **kwargs):
        log_data = {"message": message, **kwargs}
        if error_code: log_data["error_code"] = error_code
        if exception_info: log_data["exception"] = str(exception_info)
        self._write_log_entry_internal(log_data, LogLevel.ERROR, context, emit_to_ui=emit_to_ui)

    def warning(self, message, context="APP", emit_to_ui=True, **kwargs):
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.WARNING, context, emit_to_ui=emit_to_ui)

    def debug(self, message, context="APP", emit_to_ui=True, **kwargs): # デバッグログもUI表示制御可能に
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.DEBUG, context, emit_to_ui=emit_to_ui)