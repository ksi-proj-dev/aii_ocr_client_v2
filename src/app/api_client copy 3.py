# OCRApiClient.py

import os
import time
import json
import random
import shutil
import requests # requests のインポートを有効化
from log_manager import LogLevel
from PyPDF2 import PdfWriter # PyPDF2.PdfWriter であることを確認
import io
from typing import Optional, Dict, Any, Tuple # Tuple を追加

from config_manager import ConfigManager

class OCRApiClient:
    def __init__(self, config: Dict[str, Any], log_manager, api_profile_schema: Optional[Dict[str, Any]]): # ← ここが api_profile_schema
        self.log_manager = log_manager
        self.config: Dict[str, Any] = {}
        self.active_api_profile_schema: Optional[Dict[str, Any]] = {} # ★ スキーマ情報を保持
        self.active_options_values: Optional[Dict[str, Any]] = {}   # ★ オプション値(APIキー, BaseURI含む)を保持
        self.api_execution_mode: str = "demo"
        self.api_key: Optional[str] = "" # これは active_options_values から設定される
        self.timeout_seconds: int = 60

        self.update_config(config, api_profile_schema)

    def _get_full_url(self, endpoint_key: str) -> Optional[str]:
        if not self.active_api_profile_schema: # スキーマがないとエンドポイントパスが取れない
            self.log_manager.error("APIプロファイルスキーマがアクティブではありません。", context="API_CLIENT_CONFIG")
            return None

        # ★変更箇所: まず active_options_values から base_uri を試みる
        base_uri = self.active_options_values.get("base_uri") if self.active_options_values else None
        
        # 値が空文字列の場合や、options_values に base_uri が無かった場合はスキーマのデフォルトを使用
        if not base_uri: 
            base_uri = self.active_api_profile_schema.get("base_uri")
            self.log_manager.debug(f"ユーザー設定のBaseURIが空のため、スキーマ定義のBaseURI '{base_uri}' を使用します。", context="API_CLIENT_CONFIG")


        if not base_uri: # それでも base_uri がない場合
            err_msg = f"ベースURIがプロファイル '{self.active_api_profile_schema.get('id')}' に設定されていません（ユーザー設定にもスキーマ定義にもなし）。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            return None
        
        # プレースホルダーチェック (ユーザー設定後 or スキーマデフォルトのURIに対して行う)
        if "{organization_specific_domain}" in base_uri:
             self.log_manager.warning(f"ベースURIにプレースホルダーが含まれています: {base_uri}。Liveモードでは正しいドメインに置き換える必要があります。", context="API_CLIENT_CONFIG")
             # 実際のAPI呼び出し時にこれがエラーになるかは呼び出し側（read_document内など）で再度チェックする

        endpoints = self.active_api_profile_schema.get("endpoints", {})
        endpoint_path = endpoints.get(endpoint_key)

        if not endpoint_path:
            err_msg = f"エンドポイントキー '{endpoint_key}' がプロファイル '{self.active_api_profile_schema.get('id')}' に設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            return None
            
        return base_uri.rstrip('/') + endpoint_path

    def read_document(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        file_name = os.path.basename(file_path)
        effective_options = specific_options if specific_options is not None else {}
        
        # ★変更箇所: self.active_api_profile_schema を使用
        current_flow_type = self.active_api_profile_schema.get("flow_type") if self.active_api_profile_schema else None
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        # --- ★変更箇所ここまで ---

        if current_flow_type == "cube_fullocr_single_call":
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
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (read_document): {file_name}", context=log_ctx)
                url = self._get_full_url("read_document")
                if not url: return None, {"message": "エンドポイントURL取得失敗 (read_document)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
                if not self.api_key:
                    err_msg_val = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg_val, context=log_ctx, error_code="API_KEY_MISSING_LIVE")
                    return None, {"message": err_msg_val, "code": "API_KEY_MISSING_LIVE"}
                headers = {"apikey": self.api_key}
                self.log_manager.info(f"  URL: {url}", context=log_ctx)
                self.log_manager.info(f"  OCRパラメータ: {actual_ocr_params}", context=log_ctx)
                self.log_manager.warning("LiveモードAPIコールは実装されていません (Cube read_document)。", context=log_ctx)
                return None, {"message": "LiveモードAPIコール未実装 (Cube read_document)。", "code": "NOT_IMPLEMENTED_API_CALL"}

        elif current_flow_type == "dx_fulltext_v2_flow":
            log_ctx_prefix = "API_DX_FULLTEXT_V2"
            
            if self.api_execution_mode == "demo":
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Fulltext V2 - Simulate Register & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                concatenate_opt = effective_options.get("concatenate", 0)
                char_extract_opt = effective_options.get("characterExtraction", 0)
                table_extract_opt = effective_options.get("tableExtraction", 1)
                self.log_manager.debug(f"  Simulating Register with options: concatenate={concatenate_opt}, characterExtraction={char_extract_opt}, tableExtraction={table_extract_opt}", context=f"{log_ctx_prefix}_DEMO_REGISTER")

                if file_name.startswith("error_dx_register_"):
                    error_code = "DUMMY_DX_REGISTER_ERROR"
                    error_msg = f"Demo DX Suite 登録エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX Suite登録APIエラーです。"}

                dummy_full_ocr_job_id = f"demo-dx-ocr-job-{random.randint(10000, 99999)}"
                self.log_manager.info(f"  Simulated Register success. fullOcrJobId: {dummy_full_ocr_job_id}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                time.sleep(random.uniform(0.2, 0.5))
                self.log_manager.info(f"  Simulating GetResult for fullOcrJobId: {dummy_full_ocr_job_id}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")

                if file_name.startswith("error_dx_getresult_"):
                    error_code = "DUMMY_DX_GETRESULT_ERROR"
                    error_msg = f"Demo DX Suite 結果取得エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX Suite結果取得APIエラーです。"}

                demo_ocr_result_block = {
                    "text": f"これは {file_name} のデモテキストです。",
                    "bbox": {"top": 0.1, "bottom": 0.2, "left": 0.1, "right": 0.8},
                    "vertices": [{"x":0.1, "y":0.1}, {"x":0.8, "y":0.1}, {"x":0.8, "y":0.2}, {"x":0.1, "y":0.2}]
                }
                if char_extract_opt == 1:
                    demo_ocr_result_block["characters"] = [
                        {"char": "こ", "ocrConfidence": 0.95, "bbox": {"top":0.1, "bottom":0.2,"left":0.1,"right":0.12}},
                        {"char": "れ", "ocrConfidence": 0.98, "bbox": {"top":0.1, "bottom":0.2,"left":0.12,"right":0.14}},
                    ]
                demo_page_result = {
                    "pageNum": 1, "ocrSuccess": True,
                    "fulltext": f"これは {file_name} の全文デモテキストです。結合:{'ON' if concatenate_opt==1 else 'OFF'} 文字抽出:{'ON' if char_extract_opt==1 else 'OFF'} 表抽出:{'ON' if table_extract_opt==1 else 'OFF'}.",
                    "ocrResults": [demo_ocr_result_block]
                }
                demo_tables_data = []
                if table_extract_opt == 1:
                    demo_tables_data.append({
                        "bbox": {"top": 0.3, "bottom": 0.6, "left": 0.1, "right": 0.9}, "confidence": 0.98,
                        "cells": [
                            {"row_index":0, "col_index":0, "text":"ヘッダ1"}, {"row_index":0, "col_index":1, "text":"ヘッダ2"},
                            {"row_index":1, "col_index":0, "text":"データA"}, {"row_index":1, "col_index":1, "text":"データB"},
                        ]})
                demo_page_result["tables"] = demo_tables_data
                final_json_response_listwrapper = {
                    "status": "done",
                    "results": [{"fileName": file_name, "fileSuccess": True, "pages": [demo_page_result]}]
                }
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (DX Suite Fulltext V2): {file_name}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
                return final_json_response_listwrapper, None

            else: # Live モード for dx_fulltext_v2_flow (Register step)
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Fulltext V2 - Register): {file_name}", context=f"{log_ctx_prefix}_LIVE_REGISTER")
                url = self._get_full_url("register_ocr")
                if not url:
                    return None, {"message": "エンドポイントURL取得失敗 (DX Suite Register OCR)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
                if "{organization_specific_domain}" in url:
                     self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR")
                     return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
                if not self.api_key:
                    err_msg = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER", error_code="API_KEY_MISSING_LIVE")
                    return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}

                headers = {"apikey": self.api_key}
                payload_data = {
                    "concatenate": str(effective_options.get("concatenate", 0)),
                    "characterExtraction": str(effective_options.get("characterExtraction", 0)),
                    "tableExtraction": str(effective_options.get("tableExtraction", 1))
                }
                # department_id_val = effective_options.get("departmentId")
                # if department_id_val:
                #     payload_data["departmentId"] = str(department_id_val)

                try:
                    with open(file_path, 'rb') as f_obj:
                        files_data = {'file': (os.path.basename(file_path), f_obj)} # Content-Type will be auto-detected or can be specified
                        self.log_manager.debug(f"  POST to {url} with headers: {list(headers.keys())}, form-data: {payload_data}, file: {file_name}", context=f"{log_ctx_prefix}_LIVE_REGISTER")
                        response = requests.post(url, headers=headers, data=payload_data, files=files_data, timeout=self.timeout_seconds)
                        response.raise_for_status()
                        response_json = response.json()
                        self.log_manager.info(f"  DX Suite Register API success. Response: {response_json}", context=f"{log_ctx_prefix}_LIVE_REGISTER")
                        job_id = response_json.get("id")
                        if not job_id:
                            self.log_manager.error(f"  DX Suite Register API response missing 'id'. Response: {response_json}", context=f"{log_ctx_prefix}_LIVE_REGISTER_ERROR")
                            return None, {"message": "DX Suite 登録APIレスポンスにIDが含まれていません。", "code": "DXSUITE_REGISTER_NO_ID", "detail": response_json}
                        return {"job_id": job_id, "status": "ocr_registered", "profile_flow_type": current_flow_type}, None
                except requests.exceptions.HTTPError as e_http:
                    err_msg = f"DX Suite 登録API HTTPエラー: {e_http.response.status_code}"
                    detail_text = e_http.response.text
                    self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_REGISTER_HTTP_ERROR", exc_info=True)
                    try:
                        err_json = e_http.response.json()
                        api_err_detail = err_json.get("errors", [{}])[0]
                        api_err_code = api_err_detail.get("errorCode", "UNKNOWN_API_ERROR")
                        api_err_msg_from_json = api_err_detail.get("message", detail_text)
                        return None, {"message": f"DX Suite APIエラー: {api_err_msg_from_json}", "code": f"DXSUITE_API_{api_err_code}", "detail": err_json}
                    except ValueError:
                        return None, {"message": f"DX Suite 登録API HTTPエラー (非JSON応答): {e_http.response.status_code}", "code": "DXSUITE_REGISTER_HTTP_ERROR_NON_JSON", "detail": detail_text}
                except requests.exceptions.RequestException as e_req:
                    err_msg = f"DX Suite 登録APIリクエストエラー: {e_req}"
                    self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER_REQUEST_ERROR", exc_info=True)
                    return None, {"message": "DX Suite 登録APIリクエスト失敗。", "code": "DXSUITE_REGISTER_REQUEST_FAIL", "detail": str(e_req)}
                except Exception as e_generic:
                    err_msg = f"DX Suite 登録API処理中に予期せぬエラー: {e_generic}"
                    self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_REGISTER_UNEXPECTED_ERROR", exc_info=True)
                    return None, {"message": "DX Suite 登録処理中に予期せぬエラー。", "code": "DXSUITE_REGISTER_UNEXPECTED_ERROR", "detail": str(e_generic)}
        
        else: # 未対応のフロータイプ
            self.log_manager.error(f"未対応または不明なAPIフロータイプです: {current_flow_type}", context="API_CLIENT_ERROR")
            return None, {"message": f"未対応のAPIフロータイプ: {current_flow_type}", "code": "UNSUPPORTED_FLOW_TYPE"}

    def get_dx_fulltext_ocr_result(self, job_id: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        log_ctx_prefix = "API_DX_FULLTEXT_V2"
        # ★変更箇所: self.active_api_profile_schema を使用
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        # --- ★変更箇所ここまで ---
        self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Fulltext V2 - GetResult): job_id={job_id}", context=f"{log_ctx_prefix}_LIVE_GETRESULT")

        url = self._get_full_url("get_ocr_result")
        if not url:
            return None, {"message": "エンドポイントURL取得失敗 (DX Suite Get OCR Result)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
        if "{organization_specific_domain}" in url:
             self.log_manager.error(f"DX Suite のベースURIに組織固有ドメインのプレースホルダーが含まれています。設定を確認してください: {url}", context="API_CLIENT_CONFIG_ERROR")
             return None, {"message": "DX Suite ベースURI未設定エラー。", "code": "DXSUITE_BASE_URI_NOT_CONFIGURED"}
        if not self.api_key:
            err_msg = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
            self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_GETRESULT", error_code="API_KEY_MISSING_LIVE")
            return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}

        headers = {"apikey": self.api_key}
        params = {"id": job_id}

        try:
            self.log_manager.debug(f"  GET from {url} with headers: {list(headers.keys())}, params: {params}", context=f"{log_ctx_prefix}_LIVE_GETRESULT")
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            response_json = response.json()
            self.log_manager.info(f"  DX Suite GetResult API success. Status: {response_json.get('status')}", context=f"{log_ctx_prefix}_LIVE_GETRESULT")
            return response_json, None
        except requests.exceptions.HTTPError as e_http:
            err_msg = f"DX Suite 結果取得API HTTPエラー: {e_http.response.status_code}"
            detail_text = e_http.response.text
            self.log_manager.error(f"{err_msg} - {detail_text}", context=f"{log_ctx_prefix}_LIVE_GETRESULT_HTTP_ERROR", exc_info=True)
            try:
                err_json = e_http.response.json()
                api_err_detail = err_json.get("errors", [{}])[0]
                api_err_code = api_err_detail.get("errorCode", "UNKNOWN_API_ERROR")
                api_err_msg_from_json = api_err_detail.get("message", detail_text)
                return None, {"message": f"DX Suite APIエラー: {api_err_msg_from_json}", "code": f"DXSUITE_API_{api_err_code}", "detail": err_json}
            except ValueError:
                return None, {"message": f"DX Suite 結果取得API HTTPエラー (非JSON応答): {e_http.response.status_code}", "code": "DXSUITE_GETRESULT_HTTP_ERROR_NON_JSON", "detail": detail_text}
        except requests.exceptions.RequestException as e_req:
            err_msg = f"DX Suite 結果取得APIリクエストエラー: {e_req}"
            self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_GETRESULT_REQUEST_ERROR", exc_info=True)
            return None, {"message": "DX Suite 結果取得APIリクエスト失敗。", "code": "DXSUITE_GETRESULT_REQUEST_FAIL", "detail": str(e_req)}
        except Exception as e_generic:
            err_msg = f"DX Suite 結果取得API処理中に予期せぬエラー: {e_generic}"
            self.log_manager.error(err_msg, context=f"{log_ctx_prefix}_LIVE_GETRESULT_UNEXPECTED_ERROR", exc_info=True)
            return None, {"message": "DX Suite 結果取得処理中に予期せぬエラー。", "code": "DXSUITE_GETRESULT_UNEXPECTED_ERROR", "detail": str(e_generic)}

    def make_searchable_pdf(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
        file_name = os.path.basename(file_path)
        effective_options = specific_options if specific_options is not None else {}
        
        # ★変更箇所: self.active_api_profile_schema を使用
        current_flow_type = self.active_api_profile_schema.get("flow_type") if self.active_api_profile_schema else None
        profile_name = self.active_api_profile_schema.get('name', 'N/A') if self.active_api_profile_schema else "UnknownProfile"
        # --- ★変更箇所ここまで ---

        if current_flow_type == "cube_fullocr_single_call":
            if self.api_execution_mode == "demo":
                # ... (Demoロジック - 変更なし) ...
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
                # ... (Liveロジック - 変更なし) ...
                log_ctx = "API_LIVE_PDF_CUBE"
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (make_searchable_pdf): {file_name}", context=log_ctx)
                url = self._get_full_url("make_searchable_pdf")
                if not url: return None, {"message": "エンドポイントURL取得失敗 (make_searchable_pdf)", "code": "CONFIG_ENDPOINT_URL_FAIL_PDF"}
                if not self.api_key:
                    err_msg_val = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg_val, context=log_ctx, error_code="API_KEY_MISSING_PDF_LIVE")
                    return None, {"message": err_msg_val, "code": "API_KEY_MISSING_PDF_LIVE"}
                headers = {"apikey": self.api_key}
                self.log_manager.warning("LiveモードAPIコールは実装されていません (Cube make_searchable_pdf)。", context=log_ctx) # Demo動作を返す、という部分は削除
                return None, {"message": "LiveモードAPIコール未実装 (Cube make_searchable_pdf)。", "code": "NOT_IMPLEMENTED_API_CALL_PDF"}
        
        elif current_flow_type == "dx_fulltext_v2_flow":
            log_ctx_prefix = "API_DX_FULLTEXT_V2_PDF"
            if self.api_execution_mode == "demo":
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Searchable PDF V2 - Simulate Register & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                high_res_opt = effective_options.get("highResolutionMode", 0)
                self.log_manager.debug(f"  Simulating Searchable PDF Register with options: highResolutionMode={high_res_opt}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                if file_name.startswith("error_dx_spdf_register_"):
                    error_code = "DUMMY_DX_SPDF_REGISTER_ERROR"
                    error_msg = f"Demo DX Suite サーチャブルPDF登録エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX SuiteサーチャブルPDF登録APIエラーです。"}
                dummy_searchable_pdf_job_id = f"demo-dx-spdf-job-{random.randint(10000, 99999)}"
                self.log_manager.info(f"  Simulated Searchable PDF Register success. searchablePdfJobId: {dummy_searchable_pdf_job_id}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                time.sleep(random.uniform(0.1, 0.3))
                self.log_manager.info(f"  Simulating Get Searchable PDF Result for searchablePdfJobId: {dummy_searchable_pdf_job_id}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
                if file_name.startswith("error_dx_spdf_getresult_"):
                    error_code = "DUMMY_DX_SPDF_GETRESULT_ERROR"
                    error_msg = f"Demo DX Suite サーチャブルPDF取得エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX SuiteサーチャブルPDF取得APIエラーです。"}
                try:
                    writer = PdfWriter()
                    writer.add_blank_page(width=595, height=842)
                    bio = io.BytesIO()
                    writer.write(bio)
                    dummy_pdf_content = bio.getvalue()
                    self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (DX Suite Searchable PDF V2): {file_name}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
                    return dummy_pdf_content, None
                except Exception as e_pdf_dummy:
                    error_detail_str = str(e_pdf_dummy) if e_pdf_dummy else "不明なPDF生成例外"
                    error_msg_main = f"Demo DX Suite PDF生成エラー: {file_name}, Error: {error_detail_str}"
                    self.log_manager.error(error_msg_main, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code="DUMMY_DX_PDF_GEN_ERROR", filename=file_name, exc_info=True)
                    return None, {"message": error_msg_main, "code": "DUMMY_DX_PDF_GEN_ERROR", "detail": error_detail_str}
            else: # Live モード
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Searchable PDF V2): {file_name}", context=f"{log_ctx_prefix}_LIVE")
                # TODO: Liveモードでの「サーチャブルPDF登録」「サーチャブルPDF取得」(ポーリング含む) の実装
                self.log_manager.warning(f"LiveモードAPIコールは実装されていません ({profile_name} - make_searchable_pdf)。", context=f"{log_ctx_prefix}_LIVE") # Demo動作を返す、という部分は削除
                return None, {"message": f"LiveモードAPIコール未実装 ({profile_name} - make_searchable_pdf)。", "code": "NOT_IMPLEMENTED_API_CALL_DX_SPDF"}
        
        else:
            self.log_manager.error(f"未対応または不明なAPIフロータイプです: {current_flow_type} (PDF作成)", context="API_CLIENT_ERROR")
            return None, {"message": f"未対応のAPIフロータイプ (PDF作成): {current_flow_type}", "code": "UNSUPPORTED_FLOW_TYPE_PDF"}

    def update_config(self, new_config: dict, new_api_profile_schema: Optional[Dict[str, Any]]): # ★引数名を明確化
        self.log_manager.info("ApiClient: 設定更新中...", context="API_CLIENT_CONFIG_UPDATE")
        self.config = new_config

        # アクティブなプロファイルのスキーマ部分を設定
        if new_api_profile_schema:
            self.active_api_profile_schema = new_api_profile_schema
        elif "current_api_profile_id" in new_config: # スキーマが直接渡されない場合、configから再取得
            current_profile_id_from_config = new_config.get("current_api_profile_id")
            active_profile_schema_from_cfg = ConfigManager.get_api_profile(new_config, current_profile_id_from_config)
            if active_profile_schema_from_cfg:
                self.active_api_profile_schema = active_profile_schema_from_cfg
            elif new_config.get("api_profiles"):
                self.active_api_profile_schema = new_config["api_profiles"][0]
            else:
                self.active_api_profile_schema = {}
        else:
             self.active_api_profile_schema = {} # フォールバック

        # ★変更箇所: アクティブプロファイルのオプション値(api_key, base_uri含む)を取得・保持
        self.active_options_values = ConfigManager.get_active_api_options_values(self.config)
        if self.active_options_values is None: # 通常は発生しないはずだが念のため
            self.active_options_values = {}
            self.log_manager.warning("ApiClient: アクティブプロファイルのオプション値が取得できませんでした。", context="API_CLIENT_CONFIG_UPDATE")

        self.api_execution_mode = self.config.get("api_execution_mode", "demo")
        
        # APIキーを active_options_values から取得
        self.api_key = self.active_options_values.get("api_key", "") # デフォルト空文字

        profile_name_for_log = self.active_api_profile_schema.get('name', 'N/A')
        key_status_log = "設定あり" if self.api_key else "未設定"
        base_uri_for_log = self.active_options_values.get("base_uri", self.active_api_profile_schema.get("base_uri", "未設定"))

        if self.api_execution_mode == "live":
            self.log_manager.info(f"ApiClientは Liveモード ({profile_name_for_log}, APIキー: {key_status_log}, BaseURI: {base_uri_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info(f"ApiClientは Demoモード ({profile_name_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
