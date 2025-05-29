import os
import json
import datetime
from PyQt6.QtCore import QObject, pyqtSignal
from appdirs import user_log_dir
from config_manager import APP_NAME, APP_AUTHOR # インポート

# --- ログディレクトリの決定 ---
# (変更なし)
try:
    LOG_DIR_PATH = user_log_dir(appname=APP_NAME, appauthor=APP_AUTHOR)
except Exception as e:
    print(f"重大な警告: appdirs でのログディレクトリパス取得に失敗しました。エラー: {e}")
    fallback_dir_name = f"{APP_AUTHOR}_{APP_NAME}_logs_error_fallback".replace(" ", "_")
    try:
        LOG_DIR_PATH = os.path.join(os.getcwd(), fallback_dir_name)
        print(f"フォールバック先のログディレクトリパス: {LOG_DIR_PATH}")
    except Exception as fallback_e:
        print(f"フォールバックログディレクトリパスの設定も失敗しました: {fallback_e}")
        LOG_DIR_PATH = os.path.join(os.getcwd(), "logs_fallback_critical")


class LogLevel:
    INFO = "INFO"; ERROR = "ERROR"; DEBUG = "DEBUG"; WARNING = "WARNING"

class LogManager(QObject):
    log_message_signal = pyqtSignal(str, str)

    def __init__(self, log_dir_override=None):
        # (変更なし)
        super().__init__()
        if log_dir_override: self.log_dir = log_dir_override
        else: self.log_dir = LOG_DIR_PATH
        try:
            if self.log_dir and not os.path.exists(self.log_dir):
                os.makedirs(self.log_dir, exist_ok=True)
        except Exception as e: print(f"警告: ログディレクトリの作成に失敗しました: {self.log_dir}, Error: {e}")
        self.current_log_file_path = ""; self._update_log_file_path()

    def _update_log_file_path(self):
        # (変更なし)
        today_str = datetime.datetime.now().strftime('%Y%m%d')
        if not self.log_dir: print("エラー: ログディレクトリが未設定のため、ログファイルパスを更新できません。"); return self.current_log_file_path
        new_log_file_path = os.path.join(self.log_dir, f"app_log-{today_str}.jsonl")
        if self.current_log_file_path != new_log_file_path:
            old_file = self.current_log_file_path; self.current_log_file_path = new_log_file_path
            if old_file: self._write_log_entry_internal({"event": "LOG_ROTATE", "message": f"ログファイルを {os.path.basename(self.current_log_file_path)} に切り替え。"}, LogLevel.INFO, "SYSTEM_LOG", emit_to_ui=False)
        return self.current_log_file_path

# class LogManager(QObject):
# ... (他のメソッドは変更なし) ...

    def _write_log_entry_internal(self, log_data_dict, level, context, emit_to_ui=True):
        timestamp = datetime.datetime.now().isoformat()
        log_file_path = self._update_log_file_path()

        if not log_file_path:
            print(f"警告: ログファイルパスが無効なため、ログエントリーを書き込めません: Level={level}, Context={context}, Msg={log_data_dict.get('message')}")
            if emit_to_ui:
                main_message_for_ui = log_data_dict.get('message', json.dumps(log_data_dict, ensure_ascii=False))
                ui_msg_fmt_for_ui = f"[{timestamp.split('T')[1].split('.')[0]}] [{level}] [{context}] {main_message_for_ui}"
                self.log_message_signal.emit(level, ui_msg_fmt_for_ui)
            return

        log_entry_for_file = {"timestamp": timestamp, "level": level, "context": context, **log_data_dict}
        main_message = log_data_dict.get('message', json.dumps(log_data_dict, ensure_ascii=False))
        ui_message_formatted = f"[{timestamp.split('T')[1].split('.')[0]}] [{level}] [{context}] {main_message}"

        file_write_error = None # ファイル書き込みエラー情報を保持する変数
        try:
            with open(log_file_path, 'a', encoding='utf-8') as f:
                json.dump(log_entry_for_file, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            file_write_error = e # エラー情報を保持
            error_ui_message_for_file_io = f"[{timestamp.split('T')[1].split('.')[0]}] [ERROR] [LOGGING_ERROR] ログファイル書込エラー: {e} (Path: {log_file_path})"
            print(error_ui_message_for_file_io) # コンソールには必ず出す
            if emit_to_ui: # UIへの通知も試みる
                self.log_message_signal.emit(LogLevel.ERROR, error_ui_message_for_file_io)

        # UIウィジェットへのメッセージ送信
        if emit_to_ui and not file_write_error: # ファイル書き込みエラーがなかった場合に通常のログをemit
            self.log_message_signal.emit(level, ui_message_formatted)
        # elif emit_to_ui and file_write_error:
            # ファイル書き込みエラーがあった場合、エラーメッセージは既にemitされているので、
            # 通常のログメッセージを重ねてemitするかどうかは設計次第。
            # 現状はエラーメッセージのみemitされる。
            # もし通常メッセージも（エラーがあったことを示す形で）出したいならここに追加。
            # self.log_message_signal.emit(level, f"[FILE_WRITE_ERROR] {ui_message_formatted}")
            pass

    def info(self, message, context="APP", emit_to_ui=True, **kwargs):
        # (変更なし)
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.INFO, context, emit_to_ui=emit_to_ui)

    def error(self, message, context="APP", error_code=None, exception_info=None, emit_to_ui=True, **kwargs):
        log_data = {"message": message, **kwargs} # --- ここの行末のセミコロンを削除 ---
        if error_code:
            log_data["error_code"] = error_code
        if exception_info:
            log_data["exception"] = str(exception_info)
        self._write_log_entry_internal(log_data, LogLevel.ERROR, context, emit_to_ui=emit_to_ui)

    def warning(self, message, context="APP", emit_to_ui=True, **kwargs):
        # (変更なし)
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.WARNING, context, emit_to_ui=emit_to_ui)

    def debug(self, message, context="APP", emit_to_ui=True, **kwargs):
        # (変更なし)
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.DEBUG, context, emit_to_ui=emit_to_ui)