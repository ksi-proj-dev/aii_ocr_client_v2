# api_client_fulltext.py

import os
import time
import random
import requests
from PyPDF2 import PdfWriter
import io
import json
from typing import Optional, Dict, Any, Tuple

from config_manager import ConfigManager


class OCRApiClientFulltext:
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
        self.log_manager.info("FulltextApiClient: 設定更新中...", context="API_CLIENT_CONFIG_UPDATE")
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
                self.log_manager.warning(f"FulltextApiClient: current_api_profile_id '{current_profile_id_from_config}' のスキーマが見つからないため、最初のプロファイルを使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else:
                self.active_api_profile_schema = {}
                self.log_manager.error("FulltextApiClient: 設定にAPIプロファイルがありません。", context="API_CLIENT_CONFIG_UPDATE_ERROR")
        else:
            self.active_api_profile_schema = {}
            self.log_manager.error("FulltextApiClient: update_configにプロファイルスキーマもIDも渡されませんでした。", context="API_CLIENT_CONFIG_UPDATE_ERROR")

        self.active_options_values = ConfigManager.get_active_api_options_values(self.config)
        if self.active_options_values is None:
            self.active_options_values = {}
            self.log_manager.warning("FulltextApiClient: アクティブプロファイルのオプション値が取得できませんでした。", context="API_CLIENT_CONFIG_UPDATE")

        self.api_execution_mode = self.config.get("api_execution_mode", "demo")
        self.api_key = self.active_options_values.get("api_key", "")

        profile_name_for_log = self.active_api_profile_schema.get('name', 'N/A')
        key_status_log = "設定あり" if self.api_key else "未設定"
        base_uri_for_log = self.active_options_values.get("base_uri", self.active_api_profile_schema.get("base_uri", "未設定"))

        if self.api_execution_mode == "live":
            self.log_manager.info(f"FulltextApiClientは Liveモード ({profile_name_for_log}, APIキー: {key_status_log}, BaseURI: {base_uri_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info(f"FulltextApiClientは Demoモード ({profile_name_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")

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
        log_ctx_prefix = "API_DX_FULLTEXT_V2"

        if self.api_execution_mode == "demo":
            self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Fulltext V2 - Simulate Register & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER"); concatenate_opt = effective_options.get("concatenate", 0); char_extract_opt = effective_options.get("characterExtraction", 0); table_extract_opt = effective_options.get("tableExtraction", 1); self.log_manager.debug(f"  Simulating Register with options: concatenate={concatenate_opt}, characterExtraction={char_extract_opt}, tableExtraction={table_extract_opt}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
            if file_name.startswith("error_dx_register_"): error_code = "DUMMY_DX_REGISTER_ERROR"; error_msg = f"Demo DX Suite 登録エラー: {file_name}"; self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name); return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX Suite登録APIエラーです。"}
            dummy_full_ocr_job_id = f"demo-dx-ocr-job-{random.randint(10000, 99999)}"; self.log_manager.info(f"  Simulated Register success. fullOcrJobId: {dummy_full_ocr_job_id}", context=f"{log_ctx_prefix}_DEMO_REGISTER"); time.sleep(random.uniform(0.2, 0.5)); self.log_manager.info(f"  Simulating GetResult for fullOcrJobId: {dummy_full_ocr_job_id}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
            if file_name.startswith("error_dx_getresult_"): error_code = "DUMMY_DX_GETRESULT_ERROR"; error_msg = f"Demo DX Suite 結果取得エラー: {file_name}"; self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name); return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX Suite結果取得APIエラーです。"}
            demo_ocr_result_block = {"text": f"これは {file_name} のデモテキストです。", "bbox": {"top": 0.1, "bottom": 0.2, "left": 0.1, "right": 0.8}, "vertices": [{"x":0.1, "y":0.1}, {"x":0.8, "y":0.1}, {"x":0.8, "y":0.2}, {"x":0.1, "y":0.2}]};
            if char_extract_opt == 1: demo_ocr_result_block["characters"] = [{"char": "こ", "ocrConfidence": 0.95, "bbox": {"top":0.1, "bottom":0.2,"left":0.1,"right":0.12}}, {"char": "れ", "ocrConfidence": 0.98, "bbox": {"top":0.1, "bottom":0.2,"left":0.12,"right":0.14}}]
            demo_page_result = {"pageNum": 1, "ocrSuccess": True, "fulltext": f"これは {file_name} の全文デモテキストです。結合:{'ON' if concatenate_opt==1 else 'OFF'} 文字抽出:{'ON' if char_extract_opt==1 else 'OFF'} 表抽出:{'ON' if table_extract_opt==1 else 'OFF'}.", "ocrResults": [demo_ocr_result_block], "tables": []};
            if table_extract_opt == 1: demo_page_result["tables"].append({"bbox": {"top": 0.3, "bottom": 0.6, "left": 0.1, "right": 0.9}, "confidence": 0.98, "cells": [{"row_index":0, "col_index":0, "text":"ヘッダ1"}, {"row_index":0, "col_index":1, "text":"ヘッダ2"}]})
            final_json_response_listwrapper = {"status": "done", "results": [{"fileName": file_name, "fileSuccess": True, "pages": [demo_page_result]}]}; self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (DX Suite Fulltext V2): {file_name}", context=f"{log_ctx_prefix}_DEMO_GETRESULT"); return final_json_response_listwrapper, None
        else: # Live モード
            self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Fulltext V2 - Register): {file_name}", context=f"{log_ctx_prefix}_LIVE_REGISTER"); url = self._get_full_url("register_ocr")
            if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Register OCR)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
            if "{組織固有}" in url or "{organization_specific_domain}" in url: self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR"); return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
            if not self.api_key: err_msg = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER", error_code="API_KEY_MISSING_LIVE"); return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}
            headers = self._get_request_headers(); payload_data = {"concatenate": str(effective_options.get("concatenate", 0)), "characterExtraction": str(effective_options.get("characterExtraction", 0)), "tableExtraction": str(effective_options.get("tableExtraction", 1))}; file_obj = None
            try:
                file_obj = open(file_path, 'rb'); files_data = {'file': (os.path.basename(file_path), file_obj)}; self.log_manager.debug(f"  POST to {url} with headers: {list(headers.keys())}, form-data: {payload_data}, file: {file_name}", context=f"{log_ctx_prefix}_LIVE_REGISTER"); response = requests.post(url, headers=headers, data=payload_data, files=files_data, timeout=self.timeout_seconds); response.raise_for_status(); response_json = response.json(); self.log_manager.info(f"  DX Suite Register API success. Response: {response_json}", context=f"{log_ctx_prefix}_LIVE_REGISTER"); job_id = response_json.get("id")
                if not job_id: self.log_manager.error(f"  DX Suite Register API response missing 'id'. Response: {response_json}", context=f"{log_ctx_prefix}_LIVE_REGISTER_ERROR"); return None, {"message": "DX Suite 登録APIレスポンスにIDが含まれていません。", "code": "DXSUITE_REGISTER_NO_ID", "detail": response_json}
                
                # OcrWorkerに渡す情報
                return {"job_id": job_id, "status": "ocr_registered"}, None

            except requests.exceptions.HTTPError as e_http:
                err_msg = f"DX Suite 登録API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_REGISTER_HTTP_ERROR", exc_info=True)
                try: err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; api_err_code = api_err_detail.get("errorCode", "UNKNOWN_API_ERROR"); api_err_msg_from_json = api_err_detail.get("message", detail_text); return None, {"message": f"DX Suite APIエラー: {api_err_msg_from_json}", "code": f"DXSUITE_API_{api_err_code}", "detail": err_json}
                except ValueError: return None, {"message": f"DX Suite 登録API HTTPエラー (非JSON応答): {e_http.response.status_code}", "code": "DXSUITE_REGISTER_HTTP_ERROR_NON_JSON", "detail": detail_text}
            except requests.exceptions.RequestException as e_req: err_msg = f"DX Suite 登録APIリクエストエラー: {e_req}"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER_REQUEST_ERROR", exc_info=True); return None, {"message": "DX Suite 登録APIリクエスト失敗。", "code": "DXSUITE_REGISTER_REQUEST_FAIL", "detail": str(e_req)}
            except Exception as e_generic: err_msg = f"DX Suite 登録API処理中に予期せぬエラー: {e_generic}"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER_UNEXPECTED_ERROR", exc_info=True); return None, {"message": "DX Suite 登録処理中に予期せぬエラー。", "code": "DXSUITE_REGISTER_UNEXPECTED_ERROR", "detail": str(e_generic)}
            finally:
                if file_obj and not file_obj.closed:
                    try: file_obj.close()
                    except Exception as e_close: self.log_manager.warning(f"DX Suite Register用一時ファイルのクローズに失敗: {e_close}", context=f"{log_ctx_prefix}_LIVE_REGISTER")

    def get_ocr_result(self, job_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        log_ctx_prefix = "API_DX_FULLTEXT_V2"; profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"; self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Fulltext V2 - GetResult): job_id={job_id}", context=f"{log_ctx_prefix}_LIVE_GETRESULT"); url = self._get_full_url("get_ocr_result")
        if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Get OCR Result)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
        if "{組織固有}" in url or "{organization_specific_domain}" in url: self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR"); return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key: err_msg = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_GETRESULT", error_code="API_KEY_MISSING_LIVE"); return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}
        headers = self._get_request_headers(); params = {"id": job_id}
        try:
            self.log_manager.debug(f"  GET from {url} with headers: {list(headers.keys())}, params: {params}", context=f"{log_ctx_prefix}_LIVE_GETRESULT"); response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds); response.raise_for_status(); response_json = response.json(); self.log_manager.info(f"  DX Suite GetResult API success. Status: {response_json.get('status')}", context=f"{log_ctx_prefix}_LIVE_GETRESULT"); return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 結果取得API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_GETRESULT_HTTP_ERROR", exc_info=True)
            try: err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; api_err_code = api_err_detail.get("errorCode", "UNKNOWN_API_ERROR"); api_err_msg_from_json = api_err_detail.get("message", detail_text); return None, {"message": f"DX Suite APIエラー: {api_err_msg_from_json}", "code": f"DXSUITE_API_{api_err_code}", "detail": err_json}
            except ValueError: return None, {"message": f"DX Suite 結果取得API HTTPエラー (非JSON応答): {e_http.response.status_code}", "code": "DXSUITE_GETRESULT_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req: err_msg = f"DX Suite 結果取得APIリクエストエラー: {e_req}"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_GETRESULT_REQUEST_ERROR", exc_info=True); return None, {"message": "DX Suite 結果取得APIリクエスト失敗。", "code": "DXSUITE_GETRESULT_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic: err_msg = f"DX Suite 結果取得API処理中に予期せぬエラー: {e_generic}"; self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_GETRESULT_UNEXPECTED_ERROR", exc_info=True); return None, {"message": "DX Suite 結果取得処理中に予期せぬエラー。", "code": "DXSUITE_GETRESULT_UNEXPECTED_ERROR", "detail": str(e_generic)}

    def delete_job(self, full_ocr_job_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        log_ctx_prefix = "API_DX_FULLTEXT_V2_DELETE"; profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"; self.log_manager.info(f"'{profile_name}' API呼び出し開始 (DX Suite Fulltext V2 - Delete): fullOcrJobId={full_ocr_job_id}", context=log_ctx_prefix)
        
        if self.api_execution_mode == "demo":
            self.log_manager.info(f"  Demoモード: '{full_ocr_job_id}' の削除をシミュレートします。", context=log_ctx_prefix)
            if "error" in full_ocr_job_id.lower():
                err_detail = {"message": f"Demo: ジョブID '{full_ocr_job_id}' の削除に失敗しました（シミュレートされたエラー）。", "errorCode": "MOCK_DELETE_FAIL"}
                return None, {"message": "削除APIデモエラー", "code": "DXSUITE_DEMO_DELETE_ERROR", "detail": err_detail}
            return {"id": full_ocr_job_id, "status": "deleted_successfully"}, None
        
        url = self._get_full_url("delete_ocr")
        if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Delete OCR)", "code": "CONFIG_ENDPOINT_URL_FAIL_DX_DELETE"}
        if "{組織固有}" in url or "{organization_specific_domain}" in url: self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR"); return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key: return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。", "code": "API_KEY_MISSING_LIVE_DX_DELETE"}
        headers = {**self._get_request_headers(), "Content-Type": "application/json"}; request_body = {"fullOcrJobId": full_ocr_job_id}
        
        try:
            self.log_manager.debug(f"  POST to {url} with headers: {list(headers.keys())}, body: {request_body}", context=log_ctx_prefix); response = requests.post(url, headers=headers, json=request_body, timeout=self.timeout_seconds); response.raise_for_status(); response_json = response.json(); self.log_manager.info(f"  DX Suite Delete OCR API success. Response: {response_json}", context=log_ctx_prefix); return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 削除API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_HTTP_ERROR", exc_info=True)
            try: err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; return None, {"message": f"DX Suite APIエラー: {api_err_detail.get('message', detail_text)}", "code": f"DXSUITE_API_{api_err_detail.get('errorCode', 'UNKNOWN_DELETE_ERROR')}", "detail": err_json}
            except ValueError: return None, {"message": err_msg, "code": "DXSUITE_DELETE_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req: return None, {"message": "DX Suite 削除APIリクエスト失敗。", "code": "DXSUITE_DELETE_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic: return None, {"message": "DX Suite 削除処理中に予期せぬエラー。", "code": "DXSUITE_DELETE_UNEXPECTED_ERROR", "detail": str(e_generic)}

    def make_searchable_pdf(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        file_name = os.path.basename(file_path)
        base_options = self.active_options_values if self.active_options_values is not None else {}
        effective_options = {**base_options, **(specific_options or {})}
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        log_ctx_prefix = "API_DX_FULLTEXT_V2_PDF"
        
        if self.api_execution_mode == "demo":
            self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Searchable PDF V2 - Simulate Register & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
            try: writer = PdfWriter(); writer.add_blank_page(width=595, height=842); bio = io.BytesIO(); writer.write(bio); return bio.getvalue(), None
            except Exception as e_pdf_dummy: self.log_manager.error(f"Demo PDF生成エラー (DX Suite): {e_pdf_dummy}", exc_info=True); return None, {"message": f"Demo DX Suite PDF生成エラー: {e_pdf_dummy}", "code": "DUMMY_DX_PDF_GEN_ERROR", "detail": str(e_pdf_dummy)}
        
        else: # Live モード
            self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Searchable PDF V2 - Register Only): {file_name}", context=f"{log_ctx_prefix}_LIVE")
            
            full_ocr_job_id = effective_options.get("fullOcrJobId")
            if not full_ocr_job_id: 
                return None, {"message": "サーチャブルPDF作成に必要な全文読取ID(fullOcrJobId)が指定されていません。", "code": "DXSUITE_SPDF_MISSING_FULLOCRJOBID"}

            high_res_mode_opt_val = effective_options.get("highResolutionMode", 0)
            try: high_res_mode = int(high_res_mode_opt_val)
            except (ValueError, TypeError): 
                self.log_manager.warning(f"highResolutionModeの値 '{high_res_mode_opt_val}' は不正です。デフォルトの0を使用します。", context=log_ctx_prefix)
                high_res_mode = 0

            spdf_job_id, error_info_register = self._register_dx_searchable_pdf(full_ocr_job_id, high_res_mode)

            if error_info_register: return None, error_info_register
            if not spdf_job_id: return None, {"message": "DX Suite サーチャブルPDFジョブIDの取得に失敗しました。", "code": "DXSUITE_SPDF_JOBID_ACQUISITION_FAIL"}

            self.log_manager.info(f"DX Suite Searchable PDF登録成功。SearchablePdfJobId: {spdf_job_id}。結果取得はWorkerに委ねます。", context=log_ctx_prefix)
            
            # OcrWorkerに渡す情報
            return {"job_id": spdf_job_id, "status": "searchable_pdf_registered"}, None

    def _register_dx_searchable_pdf(self, full_ocr_job_id: str, high_resolution_mode: int) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        log_ctx_prefix = "API_DX_FULLTEXT_V2_PDF_REGISTER"; profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"; self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Searchable PDF - Register): fullOcrJobId={full_ocr_job_id}", context=log_ctx_prefix); url = self._get_full_url("register_searchable_pdf")
        if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Register Searchable PDF)", "code": "CONFIG_ENDPOINT_URL_FAIL_DX_SPDF_REG"}
        if "{組織固有}" in url or "{organization_specific_domain}" in url: self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR"); return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key: return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。", "code": "API_KEY_MISSING_LIVE_DX_SPDF_REG"}
        headers = {**self._get_request_headers(), "Content-Type": "application/json"}; request_body = {"fullOcrJobId": full_ocr_job_id, "highResolutionMode": high_resolution_mode}
        try:
            self.log_manager.debug(f"  POST to {url} with headers: {list(headers.keys())}, body: {request_body}", context=log_ctx_prefix); response = requests.post(url, headers=headers, json=request_body, timeout=self.timeout_seconds); response.raise_for_status(); response_json = response.json(); self.log_manager.info(f"  DX Suite Searchable PDF Register API success. Response: {response_json}", context=log_ctx_prefix); searchable_pdf_job_id = response_json.get("id")
            if not searchable_pdf_job_id: return None, {"message": "DX Suite サーチャブルPDF登録APIレスポンスにIDが含まれていません。", "code": "DXSUITE_SPDF_REGISTER_NO_ID", "detail": response_json}
            return searchable_pdf_job_id, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite サーチャブルPDF登録API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_HTTP_ERROR", exc_info=True)
            try: err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; return None, {"message": f"DX Suite APIエラー: {api_err_detail.get('message', detail_text)}", "code": f"DXSUITE_API_{api_err_detail.get('errorCode', 'UNKNOWN')}", "detail": err_json}
            except ValueError: return None, {"message": err_msg, "code": "DXSUITE_SPDF_REGISTER_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req: return None, {"message": "DX Suite サーチャブルPDF登録APIリクエスト失敗。", "code": "DXSUITE_SPDF_REGISTER_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic: return None, {"message": "DX Suite サーチャブルPDF登録処理中に予期せぬエラー。", "code": "DXSUITE_SPDF_REGISTER_UNEXPECTED_ERROR", "detail": str(e_generic)}

    def get_searchable_pdf_content(self, searchable_pdf_job_id: str) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
        log_ctx_prefix = "API_DX_FULLTEXT_V2_PDF_GET"; profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"; self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Searchable PDF - GetResult): searchablePdfJobId={searchable_pdf_job_id}", context=log_ctx_prefix); url = self._get_full_url("get_searchable_pdf_result")
        if not url: return None, {"message": "エンドポイントURL取得失敗 (DX Suite Get Searchable PDF)", "code": "CONFIG_ENDPOINT_URL_FAIL_DX_SPDF_GET"}
        if "{組織固有}" in url or "{organization_specific_domain}" in url: return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key: return None, {"message": f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。", "code": "API_KEY_MISSING_LIVE_DX_SPDF_GET"}
        headers = self._get_request_headers(); params = {"id": searchable_pdf_job_id}
        try:
            self.log_manager.debug(f"  GET from {url} with headers: {list(headers.keys())}, params: {params}", context=log_ctx_prefix); response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds); response.raise_for_status(); content_type = response.headers.get("Content-Type", "").lower()
            if "application/pdf" in content_type: self.log_manager.info(f"  DX Suite Get Searchable PDF API success. Received PDF binary.", context=log_ctx_prefix); return response.content, None
            elif "application/json" in content_type:
                response_json = response.json(); self.log_manager.info(f"  DX Suite Get Searchable PDF API returned JSON: {response_json}", context=log_ctx_prefix)
                if "status" in response_json: return None, {"message": f"DX Suite PDF処理ステータス: {response_json.get('status')}", "code": f"DXSUITE_SPDF_STATUS_{response_json.get('status','UNKNOWN').upper()}", "detail": response_json}
                return None, {"message": "DX Suite PDF取得APIが予期しないJSONを返しました。", "code": "DXSUITE_SPDF_UNEXPECTED_JSON", "detail": response_json}
            else: return None, {"message": f"DX Suite PDF取得APIが予期しないContent-Type '{content_type}' を返しました。", "code": "DXSUITE_SPDF_UNEXPECTED_CONTENT_TYPE", "detail": response.text[:500]}
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite サーチャブルPDF取得API HTTPエラー: {e_http.response.status_code}"; detail_text = e_http.response.text; self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_HTTP_ERROR", exc_info=True)
            try: err_json = e_http.response.json(); api_err_detail = err_json.get("errors", [{}])[0]; return None, {"message": f"DX Suite APIエラー: {api_err_detail.get('message', detail_text)}", "code": f"DXSUITE_API_{api_err_detail.get('errorCode', 'UNKNOWN')}", "detail": err_json}
            except ValueError: return None, {"message": err_msg, "code": "DXSUITE_SPDF_GET_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req: return None, {"message": "DX Suite サーチャブルPDF取得APIリクエスト失敗。", "code": "DXSUITE_SPDF_GET_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic: return None, {"message": "DX Suite サーチャブルPDF取得処理中に予期せぬエラー。", "code": "DXSUITE_SPDF_GET_UNEXPECTED_ERROR", "detail": str(e_generic)}
