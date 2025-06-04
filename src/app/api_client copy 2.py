# api_client.py

import os
import time
import json
import random
import shutil
# import requests # 実際のAPIコール時に必要
from log_manager import LogLevel
from PyPDF2 import PdfWriter
import io
from typing import Optional, Dict, Any
from config_manager import ConfigManager # ConfigManager をインポート

class CubeApiClient:
    def __init__(self, config: Dict[str, Any], log_manager, api_profile: Optional[Dict[str, Any]]):
        self.log_manager = log_manager
        self.config: Dict[str, Any] = {} # 初期化
        self.active_api_profile: Optional[Dict[str, Any]] = {} # 初期化
        self.api_execution_mode: str = "demo" # 初期化
        self.api_key: Optional[str] = "" # 初期化

        # ★変更箇所: update_configを呼び出して初期設定を行う
        self.update_config(config, api_profile)

        # update_config内でログ出力されるため、ここでのログは簡略化または削除も可
        # if self.api_execution_mode == "live":
        #     self.log_manager.info(f"CubeApiClientは Liveモード ({self.active_api_profile.get('name', 'N/A') if self.active_api_profile else 'Unknown'}) で動作します。", context="API_CLIENT_INIT")
        # else:
        #     self.log_manager.info(f"CubeApiClientは Demoモード ({self.active_api_profile.get('name', 'N/A') if self.active_api_profile else 'Unknown'}) で動作します。", context="API_CLIENT_INIT")

    def _get_full_url(self, endpoint_key: str) -> Optional[str]:
        if not self.active_api_profile:
            self.log_manager.error("APIプロファイルがアクティブではありません。", context="API_CLIENT_CONFIG")
            return None

        base_uri = self.active_api_profile.get("base_uri")
        endpoints = self.active_api_profile.get("endpoints", {})
        endpoint_path = endpoints.get(endpoint_key)

        if not endpoint_path:
            err_msg = f"エンドポイントキー '{endpoint_key}' がAPIプロファイル '{self.active_api_profile.get('id')}' に設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            return None
        if not base_uri:
            err_msg = f"ベースURIがAPIプロファイル '{self.active_api_profile.get('id')}' に設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            return None
        return base_uri.rstrip('/') + endpoint_path

    def read_document(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None):
        file_name = os.path.basename(file_path)

        # specific_options は呼び出し側 (OcrWorker) で ConfigManager.get_active_api_options_values を使って
        # 生成・マージされたものが渡ってくる想定。ApiClient内ではそれをそのまま利用。
        effective_options = specific_options if specific_options is not None else {}

        flow_type = self.active_api_profile.get("flow_type") if self.active_api_profile else None

        if flow_type == "cube_fullocr_single_call": # cube_fullocr_v1 用のフロー
            actual_ocr_params = {
                'adjust_rotation': effective_options.get('adjust_rotation'),
                'character_extraction': effective_options.get('character_extraction'),
                'concatenate': effective_options.get('concatenate'),
                'enable_checkbox': effective_options.get('enable_checkbox'),
                'fulltext': effective_options.get('fulltext_output_mode'),
                'fulltext_linebreak': effective_options.get('fulltext_linebreak_char'),
                'horizontal_ocr_model': effective_options.get('ocr_model')
            }
            actual_ocr_params = {k: v for k, v in actual_ocr_params.items() if v is not None}

            if self.api_execution_mode == "demo":
                log_ctx = "API_DUMMY_READ_CUBE"
                profile_name = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else "UnknownProfile"
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (read_document): {file_name}", context=log_ctx, options=actual_ocr_params)
                time.sleep(random.uniform(0.1, 0.3))

                if file_name.startswith("error_"):
                    error_code_map = { "error_auth": "DUMMY_AUTH_ERROR", "error_server": "DUMMY_SERVER_ERROR", "error_bad_request": "DUMMY_BAD_REQUEST" }
                    error_message_map = { "error_auth": f"Demo認証エラー: {file_name}", "error_server": f"Demoサーバーエラー: {file_name}", "error_bad_request": f"Demo不正リクエスト: {file_name}"}
                    simulated_error_type = file_name.split("_")[1] if "_" in file_name else "generic"
                    error_code = error_code_map.get(f"error_{simulated_error_type}", "DUMMY_OCR_ERROR")
                    error_msg_val = error_message_map.get(f"error_{simulated_error_type}", f"Demo OCRエラー: {file_name}")
                    self.log_manager.error(error_msg_val, context=log_ctx, error_code=error_code, filename=file_name)
                    return None, {"message": error_msg_val, "code": error_code, "detail": "Demoモードでシミュレートされたエラーです。"}

                page_result = {"page": 0, "result": {"fileName": file_name, "fulltext": f"Demo fulltext for {file_name} ({profile_name})"}, "status": "success"}
                response_data = [page_result]
                if actual_ocr_params.get('fulltext') == 1 :
                    simplified_data = [{"page": p.get("page"), "result": {"fileName": p.get("result",{}).get("fileName"), "fulltext": p.get("result",{}).get("fulltext")}} for p in response_data]
                    response_data = simplified_data
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (read_document): {file_name}", context=log_ctx)
                return response_data, None
            else: # Live モード
                log_ctx = "API_LIVE_READ_CUBE"
                profile_name = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else "UnknownProfile"
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (read_document): {file_name}", context=log_ctx)
                url = self._get_full_url("read_document")
                if not url: return None, {"message": "エンドポイントURL取得失敗 (read_document)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
                
                # ★変更箇所: self.api_key は update_config で設定されたプロファイル固有のものを使用
                if not self.api_key:
                    err_msg_val = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg_val, context=log_ctx, error_code="API_KEY_MISSING_LIVE")
                    return None, {"message": err_msg_val, "code": "API_KEY_MISSING_LIVE"}
                
                headers = {"apikey": self.api_key}
                self.log_manager.info(f"  URL: {url}", context=log_ctx)
                self.log_manager.info(f"  OCRパラメータ: {actual_ocr_params}", context=log_ctx)
                # TODO: 実際のAPIコールを実装 (例: requests.post(url, headers=headers, files=files, data=actual_ocr_params))
                self.log_manager.warning("LiveモードAPIコールは実装されていません (Cube read_document)。Demo動作を返します。", context=log_ctx)
                return None, {"message": "LiveモードAPIコール未実装 (Cube read_document)。", "code": "NOT_IMPLEMENTED_API_CALL"}
        # ★追加: 新しいプロファイルのフロータイプに対応するためのエルス条件（将来用プレースホルダー）
        # elif flow_type == "dx_fulltext_v2_flow":
        #     # DX Suite 全文OCR V2 用の処理
        #     self.log_manager.warning(f"APIフロータイプ '{flow_type}' の処理は未実装です。", context="API_CLIENT_WARN")
        #     return None, {"message": f"未対応のAPIフロータイプ: {flow_type}", "code": "UNSUPPORTED_FLOW_TYPE"}
        else:
            self.log_manager.error(f"未対応または不明なAPIフロータイプです: {flow_type}", context="API_CLIENT_ERROR")
            return None, {"message": f"未対応のAPIフロータイプ: {flow_type}", "code": "UNSUPPORTED_FLOW_TYPE"}


    def make_searchable_pdf(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None):
        file_name = os.path.basename(file_path)
        effective_options = specific_options if specific_options is not None else {}
        flow_type = self.active_api_profile.get("flow_type") if self.active_api_profile else None
        profile_name = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else "UnknownProfile"

        if flow_type == "cube_fullocr_single_call": # cube_fullocr_v1 用のフロー
            if self.api_execution_mode == "demo":
                log_ctx = "API_DUMMY_PDF_CUBE"
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (make_searchable_pdf): {file_name}", context=log_ctx)
                time.sleep(random.uniform(0.1, 0.3))
                if file_name.startswith("pdf_error_"):
                    error_msg_val = f"Demo PDF作成エラー: {file_name}"
                    self.log_manager.error(error_msg_val, context=log_ctx, error_code="DUMMY_PDF_ERROR", filename=file_name)
                    return None, {"message": error_msg_val, "code": "DUMMY_PDF_ERROR", "detail": "DemoモードでのPDF作成エラーです。"}
                try:
                    writer = PdfWriter()
                    writer.add_blank_page(width=595, height=842)
                    bio = io.BytesIO()
                    writer.write(bio)
                    dummy_pdf_content = bio.getvalue()
                    self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (make_searchable_pdf): {file_name}", context=log_ctx)
                    return dummy_pdf_content, None
                except Exception as e_pdf_dummy:
                    error_detail_str = str(e_pdf_dummy) if e_pdf_dummy else "不明なPDF生成例外"
                    error_msg_main = f"Demo PDF生成エラー: {file_name}, Error: {error_detail_str}"
                    self.log_manager.error(error_msg_main, context=log_ctx, error_code="DUMMY_PDF_GEN_ERROR", filename=file_name, exc_info=True)
                    return None, {"message": error_msg_main, "code": "DUMMY_PDF_GEN_ERROR", "detail": error_detail_str}
            else: # Live モード
                log_ctx = "API_LIVE_PDF_CUBE"
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (make_searchable_pdf): {file_name}", context=log_ctx)
                url = self._get_full_url("make_searchable_pdf")
                if not url: return None, {"message": "エンドポイントURL取得失敗 (make_searchable_pdf)", "code": "CONFIG_ENDPOINT_URL_FAIL_PDF"}

                # ★変更箇所: self.api_key は update_config で設定されたプロファイル固有のものを使用
                if not self.api_key:
                    err_msg_val = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg_val, context=log_ctx, error_code="API_KEY_MISSING_PDF_LIVE")
                    return None, {"message": err_msg_val, "code": "API_KEY_MISSING_PDF_LIVE"}

                headers = {"apikey": self.api_key}
                # TODO: 実際のAPIコールを実装
                self.log_manager.warning("LiveモードAPIコールは実装されていません (Cube make_searchable_pdf)。Demo動作を返します。", context=log_ctx)
                return None, {"message": "LiveモードAPIコール未実装 (Cube make_searchable_pdf)。", "code": "NOT_IMPLEMENTED_API_CALL_PDF"}
        # ★追加: 新しいプロファイルのフロータイプに対応するためのエルス条件（将来用プレースホルダー）
        # elif flow_type == "dx_fulltext_v2_flow":
        #     # DX Suite 全文OCR V2 用のPDF処理
        #     self.log_manager.warning(f"APIフロータイプ '{flow_type}' のPDF処理は未実装です。", context="API_CLIENT_WARN")
        #     return None, {"message": f"未対応のAPIフロータイプ (PDF): {flow_type}", "code": "UNSUPPORTED_FLOW_TYPE_PDF"}
        else:
            self.log_manager.error(f"未対応または不明なAPIフロータイプです: {flow_type} (PDF作成)", context="API_CLIENT_ERROR")
            return None, {"message": f"未対応のAPIフロータイプ (PDF作成): {flow_type}", "code": "UNSUPPORTED_FLOW_TYPE_PDF"}

    def update_config(self, new_config: dict, new_api_profile: Optional[Dict[str, Any]]):
        self.log_manager.info("ApiClient: 設定更新中...", context="API_CLIENT_CONFIG_UPDATE")
        self.config = new_config # 渡された新しいconfig全体を保持

        if new_api_profile:
            self.active_api_profile = new_api_profile
        elif "current_api_profile_id" in new_config:
            current_profile_id_from_config = new_config.get("current_api_profile_id")
            # ConfigManagerの静的メソッドを使って、渡されたconfigからアクティブなプロファイルを取得
            active_profile_from_cfg = ConfigManager.get_api_profile(new_config, current_profile_id_from_config)
            if active_profile_from_cfg:
                self.active_api_profile = active_profile_from_cfg
            elif new_config.get("api_profiles"): # current_api_profile_idが無効なら最初のプロファイルをフォールバック
                self.active_api_profile = new_config["api_profiles"][0]
                self.log_manager.warning(f"ApiClient: 指定されたcurrent_api_profile_id '{current_profile_id_from_config}' が見つからないため、最初のプロファイル '{self.active_api_profile.get('name')}' を使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else: # 利用可能なプロファイルが全くない場合
                self.active_api_profile = {} # 空にするか、エラーにするか検討
                self.log_manager.error("ApiClient: 利用可能なAPIプロファイルが設定にありません。", context="API_CLIENT_CONFIG_UPDATE_ERROR")
        else: # new_api_profile も current_api_profile_id もない場合（通常は考えにくい）
            if self.config.get("api_profiles"): # 既存のconfigからフォールバック試行
                 self.active_api_profile = self.config["api_profiles"][0]
                 self.log_manager.warning("ApiClient: update_configで有効なプロファイル情報が不足していたため、config内の最初のプロファイルを使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else:
                self.active_api_profile = {}
                self.log_manager.error("ApiClient: update_configで有効なプロファイル情報が不足しており、フォールバックもできませんでした。", context="API_CLIENT_CONFIG_UPDATE_ERROR")


        self.api_execution_mode = self.config.get("api_execution_mode", "demo")

        # ★変更箇所: ConfigManagerのヘルパーメソッドを使ってアクティブプロファイルのAPIキーを取得
        self.api_key = ConfigManager.get_active_api_key(self.config)
        if self.api_key is None: # get_active_api_keyがNoneを返す場合（キー未設定など）は空文字列に
            self.api_key = ""

        profile_name_for_log = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else '未定義プロファイル'
        key_status_log = "設定あり" if self.api_key else "未設定"

        if self.api_execution_mode == "live":
            self.log_manager.info(f"ApiClientは Liveモード ({profile_name_for_log}, APIキー: {key_status_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info(f"ApiClientは Demoモード ({profile_name_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")