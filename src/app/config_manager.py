import os
import json

CONFIG_PATH = os.path.join('config', 'config.json')

INTERNAL_CONFIG = {
    "api_type": "cube_fullocr",
    "endpoints": {
        "cube_fullocr": {
            "read_document": "/fullocr-read-document",
            "make_searchable_pdf": "/make-searchable-pdf"
        }
    }
}

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                try:
                    user_config = json.load(f)
                except json.JSONDecodeError:
                    user_config = {}
                    print(f"警告: {CONFIG_PATH} の読み込みに失敗しました。JSON形式が無効です。デフォルト設定で続行します。")
        else:
            user_config = {}

        # INTERNAL_CONFIG の api_type と endpoints は常に強制適用
        user_config["api_type"] = INTERNAL_CONFIG["api_type"]
        user_config["endpoints"] = INTERNAL_CONFIG["endpoints"]

        # オプションとファイルアクションのデフォルト構造を保証
        current_api_type = user_config["api_type"]
        user_config.setdefault("options", {}).setdefault(current_api_type, {
            "max_files_to_process": 100,
            "recursion_depth": 5,
            "adjust_rotation": 0,
            "character_extraction": 0,
            "concatenate": 1,
            "enable_checkbox": 0,
            "fulltext_output_mode": 0,
            "fulltext_linebreak_char": 0,
            "ocr_model": "katsuji"
        })
        user_config.setdefault("file_actions", {
            "move_on_success_enabled": False,
            "success_folder": "OCR成功",
            "move_on_failure_enabled": False,
            "failure_folder": "OCR失敗",
            "collision_action": "rename"
        })
        return user_config

    @staticmethod
    def save(config):
        # 保存前に、api_type と endpoints が INTERNAL_CONFIG の値であることを再度保証
        config["api_type"] = INTERNAL_CONFIG["api_type"]
        config["endpoints"] = INTERNAL_CONFIG["endpoints"]

        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
