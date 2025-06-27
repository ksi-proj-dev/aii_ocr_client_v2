# api_client_atypical.py

import os
import time
import random
import requests
import json
from typing import Optional, Dict, Any, Tuple

from config_manager import ConfigManager


class OCRApiClientAtypical:
    def __init__(self, config: Dict[str, Any], log_manager, api_profile_schema: Optional[Dict[str, Any]]):
        self.log_manager = log_manager
        self.config: Dict[str, Any] = {}
        self.active_api_profile_schema: Optional[Dict[str, Any]] = {}
        self.active_options_values: Optional[Dict[str, Any]] = {}
        self.api_execution_mode: str = "demo"
        self.api_key: Optional[str] = ""
        self.timeout_seconds: int = 180

        self.update_config(config, api_profile_schema)

    def update_config(self, new_config: dict, new_api_profile_schema: Optional[Dict[str, Any]]):
        self.log_manager.info("AtypicalApiClient: 設定更新中...", context="API_CLIENT_CONFIG_UPDATE")
        self.config = new_config

        if new_api_profile_schema:
            self.active_api_profile_schema = new_api_profile_schema
        elif "current_api_profile_id" in new_config:
            current_profile_id_from_config = new_config.get("current_api_profile_id")
            active_profile_schema_from_cfg = ConfigManager.get_api_profile(new_config, current_profile_id_from_config)
            if active_profile_schema_from_cfg:
                self.active_api_profile_schema = active_profile_schema_from_cfg
            elif new_config.get("api_profiles"):
                self.active_api_profile_schema = new_config["api_profiles"][0]
                self.log_manager.warning(f"AtypicalApiClient: current_api_profile_id '{current_profile_id_from_config}' のスキーマが見つからないため、最初のプロファイルを使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else:
                self.active_api_profile_schema = {}
                self.log_manager.error("AtypicalApiClient: 設定にAPIプロファイルがありません。", context="API_CLIENT_CONFIG_UPDATE_ERROR")
        else:
            self.active_api_profile_schema = {}
            self.log_manager.error("AtypicalApiClient: update_configにプロファイルスキーマもIDも渡されませんでした。", context="API_CLIENT_CONFIG_UPDATE_ERROR")

        self.active_options_values = ConfigManager.get_active_api_options_values(self.config)
        if self.active_options_values is None:
            self.active_options_values = {}
            self.log_manager.warning("AtypicalApiClient: アクティブプロファイルのオプション値が取得できませんでした。", context="API_CLIENT_CONFIG_UPDATE")

        self.api_execution_mode = self.config.get("api_execution_mode", "demo")
        self.api_key = self.active_options_values.get("api_key", "")

        profile_name_for_log = self.active_api_profile_schema.get('name', 'N/A')
        key_status_log = "設定あり" if self.api_key else "未設定"
        base_uri_for_log = self.active_options_values.get("base_uri", self.active_api_profile_schema.get("base_uri", "未設定"))

        if self.api_execution_mode == "live":
            self.log_manager.info(f"AtypicalApiClientは Liveモード ({profile_name_for_log}, APIキー: {key_status_log}, BaseURI: {base_uri_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info(f"AtypicalApiClientは Demoモード ({profile_name_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")

    def _get_full_url(self, endpoint_key: str) -> Optional[str]:
        if not self.active_api_profile_schema:
            self.log_manager.error("APIプロファイルスキーマがアクティブではありません。", context="API_CLIENT_CONFIG")
            return None
        base_uri = self.active_options_values.get("base_uri") if self.active_options_values else None
        if not base_uri:
            base_uri = self.active_api_profile_schema.get("base_uri")
            self.log_manager.debug(f"ユーザー設定のBaseURIが空のため、スキーマ定義のBaseURI '{base_uri}' を使用します。", context="API_CLIENT_CONFIG")
        if not base_uri:
            err_msg = f"ベースURIがプロファイル '{self.active_api_profile_schema.get('id')}' に設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            return None
        if ("{組織固有}" in base_uri or "{organization_specific_domain}" in base_uri) and self.api_execution_mode == "live":
            self.log_manager.warning(f"ベースURIにプレースホルダーが含まれています: {base_uri}。Liveモードでは正しいドメインに置き換える必要があります。", context="API_CLIENT_CONFIG")
        endpoints = self.active_api_profile_schema.get("endpoints", {})
        endpoint_path = endpoints.get(endpoint_key)
        if not endpoint_path:
            err_msg = f"エンドポイントキー '{endpoint_key}' がプロファイル '{self.active_api_profile_schema.get('id')}' に設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            return None
        return base_uri.rstrip('/') + endpoint_path

    def _get_request_headers(self) -> Dict[str, str]:
        header_key = "apikey"
        if not self.api_key:
            self.log_manager.warning(f"APIキーが未設定です。ヘッダーキー: {header_key}", context="API_CLIENT_HEADERS")
            return {}
        return {header_key: self.api_key}

    def read_document(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        file_name = os.path.basename(file_path)
        base_options = self.active_options_values if self.active_options_values is not None else {}
        effective_options = {**base_options, **(specific_options or {})}
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        log_ctx_prefix = "API_DX_ATYPICAL_V2"
        
        if self.api_execution_mode == "demo":
            self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Atypical V2 - Simulate Read & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
            model_opt = effective_options.get("model", "invoice"); classes_opt = effective_options.get("classes", ""); self.log_manager.debug(f"  Simulating Register with options: model='{model_opt}', classes='{classes_opt}'", context=f"{log_ctx_prefix}_DEMO_REGISTER")
            if "error" in file_name.lower():
                error_code = "DUMMY_DX_ATYPICAL_ERROR"; error_msg = f"Demo DX Suite 非定型エラー: {file_name}"; self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name); return None, {"message": error_msg, "code": error_code, "detail": "Demoモードでシミュレートされたエラーです。"}
            dummy_reception_id = f"demo-reception-{random.randint(10000, 99999)}"; self.log_manager.info(f"  Simulated Register success. receptionId: {dummy_reception_id}", context=f"{log_ctx_prefix}_DEMO_REGISTER"); time.sleep(random.uniform(0.2, 0.5)); self.log_manager.info(f"  Simulating GetResult for receptionId: {dummy_reception_id}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
            demo_part = {"className": "billing_company", "text": f"株式会社モック（モデル: {model_opt}）", "detectionConfidence": round(random.uniform(0.9, 0.99), 5), "ocrConfidence": round(random.uniform(0.85, 0.98), 5), "confidenceScore": 0, "status": 1, "tags": [], "bbox": {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.05}}
            demo_ocr_result = {"pageNum": 1, "deskewAngle": 0, "parts": [demo_part], "status": 2}
            demo_file_result = {"fileName": file_name, "ocrResults": [demo_ocr_result], "status": 2}
            final_json_response = {"status": 2, "files": [demo_file_result]}
            self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (DX Suite Atypical V2): {file_name}", context=f"{log_ctx_prefix}_DEMO_GETRESULT"); return final_json_response, None
        else: # Live モード
            self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Atypical V2 - Read): {file_name}", context=f"{log_ctx_prefix}_LIVE_READ"); url = self._get_full_url("register_ocr")
            if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Atypical Read)", "code": "CONFIG_ENDPOINT_URL_FAIL_ATYPICAL"}
            if "{組織固有}" in url: self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR"); return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
            if not self.api_key: err_msg = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_READ", error_code="API_KEY_MISSING_LIVE"); return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}
            headers = self._get_request_headers()
            data_payload = {}; model_to_send = effective_options.get("model")
            if not model_to_send: return None, {"message": "必須パラメータ '帳票モデル' が設定されていません。", "code": "DX_ATYPICAL_MODEL_MISSING"}
            data_payload['model'] = model_to_send
            if effective_options.get("classes"): data_payload['classes'] = effective_options.get("classes")
            if effective_options.get("departmentId"): data_payload['departmentId'] = effective_options.get("departmentId")
            file_obj = None
            try:
                file_obj = open(file_path, 'rb'); files_payload = {'files': (os.path.basename(file_path), file_obj)}
                self.log_manager.debug(f"  POST to {url} with headers: {list(headers.keys())}, form-data: {data_payload}, file: {file_name}", context=f"{log_ctx_prefix}_LIVE_READ"); response = requests.post(url, headers=headers, data=data_payload, files=files_payload, timeout=self.timeout_seconds); response.raise_for_status(); response_json = response.json(); self.log_manager.info(f"  DX Suite Atypical Read API success. Response: {response_json}", context=f"{log_ctx_prefix}_LIVE_READ")
                reception_id = response_json.get("receptionId")
                if not reception_id: return None, {"message": "DX Suite 非定型 読取登録APIレスポンスにreceptionIdが含まれていません。", "code": "DXSUITE_ATYPICAL_NO_RECEPTIONID", "detail": response_json}
                
                # OcrWorkerに渡す情報
                return {"receptionId": reception_id, "status": "registered"}, None

            except requests.exceptions.HTTPError as e_http:
                err_msg = f"DX Suite 非定型API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_READ_HTTP_ERROR", exc_info=True)
                try: err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; return None, {"message": f"DX Suite APIエラー: {api_err_detail.get('message', detail_text)}", "code": f"DXSUITE_API_{api_err_detail.get('errorCode', 'UNKNOWN')}", "detail": err_json}
                except ValueError: return None, {"message": err_msg, "code": "DXSUITE_ATYPICAL_HTTP_ERROR_NON_JSON", "detail": detail_text}
            except requests.exceptions.RequestException as e_req: return None, {"message": "DX Suite 非定型APIリクエスト失敗。", "code": "DXSUITE_ATYPICAL_REQUEST_FAIL", "detail": str(e_req)}
            except Exception as e_generic: return None, {"message": "DX Suite 非定型読取登録処理中に予期せぬエラー。", "code": "DXSUITE_ATYPICAL_UNEXPECTED_ERROR", "detail": str(e_generic)}
            finally:
                if file_obj and not file_obj.closed:
                    try: file_obj.close()
                    except Exception as e_close: self.log_manager.warning(f"非定型API用一時ファイルのクローズに失敗: {e_close}", context=log_ctx_prefix)

    def get_ocr_result(self, reception_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 非定型APIの読取結果を取得する。"""
        log_ctx_prefix = "API_DX_ATYPICAL_V2"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Atypical V2 - GetResult): receptionId={reception_id}", context=f"{log_ctx_prefix}_LIVE_GETRESULT")
        
        if self.api_execution_mode != "live":
            return None, {"message": "get_ocr_resultはLiveモード専用です。", "code": "METHOD_LIVE_ONLY_ERROR"}

        url = self._get_full_url("get_ocr_result")
        if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Atypical GetResult)", "code": "CONFIG_ENDPOINT_URL_FAIL_ATYPICAL_GET"}
        if "{組織固有}" in url: return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key: return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        params = {"receptionId": reception_id}
        
        try:
            self.log_manager.debug(f"  GET from {url} with headers: {list(headers.keys())}, params: {params}", context=f"{log_ctx_prefix}_LIVE_GETRESULT")
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_json = response.json()
            self.log_manager.info(f"  DX Suite Atypical GetResult API success. Status: {response_json.get('status')}", context=f"{log_ctx_prefix}_LIVE_GETRESULT")
            return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 非定型 結果取得API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_GETRESULT_HTTP_ERROR", exc_info=True)
            try:
                err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; return None, {"message": f"DX Suite APIエラー: {api_err_detail.get('message', detail_text)}", "code": f"DXSUITE_API_{api_err_detail.get('errorCode', 'UNKNOWN')}", "detail": err_json}
            except ValueError: return None, {"message": err_msg, "code": "DXSUITE_ATYPICAL_GET_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req:
            return None, {"message": "DX Suite 非定型 結果取得APIリクエスト失敗。", "code": "DXSUITE_ATYPICAL_GET_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic:
            return None, {"message": "DX Suite 非定型 結果取得処理中に予期せぬエラー。", "code": "DXSUITE_ATYPICAL_GET_UNEXPECTED_ERROR", "detail": str(e_generic)}

    def delete_job(self, reception_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """DX Suite 非定型APIのジョブを削除する。"""
        log_ctx_prefix = "API_DX_ATYPICAL_V2_DELETE"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (DX Suite Atypical V2 - Delete): receptionId={reception_id}", context=log_ctx_prefix)

        if self.api_execution_mode == "demo":
            self.log_manager.info(f"  Demoモード: '{reception_id}' の削除をシミュレートします。", context=log_ctx_prefix)
            if "error" in reception_id.lower():
                err_detail = {"message": f"Demo: 受付ID '{reception_id}' の削除に失敗しました（シミュレートされたエラー）。", "errorCode": "MOCK_DELETE_FAIL"}
                return None, {"message": "削除APIデモエラー", "code": "DX_ATYPICAL_DEMO_DELETE_ERROR", "detail": err_detail}
            return {"receptionId": reception_id, "status": "deleted_successfully"}, None

        url = self._get_full_url("delete_ocr")
        if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Atypical Delete)", "code": "CONFIG_ENDPOINT_URL_FAIL_ATYPICAL_DELETE"}
        if "{組織固有}" in url: return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key: return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。", "code": "API_KEY_MISSING_LIVE_DX_DELETE"}

        headers = {**self._get_request_headers(), "Content-Type": "application/json"}
        request_body = {"receptionId": reception_id}

        try:
            self.log_manager.debug(f"  POST to {url} with headers: {list(headers.keys())}, body: {request_body}", context=log_ctx_prefix)
            response = requests.post(url, headers=headers, json=request_body, timeout=self.timeout_seconds)
            response.raise_for_status()
            self.log_manager.info(f"  DX Suite Atypical Delete API success. Status Code: {response.status_code}", context=log_ctx_prefix)
            return {"receptionId": reception_id, "status": "deleted_successfully"}, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 非定型 削除API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text
            self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_HTTP_ERROR", exc_info=True)
            try:
                err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]
                return None, {"message": f"DX Suite APIエラー: {api_err_detail.get('message', detail_text)}", "code": f"DXSUITE_API_{api_err_detail.get('errorCode', 'UNKNOWN_DELETE_ERROR')}", "detail": err_json}
            except ValueError:
                return None, {"message": err_msg, "code": "DXSUITE_ATYPICAL_DELETE_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req:
            return None, {"message": "DX Suite 非定型 削除APIリクエスト失敗。", "code": "DXSUITE_ATYPICAL_DELETE_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic:
            return None, {"message": "DX Suite 非定型 削除処理中に予期せぬエラー。", "code": "DXSUITE_ATYPICAL_DELETE_UNEXPECTED_ERROR", "detail": str(e_generic)}

    def make_searchable_pdf(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
        """非定型OCRプロファイルではサーチャブルPDF作成はサポートされていません。"""
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.warning(f"このAPIプロファイル({profile_name})は、サーチャブルPDF作成をサポートしていません。", context="API_CLIENT_WARN")
        return None, {"message": f"このAPIプロファイル({profile_name})では、サーチャブルPDF作成はサポートされていません。", "code": f"NOT_SUPPORTED_dx_atypical_v2_flow_PDF"}
