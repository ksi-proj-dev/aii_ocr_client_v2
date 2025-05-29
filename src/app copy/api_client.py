import os
import time
import json
import random
import shutil 
# import requests # 実際のAPIコール時に必要
from log_manager import LogLevel 
from PyPDF2 import PdfWriter # ★ PyPDF2 をインポート
import io # ★ io をインポート

class CubeApiClient:
    def __init__(self, config, log_manager):
        self.config = config
        self.log_manager = log_manager
        self.api_key = self.config.get("api_key")
        self.base_uri = self.config.get("base_uri", "")
        api_type = self.config.get("api_type", "cube_fullocr")
        self.endpoints = self.config.get("endpoints", {}).get(api_type, {})

        self.dummy_mode = True 
        if self.dummy_mode:
            self.log_manager.info("CubeApiClientはダミーモードで動作します。", context="API_CLIENT_INIT")
        else:
            self.log_manager.info("CubeApiClientは実際のAPIモードで動作します。", context="API_CLIENT_INIT")


    def _get_full_url(self, endpoint_key):
        endpoint_path = self.endpoints.get(endpoint_key)
        if not endpoint_path:
            err_msg = f"エンドポイントキー '{endpoint_key}' が設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            raise ValueError(err_msg)
        if not self.base_uri:
            err_msg = "ベースURIが設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            raise ValueError(err_msg)
        return self.base_uri.rstrip('/') + endpoint_path

    def read_document(self, file_path):
        file_name = os.path.basename(file_path)
        api_type_key = self.config.get("api_type", "cube_fullocr")
        ocr_options_from_config = self.config.get("options", {}).get(api_type_key, {})
        
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


        if self.dummy_mode:
            log_ctx = "API_DUMMY_READ"
            self.log_manager.info(f"'/fullocr-read-document' ダミー呼び出し開始: {file_name}", context=log_ctx, options=actual_ocr_params)
            time.sleep(random.uniform(0.2, 0.5)) # 時間短縮

            if False: # random.random() < 0.1: # ダミーエラー無効化
                error_msg = f"ダミーエラー: {file_name} のOCR処理に失敗しました。"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_OCR_ERROR", filename=file_name)
                return None, {"error_code": "DUMMY_OCR_ERROR", "message": error_msg}

            page_result = {
                "page": 0,
                "result": {
                    "aGroupingFulltext": f"ダミー aGroupingFulltext for {file_name} (Page 1)",
                    "deskewAngle": round(random.uniform(-1, 1), 2),
                    "fileName": file_name,
                    "fulltext": f"これは {file_name} のダミーOCR結果です。\nモデル: {actual_ocr_params.get('horizontal_ocr_model')}\n結合: {actual_ocr_params.get('concatenate')}",
                    "results": [{"text": f"ダミーテキスト1 from {file_name}", "bbox": {}, "ocrConfidence": 0.95, "detectConfidence": 0.99, "vertices": [], "characters": []}],
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
                simplified_result = {
                    "page": page_result["page"],
                    "result": {"fulltext": page_result["result"]["fulltext"], "fileName": file_name},
                    "status": page_result["status"]
                }
                response_data = [simplified_result]

            self.log_manager.info(f"'/fullocr-read-document' ダミー呼び出し完了: {file_name}", context=log_ctx)
            return response_data, None
        else:
            log_ctx = "API_CALL_READ"
            self.log_manager.info(f"'/fullocr-read-document' API呼び出し開始: {file_name}", context=log_ctx)
            try:
                url = self._get_full_url("read_document")
            except ValueError as e:
                return None, {"error_code": "CONFIG_ERROR", "message": str(e)}

            headers = {}
            if self.api_key: headers["apikey"] = self.api_key

            self.log_manager.info(f"  URL: {url}", context=log_ctx)
            self.log_manager.info(f"  ヘッダーキー: {list(headers.keys())}", context=log_ctx)
            self.log_manager.info(f"  OCRパラメータ: {actual_ocr_params}", context=log_ctx)

            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (file_name, f, 'application/octet-stream')}
                    # response = requests.post(url, headers=headers, files=files, data=actual_ocr_params, timeout=180)
                    # self.log_manager.info(f"  API応答ステータス: {response.status_code}", context=log_ctx, filename=file_name)
                    # if not response.ok:
                    #     self.log_manager.error(f"  APIエラーレスポンス (ステータス {response.status_code})", context=log_ctx, filename=file_name, response_text=response.text[:500])
                    # response.raise_for_status()
                    # return response.json(), None
                    self.log_manager.info("実際のAPIコールはコメントアウトされています (read_document)。", context=log_ctx)
                    return None, {"error_code": "NOT_IMPLEMENTED", "message": "実際のAPIコールは未実装です。"}
            except FileNotFoundError:
                self.log_manager.error(f"ファイルが見つかりません: {file_path}", context=log_ctx, error_code="FILE_NOT_FOUND")
                return None, {"error_code": "FILE_NOT_FOUND", "message": f"ファイルが見つかりません: {file_path}"}
            # except requests.exceptions.RequestException as e:
            #     self.log_manager.error(f"APIリクエスト例外: {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
            #     err_resp = {"error_code": "API_REQUEST_ERROR", "message": str(e)}
            #     if hasattr(e, 'response') and e.response is not None: err_resp["status_code"] = e.response.status_code
            #     return None, err_resp
            except Exception as e:
                self.log_manager.error(f"予期せぬエラー: {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
                return None, {"error_code": "UNEXPECTED_ERROR", "message": str(e)}


    def make_searchable_pdf(self, file_path):
        file_name = os.path.basename(file_path)
        if self.dummy_mode:
            log_ctx = "API_DUMMY_PDF"
            self.log_manager.info(f"'/make-searchable-pdf' ダミー呼び出し開始: {file_name}", context=log_ctx)
            time.sleep(random.uniform(0.2, 0.5))

            if False: # ダミーエラー無効化
                error_msg = f"ダミーエラー: {file_name} のサーチャブルPDF作成に失敗。"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_PDF_ERROR", filename=file_name)
                return None, {"error_code": "DUMMY_PDF_ERROR", "message": error_msg}
            
            try:
                writer = PdfWriter()
                # A4サイズのポイント数 (72 DPI)
                # PyPDF2のバージョンによってはadd_blank_pageのwidth/heightが必須
                try:
                    writer.add_blank_page(width=595, height=842) # A4 portrait in points
                except TypeError: # 古いPyPDF2では引数なしで動く場合がある
                    writer.add_blank_page() 
                
                with io.BytesIO() as bytes_stream:
                    writer.write(bytes_stream)
                    dummy_pdf_content = bytes_stream.getvalue()
                
                self.log_manager.info(f"'/make-searchable-pdf' ダミー呼び出し完了 (有効なPDF生成): {file_name}", context=log_ctx)
                return dummy_pdf_content, None
            except Exception as e:
                error_msg = f"ダミーPDF生成エラー: {file_name}, Error: {e}"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_PDF_GEN_ERROR", filename=file_name, exc_info=True)
                return None, {"error_code": "DUMMY_PDF_GEN_ERROR", "message": error_msg}
        else:
            log_ctx = "API_CALL_PDF"
            self.log_manager.info(f"'/make-searchable-pdf' API呼び出し開始: {file_name}", context=log_ctx)
            try:
                url = self._get_full_url("make_searchable_pdf")
            except ValueError as e:
                return None, {"error_code": "CONFIG_ERROR", "message": str(e)}

            headers = {}
            if self.api_key: headers["apikey"] = self.api_key

            self.log_manager.info(f"  URL: {url}", context=log_ctx)
            self.log_manager.info(f"  ヘッダーキー: {list(headers.keys())}", context=log_ctx)

            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (file_name, f, 'application/octet-stream')}
                    # response = requests.post(url, headers=headers, files=files, timeout=300)
                    # self.log_manager.info(f"  API応答ステータス: {response.status_code}", context=log_ctx, filename=file_name)
                    # if not response.ok:
                    #     self.log_manager.error(f"  APIエラーレスポンス (ステータス {response.status_code})", context=log_ctx, filename=file_name, response_text=response.text[:200])
                    # response.raise_for_status()
                    # return response.content, None
                    self.log_manager.info("実際のAPIコールはコメントアウトされています (make_searchable_pdf)。", context=log_ctx)
                    return None, {"error_code": "NOT_IMPLEMENTED", "message": "実際のAPIコールは未実装です。"}
            except FileNotFoundError:
                self.log_manager.error(f"ファイルが見つかりません: {file_path}", context=log_ctx, error_code="FILE_NOT_FOUND")
                return None, {"error_code": "FILE_NOT_FOUND", "message": f"ファイルが見つかりません: {file_path}"}
            # except requests.exceptions.RequestException as e:
            #     self.log_manager.error(f"APIリクエスト例外: {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
            #     err_resp = {"error_code": "API_REQUEST_ERROR", "message": str(e)}
            #     if hasattr(e, 'response') and e.response is not None: err_resp["status_code"] = e.response.status_code
            #     return None, err_resp
            except Exception as e:
                self.log_manager.error(f"予期せぬエラー: {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
                return None, {"error_code": "UNEXPECTED_ERROR", "message": str(e)}