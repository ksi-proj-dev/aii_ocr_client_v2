# config_manager.py

import os
import sys
import json
import datetime # ★ datetime をインポート
import shutil   # ★ shutil をインポート
from typing import Optional, Dict, Any, List # ★ Optional, Dict, Any, List をインポート
from appdirs import user_config_dir

CONFIG_FILE_NAME = "config.json"
APP_NAME = "AI inside OCR Client"
APP_AUTHOR = "KSI"

try:
    CONFIG_DIR = user_config_dir(appname=APP_NAME, appauthor=APP_AUTHOR, roaming=True)
    CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE_NAME)
except Exception as e:
    print(f"重大な警告: appdirs での設定パス取得に失敗しました。エラー: {e}")
    fallback_dir_name = f"{APP_AUTHOR}_{APP_NAME}_config_error_fallback".replace(" ", "_")
    try:
        CONFIG_DIR = os.path.join(os.getcwd(), fallback_dir_name)
        CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE_NAME)
        print(f"フォールバック先のパス: {CONFIG_PATH}")
    except Exception as fallback_e:
        print(f"フォールバックパスの設定も失敗しました: {fallback_e}")
        CONFIG_PATH = None; CONFIG_DIR = None

DEFAULT_API_PROFILES: List[Dict[str, Any]] = [ # ★ 型ヒントを追加
    {
        "id": "cube_fullocr",
        "name": "Cube (全文OCR)",
        "base_uri": "http://localhost/api/v1/domains/aiinside/endpoints/",
        "flow_type": "cube_fullocr_single_call", 
        "endpoints": {
            "read_document": "/fullocr-read-document",
            "make_searchable_pdf": "/make-searchable-pdf"
        },
        "options_schema": { 
            "adjust_rotation": {"type": "bool", "default": 0, "label": "回転補正を行う", "tooltip": "0=OFF, 1=ON. 90度単位および±5度程度の傾きを補正します。"},
            "character_extraction": {"type": "bool", "default": 0, "label": "文字ごとの情報を抽出する (文字尤度など)", "tooltip": "0=OFF, 1=ON. ONにすると結果JSONに1文字ずつの情報が追加されます。"},
            "concatenate": {"type": "bool", "default": 1, "label": "強制結合を行う (LLM用途推奨)", "tooltip": "0=単語区切り, 1=文章として結合. LLM用途ではONを推奨。"},
            "enable_checkbox": {"type": "bool", "default": 0, "label": "チェックボックスを認識する", "tooltip": "0=OFF, 1=ON. ONにするとチェックボックスを認識しますが処理時間が増加します。"},
            "fulltext_output_mode": {"type": "enum", "values": ["詳細情報を取得 (bbox, 表など)", "全文テキストのみ取得"], "default": 0, "label": "テキスト出力モード:", "tooltip": "0=詳細情報 (bbox, 表などを含む), 1=全文テキスト(fulltext)のみを返却。"},
            "fulltext_linebreak_char": {"type": "bool", "default": 0, "label": "全文テキストにグループ区切り文字(\\n)を付加", "tooltip": "0=区切り文字なし, 1=fulltextにもグループ区切り文字として改行(\\n)を付加。"},
            "ocr_model": {"type": "enum", "values": ["katsuji (印刷活字)", "all (手書き含む)", "mix (縦横混合モデル)"], "default": "katsuji", "label": "OCRモデル選択:", "tooltip": "OCRモデルを選択します。\n katsuji: 印刷活字\n all: 手書き文字を含む汎用\n mix: 縦書き横書き混在文書用"},
            "upload_max_size_mb": {"type": "int", "default": 60, "min": 1, "max": 200, "suffix": " MB", "label": "アップロード可能な最大ファイルサイズ:", "tooltip":"OCR対象としてアップロードするファイルサイズの上限値。\nこれを超過するファイルは処理対象外となります。"},
            "split_large_files_enabled": {"type": "bool", "default": False, "label": "大きなファイルを自動分割する (PDFのみ)", "tooltip": "上記「アップロード可能な最大ファイルサイズ」以下のPDFファイルで、\nさらに「分割サイズ」を超える場合に、ファイルをページ単位で分割してからOCR処理を行います。"},
            "split_chunk_size_mb": {"type": "int", "default": 10, "min": 1, "max":100, "suffix": " MB", "label": "分割サイズ (1ファイルあたり):", "tooltip": "自動分割を有効にした場合の、分割後の各ファイルサイズの上限の目安。\n「アップロード可能な最大ファイルサイズ」を超えない値を指定してください。"},
            "merge_split_pdf_parts": {"type": "bool", "default": True, "label": "分割した場合、サーチャブルPDF部品を1つのファイルに結合する", "tooltip": "「大きなファイルを自動分割する」が有効な場合のみ適用されます。\nオフの場合、部品ごとのサーチャブルPDFがそれぞれ出力されます。"}
        }
    }
]

