import os
import json
from appdirs import user_config_dir

# --- CONFIG_PATH の決定 ---
CONFIG_FILE_NAME = "config.json"
APP_NAME = "AIInside CubeClient"  # スペースを含む新しいアプリケーション名
APP_AUTHOR = "KSInternational"     # 新しい開発者名

# 常に Roaming 以下に保存
try:
    CONFIG_DIR = user_config_dir(appname=APP_NAME, appauthor=APP_AUTHOR, roaming=True)
    CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE_NAME)
except Exception as e:
    print(f"重大な警告: appdirs での設定パス取得に失敗しました。エラー: {e}")
    print(f"フォールバックとして現在の作業ディレクトリ直下に '{APP_AUTHOR}_{APP_NAME}_config_fallback' フォルダを作成しようと試みます。")
    fallback_dir_name = f"{APP_AUTHOR}_{APP_NAME}_config_error_fallback".replace(" ", "_") # スペースをアンダースコアに置換
    try:
        CONFIG_DIR = os.path.join(os.getcwd(), fallback_dir_name)
        CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE_NAME)
        print(f"フォールバック先のパス: {CONFIG_PATH}")
    except Exception as fallback_e:
        print(f"フォールバックパスの設定も失敗しました: {fallback_e}")
        CONFIG_PATH = None
        CONFIG_DIR = None

# API種別とエンドポイントは内部で固定
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
    def _ensure_config_dir_exists():
        """設定ディレクトリが存在しない場合に作成するヘルパーメソッド"""
        if not CONFIG_PATH: # CONFIG_PATH が None (フォールバックも失敗した場合など) なら何もしない
            print("エラー: CONFIG_PATH が設定されていないため、設定ディレクトリを作成できません。")
            return False
        try:
            config_dir_for_creation = os.path.dirname(CONFIG_PATH)
            if not os.path.exists(config_dir_for_creation):
                os.makedirs(config_dir_for_creation, exist_ok=True)
                # print(f"情報: 設定ディレクトリを作成しました: {config_dir_for_creation}")
        except Exception as e:
            print(f"警告: 設定ディレクトリの作成に失敗しました: {config_dir_for_creation}, Error: {e}")
            return False
        return True

    @staticmethod
    def load():
        if not ConfigManager._ensure_config_dir_exists():
            print("エラー: 設定ディレクトリの準備ができないため、デフォルト設定でロードします。")
            # 最低限の内部設定と必須デフォルトでフォールバック
            config = INTERNAL_CONFIG.copy()
            config.setdefault("options", {}).setdefault(config["api_type"], {})
            config.setdefault("file_actions", {})
            ConfigManager._apply_default_values(config) # デフォルト値適用ヘルパーを呼ぶ
            return config

        user_config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                try:
                    user_config = json.load(f)
                except json.JSONDecodeError:
                    print(f"警告: {CONFIG_PATH} の読み込みに失敗しました。JSON形式が無効です。デフォルト設定で続行します。")
        
        # デフォルト値の適用と不要キーの整理
        ConfigManager._apply_default_values(user_config)
        
        return user_config

    @staticmethod
    def _apply_default_values(config):
        """設定オブジェクトにデフォルト値を適用し、不要なキーを削除するヘルパー"""
        # 基本設定
        config.setdefault("api_key", "")
        config.setdefault("base_uri", "http://localhost/api/v1/domains/aiinside/endpoints/")

        # API種別とエンドポイントは常にINTERNAL_CONFIGで上書き
        config["api_type"] = INTERNAL_CONFIG["api_type"]
        config["endpoints"] = INTERNAL_CONFIG["endpoints"]

        # OCRオプション
        current_api_type = config["api_type"]
        options_for_current_api = config.setdefault("options", {}).setdefault(current_api_type, {})
        options_for_current_api.setdefault("max_files_to_process", 100)
        options_for_current_api.setdefault("recursion_depth", 5)
        options_for_current_api.setdefault("adjust_rotation", 0)
        options_for_current_api.setdefault("character_extraction", 0)
        options_for_current_api.setdefault("concatenate", 1)
        options_for_current_api.setdefault("enable_checkbox", 0)
        options_for_current_api.setdefault("fulltext_output_mode", 0)
        options_for_current_api.setdefault("fulltext_linebreak_char", 0)
        options_for_current_api.setdefault("ocr_model", "katsuji")

        # ファイルアクション (サブフォルダ名を設定)
        file_actions = config.setdefault("file_actions", {})
        file_actions.setdefault("move_on_success_enabled", False)
        file_actions.setdefault("success_folder_name", "OCR成功")
        file_actions.setdefault("move_on_failure_enabled", False)
        file_actions.setdefault("failure_folder_name", "OCR失敗")
        file_actions.setdefault("collision_action", "rename")
        file_actions.setdefault("results_folder_name", "OCR結果")

        # UI関連
        config.setdefault("window_size", {"width": 1000, "height": 700})
        config.setdefault("window_state", "normal")
        config.setdefault("current_view", 0)
        config.setdefault("log_visible", True)
        config.setdefault("column_widths", [40, 250, 100, 300, 120, 100])
        config.setdefault("sort_order", {"column": 0, "order": "asc"})
        config.setdefault("splitter_sizes", []) # MainWindowで初期値を設定する方が良い場合もある

        # 最後に使用した入力フォルダ
        config.setdefault("last_target_dir", "")
        
        # 不要になったキーの削除
        keys_to_remove = [
            "target_dir", "result_dir", "last_result_dir",
            "last_success_move_dir", "last_failure_move_dir",
            "upload_interval_ms", "upload_retry_limit", "retry_timeout_sec",
            "retry_interval_ms", "retry_count_max", "last_view"
        ]
        for key in keys_to_remove:
            if key in config:
                del config[key]

    @staticmethod
    def save(config):
        if not ConfigManager._ensure_config_dir_exists():
            print("エラー: 設定ディレクトリの準備ができないため、設定を保存できません。")
            return

        # 保存前に、api_type と endpoints が INTERNAL_CONFIG の値であることを再度保証
        config_to_save = config.copy() # 元のオブジェクトを変更しないためにコピー
        config_to_save["api_type"] = INTERNAL_CONFIG["api_type"]
        config_to_save["endpoints"] = INTERNAL_CONFIG["endpoints"]

        # 保存したくない一時的な情報や、load時に整理されるべき不要なキーを再度確認して削除
        # (通常は_apply_default_valuesで整理されているはずだが、念のため)
        keys_to_remove_before_save = [
            "last_result_dir", "last_success_move_dir", "last_failure_move_dir",
            "target_dir", "result_dir", "upload_interval_ms", "upload_retry_limit",
            "retry_timeout_sec", "retry_interval_ms", "retry_count_max", "last_view"
        ]
        for key in keys_to_remove_before_save:
            if key in config_to_save:
                del config_to_save[key]
        
        if not CONFIG_PATH: # CONFIG_PATHが設定できなかった場合は保存しない
            print("エラー: CONFIG_PATH が無効なため、設定を保存できません。")
            return
            
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"エラー: 設定ファイル {CONFIG_PATH} の保存に失敗しました。理由: {e}")