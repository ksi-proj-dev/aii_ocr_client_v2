# api_client_standard.py (修正版)

import os
import random
import requests
from typing import Optional, Dict, Any, Tuple, List

from config_manager import ConfigManager


class OCRApiClientStandard:
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
        self.log_manager.info("StandardApiClient: 設定更新中...", context="API_CLIENT_CONFIG_UPDATE")
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
                self.log_manager.warning(f"StandardApiClient: current_api_profile_id '{current_profile_id_from_config}' のスキーマが見つからないため、最初のプロファイルを使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else:
                self.active_api_profile_schema = {}
                self.log_manager.error("StandardApiClient: 設定にAPIプロファイルがありません。", context="API_CLIENT_CONFIG_UPDATE_ERROR")
        else:
            self.active_api_profile_schema = {}
            self.log_manager.error("StandardApiClient: update_configにプロファイルスキーマもIDも渡されませんでした。", context="API_CLIENT_CONFIG_UPDATE_ERROR")

        self.active_options_values = ConfigManager.get_active_api_options_values(self.config)
        if self.active_options_values is None:
            self.active_options_values = {}
            self.log_manager.warning("StandardApiClient: アクティブプロファイルのオプション値が取得できませんでした。", context="API_CLIENT_CONFIG_UPDATE")

        self.api_execution_mode = self.config.get("api_execution_mode", "demo")
        self.api_key = self.active_options_values.get("api_key", "")

        profile_name_for_log = self.active_api_profile_schema.get('name', 'N/A')
        key_status_log = "設定あり" if self.api_key else "未設定"
        base_uri_for_log = self.active_options_values.get("base_uri", self.active_api_profile_schema.get("base_uri", "未設定"))

        if self.api_execution_mode == "live":
            self.log_manager.info(f"StandardApiClientは Liveモード ({profile_name_for_log}, APIキー: {key_status_log}, BaseURI: {base_uri_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info(f"StandardApiClientは Demoモード ({profile_name_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")

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
        log_ctx_prefix = "API_DX_STANDARD_V2"
        
        # 必須パラメータのチェック
        workflow_id = effective_options.get("workflowId")
        if not workflow_id or not str(workflow_id).strip():
            return None, {"message": "必須パラメータ 'ワークフローID' が設定されていません。", "code": "DX_STANDARD_WORKFLOWID_MISSING"}

        # Demoモード
        if self.api_execution_mode == "demo":
            self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Standard V2): {file_name}", context=f"{log_ctx_prefix}_DEMO")
            self.log_manager.debug(f"  Simulating Unit Register with workflowId: {workflow_id}", context=f"{log_ctx_prefix}_DEMO")
            
            dummy_unit_id = f"demo-unit-{random.randint(100000, 999999)}"
            self.log_manager.info(f"  Simulated Unit Register success. unitId: {dummy_unit_id}", context=f"{log_ctx_prefix}_DEMO")
            
            # OcrWorkerにポーリングを依頼するための情報を返す
            return {"unitId": dummy_unit_id, "status": "registered"}, None

        # Liveモード
        else:
            self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Standard V2 - Register Unit): {file_name}", context=f"{log_ctx_prefix}_LIVE_REGISTER")
            
            register_url_template = self._get_full_url("register_ocr")
            if not register_url_template:
                return None, {"message": "エンドポイントURL取得失敗 (DX Suite Standard Register)", "code": "CONFIG_ENDPOINT_URL_FAIL_STANDARD_REG"}
            
            register_url = register_url_template.replace("{workflowId}", str(workflow_id))

            if "{組織固有}" in register_url or "{organization_specific_domain}" in register_url:
                self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {register_url}", context="API_CLIENT_CONFIG_ERROR")
                return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}

            if not self.api_key:
                err_msg = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER", error_code="API_KEY_MISSING_LIVE")
                return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}

            headers = self._get_request_headers()
            data_payload = {}
            
            if effective_options.get("unitName"):
                data_payload['unitName'] = effective_options.get("unitName")

            file_obj = None
            try:
                file_obj = open(file_path, 'rb')
                files_payload = {'files': (os.path.basename(file_path), file_obj, 'application/octet-stream')}
                
                self.log_manager.debug(f"  POST to {register_url} with form-data: {data_payload}, file: {file_name}", context=f"{log_ctx_prefix}_LIVE_REGISTER")
                response_register = requests.post(register_url, headers=headers, data=data_payload, files=files_payload, timeout=self.timeout_seconds)
                response_register.raise_for_status()
                
                register_json = response_register.json()
                unit_id = register_json.get("unitId")
                if not unit_id:
                    return None, {"message": "ユニット登録APIレスポンスにunitIdが含まれていません。", "code": "DX_STANDARD_NO_UNITID", "detail": register_json}
                
                self.log_manager.info(f"  ユニット登録成功。unitId: {unit_id}", context=f"{log_ctx_prefix}_LIVE_REGISTER")

                # OcrWorkerにポーリングを依頼するための情報を返す
                return {"unitId": unit_id, "status": "registered"}, None

            except requests.exceptions.HTTPError as e_http:
                err_msg = f"DX Suite 標準 登録API HTTPエラー: {e_http.response.status_code}"
                detail_text = e_http.response.text
                self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_REGISTER_HTTP_ERROR", exc_info=True)
                try:
                    err_json = e_http.response.json()
                    api_err_detail = err_json.get("errors", [{}])[0]
                    api_err_code = api_err_detail.get("errorCode", "UNKNOWN_API_ERROR")
                    api_err_msg_from_json = api_err_detail.get("message", detail_text)
                    return None, {"message": f"DX Suite APIエラー: {api_err_msg_from_json}", "code": f"DXSUITE_API_{api_err_code}", "detail": err_json}
                except ValueError:
                    return None, {"message": f"DX Suite 標準 登録API HTTPエラー (非JSON応答): {e_http.response.status_code}", "code": "DXSUITE_STANDARD_HTTP_ERROR_NON_JSON", "detail": detail_text}
            except requests.exceptions.RequestException as e_req:
                err_msg = f"DX Suite 標準 登録APIリクエストエラー: {e_req}"
                self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER_REQUEST_ERROR", exc_info=True)
                return None, {"message": "DX Suite 標準 登録APIリクエスト失敗。", "code": "DXSUITE_STANDARD_REGISTER_REQUEST_FAIL", "detail": str(e_req)}
            except Exception as e:
                self.log_manager.error(f"ユニット登録APIでエラー: {e}", context=f"{log_ctx_prefix}_LIVE_REGISTER_ERROR", exc_info=True)
                return None, {"message": f"ユニット登録APIでエラー: {e}", "code": "DX_STANDARD_REGISTER_FAIL"}
            finally:
                if file_obj and not file_obj.closed: file_obj.close()

    def get_status(self, unit_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIのユニット状態を取得する。"""
        log_ctx_prefix = "API_DX_STANDARD_STATUS"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (GetStatus): unitId={unit_id}", context=f"{log_ctx_prefix}")

        if self.api_execution_mode == "demo":
            self.log_manager.debug(f"  Demoモード: '{unit_id}' の状態取得をシミュレートします。", context=log_ctx_prefix)
            return [{"unitId": unit_id, "dataProcessingStatus": 400}], None

        headers = self._get_request_headers()
        if not headers:
            return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        url = self._get_full_url("get_ocr_status")
        if not url:
            return None, {"message": "エンドポイントURL取得失敗 (GetStatus)", "code": "CONFIG_ENDPOINT_URL_FAIL_STATUS"}

        params = {"unitId": unit_id}
        try:
            self.log_manager.debug(f"  GET from {url} with params: {params}", context=log_ctx_prefix)
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_json = response.json()
            if isinstance(response_json, list) and response_json:
                self.log_manager.info(f"  DX Suite Standard GetStatus API success. Status: {response_json[0].get('dataProcessingStatus')}", context=log_ctx_prefix)
            return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 標準 状態取得API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text;
            return None, {"message": err_msg, "code": "DXSUITE_STATUS_HTTP_ERROR", "detail": detail_text}
        except Exception as e:
            return None, {"message": f"DX Suite 標準 状態取得で予期せぬエラー: {e}", "code": "DXSUITE_STATUS_UNEXPECTED_ERROR", "detail": str(e)}

    def get_result(self, unit_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIのOCR結果を取得する。"""
        log_ctx_prefix = "API_DX_STANDARD_RESULT"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (GetResult): unitId={unit_id}", context=f"{log_ctx_prefix}")

        if self.api_execution_mode == "demo":
            self.log_manager.debug(f"  Demoモード: '{unit_id}' の結果取得をシミュレートします。", context=log_ctx_prefix)
            return {
                "dataItems": [
                    {"dataItemId": "demo-item-1", "result": "株式会社デモ", "columnName": "会社名", "accuracy": 0.99},
                    {"dataItemId": "demo-item-2", "result": "11,000", "columnName": "合計金額", "accuracy": 0.98}
                ]
            }, None

        url = self._get_full_url("get_ocr_result")
        if not url:
            return None, {"message": "エンドポイントURL取得失敗 (DX Suite Standard GetResult)", "code": "CONFIG_ENDPOINT_URL_FAIL_STANDARD_RESULT"}

        if not self.api_key:
            return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        params = {"unitId": unit_id}
        
        try:
            self.log_manager.debug(f"  GET from {url} with params: {params}", context=log_ctx_prefix)
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_json = response.json()
            self.log_manager.info(f"  DX Suite Standard GetResult API success.", context=log_ctx_prefix)
            return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 標準 結果取得API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text;
            return None, {"message": err_msg, "code": "DXSUITE_RESULT_HTTP_ERROR", "detail": detail_text}
        except Exception as e:
            return None, {"message": f"DX Suite 標準 結果取得で予期せぬエラー: {e}", "code": "DXSUITE_RESULT_UNEXPECTED_ERROR", "detail": str(e)}

    def delete_job(self, unit_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIのユニットを削除する。"""
        log_ctx_prefix = "API_DX_STANDARD_DELETE"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (Delete): unitId={unit_id}", context=log_ctx_prefix)

        if self.api_execution_mode == "demo":
            self.log_manager.info(f"  Demoモード: '{unit_id}' の削除をシミュレートします。", context=log_ctx_prefix)
            return {"unitId": unit_id, "status": "deleted_successfully"}, None

        url_template = self._get_full_url("delete_ocr")
        if not url_template:
            return None, {"message": "エンドポイントURL取得失敗 (DX Suite Standard Delete)", "code": "CONFIG_ENDPOINT_URL_FAIL_STANDARD_DELETE"}
        
        url = url_template.replace("{unitId}", str(unit_id))

        if not self.api_key:
            return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        
        try:
            self.log_manager.debug(f"  POST to {url}", context=log_ctx_prefix)
            response = requests.post(url, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_json = response.json()
            self.log_manager.info(f"  DX Suite Standard Delete API success. Response: {response_json}", context=log_ctx_prefix)
            return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 標準 削除API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text;
            return None, {"message": err_msg, "code": "DXSUITE_DELETE_HTTP_ERROR", "detail": detail_text}
        except Exception as e:
            return None, {"message": f"DX Suite 標準 削除処理中に予期せぬエラー: {e}", "code": "DXSUITE_DELETE_UNEXPECTED_ERROR", "detail": str(e)}

    def search_workflows(self, workflow_name: Optional[str] = None) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIでワークフローを検索する。"""
        log_ctx_prefix = "API_DX_STANDARD_WF_SEARCH"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (Workflow Search)", context=log_ctx_prefix)

        if self.api_execution_mode == "demo":
            self.log_manager.debug(f"  Demoモード: ワークフロー検索をシミュレートします。", context=log_ctx_prefix)
            dummy_workflows = {
                "workflows": [
                    {"workflowId": "demo-wf-uuid-001", "folderId": "demo-folder-1", "name": "【デモ】請求書ワークフロー"},
                    {"workflowId": "demo-wf-uuid-002", "folderId": "demo-folder-1", "name": "【デモ】注文書ワークフロー"},
                ]
            }
            if workflow_name:
                dummy_workflows["workflows"] = [ wf for wf in dummy_workflows["workflows"] if workflow_name in wf["name"] ]
            return dummy_workflows, None

        # Liveモード
        base_uri_from_endpoint = self._get_full_url("register_ocr")
        if not base_uri_from_endpoint:
            return None, {"message": "ワークフロー検索用URLのベース取得に失敗", "code": "WF_SEARCH_URL_FAIL"}
        base_uri = base_uri_from_endpoint.split('/workflows/')[0]
        url = f"{base_uri}/workflows"

        if not self.api_key:
            return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        params = {}
        if workflow_name:
            params["workflowName"] = workflow_name
        
        try:
            self.log_manager.debug(f"  GET from {url} with params: {params}", context=log_ctx_prefix)
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_json = response.json()
            self.log_manager.info(f"  DX Suite Workflow Search API success.", context=log_ctx_prefix)
            return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite ワークフロー検索API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text;
            return None, {"message": err_msg, "code": "DXSUITE_WF_SEARCH_HTTP_ERROR", "detail": detail_text}
        except Exception as e:
            return None, {"message": f"DX Suite ワークフロー検索で予期せぬエラー: {e}", "code": "DXSUITE_WF_SEARCH_UNEXPECTED_ERROR", "detail": str(e)}

    def download_standard_csv(self, unit_id: str) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIで、指定したユニットのCSVをダウンロードする。"""
        log_ctx_prefix = "API_DX_STANDARD_CSV"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (Download CSV): unitId={unit_id}", context=log_ctx_prefix)

        if self.api_execution_mode == "demo":
            self.log_manager.debug(f"  Demoモード: '{unit_id}' のCSVダウンロードをシミュレートします。", context=log_ctx_prefix)
            dummy_csv_data = '"請求日","請求金額","会社名"\n"2025/06/27","11000","株式会社デモ"\n'
            return dummy_csv_data.encode('utf-8-sig'), None

        url_template = self._get_full_url("download_csv")
        if not url_template:
            return None, {"message": "エンドポイントURL取得失敗 (Download CSV)", "code": "CONFIG_ENDPOINT_URL_FAIL_CSV"}
        
        url = url_template.replace("{unitId}", str(unit_id))

        if not self.api_key:
            return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        
        try:
            self.log_manager.debug(f"  GET from {url}", context=log_ctx_prefix)
            response = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', '')
            if 'text/csv' in content_type:
                self.log_manager.info(f"  DX Suite Download CSV API success.", context=log_ctx_prefix)
                return response.content, None
            else:
                err_msg = f"APIがCSVを返しませんでした (Content-Type: {content_type})。"
                return None, {"message": err_msg, "code": "API_UNEXPECTED_CONTENT_TYPE_CSV", "detail": response.text[:500]}

        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite CSVダウンロードAPI HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text
            return None, {"message": err_msg, "code": "DXSUITE_CSV_HTTP_ERROR", "detail": detail_text}
        except Exception as e:
            return None, {"message": f"DX Suite CSVダウンロードで予期せぬエラー: {e}", "code": "DXSUITE_CSV_UNEXPECTED_ERROR", "detail": str(e)}

    def add_sort_unit(self, file_paths: List[str], sort_config_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIで仕分けユニットを追加（作成）する"""
        log_ctx_prefix = "API_DX_SORTER_ADD"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (Add Sort Unit)", context=log_ctx_prefix)
        
        if self.api_execution_mode == "demo":
            dummy_sort_unit_id = f"demo-sort-unit-{random.randint(100000, 999999)}"
            return {"sortUnitId": dummy_sort_unit_id, "runSorting": True}, None

        # Liveモード
        base_uri_from_endpoint = self._get_full_url("register_ocr")
        if not base_uri_from_endpoint: return None, {"message": "仕分けユニット追加用URLのベース取得失敗", "code": "SORTER_URL_FAIL"}
        base_uri = base_uri_from_endpoint.split('/workflows/')[0]
        url = f"{base_uri}/sorter/add"

        if not self.api_key: return None, {"message": "APIキーが設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        data_payload = { "sortConfigId": sort_config_id, "runSorting": "true" }
        
        files_payload = []
        opened_files = []
        try:
            for path in file_paths:
                f_obj = open(path, 'rb')
                opened_files.append(f_obj)
                files_payload.append(('files', (os.path.basename(path), f_obj, 'application/octet-stream')))
            
            response = requests.post(url, headers=headers, data=data_payload, files=files_payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json(), None
        except Exception as e:
            return None, {"message": f"仕分けユニット追加APIでエラー: {e}", "code": "SORTER_ADD_FAIL", "detail": str(e)}
        finally:
            for f_obj in opened_files:
                if f_obj: f_obj.close()

    def get_sort_unit_status(self, sort_unit_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIで仕分けユニットの状態を取得する"""
        log_ctx_prefix = "API_DX_SORTER_STATUS"
        
        # === 修正箇所 START ===
        if self.api_execution_mode == "demo":
            # 後続のOCR処理をシミュレートできるよう、ダミーのOCRユニットIDを含む応答を返す
            dummy_ocr_unit_id_1 = f"demo-ocr-unit-{random.randint(1000, 9999)}"
            dummy_ocr_unit_id_2 = f"demo-ocr-unit-{random.randint(1000, 9999)}"
            return {
                "statusCode": 60,
                "statusName": "仕分け完了",
                "statusList": [
                    {
                        "documentId": f"demo-doc-{random.randint(100,999)}",
                        "readingUnitId": dummy_ocr_unit_id_1,
                        "workflowId": "demo-workflow-id-1",
                        "workflowName": "【デモ】請求書"
                    },
                    {
                        "documentId": f"demo-doc-{random.randint(100,999)}",
                        "readingUnitId": dummy_ocr_unit_id_2,
                        "workflowId": "demo-workflow-id-2",
                        "workflowName": "【デモ】領収書"
                    },
                    {
                        "documentId": f"demo-doc-{random.randint(100,999)}",
                        "readingUnitId": "0", # 仕分けされなかったファイルのシミュレーション
                        "workflowId": "0",
                        "workflowName": ""
                    }
                ]
            }, None
        # === 修正箇所 END ===

        # Liveモード
        base_uri_from_endpoint = self._get_full_url("register_ocr")
        if not base_uri_from_endpoint: return None, {"message": "仕分け状態取得用URLのベース取得失敗", "code": "SORTER_STATUS_URL_FAIL"}
        base_uri = base_uri_from_endpoint.split('/workflows/')[0]
        url = f"{base_uri}/sorter/status"

        if not self.api_key: return None, {"message": "APIキーが設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        data_payload = {"sortUnitId": sort_unit_id}
        
        try:
            response = requests.post(url, headers=headers, data=data_payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json(), None
        except Exception as e:
            return None, {"message": f"仕分けユニット状態取得APIでエラー: {e}", "code": "SORTER_STATUS_FAIL", "detail": str(e)}

    def send_sort_result_to_ocr(self, sort_unit_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """DX Suite 標準APIで、仕分け結果をOCRへ送信する"""
        log_ctx_prefix = "API_DX_SORTER_SENDOCR"
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.info(f"'{profile_name}' API呼び出し開始 (Send Sort Result to OCR): sortUnitId={sort_unit_id}", context=log_ctx_prefix)
        
        if self.api_execution_mode == "demo":
            self.log_manager.debug(f"  Demoモード: '{sort_unit_id}' のOCR送信をシミュレートします。", context=log_ctx_prefix)
            return {"sortUnitId": sort_unit_id, "status": "sent_to_ocr_successfully"}, None

        # Liveモード
        base_uri_from_endpoint = self._get_full_url("register_ocr")
        if not base_uri_from_endpoint: return None, {"message": "OCR送信API用URLのベース取得失敗", "code": "SEND_OCR_URL_FAIL"}
        base_uri = base_uri_from_endpoint.split('/workflows/')[0]
        url = f"{base_uri}/sorter/sendOcr"

        if not self.api_key: return None, {"message": "APIキーが設定されていません。", "code": "API_KEY_MISSING_LIVE"}

        headers = self._get_request_headers()
        data_payload = {"sortUnitId": sort_unit_id}
        
        try:
            response = requests.post(url, headers=headers, data=data_payload, timeout=self.timeout_seconds)
            response.raise_for_status()
            return response.json(), None
        except Exception as e:
            return None, {"message": f"仕分け結果OCR送信APIでエラー: {e}", "code": "SORTER_SENDOCR_FAIL", "detail": str(e)}
            
    def make_searchable_pdf(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
        """標準OCRプロファイルではサーチャブルPDF作成はサポートされていません。"""
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        self.log_manager.warning(f"このAPIプロファイル({profile_name})は、サーチャブルPDF作成をサポートしていません。", context="API_CLIENT_WARN")
        return None, {"message": f"このAPIプロファイル({profile_name})では、サーチャブルPDF作成はサポートされていません。", "code": f"NOT_SUPPORTED_dx_standard_v2_flow_PDF"}
