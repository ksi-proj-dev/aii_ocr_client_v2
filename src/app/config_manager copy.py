# config_manager.py

import os
import sys
import json
import datetime
import shutil
from typing import Optional, Dict, Any, List
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

DEFAULT_API_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "cube_fullocr_v1",
        "name": "Cube (全文OCR V1)",
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
    },
    {
        "id": "dx_fulltext_v2",
        "name": "DX Suite (全文OCR V2)",
        "base_uri": "https://{organization_specific_domain}.dx-suite.com/wf/api/fullocr/v2/",
        "flow_type": "dx_fulltext_v2_flow",
        "endpoints": {
            "register_ocr": "/register",
            "get_ocr_result": "/getOcrResult",
            "delete_ocr": "/delete", # 仕様書に基づき追加
            "register_searchable_pdf": "/searchablepdf/register",
            "get_searchable_pdf_result": "/searchablepdf/getResult"
        },
        "options_schema": {
            "concatenate": {"type": "bool", "default": 0, "label": "結合オプション (DX Suite)", "tooltip": "0: OFF, 1: ON. デフォルトはOFF. 文字列の間隔が対象の文字幅よりも小さい場合に結合します。"},
            "characterExtraction": {"type": "bool", "default": 0, "label": "文字抽出オプション (DX Suite)", "tooltip": "0: OFF, 1: ON. デフォルトはOFF. 1文字ずつの検出結果を出力に追加します。"},
            "tableExtraction": {"type": "bool", "default": 1, "label": "表抽出オプション (DX Suite)", "tooltip": "0: OFF, 1: ON. デフォルトはON. 検出した表データを出力に追加します。"},
            "highResolutionMode": {"type": "bool", "default": 0, "label": "高解像度オプション (サーチャブルPDF, DX Suite)", "tooltip": "0: OFF (低解像度), 1: ON (高解像度). デフォルトはOFF."},
            "upload_max_size_mb": {"type": "int", "default": 20, "min": 1, "max": 20, "suffix": " MB", "label": "アップロード可能な最大ファイルサイズ:", "tooltip":"DX Suite 全文読取APIのファイルサイズ上限 (20MB)。"},
            # "departmentId": {"type": "string", "default": "", "label": "部署ID (DX Suite, 任意)", "tooltip": "DX Suiteの部署IDを数字で指定します。"},
            # ★ここからファイル分割オプションを追加
            "split_large_files_enabled": {"type": "bool", "default": False, "label": "大きなファイルを自動分割する (PDFのみ, DX Suite)", "tooltip": "「アップロード可能な最大ファイルサイズ」(現在20MB) を超過するPDFファイルを、\n「分割サイズ」を目安にページ単位で分割してからOCR処理を行います。"},
            "split_chunk_size_mb": {"type": "int", "default": 10, "min": 1, "max": 20, "suffix": " MB", "label": "分割サイズ目安 (1ファイルあたり, DX Suite):", "tooltip": "自動分割を有効にした場合の、分割後の各ファイルサイズの上限の目安。\n「アップロード可能な最大ファイルサイズ」(現在20MB) を超えない値を指定してください。"},
            "merge_split_pdf_parts": {"type": "bool", "default": True, "label": "分割した場合、サーチャブルPDF部品を1つのファイルに結合する (DX Suite)", "tooltip": "「大きなファイルを自動分割する」が有効な場合のみ適用されます。\nオフの場合、部品ごとのサーチャブルPDFがそれぞれ出力されます。"}
            # ★ここまでファイル分割オプション
        }
    },
    {
        "id": "dx_atypical_v2",
        "name": "DX Suite (非定型OCR V2)",
        "base_uri": "http://localhost/dxsuite/api/v2/", # 仮
        "flow_type": "dx_atypical_v2_flow", # 仮
        "endpoints": {}, # 仮
        "options_schema": {} # 仮
    },
    {
        "id": "dx_standard_v2",
        "name": "DX Suite (標準OCR V2)",
        "base_uri": "http://localhost/dxsuite/api/v2/", # 仮
        "flow_type": "dx_standard_v2_flow", # 仮
        "endpoints": {}, # 仮
        "options_schema": {} # 仮
    }
]

