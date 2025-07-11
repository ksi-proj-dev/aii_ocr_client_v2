# config_manager.py (修正版)

import os
import json
import datetime
import shutil
from typing import Optional, Dict, Any, List
from appdirs import user_config_dir

# --- 修正箇所 ---
# LogManagerをインポートします
from log_manager import LogManager
# --- 修正箇所 ---

from app_constants import APP_NAME, APP_AUTHOR
from model_data import MODEL_DEFINITIONS

CONFIG_FILE_NAME = "config.json"

try:
    CONFIG_DIR = user_config_dir(appname=APP_NAME, appauthor=APP_AUTHOR, roaming=True)
    CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE_NAME)
except Exception as e:
    # --- 修正箇所 ---
    # printをLogManager.warningに置き換えます
    LogManager().warning(f"appdirsでの設定パス取得に失敗しました。ローカルフォルダにフォールバックします。エラー: {e}", context="CONFIG_PATH")
    # --- 修正箇所 ---
    fallback_dir_name = f"{APP_AUTHOR}_{APP_NAME}_config_fallback".replace(" ", "_")
    try:
        CONFIG_DIR = os.path.join(os.getcwd(), fallback_dir_name)
        CONFIG_PATH = os.path.join(CONFIG_DIR, CONFIG_FILE_NAME)
        # --- 修正箇所 ---
        LogManager().info(f"フォールバック先のパス: {CONFIG_PATH}", context="CONFIG_PATH")
        # --- 修正箇所 ---
    except Exception as fallback_e:
        # --- 修正箇所 ---
        LogManager().critical(f"フォールバックパスの設定も失敗しました: {fallback_e}", context="CONFIG_PATH")
        # --- 修正箇所 ---
        CONFIG_PATH = None; CONFIG_DIR = None

