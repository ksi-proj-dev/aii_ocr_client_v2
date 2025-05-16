import os
import time
import json
import random
# import requests # 実際のAPIコール時に必要

class CubeApiClient:
    def __init__(self, config, log_manager):
        self.config = config
        self.log_manager = log_manager
        self.api_key = self.config.get("api_key")
        self.base_uri = self.config.get("base_uri", "")
        api_type = self.config.get("api_type", "cube_fullocr")
        self.endpoints = self.config.get("endpoints", {}).get(api_type, {})

        self.dummy_mode = True  # Trueにするとダミーレスポンスを返す
        if self.dummy_mode:
            self.log_manager.log_message("CubeApiClientはダミーモードで動作します。")

    def _get_full_url(self, endpoint_key):
        """エンドポイントキーから完全なURLを生成する"""
        endpoint_path = self.endpoints.get(endpoint_key)
        if not endpoint_path:
            raise ValueError(f"エンドポイントキー '{endpoint_key}' が設定されていません。")
        if not self.base_uri:
            raise ValueError("ベースURIが設定されていません。")
        return self.base_uri.rstrip('/') + endpoint_path

    def read_document(self, file_path):
        """
        全文OCR（JSON結果）をリクエストする。
        :param file_path: OCR対象のファイルパス
        :return: (レスポンスJSON, エラー情報dict) or (None, エラー情報dict)
        """
        file_name = os.path.basename(file_path)
        api_type = self.config.get("api_type", "cube_fullocr") # "cube_fullocr"
        # option_dialog.pyで設定されたオプションを取得
        ocr_options = self.config.get("options", {}).get(api_type, {})


        if self.dummy_mode:
            self.log_manager.log_message(f"[DUMMY] '/fullocr-read-document' 開始: {file_name} (オプション: {ocr_options})")
            time.sleep(random.uniform(0.5, 1.5)) # 処理時間をシミュレート

            # ダミーレスポンス生成 (Cube API仕様書 P.2-5 参照)
            # 稀にエラーを発生させる
            if random.random() < 0.1: # 10%の確率でダミーエラー
                error_msg = f"ダミーエラー: {file_name} の処理に失敗しました。"
                self.log_manager.log_message(f"[DUMMY] '/fullocr-read-document' エラー: {error_msg}")
                return None, {"error_code": "DUMMY_PROCESSING_ERROR", "message": error_msg}

            # 1ページ分のダミー結果
            page_result = {
                "page": 0,
                "result": {
                    "aGroupingFulltext": f"ダミー aGroupingFulltext for {file_name} (Page 1)",
                    "deskewAngle": round(random.uniform(-1, 1), 2),
                    "fileName": file_name,
                    "fulltext": f"これは {file_name} のダミーOCR結果です。\n" \
                                f"回転補正: {ocr_options.get('adjust_rotation')}\n" \
                                f"文字抽出: {ocr_options.get('character_extraction')}\n" \
                                f"強制結合: {ocr_options.get('concatenate')}\n" \
                                f"チェックボックス: {ocr_options.get('enable_checkbox')}\n" \
                                f"テキストモード: {ocr_options.get('fulltext_output_mode')}\n" \
                                f"改行文字: {ocr_options.get('fulltext_linebreak_char')}\n" \
                                f"OCRモデル: {ocr_options.get('ocr_model')}\n" \
                                f"これは複数行のテキストです。\nサンプル株式会社\n請求書",
                    "results": [
                        {
                            "text": "サンプル株式会社",
                            "bbox": {"top": 0.1, "bottom": 0.15, "left": 0.1, "right": 0.5},
                            "ocrConfidence": round(random.uniform(0.8, 1.0), 4),
                            "detectConfidence": round(random.uniform(0.9, 1.0), 4),
                            "vertices": [{"x":0.1,"y":0.1},{"x":0.5,"y":0.1},{"x":0.5,"y":0.15},{"x":0.1,"y":0.15}],
                            "characters": []
                        },
                        {
                            "text": "請求書",
                            "bbox": {"top": 0.2, "bottom": 0.25, "left": 0.4, "right": 0.6},
                            "ocrConfidence": round(random.uniform(0.7, 1.0), 4),
                            "detectConfidence": round(random.uniform(0.85, 1.0), 4),
                            "vertices": [{"x":0.4,"y":0.2},{"x":0.6,"y":0.2},{"x":0.6,"y":0.25},{"x":0.4,"y":0.25}],
                            "characters": []
                        }
                    ],
                    "tables": [], # 必要に応じてダミーテーブルデータも追加
                    "textGroups": [ # textGroupsのダミー例
                        {
                            "allText": "サンプル株式会社\n請求書",
                            "isTable": False,
                            "texts": [
                                {"text": "サンプル株式会社", "bbox": {"top": 0.1, "bottom": 0.15, "left": 0.1, "right": 0.5}, "characters": [], "ocrConfidence": 0.95, "detectConfidence": 0.99, "vertices": []},
                                {"text": "請求書", "bbox": {"top": 0.2, "bottom": 0.25, "left": 0.4, "right": 0.6}, "characters": [], "ocrConfidence": 0.90, "detectConfidence": 0.98, "vertices": []}
                            ]
                        }
                    ]
                },
                "status": "success"
            }
            # character_extractionが1の場合、charactersにダミーデータを追加
            if ocr_options.get('character_extraction', 0) == 1:
                for res_item in page_result["result"]["results"]:
                    for i, char_text in enumerate(list(res_item["text"])):
                        char_bbox_width = (res_item["bbox"]["right"] - res_item["bbox"]["left"]) / len(res_item["text"])
                        char_left = res_item["bbox"]["left"] + i * char_bbox_width
                        char_right = char_left + char_bbox_width
                        res_item["characters"].append({
                            "char": char_text,
                            "ocrConfidence": round(random.uniform(0.6, 1.0), 4),
                            "bbox": {"top": res_item["bbox"]["top"], "bottom": res_item["bbox"]["bottom"], "left": char_left, "right": char_right},
                            "vertices": [] # 必要なら頂点座標も
                        })

            # fulltext_output_mode が 1 (fulltextのみ) の場合、一部フィールドを削除して模倣
            if ocr_options.get('fulltext_output_mode', 0) == 1:
                simplified_result = {
                    "page": page_result["page"],
                    "result": {
                        "fulltext": page_result["result"]["fulltext"],
                        "fileName": page_result["result"]["fileName"] # fileNameは残るか確認
                    },
                    "status": page_result["status"]
                }
                response_data = [simplified_result]
            else:
                response_data = [page_result] # PDFはマルチページを想定しないが、API仕様は配列

            self.log_manager.log_message(f"[DUMMY] '/fullocr-read-document' 完了: {file_name}")
            return response_data, None
        else:
            # --- 実際のAPIコール (requestsライブラリが必要) ---
            self.log_manager.log_message(f"'/fullocr-read-document' API呼び出し開始: {file_name}")
            try:
                url = self._get_full_url("read_document")
            except ValueError as e:
                self.log_manager.log_message(f"API呼び出しエラー: {e}")
                return None, {"error_code": "CONFIG_ERROR", "message": str(e)}

            headers = {}
            if self.api_key:
                headers["apikey"] = self.api_key # Cube APIの認証ヘッダー名に合わせてください

            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (file_name, f, 'application/octet-stream')} # MIMEタイプは適宜調整
                    
                    # API仕様に合わせたパラメータ名でdataを作成
                    data_params = {
                        'adjust_rotation': ocr_options.get('adjust_rotation'),
                        'character_extraction': ocr_options.get('character_extraction'),
                        'concatenate': ocr_options.get('concatenate'),
                        'enable_checkbox': ocr_options.get('enable_checkbox'),
                        'fulltext': ocr_options.get('fulltext_output_mode'), # API仕様書のパラメータ名 'fulltext'
                        'fulltext_linebreak': ocr_options.get('fulltext_linebreak_char'), # API仕様書のパラメータ名 'fulltext_linebreak'
                        'horizontal_ocr_model': ocr_options.get('ocr_model') # API仕様書のパラメータ名 'horizontal_ocr_model'
                    }
                    # Noneの値を送らないようにフィルタリング (API仕様による)
                    data = {k: v for k, v in data_params.items() if v is not None}

                    # response = requests.post(url, headers=headers, files=files, data=data, timeout=180) # 例: タイムアウト3分
                    # response.raise_for_status() # エラーがあればHTTPErrorを送出
                    # self.log_manager.log_message(f"'/fullocr-read-document' API呼び出し成功: {file_name}, Status: {response.status_code}")
                    # return response.json(), None
                    self.log_manager.log_message("実際のAPIコールはコメントアウトされています。")
                    return None, {"error_code": "NOT_IMPLEMENTED", "message": "実際のAPIコールは未実装です。"}


            except FileNotFoundError:
                self.log_manager.log_message(f"API呼び出しエラー: ファイルが見つかりません - {file_path}")
                return None, {"error_code": "FILE_NOT_FOUND", "message": f"ファイルが見つかりません: {file_path}"}
            # except requests.exceptions.RequestException as e:
            #     self.log_manager.log_message(f"'/fullocr-read-document' API呼び出しエラー: {e}")
            #     # エラーレスポンスの形式はAPI仕様に合わせて調整
            #     error_detail = {"error_code": "API_REQUEST_ERROR", "message": str(e)}
            #     if hasattr(e, 'response') and e.response is not None:
            #         try:
            #             error_detail["response_body"] = e.response.json()
            #             error_detail["status_code"] = e.response.status_code
            #         except json.JSONDecodeError:
            #             error_detail["response_body"] = e.response.text
            #     return None, error_detail
            except Exception as e:
                self.log_manager.log_message(f"'/fullocr-read-document' 予期せぬエラー: {e}")
                return None, {"error_code": "UNEXPECTED_ERROR", "message": str(e)}


    def make_searchable_pdf(self, file_path):
        """
        サーチャブルPDFをリクエストする。
        :param file_path: OCR対象のファイルパス
        :return: (PDFバイナリ, None) or (None, エラー情報dict)
        """
        file_name = os.path.basename(file_path)

        if self.dummy_mode:
            self.log_manager.log_message(f"[DUMMY] '/make-searchable-pdf' 開始: {file_name}")
            time.sleep(random.uniform(1.0, 2.5)) # 処理時間をシミュレート

            if random.random() < 0.05: # 5%の確率でダミーエラー
                error_msg = f"ダミーエラー: {file_name} のサーチャブルPDF作成に失敗しました。"
                self.log_manager.log_message(f"[DUMMY] '/make-searchable-pdf' エラー: {error_msg}")
                return None, {"error_code": "DUMMY_PDF_CREATION_ERROR", "message": error_msg}

            # ダミーのPDFコンテンツ (バイト列)
            dummy_pdf_content = f"%PDF-1.4\n%dummy_pdf_for_{file_name}\n%%EOF".encode('utf-8')
            self.log_manager.log_message(f"[DUMMY] '/make-searchable-pdf' 完了: {file_name}")
            return dummy_pdf_content, None
        else:
            # --- 実際のAPIコール (requestsライブラリが必要) ---
            self.log_manager.log_message(f"'/make-searchable-pdf' API呼び出し開始: {file_name}")
            try:
                url = self._get_full_url("make_searchable_pdf")
            except ValueError as e:
                self.log_manager.log_message(f"API呼び出しエラー: {e}")
                return None, {"error_code": "CONFIG_ERROR", "message": str(e)}

            headers = {}
            if self.api_key:
                headers["apikey"] = self.api_key # Cube APIの認証ヘッダー名に合わせてください

            try:
                with open(file_path, 'rb') as f:
                    files = {'document': (file_name, f, 'application/octet-stream')} # MIMEタイプは適宜調整
                    
                    # response = requests.post(url, headers=headers, files=files, timeout=300) # 例: タイムアウト5分
                    # response.raise_for_status()
                    # self.log_manager.log_message(f"'/make-searchable-pdf' API呼び出し成功: {file_name}, Status: {response.status_code}")
                    # return response.content, None # PDFはバイナリで返る
                    self.log_manager.log_message("実際のAPIコールはコメントアウトされています。")
                    return None, {"error_code": "NOT_IMPLEMENTED", "message": "実際のAPIコールは未実装です。"}

            except FileNotFoundError:
                self.log_manager.log_message(f"API呼び出しエラー: ファイルが見つかりません - {file_path}")
                return None, {"error_code": "FILE_NOT_FOUND", "message": f"ファイルが見つかりません: {file_path}"}
            # except requests.exceptions.RequestException as e:
            #     self.log_manager.log_message(f"'/make-searchable-pdf' API呼び出しエラー: {e}")
            #     error_detail = {"error_code": "API_REQUEST_ERROR", "message": str(e)}
            #     if hasattr(e, 'response') and e.response is not None:
            #         try:
            #             # PDFエラーの場合、レスポンスボディはJSONではないかもしれない
            #             error_detail["response_body"] = e.response.text 
            #             error_detail["status_code"] = e.response.status_code
            #         except Exception:
            #             error_detail["response_body"] = "Failed to decode error response."
            #     return None, error_detail
            except Exception as e:
                self.log_manager.log_message(f"'/make-searchable-pdf' 予期せぬエラー: {e}")
                return None, {"error_code": "UNEXPECTED_ERROR", "message": str(e)}