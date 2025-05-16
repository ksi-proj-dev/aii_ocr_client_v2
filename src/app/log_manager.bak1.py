import os
import json
import datetime

LOG_DIR = 'logs'

class LogManager:
    def __init__(self, log_widget, log_dir=LOG_DIR):
        self.log_widget = log_widget
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

    def log_message(self, message):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {"timestamp": timestamp, "message": message}
        self.log_widget.append(f"[{timestamp}] {message}")

        log_file = os.path.join(
            self.log_dir, f"info_log-{datetime.datetime.now().strftime('%Y%m%d')}.json"
        )
        with open(log_file, 'a', encoding='utf-8') as f:
            json.dump(log_entry, f, ensure_ascii=False)
            f.write("\n")