# (DEFAULT_API_PROFILES の定義は変更ないため省略)
DEFAULT_API_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "dx_fulltext_v2",
        "name": "DX Suite (全文OCR V2)",
        "base_uri": "https://{組織固有}.dx-suite.com/wf/api/fullocr/v2/",
        "flow_type": "dx_fulltext_v2_flow",
        "endpoints": {
            "register_ocr": "/register",
            "get_ocr_result": "/getOcrResult",
            "delete_ocr": "/delete",
            "register_searchable_pdf": "/searchablepdf/register",
            "get_searchable_pdf_result": "/searchablepdf/getResult"
        },
        "options_schema": {
            "concatenate": {"type": "bool", "default": 0, "label": "結合オプション (DX Suite)", "tooltip": "0: OFF, 1: ON. デフォルトはOFF."},
            "characterExtraction": {"type": "bool", "default": 0, "label": "文字抽出オプション (DX Suite)", "tooltip": "0: OFF, 1: ON. デフォルトはOFF."},
            "tableExtraction": {"type": "bool", "default": 1, "label": "表抽出オプション (DX Suite)", "tooltip": "0: OFF, 1: ON. デフォルトはON."},
            "highResolutionMode": {"type": "bool", "default": 0, "label": "高解像度オプション (サーチャブルPDF, DX Suite)", "tooltip": "0: OFF (低解像度), 1: ON (高解像度). デフォルトはOFF."},
            "upload_max_size_mb": {"type": "int", "default": 1000, "min": 1, "max": 9999, "suffix": " MB", "label": "アップロード対象として認識する最大ファイルサイズ:", "tooltip":"OCR対象としてアップロードするファイルサイズの上限値。\nこれを超過するファイルは処理対象外となります。"},
            "split_large_files_enabled": {"type": "bool", "default": False, "label": "大きなファイルを自動分割する (PDFのみ, DX Suite)", "tooltip": "PDFファイルが「アップロード対象として認識する最大ファイルサイズ」を超える場合、\nまたは「ページ数上限での分割」が有効で「部品あたりの最大ページ数」を超える場合に分割します。"},
            "split_chunk_size_mb": {"type": "int", "default": 10, "min": 1, "max": 50, "suffix": " MB", "label": "分割サイズ目安 (1部品あたり, DX Suite):", "tooltip": "ファイルサイズで分割する場合の、分割後の各ファイルサイズの上限の目安。"},
            "split_by_page_count_enabled": {"type": "bool", "default": True, "label": "ページ数上限で分割する (PDF分割時, DX Suite)", "tooltip": "「大きなファイルを自動分割する」が有効な場合に、\nさらにページ数でも分割トリガーとするか設定します。DX Suite推奨は100ページ以下のためデフォルトON。"},
            "split_max_pages_per_part": {"type": "int", "default": 100, "min": 1, "max": 100, "label": "部品あたりの最大ページ数 (PDF分割時, DX Suite):", "tooltip": "ページ数で分割する場合の、1部品あたりの最大ページ数を指定します。\nDX Suiteの推奨は100ページ以下です。"},
            "merge_split_pdf_parts": {"type": "bool", "default": True, "label": "分割した場合、サーチャブルPDF部品を1つのファイルに結合する (DX Suite)", "tooltip": "「大きなファイルを自動分割する」が有効な場合のみ適用されます。"},
            "polling_interval_seconds": {"type": "int", "default": 3, "min": 1, "max": 60, "label": "ポーリング間隔 (秒, DX Suite):", "tooltip": "非同期APIの結果を取得する際の問い合わせ間隔（秒）です。", "suffix": " 秒"},
            "polling_max_attempts": {"type": "int", "default": 60, "min": 5, "max": 300, "label": "最大ポーリング試行回数 (DX Suite):", "tooltip": "非同期APIの結果取得を試みる最大回数です。", "suffix": " 回"},
            "delete_job_after_processing": {"type": "bool", "default": 1, "label": "処理後、サーバーからOCRジョブ情報を削除する (DX Suite)", "tooltip": "有効な場合、各ファイルのOCR処理完了後 (成功/失敗問わず)、関連するジョブ情報をDX Suiteサーバーから削除します。"}
        }
    },
    {
        "id": "dx_atypical_v2",
        "name": "DX Suite (非定型OCR V2)",
        "base_uri": "https://{組織固有}.dx-suite.com/wf/api/atypical/v2/",
        "flow_type": "dx_atypical_v2_flow",
        "endpoints": {
            "register_ocr": "/read",
            "get_ocr_result": "/result",
            "get_receptions": "/receptions",
            "delete_ocr": "/delete"
        },
        "options_schema": {
            "model": {
                "type": "enum",
                "default": "invoice",
                "values": [
                    {"display": "請求書 (invoice)", "value": "invoice"},
                    {"display": "領収書 (receipt)", "value": "receipt"},
                    {"display": "発注書 (purchase_order)", "value": "purchase_order"},
                    {"display": "住民票 (resident_card)", "value": "resident_card"},
                    {"display": "給与明細(R3) (salary_r3)", "value": "salary_r3"},
                    {"display": "自動車税納税証明書 (automobile_tax)", "value": "automobile_tax"},
                    {"display": "診療明細書 (medical_receipt)", "value": "medical_receipt"},
                    {"display": "賃貸借契約書 (lease_contract)", "value": "lease_contract"},
                    {"display": "健康診断結果報告書 (health_certificate)", "value": "health_certificate"},
                    {"display": "生命保険証券 (life_insurance)", "value": "life_insurance"},
                    {"display": "履歴書 (resume)", "value": "resume"},
                    {"display": "支払通知書 (payment)", "value": "payment"},
                    {"display": "請求書(タイ) (thai_invoice)", "value": "thai_invoice"},
                    {"display": "本人確認書類 (idcard)", "value": "idcard"}
                ],
                "label": "帳票モデル (DX Suite 非定型):",
                "tooltip": "読み取り対象の帳票モデルを選択します。（必須）"
            },
            "classes": {
                "type": "string",
                "default": "",
                "label": "読取クラス名 (カンマ区切り, 任意):",
                "placeholder": "例: title,issue_date,billing_company",
                "tooltip": "指定したクラス（項目）のみを読み取る場合に指定します。\n指定なしの場合は全クラスが対象です。"
            },
            "departmentId": {
                "type": "string",
                "default": "",
                "label": "部署ID (任意):",
                "placeholder": "例: 123",
                "tooltip": "DX Suiteの部署IDを数字で指定します。"
            },
            "upload_max_size_mb": {"type": "int", "default": 1000, "min": 1, "max": 9999, "suffix": " MB", "label": "アップロード対象として認識する最大ファイルサイズ:", "tooltip":"OCR対象としてアップロードするファイルサイズの上限値。\nこれを超過するファイルは処理対象外となります。"},
            "split_large_files_enabled": {"type": "bool", "default": False, "label": "大きなファイルを自動分割する (PDFのみ)"},
            "split_chunk_size_mb": {"type": "int", "default": 10, "min": 1, "max": 50, "suffix": " MB", "label": "分割サイズ目安 (1部品あたり):"},
            "split_by_page_count_enabled": {"type": "bool", "default": True, "label": "ページ数上限で分割する (PDF分割時)"},
            "split_max_pages_per_part": {"type": "int", "default": 100, "min": 1, "max": 500, "label": "部品あたりの最大ページ数 (PDF分割時):", "tooltip": "DX Suiteの推奨は500ページ以下です。"},
            "merge_split_pdf_parts": {"type": "bool", "default": True, "label": "分割した場合、サーチャブルPDF部品を1つのファイルに結合する"},
            "polling_interval_seconds": {"type": "int", "default": 3, "min": 1, "max": 60, "label": "ポーリング間隔 (秒):", "suffix": " 秒"},
            "polling_max_attempts": {"type": "int", "default": 60, "min": 5, "max": 300, "label": "最大ポーリング試行回数:", "suffix": " 回"},
            "delete_job_after_processing": {"type": "bool", "default": 1, "label": "処理後、サーバーからOCRジョブ情報を削除する (DX Suite)", "tooltip": "有効な場合、各ファイルのOCR処理完了後、関連するジョブ情報をDX Suiteサーバーから削除します。"}
        }
    },
    {
        "id": "dx_standard_v2",
        "name": "DX Suite (標準OCR V2)",
        "base_uri": "https://{組織固有}.dx-suite.com/wf/api/standard/v2/",
        "flow_type": "dx_standard_v2_flow",
        "endpoints": {
            "register_ocr": "/workflows/{workflowId}/units",
            "get_ocr_status": "/units/status",
            "get_ocr_result": "/units/dataItems",
            "download_csv": "/units/{unitId}/csv",
            "delete_ocr": "/units/{unitId}/delete"
        },
        "options_schema": {
            "workflowId": {
                "type": "string",
                "default": "",
                "label": "ワークフローID (DX Suite 標準):",
                "placeholder": "例: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                "tooltip": "DX Suiteの管理画面で確認したワークフローID (UUID) を指定します。（必須）"
            },
            "sortConfigId": {
                "type": "string",
                "default": "",
                "label": "仕分けルールID (Elastic Sorter):",
                "placeholder": "例: yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
                "tooltip": "仕分け処理で使用する仕分けルールのID (UUID) を指定します。\n（「仕分け」機能を利用する場合に必須）"
            },
            "unitName": {"type": "string", "default": "", "label": "読取ユニット名 (任意):", "placeholder": "例: 2025年6月分請求書", "tooltip": "DX Suite上で表示される読取ユニットの名前を指定します。"},
            "upload_max_size_mb": {"type": "int", "default": 1000, "min": 1, "max": 9999, "suffix": " MB", "label": "アップロード対象として認識する最大ファイルサイズ:", "tooltip":"OCR対象としてアップロードするファイルサイズの上限値。\nこれを超過するファイルは処理対象外となります。"},
            "split_large_files_enabled": {"type": "bool", "default": False, "label": "大きなファイルを自動分割する (PDFのみ)"},
            "split_chunk_size_mb": {"type": "int", "default": 10, "min": 1, "max": 50, "suffix": " MB", "label": "分割サイズ目安 (1部品あたり):"},
            "split_by_page_count_enabled": {"type": "bool", "default": True, "label": "ページ数上限で分割する (PDF分割時)"},
            "split_max_pages_per_part": {"type": "int", "default": 100, "min": 1, "max": 100, "label": "部品あたりの最大ページ数 (PDF分割時):"},
            "merge_split_pdf_parts": {"type": "bool", "default": True, "label": "分割した場合、サーチャブルPDF部品を1つのファイルに結合する"},
            "polling_interval_seconds": {"type": "int", "default": 3, "min": 1, "max": 60, "label": "ポーリング間隔 (秒):", "suffix": " 秒"},
            "polling_max_attempts": {"type": "int", "default": 60, "min": 5, "max": 300, "label": "最大ポーリング試行回数:", "suffix": " 回"},
            "delete_job_after_processing": {"type": "bool", "default": 1, "label": "処理後、サーバーから読取ユニットを削除する (DX Suite)", "tooltip": "有効な場合、各ファイルのOCR処理完了後、関連する読取ユニットをDX Suiteサーバーから削除します。"}
        }
    }
]