class ConfigManager:
    @staticmethod
    def _ensure_config_dir_exists():
        if not CONFIG_PATH:
            #print("エラー: CONFIG_PATH が設定されていないため、設定ディレクトリを作成できません。") # LogManagerが使える前なのでprint
            return False
        try:
            config_dir_for_creation = os.path.dirname(CONFIG_PATH)
            if not os.path.exists(config_dir_for_creation):
                os.makedirs(config_dir_for_creation, exist_ok=True)
        except Exception as e:
            #print(f"警告: 設定ディレクトリの作成に失敗しました: {config_dir_for_creation}, Error: {e}")
            return False
        return True

    @staticmethod
    def load() -> Dict[str, Any]:
        if not ConfigManager._ensure_config_dir_exists():
            #print("エラー: 設定ディレクトリの準備ができないため、デフォルト設定でロードします。")
            return ConfigManager._get_default_config_structure()

        user_config = {}
        if CONFIG_PATH and os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
            except json.JSONDecodeError:
                #print(f"警告: {CONFIG_PATH} の読み込みに失敗しました。JSON形式が無効です。デフォルト設定でバックアップを作成し、デフォルト設定で続行します。")
                ConfigManager._backup_corrupted_config()
                user_config = ConfigManager._get_default_config_structure()
            except Exception as e:
                #print(f"警告: {CONFIG_PATH} の読み込み中に予期せぬエラーが発生しました: {e}。デフォルト設定でバックアップを作成し、デフォルト設定で続行します。")
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
                shutil.copy2(CONFIG_PATH, backup_path)
                #print(f"破損した可能性のある設定ファイルを {backup_path} にバックアップしました。")
            except Exception as e_backup:
                #print(f"破損した設定ファイルのバックアップに失敗: {e_backup}")
                pass # エラー時は何もしない（printのみ）

    @staticmethod
    def _get_default_config_structure() -> Dict[str, Any]:
        config: Dict[str, Any] = {}
        ConfigManager._apply_and_migrate_default_values(config, force_defaults=True)
        return config

    @staticmethod
    def _apply_and_migrate_default_values(config: Dict[str, Any], force_defaults: bool = False):
        if force_defaults or "api_profiles" not in config or not isinstance(config["api_profiles"], list) or not config["api_profiles"]:
            config["api_profiles"] = json.loads(json.dumps(DEFAULT_API_PROFILES))
        else:
            existing_profile_ids = {p.get("id") for p in config["api_profiles"]}
            for default_profile_schema in DEFAULT_API_PROFILES: # default_profile -> default_profile_schema
                if default_profile_schema["id"] not in existing_profile_ids:
                    config["api_profiles"].append(json.loads(json.dumps(default_profile_schema)))
                else:
                    cfg_profile_schema = next((p for p in config["api_profiles"] if p.get("id") == default_profile_schema["id"]), None) # cfg_profile -> cfg_profile_schema
                    if cfg_profile_schema:
                        for key, val_schema in default_profile_schema.items(): # val -> val_schema
                            if key not in cfg_profile_schema:
                                cfg_profile_schema[key] = json.loads(json.dumps(val_schema))
                            elif isinstance(val_schema, dict) and isinstance(cfg_profile_schema.get(key), dict):
                                if key == "endpoints":
                                    for ep_key, ep_val in val_schema.items():
                                         if ep_key not in cfg_profile_schema[key]:
                                            cfg_profile_schema[key][ep_key] = ep_val
                                elif key == "options_schema":
                                    for opt_key, opt_val_item_schema in val_schema.items(): # opt_val_schema -> opt_val_item_schema
                                        if opt_key not in cfg_profile_schema[key]:
                                            cfg_profile_schema[key][opt_key] = json.loads(json.dumps(opt_val_item_schema))

        config.setdefault("current_api_profile_id", DEFAULT_API_PROFILES[0]["id"] if DEFAULT_API_PROFILES else "")
        
        current_profile_id = config.get("current_api_profile_id") # 変数名変更なし
        profile_ids = [p.get("id") for p in config.get("api_profiles", [])]
        if current_profile_id not in profile_ids and profile_ids:
            config["current_api_profile_id"] = profile_ids[0]

        config.setdefault("api_execution_mode", "demo")

        options_values_by_profile = config.setdefault("options_values_by_profile", {})
        for profile_schema in config.get("api_profiles", []):
            profile_id_val = profile_schema.get("id")
            if profile_id_val:
                profile_options_values = options_values_by_profile.setdefault(profile_id_val, {})
                profile_options_values.setdefault("base_uri", profile_schema.get("base_uri", ""))
                profile_options_values.setdefault("api_key", "")
                
                if "options_schema" in profile_schema:
                    for opt_key, opt_schema_item in profile_schema["options_schema"].items(): # key, schema -> opt_key, opt_schema_item
                        profile_options_values.setdefault(opt_key, opt_schema_item.get("default"))
        
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
    def save(config: Dict[str, Any]):
        if not ConfigManager._ensure_config_dir_exists():
            #print("エラー: 設定ディレクトリの準備ができないため、設定を保存できません。")
            return
        if not CONFIG_PATH:
            #print("エラー: CONFIG_PATH が無効なため、設定を保存できません。")
            return
        
        config_to_save = json.loads(json.dumps(config)) 

        current_profile_id_to_save = config_to_save.get("current_api_profile_id")
        available_profile_ids = [p.get("id") for p in config_to_save.get("api_profiles", [])]
        if current_profile_id_to_save not in available_profile_ids and available_profile_ids:
            config_to_save["current_api_profile_id"] = available_profile_ids[0]

        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2, ensure_ascii=False)
        except Exception as e:
            #print(f"エラー: 設定ファイル {CONFIG_PATH} の保存に失敗しました。理由: {e}")
            pass # エラー時は何もしない（printのみ）

    @staticmethod
    def get_api_profile(config: dict, profile_id: str) -> Optional[Dict[str, Any]]: # これはスキーマ部分を返す
        for profile_schema in config.get("api_profiles", []):
            if profile_schema.get("id") == profile_id:
                return profile_schema
        return None

    @staticmethod
    def get_active_api_profile(config: dict) -> Optional[Dict[str, Any]]: # これはスキーマ部分を返す
        profile_id = config.get("current_api_profile_id")
        if profile_id:
            return ConfigManager.get_api_profile(config, profile_id)
        elif config.get("api_profiles") and len(config.get("api_profiles")) > 0:
            return config["api_profiles"][0]
        return None

    @staticmethod
    def get_active_api_options_schema(config: dict) -> Optional[Dict[str, Any]]:
        active_profile_schema = ConfigManager.get_active_api_profile(config)
        if active_profile_schema:
            return active_profile_schema.get("options_schema")
        return None

    @staticmethod
    def get_active_api_options_values(config: dict) -> Optional[Dict[str, Any]]: # これがユーザ設定値（APIキー、BaseURI含む）
        active_profile_id = config.get("current_api_profile_id")
        if active_profile_id:
            return config.get("options_values_by_profile", {}).get(active_profile_id)
        elif config.get("api_profiles") and len(config.get("api_profiles")) > 0:
            first_profile_id = config["api_profiles"][0].get("id")
            if first_profile_id:
                return config.get("options_values_by_profile", {}).get(first_profile_id)
        return None
    
    @staticmethod
    def get_api_key_for_profile(config: dict, profile_id: str) -> Optional[str]:
        profile_options_values = config.get("options_values_by_profile", {}).get(profile_id, {})
        return profile_options_values.get("api_key")

    @staticmethod
    def get_active_api_key(config: dict) -> Optional[str]:
        active_options_values = ConfigManager.get_active_api_options_values(config)
        if active_options_values:
            return active_options_values.get("api_key")
        return None
    
    @staticmethod
    def get_active_base_uri(config: dict) -> Optional[str]: # 新規追加の可能性
        """アクティブプロファイルの有効なベースURIを取得（ユーザー設定値を優先）"""
        active_options_values = ConfigManager.get_active_api_options_values(config)
        active_profile_schema = ConfigManager.get_active_api_profile(config)
        
        user_set_uri = None
        if active_options_values:
            user_set_uri = active_options_values.get("base_uri")
        
        if user_set_uri: # ユーザー設定値があればそれを優先
            return user_set_uri
        elif active_profile_schema: # なければスキーマのデフォルト
            return active_profile_schema.get("base_uri")
        return None