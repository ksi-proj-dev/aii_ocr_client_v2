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
            # ★ エラー情報を辞書で返すように変更
            raise ValueError({"message": err_msg, "code": "CONFIG_ENDPOINT_MISSING"})
        if not self.base_uri:
            err_msg = "ベースURIが設定されていません。"
            self.log_manager.error(err_msg, context="API_CLIENT_CONFIG")
            raise ValueError({"message": err_msg, "code": "CONFIG_BASE_URI_MISSING"})
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
            time.sleep(random.uniform(0.1, 0.3)) # 時間調整

            # ★ ダミーエラーのシミュレーションを少し変更
            if file_name.startswith("error_"): # 特定のファイル名でエラーを発生させる
                error_code_map = {
                    "error_auth": "DUMMY_AUTH_ERROR",
                    "error_server": "DUMMY_SERVER_ERROR",
                    "error_bad_request": "DUMMY_BAD_REQUEST",
                }
                error_message_map = {
                    "error_auth": f"ダミー認証エラー: {file_name}",
                    "error_server": f"ダミーサーバーエラー: {file_name}",
                    "error_bad_request": f"ダミー不正リクエスト: {file_name}",
                }
                simulated_error_type = file_name.split("_")[1] if "_" in file_name else "generic"
                
                error_code = error_code_map.get(f"error_{simulated_error_type}", "DUMMY_OCR_ERROR")
                error_msg = error_message_map.get(f"error_{simulated_error_type}", f"ダミーOCRエラー: {file_name}")
                
                self.log_manager.error(error_msg, context=log_ctx, error_code=error_code, filename=file_name)
                # ★ エラー情報を辞書で返す
                return None, {"message": error_msg, "code": error_code, "detail": "これはダミーモードでシミュレートされたエラーです。"}

            page_result = {
                "page": 0,
                "result": {
                    "aGroupingFulltext": f"ダミー aGroupingFulltext for {file_name} (Page 1)",
                    "deskewAngle": round(random.uniform(-1, 1), 2),
                    "fileName": file_name,
                    "fulltext": f"これは {file_name} のダミーOCR結果です。\nモデル: {actual_ocr_params.get('horizontal_ocr_model')}\n結合: {actual_ocr_params.get('concatenate')}",
                    "results": [{"text": f"ダミーテキスト1 from {file_name}", "bbox": {}, "ocrConfidence": 0.95, "detectConfidence": 0.99, "vertices": [], "characters": []}],
                    "tables": [], "textGroups": []
                }, "status": "success" # API仕様書にはstatusフィールドの記載はないが、便宜上
            }
            if actual_ocr_params.get('character_extraction') == 1:
                if page_result["result"]["results"]:
                    for res_item in page_result["result"]["results"]:
                        if res_item.get("text"):
                            for i, char_text in enumerate(list(res_item["text"])):
                                res_item["characters"].append({"char": char_text, "ocrConfidence": 0.8, "bbox": {}, "vertices": []})

            response_data = [page_result] # API仕様書ではページ単位の情報の配列
            if actual_ocr_params.get('fulltext') == 1: 
                # API仕様書に基づくと、fulltext=1の場合はfileNameとfulltextのみになることが多い
                # ここでは簡略化のため、既存の構造から一部を抽出する形にする
                simplified_result_data = []
                for page in response_data:
                    simplified_page = {
                        "page": page.get("page"),
                        "result": {
                            "fileName": page.get("result", {}).get("fileName"),
                            "fulltext": page.get("result", {}).get("fulltext")
                        }
                        # "status" はAPI仕様書に明記されていないため、ここでは含めないか検討
                    }
                    simplified_result_data.append(simplified_page)
                response_data = simplified_result_data


            self.log_manager.info(f"'/fullocr-read-document' ダミー呼び出し完了: {file_name}", context=log_ctx)
            return response_data, None # 成功時はエラー情報なし
        else: # 実際のAPI呼び出し部分 (現状コメントアウト)
            log_ctx = "API_CALL_READ"
            self.log_manager.info(f"'/fullocr-read-document' API呼び出し開始: {file_name}", context=log_ctx)
            try:
                url = self._get_full_url("read_document")
            except ValueError as e_val: # _get_full_url が辞書でエラーを返すように変更した場合
                return None, e_val.args[0] if e_val.args and isinstance(e_val.args[0], dict) else \
                       {"message": str(e_val), "code": "CONFIG_ERROR_UNKNOWN"}


            if not self.api_key: # ★ APIキーのチェック
                err_msg = "APIキーが設定されていません。"
                self.log_manager.error(err_msg, context=log_ctx, error_code="API_KEY_MISSING")
                return None, {"message": err_msg, "code": "API_KEY_MISSING"}

            headers = {"apikey": self.api_key} # APIキーをヘッダーに設定

            self.log_manager.info(f"  URL: {url}", context=log_ctx)
            self.log_manager.info(f"  ヘッダーキー: {list(headers.keys())}", context=log_ctx)
            self.log_manager.info(f"  OCRパラメータ: {actual_ocr_params}", context=log_ctx)

            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (file_name, f, 'application/octet-stream')} # MIMEタイプはAPI仕様に合わせる
                    # response = requests.post(url, headers=headers, files=files, data=actual_ocr_params, timeout=180) # 例: 180秒タイムアウト
                    # self.log_manager.info(f"  API応答ステータス: {response.status_code}", context=log_ctx, filename=file_name)
                    # response.raise_for_status() # 200番台以外は例外発生
                    # return response.json(), None
                    self.log_manager.info("実際のAPIコールはコメントアウトされています (read_document)。", context=log_ctx)
                    # ★ 未実装エラーも辞書で返す
                    return None, {"message": "実際のAPIコールは未実装です。", "code": "NOT_IMPLEMENTED_API_CALL"}
            except FileNotFoundError:
                self.log_manager.error(f"ファイルが見つかりません: {file_path}", context=log_ctx, error_code="FILE_NOT_FOUND")
                return None, {"message": f"ファイルが見つかりません: {file_path}", "code": "FILE_NOT_FOUND"}
            # except requests.exceptions.HTTPError as e_http:
            #     err_msg = f"API HTTPエラー: {e_http.response.status_code} - {e_http.response.reason}"
            #     err_detail = e_http.response.text[:500] # レスポンスボディの先頭500文字
            #     self.log_manager.error(f"{err_msg}. Detail: {err_detail}", context=log_ctx, filename=file_name, exception_info=e_http, status_code=e_http.response.status_code)
            #     return None, {"message": err_msg, "code": f"API_HTTP_{e_http.response.status_code}", "detail": err_detail}
            # except requests.exceptions.RequestException as e_req:
            #     self.log_manager.error(f"APIリクエスト例外: {str(e_req)}", context=log_ctx, filename=file_name, exception_info=e_req)
            #     return None, {"message": f"APIリクエストエラー: {str(e_req)}", "code": "API_REQUEST_ERROR"}
            except Exception as e: # その他の予期せぬエラー
                self.log_manager.error(f"予期せぬエラー (read_document): {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
                return None, {"message": f"予期せぬエラー: {str(e)}", "code": "UNEXPECTED_ERROR_READ_DOC"}


    def make_searchable_pdf(self, file_path):
        file_name = os.path.basename(file_path)
        if self.dummy_mode:
            log_ctx = "API_DUMMY_PDF"
            self.log_manager.info(f"'/make-searchable-pdf' ダミー呼び出し開始: {file_name}", context=log_ctx)
            time.sleep(random.uniform(0.1, 0.3))

            if file_name.startswith("pdf_error_"): # 特定のファイル名でエラー
                error_msg = f"ダミーPDF作成エラー: {file_name}"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_PDF_ERROR", filename=file_name)
                return None, {"message": error_msg, "code": "DUMMY_PDF_ERROR", "detail": "ダミーモードでのPDF作成エラーです。"}
            
            try: # ダミーPDF生成
                writer = PdfWriter()
                try:
                    writer.add_blank_page(width=595, height=842)
                except TypeError:
                    writer.add_blank_page()
                
                with io.BytesIO() as bytes_stream:
                    writer.write(bytes_stream)
                    dummy_pdf_content = bytes_stream.getvalue()
                
                self.log_manager.info(f"'/make-searchable-pdf' ダミー呼び出し完了 (有効なPDF生成): {file_name}", context=log_ctx)
                return dummy_pdf_content, None
            except Exception as e:
                error_msg = f"ダミーPDF生成エラー: {file_name}, Error: {e}"
                self.log_manager.error(error_msg, context=log_ctx, error_code="DUMMY_PDF_GEN_ERROR", filename=file_name, exc_info=True)
                return None, {"message": error_msg, "code": "DUMMY_PDF_GEN_ERROR", "detail": str(e)}
        else: # 実際のAPI呼び出し
            log_ctx = "API_CALL_PDF"
            self.log_manager.info(f"'/make-searchable-pdf' API呼び出し開始: {file_name}", context=log_ctx)
            try:
                url = self._get_full_url("make_searchable_pdf")
            except ValueError as e_val:
                return None, e_val.args[0] if e_val.args and isinstance(e_val.args[0], dict) else \
                       {"message": str(e_val), "code": "CONFIG_ERROR_UNKNOWN_PDF"}

            if not self.api_key:
                err_msg = "APIキーが設定されていません。"
                self.log_manager.error(err_msg, context=log_ctx, error_code="API_KEY_MISSING_PDF")
                return None, {"message": err_msg, "code": "API_KEY_MISSING_PDF"}

            headers = {"apikey": self.api_key}

            self.log_manager.info(f"  URL: {url}", context=log_ctx)
            self.log_manager.info(f"  ヘッダーキー: {list(headers.keys())}", context=log_ctx)

            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (file_name, f, 'application/octet-stream')}
                    # response = requests.post(url, headers=headers, files=files, timeout=300) # 例: 300秒タイムアウト
                    # self.log_manager.info(f"  API応答ステータス: {response.status_code}", context=log_ctx, filename=file_name)
                    # response.raise_for_status()
                    # return response.content, None
                    self.log_manager.info("実際のAPIコールはコメントアウトされています (make_searchable_pdf)。", context=log_ctx)
                    return None, {"message": "実際のAPIコールは未実装です。", "code": "NOT_IMPLEMENTED_API_CALL_PDF"}
            except FileNotFoundError:
                self.log_manager.error(f"ファイルが見つかりません: {file_path}", context=log_ctx, error_code="FILE_NOT_FOUND_PDF")
                return None, {"message": f"ファイルが見つかりません: {file_path}", "code": "FILE_NOT_FOUND_PDF"}
            # except requests.exceptions.HTTPError as e_http:
            #     err_msg = f"API HTTPエラー (PDF): {e_http.response.status_code} - {e_http.response.reason}"
            #     err_detail = e_http.response.text[:200] # レスポンスボディの先頭
            #     self.log_manager.error(f"{err_msg}. Detail: {err_detail}", context=log_ctx, filename=file_name, exception_info=e_http, status_code=e_http.response.status_code)
            #     return None, {"message": err_msg, "code": f"API_HTTP_PDF_{e_http.response.status_code}", "detail": err_detail}
            # except requests.exceptions.RequestException as e_req:
            #     self.log_manager.error(f"APIリクエスト例外 (PDF): {str(e_req)}", context=log_ctx, filename=file_name, exception_info=e_req)
            #     return None, {"message": f"APIリクエストエラー (PDF): {str(e_req)}", "code": "API_REQUEST_ERROR_PDF"}
            except Exception as e:
                self.log_manager.error(f"予期せぬエラー (make_searchable_pdf): {str(e)}", context=log_ctx, filename=file_name, exception_info=e)
                return None, {"message": f"予期せぬエラー (PDF): {str(e)}", "code": "UNEXPECTED_ERROR_PDF"}