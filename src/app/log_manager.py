import os
import json
import datetime
from PyQt6.QtCore import QObject, pyqtSignal # QObjectとpyqtSignalをインポート

LOG_DIR = 'logs'

class LogLevel:
    INFO = "INFO"
    ERROR = "ERROR"
    DEBUG = "DEBUG" # DEBUGレベル自体は定義されている
    WARNING = "WARNING"

class LogManager(QObject): # QObjectを継承
    # シグナルを定義: 第1引数: ログレベル(str), 第2引数: UI用メッセージ(str)
    log_message_signal = pyqtSignal(str, str)

    def __init__(self, log_dir=LOG_DIR): # log_widget はコンストラクタから削除
        super().__init__() # QObjectのコンストラクタを呼び出す
        # self.log_widget = None # UIウィジェットへの直接参照は削除
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.current_log_file_path = ""
        self._update_log_file_path()

    # log_widget を設定するためのメソッドは削除（シグナル経由にするため）
    # def set_log_widget(self, log_widget):
    #     self.log_widget = log_widget

    def _update_log_file_path(self):
        today_str = datetime.datetime.now().strftime('%Y%m%d')
        new_log_file_path = os.path.join(self.log_dir, f"app_log-{today_str}.jsonl")
        if self.current_log_file_path != new_log_file_path:
            old_file = self.current_log_file_path
            self.current_log_file_path = new_log_file_path
            if old_file:
                # ログローテーションのメッセージもシグナル経由で出すか、ファイルのみにするか検討
                # ここではファイルのみへの記録とし、UIへの直接出力は避ける
                self._write_log_entry_internal(
                    {"event": "LOG_ROTATE", "message": f"ログファイルを {os.path.basename(self.current_log_file_path)} に切り替え。"},
                    LogLevel.INFO, "SYSTEM_LOG", emit_signal=False # ローテーションメッセージはUIに出さないオプション
                )
        return self.current_log_file_path

    def _write_log_entry_internal(self, log_data_dict, level, context, emit_signal=True): # emit_signal引数を追加
        timestamp = datetime.datetime.now().isoformat()
        log_file_path = self._update_log_file_path()

        log_entry_for_file = {
            "timestamp": timestamp, "level": level, "context": context, **log_data_dict
        }
        
        main_message = log_data_dict.get('message', json.dumps(log_data_dict, ensure_ascii=False))
        # UI用メッセージのフォーマットはここで決定
        ui_message_formatted = f"[{timestamp.split('T')[1].split('.')[0]}] [{level}] [{context}] {main_message}"

        try:
            with open(log_file_path, 'a', encoding='utf-8') as f:
                json.dump(log_entry_for_file, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            # ファイル書き込みエラーはコンソールに出力し、可能ならUIにもエラーとして通知
            error_ui_message = f"[{timestamp.split('T')[1].split('.')[0]}] [ERROR] [LOGGING_ERROR] ログファイル書込エラー: {e}"
            print(error_ui_message) # コンソールには必ず出す
            if emit_signal: # UIへの通知も試みる
                self.log_message_signal.emit(LogLevel.ERROR, error_ui_message)

        # --- UIウィジェットへの直接appendを削除し、代わりにシグナルを発行 ---
        if emit_signal:
            self.log_message_signal.emit(level, ui_message_formatted)

    def info(self, message, context="APP", **kwargs):
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.INFO, context)

    def error(self, message, context="APP", error_code=None, exception_info=None, **kwargs):
        log_data = {"message": message, **kwargs}
        if error_code: log_data["error_code"] = error_code
        if exception_info: log_data["exception"] = str(exception_info) # 例外情報を文字列に
        self._write_log_entry_internal(log_data, LogLevel.ERROR, context)

    def warning(self, message, context="APP", **kwargs):
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.WARNING, context)

    def debug(self, message, context="APP", **kwargs):
        # debugログは、ファイルにはDEBUGレベルで記録し、UIにはDEBUG_コンテキストでINFOとして送るか、
        # または、DEBUGレベルのまま送り、UI側で表示を制御するか。
        # ここでは、ファイルにはDEBUGとして記録し、シグナルもDEBUGレベルで送るように変更検討。
        # ただし、現状のINFOとして送る動作（コンテキストにDEBUG_が付く）を維持する場合は以下。
        # self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.INFO, f"DEBUG_{context}")
        
        # より良いのは、DEBUGレベルをそのまま渡すこと
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.DEBUG, context)