class ConfigManager:
    @staticmethod
    def _ensure_config_dir_exists():
        if not CONFIG_PATH:
            print("エラー: CONFIG_PATH が設定されていないため、設定ディレクトリを作成できません。")
            return False
        try:
            config_dir_for_creation = os.path.dirname(CONFIG_PATH)
            if not os.path.exists(config_dir_for_creation):
                os.makedirs(config_dir_for_creation, exist_ok=True)
        except Exception as e:
            print(f"警告: 設定ディレクトリの作成に失敗しました: {config_dir_for_creation}, Error: {e}")
            return False
        return True

    @staticmethod
    def load() -> Dict[str, Any]: # ★ 型ヒントを追加
        if not ConfigManager._ensure_config_dir_exists():
            print("エラー: 設定ディレクトリの準備ができないため、デフォルト設定でロードします。")
            return ConfigManager._get_default_config_structure()

        user_config = {}
        if CONFIG_PATH and os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
            except json.JSONDecodeError:
                print(f"警告: {CONFIG_PATH} の読み込みに失敗しました。JSON形式が無効です。デフォルト設定でバックアップを作成し、デフォルト設定で続行します。")
                ConfigManager._backup_corrupted_config()
                user_config = ConfigManager._get_default_config_structure()
            except Exception as e:
                print(f"警告: {CONFIG_PATH} の読み込み中に予期せぬエラーが発生しました: {e}。デフォルト設定でバックアップを作成し、デフォルト設定で続行します。")
                ConfigManager._backup_corrupted_config()
                user_config = ConfigManager._get_default_config_structure()
        else: 
             user_config = ConfigManager._get_default_config_structure()
        
        ConfigManager._apply_and_migrate_default_values(user_config)
        return user_config

    @staticmethod
    def _backup_corrupted_config():
        if CONFIG_PATH and os.path.exists(CONFIG_PATH):
            try:
                backup_path = CONFIG_PATH + ".corrupted_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                shutil.copy2(CONFIG_PATH, backup_path) # ★ shutil を使用
                print(f"破損した可能性のある設定ファイルを {backup_path} にバックアップしました。")
            except Exception as e_backup:
                print(f"破損した設定ファイルのバックアップに失敗: {e_backup}")


    @staticmethod
    def _get_default_config_structure() -> Dict[str, Any]: # ★ 型ヒントを追加
        config: Dict[str, Any] = {} # ★ 型ヒントを追加
        ConfigManager._apply_and_migrate_default_values(config, force_defaults=True)
        return config

    @staticmethod
    def _apply_and_migrate_default_values(config: Dict[str, Any], force_defaults: bool = False): # ★ 型ヒントを追加
        if force_defaults or "api_profiles" not in config or not isinstance(config["api_profiles"], list) or not config["api_profiles"]:
            config["api_profiles"] = json.loads(json.dumps(DEFAULT_API_PROFILES)) 
        else:
            existing_profile_ids = {p.get("id") for p in config["api_profiles"]}
            for default_profile in DEFAULT_API_PROFILES:
                if default_profile["id"] not in existing_profile_ids:
                    config["api_profiles"].append(json.loads(json.dumps(default_profile)))
                else: 
                    cfg_profile = next((p for p in config["api_profiles"] if p.get("id") == default_profile["id"]), None)
                    if cfg_profile:
                        for key, val in default_profile.items():
                            if key not in cfg_profile:
                                cfg_profile[key] = json.loads(json.dumps(val))
                            elif key == "endpoints" and isinstance(val, dict):
                                for ep_key, ep_val in val.items():
                                     if ep_key not in cfg_profile[key]:
                                        cfg_profile[key][ep_key] = ep_val
                            elif key == "options_schema" and isinstance(val, dict):
                                for opt_key, opt_val_schema in val.items():
                                    if opt_key not in cfg_profile[key]:
                                        cfg_profile[key][opt_key] = json.loads(json.dumps(opt_val_schema))


        config.setdefault("current_api_profile_id", DEFAULT_API_PROFILES[0]["id"] if DEFAULT_API_PROFILES else "")
        
        current_profile_id = config["current_api_profile_id"]
        profile_ids = [p.get("id") for p in config.get("api_profiles", [])]
        if current_profile_id not in profile_ids and profile_ids:
            config["current_api_profile_id"] = profile_ids[0]

        config.setdefault("api_key", "") 
        config.setdefault("api_execution_mode", "demo")

        options_values_by_profile = config.setdefault("options_values_by_profile", {})
        for profile in config.get("api_profiles", []):
            profile_id_val = profile.get("id") # 変数名を変更 (current_profile_idとの衝突回避)
            if profile_id_val:
                profile_options = options_values_by_profile.setdefault(profile_id_val, {})
                if "options_schema" in profile:
                    for key, schema in profile["options_schema"].items():
                        profile_options.setdefault(key, schema.get("default"))
        
        file_actions = config.setdefault("file_actions", {})
        file_actions.setdefault("move_on_success_enabled", False)
        file_actions.setdefault("success_folder_name", "OCR成功")
        file_actions.setdefault("move_on_failure_enabled", False)
        file_actions.setdefault("failure_folder_name", "OCR失敗")
        file_actions.setdefault("collision_action", "rename")
        file_actions.setdefault("results_folder_name", "OCR結果")
        file_actions.setdefault("output_format", "both")
        
        config.setdefault("window_size", {"width": 1000, "height": 700})
        config.setdefault("window_state", "normal")
        config.setdefault("current_view", 0) 
        config.setdefault("log_visible", True)
        config.setdefault("column_widths", [35, 50, 280, 100, 270, 100, 120, 100])
        config.setdefault("sort_order", {"column": 1, "order": "asc"})
        config.setdefault("splitter_sizes", [])
        config.setdefault("last_target_dir", "")
        
    @staticmethod
    def save(config: Dict[str, Any]): # ★ 型ヒントを追加
        if not ConfigManager._ensure_config_dir_exists():
            print("エラー: 設定ディレクトリの準備ができないため、設定を保存できません。")
            return
        if not CONFIG_PATH:
            print("エラー: CONFIG_PATH が無効なため、設定を保存できません。")
            return
        
        config_to_save = json.loads(json.dumps(config)) 

        current_profile_id_to_save = config_to_save.get("current_api_profile_id") # 変数名を変更
        available_profile_ids = [p.get("id") for p in config_to_save.get("api_profiles", [])]
        if current_profile_id_to_save not in available_profile_ids and available_profile_ids:
            config_to_save["current_api_profile_id"] = available_profile_ids[0]

        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"エラー: 設定ファイル {CONFIG_PATH} の保存に失敗しました。理由: {e}")

    @staticmethod
    def get_api_profile(config: dict, profile_id: str) -> Optional[Dict[str, Any]]:
        for profile in config.get("api_profiles", []):
            if profile.get("id") == profile_id:
                return profile
        return None

    @staticmethod
    def get_active_api_profile(config: dict) -> Optional[Dict[str, Any]]:
        profile_id = config.get("current_api_profile_id")
        if profile_id:
            return ConfigManager.get_api_profile(config, profile_id)
        elif config.get("api_profiles"): 
            return config["api_profiles"][0]
        return None

    @staticmethod
    def get_active_api_options_schema(config: dict) -> Optional[Dict[str, Any]]:
        active_profile = ConfigManager.get_active_api_profile(config)
        if active_profile:
            return active_profile.get("options_schema")
        return None

    @staticmethod
    def get_active_api_options_values(config: dict) -> Optional[Dict[str, Any]]:
        active_profile_id = config.get("current_api_profile_id")
        if active_profile_id:
            return config.get("options_values_by_profile", {}).get(active_profile_id)
        return None