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

class CubeApiClient:
    def __init__(self, config, log_manager):
        self.config = config # ★ MainWindowから渡されたconfigを保持
        self.log_manager = log_manager
        
        # ★ api_execution_mode を config から読み込む
        self.api_execution_mode = self.config.get("api_execution_mode", "demo") # デフォルトは "demo"
        self.api_key = self.config.get("api_key") # APIキーも初期化時に設定
        self.base_uri = self.config.get("base_uri", "")
        api_type = self.config.get("api_type", "cube_fullocr")
        self.endpoints = self.config.get("endpoints", {}).get(api_type, {})

        if self.api_execution_mode == "live":
            self.log_manager.info("CubeApiClientは Liveモード で動作します。", context="API_CLIENT_INIT")
        else: # demo モードまたは未定義の場合
            self.log_manager.info("CubeApiClientは Demoモード で動作します。", context="API_CLIENT_INIT")


    def _get_full_url(self, endpoint_key):
        # (変更なし)
        endpoint_path = self.endpoints.get(endpoint_key)
        if not endpoint_path:
            err_msg = f"エンドポイントキー '{endpoint_key}' が設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            raise ValueError({"message": err_msg, "code": "CONFIG_ENDPOINT_MISSING"})
        if not self.base_uri:
            err_msg = "ベースURIが設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            raise ValueError({"message": err_msg, "code": "CONFIG_BASE_URI_MISSING"})
        return self.base_uri.rstrip('/') + endpoint_path

    def read_document(self, file_path):
        file_name = os.path.basename(file_path)
        # ★ api_execution_mode は self.config から取得済みなので、再度読み込む必要はない
        ocr_options_from_config = self.config.get("options", {}).get(self.config.get("api_type"), {})
        
        actual_ocr_params = {
            'adjust_rotation': ocr_options_from_config.get('adjust_rotation'),
            'character_extraction': ocr_options_from_config.get('character_extraction'),
            'concatenate': ocr_options_from_config.get('concatenate'),
            'enable_checkbox': ocr_options_from_config.get('enable_checkbox'),
            'fulltext': ocr_options_from_config.get('fulltext_output_mode'),
            'fulltext_linebreak': ocr_options_from_config.get('fulltext_linebreak_char'),
            'horizontal_ocr_model': ocr_options_from_config.get('ocr_model')
        }
        actual_ocr_params = {k: v for k, v in actual_ocr_params.items() if v is not None}

        # ★ self.dummy_mode を self.api_execution_mode == "demo" に変更
        if self.api_execution_mode == "demo":
            log_ctx = "API_DUMMY_READ"
            self.log_manager.info(f"'/fullocr-read-document' Demoモード呼び出し開始: {file_name}", context=log_ctx, options=actual_ocr_params)
            time.sleep(random.uniform(0.1, 0.3))

            if file_name.startswith("error_"):
                error_code_map = {
                    "error_auth": "DUMMY_AUTH_ERROR", "error_server": "DUMMY_SERVER_ERROR",
                    "error_bad_request": "DUMMY_BAD_REQUEST",
                }
                error_message_map = {
                    "error_auth": f"Demo認証エラー: {file_name}", "error_server": f"Demoサーバーエラー: {file_name}",
                    "error_bad_request": f"Demo不正リクエスト: {file_name}",
                }
                simulated_error_type = file_name.split("_")[1] if "_" in file_name else "generic"
                error_code = error_code_map.get(f"error_{simulated_error_type}", "DUMMY_OCR_ERROR")
                error_msg = error_message_map.get(f"error_{simulated_error_type}", f"Demo OCRエラー: {file_name}")
                self.log_manager.error(error_msg, context=log_ctx, error_code=error_code, filename=file_name)
                return None, {"message": error_msg, "code": error_code, "detail": "Demoモードでシミュレートされたエラーです。"}

            page_result = {
                "page": 0,
                "result": {
                    "aGroupingFulltext": f"Demo aGroupingFulltext for {file_name} (Page 1)",
                    "deskewAngle": round(random.uniform(-1, 1), 2), "fileName": file_name,
                    "fulltext": f"これは {file_name} のDemo OCR結果です。\nモデル: {actual_ocr_params.get('horizontal_ocr_model')}\n結合: {actual_ocr_params.get('concatenate')}",
                    "results": [{"text": f"Demoテキスト1 from {file_name}", "bbox": {}, "ocrConfidence": 0.95, "detectConfidence": 0.99, "vertices": [], "characters": []}],
                    "tables": [], "textGroups": []
                }, "status": "success"
            }
            if actual_ocr_params.get('character_extraction') == 1:
                if page_result["result"]["results"]:
                    for res_item in page_result["result"]["results"]:
                        if res_item.get("text"):
                            for i, char_text in enumerate(list(res_item["text"])):
                                res_item["characters"].append({"char": char_text, "ocrConfidence": 0.8, "bbox": {}, "vertices": []})
            response_data = [page_result]
            if actual_ocr_params.get('fulltext') == 1: 
                simplified_result_data = []
                for page in response_data:
                    simplified_page = {
                        "page": page.get("page"),
                        "result": { "fileName": page.get("result", {}).get("fileName"), "fulltext": page.get("result", {}).get("fulltext") }
                    }
                    simplified_result_data.append(simplified_page)
                response_data = simplified_result_data
            self.log_manager.info(f"'/fullocr-read-document' Demoモード呼び出し完了: {file_name}", context=log_ctx)
            return response_data, None
        else: # Liveモード
            log_ctx = "API_LIVE_READ"
            self.log_manager.info(f"'/fullocr-read-document' LiveモードAPI呼び出し開始: {file_name}", context=log_ctx)
            try:
                url = self._get_full_url("read_document")
            except ValueError as e_val:
                return None, e_val.args[0] if e_val.args and isinstance(e_val.args[0], dict) else \
                       {"message": str(e_val), "code": "CONFIG_ERROR_UNKNOWN"}

            if not self.api_key:
                err_msg = "APIキーが設定されていません (Liveモード)。"
                self.log_manager.error(err_msg, context=log_ctx, error_code="API_KEY_MISSING_LIVE")
                return None, {"message": err_msg, "code": "API_KEY_MISSING_LIVE"}

            headers = {"apikey": self.api_key}
            self.log_manager.info(f"  URL: {url}", context=log_ctx)
            self.log_manager.info(f"  ヘッダーキー: {list(headers.keys())}", context=log_ctx)
            self.log_manager.info(f"  OCRパラメータ: {actual_ocr_params}", context=log_ctx)
            try:
                # ここに実際の requests.post(...) 呼び出しが入る
                # with open(file_path, 'rb') as f:
                #     files = {'document': (file_name, f, 'application/octet-stream')}
                #     response = requests.post(url, headers=headers, files=files, data=actual_ocr_params, timeout=180)
                #     response.raise_for_status()
                #     return response.json(), None
                self.log_manager.warning("LiveモードAPIコールは実装されていません (read_document)。Demoモードの動作を返します。", context=log_ctx)
                # Liveモード未実装時のフォールバックとしてDemoモードの動作を模擬（または専用エラー）
                return None, {"message": "LiveモードAPIコール未実装。", "code": "NOT_IMPLEMENTED_LIVE_API"}
            except FileNotFoundError:
                self.log_manager.error(f"ファイルが見つかりません: {file_path}", context=log_ctx, error_code="FILE_NOT_FOUND")
                return None, {"message": f"ファイルが見つかりません: {file_path}", "code": "FILE_NOT_FOUND"}
            # except requests.exceptions.HTTPError as e_http: ...
            # except requests.exceptions.RequestException as e_req: ...
            except Exception as e:
                self.log_manager.error(f"予期せぬエラー (read_document Live): {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
                return None, {"message": f"予期せぬエラー: {str(e)}", "code": "UNEXPECTED_ERROR_READ_DOC_LIVE"}


    def make_searchable_pdf(self, file_path):
        file_name = os.path.basename(file_path)
        # ★ self.dummy_mode を self.api_execution_mode == "demo" に変更
        if self.api_execution_mode == "demo":
            log_ctx = "API_DUMMY_PDF"
            self.log_manager.info(f"'/make-searchable-pdf' Demoモード呼び出し開始: {file_name}", context=log_ctx)
            time.sleep(random.uniform(0.1, 0.3))
            if file_name.startswith("pdf_error_"):
                error_msg = f"Demo PDF作成エラー: {file_name}"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_PDF_ERROR", filename=file_name)
                return None, {"message": error_msg, "code": "DUMMY_PDF_ERROR", "detail": "DemoモードでのPDF作成エラーです。"}
            try:
                writer = PdfWriter()
                try: writer.add_blank_page(width=595, height=842)
                except TypeError: writer.add_blank_page()
                with io.BytesIO() as bytes_stream:
                    writer.write(bytes_stream)
                    dummy_pdf_content = bytes_stream.getvalue()
                self.log_manager.info(f"'/make-searchable-pdf' Demoモード呼び出し完了: {file_name}", context=log_ctx)
                return dummy_pdf_content, None
            except Exception as e:
                error_msg = f"Demo PDF生成エラー: {file_name}, Error: {e}"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_PDF_GEN_ERROR", filename=file_name, exc_info=True)
                return None, {"message": error_msg, "code": "DUMMY_PDF_GEN_ERROR", "detail": str(e)}
        else: # Liveモード
            log_ctx = "API_LIVE_PDF"
            self.log_manager.info(f"'/make-searchable-pdf' LiveモードAPI呼び出し開始: {file_name}", context=log_ctx)
            try:
                url = self._get_full_url("make_searchable_pdf")
            except ValueError as e_val:
                return None, e_val.args[0] if e_val.args and isinstance(e_val.args[0], dict) else \
                       {"message": str(e_val), "code": "CONFIG_ERROR_UNKNOWN_PDF"}

            if not self.api_key:
                err_msg = "APIキーが設定されていません (Liveモード)。"
                self.log_manager.error(err_msg, context=log_ctx, error_code="API_KEY_MISSING_PDF_LIVE")
                return None, {"message": err_msg, "code": "API_KEY_MISSING_PDF_LIVE"}

            headers = {"apikey": self.api_key}
            self.log_manager.info(f"  URL: {url}", context=log_ctx)
            self.log_manager.info(f"  ヘッダーキー: {list(headers.keys())}", context=log_ctx)
            try:
                # ここに実際の requests.post(...) 呼び出しが入る
                # with open(file_path, 'rb') as f:
                #     files = {'document': (file_name, f, 'application/octet-stream')}
                #     response = requests.post(url, headers=headers, files=files, timeout=300)
                #     response.raise_for_status()
                #     return response.content, None
                self.log_manager.warning("LiveモードAPIコールは実装されていません (make_searchable_pdf)。Demoモードの動作を返します。", context=log_ctx)
                return None, {"message": "LiveモードAPIコール未実装。", "code": "NOT_IMPLEMENTED_LIVE_API_PDF"}
            except FileNotFoundError:
                self.log_manager.error(f"ファイルが見つかりません: {file_path}", context=log_ctx, error_code="FILE_NOT_FOUND_PDF")
                return None, {"message": f"ファイルが見つかりません: {file_path}", "code": "FILE_NOT_FOUND_PDF"}
            # except requests.exceptions.HTTPError as e_http: ...
            # except requests.exceptions.RequestException as e_req: ...
            except Exception as e:
                self.log_manager.error(f"予期せぬエラー (make_searchable_pdf Live): {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
                return None, {"message": f"予期せぬエラー (PDF Live): {str(e)}", "code": "UNEXPECTED_ERROR_PDF_LIVE"}

    def update_config(self, new_config: dict): # ★ MainWindowから新しいconfigを受け取るメソッド
        """ApiClientが保持するconfigオブジェクトと関連属性を更新する"""
        self.log_manager.info("ApiClient: Updating internal config.", context="API_CLIENT_CONFIG_UPDATE")
        self.config = new_config
        self.api_execution_mode = self.config.get("api_execution_mode", "demo")
        self.api_key = self.config.get("api_key")
        self.base_uri = self.config.get("base_uri", "")
        api_type = self.config.get("api_type", "cube_fullocr")
        self.endpoints = self.config.get("endpoints", {}).get(api_type, {})

        if self.api_execution_mode == "live":
            self.log_manager.info("CubeApiClientは Liveモード に更新されました。", context="API_CLIENT_CONFIG_UPDATE")
        else:
            self.log_manager.info("CubeApiClientは Demoモード に更新されました。", context="API_CLIENT_CONFIG_UPDATE")