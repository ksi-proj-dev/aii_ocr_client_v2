import os
import json
import datetime

LOG_DIR = 'logs'

class LogLevel:
    INFO = "INFO"
    ERROR = "ERROR"
    DEBUG = "DEBUG"
    WARNING = "WARNING" # WARNINGレベルを追加

class LogManager:
    def __init__(self, log_widget, log_dir=LOG_DIR):
        self.log_widget = log_widget
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.current_log_file_path = "" # 変更: パス全体を保持
        self._update_log_file_path() # 初期ファイルパス設定

    def _update_log_file_path(self):
        """日毎のログファイルパスを生成・更新する"""
        today_str = datetime.datetime.now().strftime('%Y%m%d')
        new_log_file_path = os.path.join(self.log_dir, f"app_log-{today_str}.jsonl")
        if self.current_log_file_path != new_log_file_path:
            old_file = self.current_log_file_path
            self.current_log_file_path = new_log_file_path
            if old_file: # 初回起動時以外
                self._write_log_entry_internal({"event": "LOG_ROTATE", "message": f"ログファイルを {os.path.basename(self.current_log_file_path)} に切り替え。"}, LogLevel.INFO, "SYSTEM_LOG")
        return self.current_log_file_path

    def _write_log_entry_internal(self, log_data_dict, level, context):
        """整形されたログデータをファイルに書き込む内部メソッド (引数を辞書に)"""
        timestamp = datetime.datetime.now().isoformat()
        log_file_path = self._update_log_file_path() # 呼び出しごとに最新のファイルパスを確認・更新

        log_entry_for_file = {
            "timestamp": timestamp, "level": level, "context": context, **log_data_dict
        }
        
        # UI用メッセージ (messageキーがあればそれ、なければ全データをJSON化)
        main_message = log_data_dict.get('message', json.dumps(log_data_dict, ensure_ascii=False))
        ui_message = f"[{timestamp.split('T')[1].split('.')[0]}] [{level}] [{context}] {main_message}"


        try:
            with open(log_file_path, 'a', encoding='utf-8') as f:
                json.dump(log_entry_for_file, f, ensure_ascii=False)
                f.write("\n")
        except Exception as e:
            error_ui_message = f"[{timestamp.split('T')[1].split('.')[0]}] [ERROR] [LOGGING_ERROR] ログファイル書込エラー: {e}"
            if self.log_widget: self.log_widget.append(f'<font color="red">{error_ui_message}</font>')
            print(error_ui_message)

        if self.log_widget:
            if level == LogLevel.ERROR: self.log_widget.append(f'<font color="red">{ui_message}</font>')
            elif level == LogLevel.WARNING: self.log_widget.append(f'<font color="orange">{ui_message}</font>')
            elif level == LogLevel.DEBUG: self.log_widget.append(f'<font color="gray">{ui_message}</font>')
            else: self.log_widget.append(ui_message) # INFO
            self.log_widget.ensureCursorVisible()

    def info(self, message, context="APP", **kwargs):
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.INFO, context)

    def error(self, message, context="APP", error_code=None, exception_info=None, **kwargs):
        log_data = {"message": message, **kwargs}
        if error_code: log_data["error_code"] = error_code
        if exception_info: log_data["exception"] = str(exception_info)
        self._write_log_entry_internal(log_data, LogLevel.ERROR, context)

    def warning(self, message, context="APP", **kwargs): # WARNINGレベルメソッド追加
        self._write_log_entry_internal({"message": message, **kwargs}, LogLevel.WARNING, context)

    def debug(self, message, context="APP", **kwargs):
        self.info(message, context=f"DEBUG_{context}", **kwargs) # DEBUGはINFOとして記録 (ファイルには残る)
        # または、特定の条件下でのみファイルに書き出すなど、動作を調整可能