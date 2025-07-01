# sort_worker.py (修正版)

import os
import time
import json
import random # randomをインポートします
import threading
from typing import Dict, Any, List

from PyQt6.QtCore import QThread, pyqtSignal

# ポーリング設定のデフォルト値
DEFAULT_POLLING_INTERVAL_SECONDS = 3
DEFAULT_POLLING_MAX_ATTEMPTS = 100 # 仕分けは時間がかかる可能性を考慮

class SortWorker(QThread):
    # ステータス更新用のシグナル (例: 「仕分け中...」)
    sort_status_update = pyqtSignal(str)
    # 全処理完了を通知するシグナル (bool: 成功/失敗, object: 結果/エラー情報)
    sort_finished = pyqtSignal(bool, object)

    def __init__(self, api_client, file_paths: List[str], sort_config_id: str, log_manager, input_root_folder: str, config: Dict[str, Any]):
        super().__init__()
        self.api_client = api_client
        self.file_paths = file_paths
        self.sort_config_id = sort_config_id
        self.log_manager = log_manager
        self.input_root_folder = input_root_folder
        self.config = config
        self.is_running = True

    def stop(self):
        """スレッドに停止を要求する"""
        self.is_running = False
        self.log_manager.info("SortWorker停止リクエスト受信。", context="SORT_WORKER_LIFECYCLE")


    def run(self):
        """仕分け処理と後続OCRの監視、結果ダウンロードを含むメインロジック"""
        thread_id = threading.get_ident()
        self.log_manager.info(f"SortWorkerスレッド開始。Thread ID: {thread_id}", context="SORT_WORKER_LIFECYCLE")

        try:
            # === ステージ1: 仕分け処理 ===
            self.sort_status_update.emit("仕分けユニット作成中...")
            add_result, add_error = self.api_client.add_sort_unit(self.file_paths, self.sort_config_id)
            if add_error:
                self.sort_finished.emit(False, add_error)
                return

            sort_unit_id = add_result.get("sortUnitId")
            if not sort_unit_id:
                self.sort_finished.emit(False, {"message": "レスポンスにsortUnitIdが含まれていません。", "code": "NO_SORT_UNIT_ID"})
                return
            
            self.log_manager.info(f"仕分けユニット作成成功。sortUnitId: {sort_unit_id}", context="SORT_WORKER_INFO")

            last_status_result = None
            for attempt in range(DEFAULT_POLLING_MAX_ATTEMPTS):
                if not self.is_running:
                    self.sort_finished.emit(False, {"message": "処理がユーザーによって中断されました。", "code": "USER_INTERRUPT"})
                    return

                self.sort_status_update.emit(f"仕分け中... (確認 {attempt + 1}/{DEFAULT_POLLING_MAX_ATTEMPTS})")
                status_result, status_error = self.api_client.get_sort_unit_status(sort_unit_id)

                if status_error:
                    self.sort_finished.emit(False, status_error)
                    return
                
                last_status_result = status_result
                status_code = status_result.get("statusCode")
                status_name = status_result.get("statusName", "")
                self.log_manager.info(f"仕分けステータス: {status_code} ({status_name})", context="SORT_WORKER_POLL")

                if status_code == 60:
                    break
                
                if status_code in [35, 55]:
                    error_info = {"message": f"仕分け処理でエラーが発生しました: {status_name}", "code": f"SORT_API_ERROR_{status_code}"}
                    self.sort_finished.emit(False, error_info)
                    return

                if attempt == DEFAULT_POLLING_MAX_ATTEMPTS - 1:
                    self.sort_finished.emit(False, {"message": "仕分け処理がタイムアウトしました。", "code": "SORT_TIMEOUT"})
                    return
                time.sleep(DEFAULT_POLLING_INTERVAL_SECONDS)

            # === ステージ2: 後続OCR処理 ===
            self.log_manager.info("仕分け処理が正常に完了しました。OCR処理へ送信します...", context="SORT_WORKER_SUCCESS")
            self.sort_status_update.emit("OCR処理へ送信中...")
            send_result, send_error = self.api_client.send_sort_result_to_ocr(sort_unit_id)
            if send_error:
                self.sort_finished.emit(False, send_error)
                return
            
            self.log_manager.info("OCR処理への送信が正常に完了しました。後続OCR処理の監視を開始します。", context="SORT_WORKER_SUCCESS")

            # === 修正箇所 START ===
            ocr_unit_ids_to_poll = []
            if self.api_client.api_execution_mode == "demo":
                self.log_manager.info("SortWorker (Demo Mode): 入力ファイル数に基づいてダミーのOCRユニットを生成します。", context="SORT_WORKER_DEMO")
                num_input_files = len(self.file_paths)
                for i in range(num_input_files):
                    dummy_ocr_unit_id = f"demo-ocr-unit-{random.randint(10000, 99999)}-{i+1}"
                    ocr_unit_ids_to_poll.append(dummy_ocr_unit_id)
            else: # Liveモードの場合
                final_sort_status, _ = self.api_client.get_sort_unit_status(sort_unit_id)
                if final_sort_status and "statusList" in final_sort_status:
                    for item in final_sort_status["statusList"]:
                        unit_id = item.get("readingUnitId")
                        if unit_id and unit_id != "0":
                            ocr_unit_ids_to_poll.append(unit_id)
            # === 修正箇所 END ===


            if not ocr_unit_ids_to_poll:
                self.log_manager.info("仕分け後のOCR対象ユニットがありませんでした。処理を完了します。", context="SORT_WORKER_INFO")
                self.sort_finished.emit(True, {"message": "仕分けは完了しましたが、OCR対象の文書はありませんでした。", "statusName": "OCR対象なし"})
                return

            all_unit_ids_for_download = list(ocr_unit_ids_to_poll) # ダウンロード用に元のリストをコピー
            ocr_polling_attempts = 0
            while ocr_unit_ids_to_poll and self.is_running:
                ocr_polling_attempts += 1
                self.sort_status_update.emit(f"OCR処理中... (残り{len(ocr_unit_ids_to_poll)}件, 確認{ocr_polling_attempts})")
                
                completed_ids_in_this_loop = []
                
                for unit_id in ocr_unit_ids_to_poll:
                    ocr_status_result, ocr_status_error = self.api_client.get_status(unit_id)
                    if ocr_status_error:
                        self.sort_finished.emit(False, ocr_status_error)
                        return

                    if ocr_status_result and ocr_status_result[0].get("dataProcessingStatus") in [400, 600]:
                        self.log_manager.info(f"OCRユニット {unit_id} の処理が完了しました。", context="SORT_WORKER_OCR_POLL")
                        completed_ids_in_this_loop.append(unit_id)

                ocr_unit_ids_to_poll = [uid for uid in ocr_unit_ids_to_poll if uid not in completed_ids_in_this_loop]

                if not ocr_unit_ids_to_poll:
                    break

                time.sleep(DEFAULT_POLLING_INTERVAL_SECONDS)

            if not self.is_running:
                self.sort_finished.emit(False, {"message": "処理がユーザーによって中断されました。", "code": "USER_INTERRUPT"})
                return

            # === ステージ3: 結果ダウンロード ===
            self.log_manager.info("後続のOCR処理が全て完了しました。結果をダウンロードします。", context="SORT_WORKER_SUCCESS")
            self.sort_status_update.emit("結果をダウンロード中...")
            
            file_actions = self.config.get("file_actions", {})
            output_json = file_actions.get("dx_standard_output_json", False)
            output_csv = file_actions.get("dx_standard_auto_download_csv", False)
            results_folder_name = self.config.get("file_actions", {}).get("results_folder_name", "OCR結果")
            output_dir = os.path.join(self.input_root_folder, results_folder_name)
            os.makedirs(output_dir, exist_ok=True)
            
            download_errors = []

            if output_csv:
                combined_csv_header = None
                combined_csv_rows = []

                for unit_id in all_unit_ids_for_download:
                    if not self.is_running: break

                    csv_data_bytes, csv_error = self.api_client.download_standard_csv(unit_id)
                    if csv_error:
                        status_res, _ = self.api_client.get_status(unit_id)
                        unit_name = status_res[0].get("unitName", unit_id) if (status_res and status_res[0]) else unit_id
                        download_errors.append(f"ユニット {unit_name} のCSV取得失敗: {csv_error.get('message')}")
                        continue
                    try:
                        csv_content = csv_data_bytes.decode('utf-8-sig')
                        lines = [line for line in csv_content.splitlines() if line.strip()]
                        if not lines: continue

                        if combined_csv_header is None:
                            combined_csv_header = lines[0]
                        
                        combined_csv_rows.extend(lines[1:])
                    except Exception as e:
                        status_res, _ = self.api_client.get_status(unit_id)
                        unit_name = status_res[0].get("unitName", unit_id) if (status_res and status_res[0]) else unit_id
                        download_errors.append(f"ユニット {unit_name} のCSVデータ解析失敗: {e}")

                if not self.is_running:
                    self.sort_finished.emit(False, {"message": "処理がユーザーによって中断されました。", "code": "USER_INTERRUPT"})
                    return
                
                if combined_csv_header and combined_csv_rows:
                    final_csv_content = combined_csv_header + "\n" + "\n".join(combined_csv_rows)
                    combined_csv_filename = f"仕分け結果_{os.path.basename(os.path.normpath(self.input_root_folder))}.csv"
                    combined_csv_filepath = self._get_unique_filepath(output_dir, combined_csv_filename)
                    try:
                        with open(combined_csv_filepath, 'w', encoding='utf-8-sig', newline='') as f:
                            f.write(final_csv_content)
                        self.log_manager.info(f"結合CSVを正常に保存しました: {combined_csv_filepath}", context="SORT_WORKER_CSV")
                    except Exception as e:
                        download_errors.append(f"結合CSVの保存に失敗: {e}")

            if output_json:
                for unit_id in all_unit_ids_for_download:
                    if not self.is_running: break
                    status_res, _ = self.api_client.get_status(unit_id)
                    unit_name = status_res[0].get("unitName", unit_id) if (status_res and status_res[0]) else unit_id

                    json_data, json_error = self.api_client.get_result(unit_id) # get_resultが正しい
                    if json_error:
                        download_errors.append(f"ユニット {unit_name} のJSON取得失敗: {json_error.get('message')}")
                    else:
                        json_filepath = self._get_unique_filepath(output_dir, f"{unit_name}.json")
                        try:
                            with open(json_filepath, 'w', encoding='utf-8') as f:
                                json.dump(json_data, f, ensure_ascii=False, indent=2)
                        except Exception as e:
                            download_errors.append(f"ユニット {unit_name} のJSON保存失敗: {e}")

            final_message = "仕分けと後続のOCR処理、結果ダウンロードがすべて完了しました。"
            if download_errors:
                final_message = f"処理は完了しましたが、一部のファイルダウンロードに失敗しました。\n\n" + "\n".join(download_errors)
            
            final_payload = {"message": final_message, "statusName": "完了"}
            self.sort_finished.emit(True, final_payload)

        except Exception as e:
            self.log_manager.error(f"SortWorkerで予期せぬエラー: {e}", context="SORT_WORKER_UNEXPECTED_ERROR", exc_info=True)
            self.sort_finished.emit(False, {"message": f"予期せぬエラーが発生しました: {e}", "code": "UNEXPECTED_SORT_WORKER_ERROR"})

    def _get_unique_filepath(self, target_dir: str, filename: str) -> str:
        """ファイル名の衝突を避けるためのヘルパーメソッド"""
        base, ext = os.path.splitext(filename)
        counter = 1
        new_filepath = os.path.join(target_dir, filename)
        while os.path.exists(new_filepath):
            new_filename = f"{base} ({counter}){ext}"
            new_filepath = os.path.join(target_dir, new_filename)
            counter += 1
        return new_filepath