class ConfigManager:
    @staticmethod
    def _ensure_config_dir_exists():
        if not CONFIG_PATH:
            # --- 修正箇所 ---
            LogManager().error("CONFIG_PATHが設定されていないため、設定ディレクトリを作成できません。", context="CONFIG_SAVE")
            # --- 修正箇所 ---
            return False
        try:
            config_dir_for_creation = os.path.dirname(CONFIG_PATH)
            if not os.path.exists(config_dir_for_creation):
                os.makedirs(config_dir_for_creation, exist_ok=True)
        except Exception as e:
            # --- 修正箇所 ---
            LogManager().warning(f"設定ディレクトリの作成に失敗しました: {config_dir_for_creation}, Error: {e}", context="CONFIG_SAVE")
            # --- 修正箇所 ---
            return False
        return True

    @staticmethod
    def load() -> Dict[str, Any]:
        if not ConfigManager._ensure_config_dir_exists():
            return ConfigManager._get_default_config_structure()

        user_config = {}
        if CONFIG_PATH and os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                # --- 修正箇所 ---
                LogManager().warning(f"{CONFIG_PATH} の読み込みに失敗しました: {e}。バックアップを作成し、デフォルト設定で続行します。", context="CONFIG_LOAD")
                # --- 修正箇所 ---
                ConfigManager._backup_corrupted_config()
                user_config = ConfigManager._get_default_config_structure()
        else:
            user_config = ConfigManager._get_default_config_structure()

        ConfigManager._apply_and_migrate_default_values(user_config)
        return user_config

    @staticmethod
    def get_class_definitions_for_model(model_id: str) -> List[Dict[str, str]]:
        return MODEL_DEFINITIONS.get(model_id, [])

    @staticmethod
    def _backup_corrupted_config():
        if CONFIG_PATH and os.path.exists(CONFIG_PATH):
            try:
                backup_path = CONFIG_PATH + ".corrupted_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                shutil.copy2(CONFIG_PATH, backup_path)
                # --- 修正箇所 ---
                LogManager().info(f"破損した可能性のある設定ファイルを {backup_path} にバックアップしました。", context="CONFIG_BACKUP")
                # --- 修正箇所 ---
            except Exception as e_backup:
                # --- 修正箇所 ---
                LogManager().error(f"破損した設定ファイルのバックアップに失敗: {e_backup}", context="CONFIG_BACKUP")
                # --- 修正箇所 ---
                pass
    
    # (残りのメソッドは変更ないため省略)
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
            for default_profile_schema in DEFAULT_API_PROFILES:
                if default_profile_schema["id"] not in existing_profile_ids:
                    config["api_profiles"].append(json.loads(json.dumps(default_profile_schema)))
                else:
                    cfg_profile_schema = next((p for p in config["api_profiles"] if p.get("id") == default_profile_schema["id"]), None)
                    if cfg_profile_schema:
                        for key, val_schema in default_profile_schema.items():
                            if key not in cfg_profile_schema:
                                cfg_profile_schema[key] = json.loads(json.dumps(val_schema))
                            elif isinstance(val_schema, dict) and isinstance(cfg_profile_schema.get(key), dict):
                                if key == "endpoints":
                                    for ep_key, ep_val in val_schema.items():
                                        if ep_key not in cfg_profile_schema[key]:
                                            cfg_profile_schema[key][ep_key] = ep_val
                                elif key == "options_schema":
                                    for opt_key, opt_val_item_schema in val_schema.items():
                                        if opt_key not in cfg_profile_schema[key]:
                                            cfg_profile_schema[key][opt_key] = json.loads(json.dumps(opt_val_item_schema))

        config.setdefault("current_api_profile_id", DEFAULT_API_PROFILES[0]["id"] if DEFAULT_API_PROFILES else "")
        
        current_profile_id = config.get("current_api_profile_id")
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
                    for opt_key, opt_schema_item in profile_schema["options_schema"].items():
                        profile_options_values.setdefault(opt_key, opt_schema_item.get("default"))
        
        file_actions = config.setdefault("file_actions", {})
        file_actions.setdefault("move_on_success_enabled", False)
        file_actions.setdefault("success_folder_name", "OCR成功")
        file_actions.setdefault("move_on_failure_enabled", False)
        file_actions.setdefault("failure_folder_name", "OCR失敗")
        file_actions.setdefault("collision_action", "rename")
        file_actions.setdefault("results_folder_name", "OCR結果")
        file_actions.setdefault("output_format", "both")

        log_settings = config.setdefault("log_settings", {})
        log_settings.setdefault("log_level_info_enabled", True)
        log_settings.setdefault("log_level_warning_enabled", True)
        log_settings.setdefault("log_level_debug_enabled", False)

        config.setdefault("window_size", {"width": 1000, "height": 700})
        config.setdefault("window_state", "normal")
        config.setdefault("current_view", 0) 
        config.setdefault("log_visible", True)
        config.setdefault("column_widths", [35, 50, 280, 100, 270, 100, 100, 120, 60, 100])
        config.setdefault("sort_order", {"column": 1, "order": "asc"})
        config.setdefault("splitter_sizes", [])
        config.setdefault("last_target_dir", "")
        
    @staticmethod
    def save(config: Dict[str, Any]):
        if not ConfigManager._ensure_config_dir_exists():
            # --- 修正箇所 ---
            LogManager().error("設定ディレクトリの準備ができないため、設定を保存できません。", context="CONFIG_SAVE")
            # --- 修正箇所 ---
            return
        if not CONFIG_PATH:
            # --- 修正箇所 ---
            LogManager().error("CONFIG_PATH が無効なため、設定を保存できません。", context="CONFIG_SAVE")
            # --- 修正箇所 ---
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
            # --- 修正箇所 ---
            LogManager().error(f"設定ファイル {CONFIG_PATH} の保存に失敗しました。理由: {e}", context="CONFIG_SAVE")
            # --- 修正箇所 ---
            pass

    @staticmethod
    def get_api_profile(config: dict, profile_id: str) -> Optional[Dict[str, Any]]:
        for profile_schema in config.get("api_profiles", []):
            if profile_schema.get("id") == profile_id:
                return profile_schema
        return None

    @staticmethod
    def get_active_api_profile(config: dict) -> Optional[Dict[str, Any]]:
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
    def get_active_api_options_values(config: dict) -> Optional[Dict[str, Any]]:
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
    def get_active_base_uri(config: dict) -> Optional[str]:
        active_options_values = ConfigManager.get_active_api_options_values(config)
        active_profile_schema = ConfigManager.get_active_api_profile(config)
        
        user_set_uri = None
        if active_options_values:
            user_set_uri = active_options_values.get("base_uri")
        
        if user_set_uri:
            return user_set_uri
        elif active_profile_schema:
            return active_profile_schema.get("base_uri")
        return None
