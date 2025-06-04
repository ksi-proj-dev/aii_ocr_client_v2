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
from config_manager import ConfigManager

# ★変更箇所: クラス名変更
class OCRApiClient: # 旧: CubeApiClient
    def __init__(self, config: Dict[str, Any], log_manager, api_profile: Optional[Dict[str, Any]]):
        self.log_manager = log_manager
        self.config: Dict[str, Any] = {}
        self.active_api_profile: Optional[Dict[str, Any]] = {}
        self.api_execution_mode: str = "demo"
        self.api_key: Optional[str] = ""

        self.update_config(config, api_profile)

    def _get_full_url(self, endpoint_key: str) -> Optional[str]:
        # (メソッド内容は変更なし)
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
        effective_options = specific_options if specific_options is not None else {}
        
        current_flow_type = self.active_api_profile.get("flow_type") if self.active_api_profile else None
        profile_name = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else "UnknownProfile"

        if current_flow_type == "cube_fullocr_single_call": # cube_fullocr_v1 用のフロー
            # ... (既存の cube_fullocr_single_call のロジックは変更なし) ...
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
                # ... (既存の cube_fullocr_single_call Liveモードのロジックは変更なし) ...
                log_ctx = "API_LIVE_READ_CUBE"
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (read_document): {file_name}", context=log_ctx)
                url = self._get_full_url("read_document") # このキーは cube_fullocr_v1 の endpoints で定義されているもの
                if not url: return None, {"message": "エンドポイントURL取得失敗 (read_document)", "code": "CONFIG_ENDPOINT_URL_FAIL"}
                if not self.api_key:
                    err_msg_val = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg_val, context=log_ctx, error_code="API_KEY_MISSING_LIVE")
                    return None, {"message": err_msg_val, "code": "API_KEY_MISSING_LIVE"}
                headers = {"apikey": self.api_key}
                self.log_manager.info(f"  URL: {url}", context=log_ctx)
                self.log_manager.info(f"  OCRパラメータ: {actual_ocr_params}", context=log_ctx)
                self.log_manager.warning("LiveモードAPIコールは実装されていません (Cube read_document)。Demo動作を返します。", context=log_ctx)
                return None, {"message": "LiveモードAPIコール未実装 (Cube read_document)。", "code": "NOT_IMPLEMENTED_API_CALL"}

        # ★追加: DX Suite 全文OCR V2 (dx_fulltext_v2_flow) の処理
        elif current_flow_type == "dx_fulltext_v2_flow":
            log_ctx_prefix = "API_DX_FULLTEXT_V2"
            # Demoモードでの処理
            if self.api_execution_mode == "demo":
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Fulltext V2 - Simulate Register & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                
                # 1. Simulate "全文読取登録API" (/register)
                #    オプションを取得 (config_manager.py で定義したキー名に合わせる)
                concatenate_opt = effective_options.get("concatenate", 0) # デフォルト0 (OFF) [cite: 29]
                char_extract_opt = effective_options.get("characterExtraction", 0) # デフォルト0 (OFF) [cite: 29]
                table_extract_opt = effective_options.get("tableExtraction", 1) # デフォルト1 (ON) [cite: 29]

                self.log_manager.debug(f"  Simulating Register with options: concatenate={concatenate_opt}, characterExtraction={char_extract_opt}, tableExtraction={table_extract_opt}", context=f"{log_ctx_prefix}_DEMO_REGISTER")

                # エラーシミュレーション (登録API)
                if file_name.startswith("error_dx_register_"):
                    error_code = "DUMMY_DX_REGISTER_ERROR"
                    error_msg = f"Demo DX Suite 登録エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX Suite登録APIエラーです。"}

                dummy_full_ocr_job_id = f"demo-dx-ocr-job-{random.randint(10000, 99999)}"
                self.log_manager.info(f"  Simulated Register success. fullOcrJobId: {dummy_full_ocr_job_id}", context=f"{log_ctx_prefix}_DEMO_REGISTER")
                
                time.sleep(random.uniform(0.2, 0.5)) # 処理時間をシミュレート

                # 2. Simulate "全文読取結果取得API" (/getOcrResult)
                self.log_manager.info(f"  Simulating GetResult for fullOcrJobId: {dummy_full_ocr_job_id}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")

                # エラーシミュレーション (結果取得API)
                if file_name.startswith("error_dx_getresult_"):
                    error_code = "DUMMY_DX_GETRESULT_ERROR"
                    error_msg = f"Demo DX Suite 結果取得エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX Suite結果取得APIエラーです。"}

                # Demoレスポンスの構築 (仕様書 P.18- P.29 [cite: 36, 38, 40, 42, 43, 44, 45, 46, 47, 48, 49, 50] を参考に)
                demo_ocr_result_block = {
                    "text": f"これは {file_name} のデモテキストです。",
                    "bbox": {"top": 0.1, "bottom": 0.2, "left": 0.1, "right": 0.8},
                    "vertices": [{"x":0.1, "y":0.1}, {"x":0.8, "y":0.1}, {"x":0.8, "y":0.2}, {"x":0.1, "y":0.2}]
                }
                if char_extract_opt == 1: # 文字抽出オプションONの場合 [cite: 10, 11]
                    demo_ocr_result_block["characters"] = [
                        {"char": "こ", "ocrConfidence": 0.95, "bbox": {"top":0.1, "bottom":0.2,"left":0.1,"right":0.12}},
                        {"char": "れ", "ocrConfidence": 0.98, "bbox": {"top":0.1, "bottom":0.2,"left":0.12,"right":0.14}},
                        # ... more characters
                    ]
                
                demo_page_result = {
                    "pageNum": 1,
                    "ocrSuccess": True,
                    "fulltext": f"これは {file_name} の全文デモテキストです。結合オプション: {'ON' if concatenate_opt == 1 else 'OFF'}。文字抽出: {'ON' if char_extract_opt == 1 else 'OFF'}。表抽出: {'ON' if table_extract_opt == 1 else 'OFF'}。",
                    "ocrResults": [demo_ocr_result_block] # 以前は "results" キーだったが、仕様書P21の例では ocrResults > results のネストは見られないので、ocrResults直下にブロックを配置
                }

                demo_tables_data = []
                if table_extract_opt == 1: # 表抽出オプションONの場合 [cite: 12, 13]
                    demo_tables_data.append({
                        "bbox": {"top": 0.3, "bottom": 0.6, "left": 0.1, "right": 0.9},
                        "confidence": 0.98,
                        "cells": [
                            {"row_index":0, "col_index":0, "row_span":1, "col_span":1, "text":"ヘッダ1", "bbox": {"top":0.3,"bottom":0.35,"left":0.1,"right":0.45}},
                            {"row_index":0, "col_index":1, "row_span":1, "col_span":1, "text":"ヘッダ2", "bbox": {"top":0.3,"bottom":0.35,"left":0.5,"right":0.9}},
                            {"row_index":1, "col_index":0, "row_span":1, "col_span":1, "text":"データA", "bbox": {"top":0.36,"bottom":0.4,"left":0.1,"right":0.45}},
                            {"row_index":1, "col_index":1, "row_span":1, "col_span":1, "text":"データB", "bbox": {"top":0.36,"bottom":0.4,"left":0.5,"right":0.9}},
                        ]
                    })
                demo_page_result["tables"] = demo_tables_data # 仕様書P19では pages > tables ではなく results > tables のように見えるが、P21の例では pages の中に tables がある。P26の例でも pages > tables。ここでは pages の中に配置。

                final_json_response = {
                    "status": "done", # 処理完了を想定
                    "results": { # 仕様書 P.18 [cite: 36] では "results" がオブジェクトではなくリストの場合もあるが、ここでは単一ファイル処理なのでオブジェクト想定で良いか、またはリストの最初の要素として扱う
                        "fileName": file_name,
                        "fileSuccess": True,
                        "pages": [demo_page_result]
                    }
                }
                # 仕様書P.18の results はリスト型なので、それに合わせる
                final_json_response_listwrapper = {
                    "status": "done",
                    "results": [
                        {
                            "fileName": file_name,
                            "fileSuccess": True,
                            "pages": [demo_page_result]
                            # "tables" は各ページ内にある想定。もしファイル全体でのtablesならここに。仕様書P26の例ではページ内。
                        }
                    ]
                }

                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し完了 (DX Suite Fulltext V2): {file_name}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
                return final_json_response_listwrapper, None # ★仕様書P18に合わせた形式で返す

            else: # Live モード
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (DX Suite Fulltext V2): {file_name}", context=f"{log_ctx_prefix}_LIVE")
                # TODO: Liveモードでの「全文読取登録」「全文読取結果取得」(ポーリング含む) の実装
                self.log_manager.warning(f"LiveモードAPIコールは実装されていません ({profile_name} - read_document)。Demo動作を返します。", context=f"{log_ctx_prefix}_LIVE")
                return None, {"message": f"LiveモードAPIコール未実装 ({profile_name} - read_document)。", "code": "NOT_IMPLEMENTED_API_CALL_DX_FULLTEXT"}
        # --- ★追加ここまで ---
        
        else: # 未対応のフロータイプ
            self.log_manager.error(f"未対応または不明なAPIフロータイプです: {current_flow_type}", context="API_CLIENT_ERROR")
            return None, {"message": f"未対応のAPIフロータイプ: {current_flow_type}"}









    def make_searchable_pdf(self, file_path: str, specific_options: Optional[Dict[str, Any]] = None):
        file_name = os.path.basename(file_path)
        effective_options = specific_options if specific_options is not None else {}
        
        current_flow_type = self.active_api_profile.get("flow_type") if self.active_api_profile else None
        profile_name = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else "UnknownProfile"

        if current_flow_type == "cube_fullocr_single_call": # cube_fullocr_v1 用のフロー
            # ... (既存の cube_fullocr_single_call のロジックは変更なし) ...
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
                # ... (既存の cube_fullocr_single_call Liveモードのロジックは変更なし) ...
                log_ctx = "API_LIVE_PDF_CUBE"
                self.log_manager.info(f"'{profile_name}' LiveモードAPI呼び出し開始 (make_searchable_pdf): {file_name}", context=log_ctx)
                url = self._get_full_url("make_searchable_pdf") # このキーは cube_fullocr_v1 の endpoints で定義されているもの
                if not url: return None, {"message": "エンドポイントURL取得失敗 (make_searchable_pdf)", "code": "CONFIG_ENDPOINT_URL_FAIL_PDF"}
                if not self.api_key:
                    err_msg_val = f"APIキーがプロファイル '{profile_name}' に設定されていません (Liveモード)。"
                    self.log_manager.error(err_msg_val, context=log_ctx, error_code="API_KEY_MISSING_PDF_LIVE")
                    return None, {"message": err_msg_val, "code": "API_KEY_MISSING_PDF_LIVE"}
                headers = {"apikey": self.api_key}
                self.log_manager.warning("LiveモードAPIコールは実装されていません (Cube make_searchable_pdf)。Demo動作を返します。", context=log_ctx)
                return None, {"message": "LiveモードAPIコール未実装 (Cube make_searchable_pdf)。", "code": "NOT_IMPLEMENTED_API_CALL_PDF"}

        # ★追加: DX Suite 全文OCR V2 (dx_fulltext_v2_flow) の サーチャブルPDF処理
        elif current_flow_type == "dx_fulltext_v2_flow":
            log_ctx_prefix = "API_DX_FULLTEXT_V2_PDF"
            if self.api_execution_mode == "demo":
                self.log_manager.info(f"'{profile_name}' Demoモード呼び出し開始 (DX Suite Searchable PDF V2 - Simulate Register & GetResult): {file_name}", context=f"{log_ctx_prefix}_DEMO_REGISTER")

                # 1. Simulate "サーチャブルPDF登録API" (/searchablepdf/register)
                #    オプションを取得
                high_res_opt = effective_options.get("highResolutionMode", 0) # デフォルト0 (OFF)
                self.log_manager.debug(f"  Simulating Searchable PDF Register with options: highResolutionMode={high_res_opt}", context=f"{log_ctx_prefix}_DEMO_REGISTER")

                # エラーシミュレーション (サーチャブルPDF登録API)
                if file_name.startswith("error_dx_spdf_register_"):
                    error_code = "DUMMY_DX_SPDF_REGISTER_ERROR"
                    error_msg = f"Demo DX Suite サーチャブルPDF登録エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX SuiteサーチャブルPDF登録APIエラーです。"}

                dummy_searchable_pdf_job_id = f"demo-dx-spdf-job-{random.randint(10000, 99999)}"
                self.log_manager.info(f"  Simulated Searchable PDF Register success. searchablePdfJobId: {dummy_searchable_pdf_job_id}", context=f"{log_ctx_prefix}_DEMO_REGISTER")

                time.sleep(random.uniform(0.1, 0.3)) # 処理時間をシミュレート

                # 2. Simulate "サーチャブルPDF取得API" (/searchablepdf/getResult)
                self.log_manager.info(f"  Simulating Get Searchable PDF Result for searchablePdfJobId: {dummy_searchable_pdf_job_id}", context=f"{log_ctx_prefix}_DEMO_GETRESULT")
                
                # エラーシミュレーション (サーチャブルPDF取得API)
                if file_name.startswith("error_dx_spdf_getresult_"):
                    error_code = "DUMMY_DX_SPDF_GETRESULT_ERROR"
                    error_msg = f"Demo DX Suite サーチャブルPDF取得エラー: {file_name}"
                    self.log_manager.error(error_msg, context=f"{log_ctx_prefix}_DEMO_ERROR", error_code=error_code, filename=file_name)
                    return None, {"message": error_msg, "code": error_code, "detail": "DemoモードでシミュレートされたDX SuiteサーチャブルPDF取得APIエラーです。"}

                try: # ダミーPDF生成 (cube_fullocr_single_call のDemoモードと同様)
                    writer = PdfWriter()
                    writer.add_blank_page(width=595, height=842) # A4
                    # 必要であれば、高解像度オプションに応じて内容を変えることも可能
                    # writer.add_metadata({"/Title": f"Demo Searchable PDF for {file_name} (HighRes: {high_res_opt})"})
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
                self.log_manager.warning(f"LiveモードAPIコールは実装されていません ({profile_name} - make_searchable_pdf)。Demo動作を返します。", context=f"{log_ctx_prefix}_LIVE")
                return None, {"message": f"LiveモードAPIコール未実装 ({profile_name} - make_searchable_pdf)。", "code": "NOT_IMPLEMENTED_API_CALL_DX_SPDF"}
        # --- ★追加ここまで ---

        else: # 未対応のフロータイプ
            self.log_manager.error(f"未対応または不明なAPIフロータイプです: {current_flow_type} (PDF作成)", context="API_CLIENT_ERROR")
            return None, {"message": f"未対応のAPIフロータイプ (PDF作成): {current_flow_type}", "code": "UNSUPPORTED_FLOW_TYPE_PDF"}








    def update_config(self, new_config: dict, new_api_profile: Optional[Dict[str, Any]]):
        # (メソッド内容は変更なし)
        self.log_manager.info("ApiClient: 設定更新中...", context="API_CLIENT_CONFIG_UPDATE")
        self.config = new_config

        if new_api_profile:
            self.active_api_profile = new_api_profile
        elif "current_api_profile_id" in new_config:
            current_profile_id_from_config = new_config.get("current_api_profile_id")
            active_profile_from_cfg = ConfigManager.get_api_profile(new_config, current_profile_id_from_config)
            if active_profile_from_cfg:
                self.active_api_profile = active_profile_from_cfg
            elif new_config.get("api_profiles"):
                self.active_api_profile = new_config["api_profiles"][0]
                self.log_manager.warning(f"ApiClient: 指定されたcurrent_api_profile_id '{current_profile_id_from_config}' が見つからないため、最初のプロファイル '{self.active_api_profile.get('name')}' を使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else:
                self.active_api_profile = {}
                self.log_manager.error("ApiClient: 利用可能なAPIプロファイルが設定にありません。", context="API_CLIENT_CONFIG_UPDATE_ERROR")
        else:
            if self.config.get("api_profiles"):
                 self.active_api_profile = self.config["api_profiles"][0]
                 self.log_manager.warning("ApiClient: update_configで有効なプロファイル情報が不足していたため、config内の最初のプロファイルを使用します。", context="API_CLIENT_CONFIG_UPDATE")
            else:
                self.active_api_profile = {}
                self.log_manager.error("ApiClient: update_configで有効なプロファイル情報が不足しており、フォールバックもできませんでした。", context="API_CLIENT_CONFIG_UPDATE_ERROR")

        self.api_execution_mode = self.config.get("api_execution_mode", "demo")
        self.api_key = ConfigManager.get_active_api_key(self.config)
        if self.api_key is None:
            self.api_key = ""

        profile_name_for_log = self.active_api_profile.get('name', 'N/A') if self.active_api_profile else '未定義プロファイル'
        key_status_log = "設定あり" if self.api_key else "未設定"

        if self.api_execution_mode == "live":
            self.log_manager.info(f"ApiClientは Liveモード ({profile_name_for_log}, APIキー: {key_status_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info(f"ApiClientは Demoモード ({profile_name_for_log}) に更新されました。", context="API_CLIENT_CONFIG_UPDATE")